# #452 옛 재사용 검사 워크플로 5개 삭제 (2026-10-25)

`.github/workflows/` 의 `doc-guard.yml`·`gitleaks.yml`·`ssot-approval.yml`·`risk-gate.yml`·`pr-queue.yml` 을 지웠다. 기능은 이미 `pr-checks.yml`(PR)·`pr-review.yml`(승인)·`main-checks.yml`(main push)의 단계로 합쳐져 있다(#412·#417~#420). #428 의 마지막 항목이다. Plugin version 0.10.114.

**호출하는 곳 확인.** public-cloud 는 새 caller 셋으로 교체를 마쳤다. `jaeheeMin/client-docs` 는 옛 `doc-guard.yml` 을 아직 부르지만 쓰지 않는 저장소라 깨져도 된다고 사용자가 정했다(이 PR 이후 그 저장소의 Actions 는 실패한다. 고치지 않는다). 이 저장소 안에서는 `pr-queue-self.yml` 만 옛 파일(`pr-queue.yml`)을 불렀다.

**pr-queue-self.yml.** `uses: ./.github/workflows/pr-queue.yml` 호출을 없애고 그 job 을 직접 적었다. job id `pr-queue`, 이름 `pr-queue / queue` 를 유지해 check 이름과 `merge-order` status 가 그대로 나온다(`risk_gate`·`pr_queue` 가 이름으로 순서 표시 check 를 알아본다). concurrency·권한·엔진 ref(`stable`)도 그대로다.

**시험 정리.**

| 시험 | 처리 |
|---|---|
| `test_pr_queue_workflow` | `pr-queue-self.yml` 기준으로 다시 썼다(이벤트, check 이름, concurrency·권한, 엔진 ref, 옛 파일 없음). |
| `test_doc_guard_main_failure_issue` | 이슈 알림 장치 시험을 `main-checks.yml` 의 `doc-guard-issue` 단계 기준으로 옮겼다(조건은 doc-guard 미통과 + main). |
| `test_gitleaks_scan` | 바이너리 버전·해시 고정 시험을 `pr-checks`·`main-checks` 의 gitleaks 단계 기준으로 옮기고 두 곳의 값이 같은지 시험을 더했다. |
| `test_alert_issue_single_create` | risk-gate 알림 시험 대상을 `main-checks.yml` 의 `risk-gate-issue` 단계 run 으로 바꿨다. |
| `test_version_overlap` | 열린 PR 판 번호 읽기 → 검사 → 종료코드 2 원인 구분 시험을 `pr-checks.yml` 의 doc-guard 단계 기준으로 옮겼다. |
| `test_engine_pin`·`test_plugin_version` | 예로 쓰던 파일명을 `pr-checks.yml` 로 바꿨다. |
| `test_trigger_paths` | 옛 파일의 concurrency 시험 둘을 지웠다. PR 단위 취소는 `test_pr_checks_workflow`·`test_pr_review_workflow`, push 는 취소하지 않음은 `test_main_checks_workflow` 가 이미 본다. |
| `test_ssot_approval` | 옛 `after-merge` job 권한 시험을 지웠다. main-checks 의 caller 권한(issues write 포함)은 `test_main_checks_workflow` 가 본다. |

**문서.** CLAUDE.md, README.md, checker/README.md, scaffold skeleton CLAUDE.md, docs/sap-plugin-survey.md, plugins/harness/README.md, 엔진·scripts docstring, gitleaks 설정 주석, `release-tag.yml` 의 paths(지운 5개 제거)를 새 구성에 맞게 고쳤다. 길잡이(`docs/guide/harness-guide.html`)에는 옛 파일명 언급이 없어 고치지 않았다. 과거 기록(`docs/status/`)과 새 워크플로 안의 "옛 ○○.yml" 이력 주석은 그대로 뒀다.

**미결.** client-docs 의 옛 caller 정리는 하지 않는다(사용자 결정). 병합 뒤 `release-tag` 가 `v0.10.114` 와 `stable` 을 붙이는지 확인한다.
