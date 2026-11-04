# #656 매뉴얼 캡처: 남은 필터 값 처리와 드롭다운 고르기

## 배경

- 실제 테넌트(DEV-008 캡처)에서 앱이 필터 값(MultiInput 토큰)을 기억해, 같은 값을 `입력` 하면 "유효하지 않은 데이터" 오류 창이 떴다. 드롭다운(Select)을 고르는 단계가 없었다.

## 바꾼 것

- `checker/manual_capture_js.py`: `readInput`(MultiInput 토큰 글자·Input value), `clearInput`(removeAllTokens+fireTokenUpdate, setValue+fireChange), `selectOption`(setSelectedItem+fireSelectionChange·fireChange) 추가. UI5 컨트롤이 없으면 DOM 입력 칸을 읽고 비운다.
- `checker/manual_capture.py`: 준비 단계 `선택: 이름, 값: 항목 글자` 추가. `입력` 은 넣기 전에 지금 값을 읽어, 같은 값(토큰)이면 건너뛰고 다른 값이면 지운 뒤 넣는다. 읽지 못함·지운 뒤에도 남음·항목 없음(사유에 보이는 항목 목록)·드롭다운 아님은 검사 불능. 오류 창 거부는 그대로.
- 모듈 docstring, `plugins/harness/skills/manual/SKILL.md`, 길잡이 `docs/guide/harness-guide.html` 설명 갱신.
- plugin.json version 0.10.169(main 0.10.167, 열린 PR #658 이 0.10.168).

## 시험

- `checker/tests/test_manual_capture.py`: 선택 단계 파싱 허용·거부, 같은 토큰 건너뜀, 다른 토큰 지우고 넣음, 빈 칸, 읽기·지우기 실패, 선택 성공·항목 없음·드롭다운 아님.

## 확인 못 한 것

- 실제 테넌트(UI5)에서의 동작. JS 는 가짜 페이지에서 실행되지 않아 소스 모양만 확인했다.

## 실제 테넌트 시험(11-04, 100)
- DEV-008(생산실적 모니터링) 앱에서 `선택: 생산방식 반복제조` → `입력: 플랜트 4310` → `누르기: 실행` 캡처 성공, 오류 창 없음.
- 플랜트 토큰 글자가 `AutoOne 1공장 (4310)`, 키는 빈 값이었다 → 토큰 끝 `(값)` 과 키도 같은 값으로 보게 고침(첫 실행은 지우고 다시 넣는 길로 갔지만 결과는 같았다).
