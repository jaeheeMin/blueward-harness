# Post 테마 검증 갈래 B — 홈 결함 4건 (2026-11-18, 이슈 없음)

핸드오프: `.claude/handoff/2026-11-18-post-theme-verify.md` 의 갈래 B. Post 테마만 고쳤고 Sauce(app.js·app.css·flow-ui.js)는 건드리지 않았다. push·PR·판 올리기·새 소식 없음(사용자가 나중에 함). #1066 은 닫지 않았다.

## 한 일
| # | 결함 | 고친 곳 | 내용 |
|---|---|---|---|
| 2 | 「고쳐야 할 내 PR」이 홈에 머무는 동안 갱신 안 됨 | `post-home.js` | 61초마다 `delete fixBox.dataset.ready` 후 `HK.fixCard(fixBox)`. 홈을 떠나면 `clearInterval`. flow-ui.js 의 캐시(60초)는 스스로 낡아 간다 |
| 3 | 세션 0개·불러오는 중에 새 소식 카드 없음 | `post-home.js` | 두 경로에서 `slots.whatsSlot` 을 `restSlot` 에 붙이고, 세션이 생기면 `foot` 으로 되돌린다 |
| 4 | 세션 표에 번호·기억·API 오류·고쳐야 함 칩 없음 | `post-home.js`, `theme-post.css` | `metaLine`(이슈 #·PR 칩·기억 %, 줄 전체가 링크라 PR 은 글자만), `rowChip`(API 오류 → 오류 칩, 검사 실패 PR → "고쳐야 함"). 기억을 모르면 ? 를 지어내지 않고 뺀다 |
| 5 | #1066 잘린 직원 아바타·점선 ? 원 | `theme-post.js`, `theme-post.css` | 작은 아바타(`size:'sm'`)는 글자 아바타. app.js 사이드 목록은 이름을 안 넘겨서 `MutationObserver` 가 같은 줄 제목(접힌 레일은 title)에서 첫 글자를 채운다. 기억을 모르는 점선 ? 링은 CSS 로 숨김(title 문구가 `memoryOf` 와 같아야 해서 시험이 지킨다) |

## 확인
- `uv run pytest checker/tests/test_web_console.py checker/tests/test_web_console_ui.py -q` → 1537 passed, 2 skipped. 시험은 원문 확인(ui 시험 끝에 덧붙임)이다. post-*.js 는 가짜 DOM 시험이 안 불러와서 아래 실화면 확인이 본체다.
- Aside 실화면(시험 서버 따로: 실데이터 4911, 가짜 콘솔 g24 4912, 빈 상태 4913), JS 에러 없음(`page.console.logs()` 빈 목록), 가로 넘침 없음.
  - #4: 라이트·다크 × 1440·390 에서 이슈 #·PR #812 · 검사 실패·기억 % (81% 는 경고색)·"고쳐야 함" 칩.
  - #3: 라이트·다크 × 1440·390 에서 세션 0개일 때 "이번에 바뀐 것" 카드.
  - #5: 라이트·다크 1440 사이드 목록과 390 접힌 레일 — 그림 0개, 글자 아바타, ? 링은 기억을 알 때만(DOM: `.po-si .po-av img` 0, 모르는 줄은 `display:none`).
  - #2: 홈을 연 채 PR 검사를 통과로 바꾸니 약 65초 뒤 「고쳐야 할 내 PR」이 사라짐.

## 확인 못 한 것·한계
- API 오류 칩(`po-stc-err`)은 실화면에서 못 만들었다(Sauce 표와 같은 `BHApiNotice.notice` 판정을 쓰는 코드만 확인). 색은 기존 `po-stc-wait` 패턴(네모 + `--attn`)을 따랐다.
- "불러오는 중"일 때 새 소식 카드는 실화면으로 못 봤다(코드 경로만, 세션 0개 경로와 같은 호출).
- 가짜 콘솔 시험 중 한 번, 홈 세션 목록이 0줄로 보인 적이 있다(PR 상태를 바꾼 직후 약 70초 시점). 이후 같은 절차를 두 번 다시 해서 재현되지 않았고 그때 `.fixpr` 사라짐은 설명이 갈려, #2 는 재현된 두 번째 실행(세션 3줄 유지, 65초에 `.fixpr` 1→0)으로 판단했다. 가짜 세션이 서버에서 만료됐을 가능성이 있다.
- 사이드 글자 아바타는 DOM 관찰로 채운다. 이름을 넘겨 주면 되는 app.js 두 줄(`avatar(..., { name })`)이 정석이지만 이 갈래 소유가 아니라 하지 않았다.
