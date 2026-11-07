# Harness 웹 콘솔 설계

`/harness:open` 을 실행하면 로컬 서버와 웹페이지가 뜬다. 웹에서 모든 Claude Code 세션의 상태와 결과를 보고, 승인과 질문에 답하고, 스킬을 실행하고, 새 작업을 시작한다. 사용자는 터미널을 모르는 컨설턴트이고 Windows 와 macOS 모두 지원한다.

표기: **[시험]** 은 CLI 2.1.309, macOS 에서 실제로 확인한 동작이다. Windows 는 CLI 2.1.316, Windows 10 에서 주요 흐름을 시험했고 결과는 `docs/status/558-web-console.md` 에 있다. 아래 **[시험]** 표기는 macOS 기준이다.

## 1. 원칙

- 런타임은 Python 3.12 표준 라이브러리만 쓴다. 플러그인의 기존 Python 훅과 같은 방식(`uv run --no-project python`)으로 실행한다. node 와 외부 패키지를 전제하지 않는다.
- OS 차이는 `console/platform_compat.py` 한 곳에 모은다. `pathlib` 으로 경로를 다루고, 파일과 파이프는 UTF-8 을 명시하고, `shell=True` 를 쓰지 않는다.
- 서버가 꺼져 있어도 일반 세션을 막지 않는다. 검사를 못 한 것을 승인으로 처리하지 않는다.
- 근거 없는 값을 화면에 지어내지 않는다. 시안의 `3/5` 같은 단계 표시는 넣지 않고 실제 이벤트 로그와 현재 스킬 이름을 보여 준다.

## 2. 파일 배치

```
plugins/harness/
  skills/open/SKILL.md      /harness:open. open.py 를 실행하고 결과만 보고한다
  console/
    open.py                 서버가 꺼져 있으면 띄우고, 브라우저를 열게 한다
    server.py               HTTP 서버, 라우팅, 인증, SSE
    store.py                세션·요청 상태, 디스크 저장
    hooks_api.py            /hooks/* 판단 로직
    managed.py              콘솔이 띄운 claude -p 세션 관리
    analysis.py             새 작업 읽기 전용 분석
    gitstate.py             브랜치·변경·PR 로 `이번 차례` 판단, 갈래 진행·승인자 판정용 gh 조회
    devready.py             origin/main 의 SRS·Spec·원장으로 개발 건별 Spec 유무 읽기(새 작업 종류 버튼용, #668)
    flows.py                ../workflow.json(작업 순서 정본) 읽기·검사, 세션의 갈래 진행 상태, 다음 갈래 계산
    platform_compat.py      프로세스 분리, 종료, 경로, claude 실행 파일 찾기
    session_start_hook.py   SessionStart command 훅
    static/                 index.html, app.css, app.js, theme.js, logo-sauce.png (순수 JS, 빌드 없음)
  hooks/hooks.json          훅 추가
```

시험은 저장소의 기존 시험 구성을 따른다. 실제 `claude` 를 부르지 않도록 stream-json 을 흉내 내는 가짜 실행 파일을 쓴다.

## 3. 서버

