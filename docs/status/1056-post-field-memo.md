# #1056 Post 오늘 화면 장면 칸을 현장 메모(C안)로 (2026-11-17)

## 배경
Post 점검 시안(세 안 중 C안 "현장 메모")에서 사용자가 범위를 "맨 위 장면(사무실 그림 칸)만 C안으로, 나머지는 다 원래대로" 로 정했다. 처음에는 위쪽 띠·레일 배지·숫자 카드 줄·내 세션 표까지 C안으로 바꿨다가(커밋 c6f7785) 되돌렸다. 여기에는 장면 칸만 남았다. Sauce 테마와 Post 의 다른 화면은 그대로. 모든 CSS 는 `:root[data-theme="post"]` 아래.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/static/post-home.js` | 장면을 테두리·둥근 모서리 틀(`.po-stagew`, 사무실일 때 `.is-office`) 안에 넣고 그 위에 내 차례 메모(`.po-memo`). 덱과 같은 순서의 topId 한 건, 여러 건이면 "다음 n/m"(J·K 도 된다). 메모가 보여 주는 항목이 바뀌면 `scene.focus(id)`, 장면의 `onFocus` 좌표 오른쪽(머리 x+24, y−44)에 두고 모자라면 꼬리째 왼쪽으로 뒤집고 틀 안으로 clamp, 좌표가 없으면 기본 자리(left 21%, top 12%), 760px 이하는 장면 아래 static. 차분이거나 사무실 번들이 없으면 메모 없음. 덱 카드 본문을 `cardAct` 로 뽑아 덱(질문 폼 포함)과 메모(문장 + 링크)가 같은 문장·링크를 쓴다 |
| `plugins/harness/console/static/theme-post.js` | attach 래퍼가 `focus(id)` 를 통과(번들에 focus 가 없으면 무시, 장면이 아직 안 붙었으면 붙은 뒤에 준다) |
| `plugins/harness/console/static/app.js` | `attachScene(host, extra)` 로 `onFocus` 를 넘기는 길, 홈 뷰가 `slots.scene()` 을 준다 |
| `plugins/harness/console/static/theme-post.css` | 장면 틀·메모·꼬리(`.is-flip`)·메모 칩 글자색. 760px 이하 static |
| `plugins/harness/console/static/post/office/office-post.js` | 번들(onFocus·focus·끌어 보기, ai-office-iso) |
| `plugins/harness/.claude-plugin/plugin.json`, `console/whats_new.json` | 0.10.316(whats_new 는 이 범위 두 줄) |
| `docs/guide/harness-guide.html` | 웹 콘솔 탭의 Post 오늘 화면 설명(틀 안 폭 가득, 끌어 보기, 메모) |
| `checker/tests/test_web_console_ui.py` | `test_post_home_field_memo_layout`: 메모·틀·focus 연결 + 장면 칸 밖은 그대로(덱·숫자 칸·`HK.homeTable`·범례·팀 줄·레일 배지) |

## 판단·남은 것
- 허락하기·거절하기 직접 버튼은 만들지 않았다. 요청 화면의 `decide` 는 그 화면 안에 갇혀 있고, 알림 팝업의 `nbAnswer` 는 팝업 상태에 묶여 있으며, 팝업은 명령 전체가 보이는 요청(`fitsPopup`)에만 빠른 허락을 둔다. 메모에는 제목만 보이니 맹목 승인이 된다. 덱과 같은 `가서 승인하기` 링크 + `세션으로`(가는 곳이 같으면 하나만).
- 메모는 질문 폼을 그리지 않고 문장 + `가서 답하기` 링크만 준다. 덱이 그대로 아래에 있어 같은 폼이 두 번 생기면 id 가 겹친다.
- 장면 높이는 번들이 host 에 aspect-ratio 를 직접 넣는다. CSS 의 2.4/1 은 자리 잡기용.
- 되돌린 것(원래대로): 위쪽 내 차례 띠(말풍선), 레일 숫자 배지, 인사 문장, "지금 세션들 N개" 머리줄, 팀 요약 줄·범례, "내 차례 N건" 덱, 숫자 카드 줄, 내 세션 표. 결재란·두 단 목록·상태 칩·팀 인원 한 줄은 쓰지 않아 지웠다.
- 못 본 것: 메모가 왼쪽으로 뒤집히는 경우와 끌기 중 따라가기(좌표가 번들에서 오므로 실제 번들로 확인 필요), 승인 기다림(PR OPEN) 세션이 든 화면, 실제 승인 대기 시간 글(가짜 시계라 "498584시간째" 로 나옴).
