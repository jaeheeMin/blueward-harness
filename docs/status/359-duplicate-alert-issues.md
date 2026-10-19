# #359 알림 이슈가 커밋마다 두 개씩 열리는 문제 (2026-10-19)

## 원인

public-cloud(조직 `blueward-26` 소유)에서 risk-gate after-merge 단계가 `gh issue create ... --label type:fix --assignee "$OWNER" || gh issue create ...` 를 썼다. 조직은 담당자가 될 수 없어(`GraphQL: Only users and bots can be assigned.`) 첫 create 가 이슈를 만든 뒤 담당자 지정에서 실패하고, `||` 뒤의 두 번째 create 가 라벨 없는 이슈를 하나 더 만들었다. 같은 제목 검사는 create 앞에서 한 번만 돌아 막지 못했다. 확인한 run: 39185310645, 39185397998(커밋당 risk-gate run 은 하나). 열린 이슈 쌍은 #269/#270, #271/#272.

## 고친 것

같은 방식(`create` 에 `--assignee`, 실패 시 다시 create)을 쓰던 네 워크플로를 모두 고쳤다.

- `.github/workflows/risk-gate.yml`, `human-merge-alert.yml`, `pr-tamper-alert.yml`, `release-tag.yml`
- 이슈는 라벨·담당자 없이 **한 번만** create 한다. create 자체가 실패하면 `::error` 와 함께 step 을 실패시킨다(알림을 못 연 사실을 숨기지 않는다, 원칙 7).
- 만든 URL 에서 번호를 얻어 REST(`gh api -X POST repos/<repo>/issues/<번호>/labels|assignees`)로 라벨·담당자를 따로 붙인다(일부 gh 버전의 `gh issue edit` 이 GITHUB_TOKEN 에서 프로젝트 조회로 실패해서). 번호가 비면 `::error` 로 실패한다. 실패하면 `::warning` 만 남긴다. 담당자는 `gh api repos/<repo> --jq .owner.type` 이 `User` 일 때만 지정한다(pr-tamper-alert 는 PR 작성자라 소유자 유형을 보지 않고 시도한다).
- risk-gate 는 중복 검사를 제목 일치에서 "제목 일치 또는 본문 마커 `<!-- risk-gate:<full sha> -->`" 로 넓혔다. 본문 끝에 마커를 넣는다. 나머지 워크플로의 중복 검사(PR·제목 접두어로 열린 이슈를 찾아 코멘트)는 기존대로 둔다.
- 공용 스크립트로 묶지 않았다. 재사용 워크플로는 caller 저장소에서 돌고 `pr-tamper-alert`·`release-tag` 등은 checkout 이 없어 스크립트를 얻을 방법이 없다. 각 yml 에 인라인으로 둔다.
- `doc-guard.yml`, `ledger-complete.yml`, `ssot-approval.yml` 의 create 는 `--assignee` 도 재시도도 없어 이번엔 건드리지 않았다.
- Plugin version 0.10.83 → 0.10.84. 길잡이는 레일의 판·기준일 표기만 바꿨다(동작 설명이 바뀌는 탭이 없다).

## public-cloud

caller 가 `@stable` 이라 변경은 필요 없고, 병합 뒤 stable 이 옮겨지면 반영된다. 이미 열린 #270, #272 는 public-cloud 에서 수동으로 닫는다.

## 시험

`checker/tests/test_alert_issue_single_create.py` 신규(create 한 번·재시도 없음·create 에 `--assignee`/`--label` 없음·소유자 User 일 때만 담당자·create 실패는 `::error`·risk-gate 마커). `test_engine_pin.py` 의 release-tag 기대를 `--add-assignee` 로 고쳤다. 실제 GitHub 에서 조직 소유 저장소 동작은 병합 뒤 public-cloud 에서 확인해야 한다(여기서는 정적 검사뿐).
