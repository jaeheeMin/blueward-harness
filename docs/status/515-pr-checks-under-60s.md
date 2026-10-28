# #515 pr-checks 전체 검사 job 을 60초 아래로 (2026-10-28)

## 배경

public-cloud 의 `pr-checks / check` 전체 검사 job 50개(10-26 ~ 10-28) 중 49개가 60초를 넘어 2분으로 과금된다
(p50 76초, 평균 83초). PR 푸시마다 1분이 더 나간다. 단계별 평균은 아래와 같다.

| 단계 | 평균 | 원인 |
|---|---|---|
| doc-guard | 30초 | 규칙 파일을 읽을 때 `table_headers` 규칙마다 템플릿 xlsx 를 `openpyxl.load_workbook` 으로 다시 연다. 개발사양서 템플릿의 `styles.xml` 이 11.7MB(cellStyles 54,651)라 1회 약 6초이고, 규칙 3개면 3회. 문서가 md 뿐이어도 규칙 파일을 읽을 때 치른다 |
| pr-queue | 21초 | 열린 PR 마다 코멘트·status 를 `gh` 로 순차 조회(약 35회, 호출당 0.56초) |
| status 달기·코멘트 갱신 | 약 8초 | 검사마다 단계가 따로(status 는 `uv run` 으로 파이썬을 띄움, 코멘트는 github-script) |

시뮬레이션(A+B+C 적용 가정): 50개 중 43개가 60초 이하. 추정치이고 실제 효과는 배포 뒤 job 시간으로 확인한다.

## 바꾼 것

### A. xlsx 통합문서 재사용 (`checker/readers/xlsx.py`)

- `read_xlsx`·`read_row` 가 읽기 전용 통합문서를 (해석한 경로, mtime_ns, 크기) 단위로 한 프로세스에서 한 번만 연다.
  행 결과가 아니라 열린 통합문서를 들고 있는 이유: 규칙 셋이 시트·행이 달라도 같은 파일을 열기 때문에 행 단위 캐시로는
  적중하지 않는다. 6초는 `load_workbook` 이 styles 를 읽는 값이다.
- 한도 4개(오래된 것부터 닫음), 프로세스 종료 때 `atexit` 로 모두 닫는다. 같은 경로의 낡은 판(mtime·크기가 달라짐)은 버리고 새로 연다.
- 여는 데 실패한 예외는 캐시에 넣지 않는다(통합문서는 열기가 성공한 뒤에만 들어간다).
- `checker/tests/conftest.py` 에 시험마다 캐시를 닫는 autouse fixture 를 더했다(Windows 에서 임시 파일 핸들 때문에).
- 같은 파일을 여러 번 여는 다른 자리: 엔진이 검사 대상 xlsx 를 `read_xlsx`(시트 목록)와 `table_headers` 로 따로 읽던 것도
  같은 경로로 들어와 한 번만 열린다. `openpyxl` 을 실제로 불러 쓰는 곳은 이 파일뿐이다(나머지 xlsx 처리는 zip 직접).
  열어 둔 동안 Windows 에서는 그 파일을 같은 프로세스에서 바꾸거나 지울 수 없다. 지금은 검사 프로세스가
  끝나며 `atexit` 로 닫히고, 같은 프로세스에서 xlsx 를 덮어쓰는 흐름(export 등)은 이 리더를 쓰지 않는다.
  그런 흐름이 생기면 먼저 `clear_cache()` 를 부른다.

### B. pr-queue 읽기 병렬화 (`checker/pr_queue_actions.py`)

- 쓰기 대상 PR 마다 코멘트 조회와 head 커밋 status 조회를 `ThreadPoolExecutor(max_workers=6)` 로 먼저 모두 읽는다
  (`_prefetch`). 판정·쓰기·알림은 예전 그대로 PR 번호 순서로 하나씩 한다. 읽은 결과는 `Future.result()` 를 예전에 읽던
  자리에서 부르므로, 코멘트 읽기 실패는 같은 `GhError` 로 나와 그 PR 만 `read_errors`(종료코드 2) 로 모으고 다음 PR 로 넘어간다.
  status 읽기 실패는 예전처럼 무시하고 쓴다. 예상 못 한 예외는 `apply` 밖으로 나가 종료코드 2 로 이어진다.
- 쓰기를 병렬로 하지 않은 이유: 대부분의 실행에서 쓰기는 0~2건이라 얻을 것이 적고, GitHub 의 2차 속도 제한(secondary rate
  limit)은 동시 쓰기에서 걸리며, 알림 코멘트·Teams 전송 순서가 흔들린다.
- 속도 제한 재시도: `_read_with_retry` 가 HTTP 403·429 이면서 메시지에 `rate limit` 이 든 읽기 실패만 1·2·4초 간격으로
  최대 3번 다시 한다. 권한 부족 403 은 다시 하지 않는다.
