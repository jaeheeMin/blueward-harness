# #567 SRS 다음 단계 값이 개발·설정·미정 밖이면 위반으로 막기 (2026-10-31)

## 배경

`다음 단계` 열의 허용 값은 스킬 문서에만 있었다. 번호 짝 검사(`checker/pairing.py`)는 값이 오타거나 빈 칸이면 그 요구사항의 RICEFW·원장·Spec 대조를 위반·경고 없이 건너뛰었다.

## 바꾼 것

- `checker/pairing.py`: 허용 값 상수 `NEXT_STEPS`(`개발`·`설정`·`미정`, 한 곳). `다음 단계` 열이 있는데 값(앞뒤 공백 뺀 뒤)이 밖이거나 비면 위반 `next_step_invalid` 를 내고 그 요구사항의 나머지 대조는 건너뛴다. 열이 없는 옛 SRS 는 그대로 `개발` 로 간주한다. Status 가 On Hold·Dropped·Duplicate 여도 값은 검사한다.
- 문서: `skills/srs/SKILL.md`, `checker/README.md`, `checker/export.py` 주석, 길잡이 `docs/guide/harness-guide.html`.
- 시험: `checker/tests/test_pairing.py` 에 오타·빈 칸·공백·세 값·열 없음·종료코드 1 경우. Plugin version 0.10.144.

## 확인한 것

- 이 검사는 `scripts/check_changed.py` 가 `docs/ssot/SRS.md`·Spec·원장이 바뀌었을 때 돌리고, PR 검사(`pr-checks.yml`)와 main push 검사(`main-checks.yml`)가 그 스크립트를 부른다. 위반이면 종료코드 1.
- 저장 훅(`pre_write_guard.py`)은 번호 짝 검사를 부르지 않는다(파일 하나씩 보는 doc-guard 규칙과 코드 규칙만). 그래서 저장할 때는 막히지 않고 PR 에서 막힌다.
- `audit/ledger/` 가 없는 저장소와 규칙 스위치 `번호_짝` 이 꺼진 저장소는 이 검사 대상이 아니다.
- public-cloud main 의 SRS(요구사항 11건, 모두 `개발`)로 돌려 위반 없음(pass).
