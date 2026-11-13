# #938 웹 콘솔 서버 API 오류 문구의 합니다체를 반말로

## 배경
#826·#928·#936 으로 웹 콘솔 문구를 반말로 맞춘 뒤에도 서버 API 오류 문구(`HttpError`)에 합니다체가 남아 있었다. 화면은 요청이 실패하면 이 문구를 "전달하지 못했어: …" 처럼 그대로 보여 주므로 팀원 눈에 보인다.

## 바꾼 것 (0.10.281)
| 파일 | 곳 수 | 예 |
|---|---|---|
| `plugins/harness/console/server.py` | 33(`HttpError`) | "text 가 비어 있습니다." → "text 가 비어 있어.", "허용되지 않은 Host 입니다." → "허용되지 않은 Host 야.", "POST 만 받습니다." → "POST 만 받아." |
| `plugins/harness/console/trouble.py` | 6(`HttpError`) | "number 가 필요합니다." → "number 가 필요해." |
| `plugins/harness/console/attachments.py` | 2(`AttachmentError`) | "attachments 는 목록이어야 합니다." → "…목록이어야 해." |

- `AttachmentError` 는 `server.py` 가 `HttpError(e.status, str(e))` 로 바꿔 화면에 보내므로 함께 바꿨다.
- 화면 js(`static/*.js`)에는 서버 오류 문구 글자로 분기하는 곳이 없다(서버 문구를 그대로 보여 주기만 한다).
- 이 문구를 글자로 기대하던 시험이 없어 시험 파일은 고치지 않았다.
- 길잡이 본문에 이 문구를 인용한 곳이 없어 레일 판 줄만 고쳤다. `whats_new` 는 드물게 보이는 문구라 넣지 않았다.

## 그대로 둔 것과 이유
- Claude 에게 가는 글: `managed.py` 의 deny message, `hooks_api.py` 의 stop_block·훅 응답(`error` 포함), `handoff.py`·`analysis.py` 의 프롬프트 문장.
- `flows.py` 의 workflow.json 검사 오류(개발자용). 단, `flow_error` 가 `HttpError(503, …)` 로 화면에 갈 수 있다 — 개발자용 오류라 두었다.
- `open.py`(터미널 출력), `launcher.py`, `server.py` 의 stderr 로그, 코드 주석.

## 메인 세션 대조 뒤 고친 것
- `platform_compat.py` 폴더 고르기 창(옛 대화상자로 뜰 때) 설명 "작업 폴더를 골라 주세요." → "작업 폴더를 골라 줘.": 콘솔의 [폴더 찾아보기]로 팀원이 보는 창이라 바꿨다.
- `server.py` 알림 설정 오류 "…만 받아:{…}" 의 빠진 띄어쓰기를 "…만 받아: {…}" 로.
- 바뀐 줄의 ASCII 부분(코드)이 바뀌기 전과 같음을 대조했다 — 한글 문구만 바뀌었다.

## 558 점검 뒤 더한 것 (같은 PR)
558 이 "바로가기를 누른 팀원이 직접 보는 창" 을 짚어, 팀원 눈에 보이는 나머지 문구도 같은 PR 에서 맞췄다.
| 파일 | 곳 | 어디에 보이나 |
|---|---|---|
| `launcher.py` | 3 | 바탕화면 바로가기 오류 창 |
| `open.py` | 9 | `/harness:open` 출력. 바로가기 오류 창에 그대로 뜬다 |
| `shortcut.py` | 5 | 바로가기 결과(콘솔 설정 화면·`/harness:open` 출력) |
| `server.py` | 5 | 산출물 칸 안내 3("…알 수 없어."·"…빠졌을 수 있어."), 새 작업 갈래 사유 1("…로 시작해."), 서버가 못 뜬 원인 1("포트 … 를 열지 못했어", open.py 의 "원인:" 으로 창에 뜬다) |
| `analysis.py` | 1 | 새 작업의 갈래 질문 "어떤 갈래로 진행할까?" |
- 시험 기대값 2곳(`stop_server` 결과, 바로가기 오류 창).
- 여전히 그대로: Claude 에게 가는 글, flows.py 개발자용 검사 오류, hooks_api.py 훅 응답, 코드 주석·로그.

## 시험
- `test_web_console.py`: 1118 passed, 4 skipped
- `test_web_console_ui.py`: 128 passed
- 추가 줄의 `(니다|십시오|세요)` 0건, 남은 `HttpError` 합니다체 0건.
