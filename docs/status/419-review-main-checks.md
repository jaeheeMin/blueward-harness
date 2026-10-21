# #419 승인 재판정·병합 후 검사를 각각 job 하나로 합친 pr-review·main-checks 워크플로 (2026-10-21)

## 배경

#412 설계의 (c). 승인 1번에 job 이 3~4개(risk-gate check + rerun-stale, ssot-approval, pr-queue), main 병합 1번에 run 이 5개 뜨던 것을 `.github/workflows/pr-review.yml`(`pull_request_review`)과 `.github/workflows/main-checks.yml`(`push: main`) 각 한 job(`check`)으로 합쳤다. 병합 1번은 5 → 2(`main-checks` + `ledger-complete`)다. 옛 워크플로 파일과 `ledger-complete.yml` 은 그대로 두었다(교체는 #420). 단계 규칙은 #418 `pr-checks.yml` 과 같다(`continue-on-error`, `outputs.status`, 단계 직후 `scripts/step_status.py` 로 옛 이름 commit status, 종합 `always()` 표와 단계별 `::error`, pr-queue 는 `continue-on-error` 이고 종합에서 뺌, 옛 코멘트 마커 그대로).

## pr-review 단계 구성

| 순서 | 단계(id) | if | status context |
|---|---|---|---|
| 0 | 엔진 checkout → setup-uv (저장소는 받지 않는다) | | |
| 0 | 바뀐 파일 목록 받기(`changed`, `has_ssot`) | | |
| 1 | ssot-approval 판정(`ssot-approval`) → status → PR 코멘트 갱신 | `has_ssot != 'false'` | `ssot-approval` |
| 2 | risk-gate 판정(`risk-gate`, `check-pr --wait-checks`) → status → 요약과 PR 코멘트 | 항상 | `risk-gate` |
| 3 | 옛 pr-checks 실패 실행 다시 돌리기(`rerun-stale`) | risk-gate pass 이고 (ssot-approval pass 이거나 `has_ssot == 'false'`) | |
| 4 | pr-queue(`pr-queue`) | `!cancelled()` | `merge-order`(엔진) |
| 5 | 종합 | `always()` | |

concurrency 는 `pr-review-<PR번호>` cancel-in-progress. caller 권한: contents read, pull-requests write, issues write, statuses write, checks read, actions write.

## rerun-stale 이 통합 job 에서 동작하는 근거

