# Cozy Office 8회차 — 판정 대기 J6~J14 (2026-11-18)

사용자 판정(2026-11-18): J6~J14 전부 손대되 방향은 Cozy Office 컨셉에 맞게. 서버 구조를 바꾸거나 Sauce 동작을 바꾸게 되는 것은 고치지 않고 이유를 남긴다(서버의 작은 필드 추가는 허용).
항목 원문은 `docs/status/2026-11-18-cozy-office-survey.md` 의 J 표. 시험 세계는 포트 4995(세션 116개: projA~F, 대량 bulk 84개, 승인·질문 요청, 양식 xlsx 세션 projF).

## 항목별 재현 / 원인 / 고침·기록 / 이유

| # | 재현(전) | 원인(파일:줄, 고치기 전) | 고침·기록 | 이유 |
|---|---|---|---|---|
| J6 | projD 를 고른 채 `/s/c-run`(projC): 머리 줄 `projD ⌄ work/projC`, 왼쪽 목록에 `옛 매뉴얼` 한 줄뿐, 지금 세션 줄 없음(`aria-current` 0) | `app.js postSideList`·`renderRail` 이 `sortedSessions()`(= 고른 프로젝트로 거른 목록)만 그림 | **고침**: `postGuest(rows)` — 지금 세션이 거른 목록 밖이면 그 한 줄(접힌 목록은 고리 하나)만 맨 앞에 `다른 프로젝트 · projC` 표와 덧붙인다. 걸러보기 숫자(`전체 1`)엔 안 센다, 걸러보기와 상관없이 보인다. 보는 프로젝트(고른 값)는 그대로 | 주소·알림 링크로 남의 사무실에 들른 것이지 사무실을 옮긴 게 아니다 — 고른 값을 몰래 바꾸면 돌아왔을 때 목록이 바뀌어 있다. 지금 어디인지는 보여야 한다 |
| J7 | 390 세션 화면(세션 112개): 고리 17줄, 높이 876px, 본문이 1116px 아래에서 시작 | `app.css` 좁은 폭 `.rail { flex-wrap: wrap }`(공유) | **고침**(Cozy Office CSS): `.side .rail` 한 줄 `nowrap` + 가로 스크롤(넘침은 줄 안), `postSideAfter` 가 지금 세션 고리를 줄 가운데로 민다 | 줄 수를 자르면(예: 2줄 + `+N`) 나머지 세션에 갈 길이 사라진다. 한 줄 가로 밀기는 모두 닿고 본문을 밀지 않는다. 후: 높이 48px, 본문 288px, 지금 고리 줄 안 |
| J8 | `/r/:id` 1440: 왼쪽 목록 없음, 위에 `‹ 오늘로`, 오른쪽 최근 대화·세션 칸. 띠(`.ann-slot`) display none, `data-bubble=1`, 말풍선이 같은 알림 | `theme-post.css` `#app:not([data-page="session"]) .side{display:none}`(시안 r1·r2), `app.css .ann-slot[data-bubble="1"]{display:none}`(#1016, 두 테마 공통) | **기록만**(세 가지 모두) | ① 목록 숨김은 시안(요청 화면 r1·r2 = 목록 없이 본문 + 오른쪽 칸)대로이고 `오늘로`·말풍선·위 메뉴로 돌아갈 길이 있다. ② 띠는 말풍선과 같은 출처(`sideData`)라 감춘 것(같은 알림 두 번 방지) — 합쳐짐·새 판까지 말풍선(`buildNotices`)이 다 다룬다. ③ 다른 탭 테마 동기화는 `theme.js` 에 storage 리스너를 다는 일이라 Sauce 탭도 따라 바뀐다(Sauce 동작 변경) → **사용자 선택지**: 테마까지 탭끼리 맞출지 / Cozy Office 밝기·효과만 맞출지 / 그대로(새로 고치면 맞음) |
| J9 | `/s/f-pending`: `[data-pr-card]` 2개(대화·검사 탭에 같은 PR #101 카드) | `app.js paintMsgs` 와 `paintInsp` 가 둘 다 `ui.prCard(s)` | **고침**(Cozy Office): 대화에는 `prMemo` — PR 이름 + 지금 상태 한 줄(검사 통과/도는 중/실패 · 팀 승인 상태, 막힘·닫힘·확인 못 함이면 카드와 같은 문장) + `검사 탭에서 보기`(검사 탭을 열고 초점, 좁으면 그리로 스크롤). 카드 전체는 검사 탭에만. 막힘·확인 못 함 표시(`q blocked/unsure`)를 그대로 달아 표시 약속 칸도 뜬다 | 사무실 비유로 대화는 흐름, 점검 탭은 서류철 — 같은 서류를 두 번 펴 두지 않고 흐름엔 메모만. 대화에서 PR 이 사라지면 올린 사실을 놓치니 한 줄은 남김 |
| J10 | 요청을 일찍 생긴 세션(c-idle)에 쏘자 말풍선 `내 차례 7건: 쉬는 세션 · …`, 덱 1/7 은 `로그인 SRS` | `app.js sideData` 의 `todo` 가 세션 Map 순서(처음 본 순), 덱(`post-home.js deckItems`)은 `updatedAt` 오름차순 | **고침**(Cozy Office): `sideData` 끝에서 `todo` 를 덱과 같은 키(세션 `updatedAt` 오름차순, 같으면 원래 순서)로 정렬 → 말풍선·알림 창 1/N·띠·접힌 목록 `내가 할 일` 링크가 덱 1/N 과 같은 첫 항목. 후: 말풍선 `로그인 SRS` = 덱 첫 카드 `f-fail` | 「오늘」 화면의 내 차례는 덱이 기준(사무실의 결재 줄). 알림 창만 다른 순서면 1/N 이 서로 다른 걸 가리킨다. Sauce 는 그대로 |
| J11 ① | (실화면 못 봄 — Aside 는 OS 알림 허락을 못 줌) | `app.js mergeSession`: 판정 전 폴더는 `projectView` 가 보이는 쪽으로 쳐서 다른 저장소 세션 알림이 판정 전 1초 안에 한 번 | **고침**(Cozy Office): `repoPending` 이면 `notifyHeld` 에 모았다가 `ensureRepos` 가 판정을 받으면(`flushNotify(false)`) 고른 프로젝트 것만 보냄, 끝내 못 받으면 5초 뒤 그대로 보냄. 모든 저장소를 보거나 Sauce 면 기다리지 않음 | #1070 리뷰가 걱정한 「보류하면 같은 저장소 알림을 잃음」은 5초 안전 타이머로 막음(잃지 않고 늦을 뿐) |
| J11 ② | 터미널로 넘어간 요청 수: `checkHandoff` 가 모든 세션. 팀 기록 칸: projB 를 골라도 PC 전체 기록 수 | `app.js checkHandoff`(`sessions.forEach`), `flow-ui.js loadTrouble`(`stats.open` = 모든 저장소) | **고침**: 넘어간 요청 수는 `scopedSessions()`(Sauce 는 전부 그대로)·저장소 판정 뒤에 센다. 팀 기록은 Cozy Office 에서 프로젝트를 골랐으면 기록 저장소 폴더(`projects[].root`)를 판정받은 폴더 `top` 으로 맞춰 그 저장소의 `slug` 만 `/api/trouble?status=open&project=` 로 센다(못 찾으면 `확인 못 함`), 프로젝트를 바꾸면 다시 셈. 후: projC 만 2번, projA 는 띠 없음 | 서버 API(`project`·`status` 거르기)는 이미 있어 서버 변경 없음 |
| J11 ③ | projA 파이프라인에서 projB 로 바꾸자 30ms 뒤 앞 칸 그대로였을 것 → 후: 30ms `(읽는 중)`, 3초 `projB` | `post-pipeline.js draw` 가 `st.results`(앞 폴더 결과)를 그대로 그림, `onData` 가 폴더가 바뀌면 `load()` 만 하고 다시 안 그림 | **고침**: 지금 볼 폴더(`folders()`)의 결과만 그리고 없으면 읽는 중, 폴더가 바뀌면 읽기 시작과 함께 다시 그림 | |
| J11 ④ | Sauce 는 프로젝트 거르기 없음 | #1070 설계(Sauce 세션 목록 그대로) | **기록만** | Sauce 동작 변경 → **사용자 선택지**: Sauce 에도 프로젝트 고르기를 둘지 |
| J11 ⑤(6회차) | projE(세션 없음)를 고르자 빈 홈. 코드는 `/api/folders/last`(projC) 로 `프로젝트 준비 끝 · projC` 를 쓰게 되어 있음(이번 실화면은 문구가 안 바뀐 채 — 결과가 그 사이 다시 그린 홈에 안 닿음) | `flow-ui.js emptyHome` 이 서버 마지막 폴더만 봄 | **고침**: `kit.projectPath()`(Cozy Office 고른 프로젝트)가 있으면 그 폴더로. 후: `프로젝트 준비 끝 · projE` | |
| J12 | 브라우저 없을 때 요청 → 서버가 터미널로 넘김(`콘솔이 연결돼 있지 않아 터미널로 넘김: Bash` 기록). 다시 열면 아무 안내 없음 | 서버 설계(SSE 없으면 넘김, `Hooks._terminal_without_browser`). 화면 `offSince` 는 이 탭이 끊긴 때만 잼 | **고침**(화면만, Cozy Office): 콘솔이 붙어 있는 동안 20초마다·페이지를 떠날 때 `localStorage bh-post-seen` 에 시각을 적고, 다시 열면 그 뒤(하루 안) 넘어간 요청을 센다 — 띠 `콘솔을 닫아 둔 사이 AI가 2번 허락이나 질문을 터미널에서 물었어…`(고른 프로젝트만) | 카드가 브라우저 있을 때만 생기는 것 자체는 서버 구조(바꾸면 터미널 세션이 브라우저 없이 멈춤)라 그대로. 「사라져 보이는」 경험만 메움 |
| J13 | — (데이터 문제) | 작업 PR 기준이 `pipeline.py WORK_PREFIX="src/"` 와 화면 `post-logic.js reqFlowOf` 의 `/^src\//` 두 곳 | **일부 고침**: `/api/pipeline` 에 `workPrefix` 필드(작은 필드)를 더하고 화면이 그 값을 씀 — 바꿀 자리가 서버 한 곳 | 고객사가 다른 코드 폴더를 쓸 때 **어디에 적을지**는 정해야 함 → **사용자 선택지**: scaffold 가 이미 「코드 폴더가 src/ 가 아니면 고치라」고 하는 `.github/risk-gate.yaml` 의 `ai_review_paths` 를 읽을지 / `rules.yaml` 에 키를 새로 둘지 / src/ 고정 유지. 콘솔은 엔진(checker)을 import 하지 않아 YAML 읽기를 새로 만들어야 함 |
| J14 ① | 1440 Cozy Office: 위쪽 줄 테마 단추에 초점 → Enter(Sauce 로) → 초점 BODY. 건너뛰기 링크 초점 + 테마 전환 → BODY | `bh-theme` 처리(`app.js`)가 본문 안 초점만 되살림(`snapFields`), 위쪽 줄·건너뛰기는 새 틀에 같은 요소가 없음 | **고침**(두 테마 공통 결함 수정): 본문 밖 초점이면 `themeRefocus` 가 1.5초 지켜보다 초점이 body 로 떨어진 때만 같은 클래스 단추(`ptop-*`·`po-skip*`·`nb-btn`)나 본문 h1 로. 후: `H1:로그인 SRS` | 원문은 「테마는 설정에서 바꾸니 안 생김」이었지만 위쪽 줄 테마 단추로 늘 생겼다 |
| J14 ② | projF 양식 세션 문서를 고른 뒤 다른 세션 13개가 움직이면 고르던 문서가 목록에서 빠짐(원문) | `flow-ui.js docsPage pool()` 이 최근 12개만 | **고침**(Cozy Office): 고른 문서의 세션은 12개 밖이어도 모은다, 안내 `최근에 움직인 세션 12개(와 고른 문서의 세션)의 문서만 모았어`. 후: 13개 밀린 뒤에도 `*요구사항정의서 v0.1` 고른 채 | |

## 실화면(Aside, 4995)

- 고친 화면 7개(다른 프로젝트 세션·PR 메모·오늘·파이프라인·빈 홈·산출물·대량 세션) × 라이트·다크 × 1440·390: 가로 넘침 0, `page.console.logs()` 0, 이름 없는 단추 0.
- J7 390 라이트·다크: 고리 한 줄(높이 48px), 지금 세션 고리 줄 안(`bulk-010` scrollLeft 4189, `c-run` 5796).
- J9: 메모 단추 → 검사 탭 선택·초점, 표시 약속 칸 뜸.
- 못 본 것: J11 ① OS 브라우저 알림(허락을 못 줌 — 소스 시험만), 팀 기록 칸의 숫자 경로(시험 세계 저장소가 GitHub 이 아니라 기록 저장소가 하나뿐 · `확인 못 함` 경로만 봄), J13 은 node 시험만.

- Sauce 1440 대조(`/`·`/s/f-fail`·`/s/c-run`·`/docs`): Cozy Office 클래스 보이는 요소 0, PR 메모 0·대화 PR 카드 그대로 1, 목록 116줄, 로그 0. 덤으로 본 것(안 고침, Sauce): Sauce 말풍선 첫 항목이 `/` 로 열면 `쉬는 세션`, `/s/f-fail` 로 열면 `로그인 SRS` — 세션 Map 에 처음 들어온 순서(세션 화면은 그 세션을 목록보다 먼저 받음)를 따르기 때문. J10 과 같은 원인이고 Cozy Office 는 덱 순서로 고정됨.

## 시험

`uv run pytest checker/tests/test_web_console.py checker/tests/test_web_console_ui.py -q -n 8` → 1584 passed, 2 skipped. 새 시험 `test_cozy_office_judge_j6_to_j14`(소스 + `reqFlowOf` workPrefix node 시험), `test_pipeline_gives_issue_dev_numbers_and_pr_branch_for_cozy_teams` 에 `workPrefix` 단언, #1070 알림 단언을 새 경로로.
시험 함정: smoke 가짜 DOM 은 지운 요소에 초점이 남아(`activeElement` 가 떨어지지 않음) `themeRefocus` 는 「초점이 body 일 때만」 옮긴다.

## 리뷰 처리

sonnet 독립 리뷰(읽기 전용, diff·의도만). Sauce 로 새는 동작은 없다고 봄(Sauce 1440 실화면 대조와 같음). 지적 9건을 원문과 대조:

| # | 지적 | 처리 |
|---|---|---|
| 1 | J7 한 줄 고리가 `overflow` 로 초점 윤곽선(바깥 4px)을 자름 | 반영 — `.side .rail` 안쪽 여백 `4px 4px 6px`. 390 라이트·다크에서 Tab 초점 칸이 줄 위 4px·아래 6px 안 |
| 2 | J11① 숨은 탭은 `requestAnimationFrame` 이 안 돌아 `scheduleSide` 로는 판정을 못 받음 → 5초 뒤 거르지 않고 보냄 | 반영 — `notifyInProject` 가 `ensureRepos()` 를 바로 부르고, 받는 중이었으면 끝난 뒤 남은 보류가 있으면 다시 묻는다 |
| 3 | J11② 프로젝트를 바꾼 직후 팀 기록 칸에 앞 프로젝트 숫자가 남음 | 반영 — 고른 프로젝트가 바뀌어 다시 읽기 시작하면 `불러오는 중이야` 로 되돌린다 |
| 4 | 터미널 넘김 수: 판정이 10초 안에 안 오면 거르지 않고 셈, 모든 저장소면 쓸데없이 기다림 | 일부 반영 — 모든 저장소면 안 기다림. 10초 뒤 거르지 않고 세는 것은 그대로(판정을 못 받으면 거르지 않는 #1070 규칙과 같음, 숨기는 것보다 많이 세는 쪽) |
| 5 | `bh-post-seen` 은 Cozy Office 로 쓸 때만 적혀 Sauce 로 쓴 구간을 모름, 첫 연결 전 끊김이면 저장 값을 안 씀 | 기록만 — 드문 조합(하루 안에 테마를 바꿔 닫았다 염). Sauce 에 적으면 Sauce 동작이 바뀜 |
| 6 | 한 줄 고리에서 `+`(새 세션)가 맨 끝으로 밀림 | 기록만 — 위 메뉴줄에 `새 작업` 이 늘 있음 |
| 7 | 대화 PR 메모 단추가 갱신 때마다 새 노드라 초점이 떨어질 수 있음 | 기록만 — 앞 카드의 `GitHub에서 보기` 와 같은 기존 약점(대화 다시 그리기 방식), 새 퇴행 아님 |
| 8 | 같은 클래스 단추가 있어도 숨어 초점을 못 받으면 제목으로 안 감 | 반영 — 초점이 안 갔으면 본문 h1 로 |
| 9 | plugin.json 판·새 소식 조각 없음 | 기록만 — 빠른 개발 모드 지시(판 올리기·조각은 GitHub main 머지 회차 몫) |

리뷰 반영 뒤 시험 1584 passed, 2 skipped.

## 사용자에게 물을 선택지

1. J8 ③ 탭끼리 테마 맞추기: 테마까지 / Cozy Office 밝기·효과만 / 그대로.
2. J11 ④ Sauce 에도 프로젝트 고르기를 둘지.
3. J13 코드 폴더를 어디에 적을지: `risk-gate.yaml ai_review_paths` / `rules.yaml` 새 키 / src/ 고정.

## 새 소식 한 줄(조각 안 만듦)

「Cozy Office: 다른 프로젝트 세션을 열면 목록 맨 위에 그 세션이 표와 함께 보이고, 좁은 화면 세션 고리는 한 줄로 옆으로 밀어. 브라우저를 닫아 둔 사이 터미널로 넘어간 요청도 다시 열면 알려 줘.」
