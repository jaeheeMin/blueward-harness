# Post 테마 세션 화면 남은 기능 실화면 점검 (2026-11-18, 이슈 없음)

핸드오프: `.claude/handoff/2026-11-18-post-theme-verify.md` 6회차. 5회차(`2026-11-18-post-verify-sweep.md`)가 세션 화면의 대부분을 봤고, 남은 **갈래 5종의 단계 알약·단추, 다음 갈래 넘기기, wait(합치기) 단계 도우미, MCP `다시 연결`, 터미널 세션의 `콘솔에서 이어 가기`** 를 Post 실화면으로 눌러 봤다. 고친 것은 Post 전용 파일(`post-logic.js`·`post-home.js`·`theme-post.css`)과 공유 파일(`app.js`·`flow-ui.js`·`flow-logic.js`)의 Post 분기(`isPostTheme()`·Post 가 넘기는 인자)뿐이고 Sauce 출력은 그대로다. push·PR·판 올리기·새 소식·길잡이 없음.

## 방법
- 시험 세계: 5회차 도구(`world.py`·`w1070.py`·`gone.py`·`mk1.py`·`hk.py`)를 이 세션 scratchpad 로 옮겨 포트 4931 에 띄웠다. 서버를 띄우기 전에 `FAKE_MCP='[{"name":"asksrv","status":"failed",…}]'` 를 넣어 콘솔 세션마다 MCP 하나가 실패한 채로 시작하게 했다. 더한 것:
  - 갈래마다 콘솔 세션 하나(`screens.managed_session(…, flow=…)`): spec·dev·config·standard·srs-export, 넘기기용 srs(SRS 에 `다음 단계 = 개발` 요구사항 둘).
  - 단계 넘기기: 작업 브랜치(`git checkout -b`) → `hk.py <세션> <스킬>`(Skill + Stop 훅 흉내) → 커밋 → 원격 추적 브랜치 흉내(`update-ref refs/remotes/origin/<브랜치>` + `--set-upstream-to`, 시험 원격은 가짜 GitHub 주소라 push 가 안 된다) → 가짜 gh 에 PR(열림·합쳐짐·닫힘).
  - 터미널이 닫힌 터미널 세션 `t-resume`: transcript 를 `<scratch>/w/cfg/projects/…` 에 두고 빈 `<scratch>/w/cfg/sessions/` 를 만들어 `liveness = ended`.
  - MCP 실패 경로는 `FAKE_MCP_RECONNECT_FAIL=1` 로 서버를 다시 띄워 콘솔 세션 하나로 봤다.
- Aside 는 공유 잠금 아래 한 번에 하나씩. Post 라이트·다크 × 1440·390 스크린샷을 직접 보고 판단했다.

## 기능 표(이번에 본 것·결과)
| 기능 | 실제로 한 것 | 결과 |
|---|---|---|
| 갈래 5종 첫 단계 | spec·dev·config·standard·srs-export 세션(쉬는 중·일하는 중) | 정상 — 알약 `쓰기·올리기·승인·합치기·→ 다음: 개발` / `시작·구현·올리기·합치기` / `시작·설정·기록·…` / `시작·확인·기록·…` / `뽑기·올리기·승인·합치기`, 할 일 카드 `/harness:spec`·`start`·`srs 실행`, 일하는 중엔 꺼짐 + `지금 Claude Code 가 일하는 중이야.` |
| work 단계 `끝났어` | dev 구현·config 설정·기록·standard 확인·기록(변경 있음) | 정상 — `이 단계를 끝냈어.` 뒤 올리기 질문 카드(`올리고 검토 요청`·`아직`) |
| 올리기 → 합치기 대기 | `hk deliver` + 열린 PR | 정상 — 할 일 카드 대신 PR 카드(문서 검사·비밀값 검사·팀 승인, `다시 확인`), 알약 `✓ 올리기`, 사이드 `승인 기다림 · PR #50x`, `4번 창구 · 검토 창구` |
| PR 카드 `다시 확인` | PR 을 합쳐짐·닫힘으로 바꾸고 누름 | 정상 — 합쳐짐은 끝난 갈래 카드, 닫힘은 합치기 할 일 카드로 |
| wait 단계 도우미 | PR 이 닫힌 srs-export 세션: `다시 확인`·`/harness:prs 보기` | 정상 — `다시 확인했어.`, `/harness:prs 실행을 요청했어.` (PR 이 열려 있으면 이 카드 대신 PR 카드 — G-10 설계) |
| 다음 갈래 넘기기 | srs 끝 → `새 세션에서 개발 Spec 시작` → `넘어가기` → 이어 가기 글 확인 → `이대로 새 세션 시작` | 정상 — 넘길 것 `REQ-001, REQ-002 — DEV-001, DEV-002`, 새 세션 `개발 Spec (이어서)`(spec 갈래, 첫 단계), 원래 세션 `다음 세션으로 넘어감 → 새 세션 보기`. spec 끝은 `개발하기`, dev 끝은 `이 일은 끝났어 · 이어서 할 일이 없어` |
| MCP `다시 연결` | 콘솔 세션 노란 띠의 `다시 연결` | 성공: 띠 사라지고 기술 탭 `연결 도구(MCP) 모두 연결됨`. 실패: 띠 안 `다시 연결하지 못했어: …` — **다크에서 안 보임 고침**(아래) |
| `콘솔에서 이어 가기` | 터미널이 닫힌 `t-resume` 에서 할 말 입력 → `콘솔에서 이어 가기` | 정상 — `터미널이 닫힌 걸 확인했어.`, 같은 주소에서 콘솔 세션이 되고 답이 옴(입력칸·첨부 켜짐) |
| 차례 글(머리 제목·사이드 줄·홈 덱) | 위 세션들 | **갈래 단계와 어긋남 고침**(아래) |

