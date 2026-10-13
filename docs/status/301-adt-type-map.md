# #301 활성화 기록에서 MSAG·DEVC 가 닫히지 않는 문제 (2026-10-14)

`createObject` 는 objtype 앞 4글자(`MSAG:<이름>`, `DEVC:<이름>`)로 기록하는데, `activateByName` 의 objectUrl(`/sap/bc/adt/messageclass/<이름>`, `/sap/bc/adt/packages/<이름>`)은 `adt_object_types.json` 에 없어 `URL:<루트>` 키가 되어 기록이 닫히지 않았다. 테스트로 먼저 재현한 뒤(MSAG·DEVC·AUTH·SUSO 가 실패) 표에 `messageclass`→MSAG, `packages`→DEVC 를 넣었다.

URL→유형 표를 `createObject` 로 만들 수 있는 유형 전체와 대조했다. 근거는 이 PC 의 MCP 서버가 쓰는 `abap-adt-api` 의 `build/api/objectcreator.js` `CreatableTypes`(creationPath)이고 SAP 공식 문서가 아니다. 빠져 있던 것은 MSAG·DEVC 외에 `aps/iam/auth`(AUTH), `aps/iam/suso`(SUSO) 였고 같이 넣었다. DDLX·DCLS·DDLA·TABL·DTEL·DOMA·INTF·SRVD·SRVB 등은 이미 표에 있었다. BDEF 는 `CreatableTypes` 에 없어(`createObject` 로 못 만든다) 표의 `bo/behaviordefinitions` 를 그대로 둔다.

같이 고친 것: `createObject` 가 `FUGR` 로 시작하는 모든 objtype 의 `parentName` 을 이름으로 바꿨다. 펑션 그룹(`FUGR/F`)의 `parentName` 은 패키지라서 그룹이 패키지 이름으로 기록되고 `functions/groups/<그룹>` 활성화와 맞지 않았다. `FUGR/FF`·`FUGR/I`(parentName 이 그룹)만 그렇게 하도록 좁혔다.

테스트: `CREATABLE` 표(22 유형)로 생성→`activateByName`→관문 통과를 확인하고, 이름 인코딩(`$TMP_X`→`%24tmp_x`, 네임스페이스 `%2f`)과 `/source/main` 하위 URL 도 같은 키로 모이는지 본다. `test_activation_gate`·`test_mcp_source_guard`·`test_adt_tiers` 264 통과. Plugin version 0.10.64.

미결 — 패키지(DEVC)는 생성 즉시 활성이라 기록을 `written` 이 아닌 `active` 로 남겨야 하는지는 공식 근거를 찾지 못해 바꾸지 않았다. 지금은 `written` 으로 남고 `activateByName` 으로 닫힌다. public-cloud 세션이 실제 테넌트에서 패키지 생성 직후 `inactiveObjects` 로 패키지가 비활성 목록에 나오는지 확인해야 한다. 안 나오면 생성 직후에도 push 가 막히는 불편이 있으니 그때 `DEVC` 생성은 `active` 로 남기도록 고친다. MSAG 와 AUTH·SUSO 의 실제 활성화 URL(`messageclass`·`aps/iam/*`)도 라이브러리 경로일 뿐 실측하지 못했다.
