# #682 웹 콘솔 세션 화면에 대화가 쌓이게 보이기

세션 화면은 AI 마지막 보고 하나와 이 탭에서 방금 보낸 말만 보였다. 대화가 쌓이지 않아 앞뒤를 알 수 없었다.

## 바꾼 것

- 서버(`store.py`): 세션마다 `s["chat"]`(오래된 것부터, 최대 200개, 글 최대 8000자). 항목은 `me`/`ai`/`req`.
  - `Store.add_chat(s, role, text, **extra)`: 바로 앞 항목과 role·글이 같으면 더하지 않는다(훅과 콘솔 전송, 마지막 블록과 Stop 보고가 겹친다).
  - 내 말: 훅 UserPromptSubmit 의 prompt, 콘솔 `managed.send`, 터미널 세션에 예약된 말이 Stop 으로 전달될 때. `chat_clean()` 이 시스템 블록(`task-notification`·`system-reminder`·`local-command-*`)을 걷어 내고 남는 글이 없으면 넣지 않는다. 슬래시 명령은 그대로.
  - AI 말: Stop 의 report, 콘솔 세션의 assistant text 블록 전체, result 글(Stop 이 못 왔을 때의 대비 경로).
  - 요청: `add_request` 가 `req` 항목(id·kind·title)을 더하고, `resolve`/`close` 가 같은 id 항목의 `answer` 를 채운다(질문은 고른 답 글, 승인은 허락함·거절함, 닫힘은 outcome 그대로). 응답 구조를 읽지 못하면 outcome 만 쓴다.
  - `load()` 는 chat 이 없거나 list 가 아니면 `[]`. `rekey` 는 chat 도 합친다.
- API: `public_session(..., include_chat)`. `GET /api/sessions/<id>` 만 `chat` 을 싣고(`?chat=0` 이면 뺀다), 목록과 SSE·그 밖의 응답에는 없다. 모든 응답에 `chatPartial`(터미널 세션이면 true).
- 화면(`app.js` `paintMsgs`): `s.chat` 을 시간 순으로 그린다. 내 말은 `.me`(줄바꿈 유지), AI 말은 `.ai` + 마크다운(긴 글은 항목별 접기), 요청은 끝났으면 `질문: 제목 → 답` 한 줄(`.reqnote`), 기다리는 중이면 '네 차례' 카드를 chat 안 자리에서 한 번만. 12개를 넘으면 앞을 접고 `… 앞 대화 N개 접힘`. chat 이 비면 예전처럼 마지막 보고. 터미널 세션이면 한 줄 안내. 이 탭에서 보낸 말은 서버 chat 에 같은 글이 들어오면 지운다. 새 항목이 오면 대화 끝이 화면 가까이 있을 때만 아래로 따라간다.
- 열어 보지 않는 세션의 갱신은 `?chat=0` 으로 받아 큰 응답을 피하고, `mergeSession` 이 받아 둔 chat 을 지우지 않는다.

## 시험

- `test_web_console.py`: 훅 프롬프트→me, Stop→ai, 중복 안 쌓임, 시스템 블록 전용 제외, req 추가와 answer 채움, 200개·8000자 상한, save/load, 목록엔 없고 단일엔 있음, chatPartial, 콘솔 세션 중복 제거, result 대비 경로, 예약 말 기록.
- `test_web_console_ui.py`: 12개 접힘 기준, 대기 카드 한 번만과 답 한 줄, chat 이 비었을 때 report.

## 남은 것

- 터미널 세션은 중간 AI 말을 모른다(훅이 Stop 의 마지막 답만 준다). 화면에 안내를 둔다.
- 브라우저에서 스크롤 따라가기와 `sent` 지우기는 실제 화면으로 확인하지 못했다(가짜 DOM 시험은 클릭·스크롤을 안 본다).
