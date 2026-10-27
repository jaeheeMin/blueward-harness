# #495 UI5 BSP 삭제 도구 undeployUi5App 을 훅 매처에 넣기

## 배경

- public-cloud #418 에서 080 래퍼에 BSP 삭제 도구 `undeployUi5App`(`name`, `parentName`, `confirm`, 선택 `transport`)이 추가된다. 080 전용 쓰기 도구다.

## 결정

- `hooks.json` MCP 매처에 `undeployUi5App` 을 넣어 `mcp_source_guard.py` 의 테넌트 판정(#148)이 돈다. 쓰기 금지 서버면 거절한다.
- 이름 검사(`_DIRECT_NAME_TOOLS`)에 넣어 `name` 을 CR-001 로 본다. 새 이름을 만들지 않지만 한글 등 어긋난 이름의 삭제 시도를 막는다.
- 접두어(Z/Y)·15자 검사는 훅에 없다(엔진 CR-001 은 한글 이름만 본다). 그 검사는 래퍼가 맡는다.
- PostToolUse 활성화 추적(`mcp_activation_tracker`) 대상이 아니다. BSP 삭제는 활성화 대상이 아니다.
- scaffold 의 `env/adt-tiers.example.yaml` write_tools 와 README 한계 절의 도구 수(22개 중 쓰기 14개)를 맞췄다.
- 길잡이(`harness-guide.html`)에는 MCP 도구 이름 목록이 없어 고치지 않았다.
- plugin version 0.10.125.
