# #1027 웹 콘솔 상태 표시(PR·단계·내 차례)가 화면마다 다르게 보이는 문제 (2026-11-17)

## 배경
웹 콘솔 고칠 점 65건을 원인별 7묶음으로 나눠 고치는 중이다(1순위 이슈 1011 새 작업 시작, 2순위 이슈 1018 승인+보안). 이 이슈는 3순위 "상태 표시" 묶음이다. 같은 사실(PR·단계·내 차례)을 화면 여러 곳이 서로 다르게 보여 주던 것을 한 값으로 모았다. 판 0.10.305 → 0.10.307.

## 사용자 결정
| 번호 | 결정 |
|---|---|
| D5 | 내 차례는 사람이 실제로 답할 대기 요청(승인·질문·계획·MCP 질문)이 있는 세션, 고칠 PR, 작업 브랜치에 올릴 변경이 있는 세션(deliver 짐작, 시안 G-11). 쉬는 main 세션(start 짐작)·남의 승인 대기(prs 짐작)는 뺀다 |
| D6 | stop-deliver 의 "커밋 안 된 변경" 은 막힘으로 안 센다(대화 기록 한 줄만) |
| D7 | ~~새 작업에는 시작 점검 두 줄을 만들지 않는다~~ → 11-17 사용자 결정: 시안 G-13 대로 점검 두 줄은 유지하고, 건너뛴 줄은 "건너뜀" 으로 보인다 |
| D8 | 홈이 열려 있는 동안 내 PR 은 1분마다 자동 갱신 |
| 단계 넘김 | PR 이 열리면 "올리기" 까지 끝난 것으로 보고 "합쳐지기 기다리기" 로, 병합되면 끝으로 넘긴다([끝났어] 안 눌러도) |
| 목록 순서 | 묶음(내 차례·막힘 → 일하는 중 → 쉬는 중 → 끝남)은 유지, 같은 묶음 안은 세션 시작 시각(없으면 id)으로 고정. updatedAt 으로 정렬하지 않는다 |

## 한 것
| 항목 | 원인 | 고친 곳 |
|---|---|---|
| B-3 시작 점검 "아직" | `checkState` 가 `skipped` 를 몰라 todo 로 떨어짐 | `static/flow-logic.js`(`skipped` → "건너뜀"), `static/flow-ui.js`(행 모양). 새 작업에서 점검을 빼던 구현(D7)은 시안 대조 G-13 과 달라 사용자 결정으로 되돌렸다 |
| D-1 PR 아직·고치기에 머묾 | `prCell` 이 flowId 가 있으면 prLinks 를 안 보고 "PR 아직". 평가가 "고치기"(has_changes+manual)에서 멈춰 PR 을 안 읽음 | `flow-logic.js` `prCell`(prLinks 먼저), `flows.py` `evaluate`(지금 단계와 무관하게 PR 을 한 번 읽고, 열림·병합이면 병합 대기 앞 단계를 끝으로) |
| D-2 내 차례 | 띠·알림·레일·홈 타일이 서로 다른 계산(turnSkill·askedInText 포함, 홈은 세션 수·띠는 요청 수) | `store.py`(group: 대기 요청이 있을 때만 todo), `flow-logic.js`(`groupOf`·`turnItems`·`NO_TURN_TEXT`), `app.js` `sideData`·`openIds`, `flow-ui.js` 홈(타일·카드·"지금 네가 할 일은 없어") |
| D-3 추정 | askedInText 가 todo 로 셈 | 위와 같음. 세션 본문의 참고 한 줄·제목은 그대로 |
| D-4 PR 자동 갱신 | 홈이 한 번만 읽음. 세션의 PR 칸·단계는 훅(턴 끝)이 올 때만 다시 판정 | `flow-ui.js` 홈 타이머 61초(서버 60초 기억 뒤), `CACHE_MS` 30초 → 60초(서버 `CACHE_SECONDS` 와 같게). 메인 점검에서 더함: 서버 `start_pr_ticker`(실제 서버 `main` 에서만 켬)가 60초마다 열린 PR 이 있거나 PR 을 근거로 끝나는 단계의 세션만 `advance_flow` 로 다시 판정 — 검사 결과·병합이 세션 화면에도 저절로 반영 |
| D-6 목록 흔들림 | updatedAt 으로 정렬 | `flow-logic.js` `sessionOrder`, `app.js`·`flow-ui.js` 가 같은 함수 사용 |
| D-7 영영 읽는 중 | `cached` 의 compute 에 except 없음 → last 가 안 채워져 loading 고정. 못 읽은 unknown 도 다시 읽는 동안 loading 이 덮음 | `server.py` `cached`(예외를 unknown 사유로 남김, 못 읽은 값은 loading 안 붙임) |
| D-8 병합된 문서 "안 올림" | 옛 로컬 `origin/<기본>` 과 비교 | `gitstate.py` `upload_states`(판정 전 `git fetch origin <기본>` 60초에 한 번, ref 를 못 읽으면 unknown) |
| D-9 설정 GitHub 줄 | state 'no' 도 "연결돼 있어" | `app.js` 설정(GitHub 저장소가 아니면 사유), `gitstate.py` `approval_prs` 가 `github: false` 를 냄 |
| D6 stop-deliver | 막힘 카드(block)로 쌓임 | `hooks_api.py` `blocked()`(hook 이 stop-deliver 면 `note` 한 줄, 막힘 수에 안 넣음) |
| 시작 직후 "쉬는 중" | group 이 starting 을 idle 로 계산 | `store.py`(starting 도 running) |
| 항목 12 승인 대기 | risk-gate·ssot-approval 의 실패가 "검사 실패 → 고치기" 로 셈 | `gitstate.py` `summarize_checks`(두 검사의 실패는 세지 않고 `awaitApproval` 로 따로), `flow-logic.js` `prBadge`("승인 기다리는 중") |

