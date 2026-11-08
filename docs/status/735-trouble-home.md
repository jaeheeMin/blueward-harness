# #735 웹 콘솔 홈에 고쳐야 할 내 PR·안 풀린 문제 수

## 배경
별도 "내 이슈·PR 목록" 화면은 만들지 않기로 했다. 빠진 것은 세션 밖의 "고쳐야 할 내 PR" 과 팀의 안 풀린 문제 수라서 홈에 한 줄씩 더한다(시안 G-24).

## 바꾼 것
- `console/gitstate.py` `my_open_prs`, `server.py` `GET /api/my-prs?cwd=`: `gh pr list --author @me` 의 열린 PR 과 검사 결과(fail/pending/pass/none). GitHub 저장소가 아니면 `no`, gh 실패는 빈 목록이 아니라 `unknown`. 60초 기억.
- `static/flow-ui.js` `fixCard`: 홈 타일 아래 "고쳐야 할 내 PR n건" 줄(검사 실패 PR 만, 3건까지 + "n건 더"). `AI 에게 고치라고 하기` 는 그 PR 의 보낼 수 있는 세션에 말을 보내고, 없으면 새 작업 입력칸에 문장을 넣어 간다. 못 읽으면 점선 `? 확인 못 함 · 폴더: 이유` 줄.
- 같은 파일 홈 다섯째 타일 "팀 기록 · 아직 안 풀린 문제 n건 [보기]"(`/api/trouble` 의 열린 수, `/troubles` 로 이동). 하나도 못 읽으면 0건이 아니라 `? 확인 못 함 · 이유`.
- `flow-logic.js` `prNeedsFix`, `app.js` 사이드바 "PR #n 고쳐야 함", 홈 표 상태 칩 "고쳐야 함"(일하는 중·끝난 세션 제외), `app.css` 시안 G-24 모양.
- 길잡이 `docs/guide/harness-guide.html`(웹 콘솔 탭 홈 항목), `docs/design/web-console.md`, `whats_new.json`, plugin.json 0.10.210.

## 시험
- `test_web_console.py::test_my_prs_lists_only_my_open_prs_with_check_results_and_never_hides_failure`, `test_web_console_ui.py` `dom_home_trouble_and_fix_pr`.
- 결과 숫자는 PR 본문에 적는다.
