# #1025 Post 테마를 웹 콘솔 모든 화면에 적용 (2026-11-17)

## 배경
#1013(#1019)은 테마 고르기와 Post 의 색·홈 장면 띠만 넣어 화면 틀이 Sauce 그대로였다. 사용자가 준 Post 테마 적용 가이드(아티팩트 XxciuctShdXbLqu4vN4UM2)와 시안(Hw6FqmUWBUBDX4bwsS5K9q 의 `redesign/`, 가이드의 `demo/`)대로 콘솔의 모든 화면에 Post 정의를 적용했다. 시안에 없는 화면(처음 화면, 팀 기록 상세·새 기록, 모달, 연결 끊김 등)도 같은 부품 규칙으로 그렸다.

## 한 것
| 파일 | 내용 |
|---|---|
| `static/post-logic.js` (새) | 순수 함수: `personOf`(세션 id 해시로 손님 고정), 창구 k·상태 판정(가이드 6.1·6.2), 창구 안내 문구, 도장 글자(보냄·접수·반송) |
| `static/post-home.js` (새) | Post 오늘 화면: 인사 줄, "지금 세션들" 장면 패널+범례(차분이면 세션 목록), "내 차례 N건" 덱(손님 아바타·질문 바로 답·승인 요약), 숫자 칸, 고칠 PR·최근 산출물·바뀐 것 |
| `static/post-session.js` (새) | Post 세션 화면 세 칸(목록 걸러보기·아바타 / 머리 창구 안내 `po-here` / 점검 탭 산출물·검사·기억·기록·기술), 요청 화면 직원·손님(`po-clerk`), 도장(`po-seal`) |
| `static/app.js`, `flow-ui.js`, `attach.js`, `notice-logic.js` | Post 일 때 틀(왼쪽 레일·위쪽 줄)과 각 화면 배치로 분기. 도장은 요청 API 성공 콜백에서만 찍는다. 테마를 바꿔도 입력 중인 글·고른 답이 남는다 |
| `static/theme.js` | Post 전용 `bh-fx`(0 차분·1 보통·2 화려)·`bh-mode`(auto·light·dark) 저장, `html[data-fx]`·`[data-mode]` 를 Post 일 때만 첫 페인트 전에 건다 |
| `static/theme-post.js` | 장면이 `personOf` 를 쓰고, 효과 강도(화려면 창문 구름)와 어두운 모드 명판 바탕을 따른다 |
| `static/theme-post.css` | 모든 Post 규칙(`:root[data-theme="post"]` 아래만, 어둡게는 `[data-mode="dark"]`) |
| `static/index.html` | 새 JS 세 개 연결 |
| `console/server.py` | `/auth` 만료·없는 경로 같은 서버 글자 화면을 콘솔 모양 HTML 판(`error_page`)으로. app.css·theme-post.css·theme.js 만 불러 저장된 테마대로 보인다. 응답 코드·문구 뜻은 그대로, `/api/` 오류는 계속 JSON |
| `static/app.css` | Sauce 바탕 `--bg` 를 `#132322` → `#131a19` 로(사용자가 준 화면에서 딴 색). 서버 글자 화면용 새 클래스 |
| 오류·팝업 | 알림 팝업 가운데·뒷바탕 흐림, 건너뛰기 모달 포커스 가두기·닫은 뒤 포커스 복귀(Post), 전달 실패·이미 처리됨·권한 막힘 등 주의 문구에 `!` 호박색, 분석 실패는 `? 확인 못 함` 보라 점선(Post), 첨부 단추·칩 |
| 새 작업 참고 파일 | "작업 폴더에서" 문구, Post 팝업 "작업 폴더 파일 고르기"(빈 폴더·못 읽음 문구, Esc·위아래·Enter), 고른 파일 칩(×) |
| `checker/tests/console_mockup/fake_console/serve.py` | 시험 콘솔 흉내 gh 에 팀 기록 쓰기(issue create·comment·edit) |
| `checker/tests/test_web_console_ui.py`, `console_ui_smoke.js` | 손님 고정·창구·도장 판정, 저장 키, 테마 전환 입력 보존 시험 |
| `plugin.json`, `whats_new.json`, `docs/guide/harness-guide.html` | 0.10.305 → 0.10.307(열린 #1023 이 0.10.306), 바뀐 것 한 줄, 길잡이 "화면 모양" |

## 판단
- **Sauce 는 건드리지 않는다.** Post 스타일은 theme-post.css 안 Post 선택자에만, JS 는 테마 확인으로 분기했다. 변경 전 캡처와 비교해 Sauce 는 시각 글자 말고 같다.
- **실제 콘솔에 없는 것은 만들지 않았다**: 시안의 파이프라인 메뉴·화면, ⌘K 찾기 칸, 밀도 설정, 지어낸 데이터(판 이력 등 실제 값이 없는 칸)는 넣지 않았다.
- 글자는 가이드 7.5 대로 22px 상한(시안 큰 제목·도장 26px → 22px), 문구는 반말.
- "테마 기본" 밝기는 시안 `applyPrefs` 대로 Post 기본(밝게)이고 운영체제 설정은 따르지 않는다. 운영체제 움직임 줄이기는 언제나 차분처럼 멈춘다.

## 확인
- 시험 콘솔(fake_console)로 G-01~G-24·X-01~X-12 를 Post(밝게/어둡게 × 차분/보통)·Sauce 각각 1440·1280·390 폭에서 자동 검사: 페이지 가로 넘침, 기본 모양 컨트롤, 22px 초과, 폭만큼 늘어난 버튼, Post 화면의 Sauce 색, 어두운 모드 대비 4.5:1 미만, 콘솔 오류 — 모두 0. 남은 하나는 G-18 Sauce 390 의 기억 경고 버튼 줄 넘침(411>390)으로, 이 변경 전 main 에도 있다(이 PR 범위 밖).
- 장면은 390 폭에서 패널 안 가로 스크롤(가이드 2.8 대로).
- 별도 검토 지적(테마 전환 때 입력 사라짐, 홈 덱 포커스 빠짐, 일부 화면 즉시 다시 그리기 안 됨, 창구 안내판 빔 등)을 고쳤다.
- 오류·팝업(Y 계열: 링크 만료, 전달 실패·이미 처리됨, 알림 팝업 여러 건·실패, 첨부 실패, 분석 실패, 설정 알림 막힘 등)까지 넣어 540 조합 검사 위반 0. confirm·alert·prompt 는 쓰는 곳이 없다.
- 하네스 흐름 한 바퀴(처음 화면 → 새 작업 → 분석 → 질문 답(접수) → 승인 허락(보냄)·거절(반송) → 올리고 검토 요청·건너뛰기 모달 → PR 승인 기다림 → 병합 → 다음 갈래 Spec 새 세션, 산출물·팀 기록 새 기록·설정·목록 걸러보기)를 Post·Sauce 로 화면 클릭으로 돌려 모두 통과(AI·gh·병합은 흉내). 그때 나온 Post 전용 누락(홈의 "내 세션" 표·"검토 요청(PR)" 칸, 새 작업 위쪽 줄 폴더, 산출물 제목 중복)을 고쳤다 — 홈 표·PR 칸은 `flow-ui.js` 의 `homeTable`·`homePrBox` 로 뽑아 두 테마가 같이 쓴다.
- 확인 못 함: 서버 재시작 뒤 연결 끊김 띠가 사라지는지(재시작한 서버가 옛 로그인을 받지 않아 두 테마 모두 "콘솔을 다시 열어 줘"), handoff 띠·세션 불러오는 중 상태는 직접 띄우지 못했다.
- 전체 시험 5903 통과. 실패 12건(`test_session_pr_block` 8·`test_unfinished_snapshot` 1·`test_gitleaks_scan` 3)은 main 에서도 같고, macOS 에서 실제로 기능이 잘못 동작하던 것이라 별도 이슈·PR 로 고친다.

## 남은 한계
- 시안의 효과 "화려" 중 장면 밖 연출(배경 입자 등)은 Post 시안에 해당하는 것만 옮겼다.
- 콘솔 시안 대조 검사(`CONSOLE_MOCKUP_CHECK=1`)는 Sauce 기준이라 Post 는 보지 않는다.
