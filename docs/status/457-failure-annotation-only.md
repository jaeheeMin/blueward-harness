# #457 팀원별 현황이 경고 등급 annotation 을 실패 사유로 잡는 문제

## 무엇이 문제였나

`--team`(#443)이 실패 사유로 check run 의 annotation 첫 메시지를 썼다. 그래서 GitHub 가 붙이는 경고 문구(`Node.js 20 is deprecated …`)가 "공통 원인" 으로 나왔다. 실패 등급 annotation 만 고르게 고친 뒤 실제 저장소에서 다시 돌려 보니, 이번엔 `Process completed with exit code 1.` 이 사유로 잡혔다. 같은 run 에 구체적인 실패 문구(`AI 리뷰가 큰 변경 일부만 봤다 …`)가 있었는데도 그랬다.

## 바꾼 것

- annotation 은 `annotationLevel` 이 `FAILURE` 인 것만 사유로 쓴다. 등급이 없으면 실패로 본다. `WARNING`·`NOTICE` 는 쓰지 않는다.
- 실패 annotation 이 여럿이면 흔한 문구(`is_generic_reason`: `exit code N` 포함이거나 20자 미만)보다 구체적인 문구를 먼저 쓴다.
- 쿼리를 `annotations(first:3){message}` 에서 `annotations(first:10){message annotationLevel}` 로 바꿨다.
- plugin 0.10.114.

## 확인

- `test_pr_team.py`·`test_pr_queue.py` 163 통과. 새 테스트는 경고만 있는 경우, 경고와 실패가 섞인 경우, 흔한 문구와 구체 문구가 섞인 경우다.
- public-cloud 에서 실제로 돌려 확인했다. 공통 원인이 "AI 리뷰가 큰 변경 일부만 봤다"(4 PR), "AI 리뷰를 돌리지 못했다"(5 PR)로 나왔다.
