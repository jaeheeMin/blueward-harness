# #558 로컬 웹 콘솔 `/harness:open` (2026-10-31)

## 배경

세션이 여러 개이면 터미널 창을 오가며 각 세션의 상태와 결과를 보고 승인·질문에 답해야 한다. 터미널을 잘 모르는 컨설턴트가 한 화면에서 보고 답하고 새 작업을 맡기도록 로컬 웹 콘솔을 넣는다. 설계는 `docs/design/web-console.md` 이다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `plugins/harness/console/` (신규) | 표준 라이브러리만 쓰는 로컬 서버(`127.0.0.1:4873`). `server.py`(라우팅·인증·SSE), `store.py`(세션·요청 상태, `sessions.json` 저장), `hooks_api.py`(`/hooks/*` 판단), `managed.py`(콘솔이 띄운 `claude -p` 세션), `analysis.py`(새 작업 읽기 전용 분석), `gitstate.py`(`이번 차례`), `platform_compat.py`(OS 차이), `open.py`, `session_start_hook.py`, `static/`(순수 JS 화면) |
| `skills/open/SKILL.md` (신규) | `/harness:open`. `open.py` 를 실행하고 결과를 한 줄로만 알린다 |
| `hooks/hooks.json` | 콘솔 훅 추가. 전부 command(`console/hook_post.py`)이다. 상태만 모으는 `UserPromptSubmit`·`UserPromptExpansion`·`PreToolUse *`·`PostToolUse`·`SubagentStart`·`SubagentStop`·`Notification`·`PreCompact` 는 `async: true`, `PermissionRequest`·`PreToolUse AskUserQuestion`·`Stop`·`SessionEnd` 는 동기. `SessionStart` 는 `session_start_hook.py`. 기존 훅은 그대로 |
| `docs/design/web-console.md` | 구현을 읽어 달라진 곳을 반영 |
| `docs/guide/harness-guide.html` | "처음 준비하기" 탭에 `/harness:open` 과 추가된 훅 설명, 레일 기준 판 0.10.142 |
| `plugins/harness/.claude-plugin/plugin.json` | version 0.10.141 → 0.10.142 |

## 결정

- 훅은 서버가 꺼져 있으면 연결 실패를 조용히 삼키고 세션을 막지 않으며 오류 줄도 남기지 않는다. 검사를 못 한 것을 승인으로 처리하지 않는다(터미널 프롬프트가 처리한다).
- 포트는 기본 4873 이다. 환경변수 `HARNESS_CONSOLE_PORT` 는 시험용 임시 포트 용도이고, 훅(`hook_post.py`)도 같은 변수를 읽는다.
- 상태 수집 훅은 `async: true`(아래 지연 수치). 비동기라 도착 순서가 뒤바뀔 수 있어 `hook_post.py` 가 뜬 시각(`X-Hook-Ts`)을 보내고 서버가 Stop·SessionEnd 이전에 뜬 늦은 이벤트로 상태를 되돌리지 않는다(설계 문서 5장).
- 권한 우회 모드(`bypassPermissions`) 세션은 승인 요청이 없어서 화면에 그렇게 표시한다.
- 버전은 origin/main 0.10.141 보다 큰 0.10.142 로 잡았다(rebase 시점에 plugin.json 을 바꾸는 열린 PR 은 없었다).

## 통합 시험 결과 (macOS, `claude` 2.1.309, 모델 haiku, 2026-10-31)

시험 증거(시험 폴더 `console-final/`)는 저장소에 넣지 않았다. 아래는 그 요약이다.

