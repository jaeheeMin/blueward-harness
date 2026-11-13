# #943 개발 표준 이름 규칙 검사 (0.10.280)

## 배경
고객사마다 개발 표준 이름이 다르다. 규칙은 데이터라는 원칙(CLAUDE.md 원칙 2)대로 Project Repository 의 `conventions/naming.yaml` 에 두고 하네스가 읽어 검사한다.

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/naming_rules.py` | 찾기(위로 올라가며 `.git` 에서 멈춤)·읽기(pyyaml)·판정. CLI `check`·`files`, 종료코드 0 통과·1 위반·2 검사 불능 |
| `plugins/harness/hooks/mcp_source_guard.py` | `createObject`·`renameExecute`·`renamePreview` 가 CR-001 을 통과한 새 이름을 엔진(uvx)으로 한 번 더 판정. 파일이 없으면 엔진을 부르지 않는다 |
| `scripts/check_changed.py`·`scripts/render_report.py` | 환경변수 `DOC_GUARD_ADDED_FILES` 의 추가 파일만 검사, 리포트 `naming` 키와 PR 코멘트 절 |
| `.github/workflows/pr-checks.yml` | doc-guard 단계 안에서 `git diff --no-renames --diff-filter=A` 로 `added.txt` 를 만들어 넘김(새 job 없음) |
| `plugins/harness/conventions/naming.example.yaml` | 사내 표준(Naming Guide v1.2) 예시 |
| `common.md`·`README.md`·길잡이 | CR-008 에 기계 검사(선택) 설명 |

## 규칙 모양
`영역코드` 목록, `객체`(종류 → `형식` 정규식·`최대_길이`), `예외` 목록. 종류는 ADT objtype 앞 4글자이고 `TABL/DT` 처럼 하위 종류까지 적으면 따로 본다. 형식은 대소문자 무시 전체 일치, `{영역}` 은 영역코드로 바뀐다. 없는 종류는 통과, 파일이 없으면 검사하지 않음, 못 읽으면 검사 불능.

## 결정
- 새 객체만 막는다. 이미 있는 형식 밖 객체를 고치는 PR 은 막지 않는다(사용자 결정).
- 이름 바꾸기: abap-adt-api 의 `RenameRefactoringProposal`(`refactor.d.ts`)은 `{oldName, newName, adtObjectUri: UriParts}` 이고 `UriParts`(`urlparser.d.ts`)는 `{uri, query, range, hashparms}` 객체다. 훅은 `adtObjectUri.uri`(문자열이면 그대로)에서 `key_from_url` 로 객체 종류·이름을 얻고, `oldName` 이 그 객체 이름과 같을 때(대소문자 무시)만 객체 이름 바꾸기로 보고 `newName` 을 검사한다. 클래스 이름 바꾸기는 uri 에 `/source/main` 이 붙을 수 있어 URL 모양으로 거르지 않는다. `oldName` 이 다르면(메서드·변수)·uri 나 `oldName` 이 없으면·종류를 못 얻으면 건너뛰고 CR-001 만 본다. 실제 테넌트 호출로는 확인하지 않았다(타입 정의 근거).
- public-cloud 규칙 내용(사용자 결정 2026-11-13): 새 `ZCSH_`·`ZMJH_` 이름은 막는다(영역코드에 CSH·MJH 추가 안 함). DB Table 은 표준대로 엄격(Z영역+A|D+숫자4, 최대 16자). 그 저장소의 파일은 plugin-help 세션이 만든다.

## 알려진 한계
- PR 검사는 파일 이름만 보므로 TABL 의 Table/Structure 를 구분하지 못한다(둘 중 하나라도 맞으면 통과).
- MSAG·SRVB·DOMA·DTEL 은 `src/` 파일이 없어 훅으로만 잡힌다.
- 재사용 워크플로를 고쳤으므로 Project Repository caller 는 `@stable` 이라 변경 없이 배포 뒤 적용된다.

- 예시 `naming.example.yaml` 의 DB Table 형식은 `^Z{영역}[AD]\d{4}(_.+)?$` 다. 표준의 "(+_Text)" 는 뒤에 설명을 붙여도 된다는 뜻이라 글자 `_TEXT` 를 요구하지 않는다(메인 검토에서 고침).
- 메인 확인 시험: `test_naming_rules`·`test_render_report`·`test_pr_checks_workflow`·`test_changed_listing`·`test_mcp_source_guard`(-k 이름·rename 관련) → 151 passed.
