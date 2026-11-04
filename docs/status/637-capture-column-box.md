# #637 매뉴얼 캡처 표 열 네모를 본문 칸까지 확장

## 배경
`종류: 열` 네모가 머리글 칸만 감쌌다. UI5 `sap.ui.table` 은 머리글과 본문을 다른 `<table>` 로 그려, 가장 가까운 `<table>`(머리글 표)의 아래 끝을 썼기 때문이다(public-cloud DEV-008 매뉴얼, 100 테넌트에서 재현).

## 바꾼 것
- `checker/manual_capture_js.py` `columnBox`: 바깥 격자(`role=grid` 등)에서 머리글과 같은 `aria-colindex` 의 보이는 본문 칸을 모아 그 아래 끝까지. 칸을 못 모으면 머리글과 본문이 한 표면 그 표, 아니면 바깥 격자의 보이는 아래 끝.
- plugin.json 0.10.170(main 0.10.167, 열린 PR #658 0.10.168, #660 0.10.169).

## 시험
- `uv run pytest checker/tests/test_manual_capture.py -q` 통과.
- 실제 테넌트 100 DEV-008 앱 `상태` 열: 네모가 머리글부터 보이는 마지막 행까지 감싸는 것을 그림으로 확인.
