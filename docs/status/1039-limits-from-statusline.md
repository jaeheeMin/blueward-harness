# #1039 콘솔 계정 한도를 상태줄 입력에서도 받기

## 근거
- 상태줄 입력 필드: Claude Code 공식 문서 statusline(https://code.claude.com/docs/en/statusline) "Available data" 표 —
  `rate_limits.five_hour.used_percentage`·`rate_limits.seven_day.used_percentage` 는 0~100, `resets_at` 은 Unix epoch 초.
  `rate_limits` 는 claude.ai Pro·Max·Ultra 구독자(또는 지출 한도가 있는 게이트웨이)에게만, 세션의 첫 API 응답 뒤에 오고, 창마다 따로 빠질 수 있다.
  claude-hud 0.8.0 `src/stdin.ts`(`getUsageFromStdin`, `parseRateLimitResetAt` 이 `value * 1000`)도 같은 단위로 읽는다.
- 실행 방식: 같은 문서 "Windows configuration" — Windows 에서 상태줄 명령은 **Git Bash 가 설치돼 있으면 Git Bash, 없으면 PowerShell** 로 실행한다.
  Git Bash 는 따옴표 밖 역슬래시를 먹으니 경로를 슬래시로 쓰라고 한다. 감싸개 명령 경로를 슬래시로 쓰고 큰따옴표로 감싼 이유다.
- 갱신 방식: 같은 문서 "How status lines work" — 새 assistant 메시지·`/compact`·모드 변경 등에 300ms 디바운스로 다시 돌고, **돌던 명령이 있으면 취소**한다.
  그래서 감싸개는 원래 명령을 돌리기 전에 한도 기록부터 한다. 문서는 POSIX 쪽 셸을 말하지 않아 감싸개는 `/bin/sh -c` 를 쓴다(확인하지 못함).
- #1016 이 안 쓴 이유(claude-hud 와 충돌, 설정 파일 쓰기)는 감싸개가 원래 명령을 그대로 실행하고 켜기를 확인받아 하는 것으로 풀었다.

## 설계·판단
- **설정 "계정 한도 표시"** 켜기·끄기(`limits_setup.py`, `GET·PUT /api/settings/limits`). 자동으로 바꾸지 않는다.
  - 대상 파일: `CLAUDE_CONFIG_DIR`(콘솔 서버 환경) 아래 `settings.json`, 없으면 `~/.claude/settings.json`. 화면에 경로를 보인다.
  - 켜기는 현재 statusLine 과 바뀔 값을 화면에 보여 준 뒤 [바꾸기] 를 눌러야 한다(서버도 `confirmed: true` 없으면 400).
  - 원래 statusLine(객체 통째, 없으면 없음)과 원래 파일 바이트를 상태 폴더 `statusline_orig.json` 에 기억한다. command 만 감싸개로 바꾸고 `padding` 같은 다른 키는 그대로.
  - 끄기: 켠 뒤 파일이 그대로면 켜기 전 **바이트 그대로** 되돌린다(없던 파일이면 지운다). 그 사이 다른 설정이 바뀌었으면 statusLine 만 되돌린다(없었으면 키 삭제).
    사용자가 statusLine 을 직접 바꿨으면 건드리지 않는다. 이미 감싸개면 다시 감싸지 않는다(멱등). settings.json 이 JSON 이 아니면 아무것도 쓰지 않는다.
- **감싸개** `console/statusline_wrap.py`: 켤 때 상태 폴더로 복사해 설정이 플러그인 판 경로에 묶이지 않게 한다(콘솔 시작 때 복사본이 있으면 새 판으로 맞춤).
  명령은 `uv run --no-project python "<상태폴더>/statusline_wrap.py"`(하네스 훅과 같은 실행 방식. 파이썬이 맞다 — Windows·macOS 모두 같은 코드로 stdin·stdout 을 바이트로 다룬다).
  - stdin 바이트를 읽어 `rate_limits` 의 두 창만 `statusline_limits.json`(`{t, rate_limits}`)에 원자적으로 기록. 실패하면 stderr 한 줄(`harness-statusline: …`)만 남기고 계속한다.
  - 원래 명령 문자열은 `statusline_orig.json` 에서 읽어 **다시 따옴표를 씌우지 않고** 셸 한 인자로 넘긴다(Windows 는 Git Bash 를 찾아 `bash -c`, 없으면 `powershell -NoProfile -Command`, 그 밖은 `/bin/sh -c`).
    stdin 은 그대로 넘기고 stdout 은 바이트 그대로 내보내며 종료 코드를 유지한다. 원래 상태줄이 없던 PC 는 아무것도 출력하지 않는다(0).
  - WSL 의 `System32\bash.exe` 는 고르지 않는다(Git 설치 경로·`CLAUDE_CODE_GIT_BASH_PATH` 로 찾는다).
- **서버**: `account_limits` 가 rate_limit_event 값과 `statusline_limits.json` 값을 종류(5시간·7일)별로 받은 시각 `t` 가 최신인 쪽으로 합친다.
  `used_percentage`(0~100)는 `/100` 해서 기존 `utilization`(0~1)과 단위를 맞춘다(범위 밖은 모름). 상태줄 값의 status 는 `allowed` 로 둔다(상태줄 입력은 상태를 주지 않는다). 받은 시각 표시는 그대로이고 title 에 "(상태줄에서)" 를 붙인다.
  응답 `source` 는 `latest`, 창마다 `source`(`rate_limit_event`·`statusline`).

## 시험
`checker/tests/test_statusline_limits.py`(windows-latest 에서도 그대로 돈다, `skipif` 로 Windows 를 빼지 않았다).
- 출력 바이트 보존(한글·ANSI·OSC 8·CRLF·LF 섞임·잘못된 UTF-8 바이트·끝 줄바꿈 없음), 종료 코드, 원래 상태줄 없음 → 빈 출력, 기록 실패해도 출력 유지(stderr 한 줄), 입력이 깨져도 출력 유지.
- 상태 폴더·원래 명령 경로에 공백·한글, 따옴표 섞인 원래 명령, 설정에 들어가는 실제 명령 문자열을 Claude Code 와 같은 셸로 실행.
- 켜기·끄기 왕복(LF·CRLF·탭·statusLine 없음·설정 파일 없음)이 바이트까지 같음, 멱등, 그 사이 변경, 깨진 settings.json, 서버 한도 합치기, 설정 API 확인 단계.

## 확인하지 못한 것
- Windows 실물. macOS 에서만 돌렸고 Windows 는 PR 검사 windows-latest 결과로 확인한다(Git Bash 가 있는 러너).
- PowerShell 만 있는 Windows(Git Bash 없음)에서 원래 명령이 `bash -c '…'` 형태이거나 `"경로" 인자` 처럼 `&` 없는 문자열이면 PowerShell 이 못 읽는다 — 원래 Claude Code 가 같은 문자열을 같은 셸로 돌리는 것과 같지만 시험하지 못했다.
- 실제 Claude Code 가 감싸개 명령을 도는 것. 시험은 입력 JSON 을 직접 넣었다.
