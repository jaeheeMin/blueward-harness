# #867 웹 콘솔에서 쉬는 터미널 세션 이어 가기 (2026-11-10)

## 배경

터미널에서 연 세션이 쉬는 중이면 콘솔 입력이 막혔다(`store.can_send`). 같은 session_id 를 콘솔이 `--resume` 으로 이어받으면 되지만, 터미널 창(claude 프로세스)이 아직 살아 있으면 두 프로세스가 한 세션을 쓴다.

## 실측 (claude 2.1.321, haiku, 폴더 pexp/repo 안에서만, 끝난 뒤 claude 프로세스 없음 확인)

| # | 실험 | 결과 |
|---|---|---|
| 7 | 살아 있는 세션 X 를 다른 프로세스가 `--resume X` 로 동시에 이음 | 오류 없이 갈라짐. 같은 jsonl 에 부모 uuid 로 분기, 서로의 새 메시지를 못 봄(`--fork-session` 옵션이 있음) |
| 8a | `claude -p --session-id X` 의 `<설정 폴더>/sessions/<pid>.json` | 시작하면 생김(`pid`·`sessionId`·`procStart`(Windows FILETIME)·`cwd`·`status`). 정상 종료(stdin 닫기)하면 지워짐. `taskkill /F` 로 끄면 파일이 남음(그 pid 는 죽어 있음) |
| 8b-S1 | 터미널 흉내(`claude -p`)가 **살아 있을 때** 콘솔 경로 | `session_alive.check` -> `alive`. `Manager.launch(fork_of=X)`(`--resume X --fork-session`) -> 새 session id 로 갈라져 뜸, 갈라진 쪽이 코드워드 AAA 를 기억(대화 이어받음). 원래 jsonl 은 갈라 띄우는 동안 37줄 그대로(새 jsonl 45줄). 터미널은 그 뒤에도 자기 대화를 계속 이음(37 -> 49줄) |
| 8b-S2 | 터미널 흉내를 **끝낸 뒤** | `check` -> `ended`. `launch(resume=X)` -> 같은 id, 같은 jsonl 에 이어 씀(51 -> 61줄), 답 AAA, 세션 항목은 합쳐져 두 줄이 아님(store 2개 = 원래 + 갈라진 것) |
| 8b-S3 | 첫 말 없이 `launch(resume=X)` | 15초 동안 `init` 이 오지 않음(`starting` 그대로). 첫 user 메시지를 보내자 답함 |

로그: `pexp/o8b.txt`·`o8b2.txt`(첫 시도는 jsonl 찾기가 심볼릭 링크 때문에 줄 수를 못 세서 고쳐 다시 돌림), 스크립트 `pexp/exp8a.py`·`exp8b.py`.

## 살아 있는지 확인하는 방법 조사