- 주소는 기본 `127.0.0.1:4873` 이다. 훅이 command 라서 환경변수로 바꿀 수 있지만 사용자는 바꾸지 않는 것을 기본으로 한다. 포트를 다른 프로그램이 쓰고 있으면 `/api/health` 응답으로 구별해 원인을 보고한다.
- `ThreadingHTTPServer` 를 쓴다. 훅 요청이 응답을 오래 붙들기 때문이다. 화면 갱신은 SSE(`/api/events`)로 보낸다.
- 상태 폴더: `CLAUDE_PLUGIN_DATA` → 없으면 `<CLAUDE_CONFIG_DIR 또는 ~/.claude>/harness-console`. `sessions.json` 은 원자적으로 저장한다. 대기 중인 요청은 저장하지 않는다.
- 띄운 프로세스가 끝나도 서버는 살아 있어야 한다. POSIX 는 `start_new_session=True` **[시험]**, Windows 는 콘솔 창이 뜨지 않게 base 인터프리터(`sys._base_executable`) 옆의 `pythonw.exe` 로 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` 을 줘 띄운다. `pythonw.exe` 가 없으면 지금 인터프리터에 `CREATE_NO_WINDOW` 를 준다. `pythonw.exe` 는 stdout·stderr 가 없으므로 서버는 stderr 가 있을 때만 쓴다.
- 끄기: `open.py --stop`. 상태 폴더의 `server.pid`(PID 와 포트)를 읽되, `/api/health` 가 우리 서버라고 답할 때만 종료 신호를 보낸다(옛 기록이 다른 프로세스를 가리킬 수 있어서). 서버가 SIGTERM·SIGINT 를 받으면 세션 저장을 마치고, 콘솔이 띄운 `claude` 프로세스도 stdin 을 닫아 끝낸다(5초 안에 안 끝나면 terminate, 다시 5초 뒤 kill). 서버를 끄면 콘솔이 띄운 세션도 함께 끝난다. `--stop` 은 서버가 응답을 멈춘 뒤에도 포트가 실제로 풀릴 때까지(같은 방식으로 bind 해 보며, 최대 10초) 기다린 다음에야 "껐습니다" 를 낸다. 곧바로 `open.py` 를 다시 실행해도 `OSError 10048` 로 실패하지 않게 하려는 것이다. 시작 쪽도 포트가 사용 중이면 최대 3초 재시도한 뒤 서버를 띄운다(끝내 안 풀리면 서버가 남기는 원인을 보여 준다).
- 환경변수: `HARNESS_CONSOLE_PORT`(기본 4873, 범위 밖이거나 숫자가 아니면 기본값)는 서버·`open.py`·`session_start_hook.py` 가 읽는다. 시험용 임시 포트를 위한 것이다. 훅(`hook_post.py`)도 같은 변수를 읽으므로 Claude Code 를 띄우는 환경에 같은 값이 있어야 훅이 서버에 닿는다. `HARNESS_CONSOLE_MODEL`·`HARNESS_CONSOLE_EFFORT` 는 서버가 띄우는 모든 `claude`(콘솔 세션·새 작업 분석)에 `--model`·`--effort` 의 기본값으로 넘긴다. 비어 있으면 넘기지 않는다. 새 작업 화면에서 고른 값이 있으면 그것이 우선한다(§6 새 작업).

## 4. 인증과 보안

위협은 세 가지다. 세션의 자기 승인, 다른 웹사이트의 호출, 파일 목록 노출.

- 모든 요청의 `Host` 가 `127.0.0.1:4873` 또는 `localhost:4873` 이어야 한다. DNS 리바인딩을 막는다.
- 브라우저 인증: `POST /api/open` 을 받으면 서버가 일회용 토큰(60초 만료)을 만들어 **서버 프로세스에서 직접** 브라우저를 연다. 토큰은 응답 본문과 stdout 에 절대 넣지 않는다. `/auth?t=` 가 토큰을 소비하고 `HttpOnly; SameSite=Strict` 쿠키를 준 뒤 리다이렉트한다.
- `/api/*` 는 쿠키를 요구한다(`/api/open`, `/api/health` 제외). 변경 요청은 `Origin` 이 있으면 자기 주소여야 하고 `Content-Type: application/json` 이어야 한다.
- `/hooks/*`, `/api/open` 은 쿠키 없이 `POST` 로만 받고(그 밖의 메서드는 405) `Origin` 헤더가 있으면 거부하며 JSON 객체만 받는다. 본문 상한은 `/hooks/*` 32MB, 그 밖의 API 1MB(초과 413). `/auth` 의 토큰이 없거나 만료됐으면 403 이다. 이 경로로는 요청을 **만들 수만** 있고 답할 수 없다.
- 파일 탐색 `/api/fs?root=&dir=` 와 `@` 멘션용 `/api/files?root=&q=` 는 `root` 가 최근 작업 폴더 목록이나 세션의 `cwd` 중 하나여야 하고(아니면 403), `dir` 은 그 안이어야 한다. `realpath` 로 벗어남을 검사하고 심볼릭 링크 탈출을 막는다. `/api/files` 는 결과를 50개, 탐색을 2만 파일로 제한하고(넘으면 `truncated`), `.git`·`node_modules` 같은 큰 폴더는 건너뛰며 `q` 는 200자로 자른다.
- `POST /api/folders/pick` 은 서버를 돌리는 컴퓨터에 OS 폴더 선택 창을 띄운다(§8). 쿠키로 인증한 사용자만 부르고, 창은 한 번에 하나만 연다(이미 열려 있으면 409).
- 요청 본문 크기를 제한한다. 화면은 세션 내용을 `textContent` 로만 넣어 XSS 를 막고 CSP 를 건다.
- 한계(문서에 명시): 같은 OS 사용자로 도는 프로세스를 완전히 막지는 못한다.
- 한계(문서에 명시): 세션이 Bash 권한으로 서버를 죽이고 4873 에 가짜 서버를 띄우면 승인을 위조할 수 있다. Claude Code 가 훅이 접속하는 상대를 검증하지 않아 공유 비밀로도 막지 못한다. 다만 이미 그 Bash 권한이 있는 세션은 사용자 권한으로 다른 일도 할 수 있으므로 콘솔이 새로 여는 위험은 아니다.
- 한계(문서에 명시): 브라우저 쿠키는 포트를 구별하지 않으므로 같은 호스트의 다른 localhost 포트로도 전달된다. 쿠키는 `Max-Age` 30일이고 서버도 같은 기간이 지나면 거부한다. 쿠키 값은 서버가 만든 무작위 값이라 다른 포트의 페이지가 읽을 수는 없지만(`HttpOnly`), 그 포트로 가는 요청에는 실린다.
- 한계(문서에 명시): Linux 는 지원 대상이 아니다. 인증 URL 이 `xdg-open` 의 인자로 `ps` 에 보일 수 있다(60초 일회용 토큰이다).
- 인증 없는 `/hooks/permission` 으로 누구나 요청을 만들 수 있으므로, '다시 묻지 않기' 제안(`permission_suggestions`)은 요청마다 따로 보관한다. 제안이 다르면 같은 도구 호출이라도 요청을 합치지 않아 위조 요청의 넓은 규칙(`Bash(*)`)이 진짜 요청의 답에 적용되지 않는다. 화면은 `허용하고 이 세션에서 다시 묻지 않기` 위에 추가될 규칙을 사람이 읽는 문장(`suggestionText`)으로 보여 주고, 도구 입력 JSON 전체와 `dangerouslyDisableSandbox`·`run_in_background` 같은 값을 접지 않고 보여 준다.
- 잠금 순서: `manager.lock` 은 `procs` 표만 지키는 잎 잠금이라 쥔 채로 `store.lock` 을 잡지 않고, 세션 잠금(`--resume`·시작 직렬화) → `store.lock` 순으로만 잡는다. `store.lock` 을 쥔 채 `manager.lock` 을 잡는 호출(`model_of` 등)은 살아 있는지부터 묻고 나서 잠금을 잡는다.
- 요청 읽기: `Content-Length` 가 음수이거나 숫자가 아니면 400 이다. 요청을 읽는 동안 소켓 timeout(30초)이 걸리고, 본문을 다 읽은 훅 연결은 timeout 을 풀어 승인 훅의 긴 대기를 끊지 않는다. SSE 큐는 1000개이고 가득 차면 그 구독자를 끊어 브라우저가 다시 붙게 한다.
- 상한: 세션 500개(오래된 끝난 세션부터 제거), 대기 요청 100개(넘으면 승인 훅은 빈 응답으로 터미널에 넘기고 콘솔 세션의 승인은 거부한다. 조용히 허용하지 않는다), 세션별 `skillStates` 100·`subagents` 200·예약 20·변경 파일 500·PR 링크 50.
- 터미널 세션은 마지막 훅 신호 뒤 10분이 지나면 쉬는 상태로 보고 `canSend` 를 끈다(터미널에서 Esc 로 끊으면 Stop 이 오지 않는다). 승인 대기가 있으면 계속 일하는 것으로 본다. Stop 이 예약 항목을 꺼낸 뒤 응답 전송에 실패하면 항목을 되돌린다.
- 새 작업의 `@경로`: 존재하는 작업 폴더 안의 파일만 받고, 줄바꿈·제어문자·`@`·따옴표·역슬래시가 든 경로는 후보에서 제외하며 사유를 화면에 보인다. 구분자는 `/` 로 통일한다. 공백이 든 파일은 `@"a b.txt"` 형식으로 넘긴다(claude 2.1.309 + haiku 로 1회 확인). 지원하지 않는 버전이면 `analysis.SPACE_MENTION_SUPPORTED` 를 끄면 후보에서 제외된다. git 폴더가 아니어서 `/harness:start` 를 안 붙일 때 사용자 글이 `/` 나 `@` 로 시작하면 첫 줄에 안내 문장을 앞세워 슬래시 명령으로 읽히지 않게 한다.
- 새 작업 분석용 `claude -p` 는 `--settings '{"disableAllHooks":true}'` 로 훅을 끈다. 켜 두면 분석 세션이 콘솔에 유령 세션과 승인 요청을 만든다.
- 권한 모드는 새 작업에서 세 가지만 고를 수 있다: 기본(`--permission-mode` 를 붙이지 않음, 그때그때 확인), `acceptEdits`(파일 고치기는 자동 허용), `plan`(계획만 세우기). 서버(`PERMISSION_OPTIONS`)가 허용 목록을 쥐고 그 밖의 값은 400 이다. `bypassPermissions`·`dontAsk`·`auto` 는 승인 요청이 웹까지 오지 않거나 사람이 아닌 쪽이 판단하게 되어, 사람이 웹에서 승인한다는 콘솔의 전제와 맞지 않아 화면에도 서버에도 두지 않는다. 고른 값은 `permissionChoice` 로 세션에 저장되어 `--resume` 때 같은 값으로 다시 띄운다. 세션 도중에도 `PUT /api/sessions/:id/permission` 으로 바꾼다. 살아 있는 세션에는 stdin 으로 `control_request{subtype:"set_permission_mode", mode}` 를 보내 `control_response` 를 기다린 뒤(8초) `permissionChoice` 를 갱신하고, 기본으로 되돌릴 때는 `mode:"default"` 를 보낸다. 끝난 세션이면 `permissionChoice` 만 바꿔 다음 `--resume` 에 새 값이 붙는다. 바꿀 때마다 세션 기록에 "권한 모드: A → B" 를 남긴다. 실제 `claude`(2.1.316) 로 확인했다 **[시험]**: 허용 값이면 `control_response{success, response:{mode}}` 와 `system/status{permissionMode}` 가 오고, 모르는 값은 `control_response{error, error_code:"invalid_mode"}` 가 오며, `plan` 으로 바꾼 뒤 파일 쓰기는 계획 파일만 쓰고 요청한 파일은 만들지 않았고 `acceptEdits` 로 바꾼 뒤에는 승인 없이 Write 가 됐다. 턴이 도는 중에 바꾸는 경우는 시험하지 않았다. 권한 모드는 작업을 진행하는 세션에만 적용하고 읽기 전용 분석에는 적용하지 않는다.
- 권한 우회 모드는 콘솔에서 제공하지 않는다. 그 모드(`permission_mode` 가 `bypassPermissions`)의 세션에는 `PermissionRequest` 가 발화하지 않으므로 세션 모델의 `bypassPermissions` 를 참으로 내려 화면이 표시하게 한다 **[시험]**.

## 5. 훅

| 이벤트 | 방식 | 경로 |
|---|---|---|
| SessionStart | command (`session_start_hook.py`, 자체 제한 1초, 항상 exit 0). 동기 | `/hooks/event` |
| PermissionRequest | command (`hook_post.py permission 86400`). **동기** | `/hooks/permission` |
| PreToolUse `AskUserQuestion` | command (`hook_post.py question 86400`). **동기** | `/hooks/question` |
| Stop | command (`hook_post.py stop 5`). **동기** | `/hooks/stop` |
| SessionEnd | command (`hook_post.py event 3`). **동기**(공유 제한 1.5초, 훅 timeout 5초로 늘림) | `/hooks/event` |
| UserPromptSubmit, UserPromptExpansion, PreToolUse `*`, PostToolUse, SubagentStart, SubagentStop, Notification, PreCompact | command (`hook_post.py event 3`) + **`"async": true`** | `/hooks/event` |

모든 콘솔 훅은 `type: "command"` 이고 `uv run --no-project python console/hook_post.py <경로> <제한 초> || true` 이다. 서버가 꺼져 있으면 연결 거부를 삼키고 아무것도 출력하지 않고 exit 0 이라 화면에 훅 오류 줄이 남지 않는다. http 훅은 서버가 꺼져 있으면 대화형 화면에 오류 줄이 남아서 쓰지 않는다 **[시험]**.

**왜 async 인가.** command 훅은 도구 호출마다 프로세스를 띄운다. 이 머신(macOS, uv 경유)에서 한 번에 약 130ms 이고 그 가운데 uv 자체가 약 115ms 다. 서버가 꺼져 있어도 같다. 동기로 두면 도구 호출 하나에 PreToolUse·PostToolUse 두 번, 콘솔을 쓰지 않는 사용자까지 느려진다. 상태만 모으고 응답이 필요 없는 이벤트는 `async: true` 로 세션을 기다리게 하지 않는다. 승인·질문·Stop·SessionEnd 는 응답을 쓰거나(결정, `updatedInput`, `block`) 종료 전에 끝나야 해서 동기로 둔다. 공식 문서(hooks, "Run hooks in the background")는 `async` 를 command 훅의 필드로만 설명하고 이벤트별 제한은 적지 않는다. 실제 `claude`(2.1.309) 로 UserPromptSubmit, PreToolUse `*`, PostToolUse(터미널 먼저 허용 시 요청 닫힘), SubagentStart·Stop, Notification 이 async 로 서버에 도착함을 확인했다 **[시험]**. UserPromptExpansion 과 PreCompact 은 이번 시험에서 발화를 관측하지 못했다. 문서상 막히지 않으므로 async 로 두었고, 안 오면 해당 표시(스킬 감지는 PreToolUse(Skill) 도 한다, 압축 로그)만 빠진다. async 훅은 `-p` 로 돌 때 종료 시점에 정리되므로 마지막 이벤트가 유실될 수 있지만, 콘솔이 띄운 세션은 Stop(동기)이 상태를 닫는다.

PreToolUse `*`(async)와 PreToolUse `AskUserQuestion`(동기)은 질문 도구에서 둘 다 걸린다. 서로 다른 훅 프로세스이고 `*` 쪽은 응답을 쓰지 않으므로 질문 답이 깨지지 않는다 **[시험: 관리 세션 질문 답변]**.

**도착 순서.** async 는 프로세스가 늦게 떠서 Stop 보다 늦게 올 수 있다. `hook_post.py` 는 뜨자마자 `X-Hook-Ts` 헤더에 시각을 싣고, 서버는 Stop·SessionEnd 의 시각을 세션의 경계(`boundaryTs`)로 기억한다.
- 경계보다 먼저 뜬 UserPromptSubmit·PreToolUse·UserPromptExpansion 은 `turn_running`·`ended`·현재 작업·스킬 표시를 바꾸지 않는다(쉬는 세션이 다시 도는 것으로 되돌아가거나 스킬이 계속 진행 중으로 남지 않게).
- 늦게 온 PostToolUse·UserPromptSubmit 은 그 시각까지 만들어진 요청만 닫는다(그 뒤에 같은 도구·입력으로 새로 생긴 승인 요청을 닫지 않게).
- 같은 세션의 PreToolUse 가 뒤바뀌어 오면 더 늦게 뜬 것의 현재 작업을 남긴다.
- SubagentStop 이 SubagentStart 보다 먼저 오면 끝난 것으로 남기고, 뒤늦은 시작이 다시 running 으로 만들지 않는다.
- **서브에이전트 진행.** 메인 세션의 PreToolUse(`Agent`·`Task`, `agent_id` 없음)에서 `description`·`subagent_type`·프롬프트 첫 줄(120자)·`run_in_background` 를 대기 목록(`pendingAgents`, 50개 상한)에 둔다. SubagentStart 가 오면 `tool_use_id` 가 같은 항목, 없으면 같은 종류 중 가장 오래된 항목과 짝지어 서브에이전트 항목에 `description`·`prompt`·`background`·`startedAt` 을 붙인다. 서브에이전트 안에서 난 PreToolUse 는 훅 입력에 `agent_id`·`agent_type` 이 실려 와서 그 항목의 `currentAction`·`tools`(횟수)만 갱신하고 메인 세션의 현재 동작은 덮지 않는다. SubagentStop 은 `endedAt`·`durationSec` 을 적는다. 화면은 실행 중인 서브에이전트를 위에 강조하고(종류·맡은 일·지금 동작·경과), 끝난 것은 접힌 목록에 둔다. 사이드 목록은 "서브에이전트 N개 실행 중" 을 덧붙인다. 실제 `claude`(2.1.316) 로 `agent_id` 가 서브에이전트 안 PreToolUse 에 오고 SubagentStart 에는 `tool_use_id` 가 없음을 확인했다 **[시험]**. 이 버전에서 Agent 의 PostToolUse 는 10ms 뒤에 와서(서브에이전트는 계속 돈다) `run_in_background` 를 주지 않아도 비동기로 보인다. 그래서 `background` 는 도구 입력에 `run_in_background: true` 가 있을 때만 켠다.
- 헤더가 없거나 숫자가 아니면(옛 호출자) 도착 순서를 그대로 믿는다.

**[시험]** SessionStart 는 http 를 지원하지 않는다. 86400 은 로딩 오류가 없을 뿐 상한은 미확인이고 660초 대기까지만 확인했다. Notification 은 관측했다(관리 세션 승인 대기 때 "Claude needs your permission" 알림).

서버가 SessionStart 뒤에 켜진 경우, 어떤 이벤트든 처음 온 `session_id` 를 자동 등록한다.

### 승인 `/hooks/permission`

응답: `hookSpecificOutput{hookEventName:"PermissionRequest", decision{behavior, updatedPermissions?, message?}}`.

- 터미널 세션은 프롬프트가 함께 뜬다 **[시험]**. 웹이 먼저 답하면 프롬프트가 사라진다 **[시험]**.
- **터미널에서 먼저 허용하면 훅 연결이 끊기지 않는다 [시험]**. 그래서 같은 세션의 `PostToolUse` 가 `tool_name`, `tool_input` 이 일치하면 요청을 "터미널에서 처리됨"으로 닫고 훅에는 빈 2xx 를 돌려준다. `UserPromptSubmit`, `Stop`, `SessionEnd` 가 오면 그 세션의 남은 요청을 모두 닫는다(UserPromptSubmit 은 async 라 늦게 와도 그 시각까지 만든 요청만 닫는다). 터미널 거부와 Esc 는 연결이 끊긴다 **[시험]**. 끊기면 닫는다.
- 콘솔이 띄운 세션은 터미널이 없으므로 답할 때까지 기다린다. 빈 응답은 거부가 된다 **[시험]**.
- 터미널 세션에 브라우저가 연결돼 있지 않으면 바로 빈 2xx 를 돌려준다(터미널 프롬프트가 처리한다).
- `허용하고 이 세션에서 다시 묻지 않기` 는 `permission_suggestions` 를 `updatedPermissions` 로 돌려준다. 제안이 없으면 버튼을 숨긴다.
- 같은 세션·도구·입력의 동시 호출은 요청 하나로 합친다. 요청 하나에 붙은 훅 연결이 여러 개여도 모두 같은 답을 받고, 붙은 연결이 전부 끊겨야 요청을 닫는다.
- 콘솔이 띄운 세션은 훅과 `can_use_tool` control_request 가 **동시에** 같은 승인을 보낸다 **[시험]**. 서버는 둘을 요청 하나로 합쳐 사용자에게 한 번만 묻고, 사용자가 답하면 훅 응답과 control_response 양쪽에 같은 답을 돌려준다(`managed.py`). 허용이면 control_response 는 `updatedInput` 에 원래 입력을, `updatedPermissions` 가 있으면 그것을 담는다. 요청이 답 없이 닫히면 control_response 는 거부다.
- 이 경로에서 `AskUserQuestion` 의 control_request 는 다루지 않고(훅이 맡는다) 거부로 답한다.

### 질문 `/hooks/question`

응답: `permissionDecision:"allow"` + `updatedInput{questions: 원본, answers:{질문문구: 답}}` **[시험]**. 다중 선택은 `", "` 로 이은 문자열, 자유 입력은 그 글 자체.

- `tool_name` 이 `AskUserQuestion` 이 아니면 빈 2xx 를 돌려준다 **[시험: 안 거르면 다른 도구가 깨진다]**.
- 훅이 기다리는 동안 터미널에는 질문창이 뜨지 않는다 **[시험]**. 그래서 터미널 세션은:
  - 브라우저가 연결돼 있지 않으면 즉시 빈 2xx (터미널 질문창으로 넘어간다 **[시험]**).
  - 연결돼 있으면 최대 300초 기다린 뒤 빈 2xx. 그때까지의 요청은 "터미널로 넘어감"으로 닫는다.
  - Esc 는 연결을 끊는다 **[시험]**. 끊기면 닫는다.
- 콘솔이 띄운 세션은 답할 때까지 기다린다.

### 턴 끝 `/hooks/stop`

`last_assistant_message` 를 세션의 결과 보고로 저장한다. 그 세션에 예약된 스킬이나 대기 중인 이어서 요청이 있으면 `{"decision":"block","reason":"..."}` 를 한 번 돌려준다. **[시험]** 이렇게 하면 Claude 가 Skill 도구로 스킬을 실행한다. 이 경우 스킬 감지는 `PreToolUse(Skill)` 이고, 사람이 친 슬래시와 stdin 슬래시는 `UserPromptExpansion` 이다 **[시험]**. 둘 다 처리한다.

예약은 꺼낼 때 지워서 무한 반복을 막는다. 기존 `stop-deliver.sh` 와 함께 돌 때 깨지지 않는지 확인한다.

## 6. 세션 제어

| 기능 | 콘솔이 띄운 세션 | 터미널 세션 |
|---|---|---|
| 상태·결과 보기 | 스트림 + 훅 | 훅 |
| 승인·질문 | 가능 | 가능 |
| 스킬 실행, 이어서 요청 | 언제든 stdin | 실행 중: 턴 끝에 Stop 훅으로 전달. 쉬는 중: **불가** |

쉬는 터미널 세션에 외부에서 턴을 시작하는 공식 수단은 없다 **[시험]**. 입력칸과 스킬 버튼을 막고 이유를 표시한다. 문서화되지 않은 `messagingSocketPath` 는 쓰지 않는다.

### 콘솔이 띄우는 세션

```
claude -p --input-format stream-json --output-format stream-json --verbose
       --permission-prompt-tool stdio --plugin-dir <플러그인 폴더>
```

- 작업 폴더를 `cwd` 로 띄운다. 터미널 창 없이 stdin/stdout 만 쓴다.
- `--permission-prompt-tool stdio` 가 없으면 `AskUserQuestion` 도구가 아예 없다 **[시험]**. `can_use_tool` control_request 는 훅과 동시에 오므로(§5 승인) 훅 요청에 합쳐 답한다. `can_use_tool` 이 아닌 control_request 와 `AskUserQuestion` 요청은 거부로 답하고 로그에 남긴다. control_request 만으로 답하지 않는 이유는 약 100초 뒤 취소되기 때문이다 **[시험]**.
- `--plugin-dir` 은 그 폴더에 플러그인이 켜져 있지 않아도 훅이 걸리게 하려는 것이다. 같은 이름의 플러그인이 이미 설치돼 있을 때 훅이 이중으로 걸리거나 빠지지 않는지 시험으로 확인한다. 문제가 있으면 보고한다.
- stdin 메시지는 다중 턴이 된다. `/스킬` 은 확장된다. 실행 중 보낸 메시지는 큐잉돼 같은 턴에 합쳐진다. 중단은 `control_request{subtype:"interrupt"}` 를 쓴다. 전부 **[시험]**.
- 띄우자마자 임시 id(`m-…`)로 등록하고, stdout 이벤트의 `session_id` 가 오면 실제 id 로 바꾼다(훅이 먼저 실제 id 로 등록했으면 합친다). 임시 id 로는 `--resume` 할 수 없다. `result` 이벤트의 `result` 글은 Stop 훅이 보고를 못 채웠을 때만 결과 보고로 쓴다.
- session_id 는 이벤트의 `session_id`(`hook_started`, `system/init` 등)에서 얻는다. 종료된 세션은 `--resume` 으로 다시 띄운다 **[시험]**.
- 종료: stdin 닫기. 안 끝나면 `platform_compat.terminate`(POSIX SIGTERM, Windows `taskkill /PID <pid> /T /F` 로 자식까지 끄고, 실패하면 `proc.terminate()`).
- `claude` 실행 파일은 `shutil.which` 로 찾는다. Windows 는 `claude.exe` 를 먼저 찾고, `.cmd`·`.bat`·`.ps1` 이면 옆 `node_modules/@anthropic-ai/claude-code` 의 exe 또는 `node` + `cli.js` 를 직접 실행한다. `cmd /c` 는 공백·한글 경로와 JSON 인자에서 깨져 쓰지 않는다. 뒤에 붙는 인자는 고정 값뿐이다. 사용자 입력은 stdin 으로만 넘긴다.

### 새 작업

1. `POST /api/new {text, cwd, model?, effort?}`: `claude -p --permission-mode plan --output-format json --json-schema <스키마> --no-session-persistence` 로 읽기 전용 분석을 돌린다. 승인 없이 끝난다 **[시험]**. 요청 글은 stdin 으로 넘긴다. 180초 안에 끝나지 않으면 실패로 처리하고, 분석 작업은 메모리에만 있어 서버를 다시 띄우면 사라진다.
2. 스키마: `understood`, `candidates[{path, reason}]`, `extraQuestions[{question, options[]}]`. 결과의 `path` 는 작업 폴더 안인지 서버가 다시 검사한다.
3. `POST /api/new/:id/start {picked[], extraAnswers, note, model?, effort?, permission?}`: 세션을 띄우고 첫 메시지로 요청 글과 `@경로`(**[시험]** 파일 내용이 주입된다), 답, 메모를 보낸다. 작업 폴더가 git 저장소면 앞에 `/harness:start` 를 붙인다. 화면 미리보기와 실제 메시지는 같은 함수로 만든다.

## 7. `이번 차례` 규칙 (`gitstate.py`)

위에서부터 처음 맞는 것을 고른다. `gh` 가 없거나 실패하면 PR 판단을 건너뛰고 `start` 로 두며 `turnUnknown` 을 참으로 내려보낸다. git·gh 호출은 각각 5초 제한이다. 기본 브랜치는 `origin/HEAD` → `main` → `master` 순으로 찾고, 분리된 HEAD 나 빈 브랜치 이름도 `start` 로 본다. `원격보다 앞선 커밋` 은 `@{u}..HEAD`, 올려 둔 곳이 없으면 `origin/<기본 브랜치>..HEAD` 로 센다. 변경 파일(`changedFiles`)은 이 판단의 `git status` 결과로 훅이 모은 목록을 덮어쓴다(git 저장소일 때). 그래서 커밋하면 비지만, 만든 문서 목록은 따로 쌓는 `touchedFiles` 를 함께 봐서 커밋 뒤에도 남는다(§7b).

1. git 저장소가 아니다 → 차례 없음
2. 기본 브랜치에 있다 → `start`
3. 커밋 안 된 변경이 있거나 원격보다 앞선 커밋이 있다 → `deliver`
4. 열린 PR 이 있다 → `prs`
5. 그 밖 → `start`

**글로 물은 경우(#619).** 위 판단은 git 상태 짐작일 뿐이라 세션이 결과 보고에서 글로 질문하고 턴을 마쳐도 `start` 같은 차례가 나온다. 그래서 서버(`store.report_asks`)가 마지막 결과 보고(`report`)의 끝 줄이 물음표로 끝나는지 보고, 턴이 끝났고(실행 중·시작 중·끝남 아님) 승인·질문 대기가 없고 그 보고가 **이번 턴에 받은 것**(`reportFresh`)이면 세션 모델의 `askedInText` 를 참으로 낸다. `reportFresh` 는 Stop 훅이 보고를 받을 때(콘솔 세션은 `result` 이벤트가 Stop 보다 먼저 왔을 때) 켜지고 새 턴(UserPromptSubmit, 콘솔에서 보낸 메시지)이 시작되면 꺼진다. 그래서 답한 뒤 보고 없이 끝난 턴이 지난 턴의 물음표를 다시 쓰지 않는다. 보고 글(`report`)은 화면에 그대로 남는다. 추정이라 틀릴 수 있다(물음표로 끝나지 않는 부탁, 끝 줄이 물음표인 인용은 틀린다). 화면은 이 필드만 읽고, 어디서나 추정임이 드러난다: 큰 제목 "내 답을 기다리는 듯해요(추정).", 상태 "내 답을 기다리는 중(추정)", 홈 카드 "답을 기다리는 듯해요(추정)", 할 일 동사 "답하기(추정)", 세션 화면에 "마지막 보고가 물음표로 끝나서 질문으로 추정했어요" 한 줄과 git 짐작 차례는 "참고로 git 상태로는 … 차례로 보여요" 로 낮춘다.

스킬 목록은 플러그인의 `skills/*/SKILL.md` frontmatter 의 `name`·`description` 에서 읽는다. `update`, `scaffold`, `open` 은 버튼과 `/` 자동완성에서 숨긴다(`HIDDEN_SKILLS`). 실행 중에는 스킬 흐름에서 현재 스킬을 `진행 중` 으로 표시한다.

## 7a. 갈래와 단계 (`workflow.json`, `flows.py`)

"하고 싶은 일 → 하네스 갈래 → 그 순서대로만 진행" 이다. **순서의 정본은 콘솔이 아니라 플러그인의 `plugins/harness/workflow.json` 이다**(#599, 저장소 원칙 "규칙은 데이터"). 콘솔은 화면만 쉽게 하고 순서를 따로 갖지 않는다(옛 `console/flows.json` 은 없앴다). 갈래·단계·다음 갈래·도구·조건마다 `basis: [{file, quote}]`(근거 스킬·규칙 파일과 그 안의 실제 문장)가 있어야 한다. 근거 문장을 못 찾는 단계는 넣지 않는다. 서버는 뜰 때 이 파일을 읽고 `flows.validate` 로 검사한다. 모든 스킬이 `skills/*/SKILL.md` 에 있어야 하고, 가리키는 갈래·조건·증거가 정의돼 있어야 하며, `basis` 가 비었거나 `file` 이 없거나 `quote` 가 그 파일에 없으면(공백·줄바꿈 차이는 무시) 오류다. 틀리면 갈래 기능만 끄고(`GET /api/flows` 와 갈래 지정이 503, 사유는 서버 stderr) 콘솔은 그대로 뜬다. 갈래가 없는 세션은 예전처럼 스킬 제한이 없다. PR 검사(`checker/tests/test_workflow_source.py`)는 모든 근거가 맞는지, 모든 스킬이 `workflow.json` 의 단계나 도구에 있는지 확인한다. 새 스킬을 순서나 도구에 넣지 않으면 실패한다.

| 갈래 id | 이름 | 단계 |
|---|---|---|
| `srs` | 요구사항 만들기·바꾸기 | srs → deliver → 승인·병합 기다리기 → 다음 갈래는 SRS 의 `다음 단계` 값에 따라 갈림 |
| `spec` | 개발 Spec | spec → deliver → 승인·병합 기다리기 → 다음 갈래 `dev` |
| `dev` | 개발하기 | start → 구현(SAP 080 에서 개발·활성화) → deliver → 병합 기다리기. ATC 는 단계가 아니라 도구다. 개발 묶음이 안 끝나 deliver 가 "브랜치에만 올리기" 를 고르면 PR 이 생길 때까지 deliver 단계가 끝나지 않는다(정상 경로, 단계 설명에 적혀 있다) |
| `config` | 설정하기 | start(그 `[DEV-xxx]` 로, 원장 줄은 만들지 않고 SRS Status 를 `In Process` 로) → 설정하고 SRS 상세 절 Configuration Considerations 에 기록 → deliver(SRS Status `Done` 까지 PR 에 담는다) → 병합 기다리기. 화면에는 "설정 DEV-003" 처럼 보인다(#718) |
| `standard` | 표준 기능으로 처리하기 | `config` 와 같은 모양: start → 어느 SAP 표준 앱·기능으로 해결되는지 SRS 상세 절에 기록 → deliver(Status `Done`) → 병합 기다리기. 화면에는 "표준 DEV-003" (#718) |
| `fix` | 작은 수정 | start(원장이 있는 저장소의 feat·fix 면 DEV 번호를 받을지 묻는다) → 고치기 → deliver → 병합 기다리기 |

병합 기다리기 문구: 위험하지 않은 PR 은 검사가 모두 통과하면 자동 병합, 위험한 PR 은 작성자가 아닌 승인자의 Approve, 사람이 병합해야 하는 경로(`.github/human-merge-paths`)를 바꾼 PR 은 사람이 GitHub 에서 병합한다(`rules/governance.md`).

없앤 갈래: "새 고객사 시작"(scaffold 는 프로젝트마다 한 번 하는 준비이지 작업 순서가 아니다), "ATC 지적 고치기"·"합쳐지기 기다리기"(`atc`·`prs` 는 도구다). 옛 갈래 id(`new-customer`·`atc`·`review`)로 저장된 세션은 정의를 못 찾으니 저장된 이름·단계가 그대로 보인다(`public_fields`).

**프로젝트 준비.** 조건 `project-ready`(`type: paths`)는 작업 폴더에 `templates/` 와 `rules/` 가 둘 다 있는가를 본다. 없으면 홈(프로젝트 준비 카드)과 세션·새 작업 화면의 도구 줄 위에 "프로젝트 준비 안 됨" 안내를 내고, 관리자용 도구 `scaffold`(조건 `project-not-ready`)를 보인다. git 을 실행하지 못하는 등 판정 불능이면 숨기지 않고 "확인하지 못했어요" 로 알린다.

**도구만 쓰는 일.** scaffold·cts·role·manual·handoff 같은 도구 스킬만 쓰는 일은 어느 갈래에도 억지로 넣지 않는다. 새 작업 분석의 갈래 보기에 `none`("순서 없이 이 도구만")이 늘 있고, 요청이 `/harness:<도구>` 로 시작하면 서버가 분석 결과와 상관없이 `none` 으로 본다. 이때 시작 글 앞에 `/harness:start` 같은 다른 스킬을 붙이지 않는다. 사용자가 글 맨 앞에 `/harness:<스킬>` 을 직접 적었으면(git 저장소) 그 스킬이 첫 줄이다. git 저장소가 아니면 기존 안전 문장을 앞세운다.

**분석 프롬프트의 폴더 사실.** 대상은 SAP S/4HANA Public Cloud·ABAP Cloud 로 적는다(저장소 `env/adt-tiers.yaml` 최상위 `system_type` 이 있으면 그 값도 적는다). 프로젝트 준비 조건이 `no` 면 `understood` 첫 문장에 "먼저 관리자가 프로젝트 구조 만들기(/harness:scaffold)" 를 안내하게 하고, 판정 불능이면 단정하지 않게 한다.

**SRS 다음 갈래.** `srs` 갈래가 끝나면 `docs/ssot/SRS.md` 의 요구사항 표에서 `다음 단계` 열을 읽어 값별로 센다. 빼는 Status 는 분기마다 근거가 있는 것만 둔다: `개발`·`설정`·`표준` 은 `Dropped`·`Duplicate`·`On Hold`, `미정` 은 근거가 없어 아무것도 빼지 않는다. `개발` → `spec`, `설정` → `config`(Spec 없이 `[DEV-xxx]` 설정 작업), `표준` → `standard`(Spec 없이 `[DEV-xxx]` 표준 기능 작업), `미정` → 갈래 없이 안내만("개발 Spec 을 시작하면 그 자리에서 개발인지 설정·표준인지 정하게 한다", spec 스킬의 미정 경로). 설정·표준 건의 진행은 원장이 아니라 SRS Status 다(#718). 값이 섞여 있으면 선택지를 값별 개수·ID 와 함께 모두 내려보낸다. 설정·표준 갈래로 넘길 때는 그 요구사항 번호(`ids`)를 `POST .../flow/next` 로 함께 보내 새 세션의 사유를 "설정 DEV-003"·"표준 DEV-003" 으로 적는다. 파일을 못 읽거나 열·값을 못 찾으면 `unknown` 사유를 넣고 선택지를 비운다(끝으로 두지 않는다).

**단계 종류와 완료 판정.** 단계는 `kind`(`skill` 스킬 실행 / `work` Claude Code 와 하는 작업 / `human` 사람이 하는 일 / `wait` 밖에서 일어나길 기다림)와 `done`(증거 목록, 모두 맞아야 끝)을 가진다. 증거:

| 증거 | 뜻 | 판정에 쓰는 것 |
|---|---|---|
| `skill_done` | 그 스킬이 시작된 뒤 턴이 끝났다 | Skill 이벤트(`PreToolUse` Skill, `UserPromptExpansion`)로 `진행`, Stop 으로 끝 표시 |
| `has_changes` | 커밋 안 된 변경이나 원격보다 앞선 커밋이 있다 | `gitstate.inspect` 의 `changedFiles`·`ahead` |
| `on_work_branch` | 지금 브랜치가 기본 브랜치가 아니다(start 단계: 새 작업 브랜치가 생겼다) | `gitstate.inspect` 의 `onBase` |

`skill_done` 은 질문(AskUserQuestion)이 답을 기다리는 중의 Stop 에서는 표시하지 않는다. 중간에 묻는 스킬(start·srs·spec)이 첫 응답에서 끝난 것으로 보이지 않게, start 는 `on_work_branch`, srs·spec 은 `has_changes` 를 함께 요구한다. 조건(`onlyIf`)을 판정하지 못하면 그 단계를 건너뛰지도 끝내지도 않는다(판정 불능, `flowUnknown`). git·gh 는 `store.lock` 밖에서 부르고 그 값만 잠금 안에 넘긴다.
| `pr_exists` | 이 브랜치의 PR 이 있다 | `gh pr list --head <브랜치> --state all` |
| `pr_merged` | 그 PR 이 병합됐다 | 같은 조회, 한 번 본 PR 은 번호로 `gh pr view` (브랜치를 옮겨도 본다) |
| `manual` | 사람이 화면에서 끝났다고 눌렀다 | `POST .../flow/done` |

단계 상태는 `pending`(대기) / `active`(진행) / `done`(끝) / `skipped`(건너뜀 + 이유) 이다. 스킬 단계는 그 스킬이 시작되면 `active`, 그 밖의 단계는 지금 단계가 되면 바로 `active` 다. 단계에 `onlyIf`(조건 이름)가 있고 조건이 거짓이면 이유("조건에 맞지 않아 건너뜀")와 함께 자동으로 건너뛴다. 판정은 Stop·SessionStart 의 git 갱신 때, `flow/refresh` 때, 갈래를 지정할 때 돈다. **gh 로 근거를 못 읽으면 끝으로도 아님으로도 두지 않고** 단계를 그대로 둔 채 `flowUnknown` 에 사유를 넣는다("판정 불능"). 조건 판정도 같다 — 못 읽은 조건은 `unknown` 이고 숨기지 않는다.

**순서.** 갈래가 있는 세션은 지금 단계의 스킬(`wait` 단계는 `helperSkill`)만 `POST .../skills/:skill/run`·예약으로 실행할 수 있고, 다른 스킬은 409 다. 단계를 건너뛰려면 `POST .../flow/skip {reason}` 이 필요하고 이유가 없으면 400 이다. 이유는 단계와 세션 로그에 남는다. **도구**(`tools`: version, sync, update, handoff, wrapup, prs, reload, approvals, atc, role, cts, manual, scaffold, open)는 갈래와 상관없이 언제나 실행된다. `reload`(콘솔 세션 전용)의 동작은 §7b 다. 도구에 `requires`(조건 이름)가 있으면 그 조건이 거짓일 때만 숨기고(판정 불능은 보인다), `hidden: true`(`open`)는 화면에 단추를 내지 않는다. 버튼에 안 내는 `scaffold`·`update` 도 도구 데이터에 있으면 실행된다. 권한·CTS 양식은 "준비 중" 다음 갈래가 아니라 `role`·`cts`·`manual` 도구다.

**노출 조건.** `conditions` 가 이름으로 정의한다.
- `adt-tiers` (`file`): 저장소 꼭대기에 `env/adt-tiers.yaml` 이 있는가. 없으면 `atc` 도구를 숨긴다(`GET /api/flows` 의 `exposure.visible=false`). 갈래·단계에도 `requires`·`onlyIf` 로 같은 조건을 걸 수 있다(숨김, 갈래 지정은 409, 단계는 건너뜀). 지금 `workflow.json` 의 갈래·단계에는 쓰는 곳이 없고 엔진 시험은 조건을 더한 사본으로 본다.
- `project-ready` / `project-not-ready` (`paths`): `templates/` 와 `rules/` 를 함께 가진 폴더가 저장소 꼭대기나 3단계 아래까지(`searchDepth`) 있는가 / 없는가(`negate`). `.claude-plugin/marketplace.json` 이 있는 플러그인 저장소(`exemptFile`)와 `HARNESS_NO_SCAFFOLD_HINT=1` 은 `session-start-sync.sh` 와 같이 따지지 않는다(준비된 것으로 본다). 위 "프로젝트 준비" 참고.
- `approver`: 이 저장소에서 내가 승인자인가(`approvals` 도구를 보일지). `gh api user` 로 내 아이디를 읽고 `.github/ssot-approvers` 를 `checker.ssot_approval` 과 같은 형식으로 읽는다. 내용이 있으면 거기 든 사람만 승인자다. **파일이 없거나 비어 있으면** `whenNoFile` 에 따라 `admin`(`gh repo view` 의 `viewerPermission` 이 ADMIN 일 때만) 또는 `anyone`(작성자 아닌 누구든)이다. 지금 값은 `admin` 이다. 파일은 작업 폴더의 것을 읽는다(엔진은 기준 브랜치에서 읽는다). gh 가 실패하면 `unknown` 으로 두고 도구를 숨기지 않는다. 폴더가 GitHub 저장소(`git remote -v` 에 `github.com`)가 아니면 gh 를 부르지 않고 `no`(이유 "GitHub 저장소가 아님")로 두어 도구와 홈의 승인 칸을 숨긴다. 결과는 60초 기억하고, 못 읽은 결과는 기억하지 않는다.

**분류(분석).** `POST /api/new` 의 분석 스키마에 선택 속성 `flow {id(갈래 id 목록 중 하나), reason, confident, alternativeId}` 가 더해진다(이 폴더에서 쓸 수 있는 갈래만 프롬프트·스키마에 든다. `required` 에는 넣지 않아 없어도 결과가 유효하다). 서버는 id 가 목록에 있는지 다시 검사해 결과에 `flow {id, name, reason, confident, alternativeId, alternativeName}` 와 `flowError` 를 넣는다. 확신이 없고(`confident=false`) 후보가 둘이면 `extraQuestions` 맨 앞에 두 갈래를 묻는 질문(`flowChoice: [id, id]`)을 끼운다. 시작할 때 `flow` 를 주지 않으면 확신한 분류를 쓰고, 첫 메시지는 갈래의 첫 스킬(`/harness:<skill>`)로 시작한다. 첫 단계가 스킬이 아니면 그대로 둔다.

**끝난 뒤.** 갈래가 끝나면 세션의 `nextFlow {options[{flow, name, label, disabled, value?, count?, ids?}], hint, unknown?}` 에 다음 갈래를 넣는다. "새 세션으로 시작하십시오." 힌트와 함께 내려보내고, 사람이 고르면 `POST .../flow/next` 가 자동 인계와 새 세션 띄우기를 한다(§7c).

## 7b. 플러그인 다시 불러오기, 만든 문서 보기, 같은 폴더

**플러그인 다시 불러오기** (`POST /api/sessions/:id/reload`, 콘솔이 띄운 세션만). stdin 에 `control_request{subtype:"reload_plugins"}` 를 보내 `control_response.response.plugins[{name,path,source,version}]`·`error_count` 를 받는다(claude 2.1.316 실측, 모델 비용 없음). 거절당하거나 20초 안에 답이 없으면 user 메시지 `/reload-plugins` 로 대신하고(`method:"message"`, 합성 응답 `Reloaded: N plugins · M errors` 를 읽는다. 이 경우 판 목록은 알던 값 그대로) 둘 다 안 되면 502 다. 응답 `{ok, method("control"|"message"), plugins[{name,version}], errorCount, harnessVersion, message?}`. 터미널 세션과 끝난 세션은 409. 세션이 턴 진행 중이면(턴 실행 중이거나 띄우는 중) 끝날 때까지 기다렸다가 하고(최대 10분, 같은 세션은 한 번만 대기) 바로 `202 {queued:true}` 로 답한다. 결과는 세션 로그와 `pluginVersions` 에 남는다. `POST /api/reload-all` 은 살아 있는 콘솔 세션 전부에 같은 일을 하고 `{results:[{sessionId, title, ok, ...위 응답 또는 error / queued}]}` 를 돌려준다. 세션 필드 `pluginVersions[{name,version}]` 는 `system/init` 의 `plugins`(판이 없으면 알던 판을 지킨다)와 다시 불러오기 결과로 갱신한다.

**새 세션 점검.** 콘솔이 새로 띄운 세션(새 작업 시작·다음 갈래 넘기기)은 `startChecks[{id, state}]` (`sync`, `version`, `update`, `reload`; state `pending`/`done`/`skipped`)를 가진다. `sync`·`version`·`update` 는 그 스킬의 Skill 이벤트(`PreToolUse` Skill, `UserPromptExpansion`)가 오면, `reload` 는 다시 불러오기가 성공하면 `done` 이 된다. `POST /api/sessions/:id/checks/:id/skip` 이 `skipped` 로 바꾼다(대기 중인 항목만. 모르는 항목은 404). 이어서 띄운 세션과 터미널 세션은 빈 목록이다.

**만든 문서 보기.** 세션의 작업 폴더(`cwd`) 기준이다.
- `GET /api/sessions/:id/files` → `{files:[{path(cwd 기준 '/' 상대 경로), kind(md/xlsx/pptx/docx/pdf/image/other), size, mtime(epoch 초), changed, versions[]}]}`. 화면은 파일 이름만이 아니라 이 상대 경로를 그대로 보인다(같은 이름 `README.md` 를 구분하려고, #619). 이 세션이 만들거나 바꾼 파일을 쌓아 둔 `touchedFiles`(세션 모델로는 내려보내지 않는다) 중 작업 폴더 안의 실제 파일만 낸다. 쌓는 길은 둘이다: Write·Edit·MultiEdit·NotebookEdit 훅의 경로(이 세션 것이 확실하다)와 `git status --porcelain -z -uall` 의 바뀐·새 파일(`refresh_git` 과 이 목록을 부를 때마다). 후자에서는 세션을 처음 본 때 이미 바뀌어 있던 파일(`baselineFiles`)을 뺀다. 기준선은 첫 `refresh_git` 성공 때 한 번 적고, 늦게 잡혀도 세션 시작(`startedAt`) 뒤에 마지막으로 바뀐 파일은 기준선에 넣지 않는다(첫 턴에 만든 파일이 빠지지 않게. 시작 뒤에 다른 세션·사람이 바꾼 파일은 섞일 수 있다). 경로는 구분자(`\`·`/`)와 대소문자(Windows)를 같게 보고 중복을 거르며, 작업 폴더 밖 경로(작업 폴더가 저장소 하위일 때 `git status` 에 같이 나온다)는 쌓지 않는다. 커밋해도 지우지 않는다. `.git`·`node_modules` 등 건너뛰는 폴더의 경로는 쌓지 않고, 500개 상한에 닿으면 `touchedTruncated` 가 켜져 응답에 `truncated:true` 가 붙는다(화면이 "목록이 잘렸어요"). **한계:** 같은 폴더에서 다른 세션이나 사람이 시작 뒤에 바꾼 파일은 구분할 수 없어 섞일 수 있고(화면에 그렇게 적는다), 기준선을 잡기 전에 목록을 먼저 부르면 그때 바뀌어 있던 파일도 들어간다. 항목의 `changed` 는 지금 `git status` 에 있는 파일(커밋 안 됨)만 참이고, 화면은 "아직 커밋 안 됨" / "지금 바뀐 것 없음(git 기준)" 으로 보인다(`.gitignore` 로 `git status` 에 안 나오는 파일도 뒤쪽이라 "커밋됨" 이라 단정하지 않는다). **git 저장소가 아니면** `current_paths` 를 넘기지 않고 `unknown:true, reason:"git 저장소가 아니라 커밋 여부를 알 수 없어요."` 를 내며 화면은 상태 글을 붙이지 않는다. `git status` 를 못 읽었으면(`refresh_git` 이나 이 목록 호출에서) `touchedGap{reason, at}` 을 남기고, 그 뒤 30분(`GAP_NOTICE_SECONDS`) 동안 `unknown:true, reason:"HH:MM 에 git 상태를 읽지 못해 그 사이 커밋된 문서가 빠졌을 수 있어요."` 를 낸다. 그 뒤에는 사라진다(영구 경고 없음). 목록에는 작업 폴더 안의 실제 파일만 낸다(`.git`·`node_modules` 같은 큰 폴더와 `~$` 잠금 파일은 뺀다. 최신 수정 순, 최대 300개). 판 이름(`이름_v0.1.xlsx`)이면 같은 폴더의 같은 이름 판을 모두 찾아 `versions[{path, version, size, mtime, changed}]` 에 최신 판부터 담고(숫자로 비교: 0.10 > 0.2) 항목의 `path`·`size`·`mtime` 은 가장 높은 판의 것, `changed` 는 어느 판이든 바뀌었으면 참이다. 판 이름이 아니면 `versions` 는 빈 배열이다. **`versions` 는 대표(최신) 판 자신도 담는 계약이다.** 화면은 "이전 판" 목록에서 `path` 가 대표 파일과 같은 항목을 뺀다(판 이름 파일이 하나뿐이면 이전 판이 없다).
- `GET .../files/preview?path=` → md: `{kind:"md", text, truncated}`(200KB), xlsx(xlsm): `{kind:"table", sheets:[{name, rows[[값…]](200행×40열, 값만), truncated}]}`(날짜 서식 칸은 일련번호가 아니라 `YYYY-MM-DD`, 시간이 있으면 `YYYY-MM-DD HH:MM`, 시간만 있는 서식은 `HH:MM` 으로 낸다. `styles.xml` 의 `cellXfs` 서식 번호로 판정한다: 내장 14-17·22·18-21·45-47, 사용자 `numFmts` 중 y·d·h(또는 `mmm`)가 든 서식. `workbookPr date1904` 면 1904 날짜 체계. 바꿀 수 없는 값은 원래 글자 그대로), pptx: `{kind:"slides", slides:[{index, texts[]}]}`(슬라이드 번호 순, 문단마다 한 줄), 이미지: `{kind:"image", url}`, 그 밖 `{kind:"none"}`. 표준 라이브러리(`zipfile`+`xml.etree`)만 쓰며 openpyxl 은 쓰지 않는다. 깨졌거나, 부분 **전체**에 `<!DOCTYPE`·`<!ENTITY` 선언이 있거나(긴 주석 뒤에 숨긴 것도 찾는다), UTF-16/32 이거나 UTF-8 이 아닌 인코딩을 선언했거나, 부분 하나가 16MB 를 넘거나 미리보기 한 번에 푸는 합이 64MB 를 넘으면 읽지 않고 422 다. 모든 부분을 `iterparse` 로 읽는다. `GET .../files` 는 git 을 읽지 못하면 `unknown:true, reason` 을 더해 내고 화면이 "바뀐 문서를 확인하지 못했어요" 를 보인다(빈 목록과 구분).
- `GET .../files/raw?path=` → 이미지(png jpg jpeg gif webp bmp svg)만 내려준다(아니면 403, 20MB 넘으면 413). SVG 안의 스크립트가 돌지 못하게 `Content-Security-Policy: sandbox` 를 붙인다.
- `POST .../files/open {path, mode:"open"|"reveal"}` → 서버를 돌리는 컴퓨터에서 연다. Windows 는 `open` 이 `os.startfile`, `reveal` 이 `explorer /select,"경로"`(셸 없이, explorer 가 요구하는 한 줄), macOS 는 `open` / `open -R`, 그 밖은 `xdg-open`(reveal 은 폴더). **안전:** 경로는 `realpath` 후 작업 폴더 안만(밖이면 403, 없으면 404). `open` 은 확장자 허용 목록(md txt csv xlsx pptx docx pdf png jpg jpeg gif; 매크로를 담을 수 있는 xlsm·xls 와 스크립트를 담을 수 있는 svg 는 위치 보기만)만 되고 `.bat .cmd .exe .ps1 .js .vbs .lnk` 같은 것은 403 이다. 요청한 경로와 링크를 푼 실제 경로의 확장자가 둘 다 목록에 있어야 한다. `reveal` 은 위치만 보여 주므로 허용한다. 열기에 실패하면 502.

**같은 폴더.** 세션 필드 `sameFolder` 는 같은 작업 폴더(대소문자·구분자 차이를 같게 비교)에서 살아 있는 다른 세션 id 목록이다(끝난 세션, 프로세스가 죽은 콘솔 세션, 다음 세션으로 넘어간 세션(`handedOffTo`)은 뺀다). 세션이 뜨거나 끝나면 같은 폴더의 다른 세션 화면에도 `session` 이벤트가 간다. `POST /api/folders/worktree {cwd}` 는 아는 작업 폴더가 git 저장소의 맨 위 폴더일 때(아니면 400, 모르는 폴더 403) `git fetch origin` 뒤 `git worktree add --detach <부모>/<저장소이름>-wt-<6자리 id> origin/<기본 브랜치>` 로 작업용 폴더를 만들어 아는 폴더에 더하고 `{path}` 를 돌려준다. 기본 브랜치는 `origin/HEAD` 에서 읽는다. 브랜치는 만들지 않는다(start·srs·spec 스킬이 자기 이슈·브랜치를 만든다). 실패하면 502 와 git 오류 끝 300자를 돌려준다.

## 7c. 다음 갈래로 넘어가기 (`handoff.py`)

`POST /api/sessions/:id/flow/next {flowId}` → `202 {jobId}`. 콘솔이 띄운 세션만 된다(터미널 세션은 콘솔이 `/harness:handoff` 를 보낼 수 없어 409 와 안내. 없는 갈래·숫자 아닌 flowId 400, 이 폴더에서 못 쓰는 갈래 409, 같은 세션에 진행 중인 작업이 있으면 409). 뒤에서 이렇게 한다.
1. 지금 턴이 끝나기를 기다린다(최대 10분).
2. 그 세션에 `/harness:handoff` 를 보내 그 턴의 `result` 를 기다린다(최대 10분). 결과 글의 **마지막 코드 블록**(백틱 3개 이상 울타리, 비어 있지 않은 것)을 새 세션용 프롬프트로 뽑는다. 못 뽑거나 4000자를 넘으면 사유와 함께 멈추고 새 세션을 띄우지 않는다.
3. **사람이 확인한다.** job 을 `confirm`(확인 대기, `prompt` 포함)으로 두고 화면이 그 글을 보여 준다. 사람이 [이대로 새 세션 시작] / [고쳐서 시작](글을 고칠 수 있다) / [취소] 를 고른다. 시작은 `POST /api/jobs/:id/confirm {prompt?}`(없으면 뽑은 글 그대로, 비었거나 4000자 넘으면 400, `confirm` 이 아니면 409), 취소는 `POST /api/jobs/:id/cancel`. 확인 없이는 새 세션을 띄우지 않는다. 같은 세션에서 새로 넘기면 잊힌 확인 대기 job 은 취소된다.
4. 같은 폴더에서 새 콘솔 세션을 띄운다. 모델·에포트는 이전 세션 값을, 권한 모드는 허용 집합(기본·`acceptEdits`·`plan`) 안의 값만 이어받는다. 첫 메시지는 `새 세션 시작 점검: /harness:sync 로 최신을 받고, 플러그인 판(/harness:version)을 확인해 낡았으면 알려 줘(갱신은 사용자 버튼으로 한다). 그다음 인계 내용을 이어서: <뽑은 프롬프트>` 뒤에 그 갈래의 첫 단계 안내를 붙인다. 새 세션에는 그 갈래를 지정한다(실패하면 `warning`).
5. 새 세션 프로세스가 `init` 이벤트를 낸 것을 확인한 뒤에만(60초 안에 못 받으면 `failed`, 이전 세션은 닫지 않는다) 이전 세션에 `handedOffTo: <새 세션 id>` 를 적고(세션 화면에 "다음 세션으로 넘어감 → 새 세션 링크") 그 `claude` 프로세스는 stdin 을 닫아 정상 종료한다. 넘어간 세션은 `sameFolder` 계산에서 빠져 새 세션 화면에 "다른 세션이 일하고 있어요" 경고가 뜨지 않는다.

`GET /api/jobs/:jobId` → `{id, kind:"flowNext", status("handoff"/"confirm"/"starting"/"started"/"failed"/"canceled"), fromSession, flowId, prompt(confirm 일 때), sessionId(started 일 때 새 세션 id), error, warning}`. 작업은 메모리에만 있다(서버를 다시 띄우면 사라진다). 실패는 이전 세션 로그에도 남는다. 예외가 나도 job 은 `failed`(사유)로 끝나 세션이 '넘기는 중' 에 갇히지 않는다.

## 8. API

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/open` | 브라우저 열기 (쿠키 불필요) |
| GET | `/api/health` | `{app:"harness-console", version}` (쿠키 불필요) |
| GET | `/api/events` | SSE: `session`, `request`, `removed` |
| GET | `/api/sessions` | 목록(`updatedAt` 내림차순). 각 세션의 `group`: `todo` / `running` / `idle`. 필터는 화면이 한다 |
| GET | `/api/sessions/:id` | 상세. 로그, 결과 보고, 변경 파일, 서브에이전트, 스킬 흐름 |
| POST | `/api/sessions/:id/messages` | `{text}` 이어서 요청 |
| POST | `/api/sessions/:id/skills/:skill/run` | 스킬 실행. 본문 `{args?}`, 보내는 글은 `/harness:<skill> <args>` |
| PUT, DELETE | `/api/sessions/:id/skills/:skill/reservation` | 예약 |
| POST | `/api/sessions/:id/interrupt` | 콘솔이 띄운 세션 중단 |
| PUT | `/api/sessions/:id/flow` | 갈래 지정·변경. 본문 `{flowId, reason?}`, `flowId: null` 이면 해제. 없는 갈래 400, `requires` 조건이 거짓이면 409, 데이터를 못 쓰면 503. 응답은 세션 모델 |
| POST | `/api/sessions/:id/flow/skip` | 지금 단계 건너뛰기. 본문 `{reason}` 필수(없으면 400, 갈래가 없으면 409). 이유는 단계와 로그에 남는다 |
| POST | `/api/sessions/:id/flow/done` | 사람이 지금 단계를 끝냈다고 누름. `manual` 이 든 단계만 되고(아니면 409), 같은 단계의 다른 근거(변경 등)가 안 맞으면 409 |
| POST | `/api/sessions/:id/flow/refresh` | 병합처럼 세션 밖에서 일어난 일을 지금 다시 읽어 판정 |
| POST | `/api/sessions/:id/flow/next` | 다음 갈래로 넘어가기. 본문 `{flowId}`. `202 {jobId}` (§7c) |
| GET | `/api/jobs/:jobId` | 다음 갈래 넘기기 진행 상태 (§7c) |
| POST | `/api/sessions/:id/reload` | 플러그인 다시 불러오기(콘솔 세션만). `200 {ok, method, plugins, errorCount, harnessVersion}` / 턴 중 `202 {queued:true}` / 터미널·끝난 세션 409 / 실패 502 (§7b) |
| POST | `/api/reload-all` | 콘솔 세션 전부에 같은 일. `{results[]}` |
| POST | `/api/sessions/:id/checks/:cid/skip` | 새 세션 점검 항목(`sync`/`version`/`update`/`reload`)을 건너뜀으로 |
| GET | `/api/sessions/:id/files` | 만든 문서 목록(`{files[]}`, 판 묶음 `versions`) (§7b) |
| GET | `/api/sessions/:id/files/preview` | 쿼리 `path`. md·표·슬라이드·이미지·none 미리보기 |
| GET | `/api/sessions/:id/files/raw` | 쿼리 `path`. 이미지 원본만 |
| POST | `/api/sessions/:id/files/open` | `{path, mode:"open"/"reveal"}`. 작업 폴더 안·허용 확장자만 |
| POST | `/api/folders/worktree` | `{cwd}` → `{path}`. `git worktree add --detach` 로 작업용 폴더 만들기 |
| GET | `/api/flows` | 갈래·단계·도구·증거 설명 데이터. 쿼리 `cwd`(아는 작업 폴더, 아니면 403)를 주면 갈래·단계·도구마다 `exposure {visible, state(yes/no/unknown), reason}` 와 `conditions` 를 더한다 |
| GET | `/api/srs-status` | 쿼리 `cwd` 필수(아는 폴더만, 아니면 403). 작업 폴더 `docs/ssot/SRS.md` 의 요구사항별 Status(#718). `state` 는 `yes`(`items`: `REQ-002` → `{status, next}`) / `no`(SRS 없음) / `unknown`(git 실행 불가·파일 읽기 실패, `reason`). origin/main 이 아니라 작업 폴더 파일이라 작업 브랜치의 `In Process` 가 보인다. 캐시 없음 |
| GET | `/api/dev-ready` | 쿼리 `cwd` 필수(아는 폴더만, 아니면 403). 개발 준비 상태(#668). `state` 는 `yes`(읽음) / `no`(git 저장소가 아니거나 `audit/ledger/` 도 `docs/ssot/SRS.md` 도 없어 해당 없음) / `unknown`(git 을 못 실행·`git fetch origin main`·목록·SRS·원장 읽기 실패, `reason` 에 사유). `yes` 면 `specReady`(origin/main 에 `docs/spec/DEV-xxx-*.md` 가 있는 개발 건 수), `setup`(SRS 다음 단계가 `설정`·`표준` 이거나 옛 원장 Spec 칸이 `설정` 인 건 수), `standard`(그중 `표준` 건 수), `needSpec[{number, label}]`·`needSpecCount`(Spec 이 없는 개발 요구사항. 설정·Dropped/Duplicate/On Hold·원장 `완료`·다음 단계 미정은 뺀다), `items[]`(각 항목에 `setup`·`standard` 표시). 개발 건 = SRS 다음 단계가 `개발`, 또는 SRS 에 없는데 원장에 있는 건. 기준은 start 스킬·PR 검사 spec-ready 와 같다. 60초 기억, 요청 스레드는 기다리지 않는다(읽는 중이면 `loading: true`) |
| GET | `/api/approvals` | 쿼리 `cwd` 필수. `{state(yes/no/unknown), reason, login, items[{number, title, url, author, staleApproval}]}`. 내가 승인자이고, 작성자가 내가 아니고, 초안이 아니고, 최신 커밋을 내가 아직 승인하지 않은 열린 PR(번호순, 병합 순서는 계산하지 않는다). 60초 기억. GitHub 저장소가 아닌 폴더는 `no`. 홈은 세션 폴더를 저장소별로 묶어 부르고, 전부 `no` 면 칸을 안 보이며 gh 자체 실패(`unknown`)만 "판정 불능" 으로 보인다 |
| PUT | `/api/sessions/:id/permission` | 세션 도중 권한 모드 바꾸기. body `{mode}`, 허용 3종(`""`·`acceptEdits`·`plan`) 밖은 400, 터미널 세션은 409, claude 가 거절하거나 답이 없으면 502 |
| GET | `/api/requests/:rid` | 승인·질문 내용. 요청 모델에 `sessionTitle`, `suggestions` 가 더해진다 |
| POST | `/api/requests/:rid/answer` | 승인 `{decision: allow / allow_session / deny, reason?}`, 질문 `{answers:{질문:답}}` |
| POST | `/api/new` | 분석 시작 |
| GET | `/api/new/:id` | 상태, 결과 |
| POST | `/api/new/:id/start` | 작업 시작. 세션이 실제 id 를 얻을 때까지 최대 8초 기다려 그 id 를 돌려준다 |
| GET | `/api/new/:id/preview` | 첫 메시지 미리보기. 쿼리: `picked`(반복), `extraAnswers`(JSON 문자열), `note` |
| GET | `/api/folders/recent` | 최근 작업 폴더 |
| POST | `/api/folders/validate` | `{path}` |
| POST | `/api/folders/pick` | 서버 컴퓨터에 OS 폴더 선택 창(Windows PowerShell, macOS `osascript`)을 띄운다. 응답 `{path}`, 취소하면 `{cancelled:true}`. 창이 이미 열려 있으면 409, 못 띄우거나 10분을 넘기면 503(경로를 직접 적으라는 안내). 그 밖의 OS 는 503 |
| GET | `/api/models` | 모델·에포트·권한 모드 선택지: `options`, `default`, `effortOptions`, `defaultEffort`, `customPattern`, `permissionOptions` |
| GET | `/api/skills` | `{plugin, skills[{name, description}]}`. `update`·`scaffold`·`open` 은 빠진다. 스킬 버튼 줄과 `/` 자동완성이 쓴다 |
| GET | `/api/files` | `@` 멘션용 파일 찾기. 쿼리 `root`(아는 작업 폴더, 아니면 403), `q`(경로에 든 글, 대소문자 무시). 응답 `{root, files[], truncated}`. 결과 50개, 탐색 2만 파일 상한, 큰 폴더와 밖을 가리키는 링크는 뺀다 |
| GET | `/api/fs` | 쿼리 `root`, `dir`. 응답 `{root(realpath), dir, entries[{name, kind: dir/file, size}]}`. `dir` 은 요청 값의 앞뒤 슬래시만 뗀 것, 폴더가 앞이고 이름순, `.git` 과 작업 폴더 밖을 가리키는 링크는 뺀다, 최대 2000개, 폴더의 size 는 0 |

세션 모델: `id, title, cwd, repo, branch, managed, status(starting/running/waiting/idle/ended), group, permissionMode, bypassPermissions, currentSkill, currentAction, startedAt, updatedAt, log[{time,text}], report, changedFiles[], prLinks[], subagents[], flow[{skill,state,reserved,disabledReason?}], turnSkill, turnUnknown, pendingRequestIds[], canSend, cannotSendReason`, 갈래 필드 `flowId, flowName, flowReason, stepIndex, flowSteps[{id, name, kind, skill, helperSkill, hint, onlyIf, state, reason}], flowFinished, flowUnknown[], flowPr {number, state, url, title, checks(pass/fail/pending/none)}, nextFlow`(갈래가 없으면 `flowId: null`), 그 밖에 `pluginVersions[{name,version}], sameFolder[], handedOffTo(다음 세션으로 넘어갔으면 새 세션 id, 아니면 null), startChecks[{id,state}]`(§7b·§7c).

- 시간 값(`startedAt`, `updatedAt`, 로그의 `time`, 요청의 `createdAt`·`answeredAt`)은 epoch **초**(소수 포함)다. 화면이 경과 시간을 계산한다.
- `turnSkill` 은 `이번 차례`(§7)의 `start`/`deliver`/`prs`/없음, `turnUnknown` 은 `gh` 로 PR 을 보지 못해 판단이 불완전했다는 뜻이다. `bypassPermissions` 는 `permissionMode == "bypassPermissions"` 다.
- `status` 는 끝난 터미널 세션 → `ended`, 대기 요청 있음 → `waiting`, 턴 실행 중 → `running`, 띄우는 중 → `starting`, 끝난 콘솔 세션 → `ended`, 그 밖 → `idle` 순으로 정한다.
- 요청 모델: `id, sessionId, kind(permission/question), toolName, toolInput, hasSuggestions, status(pending/answered/closed), outcome, createdAt, answeredAt` 이고 질문에는 `questions` 가 더해진다. 완료된 요청은 최근 200개만 남긴다.
- 승인 답변에서 `allow_session` 은 `permission_suggestions` 가 없으면 400, 거부 사유가 비면 "콘솔에서 거부했습니다." 를 쓴다. 질문 답변은 모든 질문에 빈 값이 아닌 답이 있어야 하고(없으면 400) 배열은 `", "` 로 잇는다. 이미 처리된 요청에 답하면 409 와 처리 결과를 돌려준다.
- 실행 중이 아닌 터미널 세션에 메시지·스킬·예약을 보내면 409 와 이유를 돌려준다. 예약은 턴 끝에 한 번 꺼내 쓰고 `sessions.json` 에 함께 저장된다.

`askedInText` 는 §7 의 글로 물은 경우 추정이다. `group` 은 대기 중인 요청이 있거나 `askedInText` 이거나 `turnSkill` 이 있고 턴이 끝났으면 `todo`, 턴 실행 중이면 `running`, 그 밖에는 `idle` 이다. 제목은 SessionStart 의 `session_title` → 첫 요청 글 첫 줄(`/` 로 시작하는 글은 제외) → 폴더 이름 순이고 60자로 자른다. 로그는 세션당 200개, 한 줄 500자로 자른다. 훅이 모은 변경 파일은 `Write`·`Edit`·`MultiEdit`·`NotebookEdit` 의 PostToolUse 에서, PR 링크는 PostToolUse 의 도구 응답에서 `github.com/.../pull/N` 을 찾아 모은다. 최근 작업 폴더는 20개까지 기억한다.

## 9. 화면

디자인은 시안(`design-canvas/project/`)을 그대로 옮긴다. 경로: `/`, `/s/:id`, `/r/:rid`, `/new`, `/settings`, `/docs`. 한 페이지 앱이고 서버는 이 경로 모두에 `index.html` 을 준다.

- 이름과 문구: 화면 이름은 "Blueward Harness" 이고 로고(`static/logo-sauce.png`, 흰 글자 + 네온 네모)를 헤더 왼쪽에 둔다. 화면 문구는 "Claude" 대신 "Claude Code" 로 쓴다. 상단의 서버 주소 표시는 두지 않는다.
- 앱 틀(#636, 디자인 "Sauce"): 위에서부터 **알림 띠 → 헤더 → (왼쪽 세션 목록 + 본문)**.
  - 알림 띠(`.ann`): 사용자가 할 일(대기 중인 질문·승인 요청, 답을 기다리는 세션 = 사이드바의 '내 차례')이 있을 때만 뜬다. "내 차례 N건 — <세션 이름>에서 답이 필요해", 누르면 그 요청(`/r/:rid`)이나 세션으로 간다. 할 일이 없으면 띠 자체를 만들지 않는다.
  - 헤더: 로고 · 메뉴 · 오른쪽에 프로젝트 이름(지금 화면이 다루는 폴더만: 새 작업은 고른 작업 폴더, 세션·질문·승인은 그 세션의 저장소 이름. 그 밖의 화면은 열린 세션의 프로젝트가 하나뿐일 때만 보이고 여럿이면 비운다 — 예전에는 가장 위 세션 것을 보여 줘서 새 작업 화면의 폴더와 달랐다)과 설정 버튼. 메뉴 ↔ 경로: `내 일` → `/`, `작업` → 가장 위 세션 `/s/:id`(내 차례가 먼저, 세션이 없으면 메뉴에서 뺀다), `새 작업` → `/new`, 설정 → `/settings`. `산출물` → `/docs`(셋째 덩어리).
  - 왼쪽 세션 목록(230px): 줄마다 기억(context) % 링 + 세션 이름 + 단계 막대(끝난 것 / 지금 / 남은 것, 갈래가 없으면 생략) + 한 줄 상태(내 차례면 노랑 `!`). 정렬은 내 차례 → 일하는 중 → 쉬는 중 → 끝난 세션. **기억 링(#648)**: 서버가 준 `context.pct` 가 있으면 채워진 링 + `NN%`(80% 초과 노랑, 90% 이상 빨강), 토큰 수만 알면 점선 링에 `24만`, 못 읽었으면 점선 보라 `?` 와 "기억 사용량 확인 못 함" 툴팁이다(기억 사용량 계산은 아래 "기억 사용량" 항목). 세션이 없으면 점선 상자와 `+ 새 세션`(새 작업으로). `[` 키로 접고(입력칸에 포커스가 있으면 동작하지 않는다) 접힌 상태를 기억한다. 760px 이하에서는 헤더가 줄바꿈되고 세션 목록이 본문 위로 쌓이며 가로 스크롤이 없다.
- 홈(`/`): 세션이 없으면 "아직 시작한 작업이 없어", 자주 하는 일 버튼 6개(누르면 새 작업 입력칸에 그 종류의 문장을 미리 넣어 `/new` 로 간다. 새 작업 화면이 종류를 인자로 받지 않는다), 하고 싶은 일 입력창(적은 글을 새 작업으로 넘긴다), 숫자 타일(내 차례·일하는 중·만든 산출물 — 산출물 수는 구할 수 없어 "확인 못 함"). 세션이 있으면 "오늘 내 일": 숫자 타일(내 차례 / AI가 일하는 중 / 쉬는 중 / 승인 기다리는 PR — 승인자일 때만, gh 실패는 "확인 못 함"), 내 차례 노랑 카드("가서 답하기·가서 승인하기". 가장 오래 기다린(`updatedAt` 이 가장 작은) 한 건만 카드로 두고, 나머지가 있으면 카드 아래 "외 n건" 알약을 눌러 펼치고 다시 눌러 접는다. 펼침 상태는 홈 화면에서만 기억한다), "내 세션" 표(작업·단계 막대·번호·기억·상태 칩). 번호 칸은 브랜치 이름에서 읽은 "이슈 #N" 과 PR 상태만 채우고 REQ/DEV 번호는 서버가 주지 않아 비워 둔다. 기억 칸은 세션 목록 링과 같은 값(`92%` / `24만 토큰` / `?`)이다. 그 아래 내가 승인할 PR 카드(GitHub 저장소가 있고 내가 승인자일 때만. gh 실패는 "판정 불능")와 프로젝트 준비 안내. 갈래를 고르지 않은 세션은 "정해진 갈래 없음" 으로 보인다.
- 세션 화면: 현재 스킬과 행동, 경과 시간(실제 계산), **갈래 순서 막대와 방향별 다음 단계 버튼**(지금 단계의 스킬만 누를 수 있고, 건너뛰려면 이유가 필요하며, "끝났어요" 는 git·gh 근거를 확인한다. 끝나면 SRS "다음 단계" 열 값에 따라 방향별 버튼이 나온다), **항상 열린 도구 줄**(판 보기·최신 받기·플러그인 갱신·인계·남은 일·내 PR·다시 불러오기·내가 승인할 PR; 갈래와 상관없이 쓴다), **결과 보고**(마크다운을 안전하게 표시), **만든 문서**(저장소 기준 상대 경로로 보이는 목록·이전 판·md/xlsx/pptx 미리보기·열기·위치 보기. 커밋해도 이 세션이 만든 문서는 남는다), 변경 파일, PR 링크, 로그, 이어서 요청 입력칸, `기술 정보 보기`. 쉬는 터미널 세션은 막는 이유를 보여 준다.
- 작업 화면(#636 둘째 덩어리: 세션 `/s/:id`, 질문·승인 `/r/:rid`, 새 작업 `/new`): 위에서부터 **제목 블록**(`<갈래> · 지금 하는 일` 라벨, 세션 이름 h1, 한 줄 상태·경과 시간) → **순서 알약**(끝난 ✓ / 지금 네온 / 남은 것, 끝나면 `→ 다음: …`. 이름은 `workflow.json` 단계의 `short`, 없으면 괄호 설명만 뗀 이름이고 전체 이름은 title) → **숫자 띠**(단계 · AI 진행 · 요구사항 · 개발 번호 · 작업 기록(이슈) · 검토 요청(PR)) → **밝은 대화 판**(AI 결과 보고 · 이 일의 순서 체크리스트 · 검토 요청 줄 · 내가 보낸 말 · 노랑 라벨의 어두운 "네 차례" 카드 · 작업 멈추기 · 입력창 알약)과 **오른쪽 만든 산출물**(넓을 때 옆, 1000px 이하에서는 아래). 도구 줄·폴더 알림·서브에이전트·권한 모드·바뀐 파일·기록·기술 정보는 아래 어두운 바탕에 그대로 있다. **데이터가 없는 칸은 지어내지 않는다**: 숫자 띠 칸은 있는 것만 만들고(요구사항·개발 번호는 끝난 갈래의 다음 갈래 옵션에 든 `REQ-xxx`, 이슈는 브랜치 이름, PR 은 갈래 데이터), AI 진행 %는 순서의 끝난 단계 수 ÷ 전체 단계 수이며 칸에 마우스를 올리면 그 근거가 나온다. AI 의 별도 할 일 목록은 데이터에 없어서 "이 일의 순서"(갈래 단계)를 체크리스트로 보인다. 검토 요청 줄은 검사가 한 값(`checks`)뿐이라 "자동 검사(문서·비밀값 등)" 한 줄, 팀 승인은 PR 상태(열림/합쳐짐/닫힘)에서만 읽는다.
  - 질문: 질문 하나마다 흰 카드(`.q`)에 라벨 · 질문 글(한 번만) · 알약 보기(`.qopt`, 고른 것은 ✓ + 반전). 위 제목은 세션 이름이라 질문 문장이 두 번 나오지 않는다(#635).
  - 승인: 시안 17 의 "확인 필요" 카드. 한 줄 요약은 바로 보이고 명령 원문·입력 전체는 "자세히" 에 있다. 쉬운 설명(`description`)이 있는 Bash 만 접어 두고, 설명이 없거나 샌드박스를 끄거나 백그라운드로 도는 명령, 파일을 쓰고 고치는 도구는 열어 둔다(무엇을 허락하는지 가려지지 않게). 버튼은 `이번만 허락` / `하지 마` / `허용하고 이 세션에서 다시 묻지 않기`. Edit 은 `원래 글` / `바꾼 글`(#634).
  - 새 작업: 종류 버튼 10개(누르면 입력칸에 문장을 미리 넣고, 갈래가 있는 종류는 그 갈래로 시작하도록 정해 둔다) → 한두 줄 입력 → 참고 파일 안내(`@` 로 작업 폴더의 파일 고르기. 끌어다 놓기·올리기는 없다) → "이렇게 진행돼"(고른 갈래의 단계 칸) → 작업 폴더 → 접힌 "고급 설정"(모델·에포트·권한 모드) → `작업 시작`. 분석 뒤 확인 화면(06)은 내 말 · AI 이해 · 갈래 · 읽을 자료 · 물어볼 것 · `이대로 시작`.
  - **종류 버튼과 개발 준비 상태(#668).** 작업 폴더가 `audit/ledger/` 또는 `docs/ssot/SRS.md` 를 가진 Project Repository 이면 종류 버튼 밑에 작은 글이 붙는다(`GET /api/dev-ready`). `개발하기`: Spec 있는 개발 건 수(0 이면 버튼이 흐려지고 "Spec 있는 건 없음 — 개발 Spec 먼저"), `개발 Spec`: Spec 이 없는 개발 요구사항이 있으면 강조 + "할 차례 REQ-001(제목)", `설정하기`: 설정 건 수(`setup - standard`), `표준 기능으로 처리`(갈래 `standard`, 설명 "SAP 표준 앱으로 끝나는 건"): 표준 건 수(`standard`). 홈의 자주 하는 일에는 `설정하기` 가 없으므로 표준 종류도 넣지 않았다. 설정·표준 갈래 세션 화면의 숫자 띠에는 "SRS 상태" 칸이 붙는다(`GET /api/srs-status?cwd=` 가 작업 폴더의 `docs/ssot/SRS.md` 를 읽어 `{state, items: {"REQ-002": {status, next}}}` 를 준다. 캐시 없음. 요구사항 번호는 다음 갈래 옵션의 REQ 번호, 없으면 세션 이름의 `REQ-`·`DEV-` 번호. 못 읽거나 번호를 못 찾으면 "확인 못 함"). 해당 없음(원장도 SRS 도 없는 저장소·git 저장소 아님)이나 확인 못 함(git 실패)이면 아무 표시도 하지 않고 개발을 막지도 않는다. 종류 버튼의 갈래는 더는 "사용자가 확정한 선택" 이 아니다: 분석 결과의 AI 갈래(`flow.id`)가 다르면 "이렇게 진행할게" 화면 맨 위에 묻는 카드("AI 는 **개발 Spec** 부터 하자고 해 — 이유")가 뜨고 `[개발 Spec 쪽으로 바꾸기 (추천)]` `[그래도 개발하기]` 에 답해야 시작할 수 있다. Spec 없음이 확실한데(읽었고 Spec 있는 건이 0) `그래도 개발하기` 를 누르면 "Spec 없이 개발은 시작할 수 없어. PR 검사(spec-ready)에서도 막혀" 를 보이고 개발 갈래로 시작하지 않는다. 확인 못 함이면 AI 추천 카드만 뜨고 막지 않는다. `개발하기` 를 누른 순간(분석 전)에도 Spec 없음이 확실하면 같은 카드가 입력칸 위에 바로 뜬다. 종류를 고르지 않았으면 예전 그대로(AI 갈래, 확신 없으면 두 후보 묻기).
- 승인 화면(`/r/:rid`)의 Bash "명령" 칸은 줄바꿈을 그대로 보인다(`white-space: pre-wrap`, 긴 줄은 접고 높이는 스크롤, #619).
- 새 세션 점검: 콘솔이 새로 띄운 세션에는 최신 받기·판 확인·갱신·다시 불러오기 체크리스트가 뜨고(건너뛸 수 있다), 하나씩 `done` 이 된다.
- 같은 폴더 알림: 같은 폴더에서 다른 세션이 일하고 있으면 알리고 "이 작업용 폴더 따로 만들기" 를 준다. 다음 세션으로 넘어간 세션은 알림에서 빠지고, 그 세션 화면에는 "다음 세션으로 넘어감 → 새 세션 링크" 가 뜬다.
- 쉬운 말: 화면에서는 git 용어를 숨긴다(이슈 = 작업 기록, 브랜치 = 작업 공간, 커밋·푸시·PR = 올리고 검토 요청하기, 병합 = 합쳐지기). 다만 srs·spec·start 스킬은 **각각** 시작할 때 이슈와 브랜치를 만든다고 단계 설명에 정확히 적는다.
- 승인, 질문, 새 작업(입력 → 분석 중 → 자료 확인), 설정: 시안대로. 처리된 요청은 "터미널에서 처리됨" 처럼 결과를 보여 준다.
- 새 작업 입력: 작업 폴더 기본값은 ① 세션·질문 화면의 `새 작업`·`+ 새 세션` 으로 왔으면 그 세션의 폴더(`/new?from=<세션 id>`) ② 아니면 콘솔에서 마지막으로 작업을 시작한 폴더(`GET /api/folders/last`, 상태 폴더 아래 `last-folder.json`, 작업 시작 때 서버가 쓰고 지금 없는 폴더는 무시) ③ 둘 다 없으면 기본값 없이 폴더 목록을 펼친다. 다른 세션의 활동으로는 정하지 않는다(`/api/folders/recent` 는 고르는 후보 목록일 뿐). 바꿀 때는 최근 폴더에서 고르거나 경로를 적거나 `폴더 찾아보기`(`POST /api/folders/pick`)로 고른다. 모델, 에포트(생각의 깊이), 권한 모드(기본 / 파일 고치기 자동 허용 / 계획만)를 고른다. 모델·에포트는 분석과 작업 세션이 같이 쓰고 권한 모드는 작업 세션에만 쓴다.
- 입력칸 보조: 예전의 스킬 버튼 줄은 없다(위 순서 막대·도구 줄이 대신한다). 스킬 이름은 `GET /api/skills` 로 받아 입력칸에서 `/` 를 치면 스킬, `@` 를 치면 작업 폴더의 파일(`GET /api/files`) 후보가 뜬다. `@` 경로에 공백이 있으면 후보 삽입 뒤 멘션이 공백에서 끊긴다(알려진 한계).
- 글자 크기 3단계(작게 0.9 · 보통 1 · 크게 1.15, 보통 = 시안 크기)는 `localStorage` (`bh-zoom`)에 저장한다(#721: 옛 `bh-scale` 은 보통이 1.15 였어서 읽지 않는다). 본문은 폭 상한 없이 오른쪽 끝까지 찬다(#721). 접근이 막혀도 기본값으로 동작한다. 테마·디자인 고르기는 없다(#636: 옛 테마 11개와 디자인 A·B·C 를 걷어내고 "Sauce" 한 벌로 합쳤다). 설정 화면은 아래 "셋째 덩어리" 항목을 본다.
- 셋째 덩어리(#636: 산출물 `/docs`, 설정, 막힘·확인 못 함, 새 세션 점검, 프로젝트 고르기, 표시 약속):
  - 산출물(`/docs`): 새 서버 API 없이 최근에 바뀐 세션 12개의 `GET /api/sessions/:id/files` 를 모아(같은 폴더의 같은 파일은 한 번만) 왼쪽에 **요구사항 · 설계**(md) / **고객 양식**(xlsx·pptx·docx·pdf) / **기록**(`audit/`) / 기타로 묶는다. 칩은 근거가 둘뿐이다: 커밋 안 된 파일 = `안 올림`, 커밋된 파일은 그 세션의 PR 상태가 OPEN = `검토 중`, MERGED = `합쳐짐`. 근거가 없거나 git 을 못 읽었으면 `확인 못 함`(보라 점선). 오른쪽은 미리보기(세션 화면의 문서 칸과 같은 미리보기 조각) + `열기` · `폴더에서 보기` + md 에만 `고객 양식으로 뽑기` + "고쳐 달라고 하기" 입력칸. 뽑기·고치기는 콘솔이 직접 하지 않고 그 문서를 만든 세션에 말을 보낸다(`POST /api/sessions/:id/messages`). xlsx·pptx·docx 를 고르면 결과 카드(종류 · 이름 · 크기 · 시각 · 폴더에서 보기 · 열기). 양식 칸을 채운 수나 비어 있는 칸 같은 값은 서버가 주지 않아 보이지 않는다.
  - 막힘 · 확인 못 함: 콘솔은 훅이 막은 결과(문서 검사 차단 등)를 받지 못한다(훅은 상태 이벤트만 보낸다). 그래서 데이터가 있는 곳만 모양을 쓴다 — 검토 요청(PR) 카드에서 자동 검사가 실패면 빨간 실선 테두리 + `✕ 막힘`, 검사 결과를 못 읽었으면 보라 점선 테두리 + `? 확인 못 함`("통과도 실패도 아니야"). 홈 맨 아래에 표시 약속(✕ 막힘 / ? 확인 못 함 / ! 내 차례) 범례를 작게 둔다.
  - 위험한 일 확인(시안 17): 명령이 되돌릴 수 없는지 판정하는 코드가 콘솔에 없다(`req.risk` 같은 값을 서버가 주지 않는다). 그래서 승인 카드는 모든 명령에 같은 "확인 필요" 모양이고, 샌드박스를 끄는 명령만 기존대로 경고 줄을 붙인다. 판정 근거가 생기면 노랑 `확인 필요 · 되돌릴 수 없어` 라벨을 쓴다.
  - 기억 사용량(#648, 시안 18): 훅 입력의 `transcript_path`(절대 경로의 `.jsonl` 만)를 세션의 `transcriptPath` 로 저장한다(터미널·콘솔 세션 모두 같은 훅). 세션 모델에 `context: {tokens, window, pct}` 를 싣는다. `tokens` 는 `context_usage.py` 가 jsonl 을 **끝에서 거꾸로** 읽어 찾은 마지막 `assistant` 줄(`isSidechain` 아님, `<synthetic>` 아님, 합 0 은 건너뜀)의 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 이다(`output_tokens` 제외). 파일의 mtime·크기가 같으면 다시 읽지 않고, 64MB 를 거꾸로 읽어도 없거나 읽기 실패면 `null`(확인 못 함). `window` 는 jsonl 에 없어서 **공식 문서에 적힌 모델만** 쓴다(https://code.claude.com/docs/en/model-config, 2026-11-04 확인): Fable 5 이상·Sonnet 5 이상·Haiku 5.5 이상·Opus 4.7 이상 = 100만, Opus 4.6·Sonnet 4.6 = 20만(이름이나 고른 값에 `[1m]` 이 있으면 100만), 그 밖은 `null` → `pct` 도 `null`. 한계: 세션 쪽 `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` 같은 설정으로 창을 줄였는지는 알 수 없다. 화면: 세션 화면 위 배너("이 세션 기억이 거의 찼어 (92%)", 90% 이상일 때만. [새 세션으로 넘기기] = 지금 갈래를 새 세션에서 이어 가는 기존 인계(`/flow/next`, 콘솔 세션 + 갈래가 있을 때만. 터미널 세션이면 버튼 대신 `/harness:handoff` 안내), [계속하기] = 이 화면을 다시 열 때까지 닫음), 숫자 띠 "기억" 칸, 갈래가 끝난 뒤 다음 일 카드의 "이 세션이 기억을 64% 썼어요" 문장. 값이 없으면 `?`·"확인 못 함" 이고 배너는 없다. 조사 기록은 `docs/status/636-console-design-rest.md`, 구현 기록은 `docs/status/648-console-context-usage.md`.
  - 새 세션 점검(시안 13): 대화 판 맨 위 카드에 `✓` 동그라미 · 이름 · 상태 · (다시) 하기 한 줄씩. 세션 화면 아래 옛 칸(도구 버튼 줄 · 권한 모드 · 검토 요청 주소와 바뀐 파일 · 일어난 일 기록 · 기술 정보)은 "자세히" 한 칸에 접는다(기능은 그대로).
  - 프로젝트 고르기(시안 02): 새 작업의 작업 폴더 고르기가 이니셜 상자 + 이름 + 경로 줄이다. 첫 실행 감지(시안 01)와 "표준 구조 만들기" 버튼(시안 03)은 데이터·기능이 없어 만들지 않았다(프로젝트 준비 안내는 홈의 기존 카드와 도구 줄 그대로).
  - 첫 화면 · 자동 점검(시안 01): 서버 API `GET /api/start-checks[?refresh=1]` 와 `POST /api/start-checks/seen`. **첫 실행** 표시는 상태 폴더(`platform_compat.state_dir()` = `CLAUDE_PLUGIN_DATA` 또는 `~/.claude/harness-console`) 아래 `first-run.json` — `시작하기` 를 누르면 서버가 쓰고(브라우저 `localStorage` 가 아니라 브라우저를 바꿔도 같다), 파일이 있으면 다시 안 뜬다. 점검은 열 때마다 서버가 백그라운드로 하고(60초 기억, `refresh=1` 은 기억을 지우고 다시, 읽는 중이면 `loading: true`) 화면은 늦추지 않는다. 항목과 판정: ① GitHub 연결 = `gh api user --jq .login`(승인자 판정이 쓰는 호출과 같은 근거). 성공 = ok, `gh` 가 없거나 출력에 `gh auth login`·`not logged in`·`401` 등이 있으면 **fail(막는 문제)** + 고치는 법, 그 밖(시간 초과·네트워크)은 unknown. ② 하네스 판 = 실린 판(`/api/health` 값)과 원격 최신 `v*` 태그(`hooks/update_notice.py` 의 `ls_remote_tags`·`latest_version`, `installed_version.py --remote` 와 같은 것, 5초 제한). 옛 판 = **old(막지 않는 문제)**: 홈을 그대로 열고 맨 위 `.ann` 띠에 "하네스 새 판 X이 있어 — 터미널에서 /harness:update" 한 줄(내 차례 띠와 함께 있으면 둘 다 보인다). 원격을 못 읽으면 unknown("최신 판은 확인 못 함"), 문제로 치지 않는다. ③ Claude Code 로그인 = 세션을 띄우는 것과 같은 claude 로 `claude auth status --json` 을 불러 `loggedIn` true 면 ok, false 면 fail(막는 문제, `claude auth login` 안내), claude 를 못 찾거나 JSON 을 못 읽으면 unknown(#721). 이메일 등 계정 정보는 화면에 옮기지 않는다. 화면: 첫 실행이거나 fail 이 있으면 헤더·목록 없이 가운데 밝은 판(`.intro-box`: 점검 줄 `.crow`, 이렇게 써 1·2·3, 버튼). fail 이면 제목이 "먼저 고칠 게 있어", 버튼은 `다시 점검`·`그냥 열기`(이번 열림만 건너뜀, 표시는 남기지 않는다). 설정의 `처음 화면 다시 보기` 는 표시를 지우지 않고 01 로 보낸다.
  - 첫 실행 흐름 01 → 02 → 03/04(시안 G-01~04, #721): 01 의 `시작하기` 는 곧바로 홈으로 가지 않고 **02 프로젝트 고르기**(같은 `data-intro` 모드, 가운데 밝은 판 하나)를 연다. 02 는 눈썹 "1단계 · 프로젝트 고르기", 최근 폴더 카드(`GET /api/folders/recent`, 이니셜 상자 · 이름 · 경로 · 준비 칩), 점선 "다른 폴더 찾아보기"(`POST /api/folders/pick` → `/api/folders/validate`)와 경로 직접 입력, `[뒤로]`(01 로) · `[이 프로젝트로]`(고르기 전엔 비활성)다. 카드를 누르면 고름 표시만 하고, `[이 프로젝트로]` 가 ① `POST /api/folders/last` {path} 로 서버에 마지막 폴더를 기억시키고(실제 폴더가 아니면 400, 쿠키 인증 필요, 최근 폴더에도 오른다. 응답 `{path, name}`) ② `POST /api/start-checks/seen` 으로 첫 실행 표시를 남긴다. 그다음 폴더가 준비 필요이고 `GET /api/folders/intro` 가 `show: true` 면 새 작업 화면(`/new`)이 03 프로젝트 준비 안내를 띄우고, 아니면 04 빈 홈으로 간다. 최근 폴더가 없으면 카드 대신 "최근에 쓴 폴더가 없어…" 한 줄. 04 빈 홈 제목 아래 줄은 서버가 기억한 마지막 폴더가 준비됨일 때 "프로젝트 준비 끝 · 이름", 아니면 기존 안내 문장이다.
  - 질문 · 승인 화면(시안 G-07·17): 카드 위에 그 세션의 최근 대화(내 말 · AI 말, 세션 상세 `chat` 의 마지막 3개)를, 카드 아래에 "AI에게 말하기" 입력창(세션 화면의 이어 요청과 같은 `POST /api/sessions/<id>/messages`, 보낼 수 없으면 비활성 + 이유)을 둔다. 질문의 직접 쓰기 칸은 보이는 글 없이 입력칸 하나. 되돌릴 수 없는 일의 단추 글은 행동을 말한다(지우기 → 이번만 지워 / 지우지 마, GitHub 올리기 → 이번만 올려 / 올리지 마, 그 밖 → 이번만 허락 / 하지 마). "하지 마" 이유 입력칸은 `이유 적기(선택)` 안에 접혀 있다.
  - 설정(시안 19): 글자 크기(`.seg`, 시안대로 작게/보통/크게, #721) · AI가 묻는 범위(`.radio`, 새 작업의 기본 권한 모드 = `bh-permission`) · 연결 상태(GitHub = `/api/approvals` 를 읽을 수 있는지, 하네스 판 = `/api/health`, 프로젝트 = `project-ready` 조건; 못 읽으면 "확인 못 함") · 고급(`details`: 모델 · 생각 깊이). 화면 밝기(다크 한 벌뿐)는 넣지 않았다. 알림은 아래 "알림 상태와 터미널로 넘어간 요청(#792)" 를 따른다.
- 디자인 "Sauce"(#636): 색은 `app.css` 맨 위 `:root` 한 곳에만 있다. 흑요석 배경 `#132322`·패널 `#0e1a19`·깊은 `#070f0f`, 네온 그린 `#3ddc91`(accent)·민트 `#97ddbc`, 밝은 판 `#edf7f5`(글자 `#132322`), 신호 노랑 `#ffcd48`(내 차례), 위험 `#e5484d`, 확인 못 함 보라 `#8b7cf6`. 알약 버튼 56px, 카드 20px, 큰 판 40px. 대문자 모노 라벨(`.eb`) 10px, 제목 20px, **어떤 글자도 22px 를 넘지 않는다**(시험이 CSS 에서 확인). 체크박스·select 화살표는 기본 모양을 쓰지 않고 직접 그린다. 라벨 글꼴은 외부 글꼴(IBM Plex Mono)을 받을 수 없어(CSP `font-src 'self'`) 내장 JetBrains Mono 를 쓴다. 상태는 색과 모양을 함께 쓴다: 지금(채운 점) / 끝남(✓) / 내 차례(노랑 !) / 실패(빨강 ✕) / 확인 못 함(보라 점선 ?). 글자 대비는 4.5:1 이상이고 시험이 CSS 값에서 계산한다. 이번 판은 앱 틀과 홈만 새 배치이고, 세션·질문·승인·새 작업·설정 화면의 배치는 그대로이며 새 색·글꼴만 입는다.
- 글꼴(#611): Pretendard(본문)와 JetBrains Mono(코드)를 `static/fonts/` 에 담았고(OFL 라이선스 파일 동봉) `app.css` 의 `@font-face` 가 `/fonts/…` 로 불러온다. 서버는 `.woff2` 를 `font/woff2` 로 내보내고 `fonts/` 한 단계만 연다. 바깥 글꼴 서버로 가는 `<link>` 는 CSP 가 막아 왔으므로 `index.html` 에서 뺐다.
- 금지: 그라데이션 배경, 유리 효과, Pulse 복제, 터미널 버튼. 시안의 샘플 데이터를 코드에 남기지 않는다. 빈 상태 화면을 만든다.

## 9a. 시안 대조 검사 (`checker/tests/console_mockup/`, #764)

"시안과 같은가" 를 눈대중이 아니라 숫자로 판정한다. **"시안 대조 완료" 는 이 검사 통과로만 기록한다**(스크린샷을 눈으로 본 것, "비슷함", 일부 요소만 잰 것은 완료가 아니다. 상태 기록·PR 본문에는 검사를 돌린 명령과 통과한 화면 번호를 적는다). 검사를 못 돌렸으면(브라우저 없음 등) "대조 못 함" 이라고 적고 통과로 쓰지 않는다.

- **기준 파일** `baseline.json`: 시안 G-01~24(`*.dc.html`)를 1440·1280 너비로 열어 요소 30종 안팎(헤더·로고·사이드바·본문·제목·알약·숫자 띠·밝은 판·대화·카드·단추·입력칸·오른쪽 칸 등)의 위치·크기·글자 크기·안쪽 여백·모서리를 CSS px 로, 배경색·글자색을 computed 문자열로 저장한 것. 시안이 바뀌면 `python -m checker.tests.console_mockup.extract_baseline <시안 폴더>` 로 다시 뽑아 같은 PR 에 넣는다(시안 폴더는 저장소 밖 디자인 도구 쪽에 있다).
- **요소 대응표** `elements.py`: 시안과 콘솔이 같은 클래스를 쓰는 것이 기본이고 다른 것만 따로 적는다(시안 `.steps` ↔ 콘솔 `.stepbar.big`, 시안 `.nav` ↔ 콘솔 `.topnav`, 시안 `.tile` ↔ 콘솔 `.docs-list`, 오른쪽 칸 `.split > aside` ↔ `aside.sess-side` 등). 비교 항목·허용 오차(기본 ±2px, 글자 크기 ±0.5)는 요소마다 정하고, 화면마다 `screen_config.py` 에서 덮어쓴다. 글 길이에 따라 달라지는 높이·세로 위치는 기본에서 뺐고, 세로 위치는 헤더 아래끝 기준이다(맨 위 알림 띠가 있고 없고에 흔들리지 않게).
- **상태 만들기** `fake_console/`: 가짜 gh·claude 로 화면마다 세션 상태를 만들어 시험 콘솔(기본 포트 4881, `CONSOLE_CHECK_PORT`)을 임시 폴더에 띄운다. 준비된 화면은 G-04·05·06·09·10·12·13·15, 더하려면 `fake_console/screens.py` 에 함수를 만들고 `BUILDERS` 에 올린다.
- **대조**: 헤드리스 Chrome·Edge·Chromium 을 DevTools 프로토콜로 직접 움직인다(새 의존성 없음, 표준 라이브러리만). 허용 오차 밖이면 `화면 너비 요소.항목: 시안 값 / 실제 값` 을 찍고 실패한다. 가로 스크롤(`scrollWidth > clientWidth`)도 실패다. 그 밖에 ① 페이지 배경이 창 높이(innerHeight) 끝까지 덮는지(html·body 배경 또는 최상위 앱 상자 배경; 시안은 `.app min-height 1000` 이라 콘솔 쪽만 판정), ② 헤더 로고가 실제로 떴는지(`naturalWidth > 0`)와 크기·위치, ③ 주요 요소의 `background-color`·`color` 가 시안과 **정확히 같은지**를 본다. 글자색 예외는 `screen_config.py` 의 `COLOR_EXCEPTIONS` 에 (시안 색, 콘솔 색) 값 쌍과 이유로 적는다(지금은 #722 의 대비 4.5:1 결정 둘: 기본 글자색 #fff→rgb(243,250,248), --lmuted #6d7775→#55625f). 값 쌍이 아니면 실패하고, 배경색·테두리색에는 예외가 없다. `screen_config.py` 의 `expect` 로 글·단추(기능) 기대값도 같이 본다.

실행(저장소 루트에서):

```
python -m checker.tests.console_mockup.check_console                  # 준비된 화면 전부
python -m checker.tests.console_mockup.check_console G-09 --shots out  # 한 화면만, 그림도 저장
```

종료 코드 0 = 모두 시안 안, 1 = 시안과 다름, 2 = **검사 불능**(브라우저·기준 파일 없음, 서버 못 띄움). 2 는 통과가 아니다. 브라우저는 `CONSOLE_CHECK_BROWSER` → PATH → 흔한 설치 위치 순으로 찾고(Windows 는 Edge 가 기본으로 있다), 다른 작업 폴더의 콘솔을 보려면 `CONSOLE_CHECK_REPO`. pytest 에서는 `CONSOLE_MOCKUP_CHECK=1` 일 때만 같은 검사가 돈다(브라우저가 없으면 이유를 보이고 건너뜀). 기본 시험은 브라우저 없이 비교 함수·기준 파일 모양·main 에서 잰 G-09 값에서 차이를 잡아내는지만 확인한다. 한계: 시안 폴더의 `_blob/` 에 진짜 로고(png)·글꼴(woff2)이 있어야 기준을 뽑을 수 있다(이미지를 못 불러오면 멈춘다). 시안이 쓰는 구글 글꼴 IBM Plex Mono 만 밖에서 안 불러와져 콘솔의 JetBrains Mono 로 대신 잰다. gh·claude 는 흉내라 PR 검사 이름·승인 수 같은 진짜 GitHub 값은 못 본다.

## 10. 범위 밖

- `SKILL.md` 를 고쳐 단계별 진행을 보고하게 하는 일. 나중에 한다.
- 서버 재시작 뒤 대기 중 요청 복구.
- 원격 접속. 로컬 전용이다.

## 알림 상태와 터미널로 넘어간 요청 (#792)

- 설정의 알림 줄 아래 한 줄(`data-notify-perm`)이 브라우저 권한을 구분해 보인다: 지원 안 함 / 아직 안 물음 / 허용창 답 기다리는 중(`waiting`, 스위치는 아직 꺼진 채) / 허용창을 답 없이 닫음(`dismissed`) / 막힘(+ 브라우저 설정에서 켜는 법 한 줄) / 허용됨(스위치 하나라도 켜짐 vs 모두 꺼짐). 서버엔 켜 둔 값이 저장돼 있는데 브라우저가 허용하지 않은 상태는 따로 경고(`data-notify-stale`)한다. 스위치는 허용됨일 때만 켜진 것으로 그린다. 시안 G-19 치수·색은 그대로다(문구만 바뀜).
- 터미널로 넘어간 요청: 콘솔(SSE)이 아무도 안 붙은 사이 훅이 오면 `Hooks._terminal_without_browser` 가 세션 기록에 `콘솔이 연결돼 있지 않아 터미널로 넘김: <도구>` 를 한 줄 남긴다(같은 호출이 거듭 오면 한 번). 연결이 끊긴 때(`down`)나 숨은 탭이 SSE 를 닫은 때부터 다시 붙을 때까지의 시각을 `offSince` 로 재고, 다시 붙으면 그 사이 기록만 세어 위쪽 연결 띠에 "N번 터미널에서 물었어" 로 알린다. 이 탭이 열리기 전에 넘어간 건 기준 시각이 없어 세지 않는다.
