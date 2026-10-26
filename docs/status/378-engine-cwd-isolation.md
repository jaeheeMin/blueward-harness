# #378 하네스 저장소에서 훅의 엔진 호출이 작업 트리의 checker 를 잡는 문제

## 증상

- 훅이 `uvx --from <엔진> python -m checker.<모듈>` 로 엔진을 부를 때 cwd 가 하네스 저장소 루트면 `python -m` 이 cwd 를 `sys.path[0]` 에 넣어 작업 트리의 `checker/` 를 설치본보다 먼저 잡는다. rebase 하지 않은 브랜치의 옛 `checker` 가 잡히면 새 옵션이 없어 argparse 오류(종료코드 2)가 나고 "확인 불능, 사유: usage…" 만 보인다.
- 재현: 하네스 루트에서 `uvx --from <엔진> python -c "import checker;print(checker.__file__)"` 는 작업 트리의 `checker/__init__.py`, 다른 폴더에서는 uv 캐시의 설치본을 가리켰다.

## 결정

- 엔진은 cwd 를 저장소로 쓴다(`gh`·git 호출이 cwd 기준). 그래서 cwd 를 바꾸지 않고 `python -P`(Python 3.11+, cwd 를 `sys.path` 에서 뺀다)를 붙인다. 엔진은 `requires-python >=3.12` 라 쓸 수 있다.
- 호출 지점마다 `-P` 를 붙였다: `pre-bash-git-guard.sh` 6곳, `session-start-sync.sh`, `pre_write_guard.py`·`mcp_source_guard.py` 의 code_rules, 스킬(approvals·deliver·prs·spec·srs·start)의 명령. 공통 헬퍼로 모으면 sh·py·스킬 문서가 모두 헬퍼를 거치게 바뀌어 위험이 더 커서 각 호출에 붙였다.
- `doc-guard` 콘솔 스크립트 호출은 `sys.path[0]` 가 스크립트 폴더라 영향이 없어 그대로 둔다.
- 테스트 `checker/tests/test_engine_cwd_isolation.py`: 옛 `checker/` 가 있는 폴더를 cwd 로 두면 `-P` 없이는 그것이 잡히고 `-P` 로는 설치본이 잡히며 cwd 가 유지됨을 확인하고, 훅·스킬의 모든 호출에 `-P` 가 있는지 훑는다.
- plugin version 0.10.124, 길잡이 레일 판 0.10.124.

## 남은 일

- `.github/workflows/human-merge-alert.yml` 의 `uv run python -m checker...` 는 이 저장소 체크아웃의 엔진을 쓰는 것이 의도라 건드리지 않았다.

## 로컬 테스트에서 드러난 캐시 문제

- `-P` 를 붙인 뒤 `test_hook.py`·`test_mcp_source_guard.py` 의 CR-009 테스트 4건이 로컬에서 실패했다. 테스트는 `uvx --from <작업 트리>` 로 엔진을 부르는데, uv 캐시에 남은 옛 빌드(CR-009 이전)가 쓰였다. `-P` 전에는 cwd 의 작업 트리 `checker/` 가 그 캐시를 가렸다.
- 빈 캐시(`UV_CACHE_DIR=<새 폴더>`)로 다시 돌리면 4건 모두 통과했다. 코드 문제가 아니다.
- 실제 훅은 엔진을 판 태그(`v{version}`)로 받으므로 이 캐시 문제가 없다. CI 러너도 매번 새 캐시다.
- 로컬에서 엔진 테스트가 이유 없이 옛 동작을 보이면 `UV_CACHE_DIR` 를 새 폴더로 주거나 `uv cache clean doc-guard-checker` 를 한다.
