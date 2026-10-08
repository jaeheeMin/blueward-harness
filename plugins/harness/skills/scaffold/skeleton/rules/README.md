# rules

이 폴더의 최상위 `*.yaml` 을 검사기가 읽는다. 하위 폴더는 읽지 않는다.

- 한 파일에 문서 유형 하나를 담는다.
- `관할` 은 저장소 루트를 기준으로 한 glob 이다(`docs/제안서/**`).
- 이 폴더에 yaml 이 하나도 없으면 모든 검사가 설정 오류로 실패한다.
  `ssot.yaml` 을 지우지 않는다.
- `관할` 이 가리키는 자리에 `.gitkeep` 같은 자리표시·시스템 파일을 둬도 된다.
  검사기가 문서로 보지 않고 건너뛰며, 건너뛴 이유를 리포트에 남긴다. 다만
  `.hwp` 처럼 진짜 문서인데 읽을 리더가 없는 형식은 이 예외를 타지 않고
  검사 불능이 된다 — 관할을 좁혀 그 파일을 빼거나 리더를 추가해야 한다.

## 예시 — 템플릿이 있는 유형

아래는 템플릿을 대조하는 유형의 예시다. 실제로 쓰려면 `templates/` 에 해당
파일을 넣고, 이 예시를 참고해 새 `*.yaml` 을 만든다.

```yaml
템플릿: ../templates/제안서.md
관할: "docs/제안서/**"

규칙:
  - 종류: filename
    패턴: '^\d{8}_.+_제안서\.md$'
  - 종류: location
    있어야_할_곳: docs/제안서
  - 종류: required_sections
    선택_섹션: [부록]
```

템플릿을 읽지 않는 규칙(`filename`, `location` 등)만 쓸 때는 `템플릿:` 을
아예 생략할 수 있다.

## harness 가 미리 넣어 둔 규칙

`ssot.yaml` 외에 `audit-changes.yaml` 과 `audit-ledger.yaml` 과 `spec.yaml`
도 이미 있다. `ssot.yaml` 은 `docs/ssot/SRS.md` 의 파일 이름과 필수 절
(`templates/harness/SRS.md` 의 `##` 제목)을 검사하고, `audit-changes.yaml`
과 `audit-ledger.yaml` 은 `audit/changes/` 와 `audit/ledger/` 에 쓰는 기록의
파일 이름과 필수 절을 검사하고, `spec.yaml` 은 `docs/spec/` 에 쓰는 개발
Spec 의 파일 이름(`DEV-001-<요약>.md`)과 필수 절(`templates/harness/spec.md`
의 `##` 제목)을 검사한다. 이 넷이 가리키는 템플릿은 `templates/harness/`
아래에 있다 — harness 자신의 템플릿이라 고객사 템플릿과 섞이지 않게 따로
둔다. 이 넷도 지우지 않는다.
