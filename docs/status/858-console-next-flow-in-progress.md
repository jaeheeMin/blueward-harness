# #858 웹 콘솔 진행 중 세션에 다음 갈래 표시 (0.10.270)

## 배경

#819(PR #851) 시안 대조에서 남긴 것. 시안 G-09(SRS 를 쓰고 올릴 차례인 세션)는 순서 알약 끝에 "→ 개발 Spec" 처럼 다음 갈래를 보이는데(시안 알약 4개), 콘솔은 갈래가 끝난 뒤에만 다음 갈래(`nextFlow`)를 계산해 진행 중에는 그리지 못했다. 같은 이슈의 "G-09 미리보기 표 ID 줄바꿈" 은 #904(PR #912)에서 고쳤다.

## 바꾼 것

- `console/server.py` `advance_flow`: 갈래가 진행 중이면 `flows.compute_next` 로 다음 갈래를 미리 계산해 `flowState.upcoming` 에 둔다(`UPCOMING_REFRESH` 30초에 한 번만, 판정마다 SRS 를 읽지 않게).
- `console/flows.py` `public_fields`: `upcomingFlow`(끝나면 `null`).
- `console/static/app.js` `paintStages`: 순서 알약이 보이는 때 끝난 갈래는 `nextFlow`, 진행 중은 `upcomingFlow` 로 `→ 다음: <갈래>` 알약. 고를 수 있는 갈래가 없거나 `unknown` 이면 알약을 만들지 않는다.
- 시험: `test_in_progress_srs_flow_previews_next_flow_from_srs`(SRS 없음 → unknown, 30초 안 다시 안 읽음, 읽으면 개발 → 개발 Spec·REQ 번호, nextFlow 는 그대로 null), `test_in_progress_session_step_bar_ends_with_upcoming_next_flow`(알약·unknown·옛 서버).
- 길잡이 웹 콘솔 '갈래와 순서 막대', `docs/design/web-console.md`, whats_new 0.10.270(0.10.268 은 #914, 0.10.269 는 #915 가 잡음).

## 결정

- 모를 때 "확인 못 함" 알약을 따로 만들지 않고 아무것도 안 그린다. 끝난 갈래의 기존 알약도 같은 규칙이고, 미리보기라 없어도 일에는 지장이 없다. 지어내지는 않는다.

## 확인

- 시안 자동 검사 G-09·G-12 통과, G-09 그림에서 알약 "→ 다음: 개발 Spec" 확인.
