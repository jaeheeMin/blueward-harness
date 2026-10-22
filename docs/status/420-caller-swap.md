# #420 scaffold caller 교체와 옛 검사 워크플로 대체 표시 (2026-10-21)

## 배경

#412 설계의 (d), 구현 4개 중 마지막. 새 재사용 워크플로(#418 `pr-checks.yml`, #419 `pr-review.yml`·`main-checks.yml`)를 부르는 쪽을 새로 내고, 옛 재사용 워크플로 5개에는 "대체됨" 표시만 한다. 옛 파일은 지우지 않는다. public-cloud 의 옛 caller 가 `@stable` 로 부르므로, 새 판이 stable 이 되는 순간 파일이 없으면 그쪽 검사가 전부 검사 불능이 된다. 그래서 로직이 둘인 것을 한 판 동안 감수하고, 교체 뒤 삭제는 후속 이슈에서 한다.

## 바꾼 것

| 구분 | 내용 |
|---|---|
| 옛 재사용 워크플로 5개 | `doc-guard`·`gitleaks`·`ssot-approval`·`risk-gate`·`pr-queue` 머리에 "대체됨(#412·#420), 한 판만 남기고 다음 판에서 지움" 3줄. 기존 주석은 그대로. `ledger-complete.yml` 은 대체되지 않아 그대로 |
| scaffold caller | 옛 caller 5개 삭제, 새 caller 3개(`pr-checks.yml`·`pr-review.yml`·`main-checks.yml`) 추가. `ai-review`·`pr-tamper-alert`·`ledger-complete` caller 는 그대로 |
| 시험 | `test_scaffold.py`(파일 목록, 옛 caller 가 없음, 새 caller 셋 구조), `test_trigger_paths.py`·`test_pr_checks_workflow.py`·`test_main_checks_workflow.py`(paths 비교 대상을 caller 에서 `pr-checks.yml` 의 `DOC_GUARD_PATHS` 로), `test_pr_queue_workflow.py`(없어진 caller 시험 삭제) |
| 문서 | `rules/governance.md`, `plugins/harness/README.md`, `skills/scaffold/SKILL.md`, `docs/guide/harness-guide.html`(검사 탭에 "검사는 한 덩어리" 안내, 조회·scaffold 파일 목록) |
| 버전 | plugin.json `0.10.105` → `0.10.106` |

## 새 caller 셋

| 파일 | name = job id | 트리거 | permissions |
|---|---|---|---|
| `pr-checks.yml` | `pr-checks` | `pull_request` types `[opened, synchronize, reopened, ready_for_review, closed]` | contents read, pull-requests write, issues write, statuses write, checks read, actions read |
| `pr-review.yml` | `pr-review` | `pull_request_review` types `[submitted, dismissed]` | 위와 같고 actions write |
| `main-checks.yml` | `main-checks` | `push` branches `[main]` | contents read, pull-requests read, issues write, statuses write, checks read |

모두 `uses: jaeheeMin/blueward-harness/.github/workflows/<파일>@stable` 이고 `secrets: TEAMS_PLUGIN_ALERT_WEBHOOK` 을 넘긴다. 머리 주석의 caller 예시가 정본이며 그대로 옮겼다. workflow `name:` 이 중요한 이유: pr-review 의 rerun 단계가 `.name == "pr-checks"` 로 run 을 찾고, 엔진의 `EXCLUDED_CHECK_GROUPS` 가 이 이름들을 본다. 옛 doc-guard caller 의 paths 목록은 단계 `if`(`DOC_GUARD_PATHS`)가 맡으므로 caller 에 없고, caller 머리 주석에 그 사실을 적었다.

## 판단

1. **paths 비교 시험**: scaffold doc-guard caller 가 없어져 `pr-checks.yml` 의 `DOC_GUARD_PATHS` 가 유일한 정의가 됐다. "caller 와 같다" 는 시험을 "`pr-checks` 와 `main-checks` 의 `DOC_GUARD_PATHS` 가 같다" 로 바꿨다. 엔진이 보는 파일을 덮는지(`test_trigger_paths`)도 이 정의를 본다.
2. **pr-queue 재사용 워크플로 시험**: caller 구조 시험은 새 caller 시험(`test_scaffold.py`)으로 옮겼다.
3. **`test_engine_pin` 의 caller `@stable` 시험**: skeleton 을 glob 으로 훑으므로 새 caller 3개를 자동으로 본다.

## 후속

- #428: public-cloud caller 교체(옛 5개 삭제 + 새 3개 추가, 한 PR) 뒤 확인, 길잡이 아티팩트 갱신, 옛 재사용 워크플로 5개 삭제 이슈 열기. 이 이슈에서는 삭제 이슈를 만들지 않는다(교체 병합 뒤).

## 알려진 한계

- 실제 PR·push·승인으로 돌려 보지 않았다. 구조 시험과 YAML 문법만 확인했다. #419 에 적은 첫 실행 확인 사항(rerun 의 run 이름 찾기, main 커밋 status, compare API 한도)이 그대로 남아 있고, #428 에서 확인한다.
- 길잡이 아티팩트는 병합 뒤에 다시 올린다(`docs/guide/README.md`). 이 PR 에서는 올리지 않았다.
- `docs/status.md` 는 건드리지 않았다.
