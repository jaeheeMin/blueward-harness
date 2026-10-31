# Harness 웹 콘솔 설계

`/harness:open` 을 실행하면 로컬 서버와 웹페이지가 뜬다. 웹에서 모든 Claude Code 세션의 상태와 결과를 보고, 승인과 질문에 답하고, 스킬을 실행하고, 새 작업을 시작한다. 사용자는 터미널을 모르는 컨설턴트이고 Windows 와 macOS 모두 지원한다.

표기: **[시험]** 은 CLI 2.1.309, macOS 에서 실제로 확인한 동작이다. Windows 는 어느 항목도 시험하지 않았다.

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
    gitstate.py             브랜치·변경·PR 로 `이번 차례` 판단
    platform_compat.py      프로세스 분리, 종료, 경로, claude 실행 파일 찾기
    session_start_hook.py   SessionStart command 훅
    static/                 index.html, app.css, app.js (순수 JS, 빌드 없음)
  hooks/hooks.json          훅 추가
```

시험은 저장소의 기존 시험 구성을 따른다. 실제 `claude` 를 부르지 않도록 stream-json 을 흉내 내는 가짜 실행 파일을 쓴다.

## 3. 서버

- 주소는 기본 `127.0.0.1:4873` 이다. 훅이 command 라서 환경변수로 바꿀 수 있지만 사용자는 바꾸지 않는 것을 기본으로 한다. 포트를 다른 프로그램이 쓰고 있으면 `/api/health` 응답으로 구별해 원인을 보고한다.
- `ThreadingHTTPServer` 를 쓴다. 훅 요청이 응답을 오래 붙들기 때문이다. 화면 갱신은 SSE(`/api/events`)로 보낸다.
- 상태 폴더: `CLAUDE_PLUGIN_DATA` → 없으면 `<CLAUDE_CONFIG_DIR 또는 ~/.claude>/harness-console`. `sessions.json` 은 원자적으로 저장한다. 대기 중인 요청은 저장하지 않는다.
- 띄운 프로세스가 끝나도 서버는 살아 있어야 한다. POSIX 는 `start_new_session=True` **[시험]**, Windows 는 `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`.
- 끄기: `open.py --stop`. 상태 폴더의 `server.pid`(PID 와 포트)를 읽되, `/api/health` 가 우리 서버라고 답할 때만 종료 신호를 보낸다(옛 기록이 다른 프로세스를 가리킬 수 있어서). 서버가 SIGTERM·SIGINT 를 받으면 세션 저장을 마치고, 콘솔이 띄운 `claude` 프로세스도 stdin 을 닫아 끝낸다(5초 안에 안 끝나면 terminate, 다시 5초 뒤 kill). 서버를 끄면 콘솔이 띄운 세션도 함께 끝난다.
- 환경변수: `HARNESS_CONSOLE_PORT`(기본 4873, 범위 밖이거나 숫자가 아니면 기본값)는 서버·`open.py`·`session_start_hook.py` 가 읽는다. 시험용 임시 포트를 위한 것이다. 훅(`hook_post.py`)도 같은 변수를 읽으므로 Claude Code 를 띄우는 환경에 같은 값이 있어야 훅이 서버에 닿는다. `HARNESS_CONSOLE_MODEL` 은 서버가 띄우는 모든 `claude`(콘솔 세션·새 작업 분석)에 `--model` 로 넘긴다. 비어 있으면 넘기지 않는다.

## 4. 인증과 보안

위협은 세 가지다. 세션의 자기 승인, 다른 웹사이트의 호출, 파일 목록 노출.

- 모든 요청의 `Host` 가 `127.0.0.1:4873` 또는 `localhost:4873` 이어야 한다. DNS 리바인딩을 막는다.
- 브라우저 인증: `POST /api/open` 을 받으면 서버가 일회용 토큰(60초 만료)을 만들어 **서버 프로세스에서 직접** 브라우저를 연다. 토큰은 응답 본문과 stdout 에 절대 넣지 않는다. `/auth?t=` 가 토큰을 소비하고 `HttpOnly; SameSite=Strict` 쿠키를 준 뒤 리다이렉트한다.
- `/api/*` 는 쿠키를 요구한다(`/api/open`, `/api/health` 제외). 변경 요청은 `Origin` 이 있으면 자기 주소여야 하고 `Content-Type: application/json` 이어야 한다.
- `/hooks/*`, `/api/open` 은 쿠키 없이 `POST` 로만 받고(그 밖의 메서드는 405) `Origin` 헤더가 있으면 거부하며 JSON 객체만 받는다. 본문 상한은 `/hooks/*` 32MB, 그 밖의 API 1MB(초과 413). `/auth` 의 토큰이 없거나 만료됐으면 403 이다. 이 경로로는 요청을 **만들 수만** 있고 답할 수 없다.
- 파일 탐색 `/api/fs?root=&dir=` 는 `root` 가 최근 작업 폴더 목록이나 세션의 `cwd` 중 하나여야 하고(아니면 403), `dir` 은 그 안이어야 한다. `realpath` 로 벗어남을 검사하고 심볼릭 링크 탈출을 막는다.
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
- 권한 우회 모드는 콘솔에서 제공하지 않는다. 그 모드(`permission_mode` 가 `bypassPermissions`)의 세션에는 `PermissionRequest` 가 발화하지 않으므로 세션 모델의 `bypassPermissions` 를 참으로 내려 화면이 표시하게 한다 **[시험]**.

## 5. 훅

| 이벤트 | 방식 | 경로 |
|---|---|---|
| SessionStart | command (`session_start_hook.py`, 자체 제한 1초, 항상 exit 0). 동기 | `/hooks/event` |
| PermissionRequest | command (`hook_post.py permission 86400`). **동기** | `/hooks/permission` |
| PreToolUse `AskUserQuestion` | command (`hook_post.py question 86400`). **동기** | `/hooks/question` |
| Stop | command (`hook_post.py stop 5`). **동기** | `/hooks/stop` |
| SessionEnd | command (`hook_post.py event 1`). **동기**(공유 제한 1.5초) | `/hooks/event` |
| UserPromptSubmit, UserPromptExpansion, PreToolUse `*`, PostToolUse, SubagentStart, SubagentStop, Notification, PreCompact | command (`hook_post.py event 3`) + **`"async": true`** | `/hooks/event` |

모든 콘솔 훅은 `type: "command"` 이고 `uv run --no-project python console/hook_post.py <경로> <제한 초> || true` 이다. 서버가 꺼져 있으면 연결 거부를 삼키고 아무것도 출력하지 않고 exit 0 이라 화면에 훅 오류 줄이 남지 않는다. http 훅은 서버가 꺼져 있으면 대화형 화면에 오류 줄이 남아서 쓰지 않는다 **[시험]**.

**왜 async 인가.** command 훅은 도구 호출마다 프로세스를 띄운다. 이 머신(macOS, uv 경유)에서 한 번에 약 130ms 이고 그 가운데 uv 자체가 약 115ms 다. 서버가 꺼져 있어도 같다. 동기로 두면 도구 호출 하나에 PreToolUse·PostToolUse 두 번, 콘솔을 쓰지 않는 사용자까지 느려진다. 상태만 모으고 응답이 필요 없는 이벤트는 `async: true` 로 세션을 기다리게 하지 않는다. 승인·질문·Stop·SessionEnd 는 응답을 쓰거나(결정, `updatedInput`, `block`) 종료 전에 끝나야 해서 동기로 둔다. 공식 문서(hooks, "Run hooks in the background")는 `async` 를 command 훅의 필드로만 설명하고 이벤트별 제한은 적지 않는다. 실제 `claude`(2.1.309) 로 UserPromptSubmit, PreToolUse `*`, PostToolUse(터미널 먼저 허용 시 요청 닫힘), SubagentStart·Stop, Notification 이 async 로 서버에 도착함을 확인했다 **[시험]**. UserPromptExpansion 과 PreCompact 은 이번 시험에서 발화를 관측하지 못했다. 문서상 막히지 않으므로 async 로 두었고, 안 오면 해당 표시(스킬 감지는 PreToolUse(Skill) 도 한다, 압축 로그)만 빠진다. async 훅은 `-p` 로 돌 때 종료 시점에 정리되므로 마지막 이벤트가 유실될 수 있지만, 콘솔이 띄운 세션은 Stop(동기)이 상태를 닫는다.

PreToolUse `*`(async)와 PreToolUse `AskUserQuestion`(동기)은 질문 도구에서 둘 다 걸린다. 서로 다른 훅 프로세스이고 `*` 쪽은 응답을 쓰지 않으므로 질문 답이 깨지지 않는다 **[시험: 관리 세션 질문 답변]**.

**도착 순서.** async 는 프로세스가 늦게 떠서 Stop 보다 늦게 올 수 있다. `hook_post.py` 는 뜨자마자 `X-Hook-Ts` 헤더에 시각을 싣고, 서버는 Stop·SessionEnd 의 시각을 세션의 경계(`boundaryTs`)로 기억한다.
- 경계보다 먼저 뜬 UserPromptSubmit·PreToolUse·UserPromptExpansion 은 `turn_running`·`ended`·현재 작업·스킬 표시를 바꾸지 않는다(쉬는 세션이 다시 도는 것으로 되돌아가거나 스킬이 계속 진행 중으로 남지 않게).
- 늦게 온 PostToolUse·UserPromptSubmit 은 그 시각까지 만들어진 요청만 닫는다(그 뒤에 같은 도구·입력으로 새로 생긴 승인 요청을 닫지 않게).
- 같은 세션의 PreToolUse 가 뒤바뀌어 오면 더 늦게 뜬 것의 현재 작업을 남긴다.
- SubagentStop 이 SubagentStart 보다 먼저 오면 끝난 것으로 남기고, 뒤늦은 시작이 다시 running 으로 만들지 않는다.
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
- 종료: stdin 닫기. 안 끝나면 `platform_compat.terminate`(POSIX SIGTERM, Windows `terminate()`).
- `claude` 실행 파일은 `shutil.which` 로 찾는다. Windows 의 `.cmd` 는 직접 실행할 수 없으면 `cmd /c` 로 감싸되 인자는 사용자 입력을 넣지 않는다. 사용자 입력은 stdin 으로만 넘긴다.

### 새 작업

1. `POST /api/new {text, cwd}`: `claude -p --permission-mode plan --output-format json --json-schema <스키마> --no-session-persistence` 로 읽기 전용 분석을 돌린다. 승인 없이 끝난다 **[시험]**. 요청 글은 stdin 으로 넘긴다. 180초 안에 끝나지 않으면 실패로 처리하고, 분석 작업은 메모리에만 있어 서버를 다시 띄우면 사라진다.
2. 스키마: `understood`, `candidates[{path, reason}]`, `extraQuestions[{question, options[]}]`. 결과의 `path` 는 작업 폴더 안인지 서버가 다시 검사한다.
3. `POST /api/new/:id/start {picked[], extraAnswers, note}`: 세션을 띄우고 첫 메시지로 요청 글과 `@경로`(**[시험]** 파일 내용이 주입된다), 답, 메모를 보낸다. 작업 폴더가 git 저장소면 앞에 `/harness:start` 를 붙인다. 화면 미리보기와 실제 메시지는 같은 함수로 만든다.

## 7. `이번 차례` 규칙 (`gitstate.py`)

위에서부터 처음 맞는 것을 고른다. `gh` 가 없거나 실패하면 PR 판단을 건너뛰고 `start` 로 두며 `turnUnknown` 을 참으로 내려보낸다. git·gh 호출은 각각 5초 제한이다. 기본 브랜치는 `origin/HEAD` → `main` → `master` 순으로 찾고, 분리된 HEAD 나 빈 브랜치 이름도 `start` 로 본다. `원격보다 앞선 커밋` 은 `@{u}..HEAD`, 올려 둔 곳이 없으면 `origin/<기본 브랜치>..HEAD` 로 센다. 변경 파일은 이 판단의 `git status` 결과로 훅이 모은 목록을 덮어쓴다(git 저장소일 때).

1. git 저장소가 아니다 → 차례 없음
2. 기본 브랜치에 있다 → `start`
3. 커밋 안 된 변경이 있거나 원격보다 앞선 커밋이 있다 → `deliver`
4. 열린 PR 이 있다 → `prs`
5. 그 밖 → `start`

스킬 목록은 플러그인의 `skills/*/SKILL.md` frontmatter 에서 읽는다. `update`, `scaffold`, `open` 은 버튼으로 내지 않는다. 실행 중에는 스킬 흐름에서 현재 스킬을 `진행 중` 으로 표시한다.

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
| GET | `/api/requests/:rid` | 승인·질문 내용. 요청 모델에 `sessionTitle`, `suggestions` 가 더해진다 |
| POST | `/api/requests/:rid/answer` | 승인 `{decision: allow / allow_session / deny, reason?}`, 질문 `{answers:{질문:답}}` |
| POST | `/api/new` | 분석 시작 |
| GET | `/api/new/:id` | 상태, 결과 |
| POST | `/api/new/:id/start` | 작업 시작. 세션이 실제 id 를 얻을 때까지 최대 8초 기다려 그 id 를 돌려준다 |
| GET | `/api/new/:id/preview` | 첫 메시지 미리보기. 쿼리: `picked`(반복), `extraAnswers`(JSON 문자열), `note` |
| GET | `/api/folders/recent` | 최근 작업 폴더 |
| POST | `/api/folders/validate` | `{path}` |
| GET | `/api/fs` | 쿼리 `root`, `dir`. 응답 `{root(realpath), dir, entries[{name, kind: dir/file, size}]}`. `dir` 은 요청 값의 앞뒤 슬래시만 뗀 것, 폴더가 앞이고 이름순, `.git` 과 작업 폴더 밖을 가리키는 링크는 뺀다, 최대 2000개, 폴더의 size 는 0 |

세션 모델: `id, title, cwd, repo, branch, managed, status(starting/running/waiting/idle/ended), group, permissionMode, bypassPermissions, currentSkill, currentAction, startedAt, updatedAt, log[{time,text}], report, changedFiles[], prLinks[], subagents[], flow[{skill,state,reserved,disabledReason?}], turnSkill, turnUnknown, pendingRequestIds[], canSend, cannotSendReason`.

- 시간 값(`startedAt`, `updatedAt`, 로그의 `time`, 요청의 `createdAt`·`answeredAt`)은 epoch **초**(소수 포함)다. 화면이 경과 시간을 계산한다.
- `turnSkill` 은 `이번 차례`(§7)의 `start`/`deliver`/`prs`/없음, `turnUnknown` 은 `gh` 로 PR 을 보지 못해 판단이 불완전했다는 뜻이다. `bypassPermissions` 는 `permissionMode == "bypassPermissions"` 다.
- `status` 는 끝난 터미널 세션 → `ended`, 대기 요청 있음 → `waiting`, 턴 실행 중 → `running`, 띄우는 중 → `starting`, 끝난 콘솔 세션 → `ended`, 그 밖 → `idle` 순으로 정한다.
- 요청 모델: `id, sessionId, kind(permission/question), toolName, toolInput, hasSuggestions, status(pending/answered/closed), outcome, createdAt, answeredAt` 이고 질문에는 `questions` 가 더해진다. 완료된 요청은 최근 200개만 남긴다.
- 승인 답변에서 `allow_session` 은 `permission_suggestions` 가 없으면 400, 거부 사유가 비면 "콘솔에서 거부했습니다." 를 쓴다. 질문 답변은 모든 질문에 빈 값이 아닌 답이 있어야 하고(없으면 400) 배열은 `", "` 로 잇는다. 이미 처리된 요청에 답하면 409 와 처리 결과를 돌려준다.
- 실행 중이 아닌 터미널 세션에 메시지·스킬·예약을 보내면 409 와 이유를 돌려준다. 예약은 턴 끝에 한 번 꺼내 쓰고 `sessions.json` 에 함께 저장된다.

`group` 은 대기 중인 요청이 있거나 `turnSkill` 이 있고 턴이 끝났으면 `todo`, 턴 실행 중이면 `running`, 그 밖에는 `idle` 이다. 제목은 SessionStart 의 `session_title` → 첫 요청 글 첫 줄(`/` 로 시작하는 글은 제외) → 폴더 이름 순이고 60자로 자른다. 로그는 세션당 200개, 한 줄 500자로 자른다. 훅이 모은 변경 파일은 `Write`·`Edit`·`MultiEdit`·`NotebookEdit` 의 PostToolUse 에서, PR 링크는 PostToolUse 의 도구 응답에서 `github.com/.../pull/N` 을 찾아 모은다. 최근 작업 폴더는 20개까지 기억한다.

## 9. 화면

디자인은 시안(`design-canvas/project/`)을 그대로 옮긴다. 경로: `/`, `/s/:id`, `/r/:rid`, `/new`, `/settings`. 한 페이지 앱이고 서버는 이 경로 모두에 `index.html` 을 준다.

- 사이드바: `내가 할 일`, `Claude가 하는 일`, `쉬는 중`. `[` 키로 접는다(입력칸에 포커스가 있으면 동작하지 않는다). 접힌 상태를 기억한다.
- 세션 화면: 현재 스킬과 행동, 경과 시간(실제 계산), 스킬 버튼 흐름, **결과 보고**(마크다운을 안전하게 표시), 변경 파일, PR 링크, 로그, 이어서 요청 입력칸, `기술 정보 보기`. 쉬는 터미널 세션은 막는 이유를 보여 준다.
- 승인, 질문, 새 작업(입력 → 분석 중 → 자료 확인), 설정: 시안대로. 처리된 요청은 "터미널에서 처리됨" 처럼 결과를 보여 준다.
- 테마 10개와 글자 크기 3단계는 `localStorage` (`bh-theme`, `bh-scale`)에 저장한다. 접근이 막혀도 기본값으로 동작한다. 테마 표는 한 곳에만 둔다.
- 금지: 그라데이션 배경, 유리 효과, Pulse 복제, 터미널 버튼. 시안의 샘플 데이터를 코드에 남기지 않는다. 빈 상태 화면을 만든다.

## 10. 범위 밖

- `SKILL.md` 를 고쳐 단계별 진행을 보고하게 하는 일. 나중에 한다.
- 서버 재시작 뒤 대기 중 요청 복구.
- 원격 접속. 로컬 전용이다.
