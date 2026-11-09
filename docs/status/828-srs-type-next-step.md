# #828 SRS 에서 Type 을 고르면 다음 단계가 정해지게 (2026-11-09)

## 배경
`/harness:srs` 가 고객 Backlog 양식의 드롭다운 열 `Type`(SSCUI / Process / Developer Extensibility …)과 하네스 갈래 열 `다음 단계`(개발/설정/표준/미정)를 따로 물었다. 둘은 사실상 같은 결정이라 두 번 묻고, 어긋난 조합(SSCUI + 개발)을 아무도 잡지 않았다(`checker/pairing.py` 는 다음 단계 ↔ RICEFW ID 만 봤다).
사용자 결정(2026-11-09): Type 드롭다운에서 하나를 고르면 다음 단계가 정해진다. 하나로 안 정해지는 값만 개발/설정을 한 번 더 묻고, Type 을 모르면 `미정`, Type 열이 없는 양식은 지금처럼 다음 단계를 직접 묻는다. checker 는 처음엔 경고로 알린다.

## 설계
- 대응표는 데이터다. 양식 지도(Project Repository 의 `templates/forms/<양식>.yaml`)의 `원본: SRS` 표에 `다음_단계_대응: {열: Type, 값: {<드롭다운 값>: 개발|설정|표준|묻기}}` 로 둔다. Type 값은 고객 양식마다 달라 엔진 코드에 두지 않는다(CLAUDE.md 원칙 2·3).
- 모양 검사는 `checker/blank_template.py` 의 `map_problems` 에 넣어 `form_columns`·산출이 같은 검증을 쓴다. 틀리면 지도 오류(검사 불능).
- 키가 드롭다운 허용 값 안인지는 xlsx 를 열어야 알아서 `export --list-values` 가 `type: next-step-map` 경고로 알린다.
- Type↔다음 단계 대조는 `pairing.py`(경고 `type_next_step_mismatch`·`type_unmapped`·`type_map_invalid`). `묻기` 는 개발·설정 둘 다 허용, 다음 단계 `미정`·빈 Type 은 대조하지 않는다. 대응표가 없거나 SRS 에 Type 열이 없으면 아무것도 하지 않는다.

## 바꾼 것
- `checker/blank_template.py`, `checker/export.py`, `checker/pairing.py`, `checker/README.md`
- `plugins/harness/skills/srs/SKILL.md`: "Type 으로 정해지는 다음 단계" 절(예시 대응표 포함), 허용 값 보기·질문·고치기 문장
- `docs/guide/harness-guide.html`: 다음 단계 절에 Type 으로 정해진다는 설명
- `plugins/harness/.claude-plugin/plugin.json` 0.10.233 → 0.10.235(열린 PR 최고 판 0.10.234 + 1), `console/whats_new.json`
- 시험: `test_pairing.py`(일치·어긋남·묻기·없음·Type 열 없음·지도 오류), `test_form_columns.py`(모양), `test_export.py`(허용 값 밖 키)

## 확인 못 한 것
- 대응표 경고는 `audit/ledger/` 가 있는 저장소에서만 돈다(번호 짝 검사 전체가 그렇다).
- 실제 public-cloud 양식으로 srs 스킬 대화를 끝까지 돌려 보지 못했다(문장만 바꿨다).
- skeleton `templates/forms` 는 비어 있어 예시는 README 와 srs 스킬에만 적었다.

## public-cloud 쪽 후속 (이 PR 밖)
Project Repository 의 `templates/forms/Backlog.yaml` 에 `다음_단계_대응` 을 추가해야 켜진다(위 예시 값 초안). 엔진 태그가 퍼진 뒤에 넣는다.
