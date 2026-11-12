# #900 웹 콘솔 API 오류 카드 다듬기 (0.10.265)

## 배경

#891(한도·로그인·재시도 오류 안내, 0.10.258) 병합 뒤 558 세션 리뷰에서 나온 네 가지.

## 바꾼 것

- `static/api-notice.js`: 모델 오류 본문이 없는 "설정" 을 가리켰다 → 새 작업 화면의 "고급 설정" 에서 다른 모델을 골라 새로 시작. 콘솔 설정 화면에도 "모델과 생각 깊이는 새 작업 화면의 고급 설정에서 바꿔" 라고 돼 있고, 세션 도중 모델을 바꾸는 길은 없다.
- `static/flow-ui.js`: `auth`·`limit`(apiIssue 또는 rateLimit `rejected`)·`model` 오류가 열려 있으면 다음 단계 카드·갈래 고르기 대신 "⚠ 오류 · 먼저 할 일" 카드(`data-api-hold`). 막힘(#791)과 같은 자리·같은 [그래도 다음 단계 보기] 넘기기. 넘김은 그 오류의 시각(`t`)마다 기억해, 새 오류가 오면 다시 안내한다. `other`·`unknown` 은 일시적일 수 있어 막지 않는다. 훅 막힘이 열려 있으면 막힘 안내가 먼저다.
- `static/app.js`: 오류 카드의 [자세히] 를 `pill line quiet-edge` → `pill line`. quiet-edge 는 막힘 카드처럼 다른 테두리 단추와 나란할 때만 글자 단추로 읽히고, 혼자면 밝은 판에서 글자만 보였다.
- `static/flow-ui.js` `bk ?h(` 띄어쓰기, `test_web_console_ui.py` `other =dict(` 띄어쓰기.
- 시험 `test_api_error_holds_next_step_until_login_or_limit`(세 종류·넘기기·갈래 없음·other 는 안 막음·rateLimit 만·모델 문구), [자세히] 테두리 단언. 고치기 전 코드로 돌려 실패 확인.
- 길잡이 웹 콘솔 탭, `docs/design/web-console.md`, whats_new 0.10.265.

## 확인 못 한 것

- 실제 오류 세션(로그인 풀림 등)으로 띄운 화면은 아니고 가짜 DOM 시험과 시안 검사 그림으로만 봤다.
