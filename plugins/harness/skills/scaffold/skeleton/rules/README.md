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

`spec.yaml` 은 `## Launchpad 노출` 표(`| 타일 제목 | 부제 | 아이콘 | 시맨틱 오브젝트 | 액션 | 파라미터 | 카탈로그 | 배치 |`)
를 보는 `md_table` 을 하나 더 가진다. 시맨틱 오브젝트·액션의 문자 형식만 검사하고, 이 절도
선택 절이라 없는 옛 Spec 은 통과한다. 사용 객체 `종류` 값에는 `IAM App`, `Business Catalog`,
`Launchpad App Descriptor Item` 이 더해졌다. 새 규칙 종류가 아니라 같은 `md_table` 이라 엔진 판
제약은 없다. 다만 새 절·새 종류는 이미 만들어진 Project Repository 의 `rules/spec.yaml` 과
`templates/harness/spec.md` 에 자동으로 오지 않는다 — 엔진·스킬을 갱신한 뒤 각 저장소 rules 에 직접
반영한다(그 전에는 옛 규칙대로 검사되고, 새 종류를 쓴 Spec 은 `종류` 허용 목록 위반이 된다).

`ssot.yaml` 의 `form_columns` 는 SRS 요구사항 표의 열과 상세 절 `####` 소제목이 양식 지도(`templates/forms/` 에서
`원본: SRS` 인 지도)의 열 + md 전용 열 + `다음 단계` 밖이면 "양식 밖 열" 로 거절한다. 지도에 있는데 표에 빠진 열은
허용한다. 지도가 없으면 `templates/harness/SRS.md` 의 열이 기준이고 `기본_소제목`(설명, 완료 조건)이 상세 절에 허용된다.
`spec.yaml` 의 `form_columns`(`원본: 작업본`)는 Spec 의 `## 양식 항목` 이 지도에 없는 양식·시트·칸·표·열을 쓰면 거절한다.
이 규칙 종류는 그 규칙이 든 엔진 배포 태그(v0.10.75 이상, `stable`)를 받게 된 뒤에만 켤 수 있다. 순서: 병합 → 엔진 태그
`v0.10.75`·`stable` 이동 확인 → 팀원 플러그인 0.10.75 이상 → 각 Project Repository `rules/` 에 켜기. 먼저 켜면 규칙 파일을
읽는 순간 설정 오류(종료코드 2)가 나서 *모든 문서 유형*이 검사 불능으로 멈춘다. 새 scaffold 는 `stable` 이 0.10.75 이상일 때만
쓴다(아니면 `form_columns` 항목을 빼고 시작). `지도_폴더` 를 적었는데 폴더가 없으면 틀 기준으로 갈아타지 않고 검사 불능이다. 이미 만든 Project Repository 의 `rules/ssot.yaml`·`rules/spec.yaml` 에는
자동으로 오지 않으니 직접 반영한다. 양식 지도를 못 읽으면 이 규칙은 통과도 위반도 아닌 검사 불능이다.

## 교차 검사 스위치 — `cross-checks/switches.yaml`

doc-guard 는 문서 하나씩 보는 규칙 말고도 여러 문서를 함께 보는 검사 셋을 돌린다.

- `번호_짝` — SRS·Spec·진행 원장의 개발 번호가 서로 맞는지(진행 원장이 있는 저장소에서만).
- `객체_겹침` — 두 Spec 의 `## 사용 객체` 표가 같은 객체를 생성·수정한다고 적었는지(경고만).
- `판_겹침` — 열린 PR 끼리 같은 문서 판 번호를 쓰는지(경고만). 이 PR 이 추가한 `_v0.3` 같은 판 있는
  산출 파일이나 바꾼 SRS `버전:` 이 다른 열린 PR 과 같으면 알려 준다. 다른 열린 PR 을 GitHub 에서
  읽어야 해서 PR 에서만 돌고(로컬 훅은 안 돎), 못 읽으면 검사 불능이다. v0.10.71 이상 엔진이 읽는다.

`cross-checks/switches.yaml` 에서 값을 `false` 로 하면 그 검사를 이 저장소에서 끈다. 꺼진
검사는 PR 코멘트에 "이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" 한 줄로
남는다. 파일이 없으면 모두 켜진다. 모르는
키나 `true`/`false` 가 아닌 값은 설정 오류(검사 불능)다. 이 파일만 하위 폴더에 두는 이유는,
위에 적었듯 검사기가 이 폴더 최상위 `*.yaml` 을 모두 문서 규칙으로 읽기 때문이다 — 최상위에
두면 `관할` 이 없는 규칙 파일로 읽혀 모든 검사가 설정 오류로 멈춘다. 스위치는 엔진 v0.10.62
이상에서 읽는다.
