# {{client}} {{project}}

이 저장소는 {{date}} 에 blueward-harness 플러그인의 `/scaffold` 로 만든
Project Repository 다. 이 프로젝트의 최종 산출물과, 그 산출물을 검사할
기준(템플릿과 규칙)을 함께 든다.

## 디렉터리

| 경로 | 무엇을 두나 |
|---|---|
| `docs/ssot/PRD.md` | 이 프로젝트의 SSOT. 요구사항의 정본 |
| `docs/spec/` | 개발 Spec. 개발 건 하나에 파일 하나(`DEV-001-<요약>.md`) |
| `templates/` | 고객사에게 받은 템플릿 원본. `templates/harness/` 는 harness 자신의 템플릿(Audit 등) |
| `rules/` | 검사 규칙(`*.yaml`). 문서가 템플릿을 따르는지 이 규칙으로 본다 |
| `conventions/` | 이 프로젝트에서만 통하는 Convention |
| `audit/changes/` | 변경 기록. 무엇이 왜 바뀌었는지, 기록 하나에 파일 하나 |
| `audit/ledger/` | 진행 원장. 프로그램 하나에 파일 하나 |
| `env/` | 환경별 접속 URL |
| `.github/workflows/doc-guard.yml` | PR 과 main 커밋마다 doc-guard 검사를 돌리는 워크플로 |

## 규칙

- 산출물은 `docs/` 아래 두고 버전은 파일명에 남긴다(`개발사양서_v1.0.xlsx`).
  이전 버전도 지우지 않는다.
- 고객사 템플릿과 검사 규칙은 이 저장소 안 `templates/` 와 `rules/` 에 둔다.
- `docs/ssot/PRD.md` 가 SSOT 이고, Convention 과 Template 은 링크로만
  참조한다.
- 객체·파일·변수 이름을 지을 때는 `conventions/` 의 파일(특히 `naming.md`)을
  먼저 읽는다. CAP·SAPUI5 코드는 `conventions/cap-ui5.md` 도 읽는다.
- 비밀번호 같은 Credential 은 저장소에 두지 않는다.
- 검사를 못 했다는 결과를 통과로 보지 않는다.