문서: `docs/design/web-console.md`(group·내 차례·정렬·점검·PR 단계·my-prs·stop-deliver·산출물 칩), `docs/guide/harness-guide.html` 웹 콘솔 탭(보는 것·글로 물어본 세션·홈과 도구 줄). 새 판 안내 `console/whats_new.json` 0.10.307.

## 시험
- `checker/tests/test_web_console.py`: 새 시험 — 승인 검사 실패 제외·`awaitApproval`, fix 갈래에서 PR 열림→병합 대기·병합→끝, 닫힌 PR 은 안 넘김, `upload_states` fetch 1회·60초·ref 못 읽으면 unknown, `cached` 예외 사유, stop-deliver 는 note. 고친 시험 — group 규칙(turnSkill·askedInText 는 idle, starting 은 running), 새 작업 시작 점검 없음.
- `checker/tests/test_web_console_ui.py`: 새 시험 — 내 차례는 실제 요청만·`turnItems`·시험 고정 정렬·건너뜀 점검·prLinks 우선·승인 기다리는 중 칩.
- 결과 숫자는 아래 "시험 결과" 에 적는다.

## 실사용 시험(11-17, Windows 시험 콘솔, 화면 직접 + 진짜 claude)

시험 저장소에서 [새 작업] 으로 "README 한 줄 더하고 올려 줘" 를 시작하고, 승인은 시험 도구가 누르되 병합 승인 앞에서 멈췄다.

