# #866 웹 콘솔 바탕화면 바로가기 (2026-11-10)

## 배경

콘솔을 여는 길이 `/harness:open` 뿐이라 Claude Code 를 먼저 열어야 했고, 서버가 다시 뜨면 쿠키가 사라져 또 `/harness:open` 이 필요했다. 사용자 결정(11-10): 바탕화면 바로가기(자동 시작은 안 함).

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `console/shortcut.py` (신규) | 바탕화면 `Blueward Harness.lnk` 만들기·고치기·지운 것 기억. 런처 파일 복사. Windows 만 |
| `console/launcher.py` (신규) | 바로가기가 실행하는 런처. 설치 캐시에서 가장 높은 판의 `open.py` 를 찾아 실행, 실패하면 메시지 상자 |
| `console/open.py` | 성공 뒤 `shortcut.ensure_shortcut()` 호출. `--make-shortcut`(강제로 다시 만듦), `--from-shortcut`(바로가기가 부른 실행, 만들기 건너뜀) |
| `console/server.py`, `static/app.js` | 인증이 풀렸을 때 안내를 "바탕화면의 Blueward Harness 를 다시 눌러 줘(없으면 /harness:open)" 로. 인증 규칙은 그대로 |
| `skills/open/SKILL.md`, `docs/design/web-console.md`, `docs/guide/harness-guide.html`, `console/whats_new.json` | 바로가기 설명, 판 0.10.253 |
| `checker/tests/test_web_console.py` | 바로가기·런처 시험 9개, open.main 시험이 실제 바탕화면을 건드리지 않게 하는 autouse 대역 |

## 결정과 근거

- **런처 위치**: `<CLAUDE_CONFIG_DIR 또는 ~/.claude>/harness-console/launcher/`. 훅이냐 스킬이냐에 따라 달라지는 `CLAUDE_PLUGIN_DATA` 를 쓰지 않는다(바로가기가 가리키는 자리가 실행 환경에 따라 바뀌면 안 된다). 플러그인 캐시 폴더는 갱신마다 새 판 폴더가 생기고 옛 폴더는 남거나 지워지므로 거기에 두지 않는다.
- **최신 판 찾기**: `~/.claude/plugins/cache/blueward-harness/harness/<판>/console/open.py` 중 판 번호(점으로 나눈 숫자)가 가장 큰 것. `installed_plugins.json` 은 프로젝트마다 다른 판을 적고 있어(이 PC 는 판 8개) "가장 최근 설치" 를 가려내기 어려워 쓰지 않았다. 번호가 가장 높은 판이 팀원이 갱신한 최신이다.
- **창 없이 실행**: `.lnk` -> `wscript.exe launcher.vbs`(실행 스타일 0) -> `uv run --no-project python launcher.py`. VBS 는 한글 경로를 읽도록 UTF-16 LE BOM 으로 쓴다. `uv` 는 만들 때 `shutil.which` 로 찾은 전체 경로를 적는다(스킬이 이미 `uv` 를 요구한다).
- **다시 안 만들기**: 같은 폴더의 `shortcut.json` 에 `made`/`removed`. 만든 뒤 `.lnk` 가 없으면 지운 것으로 보고 `removed` 를 적고 조용히 넘어간다. 강제는 `open.py --make-shortcut` 뿐이다. 콘솔 설정의 "바탕화면 바로가기 → 만들기" 단추도 같은 강제 경로를 쓴다(`POST /api/settings/shortcut`, server.py 에 핸들러·경로·import 만 더했다. #793 과 겹치지 않게 최소로).
- **실패 표시**: 못 만들면 `바로가기를 만들지 못함(이유)` 한 줄만 덧붙이고 상태는 기록하지 않아(다음 실행에 다시 시도) 통과로 뭉개지 않는다. 성공은 기존 한 줄 끝에 붙인다.
- **인증**: 바로가기도 `POST /api/open` -> 일회용 토큰 -> 서버가 직접 브라우저를 여는 기존 길을 그대로 쓴다. 토큰이 stdout·바로가기 어디에도 남지 않는다.
- **아이콘**: 기본 아이콘. 바로가기 아이콘은 `.ico` 가 필요한데 로고(`logo-sauce.png`)는 860x141 로 가로로 길고 PNG 를 변환할 표준 라이브러리 수단이 없다.

## 확인

- `uv run pytest -q -p no:cacheprovider checker/tests/test_web_console.py -k "open or auth or launcher or shortcut"` -> 52 passed, 1 skipped.
- 임시 폴더에서 실제 `.lnk` 를 만들어 PowerShell 로 대상(`wscript.exe`)과 인자(한글·공백 경로의 `launcher.vbs`)를 읽어 확인했고, 인자를 바꾸면 불일치로 판정한다.
- 한글·공백 경로의 `launcher.vbs` 를 실제 `wscript` 로 돌려 `uv` 대역에 `run --no-project --quiet python ".../launcher.py"` 가 정확히 넘어가는 것을 확인했다.
- 실제 바탕화면에는 만들지 않았다. 재부팅 뒤 실제 클릭 시험은 사용자 확인 뒤에 한다.