모든 화면 콘솔 오류 0, 가로 넘침 0(1440·390).

## 고친 것
1. **갈래 세션의 차례 글이 갈래 단계 대신 git 추정을 따름**(`post-logic.js` 새 `turnLine`·`turnVerb`, `app.js` `headlineFor`·`sideStatus` 의 Post 분기, `post-home.js` 덱 문구). 서버의 `turnSkill` 은 git 상태로 짐작한 start·deliver·prs 라:
   - srs·spec 첫 단계(스킬이 브랜치를 만들기 전 main) → 머리 제목 `이제 작업 시작 차례야.`(할 일 카드는 `/harness:spec 실행`). 넘기기로 만든 새 세션도 같았다.
   - dev 구현 단계에 변경이 있으면 → `AI가 올릴 준비를 마치고 네 답을 기다리는 중`, 사이드 `내 차례 · 제출하기`(할 일 카드는 구현 `끝났어`).
   - 닫힌 PR 의 합치기 단계 → `이제 작업 시작 차례야.`
   - 홈 덱 카드: 올릴 차례 세션이 모두 `제출하기 끝남 — 다음을 정해 줘`(올리기는 아직이다).
   
   Post 는 갈래의 지금 단계를 따른다: `이제 Spec 쓰기 차례야.`·`이제 구현 차례야.`·`지금은 승인받고 합쳐지기 기다리기 단계야.`, 사이드 `내 차례 · 구현`. 올리기 단계에 올릴 변경이 있으면(G-09) 원래 글 그대로. 덱은 갈래 세션이면 같은 글, 올리기 단계면 세션 카드와 같은 `GitHub에 올려서 검토 요청(PR)을 만들까?`, 갈래 없는 세션은 `이제 제출하기 차례야.`. 갈래가 없거나 끝났거나 단계를 모르면 원래 글.
