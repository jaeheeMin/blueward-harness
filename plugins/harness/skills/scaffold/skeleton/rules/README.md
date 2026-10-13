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
(`templates/harness/SRS.md` 의 `##` 제목)을 검사하고 상세 절이 다른 REQ·DEV 번호를
말하면 `관계: 별개 — <이유>` 줄을 요구하며(`req_cross_reference`), `audit-changes.yaml`
과 `audit-ledger.yaml` 은 `audit/changes/` 와 `audit/ledger/` 에 쓰는 기록의
파일 이름과 필수 절을 검사하고, `spec.yaml` 은 `docs/spec/` 에 쓰는 개발
Spec 의 파일 이름(`DEV-001-<요약>.md`)과 필수 절(`templates/harness/spec.md`
의 `##` 제목)을 검사한다. 이 넷이 가리키는 템플릿은 `templates/harness/`
아래에 있다 — harness 자신의 템플릿이라 고객사 템플릿과 섞이지 않게 따로
둔다. 이 넷도 지우지 않는다.

`req_cross_reference` 의 관계 줄은 그 REQ 제목 바로 아래(첫 `####` 앞)에 일반
줄로 쓴다. `별개 —` 는 권장 표기이고, `관계:` 뒤에 이유가 있으면 통과한다. 이
규칙 종류는 그 규칙이 들어간 엔진 배포 태그를 쓰게 된 뒤에만 켤 수 있다(main 에 병합된 것만으로는
부족하다. Actions 는 `stable`, 훅은 플러그인 version 의 `v{version}` 태그를 받는다) — 엔진이 모르는
규칙 종류를 켜면 doc-guard 가 설정 오류(종료코드 2, 검사 불능)로 멈춘다. 이 규칙이
없는 옛 저장소에 더할 때도 같다.

`spec.yaml` 의 `md_table` 은 Spec 의 `## 사용 객체` 표(`| 종류 | 이름 | 작업 | 비고 |`)를
본다. 종류는 `conventions/naming.md` 의 표기, 작업은 생성·수정·참조 중 하나여야 한다.
`required_sections` 의 `선택_섹션` 에 `사용 객체` 가 있어 이 절이 없는 옛 Spec 은 통과한다.
`md_table` 도 엔진 v0.10.59 이상(`stable`)을 받게 된 뒤에만 켤 수 있다 — 먼저 켜면 위와 같이
설정 오류로 멈춘다.

## 교차 검사 스위치 — `cross-checks/switches.yaml`

doc-guard 는 문서 하나씩 보는 규칙 말고도 여러 문서를 함께 보는 검사 둘을 돌린다.

- `번호_짝` — SRS·Spec·진행 원장의 개발 번호가 서로 맞는지(진행 원장이 있는 저장소에서만).
- `객체_겹침` — 두 Spec 의 `## 사용 객체` 표가 같은 객체를 생성·수정한다고 적었는지(경고만).

`cross-checks/switches.yaml` 에서 값을 `false` 로 하면 그 검사를 이 저장소에서 끈다. 꺼진
검사는 PR 코멘트에 "이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" 한 줄로
남는다. 파일이 없으면 둘 다 켜진다. 모르는
키나 `true`/`false` 가 아닌 값은 설정 오류(검사 불능)다. 이 파일만 하위 폴더에 두는 이유는,
위에 적었듯 검사기가 이 폴더 최상위 `*.yaml` 을 모두 문서 규칙으로 읽기 때문이다 — 최상위에
두면 `관할` 이 없는 규칙 파일로 읽혀 모든 검사가 설정 오류로 멈춘다. 스위치는 엔진 v0.10.62
이상에서 읽는다.
