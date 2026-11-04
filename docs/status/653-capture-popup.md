# #653 매뉴얼 캡처: 팝업·대화상자 화면 찍기

## 배경

- 준비 단계 뒤나 찍기 직전에 대화상자가 하나라도 보이면 검사 불능이라(오류 창 막기용, #533) 팝업을 열어 찍을 수 없었다.

## 바꾼 것

- `checker/manual_capture.py`: 준비 단계 `{팝업: 버튼 이름}` 추가. 버튼을 누른 뒤 대화상자가 정확히 하나 떠야 하고(안 뜸·둘 이상·오류/경고 창은 검사 불능), 화면의 마지막 준비 단계 하나여야 한다(파싱 때 확인). 팝업 화면은 찍기 직전에도 그 팝업 하나만 허용하고, 표시 요소를 팝업 안에서만 찾는다. 대기(`wait_content`)도 팝업 안 이름을 기다린다. 확인·저장은 누르지 않는다.
- `checker/manual_capture_js.py`: 찾는 범위 뿌리(`setScope`/`clearScope`)와 `dialogInfo`(글·오류 여부: alertdialog·MessageBox·UI5 `getState()` Error/Warning) 추가. 후보 찾기는 범위 뿌리에서만 한다. 겹쳐 붙은 role 은 바깥 대화상자 하나로 센다.
- `plugins/harness/skills/manual/SKILL.md`, `docs/guide/harness-guide.html` 설명 갱신. plugin.json version 0.10.172(main 0.10.170, 열린 PR #669 가 0.10.171).

## 시험

- `checker/tests/test_manual_capture.py`: 파싱(허용·마지막 아님·둘·값 동반 거부), 팝업 성공·안 뜸·둘·오류 창·찍기 직전 다른 창·이미 떠 있음·범위 실패, 팝업 없는 화면은 범위를 안 정함, JS 소스 모양.

## 확인 못 한 것

- 실제 테넌트(UI5)에서의 동작(팝업 안 열 네모, `getState()` 판정). JS 는 가짜 페이지에서 실행되지 않는다.
