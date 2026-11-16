# #1010 웹 콘솔: 새 작업 시작이 끊기는 문제 수정 (2026-11-16)

## 찾은 문제

11-16 Windows(0.10.297)에서 진짜 claude 세션으로 새 작업 화면을 직접 눌러 보니 시작 흐름이 끊겼다. 이슈 본문의 여덟 장면.

## 한 일과 이유

| # | 고친 것 | 곳 | 이유 |
|---|---|---|---|
| A1 | 시작에 성공하면 `/s/<id>` 로 바로 이동. id 가 없을 때만 옛 링크 한 줄 | `static/app.js` newView `start()` | "작업을 시작했어" 한 줄만 남아 팀원이 시작이 안 됐다고 느꼈다. 이동하면 뷰가 destroy 되어 `draw()` 는 `alive` 가드로 막힌다 |
| A2 | 사용자·종류 버튼이 안 골랐고 AI 가 `confident=false` + `alternativeId` 면 "어느 쪽에 더 가까운지 위에서 먼저 골라 줘." 로 시작을 막음 | `app.js` `startBlock()` | 고르지 않고 시작하면 "정해진 갈래 없음" 세션이 됐다. 서버는 막지 않는다(옛 호출 호환) |
| E-1 | 막힌 시작 단추를 `disabled` 대신 `aria-disabled` 로 두고, 누르면 고르는 카드로 스크롤·첫 단추 초점 | `app.js` `focusChooser`, `app.css` `.pill[aria-disabled]` | 이유가 단추 옆 작은 글뿐이라 왜 안 눌리는지 몰랐다. 시작 중에는 진짜 `disabled` |
| 분석 | 분석 지시문에 "작업 방식은 묻지 않는다" 를 더하고, 서버가 규칙 위반 보기·질문을 데이터 목록으로 거름 | `analysis.py` `PROMPT_BODY`·`check_result`·`break_rule`, 새 `console/analysis_block.json` | AI 가 "main 에 바로 커밋하고 푸시한다" 를 보기로 냈다. 동작어와 짝지은 정규식이라 내용 질문("main 브랜치 기준 SRS")은 남는다 |
| E-4 | 갈래 이름을 못 찾으면 서버가 준 `flow.name`·`alternativeName`, 그래도 없으면 "다른 일" (id 를 내지 않음) | `static/flow-ui.js` flowChooser `nameOf`·`foundName` | 갈래 id(`srs`)가 그대로 보였다 |
| E-6 | `잘 모르겠어`(갈래·미리 넣는 문장 없음)는 "AI가 요청을 읽고 어떤 순서로 할지 정해 줘." | `app.js` drawWrite 의 미리보기 note | "도구 스킬로 바로 시작" 은 틀린 안내였다. 판정은 이름이 아니라 `!k[2] && !k[3]` |
| E-10 | 새 작업 화면의 같은 폴더 경고는 `running`·`starting` 세션만 센다 | `static/flow-logic.js` `workingSessions`, `app.js` drawWrite | 쉬는 세션만 있어도 "일하고 있어" 라고 했다 |
| G-03 | 준비 안 된 폴더: 서버가 `canSetup`(GitHub admin 여부)을 intro 응답에 실음. 관리자만 `[만들기]`, 아니면 "관리자에게 말해 줘" + `[확인]`. 못 읽으면 문구 끝에 "(관리자인지 확인하지 못했어)" | `server.py` `a_folder_intro`·`repo_admin`, `app.js` drawIntro·checkIntro | 표준 구조는 관리자가 만든다(사용자 결정 11-16). 확인 못 함을 통과(관리자)로 뭉개지 않는다 |

### 추가: 관리자 여부 읽기가 03 안내를 늦추던 문제

화면 시험에서 준비 안 된 폴더를 고른 뒤 6초 넘게 평소 새 작업 화면이 보이다가 갑자기 03 안내로 바뀌었다. `/api/folders/intro` 가 `gh api`(이 PC 에서 약 3.8초 실측)를 기다렸기 때문이다(팀원·확인 못 함도 같은 대기).