2. **어두운 모드에서 MCP 띠 안 실패 문구가 안 보임**(`theme-post.css` 끝): 노란 띠는 두 모드 모두 밝은 노랑인데 `.mcp-err` 가 어두운 모드의 밝은 `--attn`(#F2B24C)이었다 → 띠 안에서만 라이트와 같은 #9A5400.

확인: 고친 뒤 Post 라이트·다크 × 1440·390 에서 같은 세션·홈 덱을 다시 찍어 봤다(머리 제목·사이드 줄·덱 카드 글, 띠 실패 문구, 가로 넘침 0).

시험: `test_web_console_ui.py` 끝 `test_post_turn_text_follows_flow_step`(node 로 `turnLine`·`turnVerb` + app.js·post-home.js 원문), `test_post_mcp_error_readable_on_yellow_banner_in_dark`(원문). 전체 결과는 아래 「시험」.

## 독립 리뷰(서브에이전트 sonnet, 읽기 전용) 반영
- 확실한 결함 없음. Sauce 로 새는 경로 없음(app.js 세 곳 모두 `isPostTheme()` 뒤), 빈 세션·단계 없음·끝난 갈래·`L` 없음은 모두 `null`(원래 글), `.mcp-err` 는 `.banner.mcp` 안에서만 생긴다.
- 반영: 머리 제목에서 확인 대기·일하는 중·승인 기다림(`phase`)이 갈래 글보다 먼저 걸러지는 순서를 시험에 고정.
- 둘째 리뷰(공유 코드 Post 분기 넷)에서 결함 하나를 잡아 고침: `app.js mcpReconnect` 에 붙인 줄 주석이 뒤의 `.then(…)` 을 삼켜 `다시 연결` 단추가 「연결하는 중…」 에 멈췄다(Sauce 포함, `node --check` 는 통과). 주석을 문장 끝으로 옮기고, 시험이 `.then` 까지 한 줄로 확인하게 했다. 실화면으로 단추가 풀리고 다시 누를 수 있는 것을 봤다.
- 기록만(추측, 실제 조합 미확인): 합치기(wait) 단계인데 PR 이 열려 있지 않고 올릴 변경이 남아 있으면(turnSkill deliver) 덱이 내 차례 카드로 `지금은 합쳐지기 기다리기 단계야.`, 사이드 `내 차례 · 합치기` 를 보인다.

## 공유 코드의 틀린 글 — Post 분기로 고침
처음엔 공유 코드라 기록만 하려다, 사용자 지시(Post 에서는 하네스 기능이 다 돼야 하고 공유 코드라고 결함을 미루지 않는다)에 따라 Post 분기로 고쳤다. Sauce 출력은 그대로다(Sauce 는 평가·수정하지 않는다).
3. **닫힌 PR 카드가 검사 실패처럼 말함**(`flow-ui.js prCard`): 합쳐지지 않고 닫힌 PR 은 팀 승인 줄이 실패라 `✕ 막힘 · 자동 검사가 잘못을 찾았어. 고쳐서 다시 올려야 넘어가.`(검사는 `아직 돌고 있어`) → Post 는 `이 검토 요청(PR)은 합쳐지지 않고 닫혔어. GitHub 에서 다시 열거나 새로 올려야 넘어가.`
4. **조사 `PR #502이 합쳐졌어`**(`flow-logic.js` `phaseLine`·`finishedBand` 에 둘째 인자 `fix`, `app.js` 세 호출만 `isPostTheme()` 를 넘김) → Post 는 `PR #502가`·`PR #501이`.
5. **MCP 실패 문구 중복**(`app.js mcpReconnect`): `다시 연결하지 못했어: MCP 를 다시 연결하지 못했어: …` → Post 는 서버 글이 이미 같은 말로 시작하면 접두를 붙이지 않는다.
6. **넘긴 뒤에도 원래 세션에 넘기기 카드**(`flow-ui.js drawFinished`): `새 세션에서 개발 Spec 시작` 을 또 누를 수 있었다(서버는 진행 중인 넘기기만 막는다, 또 누르면 같은 일을 하는 세션이 하나 더 생김). Post 는 `다음 일은 새 세션으로 넘겼어` + `새 세션 보기`(기억 띠가 넘긴 세션에 넘기기를 숨기는 것과 같다).

확인: 새 시험 세계(PR #502 합쳐짐 srs 세션, PR #506 닫힘 srs-export 세션, `FAKE_MCP_RECONNECT_FAIL`)에서 실제로 넘기기를 한 번 하고 Post 라이트·다크 × 1440·390 으로 봤다 — 머리 `PR #502가 합쳐졌어. 다음 갈래는 개발 Spec이야`, 초록 띠 `PR #502가 합쳐졌어 — 다음은 개발 Spec`, 넘긴 뒤 카드, 닫힌 PR 카드 문구, MCP `MCP 를 다시 연결하지 못했어: Server not found or failed` 한 번, 가로 넘침 0. 시험 `test_post_shared_flow_text_fixes`(node 로 Sauce·Post 조사 + 원문).

## 고치지 않음
- 머리 숫자 칸: 단계 이름이 긴 단계(`올리고 검토 요청하기`·`합쳐지기 기다리기`)에서 칸이 두 줄로 접힌다(격자 줄바꿈, 깨짐은 아님).
- `flow-logic.js` 의 PR 배지 title(`이 세션의 PR #502 이 합쳐졌어.`)은 띄어 쓴 꼴이라 그대로 뒀다(마우스를 올려야 보이는 글).

## 시험 세계 메모
- `serve.py` 는 `App` 만 만들어 PR 1분 다시 판정(`start_pr_ticker`)이 돌지 않는다 — 가짜 gh 를 바꾼 뒤에는 화면의 `다시 확인`(또는 `/flow/refresh`)으로 반영된다.
- 시험 원격은 `https://github.com/example/proj.git` 라 push 가 안 된다. PR 단계로 넘기려면 원격 추적 브랜치를 흉내 낸다(위 방법).
- 서버 환경변수(`FAKE_MCP`·`FAKE_MCP_RECONNECT_FAIL`)는 가짜 claude 까지 그대로 간다 — 실패 경로를 보려면 서버를 다시 띄운다.

## 시험
`uv run pytest checker/tests/test_web_console.py checker/tests/test_web_console_ui.py -q` → **1569 passed, 2 skipped**(6분 8초). 덧붙인 시험: `test_post_turn_text_follows_flow_step`, `test_post_mcp_error_readable_on_yellow_banner_in_dark`, `test_post_shared_flow_text_fixes`(모두 `test_web_console_ui.py` 끝).
