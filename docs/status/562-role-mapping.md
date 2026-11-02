# #562 User Role Mapping 산출과 role 스킬 추가 (2026-11-02)

## 배경

고객 양식 사용자권한관리(User Role Mapping)의 `Role to Area Menu` 는 Role 이 열로 늘어나는 표(Role 48개, O 표시 543개)인데, 엔진의 표는 지도에 적힌 고정 열만 처리했다. 이 일은 그 "가로로 늘어나는 열"을 일반 기능으로 더하고, 작업본·스킬·Spec 대조를 붙인다.

## 바꾼 것

- `checker/expand.py`(새): 표 지도 키 `펼침`. 지도 검증, 펼침이 맡은 영역, 빈 양식이 비우는 범위, 머리글·O 쓰기, 표시 열의 없는 값 찾기(`unknown_marks`).
- `checker/export.py`: 표 쓰기에서 펼침 호출, 작업본 전용 열(`md_전용`, `표시.열`)을 엑셀로 보내지 않고 읽기, `spec_offenders` 가 같은 열을 허용하고 없는 Role 값을 위반으로 보고(산출과 `form_columns` 가 같은 함수), `fill_ranges` 에 펼침 영역.
- `checker/blank_template.py`: 지도 검증에 `펼침`·`md_전용`·시트 `머리글_유지` 와 펼침 영역 겹침(`비우기`·`서식_지우기`).
- `checker/leftover.py`: 시트 `머리글_유지` 와 같은 머리글·바닥글 문구는 `leftover-review` 경고에서 뺀다.
- `checker/rules/form_columns.py`: 작업본 검사에 같은 시트들 전달(없는 Role 값 위반).
- `checker/role_check.py`(새): Spec `## Launchpad 노출` 카탈로그가 작업본 메뉴 배정 표에 있는지 대조(`python -P -m checker.role_check`, 종료코드 0 ok / 1 missing / 2 검사 불능).
- `plugins/harness/skills/role/`: `SKILL.md`, 규칙 사본 `role.yaml`·`role-output.yaml`, 틀 `role-template.md`.
- `plugins/harness/skills/spec/form-map.md`: `펼침`·`md_전용`·`머리글_유지` 형식.
- `checker/tests/test_role_mapping.py`(새), `test_plugin_layout.py`·`test_engine_pin.py` 스킬 목록에 `role`.
- `CLAUDE.md`·`plugins/harness/README.md` 스킬 표, 길잡이 `docs/guide/harness-guide.html` 에 Role 매핑 탭(CTS 뒤, 시작하기 앞)과 레일 판. plugin.json 0.10.152(열린 #591 이 0.10.151).

## 정한 것

- **작업본 위치:** `docs/권한관리/사용자권한관리_User_Role Mapping.md`. CTS 와 같이 지도 `산출.파일명` 에서 `_v{버전}` 만 뺀 이름이라 산출 xlsx 와 나란히 놓인다(파일명에 공백이 있다).
- **펼침 키:** `원본`(시트·표·열) / `시작_열` / `끝_열` / `머리글`(행 번호: 원본 표의 열 이름) / `표시`(열·값). 넘치면 산출 거부(종료코드 1), 표시 열의 없는 Role 은 종료코드 2·`form_columns` 위반.
- **Role 개요의 `조직 레벨`:** 지도 표 `열` 에 없는 작업본 전용 열이라 표 키 `md_전용` 으로 처리한다.
- **고정 머리글·바닥글:** 시트 키 `머리글_유지: [문구…]` 를 새로 더했다(기존에 선언 수단이 없었다).
- **사람 행:** `ID-Role Mapping` 은 `표시` 없는 펼침(Role 머리글만)이라 사람 행은 비워 산출한다. 작업본에 이 시트 표를 쓰지 않는다.
- **Spec 대조는 코드:** 스킬 절차가 아니라 `role_check` 명령으로 하고 시험했다. 카탈로그 이름만 보고, `## 권한` 은 대조하지 않는다.

## 확인하지 못한 것 / 범위 밖

- 모듈 묶음 행(2행 병합)은 채우지 않는다. 병합 조작이 커서 범위 밖이다. `머리글` 에 적지 않은 행은 건드리지 않는다.
- COUNTA 수식 행은 건드리지 않는다. 펼친 열 수가 `끝_열` 보다 적으면 남은 열의 수식이 0 을 센다.
- public-cloud 지도에 `펼침`·`md_전용`·`머리글_유지` 반영과 `비우기: [G8:BB1295]`·`서식_지우기: [G2:BB6]`·`[P1:CN5]` 조정은 다른 세션 몫이다(펼침 영역과 겹치면 지도 오류).
- 엑셀 화면에서 본 서식은 사람이 열어 확인해야 한다. openpyxl 로 값·수식 위치만 읽었다.