- 서버(`server.py` `repo_admin`·`warm_admin`): 폴더가 알려지는 순간(validate·last 설정·recent 에서 준비 안 됨) 백그라운드로 미리 읽어 `cached` 에 둔다. intro 는 기다리지 않고 읽은 값이면 `canSetup` true/false, 읽는 중이면 `canSetup: null` + `adminChecking: true`, 읽기가 끝났는데 못 읽었으면 `adminChecking: false` + `canSetup: null`(못 읽은 값은 기억하지 않고 10초 동안만 재시도를 미룬다).
- 화면(`app.js` `checkIntro`·`askIntro`·`drawIntro`): `show` 면 바로 03. `adminChecking` 이면 "관리자인지 확인하는 중이야." 한 줄만, 1.5초마다 최대 10번 다시 물어 결과 화면으로 바꾼다. 폴더를 바꾸거나 화면을 떠나면 멈춘다. `seen` 은 최종 화면 뒤 한 번.
- 시험: gh 가 느려도 intro 가 바로 답함, validate 뒤 미리 읽기 시작, 못 읽음의 끝, 화면이 확인 중 → 결과로 바뀜(스모크에 `wait` 동작 추가).

분석 지시문의 "관리자가 프로젝트 구조 만들기를 해야 한다" 와 `flow-logic.js projectNotice` 의 "관리자가 처음에 한 번 기본 폴더 구조를 만들어 줘야 해" 는 이 결정(팀원은 관리자에게 말한다)과 이미 맞아서 고치지 않았다.

### 558 점검 반영 (머리 765bfd3 뒤)

- 시안 대조 G-03 이 23/24 로 떨어졌다: 시안용 가짜 콘솔(`checker/tests/console_mockup/fake_console/serve.py` 의 `fake_gh`)이 `gh api repos/{owner}/{repo} --jq .permissions.admin` 을 몰라 "확인 못 함" 화면이 그려졌다. 시안 G-03 은 관리자 화면이라 `true` 를 답하게 했다.
- `analysis_block.json` 이 SAP 업무 질문을 지웠다("구매 승인 단계를 생략할 수 있게 할까?", "품질 검사를 생략하는 자재 유형이 있어?", "main 화면에 바로 보여 줄까?" 등 7개). 승인·검사·검토 생략 규칙은 병합·머지·커밋·푸시·브랜치·doc-guard·risk-gate·하네스 낱말과 짝일 때만, `main … 바로/직접` 은 `main 브랜치` + 올리기·커밋 동사와 짝일 때만 걸리게 좁혔다. SAP 에서 PR 은 구매요청(Purchase Requisition)이기도 해서 승인·올리기 규칙에서 `PR` 낱말을 뺐다. 업무 질문 12개가 남는 시험(`test_check_result_keeps_sap_business_questions_…`)을 더했다.

## 시험

- `checker/tests/console_ui_smoke.js`: `scrollIntoView` 흉내와 `scrolled`·`active`·`ariaDisabled` 출력 추가.
- `test_web_console_ui.py`: 시작 뒤 이동(id 없음 포함), 확신 없는 분류 막기·칩으로 풀기·서버 이름·스크롤과 초점, `잘 모르겠어` 안내와 같은 폴더 경고(상태별), 준비 안 된 폴더의 관리자·팀원·확인 못 함 화면. 기존 03 시험은 `canSetup: true` 로 갱신.
- `test_web_console.py`: `folders/intro` 의 `canSetup`(true·false·못 읽음 다섯 모양, 60초 기억), 분석 지시문 문장, `check_result` 의 위반 보기·질문 거르기(실제 사례 포함, 오탐 방지 사례), `analysis_block.json` 형식, `check_flow` 이름 필드. 기존 intro 단언은 `canSetup: None` 으로 갱신.

결과 숫자는 PR 설명·보고에 적는다.

## 남은 것

- 세션 화면의 `sameFolderBusy`(`flow-logic.js`)는 쉬는 세션도 센다. 같은 문제로 보이나 이 이슈 범위 밖이라 건드리지 않았다.
- 완료 조건의 Windows 시험 콘솔 전후 그림(진짜 claude)은 메인 세션이 한다.
- `plugin.json` 판 올림, 길잡이(`docs/guide/harness-guide.html`) 새 작업 탭 갱신은 메인 몫.
