# #650 웹 콘솔에 훅이 막은 이유 보이기

하네스 훅이 도구 호출을 막아도 콘솔에는 그 이유가 보이지 않았다. 시안 16 의 "✕ 막힘" 카드로 세션 대화에 보인다.

## 공식 문서 근거

PreToolUse 훅이 exit 2 나 `permissionDecision: deny` 로 막은 호출에는 PostToolUseFailure·PermissionDenied 같은 다른 훅 이벤트가 뜨지 않고, 한 훅은 다른 훅의 결과를 볼 수 없다
(https://code.claude.com/docs/en/hooks). 그래서 콘솔이 이벤트로 알아챌 길이 없고, **막는 훅이 막을 때 직접 콘솔로 보낸다.**

## 바꾼 것

- 보내는 쪽 `plugins/harness/hooks/console_block.py`(새): `report(payload, hook, reason)`. `127.0.0.1:<HARNESS_CONSOLE_PORT 또는 4873>/hooks/blocked` 로 POST
  (본문: `hook_event_name: "HarnessBlocked"`, hook, reason, session_id·tool_use_id·tool_name·cwd). 연결 0.5초, 전체 약 1.5초 안에 포기(별도 스레드에서 보내고 join).
  모든 예외를 삼키고 stdout·stderr 에 쓰지 않는다. session_id 가 없으면 보내지 않는다. CLI: `python console_block.py <훅 이름>`, 훅 입력 JSON 은 stdin, 사유는 환경변수 `HARNESS_BLOCK_REASON`.
- 막는 훅별로 넣은 곳(판정 JSON 을 낸 뒤에 보고 → 종료코드·stdout 은 그대로)
  - `pre-bash-git-guard.sh`: `deny()` 와, 직접 JSON 을 내는 두 곳(enabledPlugins 검사, 활성화 관문)이 `report_block()` 을 부른다. 입력에 `"session_id"` 가 없으면 python 을 띄우지 않는다.
  - `stop-deliver.sh` 는 보내지 않는다(검토 뒤 뺐다): 커밋 안 된 변경 알림은 오류가 아니라 안내인데, 서브에이전트가 일하는 동안 턴마다 빨간 막힘 카드가 쌓였다.
  - bash 쪽 `timeout` 은 `timeout --version` 이 될 때(GNU)만 쓴다. Windows 기본 `timeout.exe` 가 잡히면 보고가 조용히 사라지던 것을 막는다.
  - `pre_write_guard.py`, `agent_delegation_guard.py`, `mcp_source_guard.py`: 각 `deny()` 끝에서 `console_block.report(_PAYLOAD, ...)`. `_PAYLOAD` 는 `_main` 이 입력을 읽은 뒤 기억한다(JSON 을 못 읽은 경우는 payload 가 없어 보내지 않는다).
  - 보내지 않은 것: `subagent_edit_guard.py`(#690 에서 따로), `mcp_source_guard.py` 의 `ask`(막는 게 아니라 되묻기), `adt_tiers.py`(판정 함수만 있고 막는 출구는 mcp_source_guard 의 deny), `mcp_activation_tracker.py`(PostToolUse 라 이미 끝난 호출을 막지 못한다), `activation_gate.py`·`enabled_plugin_guard.py`(출력이 pre-bash-git-guard 의 deny 로 들어가 거기서 한 번 보낸다).
- 서버 `console/hooks_api.py`: `/hooks/blocked` → `Hooks.blocked()`. 그 세션 `chat` 에 `{"role": "block", hook, kind, text(사유 원문), fix("다음:" 뒤), tool}` 을 더한다.
  `kind` 는 `block_kind()`: 사유에서 `다음:`·`사유:`·`자세히:` 앞부분만 보고(뒤는 고치는 법·도구 출력이라 섞이면 오판), `검사 불능`·`확인하지 못`·`확인되지 않는 상태`·`알 수 없`·`읽지 못` 등이 있으면 `cannot_check`, 아니면 `blocked`. 실제 훅 사유 80여 개(bash deny 문구, python deny 의 AST 로 이은 문구)에 대입해 맞췄다. 바로 앞 항목과 role·글이 같으면 `add_chat` 이 쌓지 않는다. 모르는 세션도 다른 훅 이벤트처럼 `ensure` 로 만든다. 사유가 비면 400.
- 화면 `console/static/app.js`: `chatBlock()`. blocked → 빨간 `✕ 막힘`(`.q.blocked`, `.tagx.fail`), cannot_check → 보라 점선 `? 확인 못 함`(`.q.unsure`, `.tagx.unk`) — 기존 CSS 재사용. 제목 "하네스 검사가 막았어 · 훅 이름" / "검사를 못 해서 멈췄어 · 훅 이름"(`HOOK_NAMES` 표, 모르면 원래 이름). 본문은 첫 문장만 크게, 나머지는 `전체 보기` 로 접기. `고치는 법` 줄에 fix.
  `s.canSend === true` 면 "그렇게 고쳐 줘" 버튼 → `sendFollow('하네스 훅이 막은 이유대로 고쳐 줘: <첫 문장>\n고치는 법: <fix>')`(`sendFollow` 가 글을 인자로 받도록 넓힘, 입력칸은 건드리지 않는다).

## 시험

- `checker/tests/test_console_block.py`(새): 콘솔 없음·포트 오류·느린 서버에서 예외 없이 빨리 끝나고 무출력, 본문 필드, CLI, agent_delegation_guard·pre_write_guard·pre-bash-git-guard 가 막을 때 보고가 나가고(stop-deliver 는 보고하지 않음) (종료코드, stdout, stderr) 가 콘솔 있을 때와 없을 때 같음, 허용할 땐 보고 없음.
- `test_web_console.py`: blocked 보고→chat 항목·fix, kind 판정 여섯 낱말, 중복, 사유·세션 없음 400.
- `test_web_console_ui.py`: 카드 두 종류, 첫 문장만 보임, 고치는 법, 버튼 유무, 모르는 훅 이름.

## 남은 것

- 크롬 확인: sandbox 세션에 보고 두 건(막힘·검사 불능)을 CLI 로 보내 두 카드가 대화 안에 뜨는 것을 봤다. 실제 훅이 막아서 뜨는 것은 이 판이 설치된 뒤에 볼 수 있다(지금 세션 훅은 설치본 0.10.174).
- 시험은 "콘솔 있음 대 닫힌 포트" 를 비교한다. 보고 코드가 없던 옛 판과 직접 비교하지는 않는다(검토 지적, 남겨 둠).
- 버튼 클릭은 가짜 DOM 시험이 보지 않는다.
- bash 훅은 막을 때마다 `uv run python` 을 한 번 더 띄운다(콘솔 세션이면 약 0.3초 안팎, 최대 5초 제한).
