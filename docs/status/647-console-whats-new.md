# #647 웹 콘솔 — 플러그인 갱신 뒤 바뀐 점 안내

## 바꾼 것
- `plugins/harness/console/whats_new.json`: 판(plugin.json version)별 쉬운 말 한두 줄. 판 키가 없는 판은 안 띄운다.
- `server.py`: `GET /api/whats-new`, `POST /api/whats-new/seen`.
  - 콘솔이 실린 판(`/api/health` 의 version 과 같은 값)과 상태 폴더 `seen-version.json` 의 지난번 본 판을 숫자 단위로 비교한다(0.10.99 < 0.10.100).
    seen < 판 <= current 인 판 중 whats_new.json 에 줄이 있는 것만 새 판부터 준다.
  - seen 파일이 없으면(이 PC 에서 처음) 비워 주고 seen 을 current 로 저장한다(첫 실행 화면이 따로 있어 옛 변경을 쏟지 않는다).
  - 목록을 못 읽거나 current 를 모르면 비워 주고 seen 은 그대로 두며 `reason` 을 넣는다(다음에 읽히면 보인다).
  - seen 이 current 보다 크면(판을 내림) 비워 주고 seen 을 current 로 맞춘다.
- `static/app.js`·`app.css`: 홈 맨 위 카드 "하네스가 새 판(0.x.y)으로 바뀌었어 · 이번에 바뀐 것" + 판별 줄 + [알겠어](seen 저장 뒤 닫힘).
  첫 실행 화면이 뜨는 동안에는 서버에 묻지도 않는다. 전체 8줄을 넘으면 앞 판들만 보이고 [더 보기].
- 시험: `test_web_console.py`(서버 7개), `test_web_console_ui.py`(화면 2개).

## 약속
판을 올리는 PR 이 팀원이 알아야 할 변경이면 whats_new.json 에 그 판의 쉬운 말 한두 줄을 더한다
(규칙 정본: `plugins/harness/rules/issue-and-release.md` "엔진 배포" 절). 시험·내부 정리는 적지 않는다.