| 장면 | 본 것 |
|---|---|
| 시작 직후 | 시작 점검 두 줄 없음(D7) ✅, 왼쪽 목록 "작업 중"(시작 중도 일하는 중) ✅ |
| AI 가 PR #34 를 만들고 병합 승인 대기(턴 중간) | 내 차례 1 = 그 승인 카드 ✅. **PR 칸이 "PR #32"** ❌(PR 목록 출력에 스친 다른 브랜치의 PR), 단계 "1 / 4 시작" ❌(턴 중간이라 판정이 안 돎) |
| 병합 승인을 화면에서 거부 → 턴 끝 | 단계 "4 / 4 승인 기다림", PR 칸 "PR #34 검토 중", 목록 "승인 기다림 · PR #34", 내 차례 아님 ✅ |
| GitHub 에서 PR #34 병합(콘솔은 아무것도 안 누름) | 약 20초 안에 "4 / 4 끝 · PR #34 합쳐짐" ✅(서버 1분 다시 판정) |
| 홈 | 내 차례 0 · "지금 네가 할 일은 없어" ✅. **"고쳐야 할 내 PR #32 · 검사 실패"** ❌(#32 는 risk-gate·ssot-approval 승인 대기인데 검사 묶음 job `pr-checks / check` 도 실패로 와서), **표의 PR #34 칩 "검사 진행 중"** ❌(이미 합쳐짐) |

시험에서 찾은 것을 고쳤다:
- PR 칸: `prLinks` 는 출력에 스친 모든 PR 주소라 갈래 세션에는 쓰지 않고, `gh pr create` 출력의 PR 만 `prCreated` 로 따로 남겨 쓴다(`hooks_api.py`, `store.py`, `flow-logic.js` `prCell`). 서버 1분 다시 판정도 `prCreated` 가 있는 세션을 지켜본다(턴 중간에 PR 을 만든 세션).
- 검사 요약: 승인 관문과 검사 묶음 job(`pr-checks`·`pr-review`·`main-checks`)의 실패, 순서 표시(`merge-order`·`pr-queue`)는 세지 않는다 — 엔진 `checker.risk_gate.EXCLUDED_CHECK_GROUPS`·`checker.pr_queue` 와 같은 규칙(`gitstate.py`).
- PR 칩: 합쳐짐·닫힘이 검사 상태보다 먼저(`flow-logic.js` `prBadge`).
- 시험: `test_pr_created_is_only_the_pr_this_session_made`, `summarize_checks` 시험에 #32 모양, UI `pr_cell_prefers_session_pr_links`·`pr_badge_says_waiting_for_approval`.
- 고친 뒤 화면 확인(2회차): 홈의 "고쳐야 할 내 PR #32" 가 사라지고 표가 "PR #34 · 합쳐짐" ✅. 그런데 **두 번째 작업 세션이 시작하자마자 "4 / 4 끝 · PR #34 합쳐짐"** ❌ — 시험 저장소가 앞 세션의 병합된 브랜치(docs/33)에 남아 있었고, "어느 단계든 PR 을 미리 읽어 열림·병합이면 넘김" 이 그 브랜치의 PR #34 를 읽어 첫 단계부터 끝냈다. 고침: 미리 넘기는 근거는 **이 세션이 만든 PR(`prCreated` → 갈래 state `createdPr`)뿐**이고, 그 PR 은 번호로 읽는다(`server.advance_flow`·`read_evidence`). 다른 PR 을 읽었으면 세션의 PR 정보(`pr`·`prNumber`)를 되돌린다(`flows.evaluate`). 시험 `test_merged_pr_of_an_old_branch_does_not_finish_a_new_flow`, `test_open_pr_moves_…`(브랜치로만 찾은 PR 은 안 넘김 → prCreated 가 생기면 넘김).
- 3회차(병합된 브랜치 docs/35 에 남은 채 새 작업): 시작 "1 / 4 시작 · PR 아직" ✅. AI 가 PR #38 을 만들고 병합 승인을 기다리는 턴 중간에 "4 / 4 합치기 · PR #38 검토 중", 내 차례 1(그 승인) ✅. 남은 것: 작업 기록이 "이슈 #35"(실제 #37) — 브랜치 이름을 턴 끝에만 다시 읽어서. 고침: 1분 다시 판정이 갈래만이 아니라 `refresh_git_now`(브랜치·변경·갈래)를 부른다.

## 시험 결과
| 명령 | 결과 |
|---|---|
| `checker/tests/test_web_console.py` | 1282 통과 · 0 실패 · 4 건너뜀 (구현 직후) |
| `checker/tests/test_web_console_ui.py` | 156 통과 · 0 실패 (구현 직후) |
| main 위로 옮긴 뒤 `test_web_console.py`+`_risk.py` | 1437 통과 · 4 건너뜀 |
| main 위로 옮긴 뒤 `test_web_console_ui.py` | 183 통과 |

UI 시험 러너는 홈의 1분 타이머가 node 를 붙잡아 멈추지 않게 케이스 끝에 `process.exit(0)` 을 더했다.

## 판단과 확인 못 한 것
- D-9: 요청은 "approvals state 'no' 면 GitHub 저장소가 아니야" 였지만 서버의 'no' 는 "승인자가 아님" 도 뜻해서, 서버가 `github: false` 를 따로 낼 때만 그 문구를 쓴다. 승인자가 아닌 사람이 "GitHub 저장소가 아니야" 를 보지 않게 하려는 것이다.
- D-7: 프런트 `LOADING_POLL` 루프를 고치지 않고 서버가 못 읽은 unknown 에 `loading` 을 안 붙이게 해서 루프가 저절로 멈춘다. 첫 계산 전 자리표시(unknown+loading)는 그대로 읽는 중이다.
- D-1: PR 은 지금 단계와 무관하게 매 판정마다 한 번 읽는다(gh 한 번 추가). 메인 점검에서 고침: PR 이 필요 없는 단계(고치기 등)에서 미리 읽다 못 읽은 사유는 `unknown` 에 남기지 않는다(전처럼 PR 을 근거로 끝나는 단계부터 "확인 못 함"). 시험 `test_flow_early_pr_read_failure_leaves_no_unknown_on_steps_without_pr`. `workflow.json` 은 바꾸지 않았다.
- "고쳐야 할 PR"(G-24, 검사 실패한 내 PR)은 사람이 직접 할 일이라 내 차례로 계속 센다. D5 문구에 없어 판단이 갈릴 수 있다.
- 내 차례 개수는 요청 하나·고칠 PR 하나가 한 건이다(띠·알림·레일·홈 타일 모두). 홈 타일은 전에 세션 수였다.
- D-8: fetch 는 판정 요청 스레드 안에서 한 번 돌아 서버 `run`(gh 용 20초 제한)을 쓴다. "짧은 timeout" 은 따로 두지 않았다(실패해도 진행). 60초에 한 번.
- 시작 점검 탭이 아니라 새 작업 시작에서만 뺐다. 다음 갈래 넘기기 세션은 점검 두 줄을 그대로 가진다.
- 실제 claude·Windows 콘솔에서 화면을 눌러 보는 전후 확인(이슈 완료 조건)은 하지 못했다. 시험은 단위·가짜 DOM 이다.
- 시안 대조(G-xx)는 돌리지 않았다. 홈에 "지금 네가 할 일은 없어" 한 줄이 새로 생겨 시안과 다르다(할 일이 0건일 때만).
- origin/main 은 시작 뒤 0.10.308 로 올라갔다. main(#1023·#1028·#1031) 위로 옮기며 판 0.10.309 로 맞췄다. #1028 이 홈 표를 `homeTable` 로 옮기고 Post 홈(`post-home.js`)을 더해서, 같은 내 차례 규칙(`turnItems`·`openIds`)을 그쪽에도 적용했다. 길잡이 기준 판 표기도 0.10.309 로.
