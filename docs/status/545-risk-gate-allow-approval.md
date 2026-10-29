# #545 risk-gate: 예외 주석을 넣거나 바꾸면 승인 요구 (2026-10-29)

`write_auth` 는 PR head 소스로 CR-009 를 돌리므로, 같은 PR 에서 `harness:allow CR-009 <이유>` 를 넣으면 "쓰기 앱인데 권한 검사 없음" 사유가 사라져 승인 없이 통과(자동 병합)할 수 있었다. public-cloud #439(GRIV 권한 정리)를 처리하다 찾았다.

- 새 기준 `allow`(`checker/risk_gate.py` `_crit_allow`): 바뀐 `.abap` 파일의 diff 추가 줄에 `harness:allow CR-0NN` 이 있으면 "코드 예외 주석(harness:allow CR-0NN)을 넣거나 바꿈" 사유로 승인을 요구한다. 규칙 번호와 상관없이 본다.
- base 와 head 비교는 diff 추가 줄로 한다 — base 와 같은 주석은 사유가 아니고, 이유만 바꾼 주석·옮긴 주석·새 파일의 주석은 사유다. 지운 주석은 검사가 다시 걸리므로 사유가 아니다.
- diff 가 너무 커 patch 가 없으면 "확인하지 못함" 사유(원칙 7). 설정 키는 없다(게이트가 켜져 있으면 항상 본다).
- 하지 않은 것: METHOD 안 첫 줄 주석을 예외로 인정하도록 넓히지 않았다. #524 PRIVILEGED 경고는 그대로.
- 시험: `checker/tests/test_risk_gate.py` 에 7건 추가. Plugin version 0.10.139.
