# #577 CTS 관리대장 작업본 산출 스킬 추가 (2026-11-02)

## 배경

public-cloud 에 CTS 관리대장 Configuration·CBO 양식과 지도(`templates/forms/CTS_관리대장_*.yaml`)가 들어왔다. 엔진은 이미 작업본 md 로 이 지도를 산출한다(#576 의 머리 `버전:`). 막힌 것은 트랜스포트에서 값을 자동으로 가져오는 부분뿐이라 [#563](https://github.com/jaeheeMin/blueward-harness/issues/563) 에서 떼어 먼저 했다. 이 스킬은 사람이 알려 준 요청 건을 받아 적는다.

## 바꾼 것

- `plugins/harness/skills/cts/SKILL.md`: `/harness:cts`. 브랜치 확인(start 의 "다른 스킬이 부르는 브랜치 확인"), 종류 고르기, 요청 건·Error 내역 행 추가(NO 는 표마다 마지막 + 1), 버전 올리기, `--check` → 산출(`engine_spec.py`·`uvx`·`python -P -m`), 종료코드 안내, 규칙 설치.
- `plugins/harness/skills/cts/cts.yaml`·`cts-output.yaml`·`cts-template.md`: 규칙 사본 둘(작업본 `.md` / 산출 `.xlsx`)과 틀. Project Repository 의 `rules/cts.yaml`·`rules/cts-output.yaml`·`templates/harness/cts.md` 로 복사한다.
- `checker/tests/test_cts_ledger.py`: 시험용 양식을 코드로 만들어 두 양식 산출(`_v0.1`), 행 추가 뒤 `_v0.2` 와 이전 판 보존, 양식 밖 열, 규칙 사본.
- `test_plugin_layout.py`·`test_engine_pin.py` 의 스킬 목록에 `cts` 추가. `CLAUDE.md`·`plugins/harness/README.md` 스킬 표, 길잡이(`docs/guide/harness-guide.html`)에 CTS 관리대장 탭. plugin.json 0.10.150(열린 #584 가 0.10.149).

## 정한 것

- **작업본 위치:** `docs/CTS관리대장/CTS관리대장_<종류>.md`. 지도 `산출.폴더` 가 `docs/CTS관리대장` 이고 파일명이 `CTS관리대장_<종류>_v{버전}.xlsx` 라서 `_v{버전}` 만 뺀 이름으로 같은 폴더에 둔다. 종류마다 파일 하나, 한 번에 한 종류만 산출(`--form`).
- **규칙 사본을 둘로 나눔:** 한 규칙 파일은 `관할` 이 하나뿐이라 `.md`(cts.yaml)와 `.xlsx`(cts-output.yaml)를 따로 둔다. 지도에 `검사_규칙` 이 없어 산출이 xlsx 파일명 패턴을 대조하지는 않고, PR 의 doc-guard 가 본다.
- 판 올리기: 작업본 하나, 판마다 새 xlsx. `origin/main` 에 있는 판이면 `버전:` 을 0.1 올리고, 이 브랜치에서 만든 판이면 그대로 다시 산출한다(엔진 동작 그대로).

## 확인하지 못한 것

- 자동 채우기(트랜스포트 조회)는 #563.
- 엑셀 화면에서 본 서식(고객 원본 양식 기준)은 사람이 열어 확인해야 한다. openpyxl 로 값 위치·병합·날짜 서식만 읽었다.

## 독립 검토 뒤 보완

- 다른 종류의 양식 소절(예: Configuration 작업본 안의 `CTS_관리대장_CBO`)은 `--form` 산출에서 조용히 빠졌다. `form_columns` 에 일반 키 `파일명_양식`(파일 이름 정규식의 이름 그룹 → 양식 이름 틀)을 더해 저장 훅·PR 에서 거절한다. `cts.yaml` 에 적용.
- 날짜 서식 칸에 `YYYY-MM-DD` 가 아닌 값이 들어가면 산출이 `type: date-text` 경고(종료코드 3)를 낸다. 모든 xlsx 산출에 걸린다. 막지는 않는다(기존 문서의 `-` 같은 값 때문).
- `NO` 가 숫자인지는 검사하지 않는다. 양식 칸이 일반 서식이라 엔진이 숫자 칸인지 모른다. 스킬이 1부터 이어 쓴다.
- 스킬의 `git ls-tree` 에 `-c core.quotepath=false`. `export.py` 머리 설명의 `dropdown-unchecked` 종료코드를 실제(3)에 맞춤.
- 시험: `test_cts_ledger.py` 23개, `test_form_columns.py` 등 74개, `test_export.py`·`test_export_pptx.py` 201개 통과. 전체 시험은 로컬 메모리 부족으로 돌리지 않았다.