옛 `rerun-stale` 은 같은 부르는 쪽 워크플로 파일의 같은 PR head `pull_request` 실행 중 실패·취소를 다시 돌렸다. 이제는 **같은 PR head 에서 이름이 `pr-checks` 인 workflow 의 run** 을 다시 돌린다(`actions/runs?head_sha=…&event=pull_request` 에서 `.name == "pr-checks"` 와 conclusion 으로 고른다. `rerun-failed-jobs`/`rerun` 은 원본 그대로). 부르는 쪽 workflow 의 `name:` 이 `pr-checks` 여야 한다(#420 의 caller 가 지킨다).

1. 다시 도는 실행은 `pull_request` 이벤트라 `pull_request_review` 로 도는 이 워크플로를 다시 타지 않는다. 반복이 없다. 판정은 리뷰를 API 로 실시간 읽으므로 다시 돌려도 승인이 인정된다.
2. 이 job 의 concurrency 그룹(`pr-review-<n>`)이 pr-checks 의 그룹(`pr-checks-<n>`)과 달라, check 가 도는 중에 pr-checks 를 다시 돌려도 지금 실행이 취소되지 않는다. 옛 `rerun-stale` 이 별도 job 이었던 이유(risk-gate 의 check 와 같은 그룹이라 도는 중에 다시 돌리면 자기가 취소됨)가 그룹이 달라져 사라졌다. 그래서 단계 하나로 충분하고, 두 판정이 모두 끝난 뒤에 도는 순서는 단계 순서가 지킨다.

"둘 다 성공" 은 옛 `needs.check.result == 'success'` 에 대응한다. docs/ssot 를 안 건드린 PR 은 ssot-approval 단계를 건너뛰는데, 옛 check job 은 그 PR 에서 통과였으므로 성공으로 센다. 다시 돌리기가 실패해도 단계는 성공으로 끝나고(경고와 job 요약), `actions: write` 가 없으면 원본처럼 경고만 낸다.

## main-checks 단계 구성

| 순서 | 단계(id) | if | status context(`github.sha`) |
|---|---|---|---|
| 0 | 저장소(fetch-depth 0) → 엔진 checkout → setup-uv | | |
| 0 | 바뀐 파일 목록 받기(`changed`, `has_doc_guard`; `gh api compare before...sha`) | | |
| 1 | gitleaks 검사 → status → 리포트 올리기 (`before..sha` 범위) | 항상 | `gitleaks` |
| 2 | doc-guard 검사 → status → main push 실패를 이슈로 알리기(`doc-guard-issue`) | `has_doc_guard != 'false'` | `doc-guard` |
| 3 | risk-gate after-merge(`check-commit`) → status → 승인 없이 들어왔으면 이슈(`risk-gate-issue`) | 항상 | `risk-gate` |
| 4 | ssot-approval after-merge(`check-commit`) → status → 이슈(`ssot-approval-issue`) | 항상 | `ssot-approval` |
| 5 | pr-queue(`pr-queue`) | `!cancelled()` | `merge-order`(엔진) |
| 6 | 종합 | `always()` | |

concurrency 없음(병합 뒤 감시는 취소되면 안 된다). caller 권한: contents read, pull-requests read, issues write, statuses write, checks read. `contents: write` 는 없다. ledger-complete 를 따로 두는 이유는 머리 주석에 적었다(쓰기 토큰을 외부 바이너리를 받는 gitleaks 와 한 job 에 두지 않음).

## 원본에서 달라진 점·판단

1. **옛 "판정 불능이면 실패" 단계**(risk-gate/ssot-approval after-merge)는 종합이 대신한다. 종료코드 0/1/그 밖을 pass/fail/unknown 으로 내고 종합이 `::error` 와 job 실패로 드러낸다.
2. **이슈 단계**는 내용이 원본 그대로이나 `continue-on-error` 이다. 단계가 죽으면 뒤 검사가 건너뛰어지는 것을 막고, 종합이 `OUTCOME_ISSUE_*` 가 `failure` 이면 `::error` 와 job 실패로 센다(알림이 안 나간 채 지나가면 안 된다). doc-guard 이슈는 원본 `failure()` 조건 대신 `doc-guard` 가 pass 가 아닐 때(fail·unknown 모두 원본에서는 job 실패)로 옮겼다.
3. **doc-guard paths**: push 트리거의 `paths` 를 단계 `if` 로 옮겼다. `gh api compare` 의 파일은 300개까지라 그 이상이면, 또 `before` 가 없거나 비교에 실패하면 `unknown` 이라 건너뛰지 않는다. `DOC_GUARD_PATHS` 는 pr-checks 와 scaffold doc-guard caller 와 같음을 시험이 비교한다. gitleaks·risk-gate·ssot-approval 은 옛 push 경로처럼 paths 없이 항상 돈다.
4. **doc-guard 단계 묶음**: pr-checks 와 같이 한 단계다. push 에는 PR 코멘트와 열린 PR 읽기가 없다. 바뀐 문서는 원본처럼 `git diff --diff-filter=d $before HEAD` 이고, 실패하면 `ls-files` 로 대신한다.
5. **gitleaks**: pr-checks 와 같이 받기와 검사를 한 단계로 묶었다. 저장소는 기본 ref(push 한 sha)로 받는다.
6. **pr-review 의 저장소 checkout 없음**: 원본 ssot-approval/risk-gate review 경로도 저장소를 받지 않고 API 만 쓴다.
7. **status 대상**: pr-review 는 PR head sha, main-checks 는 `github.sha`(main 커밋)에 단다. main 커밋의 status 는 읽는 쪽이 없고 화면에서 사람이 보는 용도다.
8. **`release-tag.yml` paths**: 재사용 워크플로 목록을 시험(`test_engine_pin`)이 비교하는데 #418 의 `pr-checks.yml` 이 빠져 이미 어긋나 있었다. `pr-checks.yml`·`pr-review.yml`·`main-checks.yml` 을 더했다.
9. **risk_gate.py** 의 `EXCLUDED_CHECK_GROUPS` 는 #417 이 이미 `pr-review`·`main-checks` 를 담고 있어 고치지 않았다.

## 알려진 한계

- 실제 PR·push 에서 돌려 보지 않았다. 구조 시험과 YAML 문법뿐이다. 첫 실행에서 확인할 것: (1) rerun-stale 이 `.name == "pr-checks"` 로 실행을 찾는지(run 의 `name` 은 workflow 이름이고 `run-name` 을 쓰면 달라진다), (2) main 커밋에 단 status 가 읽히는지, (3) `compare` API 파일 수 한도 처리. caller 교체는 #420.
- `risk-gate check-commit` 이 main 커밋의 status 를 읽는지는 확인하지 않았다. 읽는다면 같은 job 이 방금 단 `gitleaks`·`doc-guard` status 와 섞일 수 있다.
