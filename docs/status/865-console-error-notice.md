# #865 웹 콘솔 API 오류·재시도·사용 한도 안내 (2026-11-10)

## 배경

콘솔이 띄운 세션이 로그인 풀림·한도·서버 오류로 멈춰도 '오류로 끝남' 로그 한 줄뿐이었다. 더 나쁘게는 오류 `result` 가 `subtype:"success"` 라서 그 오류 문장("Invalid API key …")이 AI 말·보고로 대화 판에 들어가 정상 답처럼 보였다.

근거: claude -p stream-json 실측(claude 2.1.321, 로그 l1·l6·lD1·lD2).

- 오류 result: `is_error:true`, `terminal_reason:"api_error"`, `api_error_status`(401 인증, 404 없는 모델), `result` 에 오류 문장.
- 앞서 오는 assistant: `error:"authentication_failed"|"model_not_found"`, `is_api_error_message:true`, 모델 `<synthetic>`.
- `system/api_retry`: `attempt`, `max_retries:10`, `retry_delay_ms`, `error_status`(연결 실패는 null), `error`("unknown").
- `rate_limit_event.rate_limit_info`: `status`(`allowed_warning` 등), `rateLimitType`, `utilization`, `resetsAt`(초).

## 바꾼 것

- `console/managed.py`: 위 이벤트를 세션 `apiIssue`(auth·limit·model·other·unknown·retry)·`rateLimit` 으로 받는다. is_error result 의 글은 AI 말·보고로 쓰지 않는다. API 오류 표시가 없는 is_error 는 `unknown`. 성공 result·새 메시지·새 `init` 에 닫는다. auto 모드 불가 안내(`permissionNote`)로 처리된 오류는 카드를 따로 만들지 않는다.
- `console/store.py`: 세션 모델에 `apiIssue`·`rateLimit`. 콘솔을 다시 켜면 저장된 retry 는 버린다.
- `console/static/api-notice.js`(새 파일, `BHApiNotice`): 쉬운 말·현지 시각 변환 순수 함수. `index.html` 에 실음.
- `console/static/app.js`: 대화 판 ⚠ 카드(원문은 `자세히`), 왼쪽 목록·레일·맨 위 띠("⚠ 오류 n건", 훅 막힘 띠와 따로)·세션 제목. `flow-ui.js`: 홈 표 상태 칩. `app.css`: 노란 실선 + ⚠(훅 막힘 ✕ 빨강·? 보라 점선과 다른 모양), 재시도·한도 경고는 회색 안내.
- 시험: `test_web_console.py`(이벤트 → 세션 상태 6개), `test_web_console_ui.py`(문구·시각 1개, 화면 1개), `console_ui_smoke.js` 가 api-notice.js 를 싣게.
- 길잡이 작업 화면 설명, `docs/design/web-console.md`, whats_new 0.10.258, plugin.json 0.10.258.

## 확인 못 한 것

- 재시도를 다 쓴 뒤 최종 result 모양(실측이 90초에 끊김). is_error 면 앞선 재시도 정보를 가진 서버 오류(`other`)로 남긴다.
- 한도에 실제로 걸렸을 때(`rejected`)의 이벤트·result 모양, 429 의 `error` 이름. 상태 번호 429·`rate_limit` 을 한도로 본다(추정).
- 로그인 안 한(키 없음) 경우의 문구.
- 실제 브라우저 화면 확인은 안 했다(가짜 DOM 시험만).
