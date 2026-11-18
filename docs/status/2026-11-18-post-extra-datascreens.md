# Post 데이터 있는 화면·접근성 점검 X2 (2026-11-18, 이슈 없음)

핸드오프: `.claude/handoff/2026-11-18-post-extra-datascreens.md`. Post 테마만 고쳤다(Sauce 동작·DOM 불변 — 공유 파일을 고친 곳은 전부 `isPost()`·`isPostTheme()`·`getTheme() === 'post'` 로 가르거나 `:root[data-theme="post"]` 범위 CSS). push·PR·이슈·판 올리기·새 소식 없음.

## 방법
임시 가짜 콘솔(포트 4922, `localhost` 로 열어 다른 세션의 127.0.0.1 쿠키와 안 겹침)에 데이터를 만들고 Aside 로 눌렀다.
- 산출물 세계: 세션 셋(docx·pptx·xlsx 9개 파일, 같은 이름 여러 판 v0.1·v0.2, 아주 긴 파일명, 시트 셋짜리 xlsx, 깨진 xlsx, 다른 세션의 같은 이름 파일, 폴더를 지운 세션 → 409, git 을 못 읽는 세션).
- 팀 기록 세계: `screens.py` 의 `_trouble_world`(이슈 9건·저장소 하나는 gh 로그인 필요) + 초안(`/api/trouble/draft`, 비밀값 포함).
- MCP url 모드: 이 PR 의 시험용 가짜 claude 복사본이 `control_request(elicitation, mode:url)` 을 보내고 control_response 를 기다린다(콘솔이 띄운 세션). 주소 4종(정상·`javascript:`·빈 값·아주 긴 주소)과 다 했어·거절·닫기.
- 건너뛰기 링크: 세션 57개(대량 50)로 Tab 순서를 세고 고침 뒤 다시 센다.

## 찾아서 고친 것
| # | 화면 | 결함 | 고친 곳 |
|---|---|---|---|
| 1 | 산출물 | 키보드로 문서 줄을 눌러 고르면 목록을 통째로 다시 그려 포커스가 body 로 떨어짐(다시 처음부터 Tab) | `flow-ui.js` `draw()` 가 다시 그리기 전 포커스한 줄의 경로를 기억했다가 되돌림(Post) |
| 2 | 산출물 | 이전 판(접힌 칸)을 고르면 다시 그리며 칸이 닫혀 고른 줄이 숨고 포커스도 사라짐 | `flow-ui.js` 이전 판 칸을 고른 판이 있거나 사용자가 연 상태면 열어 둠(`st.oldOpen`, Post) |
| 3 | 산출물 | 세션이 12개를 넘으면 오래된 세션의 문서가 말없이 빠지고 빈 화면은 "아직 양식으로 뽑은 산출물이 없어"(세션 57개 실험) | `flow-ui.js` Post 는 "최근에 움직인 세션 12개의 문서만 모았어. 더 오래된 세션 N개의 문서는 여기에 안 나와." + 빈 안내 문구 구분 |
| 4 | 산출물 | 다른 세션의 같은 이름 파일(BW_Backlog List v0.1 두 개)을 가를 수가 없음 — 세션 이름은 마우스를 올려야만 보임 | `flow-ui.js` 목록에 세션이 둘 이상 섞이면 둘째 줄에 세션 이름(말줄임, Post) |
| 5 | 산출물 | 좁은 화면(390)에서 줄을 눌러도 미리보기가 목록 아래라 아무 일도 없어 보임 | `flow-ui.js` 눌러 고르면 미리보기가 화면 밖일 때 그쪽으로 스크롤, `theme-post.css` `scroll-margin-top: 88px`(위 메뉴줄에 머리가 안 가리게) |
| 6 | 산출물 | docx 배지만 색이 없고 폭이 달라 줄 글자가 3px 어긋남 | `theme-post.css` `.ext` 고정 폭 44px, `.ext-docx` 파랑 |
| 7 | 산출물 | 미리보기 못 하는 문서(docx)가 "아래 버튼으로 열어 봐" — 버튼은 위 카드에 있음 | `flow-ui.js` `renderPreview` ctx.btnAt, Post 는 "위" |
| 8 | 팀 기록 | 거르기(아직·해결됨)·찾기 Enter·선택 상자·종류 고르기·새 기록 단계/상태 고르기에서 화면을 통째로 다시 그려 포커스가 body 로 떨어짐 | `trouble.js` `focusKey`/`focusBack` 를 목록·한 건·새 기록의 `draw` 에 씌움(Post, 입력칸은 id·aria-label, 단추는 태그·class·글) |
| 9 | MCP url 요청 | 아주 긴 주소가 줄을 못 바꿔 390 에서 가로 스크롤(문서 폭 1556px) | `theme-post.css` `[data-elicit-url] { overflow-wrap: anywhere; word-break: break-all }` |
| 10 | MCP url 요청 | `javascript:` 같은 주소는 열기 링크를 안 만들어 안전하지만 "열 수 없는 주소야" 옆에서 [다 했어] 가 눌려 "마쳤다"고 답이 감 | `app.js` `cantOpen`(Post): 단추 비활성 + 안내 "마칠 수 없으니 거절하거나 닫아 줘" |
| 11 | 틀 | Tab 건너뛰기 없음(세션 57개: 본문까지 Tab 약 72번) | `app.js` Post 에서만 보이는(`hidden` 토글, `bh-theme` 이벤트 따라감) 「본문으로 건너뛰기」를 레일보다 앞에, 사이드 목록 맨 앞에 「세션 목록 건너뛰기」. 클릭은 `document` 한 곳에서 받아 `#main` 에 포커스. `theme-post.css` 평소 1px 클립, 포커스 오면 보임 |

