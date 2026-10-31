# #565 CDS 소스 확장자 5종을 코드 검사 대상에 추가 (2026-10-31)

## 배경

코드 검사(CR 규칙)는 확장자로 언어를 고른다. CDS 는 `.cds` 뿐이어서, abapGit 으로 받은 실제 소스(`.asddls` 등)는 검사 대상이 아니었다. public-cloud `src/` 에서 238개가 빠져 있었다.

## 바꾼 것

Plugin version 0.10.142.

- `checker/code_checks.yaml`: `cds.suffixes` 에 `.asddls`(DDLS), `.asddlxs`(DDLX), `.srvdsrv`(SRVD), `.asdcls`(DCLS), `.astabldt`(TABL) 추가. 규칙별 적용 언어(CR-001 만 cds 대상 등)는 그대로다.
- TABL 도 `cds` 로 묶었다. public-cloud 의 `.astabldt` 를 읽어 보니 `@Annotation : '문자열'`, `define table`, `"%admin"` 식별자로 CDS DDL 과 같은 주석·문자열 문법이라 같은 마스킹이 맞는다.
- 같은 목록의 사본: `pr-checks.yml`·`main-checks.yml` 의 `DOC_GUARD_PATHS`, 훅 `pre_write_guard.py` 의 `CODE_SUFFIXES`, `plugins/harness/README.md`.
- 시험: `test_code_rules.py` 에 5종 분류·CR-001 시험과 훅 `CODE_SUFFIXES` == yaml 확장자 비교 시험을 더했다. 워크플로 paths 와 yaml 비교는 `test_trigger_paths.py` 가 이미 한다.

## 확인한 것

- public-cloud `src/` 238개(`.asddls` 154, `.astabldt` 41, `.asddlxs` 22, `.srvdsrv` 18, `.asdcls` 3)에 새 설정으로 `check_source` 를 돌려 위반 0건. 단, 파일은 public-cloud 작업 트리에서 읽었다(다른 저장소 git 명령이 막혀 origin/main 추출은 못 했다).
- `uv run pytest checker/tests/test_code_rules.py checker/tests/test_trigger_paths.py checker/tests/test_hook.py -q`: 179 passed.

## 남긴 것

- 길잡이 `docs/guide/harness-guide.html` 에는 코드 검사 확장자 목록이 없어 고치지 않았다.
- scaffold skeleton 의 caller 워크플로에는 코드 확장자 paths 가 없다(#420 이후 재사용 워크플로가 가진다).
