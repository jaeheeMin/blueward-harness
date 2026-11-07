# #765 콘솔에 막힘을 알리지 않던 훅 넷 알리기

#650 에서 pre_write_guard·mcp_source_guard·agent_delegation_guard·pre-bash-git-guard 만 막힘을 콘솔로 보냈다. 나머지가 막아도 팀원은 Claude 가 멈춘 이유를 콘솔에서 볼 수 없었다.
기존 방식(`hooks/console_block.py` 의 `report`, 서버 `/hooks/blocked`, 사유로 가르는 `block_kind`)을 그대로 따랐다. 새 서버 API·화면 코드는 없다.

## 바꾼 것

- `subagent_edit_guard.py`: SubagentStop 이 `{"decision":"block"}` 을 낸 뒤 `console_block.report(payload, "subagent_edit_guard", reason)`. 통과·경고(`systemMessage`)는 보내지 않는다. 사유에 `다음:` 이 없어 고치는 법 줄은 비고 `✕ 막힘` 으로 뜬다.
- `stop-deliver.sh`: `pre-bash-git-guard.sh` 와 같은 `report_block()`(uv 있을 때만, GNU timeout 일 때만 5초 제한)을 더해 block JSON 을 낸 뒤 부른다(jq 있음·없음 두 갈래 모두). `stop_hook_active` 로 다시 들어온 경고(막지 않음)는 보내지 않는다. `hook_dir` 는 cd 하기 전에 잡는다.
- `mcp_activation_tracker.py`: 실패해 exit 2 로 끝낼 때(`_fail`) 알린다. 이미 끝난 호출이라 막은 것이 아니라 활성화 상태를 확인하지 못한 것이므로 사유를 "확인하지 못했다" 로 써서 `? 확인 못 함` 카드가 되게 했다(`다음:` 뒤는 고치는 법). 훅 입력 JSON 을 못 읽은 경우는 세션 id 가 없어 보내지 않는다.
- `hooks.json` 의 "uv 없음" 폴백 넷(pre_write_guard·agent_delegation_guard·mcp_source_guard 의 `|| { echo …; exit 2; }`, mcp_activation_tracker 의 마지막 `hook-not-run` 갈래): 폴백이 훅 입력을 볼 수 있게 `input="$(cat)"` 로 먼저 받아 훅에 넘기고, 폴백에서 새 `hooks/console-block-nouv.sh` 로 보낸다. uv 가 없어 python 을 못 띄우므로 bash `/dev/tcp` 로 같은 주소·같은 본문을 보낸다(Windows Git Bash 에서 확인). 사유가 "검사하지 못했다/확인하지 못했다" 라 `? 확인 못 함` 카드가 된다(검사 불능을 막힘으로 뭉개지 않음, CLAUDE.md 7번). 폴백의 stderr 문구·종료코드 2 는 그대로.
- `plugin.json` version 0.10.211. 길잡이 `docs/guide/harness-guide.html` 의 작업 화면 항목(막힘 카드가 뜨는 훅, 마무리 확인도 카드로). `docs/design/web-console.md` 에 알리는 훅 목록.

## 시험

- `checker/tests/test_hook_block_cards.py`(새): 진짜 콘솔 서버(Console 픽스처)를 띄우고 훅을 실제로 돌려 세션 대화에 카드 항목이 쌓이는지 본다 — subagent_edit_guard(blocked, 콘솔 꺼짐/켜짐 출력 동일), stop-deliver(blocked), mcp_activation_tracker(cannot_check, 종료 2), uv 없음 폴백 넷(PATH 에서 uv 를 뺀 bash 로 hooks.json 명령 그대로 실행, cannot_check, 종료 2, 콘솔 꺼짐/켜짐 출력 동일). 통과·정상·세션 id 없음에서는 보내지 않는 것도 본다. 카드가 화면에 그려지는 것은 기존 `test_web_console_ui.py::test_chat_draws_hook_block_cards_two_kinds_and_fix_button` 이 본다.
- `test_console_block.py`: `stop-deliver` 가 이제 알리므로 "알리지 않음" 시험을 "알리고 출력은 그대로" 로 바꿨다.

## 남은 것

- stop-deliver 는 #650 에서 일부러 뺐다(커밋 안 된 변경 알림은 오류가 아니라 안내인데 서브에이전트가 일하는 동안 턴마다 빨간 카드가 쌓임). 이 이슈가 알리라고 해서 넣었다. 카드가 너무 쌓이면 되돌리거나 같은 사유를 한 번만 보이게 줄일 일이다(서버는 바로 앞 항목과 같으면 쌓지 않는다).
- SubagentStart/Stop/record 의 "uv 없음" `systemMessage` 폴백 셋은 막는 것이 아니라 경고라 알리지 않았다(Edit/Write 마다 도는 훅이라 uv 가 없으면 카드가 쌓인다).
- subagent_edit_guard 의 "확인 못 함" 경고(`warn`)는 사용자 화면 메시지와 메인 모델 주입으로만 가고 콘솔 카드는 아니다.
- 실제 Claude Code 가 막은 세션에서 크롬으로 보는 확인은 이 판이 설치된 뒤에 가능하다(시험은 훅을 직접 돌리고 콘솔 API 의 대화를 본다).

## 메인 검토에서 고친 것 (2026-11-08)

- `hooks.json` uv 없음 폴백 셋(pre_write_guard·agent_delegation_guard·mcp_source_guard)에서 `echo` 뒤 띄어쓰기가 빠져(`echo\"…`) 안내 문구 대신 command not found 가 나가던 것을 고쳤다. 시험은 그 오류 문구 안에도 `winget install` 이 들어 있어 통과했었다 — 안내 줄이 `doc-guard:`·`harness:` 로 시작하는 한 줄로 나오는지 보도록 시험을 바꿨다.
