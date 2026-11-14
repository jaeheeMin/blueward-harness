# #952 승인을 빨리 누르면 늦게 온 훅이 카드를 또 띄움 (0.10.284)

## 배경
콘솔이 띄운 세션은 같은 도구 승인을 두 경로로 받는다: claude 의 `control_request(can_use_tool)`(바로 옴)와 하네스 `PermissionRequest` 훅(`uv run … hook_post.py`, 몇 초 늦음). 둘 다 대기 중이면 `store.add_request` 가 같은 키로 합쳐 카드 하나가 된다. 실사용 시험 B(11-14)에서 승인을 2~4초 안에 누르면 늦게 온 훅이 이미 답한 요청과 합쳐지지 못해 같은 도구 카드가 한 번 더 떴다(12초 뒤 누르거나 훅이 없으면 한 번).

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/store.py` | `Request.sources`(기다린 경로 "hook"·"control") 를 둔다. `add_request(source=…)` 가 대기 요청이 없을 때, 훅이면 `LATE_JOIN_SECONDS`(30초) 안에 답한 같은 세션·종류·키·제안의 요청 중 control 만 기다린 것(`sources == {"control"}`)에 붙어 그 답을 받는다(새 카드 없음) |
| `plugins/harness/console/hooks_api.py` | 훅 승인은 `source="hook"` |
| `plugins/harness/console/managed.py` | control_request 승인은 `source="control"` |
| `checker/tests/test_web_console.py` | 빨리 답한 뒤 늦은 훅(허락·거부)이 카드 1개로 같은 답, 같은 경로 재요청·제안 다른 훅·짝 없는 훅·30초 지난 훅은 묻기, 훅만 있는 세션은 같은 명령을 다시 물음 |

## 결정
- 늦는 쪽은 훅뿐이라 훅만 받아 간다. control 은 이전 답을 받아 가지 않는다 — 훅만 쓰는 터미널 세션에서 같은 명령을 곧 다시 실행해도 늘 묻는다.
- 요청 하나에 늦은 훅 한 번만 붙는다(붙으면 sources 가 {control, hook} 이 되어 다음 훅은 새 카드).
- 되돌릴 수 없는 일(노랑 카드)도 같은 호출의 늦은 훅이면 사람이 방금 그 호출에 준 답을 돌려준다. 새 승인이 아니라 같은 승인의 두 번째 경로라서다. 다른 호출(같은 경로로 다시 옴)은 노랑 카드로 다시 묻는다.
- 제안(permission_suggestions)이 다르면 합치지 않는 기존 규칙은 그대로다.

## 알려진 한계
- 사람이 답한 뒤 같은 명령의 다른 호출이 control 없이 훅으로만 30초 안에 오면 앞 답을 받는다. 콘솔이 띄운 세션은 승인마다 control_request 가 먼저 오므로 실제로는 생기지 않는다고 본다.
