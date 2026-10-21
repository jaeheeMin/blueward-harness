# #401 merge-order 앞 PR 대기를 실패 대신 노란 대기로 (2026-10-21)

#370 의 커밋 status `merge-order` 는 앞 PR 이 열려 있으면 `failure` 라, GitHub 이 빨간 X 와 "Some checks were not successful" 로 보여 PR 에 오류가 있는 것처럼 읽혔다. 앞 PR 대기는 결함이 아니라 순서 정보라 `pending`(노란 대기)으로 바꿨다. 0.10.98.

## 한 것

- `checker/pr_queue_actions.py` `decide_status`: 앞 PR 이 열려 있으면 `pending`, 설명 `#n 병합 대기 (제목)`. 순서 판정 불능(순환, 읽기 실패, PR 한도, version 못 읽음)은 `error` 그대로.
- `checker/pr_queue.py` `classify`: GitHub 는 non-required status 가 pending 이어도 `mergeStateStatus` 를 UNSTABLE 로 보므로, UNSTABLE→CLEAN 보정을 merge-order 가 `fail` 일 때뿐 아니라 `pending` 일 때도 적용. merge-order 는 이미 `checks` 에서 빠져 "검사 진행 중" 목록에 들어가지 않는다.
- risk-gate: `EXCLUDED_CHECK_GROUPS` 가 merge-order 를 이미 빼므로 코드 변경 없음(진행 중 merge-order 가 사유가 안 되는 시험 추가). 주석만 고침.
- 병합 훅 `pre-bash-git-guard.sh` 의 검사 필터는 이름이 `merge-order` 인 것을 상태와 무관하게 빼므로 변경 없음.
- 시험: `test_pr_queue_actions.py`(pending, 판정 불능 error 시험은 그대로), `test_pr_queue.py`(pending + UNSTABLE → 병합 가능), `test_risk_gate.py`(진행 중 merge-order 는 사유 아님).
- 문구: README·governance 규칙·scaffold SKILL.md 와 pr-queue 워크플로 주석·길잡이 "빨간불" → 노란 대기(순서 판정 불능만 빨간불).

## 한계

- #398(pr_approvals)이 merge-order 를 다루는지는 이 브랜치에 없어 확인하지 못했다.
- 새 판이 병합돼 태그가 붙기 전에는 호출 쪽 저장소가 이전 엔진으로 `failure` 를 단다.
