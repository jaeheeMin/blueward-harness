# #1065 Post 오늘 화면 내 세션 두 단 목록 + 메모가 장면을 따라가지 않는 문제 (2026-11-17)

## 배경
#1056(장면 칸 현장 메모) 뒤 실제 콘솔에서 두 가지가 보였다. (1) 내 세션을 시안 C 의 두 단 목록으로 바꾸기로 했다(#1056 에서는 범위를 줄이며 표로 되돌렸다). (2) 내 차례 메모가 부르는 사람 옆에 붙지 않고 기본 자리(left 21%, top 12%)에 머물며 장면을 끌어도 안 따라간다. Sauce 와 Post 의 다른 화면은 그대로. 모든 CSS 는 `:root[data-theme="post"]` 아래.

## 메모 원인 (가짜 세션으로 재현)
- 갈래(flow) 없는 세션 12개(내 차례 4건 = 대기 요청 2·deliver 차례 2, 막힘·확인 못 함, 일하는 중 4, 쉬는 중 2), 헤드리스 크롬 1440px.
- 메모는 덱과 같은 순서의 `topId`(= 가장 오래 기다린 `a1`)를 보여 주며 `scene.focus('a1')` 을 부른다. 그런데 장면은 `flow: ''` 인 세션을 모두 "리셉션" 한 곳에 줄 세우고 **자리 하나만** 그린다(번들 `draw()` 의 `'flow' in s` → `queue('reception')`, 자리만큼만 그림). 그 자리는 "내 답을 구하는 쪽 먼저, 그다음 목록 순서"(목록은 새로 시작한 세션이 앞)로 채워져, 그려진 사람은 `u1`(확인 못 함) 하나였다. 메모 세션 `a1` 은 장면에 없었다(`__o9.people` 키 = `i2, i1, u1`).
- 번들 `Scene.focus(id)` 는 `ctl.has(id)` 가 거짓이면 `focusId = null` 로 버렸고, 카메라는 "가장 오래 기다린 부르는 사람"(`u1`)을 주인공으로 잡아 `onFocus({id:'u1', x:936, y:352})` 를 계속 알렸다. 콘솔은 `foc.id !== memoId` 라 좌표를 무시하고 기본 자리에 두었다 — 장면을 끌어도 `u1` 좌표만 바뀌니 메모는 움직이지 않는다. 사용자 화면의 "안내 데스크 뒤 ?" 가 이 `u1` 자리다. 실제 세션이 모두 "정해진 갈래 없음" 이라 리셉션 한 자리에 몰리는 것이 근본.
- 호출값(고치기 전): `focus a1` → `onFocus u1 936,352 …`(a1 은 한 번도 안 옴), 메모 `style` 없음(기본 자리).

## 고침
| 파일 | 내용 |
|---|---|
| `ai-office-iso` `src/office10.ts`, `src/office-post.ts` → `plugins/harness/console/static/post/office/office-post.js` | `Live.wantId`. 콘솔이 `focus(id)` 로 보여 달라고 한 세션은 자기 종류 줄(`lq`)의 맨 앞에 세워 자리가 모자라도 먼저 그린다. `Scene.focus` 는 요청 id(`wantId`)를 기억하고, 목록에 있는데 안 그려진 세션이면 장면을 다시 짠다(`build()`). 다시 짠 뒤 그려졌으면 `focusId` 로 잡는다(목록에 아직 없던 세션이 나중에 생겨도 그때 잡힌다). 빈 catch·`innerHTML`·`eval`·`new Function`·`import(` 없음 |
| `plugins/harness/console/static/post-home.js` | 그 세션이 장면에 아예 없을 때(`foc` 없음·id 불일치)는 기본 자리에 꼬리 없이(`is-loose`) 둔다. 내 세션 두 단 목록(`sessionsPanel`) — 아래 |
| `plugins/harness/console/static/theme-post.css` | 두 단 목록·결재란·상태 칩, `.po-memo.is-loose::before`(꼬리 없음), 장면이 작은 창(PiP)에 가 있는 동안 메모 숨김(`.po-stagew:has(.bh-office-away) .po-memo`) |
| `plugins/harness/.claude-plugin/plugin.json`, `console/whats_new.json` | 0.10.319 → 0.10.323(열린 PR 이 0.10.320~322 사용) |
| `docs/guide/harness-guide.html` | 웹 콘솔 탭: 메모가 그 사람 옆에 붙는다·없으면 꼬리 없이·작은 창일 때 숨음, 내 세션 두 단 목록 |
| `checker/tests/test_web_console_ui.py` | 두 단 목록·메모·PiP 숨김 확인, `test_post_home_memo_follow_scene_bundle` |

## 내 세션 두 단 목록
- c6f7785 에서 가져온 것: 두 단(1100px 이하 한 단) `ul.po-mine`, 글자 아바타(`po-ava`), 제목·둘째 줄, 결재란(`po-kyul`: 칸은 `BHLogic.barSteps`, 이름은 `stepShort`, 끝난 칸 붉은 도장·지금 칸 남색 줄), 상태 칩(`po-stc` 색 + 모양).
- 안 가져온 것: 칩·레일 점·숫자 카드 삭제·범례 삭제·팀 strip·lede 변경·덱 숨김, "표로 보기" 링크.
- 바꾼 것: 상태 칩 글은 `내 차례·일하는 중·승인 기다림·쉬는 중·끝남·확인 못 함·막힘` 전부. 둘째 줄은 팀 이름, 팀이 없는 갈래는 갈래 이름, 갈래 없음은 `정해진 갈래 없음`(Sauce 표 둘째 줄과 같은 글). 갈래 없는 세션은 결재란 칸이 없고 자리만 있다 — 자리 폭은 목록에서 가장 긴 결재란에 맞춰(`칸 64px × 최대 단계 수`) 줄 정렬이 흔들리지 않는다. 머리 "내 세션 N개". 줄 순서는 `HK.sessionList()` 와 같다. 차분(fx=0)일 때도 이 목록. 760px 이하는 결재란을 숨긴다.

## 판단·남은 것
- 메모 세션을 먼저 앉히므로 리셉션처럼 자리가 모자란 곳에서는 메모를 "다음" 으로 넘길 때 앉은 사람이 바뀐다(장면이 다시 그려진다). 자리가 모자란 건 그대로다.
- 그려져도 장면 틀 밖(카메라가 못 담는 자리)이면 번들이 좌표를 알리지 않아(`tell` 이 null) 기본 자리·꼬리 없음.
- 작은 창(PiP) 중 메모 숨김은 번들이 패널에 단 `.bh-office-away` 줄을 CSS `:has()` 로 본다(번들 변경 없음). 헤드리스에서는 진짜 PiP 를 못 열어 iframe 의 window 로 `_moveTo` 하여 확인했다.
