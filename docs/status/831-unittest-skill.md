# #831 단위테스트 List 작성 스킬 /harness:unittest (2026-11-09)

## 무엇을 했나
LoB 별 단위테스트 List 작업본(`docs/unittest/<LoB>.md`)을 쓰고 고객 양식 xlsx(`BW_단위테스트 List_<LoB>_v<버전>.xlsx`)로 산출하는 스킬을 더했다. 시나리오 초안은 SAP Best Practices 의 스코프 아이템별 공식 테스트 스크립트에서만 만들고, 확인하지 못한 칸은 비워 `근거` 열에 `확인 필요` 로 남긴다. 담당자·일정·상태·Test 결과 같은 사람 칸은 작업본에 열 자체가 없고 비워 산출한다.

- `plugins/harness/skills/unittest/` — `SKILL.md`, `unittest.yaml`(작업본 규칙: 파일명·필수 절·form_columns·ID 형식), `unittest-output.yaml`(산출 파일명), `unittest-template.md`(틀).
- `checker/rules/form_columns.py` — 새 파라미터 `ID_패턴`: 반복 견본 소절(`### <양식> · <견본> · <ID>`)의 ID 가 정규식 전체와 맞아야 한다. 단위테스트 규칙은 `^[A-Z]{2,3}(\.\d{2}){3,4}$`.
- `plugins/harness/workflow.json`(도구 `unittest`), `CLAUDE.md` 스킬 표, `plugins/harness/README.md`, 길잡이 `docs/guide/harness-guide.html`(탭 "단위테스트 List 쓰기"), plugin.json 0.10.242.
- 시험: `checker/tests/test_unittest_skill.py`(새 파일), `test_form_columns.py` 에 `ID_패턴` 시험, 스킬 목록이 열거된 `test_engine_pin.py`·`test_plugin_layout.py`·`test_web_console.py` 의 목록에 `unittest` 추가.

## 설계 결정
- 양식 지도·빈 양식 xlsx·`rules/`·틀은 Project Repository(public-cloud) 몫이다. 이 저장소는 스킬과 규칙·틀 사본만 둔다(role·cts 와 같다). public-cloud 에 넣을 파일은 스테이징해 인계했다.
- 받은 견본은 Test Case 시트가 둘(`FI.01.03.02.02`·`FI.02.03.02`)이었다. 하나(`TC.견본`)만 남기고 나머지는 템플릿에서 뺐다(다른 고객의 계층·사람 이름이 들어 있어 `빼기` 로 두지 않았다).
- 계층 칸은 처음 한 번만 적는다(양식 1행 `SUBTOTAL` 이 비어 있지 않은 칸을 센다). 엔진에 병합 쓰기가 없어 견본의 세로 병합은 풀었다.
- Test Case ID 형식은 견본 그대로 `<모듈>.<NN>.<NN>.<NN>`(Task 레벨)·한 자리 더(Task Variant 레벨)다. 견본에서 Mega No 가 모듈 자신(`FI`)이라 숫자가 세 개·네 개다.
- `근거` 는 지도 `md_전용` 열(엑셀에 안 간다). 스코프 아이템 ID·문서 출처·`확인 필요` 를 적는다. List 표 짝(`Test Case ID` ↔ `TC.견본 · <ID>` 소절)은 어느 검사도 안 본다 — 스킬이 산출 전에 알린다.

## 시험
- `test_unittest_skill.py`·`test_form_columns.py`·`test_workflow_source.py`·`test_engine_pin.py`: 162 통과, 6 건너뜀(Windows 파일 이름 `*` 등).
- 실제 양식으로 만든 빈 템플릿과 지도를 임시 루트에 놓고 가짜 LoB(Test Case 2개)를 `checker.export --check`·본 산출: 종료 0. 시트 `Document Control, 단위테스트 List, <ID>×2`, 사람 칸 전부 비어 있음, 견본 흔적(다른 고객 이름·시스템명·FI 계층·로고) 없음, `checker.blank_template` 의 `leftovers` 0.

## 확인 못 한 것
- Excel 에서 열어 보지 못했다(openpyxl 다시 읽기와 zip 검사까지). 견본 5~13행 Process 칸의 병합을 풀며 서식을 이웃 행과 같게 맞췄다.
- 설치된(이전 판) 엔진 훅은 새 규칙 키 `ID_패턴` 과 시트 `반복` 을 몰라 이 판이 배포되기 전에는 Project Repository 에서 작업본 저장이 막힌다.
- 공식 문서(SAP Best Practices Explorer)를 실제로 읽어 초안을 만드는 단계는 아직 실행하지 않았다(SKILL 절차만 정했다).
