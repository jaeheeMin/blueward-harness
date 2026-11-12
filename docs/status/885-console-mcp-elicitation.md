# #885 웹 콘솔 MCP 질문(elicitation)을 화면에서 답하기

## 실측 (2026-11-12, claude 2.1.322, claude-haiku-5-5)

실험 폴더(세션 scratchpad `e885/`)에서만 했다. 자작 stdio MCP 서버(`elicit_mcp.py`, 표준 라이브러리)를
`--mcp-config mcp.json --strict-mcp-config` 로 연결하고, 도구 `ask_user` 를 부르면 서버가
`elicitation/create` 를 보내게 했다. 드라이버는 콘솔과 같은 인자(`claude -p --input-format stream-json
--output-format stream-json --verbose --permission-prompt-tool stdio`).

- claude 는 MCP initialize 에서 `capabilities.elicitation: {"form":{}, "url":{}}` 를 알린다(두 모드 다 받는다).
- MCP 서버의 `elicitation/create` 는 stdout 에 `control_request` 로 온다(도구 승인 can_use_tool 이 먼저 오고, 허용 뒤에).

form 모드 요청(로그 l1:18):
```
{"type":"control_request","request_id":"..","request":{"subtype":"elicitation",
 "mcp_server_name":"asksrv","message":"좋아하는 색과 팀 인원을 알려 줘","mode":"form",
 "requested_schema":{"type":"object","properties":{"color":{"type":"string","title":"색","enum":[...]},
   "size":{"type":"integer","title":"팀 인원","minimum":1,"maximum":50},"note":{"type":"string","title":"메모"},
   "ok":{"type":"boolean","title":"동의"}},"required":["color"]},
 "property_order":["color","size","note","ok"]}}
```

url 모드 요청(l4_url:18):
```
{"subtype":"elicitation","mcp_server_name":"asksrv","message":"이 주소에서 로그인해 줘","mode":"url",
 "url":"https://example.com/login","elicitation_id":"e885-1"}
```

| # | 보낸 답(control_response 의 response) | MCP 서버가 받은 result | 로그 |
|---|---|---|---|
| 1 | 답 안 함 | 120초 동안 기다림(claude 쪽 시간 제한은 보지 못함, 드라이버가 끔) | l1 |
| 2 | `{"action":"accept","content":{...}}` | 그대로 `{"action":"accept","content":{...}}`, 모델이 값으로 답을 이어 감 | l2:19 |
| 3 | `{"action":"decline"}` | `{"action":"decline"}` | l3_decline:19 |
| 4 | 지금 콘솔 답 `{"behavior":"deny","message":..}` | **`{"action":"cancel"}`** — 사용자에게 보이지 않고 닫은 것으로 처리 | l3_console:19 |
| 5 | url 모드에 accept + content | content 까지 그대로 전달(url 모드는 content 없이 보내야 맞음) | l4_url:19 |

- 확인 못 함: 답을 오래 안 할 때 claude 쪽 시간 제한, 사용자 MCP 설정과 같이 뜰 때(strict 없이) 모양 차이(ABAP 서버 연결을 피하려 안 돌림).
- 터미널 세션(콘솔이 띄우지 않은 세션)의 elicitation 은 터미널이 직접 묻는다. 이번 범위는 콘솔이 띄운 세션.

## 결정
- 콘솔이 띄운 세션의 `subtype:"elicitation"` 을 거부 대신 요청 카드(kind `elicitation`)로 띄우고, 사용자가
  보내기(accept + 값)·거절(decline)·닫기(cancel) 중 하나로 답한다. url 모드는 주소를 보여 주고 [다 했어](accept, content 없음)·거절·닫기.
- 세션이 끝나거나 요청이 닫히면 cancel 로 답한다.

## 구현 (0.10.274)

바꾼 것
- `managed.py`: control_request 의 subtype `elicitation` 을 `_bridge_elicitation` 으로 보낸다. 요청 카드(kind `elicitation`, tool_name `elicitation:<서버>`)를
  만들고 `r.event` 를 기다렸다 accept(form 은 content 포함, url 은 content 없이)·decline·cancel 로 답한다. 요청이 닫히면 cancel.
  요청 키는 request_id 기반이라 서로 다른 요청이 합쳐지지 않는다. mode 가 form·url 이 아니거나 schema 를 읽을 수 없거나 url 이 비면 카드 없이 cancel 하고 로그에 남긴다.
  대기 요청 한도를 넘어도 cancel. 그 밖의 subtype 은 지금처럼 `_deny_control`.
- `store.py`: `elicitation_fields`(schema 를 property_order 순서의 필드 목록으로 정리. 지원 타입 밖이면 None), 제목·답 요약, `public()` 의 `elicitation`.
  지원 모양: string(minLength·maxLength·format)·number·integer(minimum·maximum)·boolean·enum(enumNames·oneOf)·문자열 enum 배열(multi).
- `server.py`: `a_answer` 가 elicitation 에서 `{"action","content"}` 를 받아 schema 로 검증(필수·타입·enum 값·범위·길이·없는 키). 실패는 400. url accept 는 content 무시.
- 화면(`app.js`): `elicitCard` 하나를 대화 안(`inlineElicit`)과 `/r/<id>`(`drawElicitation`)가 함께 쓴다. 기존 `.q`·`.qopt`·`.qgroup`·`pill` 만 쓰고 CSS 는 그대로.
  url 은 http·https 만 링크(`target=_blank`, `rel="noopener noreferrer"`), 다른 스킴은 글로만 보이고 "열 수 없는 주소야".
- 길잡이(`harness-guide.html`) 콘솔 탭의 "답하는 것" 에 한 줄, 레일 판 0.10.274, whats_new 0.10.274.

시험
- `test_web_console.py` 7개, `test_web_console_ui.py` 4개 추가(`console_ui_smoke.js` 에 `disabledButtons`·`links` 출력 추가).
  고치기 전 코드(origin/main 의 console 파일)로 같은 시험을 돌리면 11개 모두 실패하는 것을 확인했다.

확인 못 한 것
- 브라우저 화면을 띄운 실사용 시험은 하지 않았다(아래 실측은 콘솔 Manager·Store·서버 검사까지, 화면은 UI 시험으로).

실측(콘솔 코드로, 2026-11-12, claude 2.1.322·haiku, 리베이스 뒤 머리)
- 드라이버 `e885/live885.py`: 콘솔 `Manager`·`Hooks` 로 실제 claude 를 띄우고(`--strict-mcp-config --mcp-config` 자작 서버), 요청을 `App.check_elicitation` 으로 검사해 `store.resolve`.
- 수락: 요청 kind `elicitation`, 제목 "연결 도구(asksrv)가 묻는 것: …", 필드 4개가 property_order 순서. 보낸 `{"color":"blue","size":5}` 가 MCP 서버에 `{"action":"accept","content":{"color":"blue","size":5}}` 로 도착, 모델이 그 값으로 답함.
- 거절: 대화 답 "거절함", MCP 서버는 `{"action":"decline"}`.
- 시험 뒤 남은 claude·MCP 프로세스 없음.
- 전체 시험(리베이스 뒤): `test_web_console.py` 1118 passed·4 skipped, `test_web_console_ui.py` 126 passed.
- 답을 오래 안 할 때 claude 쪽 시간 제한은 그대로 확인 못 함.