| 방법 | 판단 |
|---|---|
| `<설정 폴더>/sessions/<pid>.json` + pid·`procStart` 확인 | **채택.** 실측 8a 로 시작·정상 종료·강제 종료를 모두 구분. 한계: 공식 문서에 없는 내부 파일이고 옛 claude 는 만들지 않음 |
| 훅 SessionEnd 수신 여부 | 근거로 안 씀. 창을 강제로 닫으면 오지 않아서 "안 왔다 = 살아 있다" 도 "왔다 = 끝났다" 도 확실하지 않음(`/clear` 도 SessionEnd 를 냄) |
| claude 프로세스 명령줄에 session id | 근거로 안 씀. `claude --resume X` 로 연 터미널에만 id 가 있고, 그냥 `claude` 로 연 터미널은 명령줄에 id 가 없음(없다는 증거가 못 됨) |
| jsonl 이 다른 프로세스에 열려 있는지 | 안 씀. claude 는 줄 단위로 열고 닫는 것으로 보이고 Windows 에서 쓰는 쪽 프로세스를 가려내는 표준 수단이 없음(실험하지 않음) |

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `console/session_alive.py` (신규) | `check(session_id, transcript_path)` -> `(alive/ended/unknown, 설명)`. 설정 폴더는 훅이 준 `transcriptPath` 에서, 없으면 `CLAUDE_CONFIG_DIR`·`~/.claude`. sessions 폴더가 없거나 못 읽은 파일이 있으면 `unknown`. pid 확인은 Windows `OpenProcess`·`GetProcessTimes`·`GetExitCodeProcess` + `procStart` 비교(pid 재사용), POSIX `kill(pid,0)`. 확인할 수 없으면 살아 있는 쪽으로 답함 |
| `console/managed.py` | `command(..., fork=)` 가 `--fork-session` 을 붙임, `launch(fork_of=)` 가 임시 id(`m-…`)로 띄워 init 의 새 session id 로 rekey(기존 흐름). 모델·에포트·권한은 원래 세션 값을 따름. 세션에 `forkedFrom` 기록, 새 세션 점검 목록은 만들지 않음 |
| `console/server.py` | `GET /api/sessions/:id/liveness`, `POST /api/sessions/:id/continue {mode, text}`. `resume` 은 서버가 다시 확인해 `ended` 일 때만(아니면 409 + 이유 + "갈라서 이어 가기" 안내), `fork` 는 언제나. `App.session_alive` 로 시험이 바꿔 끼움 |
| `console/store.py` | 세션 모델에 `forkedFrom` |
| `console/static/app.js`, `app.css` | 막힌 터미널 세션 입력칸 아래 "콘솔에서 이어 가기" 칸(열림 확인 결과·첫 말 입력·[콘솔에서 이어 가기]·[갈라서 이어 가기]·[다시 확인]), 갈라진 세션 위 "갈라서 이어 감" 배너 |
| `console/whats_new.json`, `.claude-plugin/plugin.json` | 판 0.10.262 |
| `docs/design/web-console.md`, `docs/guide/harness-guide.html` | §6·§8, 작업 화면 설명, 레일 판 표기 |
| `checker/tests/test_web_console.py`, `test_web_console_ui.py`, `fake_claude.py` | 시험 추가, 가짜 claude 가 `--fork-session` 이면 새 id |

## 결정과 근거

- **resume 은 확인된 `ended` 일 때만, 서버에서도 다시 확인.** 화면이 아니라 서버가 막는다(화면 검사만 믿으면 우회된다). 모르면(`unknown`) 막고 이유를 보임. 통과로 뭉개지 않는다.
- **fork 는 항상 가능.** 새 session id 라 원래 터미널 세션과 부딪치지 않는다. 화면에 갈라졌음을 밝히고 원래 세션 링크를 둔다.
- **첫 말 필수.** 실측 8b-S3: 말 없이 띄우면 init 이 안 와서 `starting` 에 머문다.
- **기존 항목과 합치기**: resume 은 원래 session id 그대로라 `store.ensure` 가 같은 항목을 `managed` 로 바꾼다(rekey 불필요). fork 는 `m-…` 임시 id -> init 의 새 id 로 rekey(기존 흐름).

## 11-11 main 위로 옮기며 고친 것(558 세션 점검)

- 첨부(#860)와 합치며 `launch`·`_launch` 가 `attachments` 와 `fork_of` 를 둘 다 받는다.
- [다시 확인] 이 어두운 바탕용 `pill ghost` 라 밝은 이어 가기 칸 위에서 글자가 묻혔다 → `pill line`.
- 입력칸 밑 "터미널에서 이어서 말해 줘." 바로 아래에 "콘솔에서 이어 가기" 칸이 있어 서로 어긋났다 → 터미널 세션이면 "터미널에서 이어서 말하거나, 아래에서 콘솔로 이어 가." 로 보인다.
- 잠긴 위 입력칸을 숨기자는 권장은 따르지 않음: 시안 G-09(터미널 세션 화면)가 잠긴 입력칸을 그대로 보이고, 숨기면 시안 검사가 어긋난다.

## 확인 못 한 것

- macOS·Linux 에서 `sessions/<pid>.json` 의 `procStart` 모양(Windows FILETIME 만 확인). POSIX 는 `procStart` 를 비교하지 않고 `kill(pid,0)` 만 본다.
- 사용자가 `claude` 를 인터랙티브 터미널로 연 실제 창에서의 확인(실측은 `claude -p` 프로세스로 흉내, 인터랙티브 쪽 파일은 이 PC 의 열린 세션 파일 모양을 읽어 확인: `kind:"interactive"`, `entrypoint:"cli"`).
- 옛 claude(sessions 폴더 없음)에서의 동작은 `unknown` 으로 떨어지게 시험만 했다.
