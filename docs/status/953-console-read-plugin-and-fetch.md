# #953 콘솔이 하네스 스킬 파일 읽기·git fetch 섞인 읽기 명령에 승인을 물음 (0.10.285)

## 배경
실사용 시험 B(11-14, 콘솔 0.10.280)에서 `/harness:spec` 을 콘솔로 돌렸을 때 팀원이 판단할 게 없는 승인 카드가 떴다.
- `Read`: 설치된 하네스 플러그인의 `skills/start/SKILL.md`(설정 폴더 아래 plugins/cache, 작업 폴더 밖)
- `Bash`: `cd <작업 폴더> && git fetch origin 2>&1 | tail -2; git status --short; …` — `git fetch` 가 목록에 없어 unknown

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/risk.py` | `classify(read_roots=…)`: 읽기 도구(Read·Glob·Grep 등 path_tools)의 경로가 작업 폴더 밖이어도 모두 그 폴더 안이면 safe. 판정은 작업 폴더와 같은 `_path_ok`(보호 경로·비밀값 모양·`..`·변수는 묻기) |
| 〃 | `git fetch`: `git_fetch_options` 옵션만, 위치 인자는 원격 이름(`[A-Za-z0-9][A-Za-z0-9._-]*`)과 브랜치 이름 하나까지. refspec(`:`·`+`), 주소(`://`·`@…:`·경로), `..`, `-f`·`--upload-pack`·`--unshallow` 는 unknown |
| `plugins/harness/console/safe_tools.json` | `git_fetch_options`: `-q --quiet -p --prune --tags --no-tags --all -v --verbose --` |
| `plugins/harness/console/hooks_api.py` | `plugin_read_roots()`: 설치본이면 `<설정 폴더>/plugins/cache/<마켓>/harness`(판 폴더 전부 — 세션이 콘솔과 다른 판일 수 있다), 저장소에서 돌면 `plugins/harness`. `decide` 가 넘긴다 |
| `docs/guide/harness-guide.html` | 콘솔 "답하는 것" 문단의 묻지 않는 읽기에 `git fetch`·플러그인 문서 읽기 추가 |
| `checker/tests/test_web_console.py` | fetch 모양 23가지, 플러그인 폴더 읽기 safe·쓰기 irreversible·보호 경로/비밀값/다른 플러그인/폴더 밖/셸 cat 은 묻기, 읽기 폴더 계산 |

## 결정
- `git fetch` 는 원격 추적 브랜치만 바꾸고 작업 사본·내 브랜치는 그대로라 되돌릴 수 있는 읽기로 본다. 단 refspec 으로 내 브랜치를 바꾸거나, 주소로 다른 곳(ext:: 같은 전송 포함)에서 받는 모양은 판정하지 않는다.
- 플러그인 읽기는 읽기 도구만 넓혔다. `cat <플러그인 파일>` 같은 셸 읽기는 그대로 묻는다(시험 B 에서 물은 건 Read 였다).
- 플러그인 안의 훅·설정 파일(보호 경로)은 읽기도 묻는다. 작업 폴더와 같은 기준이다.
- 플러그인 폴더 판정은 도구가 실제로 열 경로로 한다: 상대 경로는 작업 폴더(Glob pattern 은 path) 기준으로 붙이고, 링크를 모두 푼 실제 경로(글롭이면 글롭 앞까지)도 플러그인 폴더 안이어야 한다. 처음 판은 상대 경로를 플러그인 폴더에 붙여 보아, 작업 폴더 안 Junction `lnk`(→ 밖)에 `Grep path="lnk"` 가 safe 였다(558 점검, Junction 으로 재현).
