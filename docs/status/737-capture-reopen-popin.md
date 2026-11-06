# #737·#738 매뉴얼 캡처 다시 열기 앱 안 경로와 접힌 열 안내

## 배경
public-cloud DEV-006 매뉴얼 캡처(100 테넌트, v0.10.186)에서 나온 두 가지(plugin-help 세션 보고).
- #737: 상세 화면(`#App-manage&/Entity(...)`)을 찍은 뒤 다음 목록 화면을 강제로 다시 열어도 앱 안 경로가 남아 이름을 못 찾았고, 사유는 "--timeout 을 늘려라" 로 엉뚱했다.
- #738: 응답형 표가 폭이 모자라 접은(pop-in) 열은 `열` 로 "찾지 못했다(후보 0)" 만 나왔다.

## 바꾼 것
- `checker/manual_capture.py` `navigate`: 다시 연 뒤 해시가 화면 목록 `앱` 과 다르면(`route_ok` — `&/`, `&/?sap-iapp-state=…` 는 같은 화면) `location.hash` 를 맞추고 다시 기다린다. 그래도 다르면 지금·기대 경로를 적어 검사 불능.
- `locate`: `열` 후보 0 인데 같은 이름의 pop-in 라벨(`.sapMListTblSubCntHdr`)이 있으면 "접힌(pop-in) 열이다 — `그 밖` 으로 찾거나 `배율:`" 안내.
- plugin.json 0.10.197(열린 PR #730 0.10.195, #728 0.10.196).

## 시험
- `uv run pytest checker/tests/test_manual_capture.py -q` 173 통과·1 건너뜀(route_ok 표, 경로 맞추기 성공·실패, 접힌 열 안내).
- 실제 테넌트로는 이 PR 을 돌리지 않았다. #737 의 해법(location.hash 를 목록으로)은 plugin-help 세션이 DEV-006 에서 손으로 확인했다.