| 시험 | 결과 |
|---|---|
| 관리 세션(콘솔이 띄운 `claude -p`) 새 작업 분석 → 시작 → 결과 보고 | 통과 |
| 관리 세션 Bash 승인 허용, 파일이 실제로 만들어짐 | 통과 |
| 관리 세션 `AskUserQuestion` 에 웹에서 답, 그 답이 Claude 의 결과 보고에 반영됨(PreToolUse `*` async 와 `AskUserQuestion` 동기가 겹침) | 통과 |
| 관리 세션 스킬 버튼(`/harness:version`) → 현재 스킬 표시 → 승인 요청 4건 웹 허용 → 끝나면 스킬 `done`, 쉬는 상태 | 통과 |
| PTY 터미널 세션 등록(SessionStart) | 통과(`terminal`, 쉬는 상태 `canSend=false`) |
| 터미널에서 먼저 허용하면 웹 요청이 "터미널에서 처리됨"으로 닫힘(async PostToolUse) | 통과 |
| 턴 끝 예약 실행: 실행 중 `version` 예약 → Stop 이 `block` 으로 스킬 실행 → 웹 승인 → 끝 | 통과 |
| 턴이 끝난 터미널 세션이 쉬는 상태로 남음(늦은 async 이벤트로 `running` 이 되지 않음), 쉬는 세션에 입력 불가 안내 | 통과 |
| 서버를 끈 PTY 세션: 오류 줄 없음, 터미널 승인 프롬프트가 바로 뜸 | 통과(화면에 error 문자열 0건, `claude -p` stderr 0바이트) |
| 보안 수정 화면 캡처(헤드리스 Chrome, 별도 프로파일): 승인 화면의 입력 전체, `.sugg` 규칙 안내, Bash 위험 값 행(샌드박스·백그라운드), 긴 입력 스크롤(높이 320 / 내용 1685), 새 작업의 제외됨 줄 | 통과, 깨진 곳 없음 |
| 자동 시험 `checker/tests/test_web_console.py` | 통과(늦게 온 이벤트 회귀 시험 포함) |

- 관리 세션 승인 시험에서 `changedFiles` 는 비었다. `touch` 는 파일 편집 도구가 아니라서 정상이다.
- 화면 캡처 시험의 승인·질문 요청은 터미널 세션을 흉내 낸 훅 호출(가짜 `claude` 분석 포함)로 만들었다. 실제 `claude` 로 만든 요청 화면은 위 관리·PTY 시험에서 API 로만 확인했다.

## 훅 지연 (macOS, 이 머신 한 대)

| 측정 | 값 |
|---|---|
| `hook_post.py` 1회(uv 경유) 20회, 서버 꺼짐 | 중앙 131ms, 최대 135ms |
| 같은 측정, 서버 켜짐 | 중앙 131ms, 최대 133ms |
| 첫 실행 | 132ms(서버 꺼짐), 133ms(켜짐). uv 캐시가 이미 데워진 뒤라 진짜 콜드 비용은 재지 못했다 |
| 비교: `uv run --no-project python -c pass` | 중앙 115ms. 훅 한 번의 대부분이 uv 기동이다 |
| 비교: `python3 hook_post.py` 직접 | 중앙 28ms(서버 켜짐 29ms). Windows 의 `python3` 부재 때문에 uv 를 유지했다 |
| 도구 호출이 끝난 뒤 다음 모델 요청까지 간격(PostToolUse 훅 대기 포함), `claude -p` Bash 8회 × 5번, 서버 꺼짐, 40건 | 콘솔 훅 동기 중앙 145ms, **async 중앙 34ms**, 콘솔 훅 없음 중앙 32ms |
| 같은 시험의 전체 시간 중앙 | 동기 20.7s, async 14.2s, 훅 없음 18.9s. 모델 응답 편차가 커서(async 11.9~18.5s) 비교 지표로 쓰지 않는다 |

도구 호출 하나에 PreToolUse 와 PostToolUse 가 각각 한 번이라, 동기 상태에서는 서버를 쓰지 않는 사용자도 호출마다 약 0.25초를 더 기다렸다. async 로 바꾸고 콘솔 훅 없음과 구별되지 않는 수준(+2ms)이 되었다. 앞쪽(PreToolUse) 대기는 따로 재지 않았고 같은 크기로 추정한다.

## 이번에 고친 것

- 상태 수집 훅 8개 이벤트를 `async: true` 로 바꿨다(위 표). 공식 문서는 이벤트별 제한을 적지 않았고, 실제로 UserPromptSubmit, PreToolUse, PostToolUse, SubagentStart·Stop, Notification 이 도착했다. UserPromptExpansion 과 PreCompact 은 이번에 발화를 관측하지 못했다.
- 늦게 도착한 async 이벤트가 상태를 되돌리는 문제: Stop 뒤에 도착한 PreToolUse·UserPromptSubmit·UserPromptExpansion 이 `turn_running` 을 다시 켜거나 스킬을 진행 중으로 남길 수 있었고, 늦은 PostToolUse·UserPromptSubmit 이 그 뒤에 만든 같은 입력의 승인 요청을 닫을 수 있었다. `X-Hook-Ts` 로 시각을 보내 서버가 가린다. 회귀 시험 12건을 추가했다.
- SubagentStop 이 SubagentStart 보다 먼저 오면 서브에이전트가 `running` 으로 남던 문제.
- `test_control_request_permission_is_bridged_with_hook_request` 가 부하에서 한 번 실패했다는 보고가 있었다. 원인을 재현하지 못했다(이 시험만 스레드 전환 간격 1µs 로 400회, CPU 점유 프로세스 14개를 띄운 채 전체 파일 2회 실행: 모두 통과). 대기·join 제한이 짧아 부하에서 시간 초과가 났을 가능성이 가장 커서 제한을 5초·10초에서 60초로 늘리고 스레드 종료를 단언으로 확인하게 했다. 근본 원인 확정은 아니다.

