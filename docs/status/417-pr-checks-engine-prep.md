# #417 pr-checks job 제외와 단계 commit status 달기 엔진 준비 (2026-10-21)

## 배경

#412 설계의 (a). 검사를 한 job(`pr-checks / check`)으로 합치면 엔진과 훅이 읽는 옛 이름(`gitleaks`·`doc-guard`·`ssot-approval`·`risk-gate`)이 사라지므로, 단계가 그 이름으로 commit status 를 단다. 이 이슈는 그 엔진 쪽 준비다. 워크플로(#418)는 아직 없다.

## 결정

1. `risk_gate.EXCLUDED_CHECK_GROUPS` 에 `pr-checks`, `pr-review`, `main-checks` 를 더했다. 모두 risk-gate 를 안에서 돌리는 합친 job 이라 `checks` 기준이 세면 자기가 끝나길 기다리는 교착이 된다. `pr-review`·`main-checks` 는 #419 의 워크플로 이름이다(이슈 범위는 `pr-checks` 뿐이었으나 같은 이유라 같이 넣었다). `--step-results` 인자는 만들지 않았다.
2. `scripts/step_status.py` 는 얇은 진입점이고 로직은 `checker/step_status.py` 에 있다(다른 `scripts/*.py` 와 같은 방식). `state_for(result)`(pass→success, fail→failure, unknown→error)와 `post_status(...)`를 나눴다. gh 실패·잘못된 result 는 종료코드 2 와 stderr 사유.
3. 읽기 확인(바꾸지 않음):
   - `pr_queue._norm_check` 는 `context` 가 있고 `name` 이 없는 항목(StatusContext)을 check run 모양으로 바꾼다. SUCCESS→success, PENDING/EXPECTED→진행 중, 그 밖(FAILURE·ERROR)→failure. error 도 실패로 센다. `GATE_GROUPS`(`risk-gate`, `ssot-approval`)는 그 이름으로 `fail` 인 것만 본다. `pr_approvals.py` 는 `GATE_GROUPS` 를 가져다 쓴다. 모두 바뀌지 않았다.
   - `risk_gate.fetch_check_runs` 는 commit status 를 `context`→`name` 으로 바꾸고 pending 만 진행 중, success 가 아니면 실패로 센다(error 포함).
   - 훅은 `gh pr checks --json name,...` 로 읽는다. gh 가 status 의 context 를 `name` 으로 내므로 옛 이름 status 는 지금처럼 읽힌다. 훅의 `jq` 필터는 `merge-order`·`pr-queue` 만 빼고 `pr-checks` 는 빼지 않는다(job 실패 = 검사 실패). 그 점을 훅 주석 한 줄로 남겼다. 훅 동작은 바뀌지 않았다.
4. 시험: `test_risk_gate.py` 에 합친 job 제외, 옛 이름 status(failure·error·pending)가 지금처럼 세어지는 시험. 새 `test_step_status.py`.

## 알려진 한계

- 훅이 `gh pr checks` 로 status 를 읽는 것은 코드를 읽어 확인했을 뿐, 실제 status 를 달아 본 시험은 없다. #418 의 워크플로가 생긴 뒤 실제 PR 에서 확인한다.
