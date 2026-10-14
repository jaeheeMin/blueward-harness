# #308 엔진 메시지의 REQ·DEV 번호에 제목 괄호 붙이기 (2026-10-14)

#307 의 표기 규칙(`DEV-002(판매오더 조회 앱)`)을 엔진·스크립트가 사람에게 내는 메시지에도 적용했다. 기계가 읽는 값(JSON 키, `kind`, `dev` 필드, 파서 정규식, PR 코멘트 마커)은 바꾸지 않았다.

- `checker/pairing.py`: 메시지의 번호를 `titled()` 로 만든다 — 원장 중복, Spec 칸(외부 링크·대상 없음·다른 번호), 근거 요구사항 불일치, 원장 Spec 칸 `설정`, `no_*` 경고, `ledger_without_req`·`spec_without_req`, RICEFW 메시지의 `REQ-nnn`. 제목은 SRS 요구사항 표의 `Title`(없으면 `요구사항`) 열, SRS 에 없는 번호는 원장 `내용` 칸, 그것도 없으면 `(제목 미확인)`. 추측하지 않는다. RICEFW 메시지의 "`DEV-nnn` 이어야 합니다" 는 기대값이라 그대로 뒀다. 공용 헬퍼 `number_titles(root)` 를 두어 읽기에 실패하면 그 출처를 건너뛴다(메시지 꾸밈이 검사 결과를 바꾸지 않는다).
- `checker/overlap.py`: `DEV-nnn` 라벨을 `number_titles` 로 붙이고 작업은 공백으로 뗐다(`DEV-002(조회 앱) 생성` — 괄호가 연달아 붙어 읽기 어려워서). 판단 — Spec 파일명 요약이나 Spec 본문에서 제목을 추측하지 않는다. 파일명 요약은 사람이 지은 이름이라 SRS 제목이 아니고 규칙이 번호·제목 모양을 읽는 파일명을 건드리지 않기로 했다. SRS·원장 둘 다 없으면 `(제목 미확인)`.
- `checker/risk_gate.py`: `split_hint` 사유의 REQ·DEV 번호(새 REQ, (a) 다른 번호 언급, (b) "하지 않는 것" 꼬리표 번호, (c) 겹친 기존 REQ)에 `titled_id()` 로 제목을 붙인다. (c) 는 `REQ-001 '제목'` 이던 것을 `REQ-001(제목)` 으로 통일. DEV 번호는 같은 숫자의 REQ 제목을 쓴다.
- `plugins/harness/skills/start/reserve_number.py`: 기존 키는 그대로 두고 필드만 더했다 — `list` 의 `devs[].label`(SRS 제목, 없으면 원장 내용, 이슈 제목, `(제목 미확인)` 순), `confirm` 의 `matches[].label`, `excluded_matches[].reqs_labeled`(`reqs` 는 그대로). start `SKILL.md` 에 이 필드를 쓰라는 안내를 최소로 넣었다.
- `scripts/render_report.py`: 번호를 따로 조립하는 곳이 없다(엔진 메시지와 파일 경로만 그대로 싣는다). 고치지 않았다. 객체 겹침 표의 Spec 칸은 파일 경로(`DEV-002-...md`)라 범위 밖.

검토 반영: 제목 칸이 `-`·`—`·`–`·빈 값이면 제목 없음으로 보고 다음 후보로 간다(엔진·`list` 모두). overlap 문장은 `<종류> <이름> — 같은 객체를 여러 Spec 이 다룹니다: DEV-001(…) 생성; DEV-002(…) 수정`. 엔진과 `list` 의 차이 — `reserve_number list` 의 `label` 은 마지막 대체로 이슈 제목(`[DEV-xxx]` 뗀 것, 사람이 쓴 제목)도 쓰지만 엔진(pairing·overlap)은 이슈를 읽지 않아 SRS → 원장 내용 → `(제목 미확인)` 까지만 간다.

테스트: `test_pairing`·`test_overlap`·`test_risk_gate`·`test_reserve_number` 에 제목 있음 / SRS 에 없음(원장 내용 대체) / 둘 다 없음(제목 미확인) 경우를 더하고 바뀐 기대 문자열을 갱신했다.

길잡이: 동작 설명이 바뀌는 곳이 없어 레일 버전만 harness 0.10.67 로 고쳤다. Plugin version 0.10.66 → 0.10.67.
