# #625 AI 리뷰 묶음 호출 실패 때 Claude 오류 원문을 남겼다 (2026-11-03)

배경. blueward-26/public-cloud#469 의 `ai-review / review` 가 "검사 불능: 성공한
묶음이 없다: 종료코드 1" 로 실패했다(run 41589501544). Claude 호출이 약 2초 만에
끝나는데 오류 원문이 로그에 없었다. 10-31 성공 run 과 Claude Code 판(2.1.310)·인자·
엔진 코드가 같고, 토큰을 새로 넣은 뒤에도 같은 결과라 원인을 가를 증거가 없었다.
`run_batch` 가 종료코드≠0 이면 stderr 마지막 한 줄만 사유로 쓰고 stdout JSON 의
`is_error`·`subtype`·`result` 를 버렸기 때문이다. 인증·한도 오류는 보통 stdout 에 담긴다.

결정.
- 종료코드≠0 사유(`checker/ai_review.py` 의 `failure_detail`): stdout 이 JSON 객체면
  `is_error`·`subtype`·`result`(앞 300자), 아니면 stdout 앞 300자, stderr 는 앞 3줄·뒤
  3줄(각 200자). 비어 있는 것은 빼고 ` | ` 로 이어 한 줄로 만든다. 전체 1,500자 상한.
  아무것도 없으면 종전처럼 `종료코드 N` 만.
- 종료코드 0 인데 `is_error` 거나 subtype 이 success 가 아닌 경우도 `result` 앞부분을
  덧붙인다(`claude 가 오류로 끝남(subtype): result=...`).
- 담기 전에 `redact` 로 가린다: env 의 토큰 실제 값, `load_secret_patterns()`(risk_gate
  패턴 + 추가분), `Bearer ...`, `sk-...`, 32자 이상 hex, 긴 base64 모양. 값은 `***`.
- PR 코멘트: 워크플로 결과 정리 단계가 사유를 `clean(reason, 500)` 으로 자르던 것을
  1,500 으로 늘렸다(`clean` 이 공백·줄바꿈을 한 줄로 합친다). Actions 로그에는 엔진이
  `검사 불능: <사유>` 를 stderr 로 그대로 낸다.

시험. `checker/tests/test_ai_review.py` 에 인증 오류 JSON, JSON 아닌 stdout,
stderr 만, 비밀값 섞임(가려짐), 아무것도 없음, 종료코드 0 + is_error 를 더했고 옛
사유 형식 시험을 `stderr=` 접두에 맞췄다.

한계. 가리기는 모양 기반이라 모양이 다른 비밀값은 못 가린다. 원인 자체는 배포 뒤
public-cloud#469 재실행에서 원문이 보여야 안다.
