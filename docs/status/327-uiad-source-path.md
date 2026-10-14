# #327 UIAD 앱 디스크립터 소스 경로 허용 (2026-10-14)

public-cloud DEV-003 이 080 MCP `setObjectSource` 로 UIAD `ZMM_STOCKLEDGER_APP` 의 JSON 을 쓰려다 `mcp_source_guard.py` 의 판별 불능 거부에 막힌 건이다. SAP 는 호출하지 않았다(경로는 080 실측 결과를 받아 반영).

실측(080): UIAD uri `/sap/bc/adt/fiori/uiad/zmm_stockledger_app`, type `UIAD/TYP`, 소스 `./zmm_stockledger_app/source/main`, 소스 content type `application/json`.

- `hooks/mcp_object_source_map.json`: "비코드 소스" 갈래를 데이터로 추가. 항목은 `suffix`(언어 확장자) 또는 `check: "none"`(코드 검사 없음) 중 정확히 하나를 가진다. 열린 경로는 UIAD 하나뿐이다: `^/sap/bc/adt/fiori/uiad/[A-Za-z0-9_]+/source/main/?\Z`(끝까지 고정, 이름은 영숫자·밑줄만). `suffix_for_url` 은 제어문자·공백이 든 URL 을 판별하지 않는다(urlsplit 이 개행을 떼어 버림). `uipgtyp`·`uisttop` 등은 열지 않았다.
- `hooks/mcp_source_guard.py`: 맵 로더가 항목을 엄격히 읽는다. 모르는 필드, 모르는 `check` 값, suffix 와 check 가 둘 다/하나도 없는 항목은 ValueError 가 되고 `main()` 의 fail-closed 가 거부로 바꾼다(맵 하나가 깨지면 ABAP 쓰기도 통과하지 않는다). `check: none` 이면 `suffix_for_url` 이 `NO_CODE_CHECK` 를 돌려주고, 티어 가드(1단계)는 그대로 거친 뒤 코드 검사 엔진(uvx)을 부르지 않고 allow 한다. 빈 `source` 는 기존대로 먼저 거부한다. 그 밖의 모르는 경로는 지금처럼 판별 불능 거부다.
- `hooks/adt_object_types.json`: collections 에 `fiori/uiad` → `UIAD`. `created_active` 에는 넣지 않았다 — 쓴 뒤 활성화가 필요한지 아직 실측하지 않아 `written` 으로 추적(activateByName/activateObjects/inactiveObjects 로 닫힘)해 fail-closed 로 둔다.

## 실측 뒤 결정

- UIAD `setObjectSource` 직후 `inactiveObjects` 에 나오는지 보고, 나오지 않으면(곧바로 활성) 관문이 불필요하게 푸시를 막지 않도록 `created_active` 처럼 쓰기 후에도 active 로 남기는 방식으로 옮길 수 있다. 지금 `created_active` 는 createObject 기록에만 적용되므로, 옮기려면 그 의미 확장이 필요하다.

## 테스트

`test_mcp_source_guard`(UIAD JSON 이 엔진 없이 통과 = 엔진을 안 부름, 빈 source 거부, uipgtyp·uisttop·하위 다른 경로·`..` 등 비슷한 경로 판별 불능, 100 서버 `writes_allowed: false` 거부와 080 통과, 맵의 모르는 check/필드 거부), `test_activation_gate`(UIAD 쓰기 후 written, activateByName 과 inactiveObjects 로 닫힘).

길잡이: "SAP 에서 개발하기" 탭에 UIAD 한 줄, 레일 harness 0.10.72. README 의 맵 설명 갱신. Plugin version 0.10.70 → 0.10.72(0.10.71 은 다른 세션의 #315 몫).
