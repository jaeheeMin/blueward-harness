# #524 CR-009 에 EML PRIVILEGED 위임 빈틈 경고 추가 (2026-10-28)

권한을 표준 BO 에 맡긴다며 권한 메서드를 전부 허용(또는 빈 본문)으로 두고, 그 BO 를 EML `PRIVILEGED`(`FORWARDING PRIVILEGED` 포함)로 부르면 표준 BO 의 권한 검사가 건너뛰어질 수 있어 위임이 성립하지 않는다(ABAP Keyword Documentation, EML PRIVILEGED). `checker/code_rules.py` 의 CR-009 가 이 경우 별도 경고를 낸다.

- 조건: 파일의 권한 메서드가 전부 기존 CR-009 경고 대상이고(AUTHORITY-CHECK 없음), MODIFY/READ/COMMIT 등 `ENTITIES` 문에 `PRIVILEGED` 가 있다. 주석·문자열 속은 마스킹으로 제외. 위치는 PRIVILEGED 가 나온 줄.
- 오탐 방지: 실제 AUTHORITY-CHECK 가 있거나 권한 메서드 하나라도 실제 검사를 하면 PRIVILEGED 만으로는 경고하지 않는다.
- 예외: `harness:allow CR-009 <이유>` 를 그 줄이나 위 줄에 두면 allowed, 이유가 없으면 인정하지 않는다(기존 규칙).
- risk-gate 의 `write_auth` 는 이 경고를 "권한을 표준에 맡기고 EML 을 PRIVILEGED 로 부름" 사유로 따로 보여 준다. ai-review 는 CR-009 를 직접 옮기지 않아 바꾸지 않았다.
- 시험: `checker/tests/test_code_rules.py` 에 7건 추가. Plugin version 0.10.134.
