# #412 몇 초짜리 PR 검사들을 job 하나로 합치는 설계 (2026-10-21)

## 배경

public-cloud 의 Actions 는 월 환산 약 4,600분을 쓰고 무료는 2,000분이다. 비용은 job 개수다 — 평균 13~46초짜리 job 도 1분씩 깎인다. 10-14~10-21 run 1,000건(`runs.tsv`) 기준:

| 이벤트 1번 | 지금 | 내용 |
|---|---|---|
| PR 푸시 | run 7개 | ai-review·doc-guard·risk-gate·ssot-approval·gitleaks·ops-guard·pr-tamper-alert |
| 승인 | job 3~4개 | risk-gate check + rerun-stale, ssot-approval, pr-queue |
| main 병합 | run 5개 | doc-guard·gitleaks·risk-gate after-merge·ssot-approval after-merge·ledger-complete |

푸시 한 번 만들기(#410, −31%)와 트리거 손질(#411, −12%)을 해도 월 약 2,600분이라 넘는다. 이벤트 1번당 job 수를 줄여야 하고, 그 방법이 몇 초짜리 검사들을 한 job 의 단계로 합치는 것이다. 이 기록은 설계이고 구현은 하위 이슈로 나눈다.

## 결정

| # | 결정 | 내용 |
|---|---|---|
| 1 | 묶음 셋 + 따로 둘 | 아래 표 |
| 2 | check 이름은 commit status 로 살린다 | 아래 "2. check 이름" |
| 3 | 원칙 7 | 모든 검사 단계는 `continue-on-error: true` 이고 `outputs.status` 를 `pass`·`fail`·`unknown` 으로 낸다. 마지막 "종합" 단계가 하나라도 `fail`·`unknown` 이면 job 을 실패시키되 어느 단계가 왜인지 `::error title=` 로 나눠 적는다. 앞 단계가 불능이어도 뒤 단계를 건너뛰지 않는다. 단 pr-queue 단계는 종합에서 뺀다(아래) |
| 4 | 엔진 변경은 최소 | 아래 "4. 엔진" |
| 5 | 호환 전략 | 옛 재사용 워크플로(doc-guard·gitleaks·ssot-approval·risk-gate·pr-queue·ledger-complete)는 한 판 동안 남기고 로직이 둘인 것을 감수한다. 머리 주석에 "pr-checks·pr-review·main-checks 로 대체됨, 다음 판에서 삭제". 이유: public-cloud 의 옛 caller 가 `@stable` 을 보므로 새 판이 stable 이 되는 순간 옛 파일이 없으면 그쪽 검사가 전부 검사 불능이 된다. scaffold 는 새 caller 를 내고 옛 caller 를 내지 않는다. public-cloud 는 PR 하나로 caller 를 갈아끼운다(옛 caller 삭제 + 새 caller 추가, `risk-gate.yaml` 그대로). 같은 PR 에서 옛·새가 함께 도는 순간은 없다. 교체 PR 이 병합된 뒤 옛 파일 삭제 이슈를 연다((d) 완료 조건) |
| 6 | Draft 건너뛰기 | 지금 안 켠다("안전판", 아래) |
| 7 | 트리거는 합집합, 단계는 `if` | 아래 "7. 트리거" |
| 8 | concurrency | PR 단위 cancel-in-progress(risk-gate 방식). pr-queue 의 저장소 전체 그룹은 버린다. 한계는 아래 |

### 1. 묶음

| 워크플로 | 트리거 | 한 job 의 단계 순서 |
|---|---|---|
| `pr-checks.yml` | `pull_request` | gitleaks → doc-guard → ssot-approval → risk-gate → pr-queue(코멘트·merge-order status). 엔진 checkout·uv 설치는 한 번 |
| `pr-review.yml` | `pull_request_review` | ssot-approval 재판정 → risk-gate 재판정 → rerun-stale(#221) → pr-queue |
| `main-checks.yml` | `push: main` | gitleaks → doc-guard(paths) → risk-gate after-merge → ssot-approval after-merge → pr-queue. 읽기 권한만 |
| 따로 둠: `ledger-complete.yml` | `push: main` | `contents: write` 를 gitleaks(외부 바이너리를 받는 단계)와 한 job 에 두지 않는다. 재시도 루프(`scripts/ledger_complete_loop.sh`)와 "concurrency 로 줄 세우지 않는다" 원칙은 그대로 |
| 따로 둠: `ai-review.yml` | | 토큰·실행 시간·비밀값 사전 판정이 다르고 risk-gate 가 그 check run 을 읽는다. `paths: ['src/**']` 도 그대로 |
| 따로 둠: `pr-tamper-alert.yml` | `pull_request_target`(+`pull_request_review` dismissed) | base 코드로 도는 보안 경계라 PR head 를 받는 job 과 섞지 않는다 |

저장소 자체 워크플로(public-cloud 의 ops-guard, notify-teams)는 범위 밖.

효과: PR 푸시 1번 run 7 → 3(ai-review·pr-checks·저장소 자체 ops-guard), 승인 1번 3~4 → 1, 병합 1번 5 → 2(main-checks·ledger-complete). pr-tamper-alert 는 synchronize 때만 +1 이다(dismissed 해제 때도 따로 1개 뜬다). 주 약 250분은 병합 5 → 1 로 계산한 수치라 병합 한 건당 1분씩 덜 줄어든다 — 구현 뒤 재계산한다.

### 2. check 이름

GitHub 에는 job `pr-checks / check` 하나가 뜨지만, 엔진과 훅이 읽는 이름은 **commit status 로 살린다**. pr-checks 의 각 단계가(또는 종합 단계가) `statuses: write` 로 그 sha 에 옛 이름 그대로 status 를 단다: `gitleaks`, `doc-guard`, `ssot-approval`, `risk-gate`. state 는 success / failure / error(error 가 검사 불능). pr-queue 가 `merge-order` status 를 다는 것과 같은 방식이고 job 이 아니라 과금이 없다. 각 단계는 지금처럼 자기 마커 코멘트(`<!-- risk-gate -->`, doc-guard, ssot-approval, pr-queue 마커)를 그대로 남기고, job 요약에 단계별 표(통과·위반·검사 불능)를 쓴다.

### 4. 엔진

- `risk_gate` 의 `checks` 기준·`EXCLUDED_CHECK_GROUPS`·`pr_queue.GATE_GROUPS`·`pr_approvals.py`·훅은 지금 이름(`gitleaks`·`doc-guard`·`ssot-approval`·`risk-gate`)을 그대로 읽는다. `GATE_GROUPS` 와 `pr_approvals.py` 는 바뀌지 않는다(확인만).
- 엔진 변경은 `EXCLUDED_CHECK_GROUPS` 에 job 자신 `pr-checks` 를 더하는 것(교착 방지)과 단계 status 를 다는 작은 스크립트(`scripts/` 또는 워크플로 안 `gh api`)뿐이다.
- `risk_gate check-pr --step-results` 인자는 만들지 않는다. risk-gate 단계는 앞 단계가 이미 단 status 를 API 로 읽는다 — 같은 job 안에서 순서가 보장되고, status 는 sha·context 별 최신값이라 재실행에도 맞다. pr-review 의 재판정도 같은 status 를 읽으므로 모순이 없다.
- 훅 `pre-bash-git-guard.sh`: `merge-order`·`pr-queue` 제외는 그대로. `pr-checks`(job)는 status 이름과 다르게 읽히니 제외하지 않는다 — 검사 실패로 센다.
- `ai_review` 기준·`AI_REVIEW_CHECK_NAME` 은 그대로.
- **pr-queue 단계는 종합에서 뺀다.** 지금도 `pr-queue / queue` 실패는 훅·risk_gate 가 세지 않는다. 단계는 `continue-on-error` 로 돌고 실패는 job 요약의 경고로만 남긴다. 순서 판정 불능은 지금처럼 `merge-order` status 의 error 로 드러나고 훅이 그것을 읽는다 — 원칙 7 은 그 status 가 지킨다.

### 7. 트리거

pr-checks 의 `pull_request.types` 는 `[opened, synchronize, reopened, ready_for_review, closed]`(#415 병합 뒤 기준 — `edited`·`converted_to_draft` 없음). gitleaks·doc-guard·ssot-approval·risk-gate 단계는 `closed` 가 아닐 때만, pr-queue 단계는 항상 돈다. `closed` 이벤트의 job 은 지금 pr-queue 1분과 같다. doc-guard·ssot-approval 의 paths 는 트리거가 아니라 단계 `if` 로 옮긴다(단계 건너뛰기는 과금이 없고, 한 job 이라 트리거 paths 를 못 쓴다). 바뀐 파일 목록은 job 첫머리에서 한 번 받아 단계들이 공유한다.

## 구현 순서

각각 한 번의 `/harness:start` 크기. 앞 이슈가 먼저 병합돼야 한다.

| 순서 | 이슈 | 내용 |
|---|---|---|
| (a) | [#417](https://github.com/jaeheeMin/blueward-harness/issues/417) | 엔진: `EXCLUDED_CHECK_GROUPS` 에 `pr-checks`, 단계 status 를 다는 스크립트, 시험. `pr_approvals.py`·`GATE_GROUPS` 는 확인만 |
| (b) | [#418](https://github.com/jaeheeMin/blueward-harness/issues/418) | `pr-checks.yml` + 시험(`test_*_workflow.py` 스타일). 먼저: #417 |
| (c) | [#419](https://github.com/jaeheeMin/blueward-harness/issues/419) | `pr-review.yml`·`main-checks.yml`(ledger-complete 는 따로) + 시험. 먼저: #417, #418 |
| (d) | [#420](https://github.com/jaeheeMin/blueward-harness/issues/420) | scaffold caller 교체, 옛 워크플로 머리 주석, governance.md·길잡이·README, plugin.json version, 삭제 이슈 열기. 먼저: #417~#419. public-cloud caller 교체는 그쪽 저장소 PR 로(여기엔 길잡이 갱신 이슈로만) |

## 알려진 한계·열어 둔 것

- **Draft 건너뛰기 안전판**: caller 의 `if: github.event.pull_request.draft == false` 는 skipped 라 과금이 없지만 Draft 동안 피드백이 없다. 지금은 켜지 않는다. 11월 15일 사용량이 1,000분을 넘으면 켠다(그때 `/harness:deliver` 가 Draft 로 열고 끝에 ready 로 바꾸는 흐름을 같이 만든다). 효과 10~25% 는 Draft 비율을 몰라 추정이다.
- **저장소 자체 검사는 범위 밖**: public-cloud 의 ops-guard·notify-teams 는 이 합치기에 들지 않는다. PR 푸시 1번에 ops-guard 1개가 남는다.
- **실측은 11월**: 절감 추정은 run 1,000건 위의 것이다. 구현 뒤 실제 사용량으로 확인한다.
- **pr-queue 의 줄 세우기를 잃는다**: pr-queue 의 저장소 전체 concurrency 그룹을 버리고 PR 단위로 바꾸므로 다른 PR 의 실행이 동시에 다른 PR 의 순서 코멘트를 쓸 수 있다. 둘 다 열린 PR 전체 상태를 다시 계산하니 마지막 쓰기가 같은 결과이고, 다음 이벤트가 바로잡는다. 그 사이 코멘트가 잠깐 낡을 수 있다.
- **옛 파일과 로직이 둘**: 재사용 워크플로는 job 단위로만 부를 수 있어 옛 파일의 단계를 가져다 쓸 수 없다. 새 파일에 옮겨 적고, 옛 파일은 한 판 동안 남는다. 공통 부분을 `scripts/` 로 빼는 것을 검토.
- **status 쓰기 권한**: pr-checks caller 는 `statuses: write` 가 필요하다(지금 risk-gate caller 는 read).
- 트리거는 #411(PR #415)이 바꾸는 중이라 #415 병합 뒤 기준으로 구현한다.
