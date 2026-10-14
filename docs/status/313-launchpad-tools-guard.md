# #313 Launchpad 타일 도구의 훅 검사와 유형 매핑 (2026-10-14)

public-cloud 080 MCP 래퍼 3단계의 새 도구 `deployUi5App`(UI5 BSP 업로드), `publishBusinessCatalog` 와 `createObject` 의 새 유형 SIA6·SIA1·SIA7 에 훅을 맞췄다. SAP 는 호출하지 않았고 모두 실측 전이다.

- `hooks/hooks.json`: mcp_source_guard 의 PreToolUse 매처에 `deployUi5App`, `publishBusinessCatalog` 추가. 서버 접두는 `mcp__.*__` 라 `abap-adt-z5u-dev` 래퍼도 그대로 걸린다.
- `hooks/mcp_source_guard.py`: 도구 이름 정규식에 두 도구를 더하고, `name` 이 바로 문자열인 도구 표(`_DIRECT_NAME_TOOLS`: createObject + 두 도구)로 CR-001 이름 검사를 건다. `deployUi5App` 의 `sourceDir` 는 읽지 않는다(UI5 소스). 티어 가드(`adt_tiers.decide`)는 도구 이름을 코드에 박지 않고 Project Repository 의 `env/adt-tiers.yaml` `write_tools` 만 본다 — 그 yaml 에 두 도구를 적는 것은 public-cloud 쪽 일이다. 하네스 쪽은 scaffold 예시 `env/adt-tiers.example.yaml` 의 `write_tools` 에만 더했다(기본 목록 파일 `mcp_default_tools.json` 은 데이터 도구 전용이라 그대로).
- `hooks/adt_object_types.json`: collections 에 `aps/cloud/iam/sia6|sia1|sia7`. `created_active` 에는 넣지 않았다. 가장 긴 접두 매칭이라 `aps/iam/auth`·`suso` 와 겹치지 않는다(`aps/cloud/iam/...` 은 `aps/iam/...` 과 다른 경로). SIA7 은 생성 시 `name`(`<카탈로그>_000N`), 활성화 시 URL 마지막 마디가 같은 값이라 기록 키(`SIA7:<카탈로그>_000N`)가 양쪽에서 같다.
- 활성화 기록: PostToolUse 매처(`setObjectSource|createObject|deleteObject|activateObjects|activateByName|inactiveObjects`)와 `adt_activation.targets_for` 의 도구 분기는 고정 목록이라 새 두 도구는 기록되지 않는다. 테스트로 고정했다(PostToolUse 매처에 이름이 없음, 직접 불러도 기록 없음).

## 실측 뒤 결정

- `deployUi5App` 이 만드는 BSP·UIAD(`<BSP>_UI5R`)와 `publishBusinessCatalog` 를 활성화 기록 대상으로 둘지: 배포·게시가 곧 활성일 것으로 추정되나 미실측. 넣으면 실측 전에 푸시를 막을 수 있어 넣지 않았다.
- SIA6·SIA1·SIA7 이 `createObject` 만으로 활성인지(`created_active` 등재 여부): 실측 전이라 `written` 으로 둔다.
- SIA7 `createObject` 응답이 실제로 어떤 이름을 돌려주는지, 실제 활성화 URL 이 위 경로인지도 실측 때 확인한다.

## 테스트

`test_mcp_source_guard`(두 도구 영문 통과·한글 CR-001 거절·이름 없음 검사 불능·`sourceDir` 무시), `test_adt_tiers`(쓰기 금지·모르는 서버 거절, 허용 서버에서 CR-001 이어짐, 매처가 두 도구를 잡음), `test_activation_gate`(SIA6·SIA1·SIA7 생성 후 activateByName 으로 닫힘, 접두 매칭, 새 두 도구 기록 안 됨), `test_plugin_layout`(매처 기대값 갱신).

길잡이: MCP 도구 목록이 없어 레일 버전만 harness 0.10.68 로 고쳤다. `plugins/harness/README.md` 의 가로채는 도구 수(19→21개)를 고쳤다. Plugin version 0.10.67 → 0.10.68.

## 실측 뒤 결정 (2026-10-14)

public-cloud 세션이 080 에서 패키지 → deployUi5App → SIA6 → SIA1 → SIA7 → publishBusinessCatalog
순서로 만들며 단계마다 inactiveObjects 를 봤다. BSP·UIAD·SIA6·SIA1·SIA7 모두 한 번도 비활성
목록에 나오지 않았다. 그래서 SIA6·SIA1·SIA7 을 `created_active` 에 넣어 createObject 기록을
처음부터 active 로 남긴다. deployUi5App·publishBusinessCatalog 는 그대로 기록 대상이 아니다
(배포 즉시 활성). 참고: SIA6(EXT) 이름은 `_EXT` 로 끝나야 생성된다 — 래퍼가 미리 막는다.
Plugin 0.10.70(같은 시각 열린 #322 가 0.10.69).
