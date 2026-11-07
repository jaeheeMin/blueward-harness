# #752 길잡이의 UI5 배포·IAM·카탈로그 안내를 실제 도구 범위에 맞추기 (2026-11-07)

길잡이 "080 에서 Claude 가 하는 일" 문단(`docs/guide/harness-guide.html`)은 "UI5 앱 배포·권한(IAM)·카탈로그는 지금도 사람이 SAP 화면에서 해" 라고 적혀 있었다. 그런데 #313 이후 실제 동작은 다르다.

- 훅이 `deployUi5App`·`undeployUi5App`·`publishBusinessCatalog` 와 `createObject`(SIA6·SIA1·SIA7)를 가로챈다. 이름에 한글이 있는지(CR-001)와 쓰기 금지 테넌트인지를 검사한다(`hooks/mcp_source_guard.py` `_TOOL_NAME_RE`, `hooks.json:44`).
- public-cloud 에서 이 도구들로 BSP → IAM App → Catalog 를 만든 실측 기록도 있다(`docs/status/313-launchpad-tools-guard.md`).

#313 때는 레일 판만 고치고 본문은 그대로 두었다.

## 바뀐 것

- 길잡이 문단을 고쳤다.
  - 080 에서 Claude 가 UI5 배포, IAM App·Catalog 생성, 카탈로그 게시를 MCP 로 할 수 있다고 적었다.
  - 훅이 무엇을 검사하는지(한글 이름, 쓰기 금지 테넌트)와 무엇을 안 보는지(UI5 소스 내용)를 적었다.
  - 사람이 하는 일은 남겼다. Business Role·Space·Page 와 사용자 배정은 관리자가 customizing 테넌트에서 하고, 옮기는 길은 Role 탭을 보라고 했다(#750).
- 배포 파일이 아니라 Plugin version 은 올리지 않는다. 병합 뒤 길잡이 아티팩트를 다시 올린다(`docs/guide/README.md`).
