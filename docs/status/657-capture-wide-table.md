# #657 매뉴얼 캡처의 넓은 표 가로 스크롤 대응 (2026-11-04)

## 문제

실제 테넌트 100(public-cloud DEV-008): 캡처가 `열` 표시마다 `scrollColumn` 으로 그 열을 가운데로 넘겨, 오른쪽 열을 넘기면 먼저 보이던 왼쪽 열이 밀려 `not_found` 가 됐다. 표 보이는 폭 약 1,490px 에서 `상태`(왼쪽)와 `반복생산 확인` 이 5% 차이로 한 화면에 안 들어갔다.

## 바꾼 것

- A 한 번에 넘기기: `window.__mc.scrollColumns([{name,index}])`(`checker/manual_capture_js.py`). 같은 표의 열들의 가로 범위가 표의 보이는 폭 안이면 그 범위가 가운데 오는 위치 하나로 넘긴다. 스크롤 요소는 `.sapUiTableHSb`(scrollLeft), 없으면 overflow-x 가 auto·scroll 인 가장 가까운 조상. 결과 `{ok, fits, span, view, cols:[{name,left,width}]}`. 열이 하나거나 `ok:false` 면 예전 `scrollColumn`.
- B 나누기 제안: `fits:false` 면 찍지 않고 검사 불능. 사유에 필요 폭·보이는 폭, 왼쪽부터 묶은 나누기 제안, 필요 `배율`(5% 단위 내림, 0.5 미만이면 부족하다고)을 적는다(`split_columns`, `wide_reason`).
- C 화면별 `배율`(0.5~1.0): `Emulation.setDeviceMetricsOverride(width=1600/배율, height=900/배율, deviceScaleFactor=배율)`. 그림은 1600x900 유지, 찍기 전 `innerWidth/Height` 가 CSS 크기와 같은지 검사, 덮개(테두리·배지)는 1/배율 로 키워 그림에서 같은 굵기, 화면이 끝나면 원래 크기로 되돌린다.
- 스킬 `manual` 화면 목록 설명, 모듈 docstring, 길잡이 매뉴얼 탭 "캡처 못 하는 것".
- plugin.json 0.10.176(main 0.10.173, 열린 PR #678=0.10.175·#676=0.10.174 — 2026-11-04 확인).

## 시험

`uv run pytest checker/tests/test_manual_capture.py -q`: 161 통과, 1 건너뜀(전체 시험은 돌리지 않음).

## 실제 테넌트로 확인할 것

- `.sapUiTableHSb` 의 `scrollLeft` 를 바꾸면 표 머리글·본문이 따라 움직이는지(UI5 가 scroll 이벤트로 동기화). 열 좌표의 0 기준을 HSb 왼쪽 끝으로 잡았다 — 고정 열이 있으면 어긋날 수 있다.
- `deviceScaleFactor<1` 스크린샷이 정확히 1600x900 인지(반올림), 글자·덮개가 맞는지.
- 열 머리글 `getBoundingClientRect().width` 가 화면 밖 열에서도 실제 폭인지.

## 실제 테넌트 시험(11-04, 100, DEV-008 앱)
- A: `생산버전`+`자재문서`(처음엔 자재문서가 화면 밖) → 한 번 넘겨 둘 다 보이게 찍힘.
- B: `상태`+`반복생산 확인` 필요 1510px > 보이는 1447px → 나누기 제안과 `배율: 0.95` 안내. `상태`+`백로그상태` 2022px → `배율: 0.7` 안내.
- C: `배율: 0.9` 로 `상태`+`반복생산 확인` 한 장, 그림 1600x900 유지, 네모 위치 맞음.
- 시험 중 창이 가려져 "브라우저 응답을 기다리다 시간이 지났다" 가 다시 나왔다(visibilityState=hidden). 원인 안내는 #654(PR #678).
