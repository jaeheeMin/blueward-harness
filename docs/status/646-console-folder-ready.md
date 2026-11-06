# #646 웹 콘솔 프로젝트 폴더별 준비 판정과 첫 열기 안내

새 작업에서 폴더를 고를 때 폴더마다 하네스 구조(templates/ 와 rules/)가 있는지 칩으로 보이고(시안 02), 준비 안 된 폴더를 처음 고르면 "프로젝트 준비" 안내(시안 03)를 보인다.

## 바꾼 것

- 서버 `console/server.py`
  - `folder_ready(path, wait, fresh)`: 기존 `cond_state("project-ready")` 를 폴더별로 부른다. 기본은 `cached`(60초 기억, `wait=False`)라 요청 스레드가 기다리지 않고, 읽는 중이면 `checking: true`. 갈래 데이터가 없거나 조건이 없으면 `unknown`.
  - `GET /api/folders/recent` 각 항목에 `ready`(yes/no/unknown)·`checking`·`sessions`(그 폴더 또는 하위 폴더를 cwd 로 가진 세션 수, 끝난 세션 포함)를 더했다.
  - `GET /api/folders/intro?path=` → `{ready, seen, show}`. `show` 는 `ready == no` 이고 안내를 본 적이 없을 때만 true. 이 판정은 기억을 건너뛰고 지금 읽는다(`fresh`). 콘솔이 아는 폴더만 받는다(403).
  - `POST /api/folders/intro/seen {path}`: 본 폴더를 `~/.claude/harness-console/folder-intro.json` 에 남긴다(경로는 `normcase(realpath)`, 최대 200개, 넘치면 오래된 것부터 잊음, 다시 보면 맨 뒤로). 상태 폴더가 없는 실행은 메모리.
- 화면 `console/static/app.js` (`newView`): 폴더 카드 칩 `준비됨 · 세션 n`(n=0 이면 `준비됨`) / `준비 필요` / `확인하는 중` / `확인 못 함`. `checking` 이 있으면 1.5초 간격으로 최대 6번 다시 묻고 바뀐 때만 다시 그린다.
  폴더를 골랐을 때(`useFolder`: 목록·찾아보기·경로 입력 모두) `/api/folders/intro` 를 묻고 `show` 면 시안 03 화면(`drawIntro`)을 보인다. 보여 주면서 바로 `seen` 을 남긴다.
  [만들기] → 입력칸을 `/harness:scaffold` 로 두고 `begin()`(도구 스킬을 입력칸에 적고 분석을 거쳐 시작하는 기존 경로), [나중에] → 원래 새 작업 화면. `unknown` 이거나 안내를 못 읽으면 03 을 띄우지 않는다.
- `static/app.css`: `.chip2.warn`(준비 필요, 기존 `--attn` 토큰).
- 길잡이 `docs/guide/harness-guide.html` "폴더·모델·권한 고르기" 에 칩과 첫 열기 안내를 적었다.

## 시험

- `test_web_console.py`: recent 의 ready·sessions·60초 기억, git 불능·갈래 데이터 없음은 unknown, 비동기 계산 중 checking 후 채워진 값, intro 한 번만·상태 폴더에 저장·깨진 파일·모르는 폴더 403·200개 상한.
- `test_web_console_ui.py`: 칩 다섯 종류(옛 서버 응답은 확인 못 함), 03 화면 글, [만들기]가 `/api/new` 로 scaffold 시작, [나중에]는 시작 안 함, seen/ready/unknown/오류엔 03 이 안 뜸.
- `console_ui_smoke.js`: 선택 동작(`click`) 목록과 `posts` 출력을 더했다(기존 시험은 그대로).

## 남은 것

- 크롬 확인(메인 세션): 최근 폴더 카드 칩(`준비됨 · 세션 5`, `준비 필요`, `준비됨`)과, 준비 안 된 scratchpad 폴더를 골랐을 때 03 화면·[나중에] 복귀를 봤다. 목록을 내려 고르면 03 이 맨 아래부터 보여서, 안내가 뜰 때 맨 위로 올리게 고쳤다. [만들기](실제 scaffold 세션 시작)는 시험으로만 확인했다.
- 플러그인 저장소(558 등)도 `templates/`·`rules/` 를 가져서 `준비됨` 으로 나온다 — 기존 project-ready 조건 그대로다.
- [만들기]는 입력칸에 쓴 글이 있으면 `/harness:scaffold` 로 바꾼다.
- 세션 수는 끝난 세션도 센다(세션 목록과 같은 기준).
