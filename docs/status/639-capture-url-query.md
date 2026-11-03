# #639 매뉴얼 캡처 테넌트 주소에 `?sap-client=` 쿼리 허용

## 배경

- `check_base_url` 이 `?` 쿼리를 모두 거부해, 클라이언트를 가려야 하는 테넌트(`?sap-client=100`)를 캡처할 수 없었다.

## 바꾼 것

- `checker/manual_capture.py`: 쿼리는 허용 키만 받는다 — `sap-client`(숫자 3자리), `sap-language`(영문 2자리). 다른 키·값 모양·중복 키·값 없는 키는 거부. `#`·계정 거부는 그대로.
- `compose_url` 은 base + 앱 해시라 쿼리가 그대로 보존된다(`…/ui?sap-client=100#App-display`). `same_site`(https 는 출처만 비교)·`pick_tab` 은 그대로 맞고, file:// 경로 비교만 쿼리를 떼고 비교하게 고쳤다.
- 모듈 docstring, `plugins/harness/skills/manual/SKILL.md`, 길잡이 `docs/guide/harness-guide.html` 의 테넌트 주소 설명에 쿼리 사용법 추가.
- plugin.json version 0.10.165.

## 시험

- `checker/tests/test_manual_capture.py` 에 허용·거부 표, compose 보존, same_site·pick_tab 시험 추가.
