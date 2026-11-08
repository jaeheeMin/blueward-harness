# #804 gitleaks 받기 캐시와 재시도 (2026-11-08)

## 왜

gitleaks 릴리즈 파일을 매번 github.com 에서 내려받아, 일시 고장이면 검사 불능이 됐다(재시도 3번뿐).

## 바꾼 것 (plugin.json 0.10.216)

| 파일 | 내용 |
|---|---|
| `.github/workflows/checker.yml` | `actions/cache@v5` 단계 추가(경로 `~/.cache/gitleaks-dl`, 키 `gitleaks-${{ runner.os }}-8.30.1`). 받기 단계는 캐시에 없을 때만 curl(`--retry 5 --retry-all-errors --retry-delay 10`), 어느 쪽이든 sha256 확인 |
| `.github/workflows/pr-checks.yml` | 같은 캐시 단계를 gitleaks 검사 앞에 추가, 같은 받기 방식 |
| `.github/workflows/main-checks.yml` | 같음 |

- sha256 이 다르면 파일을 지우고 실패한다(변조·깨진 파일이 캐시에 저장되지 않는다). 받지 못하면 지금처럼 검사 불능(`status=unknown`)이며 통과로 두지 않는다.
- GITLEAKS_VERSION·SHA 는 그대로. 캐시 키의 판 번호는 판을 올릴 때 함께 고친다(주석에 적음).
- 권한: actions/cache 는 GITHUB_TOKEN 이 아니라 러너 런타임 토큰으로 캐시 서비스를 부르므로 caller 의 permissions 를 늘리지 않는다.

## 확인

- 세 워크플로 YAML 구문, 관련 시험(아래 보고 참조). 실제 캐시 적중·재시도는 Actions 에서만 확인된다(미확인).

## 메인 검토에서 바꾼 것 (2026-11-08)

- `actions/cache` 한 단계(작업이 성공하면 무조건 저장)를 `actions/cache/restore` + `actions/cache/save` 로 나눴다. pr-checks·main-checks 는 gitleaks 를 못 받아도 검사 불능으로 처리하고 작업이 성공으로 끝날 수 있어, 그때 빈 캐시가 저장되면 같은 키가 차서 판을 올릴 때까지 캐시가 쓰이지 않는다. 이제 sha256 확인까지 통과했을 때(`GITLEAKS_CACHE_OK=1`)만 저장한다.
- curl 이 실패하면 `.part` 조각을 지운다.
- main-checks 는 gitleaks 검사 바로 뒤에 status 단계가 와야 해서(시험) 저장 단계를 status 단계 뒤에 뒀다.
- 시험: `test_main_checks_workflow.py`·`test_pr_checks_workflow.py`·`test_plugin_version.py`·`test_ensure_tools.py` 110 통과, 세 run 스크립트 `bash -n` 통과.
- 기본 주소(github.com 릴리스)가 막히면 `gh release download`(GitHub API 경로, `GH_TOKEN: github.token`)로 다시 받는다. 2026-11-08 고장 때 github.com 은 504, API 경로는 정상이었다. 로컬 확인: 기본 주소를 막은 상태로 checker.yml 단계를 돌려 API 로 받고 sha256 OK·캐시 표시 남음, 캐시 파일을 바꾸면 sha256 FAILED·파일 삭제·종료 1.
