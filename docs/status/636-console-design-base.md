# #636 웹 콘솔 디자인 "Sauce" 1차: 디자인 바탕 + 앱 틀 + 홈

3덩어리 중 첫 덩어리. 세션 대화·새 작업·질문/승인·설정 화면의 배치는 이번에 바꾸지 않았고, 새 색·글꼴·알약 버튼만 입는다(2·3덩어리에서 배치 개편).

## 한 일

- `static/app.css`: 맨 위 `:root` 한 벌로 Sauce 토큰(흑요석 `#132322`·패널 `#0e1a19`·네온 `#3ddc91`·밝은 판 `#edf7f5`·노랑 `#ffcd48`·위험 `#e5484d`·보라 `#8b7cf6`). 알약 56px·카드 20px·큰 판 40px. 앱 틀(알림 띠·헤더·230px 세션 목록)과 홈(타일·노랑 카드·표·빈 홈) 스타일. `:root[data-design]` A·B·C 블록과 옛 테마 카드, 옛 사이드바·세션 카드 CSS 삭제. 상태 표시(✓ ✕ ! ? 점선)는 디자인 전용에서 전역 규칙으로 옮겼다. 기본 체크박스·select 화살표는 직접 그렸고, 22px 넘는 글자 규칙을 없앴다(h1 20px, 큰 숫자 22px).
- `static/app.js`: `boot` 가 알림 띠 → 헤더 → (세션 목록 + 본문) 틀을 만들고 `renderSide` 가 셋을 같이 그린다. 디자인 빠른 전환 버튼과 설정의 테마·디자인 칸 삭제(글자 크기만 남김). 홈에서 새 작업으로 글을 넘기는 `startNew` 추가.
- `static/flow-ui.js`: 홈(`homeView`)을 빈 홈 / 진행 중 홈으로 새로 썼다. 옛 `sessionCard` 삭제. 승인 카드가 결과를 타일에도 알린다.
- `static/theme.js`: 테마 11개·디자인 전환 삭제, 글자 크기만 남김(`bh-scale` 그대로).
- `static/logo-sauce.png` 추가, 쓰는 곳이 없던 `blueward-logo.png` 삭제.
- 시험: `test_web_console_ui.py` 의 테마·디자인 시험을 새 동작(글자 크기만, 대비 4.5:1, 22px 이하, 기본 위젯 없음, 앱 틀 규칙)으로 바꾸고 홈 시험을 새 화면에 맞췄다(`dom_home_cards`, `dom_home_empty`).
- `plugin.json` 0.10.165. `docs/design/web-console.md` 9절, `docs/guide/harness-guide.html` 의 콘솔 항목 갱신.

## 메뉴 ↔ 경로

| 메뉴 | 경로 | 비고 |
|---|---|---|
| 내 일 | `/` | 홈 |
| 작업 | `/s/:id` | 가장 위 세션(내 차례 먼저). 세션이 없으면 메뉴에서 뺀다 |
| 산출물 | (없음) | 만든 문서는 세션 화면 안의 칸이라 모아 보는 경로가 없다. 지어내지 않고 메뉴에서 뺐다 |
| 새 작업 | `/new` | |
| 설정 | `/settings` | 헤더 오른쪽 버튼 |

## 데이터가 없어 비우거나 "확인 못 함" 으로 둔 칸

- 기억(context) % — 서버가 주지 않는다. 링 안 `?`, 툴팁 "기억 사용량 확인 못 함". 숫자를 만들지 않았다.
- 홈 "만든 산출물" 타일(빈 홈) — 세션 밖에서 개수를 구할 길이 없어 "확인 못 함".
- 번호 칸의 REQ/DEV — 세션 데이터에 없다. 이슈 번호는 브랜치 이름(`feat/636-…`)에서 읽고, PR 은 갈래 데이터(`flowPr`)를 쓴다.
- 승인 기다리는 PR 타일 — 내가 승인자일 때만 보이고 gh 실패는 "확인 못 함".

## 시험 결과 (2026-11-04, 로컬 Windows)

- `test_web_console.py` + `test_web_console_ui.py`: 456 통과, 3 건너뜀, 실패 0.
- 건너뛴 3개는 모두 심볼릭 링크를 만들어야 하는 시험이라 이 PC(관리자 권한·개발자 모드 없음, WinError 1314)에서 스스로 건너뛴다. 이번 변경과 무관하다. GitHub Actions 에서 실제로 도는지는 확인 못 했다 — #640 검사는 Linux·Windows 모두 4053 통과·15 건너뜀이었지만 `pytest -q` 가 건너뛴 시험 이름을 남기지 않는다. 셋째 PR 에서 `checker.yml` 에 `-rs` 를 더해 로그로 확인한다.
  - `test_analysis_symlink_candidate_escape` — 폴더 밖을 가리키는 링크 후보 걸러 내기
  - `test_files_route_excludes_links_that_escape_the_root` — 파일 목록에서 폴더 밖 링크 빼기
  - `test_file_open_blocks_a_link_that_hides_an_executable` — 링크 뒤 실행 파일 열기 막기
- 전체 `uv run pytest -q` 는 49% 까지 실패 0 에서 PC 메모리 부족으로 Claude Code 가 멈췄다. 나머지는 PR 검사(Actions)로 확인한다.

## 알아 둘 것

- 홈 "자주 하는 일" 버튼은 새 작업 입력칸에 문장을 미리 넣어 `/new` 로 보낸다. 새 작업 화면이 종류를 인자로 받지 않고, 매뉴얼·CTS·Role 은 갈래(`workflow.json` flows)가 아니라 도구라서 갈래를 미리 고를 수 없다.
- 라벨 글꼴 IBM Plex Mono 는 CSP(`font-src 'self'`) 때문에 못 받아 JetBrains Mono 로 대신했다.
- 길잡이 아티팩트는 병합 뒤 다시 올려야 한다(`docs/guide/README.md`).
