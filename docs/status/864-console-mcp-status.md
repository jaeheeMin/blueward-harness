# #864 웹 콘솔 세션의 MCP 연결 상태와 MCP 도구 승인 (2026-11-10)

## 배경

SAP MCP(abap-adt)가 연결에 실패해도 콘솔 팀원은 AI 가 왜 도구를 못 쓰는지 몰랐다(콘솔은 `system/init` 의 `mcp_servers` 를 읽지 않았다). MCP 도구 승인 카드는 `mcp__abap-adt__getObjectSource` 같은 원문 이름을 그대로 보였다.

## 바꾼 것 (0.10.259)

- `console/managed.py`: init 의 `mcp_servers` 를 세션 `mcpServers` 로 적고, 연결 안 된 서버가 있으면 별도 스레드에서 `control_request(mcp_status)` 로 실패 사유를 받아 채운다. `refresh_mcp`·`reconnect_mcp`(`mcp_reconnect` 뒤 `mcp_status`). `can_use_tool` 의 `mcp_server`·`display_name` 을 요청에 싣는다.
- `console/store.py`: `mcp_view`(상태를 ok/problem/none/unknown 과 쉬운 말로), `mcp_request_info`(`mcp__<서버>__<도구>` 풀이), 요청 모델 `mcp`, 세션 모델 `mcp`.
- `console/server.py`: `POST /api/sessions/:id/mcp/reconnect`.
- `console/static/app.js`·`app.css`: 세션 화면 알림(실패만 눈에 띄게, 모두 연결되면 조용, 터미널 세션은 기술 정보에 "확인할 수 없어"), [다시 연결], MCP 승인 카드 문장.
- 시험: `test_web_console.py`(init·mcp_status 실측 모양, 라우트, 승인 요청), `test_web_console_ui.py`(알림·단추·카드), `fake_claude.py`(`FAKE_MCP`, `mcp_status`·`mcp_reconnect`).
- `docs/design/web-console.md` §7d, 길잡이(웹 콘솔 탭), `whats_new.json`.

## 정직하게 둔 것

- 터미널 세션은 init 을 못 받아 `unknown`("확인할 수 없어"). 연결됨으로 뭉개지 않는다.
- 11-11 main 위로 옮길 때 시안 검사 G-09(터미널 세션 화면)가 이 알림 띠 때문에 57.5px 밀려 실패 → 띠를 없애고 "자세히 > 기술 정보" 의 `연결 도구(MCP)` 줄로 옮김.
- 11-11 점검 반영: 되돌릴 수 없는 MCP 승인(SAP 쓰기 등)은 '자세히(도구 이름·넘기는 값)' 를 펼쳐 둔다. 새 문구는 콘솔 기본인 반말로 맞춤.
- 모르는 status 값은 문제로 보고 원문을 같이 보인다.
- 다시 연결 요청이 받아들여져도 연결됐다고 단정하지 않고 새 상태(`mcp_status`)로만 보인다.

## 남은 일

- MCP elicitation 등 `mcp__` 가 아닌 `control_request` 는 아직 거부로 답한다(형식을 실측하지 않았다).
- `needs-auth` 는 다시 연결로 안 풀려 "터미널에서 /mcp 로 로그인" 안내만 한다.
- 실제 세션에서 실패한 MCP 가 화면에 보이는지는 가짜 claude 로만 시험했다(실제 claude 로 띄운 콘솔 화면은 확인하지 않았다).
