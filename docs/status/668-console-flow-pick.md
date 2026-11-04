# #668 웹 콘솔: 종류 버튼이 AI 추천을 덮지 않게, 개발 가능 여부 미리 보이기 (2026-11-04)

## 찾은 문제

harness-console-sandbox(REQ-001 있음, Spec 없음)에서 새 작업 → "개발하기" → "구매오더 조회 앱 개발할래" 로 분석하면 AI 결과는 `flow: {id: spec, confident: false, alternativeId: dev, reason: "…Spec 이 없어…"}` 인데 화면은 "이 일은 '개발하기' 갈래야" 로 시작했다. 원인: `begin()` 이 종류 버튼 갈래를 `draft.flowUser = true`(사용자가 확정)로 잡고, `effectiveFlow()` 가 그때 AI 갈래를 무시했다.

## 이번 PR 의 범위 (이슈 4번, 웹 콘솔만)

1~3번(PR 검사 spec-ready, start 스킬 멈춤)은 PR #674(브랜치 `fix/668-spec-gate`). 같은 기준을 쓴다: origin/main 에 `docs/spec/DEV-xxx-*.md` 가 있는가, 원장 Spec 칸 `설정` 은 설정 갈래.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `console/devready.py`(새), `server.py` | `GET /api/dev-ready?cwd=`. git 으로 origin/main 의 SRS·Spec·원장을 읽는다(`git fetch origin main` 포함). 60초 기억·요청 스레드 비대기(`cached` wait=False). 상태 `yes`/`no`(원장 없음·git 아님 = 해당 없음)/`unknown`(읽기 실패, 지어내지 않음) |
| `static/flow-logic.js` | `devReadyView`·`kindHint`·`devBlock`·`kindConflict` 순수 함수 |
| `static/flow-ui.js` | `devReadyFor`·`askCard`, `flowChooser` 가 종류와 AI 갈래가 다를 때 묻는 카드를 갈래 카드 대신 맨 위에 그림 |
| `static/app.js` | 종류 버튼 밑 안내 글, 개발하기 눌렀을 때 Spec 없음 카드, `begin()` 이 종류 갈래를 확정 선택으로 잡지 않음, 답하기 전 `이대로 시작` 막기 |
| `static/app.css` | `.kind.dim`·`.kind.hot`·`.khint`·`.askcard` |
| `docs/design/web-console.md`, `docs/guide/harness-guide.html` | API 표, 새 작업 설명, 레일 판 0.10.174 |
| `plugin.json` | 0.10.174 (열린 PR #671 0.10.172, #674 0.10.173) |

## 규칙

- 개발 건 = SRS 다음 단계 `개발`, 또는 SRS 에 없는데 원장에 있는 건. 설정 건 = 원장 Spec 칸 `설정`(SRS 다음 단계 `설정` 만 있고 원장에 없으면 세지 않는다 — #674 와 같은 기준).
- 할 차례(`needSpec`) = Spec 없는 개발 건. Dropped/Duplicate/On Hold, 원장 `완료`, 다음 단계 미정·빈 칸은 뺀다.
- 종류 버튼: 개발하기 = Spec 있는 건 수(0 이면 흐림 + "Spec 있는 건 없음 — 개발 Spec 먼저"), 개발 Spec = 할 차례가 있으면 강조 + "할 차례 REQ-001(제목) 외 n건", 설정하기 = 설정 건 수. 해당 없음·확인 못 함이면 표시 없음.
- 종류 버튼 갈래와 AI 갈래가 다르면 묻는 카드. 답하기 전에는 시작 불가. "그래도 개발하기" 는 Spec 없음이 확실할 때(읽었고 Spec 있는 건 0)만 막는다. 종류를 안 골랐으면 예전 동작.

## 남은 일 / 한계

- Spec 있는 건이 1개 이상이면 사용자의 글이 어느 DEV 를 가리키는지는 따지지 않는다(막지 않고 AI 카드만).
- 홈 빈 화면의 자주 하는 일 버튼(`flow-ui.js` KINDS)에는 안내 글을 붙이지 않았다(새 작업 화면만).
- 새 작업 화면의 브라우저 실제 화면은 이 PR 에서 시험 자동화(가짜 DOM)와 서버 API 시험으로 확인했고, 실제 sandbox 콘솔 눈 확인은 메인 세션이 한다.
