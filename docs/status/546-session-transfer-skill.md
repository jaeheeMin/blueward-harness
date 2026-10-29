# #546 세션 인계 스킬 handoff 추가 (2026-10-29)

- **`/harness:handoff`**(`plugins/harness/skills/handoff/SKILL.md`): 하던 일을 새 세션이 되묻지 않고 이어 가게 인계 파일을 Claude Code 자동 메모리 폴더에 `handoff-YYYY-MM-DD-<영문-요약>.md` 로 저장하고, `MEMORY.md` 에 한 줄을 올리고, 새 세션에 붙여 넣을 짧은 프롬프트를 준다. owner 개인 스킬 `new-session` 의 인계 틀(한 줄 요약 · 지켜야 할 규칙 · 지금까지 · 남은 일 · 도구·경로)과 "되묻지 않아도 되는가" 기준을 가져오고, 앱 전용 도구로 세션을 여는 단계는 뺐다.
- **하는 것 / 하지 않는 것**: 인계할 게 없으면 만들지 않고 묻는다. 같은 일의 이전 인계 파일이 있으면 갱신한다. 비밀은 넣지 않는다. 메모리 폴더를 알 수 없으면 저장을 추측하지 않고 붙여 넣을 인계문을 출력한다. 새 세션 열기와 `/clear` 는 하지 않고 사용자가 한다. 인계 뒤 이 세션은 그 작업을 더 진행하지 않는다.
- **같이 고친 것**: `CLAUDE.md` 스킬 표, `README.md`, `plugins/harness/README.md` 스킬 목록, 길잡이 `harness-guide.html`(작업 닫기 묶음에 "새 세션에 인계하기" 탭과 앞뒤 이동 버튼), `checker/tests/test_plugin_layout.py` 의 스킬 목록 두 곳, `plugin.json` 0.10.140(0.10.139 는 열린 PR #547 이 쓴다).
- **병합 뒤 할 일**: 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