## 확인(Aside, 실제로 눌러서)
- 산출물: 결과 화면(가장 새 파일이 xlsx 라 "고객 양식으로 뽑았어") → 문서 목록 보기 → 고르기(xlsx 시트 셋·시트 전환·양식 칸 세기·빈 칸 배너, pptx 슬라이드, docx 미리보기 불가, 깨진 xlsx "엑셀 문서를 읽지 못했어: BadZipFile"), 이전 판 칸, 판 이력, 폴더를 지운 세션 → "1개 세션은 작업 폴더가 없어져서…", git 을 못 읽는 세션 → "확인 못 함" 칩 + 안내(검사 불능을 통과·없음으로 뭉개지 않음).
- 팀 기록: 목록(열린 3·해결 6, 상태·프로젝트·쓴 사람 걸러보기, 찾기), 한 건(요약·이력·관련 PR·비슷한 기록, 시도 올리기 — 비밀값 `client_secret=…` 이 `••••` 로 가려져 올라감), 새 기록(초안 AI 배너·가림 카드·비슷한 기록 줄·GitHub 미리보기, 직접 쓴 `password=`·`ghp_…` 가림), 홈 「팀 기록 · 아직 안 풀린 문제」 타일을 Enter 로 눌러 /troubles.
- MCP url 요청: 카드(`연결 도구(asksrv)가 묻는 것` + 주소 + [주소 열기]) → 다 했어 `{"action":"accept"}`·거절 `decline`·닫기 `cancel` 이 가짜 claude 에 그대로 도착, 도장 "접수". `javascript:` 는 링크 없음·주소 글자만·`role=alert`, Sauce 는 단추 그대로 켜짐(회귀 없음). 빈 주소는 카드 없이 cancel(서버, 기존 시험).
- 건너뛰기: Tab 1번 → 「본문으로 건너뛰기」(왼쪽 위 8,8, 포커스 때만 보임), Enter → `#main` 포커스, 다음 Tab 은 본문 첫 단추. 목록 안 링크 Enter → 본문. Sauce: 링크 `hidden`, Tab 1번은 원래대로 `A.brand`, 목록 링크 없음.
- 라이트·다크 × 1440·390 × (/docs 목록·/troubles·/troubles/…/842·/troubles/new?draft=…) 가로 넘침 0, `page.console.logs()` 오류 0.

## 고치지 않은 것(Sauce 도 바뀌거나 서버 문구라 판정 대기)
- 미리보기 실패 문구가 파이썬 예외 이름을 그대로 보임("엑셀 문서를 읽지 못했어: BadZipFile") — 서버 `docfiles.py` 문구(Sauce 도 같음).
- 새 기록 입력칸의 aria-label 이 `symptom`·`cause`·`solution` 영어 키 — 기존 UI 시험이 `[aria-label=symptom]` 으로 잡고 있어 바꾸면 Sauce 시험이 깨진다. 스크린 리더가 영어 키를 읽음.
- 정보 요청 url 모드 도장 문구 "연결 도구가 받은 값으로 이어 가"는 값이 없는 url 모드엔 맞지 않음(공유 `ELICIT_RES`).
- MCP url 요청 답한 뒤 카드가 사라지며 포커스가 body 로(도장은 보임).
- 새 기록·한 건에서 글을 올린 뒤 포커스(보내기 단추가 비활성이 되어 되돌릴 곳이 없음)는 body.
- 산출물의 아주 긴 파일명이 `formInfo` 부제목에서 "고객사 …양식" 안에 통째로 들어감(BW_ 규칙 이름이 아닐 때, 지어낸 시험 이름이라 손대지 않음).

## 독립 리뷰(서브에이전트 sonnet, 읽기 전용) 반영
- 같은 경로 파일이 다른 세션에 있으면 포커스 복원이 첫 줄로 감 → 줄에 `data-dkey`(폴더|경로, Post) 로 되돌림. Aside: 같은 경로 pptx 둘 중 둘째 줄에서 Enter → 포커스가 둘째 줄에 남음.
- 팀 기록의 같은 단추(후보마다 `이걸로 해결`)가 여럿이면 첫 번째로 감 → 키에 몇 번째인지, id·aria-label 은 이스케이프 없이 끼우지 않고 노드를 걸러 찾음.
- Sauce 에 숨은 `<a>` 가 DOM 에 남음 → 건너뛰기 링크는 Post 일 때만 붙이고 테마가 바뀌면 붙였다 뗌(Sauce Tab 첫 번째는 그대로 `A.brand`, `.po-skip` 0개).
- 같은 이름을 가르려고 넣은 세션 이름이 좁으면 맨 먼저 잘림 → 둘째 줄을 두 줄까지 허용.
- 판정 안 하고 둔 것: 본문 포커스 표시 없음(프로그램 포커스 관례), 목록 로딩 폴링 때 IME 조합이 끊김(이전부터), 위 링크 `position: fixed` 가 컨테이너 기준일 수 있다는 추정(1440·390 실화면에서 왼쪽 위 8,8 에 보임).

## 시험
`checker/tests/test_web_console_ui.py` 끝에 3건(Sauce 회귀 1 + Post 원문 확인 2), `test_web_console.py` 끝에 1건(javascript: url 요청 서버 통과). post-*.js 는 가짜 DOM 시험이 안 불러와서 원문 확인이 보조이고 본체는 위 Aside 실화면이다.
