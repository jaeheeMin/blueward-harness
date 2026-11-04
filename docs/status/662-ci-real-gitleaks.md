# #662 Actions 시험에서 진짜 gitleaks 시험이 건너뛰던 빈틈

## 찾은 경위
#658 에서 `checker.yml` 에 `pytest -rs` 를 더해 건너뛴 시험 이름을 처음 봤다(2026-11-04, Linux job). 건너뛴 15개:

| 개수 | 시험 | 이유 | 판단 |
|---|---|---|---|
| 5 | `test_engine_pin.py` 재사용 워크플로 engine-ref 기본값 | 그 입력이 없는 워크플로라 볼 게 없음 | 정상 |
| 9 | `test_git_guard_secret_scan.py` 6, `test_gitleaks_scan.py` 3 "진짜 gitleaks" | 시험 job 에 gitleaks 가 없어 `GITLEAKS_BIN` 이 비어 있음 | **빈틈** — 이 PR 에서 메움 |
| 1 | `test_manual_capture.py` 실제 Chrome | `HARNESS_CHROME_TEST=1` 일 때만 도는 손 확인용 | 정상(절차는 `533-manual-capture.md`) |

## 한 일
- `checker.yml` 시험 job 에 "gitleaks 받기" 단계: 8.30.1 을 공식 체크섬(`gitleaks_8.30.1_checksums.txt`)으로 고정해 받고 `GITLEAKS_BIN` 을 `$GITHUB_ENV` 로 시험 단계에 넘긴다. Linux 체크섬은 `main-checks.yml`·`pr-checks.yml` 과 같은 값, Windows 는 zip 체크섬을 새로 고정. Windows 는 bash 훅 시험을 위해 `cygpath -m` 으로 경로를 바꾼다.
- 시험 단계 줄(`pytest`)은 건드리지 않았다(#658 의 `-rs` 와 겹치지 않게).

## 확인
- 로컬(Windows, gitleaks 8.30.1): 9개 모두 통과.
- Actions: 이 PR 검사 로그에서 확인한다. `-rs` 는 #658 에 들어 있으므로, 이 PR 만으로는 건너뛴 이름이 로그에 안 나오면 시험 수(passed 가 9 늘고 skipped 가 9 줄어듦)로 확인한다.
