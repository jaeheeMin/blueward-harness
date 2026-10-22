# #418 PR 검사들을 job 하나로 합친 pr-checks 재사용 워크플로 (2026-10-21)

## 배경

#412 설계의 (b). gitleaks·doc-guard·ssot-approval·risk-gate·pr-queue 를 `.github/workflows/pr-checks.yml` 한 job(`check`)의 단계로 옮겼다. 엔진 checkout·uv 설치도 한 번이다. 옛 워크플로 파일은 그대로 두었다(머리 주석·삭제는 #420). 단계 status 를 다는 스크립트는 #417 의 `scripts/step_status.py` 를 쓴다.

## 단계 구성

| 순서 | 단계(id) | if | status context |
|---|---|---|---|
| 0 | 저장소 → 엔진 checkout → setup-uv | 저장소는 `closed` 가 아닐 때 | |
| 0 | 바뀐 파일 목록 받기(`changed`) | `closed` 가 아닐 때 | |
| 1 | gitleaks 검사(`gitleaks`) → status → 리포트 올리기 | `closed` 가 아닐 때 | `gitleaks` |
| 2 | doc-guard 검사(`doc-guard`) → status → PR 에 남기기 | `closed` 가 아니고 `has_doc_guard != 'false'` | `doc-guard` |
| 3 | ssot-approval 판정(`ssot-approval`) → status → PR 코멘트 갱신 | `closed` 가 아니고 `has_ssot != 'false'` | `ssot-approval` |
| 4 | risk-gate 판정(`risk-gate`) → status → 요약과 PR 코멘트 갱신 | `closed` 가 아닐 때 | `risk-gate` |
| 5 | pr-queue(`pr-queue`) | `!cancelled()`(`closed` 포함) | `merge-order`(엔진이 단다) |
| 6 | 종합 | `always()` | |

검사 단계 넷은 `continue-on-error: true`, 끝에 `status=pass|fail|unknown` 과 사유 한 줄(`reason`)을 낸다. 종료코드 매핑은 원본 "판정" 단계 그대로다(0 통과, 1 위반, 그 밖 검사 불능. gitleaks 는 `result=clean|leak|else`).

## 원본에서 달라진 점·판단

1. **checkout 순서와 ref**: 저장소를 먼저, 엔진을 나중에 받는다(checkout 이 작업 폴더의 추적 안 되는 파일을 지운다). 저장소는 기본 ref(합성 커밋)에 `fetch-depth: 0` 이다. 옛 gitleaks 는 head sha 를 받았으나 `gitleaks_scan.sh` 는 `BASE_SHA`·`HEAD_SHA` 를 직접 받아 `git log` 범위를 훑으므로 작업 폴더가 어느 쪽이든 결과가 같고, doc-guard 의 `origin/<base> HEAD` diff 는 합성 커밋 기준이어야 PR 이 더한 것만 나온다. 엔진 경로는 `.harness-engine` 로 통일했다(옛 doc-guard 는 `.doc-guard-engine`).
2. **바뀐 파일 목록**: `gh api repos/<repo>/pulls/<n>/files --paginate`(이름이 바뀐 파일은 옛 경로도 센다). 못 받거나 3000개 이상이면(API 한도) `has_*` 를 `unknown` 으로 두고, `!= 'false'` 라 단계를 건너뛰지 않는다. paths glob 은 단계 안 python 이 평가한다(`**/` 는 0개 이상 디렉터리, `*` 는 `/` 를 넘지 않음). `DOC_GUARD_PATHS` 가 scaffold doc-guard caller 의 paths 와 같음을 시험이 비교한다. 이 값은 caller paths 가 바뀌면 같이 고쳐야 한다.
3. **doc-guard 단계 묶음**: 옛 "바뀐 문서 찾기"·"열린 PR 의 판 번호 읽기"·"검사"·"결과 정리"·"판정" 을 한 단계로 묶었다(바뀐 문서 목록은 옛처럼 git diff 이고 위 API 목록과는 별개다). 바뀐 문서가 없으면 옛처럼 아무것도 안 하고 통과다. 옛 "판정" 단계의 `harness 판정` 요약 절은 쓰지 않고, 그 사유(위반, 열린 PR 읽기 실패의 다시 돌리기 안내, 규칙·설정 문제)를 `reason` 으로 옮겨 종합의 표와 `::error` 에 쓴다. PR 코멘트·`comment` 입력은 그대로다. 코멘트 단계가 실패해도 판정은 바뀌지 않는다(`continue-on-error`, 종합이 경고). 옛 파일에서는 코멘트 실패가 job 실패였다.
4. **gitleaks**: 바이너리 받기와 검사를 한 단계로 묶고(받기 실패 = 검사 불능), 스크립트의 `result=` 출력은 임시 `GITHUB_OUTPUT` 파일로 받아 읽는다. 스크립트는 바꾸지 않았다. 옛 job 의 `permissions: contents: read` 는 job 에 적지 않고 caller 권한(`contents: read`)에 합쳤다. 버전·sha256 은 `gitleaks.yml` 과 같은 값을 복사했으므로 올릴 때 둘 다 고친다.
5. **ssot-approval**: `pull_request` 경로만 옮겼다. `pull_request_review` 전용인 "옛 실패 실행 다시 돌리기"는 #419 의 pr-review 에 간다. after-merge 도 #419(main-checks)다.
6. **risk-gate**: `check-pr --wait-checks` 그대로다. 앞 단계 status 가 이미 달려 있어 기다릴 것은 job 밖 검사(ai-review 등)뿐이다. job 자신은 `EXCLUDED_CHECK_GROUPS` 의 `pr-checks` 로 빠진다(#417). 옛 `rerun-stale` 은 #419.
7. **결과 파일 이름**: 한 job 에서 같은 이름이 겹치지 않게 `ssot-result.json`·`risk-result.json` 등으로 나눴다.
8. **pr-queue**: 단계 내용은 그대로이고 실패 때 `::error` 대신 `::warning` 을 낸다(종합에서 뺀다). 옛 job 의 `if` 이벤트 조건은 caller 가 `pull_request` 뿐이라 뺐다. 저장소 전체 concurrency 는 PR 단위로 바뀌었고 한계는 워크플로 머리 주석에 적었다.
9. **종합**: 대상이 아닌 단계(`closed`, paths 에 안 걸림)만 "건너뜀" 이다. 대상인데 `status` 가 비어 있으면(앞 단계가 죽음) 검사 불능이다(원칙 7). status 달기·코멘트·pr-queue 실패는 `::warning` 으로만 남기고 종료코드에 넣지 않는다.
10. **caller 권한**: `contents: read`, `pull-requests: write`, `issues: write`, `statuses: write`, `checks: read`, `actions: read`. `actions: read` 는 pr-queue 의 옛 caller 권한을 그대로 가져왔다. rerun 용 `actions: write` 는 pr-review(#419) 몫이라 뺐다.

## 알려진 한계

- 실제 PR 에서 돌려 보지 않았다. 구조 시험과 YAML 문법, 바뀐 파일 목록 glob 의 로컬 확인뿐이다. caller 를 이 파일로 바꾸는 것은 #420 이고, 그때 첫 실행에서 status 가 `gh pr checks` 에 옛 이름으로 읽히는지 확인한다(#417 의 한계와 같은 확인).
- 한 단계의 `::error` 가 gitleaks 스크립트 자체의 `::error`(유출 발견·검사 불능)와 중복으로 뜬다.
