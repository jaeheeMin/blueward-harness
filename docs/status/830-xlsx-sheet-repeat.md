# #830 xlsx 산출 엔진의 견본 시트 반복 복제 (2026-11-09)

## 무엇을 했나
양식 지도 시트 항목에 `반복: true` 를 두면 그 템플릿 시트를 견본으로 보고, 작업본의 `### <양식> · <견본 이름> · <ID>` 소절마다 시트 하나를 복제해(시트 이름 = ID) 산출한다. 견본 시트와 `빼기: [시트…]` 로 적은 다른 견본 시트는 산출에서 빠진다.

- `checker/sheet_repeat.py`(새 파일) — 지도 검증, 시트 이름 검사(31자·금지 문자 `\ / ? * [ ] :`·작은따옴표 양끝·빈 이름·대소문자 무시 중복), 복제와 workbook.xml·rels·`[Content_Types]`·app.xml·정의된 이름(localSheetId) 정리.
- `checker/export.py` — 템플릿을 읽은 직후 `sheet_repeat.expand` 로 지도·작업본·zip 을 ID 시트로 풀고, 이후는 기존 코드가 그대로 돈다.
- `checker/blank_template.py` — `map_problems` 에 `반복`·`빼기` 검증.
- `checker/rules/form_columns.py` — `견본 · ID` 소절을 견본 항목으로 대조하고 ID 가 시트 이름 규칙을 지키는지 본다.
- `plugins/harness/skills/spec/form-map.md` — "견본 시트 반복" 절.
- 시험: `checker/tests/test_export_sheet_repeat.py`(새 파일), `test_form_columns.py` 에 4건.

## 설계 결정
- 작업본 표지는 파서를 고치지 않고 `견본 · ID` 가 한 덩어리 시트 이름으로 읽히는 것을 이용했다.
- 자유 칸 채우기는 새 `칸:` 키 대신 기존 칸 `형식` 에 `{ID}` 만 더했다. 지도에 `ID` 칸 항목이 있으면 작업본에 안 적어도 ID 로 채운다.
- 시트에 딸린 메모·VML·프린터 설정은 복제본마다 새 파트로 복사한다. drawing·차트·표·피벗이 딸려 있으면 검사 불능(종료코드 2)이다.
- 시트 순서가 바뀌므로 `calcChain` 은 지운다(엑셀이 다시 만든다).

## 시험
- `test_export_sheet_repeat.py`·`test_form_columns.py`·`test_export.py`·`test_blank_template.py`·`test_leftover.py`·`test_form_map.py`: 281 통과.

## 확인 못 한 것
- Excel 에서 열어 보지 못했다(openpyxl 로 다시 읽기와 zip 연결 검사까지). 실제 양식(BW_단위테스트 List)으로 복제 산출해 시트 이름·수식·메모 파트 구성을 확인했다.
- 화면 그림 지난 판 비교는 복제본 이름이 달라 지난 판을 못 찾는다고 알린다(단위테스트 양식은 화면이 없다).

## 실제 양식 확인(메인 세션, 11-09)
- 실제 `BW_단위테스트 List_Lob_v0.1(템플릿).xlsx` 와 임시 지도(견본 `FI.01.03.02.02` 반복, `빼기: [FI.02.03.02]`)로 작업본 Test Case 2개 산출 → 시트 `Document Control, 단위테스트 List, PP.01.01.01.01, PP.01.01.01.02`, A3 제목·단계 행 채움, `COUNTIF` 수식 유지.
- Excel(COM)로 열고 전체 재계산 정상. 템플릿의 깨진 이름 정의(`#REF!`, 사람 이름 포함)는 그대로 남는다 — 빈 양식 정리는 #831 에서.