## 알려진 한계

- **Windows 미검증.** `platform_compat.py` 의 Windows 분기(`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `CREATE_NO_WINDOW`, `.cmd` 를 `cmd /c` 로 감쌈, 경로 대소문자 무시)는 코드를 읽어 쓴 것이고 실행해 본 적이 없다.
- `--plugin-dir` 로 띄운 세션과 같은 이름의 설치본이 함께 있을 때의 이름 충돌은 시험하지 못했다(문서상 `--plugin-dir` 쪽이 교체한다고 되어 있다). 이번 PTY·관리 시험은 `--plugin-dir` 만 썼고 훅이 이중으로 걸리는 현상은 보지 못했다.
- 86400초 대기는 시험하지 못했다. 660초 대기까지만 확인했다.
- 서버를 재시작하면 쿠키가 서버 메모리에만 있어 브라우저는 `/harness:open` 을 다시 실행해야 한다.
- SIGKILL 로 죽은 터미널 세션은 SessionEnd 가 오지 않아 목록에 남는다(10분 뒤 쉬는 상태로 보인다).
- 쉬는 터미널 세션에는 콘솔에서 입력할 수 없다(터미널에서 직접 이어 가야 한다).
- 서버가 꺼진 동안의 훅 이벤트는 유실된다. 서버가 켜진 뒤 처음 온 `session_id` 는 자동 등록된다.
- 훅 지연 수치는 한 대의 macOS 에서 잰 것이다. Windows 는 프로세스 기동이 더 느릴 수 있다.
- `claude -p` 로 도는 세션에서는 async 훅이 종료 시점에 정리되어 마지막 이벤트가 유실될 수 있다(공식 문서). 콘솔이 띄운 세션은 stream-json 으로 오래 사는 프로세스라 문제 되지 않았다.

## Windows 실기 확인 항목 8개

PowerShell 에서 아래를 차례로 확인하고 결과를 이 문서에 적는다.

1. `uv --version` 이 나오는지 확인한 뒤 Claude Code 에서 `/harness:open` 을 실행해 브라우저가 열리고 화면이 표시되는지 본다.
2. `Get-Content "$env:USERPROFILE\.claude\harness-console\server.pid"` 로 PID 와 포트를 읽고, 그 PID 를 종료하면 서버가 정상 종료하고 pid 파일이 사라지는지 본다.
3. `netsh interface ipv4 show excludedportrange protocol=tcp` 로 4873 이 제외 범위(Hyper-V·WSL 예약)에 들어 있는지 확인한다. 들어 있으면 서버가 포트를 못 열 때의 안내가 화면과 `server.err` 에 나오는지 본다.
4. `where.exe claude` 로 설치 형태(`.exe`, `.cmd`, npm 전역 설치 등)를 확인하고, 사용자 폴더 이름에 공백이나 한글이 있는 환경에서 콘솔의 새 작업이 시작되는지 본다.
5. 따옴표가 붙은 경로(예: `"C:\Users\홍 길동\work"`)를 작업 폴더 검증에 넣었을 때 처리가 맞는지 본다.
6. 한글 파일명을 바꾼 세션에서 "이번 차례"의 변경 파일 표시가 깨지지 않는지 본다.
7. 시험이 끝난 뒤 `Get-Process claude,node -ErrorAction SilentlyContinue` 로 콘솔이 띄운 `claude` 자식 프로세스가 남지 않았는지 본다.
8. `uv` 가 없는 상태(PATH 에서 제외)에서 세션을 열었을 때 콘솔 훅 때문에 세션이 막히지 않는지 본다(기존 가드 훅의 `uv` 안내는 별개이다).
