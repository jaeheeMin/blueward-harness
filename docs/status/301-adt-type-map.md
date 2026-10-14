# #301 활성화 기록에서 MSAG·DEVC 가 닫히지 않는 문제 (2026-10-14)

`createObject` 는 objtype 앞 4글자(`MSAG:<이름>`, `DEVC:<이름>`)로 기록하는데, `activateByName` 의 objectUrl(`/sap/bc/adt/messageclass/<이름>`, `/sap/bc/adt/packages/<이름>`)은 `adt_object_types.json` 에 없어 `URL:<루트>` 키가 되어 기록이 닫히지 않았다. 테스트로 먼저 재현한 뒤(MSAG·DEVC·AUTH·SUSO 가 실패) 표에 `messageclass`→MSAG, `packages`→DEVC 를 넣었다.

URL→유형 표를 `createObject` 로 만들 수 있는 유형 전체와 대조했다. 근거는 이 PC 의 MCP 서버가 쓰는 `abap-adt-api` 의 `build/api/objectcreator.js` `CreatableTypes`(creationPath)이고 SAP 공식 문서가 아니다. 빠져 있던 것은 MSAG·DEVC 외에 `aps/iam/auth`(AUTH), `aps/iam/suso`(SUSO) 였고 같이 넣었다. DDLX·DCLS·DDLA·TABL·DTEL·DOMA·INTF·SRVD·SRVB 등은 이미 표에 있었다. BDEF 는 `CreatableTypes` 에 없어(`createObject` 로 못 만든다) 표의 `bo/behaviordefinitions` 를 그대로 둔다.

같이 고친 것: `createObject` 가 `FUGR` 로 시작하는 모든 objtype 의 `parentName` 을 이름으로 바꿨다. 펑션 그룹(`FUGR/F`)의 `parentName` 은 패키지라서 그룹이 패키지 이름으로 기록되고 `functions/groups/<그룹>` 활성화와 맞지 않았다. `FUGR/FF`·`FUGR/I`(parentName 이 그룹)만 그렇게 하도록 좁혔다.

테스트: `CREATABLE` 표(22 유형)로 생성→`activateByName`→관문 통과를 확인하고, 이름 인코딩(`$TMP_X`→`%24tmp_x`, 네임스페이스 `%2f`)과 `/source/main` 하위 URL 도 같은 키로 모이는지 본다. `test_activation_gate`·`test_mcp_source_guard`·`test_adt_tiers` 267 통과. Plugin version 0.10.64.

결정 — DEVC·MSAG 는 생성 즉시 활성이다(2026-10-14, public-cloud 세션이 080 에서 실측). `createObject` DEVC/K 응답이 `activated:true` 이고 직후 `inactiveObjects` 에 없었다. MSAG/N 도 직후 `inactiveObjects` 에 없었고, `activateByName` 은 "조회 권한이 없습니다" 로 실패했다(활성화 대상이 아님). 그래서 `createObject` 가 이 둘을 `written` 이 아니라 `active` 로 남긴다. 유형 목록은 코드가 아니라 `adt_object_types.json` 의 `created_active` 키(`["DEVC", "MSAG"]`)에 두고 `adt_activation.py` 가 읽는다. 이후 `setObjectSource` 로 쓰면 `written` 으로 돌아가고, messageclass·packages URL 매핑은 `inactiveObjects` 경로에서도 키가 맞아야 해서 그대로 둔다. 다른 유형(CLAS 등)은 여전히 `written`.

미결 — AUTH·SUSO 의 실제 활성화 URL(`aps/iam/*`)은 라이브러리 경로일 뿐 실측하지 못했다.
