# #952 승인을 빨리 누르면 늦게 온 훅이 카드를 또 띄움 (0.10.284)

## 배경
콘솔이 띄운 세션은 같은 도구 승인을 두 경로로 받는다: claude 의 `control_request(can_use_tool)`(바로 옴)와 하네스 `PermissionRequest` 훅(`uv run … hook_post.py`, 몇 초 늦음). 둘 다 대기 중이면 `store.add_request` 가 같은 키로 합쳐 카드 하나가 된다. 실사용 시험 B(11-14)에서 승인을 2~4초 안에 누르면 늦게 온 훅이 이미 답한 요청과 합쳐지지 못해 같은 도구 카드가 한 번 더 떴다(12초 뒤 누르거나 훅이 없으면 한 번).

## 실측 (11-14, claude `-p --input-format stream-json --permission-prompt-tool stdio`, 콘솔과 같은 띄우기)
- `control_request(can_use_tool)` 에는 `tool_use_id` 가 있다. `PreToolUse` 훅 입력에도 같은 `tool_use_id` 가 있다.
- **`PermissionRequest` 훅 입력에는 `tool_use_id` 가 없다**(`session_id`·`prompt_id`·`tool_name`·`tool_input`·`permission_suggestions` 등). 그래서 훅이 어느 호출의 것인지 id 로 짝지을 수 없다.
- 훅이 아무 답도 내지 않아도 control 쪽 허락으로 도구가 돌았다(파일이 만들어짐).

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/store.py` | `Request.sources`(기다린 경로 "hook"·"control"). `late_hook_after_control()` — `LATE_JOIN_SECONDS`(30초) 안에 답한 같은 세션·종류·키·제안의 요청 중 control 만 기다린 것이 있으면 그 요청에 "hook" 을 적고 True |
| `plugins/harness/console/hooks_api.py` | 콘솔이 띄운 세션의 승인 훅이 위에 걸리면 카드도 답도 없이 빈 응답(200, None). 아니면 지금처럼 카드(`source="hook"`) |
| `plugins/harness/console/managed.py` | control_request 승인은 `source="control"` |
| `checker/tests/test_web_console.py` | 빨리 답한 뒤 늦은 훅(허락·거부)은 빈 응답·카드 1개, 다음 호출의 훅이 그 control 보다 먼저 와도 앞 허락을 받지 않고 control 카드로 묻기(노랑·판정 못 함), 요청마다 한 번·제안 다른 훅·짝 없는 훅·30초 지난 훅은 묻기, 훅만 있는 세션은 같은 명령을 다시 물음 |

## 결정
- 늦은 훅에 앞 답을 넘기지 않고 빈 응답으로 넘긴다. 앞 호출의 훅이면 claude 는 이미 control 답으로 진행했고, 같은 명령의 다음 호출 훅이면 claude 가 그 호출의 control_request 로 넘어가 거기서 카드가 뜬다. 그래서 다른 호출이 앞 허락을 받아 가는 길이 없다.
  - 처음 판은 늦은 훅에 앞 답을 넘겼다. 558 점검이 "A(`rm -rf docs`)를 허용했는데 A 의 훅이 안 오고 같은 명령 B 의 훅이 B 의 control 보다 먼저 오면 B 가 A 의 허락을 받는다" 를 store 로 재현했고, 노랑만 막은 둘째 판도 판정 못 함(`python deploy.py` 등)에 같은 구멍이 남아 빈 응답으로 바꿨다.
- 늦는 쪽은 훅뿐이라 훅만 넘긴다. 훅만 쓰는 터미널 세션(control 없음)은 지금처럼 묻는다.
- control 만 기다린 요청 하나에 늦은 훅 한 번만 넘긴다(넘기면 sources 가 {control, hook}).
- 제안(permission_suggestions)이 다르면 넘기지 않고 묻는다(기존 규칙).

## 알려진 한계
- 앞 호출의 훅이 30초보다 늦게 오면 지금처럼 카드가 한 번 더 뜬다(그 카드는 PostToolUse 가 오면 닫힌다).