- `pr_queue.compute` 쪽 읽기(`pr list`, plugin.json version 읽기)는 건드리지 않았다.

### C. 작은 단계 합치기 (`.github/workflows/pr-checks.yml`)

- status 단계 3개(gitleaks·doc-guard·ssot-approval)를 `early-status` 한 단계로 합쳤다. `uv run` 대신
  `PYTHONPATH=.harness-engine python3 .harness-engine/scripts/step_status.py` 로 같은 스크립트를 부른다(표준 라이브러리만 쓴다).
  context 이름·설명 기본값·`pass→success / fail→failure / unknown→error` 는 그대로다. 대상 아님(`outcome == skipped`)인 검사는 달지 않는다.
  하나가 실패해도 나머지를 달고, 못 단 이름을 `failed` 출력에 남기며, 단계는 실패(`continue-on-error`)로 끝난다.
- 코멘트 단계 4개 중 3개(doc-guard·ssot-approval·ledger-ready)를 `early-comments` 한 github-script 단계로 합쳤다. 마커·본문·
  삭제 조건·요약 쓰기(`core.summary`)는 그대로, 코멘트 목록은 한 번(`per_page: 100`)만 받는다(전에 doc-guard·ssot-approval 은 기본 30개였다).
  각 부분을 try/catch 로 감싸 하나가 실패해도 나머지를 계속하고, 실패한 이름을 `failed` 출력에 남긴다.
- 두 단계는 ledger-ready 판정 뒤, risk-gate 앞에 둔다(risk-gate 는 앞 status 를 API 로 읽는다).
- 종합 단계: 판정(`judge`)·`::error`·pr-queue 경고는 손대지 않았다. status·코멘트 실패 경고는 같은 제목으로, 이름별로 낸다.
  단계가 이름도 못 남기고 죽었으면 원인을 모르므로 그 단계의 세 이름을 모두 경고한다.
- risk-gate 는 status 단계와 코멘트 단계를 합치지 않았다(bash 와 github-script 로 언어가 달라 합치면 오히려 위험). status 단계만 `uv` 를 뺐다.
- 합치지 않은 것: risk-gate 코멘트(자기 판정 뒤에야 쓸 수 있다), pr-queue·병합 알림(조건이 다르다).
- `main-checks.yml`·`pr-review.yml` 의 같은 구조는 이번 범위가 아니다(단계 id 가 옛 그대로다).

배포되는 파일을 바꿨으므로 plugin.json 을 0.10.128 → 0.10.131 로 올렸다(0.10.129·0.10.130 은 다른 열린 PR 몫).

## 로컬 측정

public-cloud 로컬 체크아웃(`harness-fb`)에서 CI 와 같이 `scripts/check_changed.py 목록파일` 을 돌렸다(Windows, 이 PC 기준. 서버 값이 아니다).

| 바뀐 파일 | 전(0.10.128) | 후 | 리포트 |
|---|---|---|---|
| `docs/spec/DEV-003-….md` 1개 | 21.9초 | 8.1초 | 바이트 동일 |
| 개발사양서 xlsx 1개 + spec md 1개 | 50.1초 | 14.9초 | 바이트 동일 |

## 시험

- 새: `checker/tests/test_xlsx_cache.py`(한 번만 열기, 규칙 셋이 한 번, 파일 바뀌면 다시, 열기 실패·없는 파일은 캐시 안 함, 한도),
  `test_pr_queue_actions.py`(병렬과 순차의 쓰기·리포트 동일, 읽기 하나 실패 시 종료코드 2·나머지는 씀, status 읽기 실패해도 씀, 속도 제한 재시도·소진·권한 403 은 재시도 안 함),
  `test_pr_checks_workflow.py`(합친 단계의 구조, 종합의 이름별 경고).
- JS(`early-comments` 스크립트)는 `node --check` 로 구문만, bash 두 단계는 `bash -n` 과 분기 모의로 확인했다.
  GitHub 위에서 실제로 돌려 본 것은 아니다.

## 배포 뒤 확인할 것

- public-cloud 전체 검사 job 시간(`pr-checks / check`): 대부분 60초 이하인지, 이 PR 병합 뒤 10~20개 job 의 p50·p90.
- 첫 job 에서 `앞 검사 status 달기` 가 `gitleaks`·`doc-guard`·`ssot-approval` status 를 달았는지(PR 의 Checks), risk-gate 가 그것을 읽었는지.
- 종합 요약에 `status 못 담`·`코멘트 실패` 경고가 새로 생기지 않는지. 코멘트(doc-guard·ssot-approval·ledger-ready)가 그대로 갱신되는지.
- pr-queue 요약의 `읽기 실패` 가 늘지 않는지(병렬 읽기 속도 제한).
- 60초를 못 넘기는 job 이 남으면 남은 단계(gitleaks 바이너리 받기, uv 설치, checkout)를 다시 잰다.
