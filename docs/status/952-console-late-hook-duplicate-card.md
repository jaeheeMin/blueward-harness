# #952 승인을 빨리 누르면 늦게 온 훅이 카드를 또 띄움 (0.10.284)

## 배경
콘솔이 띄운 세션은 같은 도구 승인을 두 경로로 받는다: claude 의 `control_request(can_use_tool)`(바로 옴)와 하네스 `PermissionRequest` 훅(`uv run … hook_post.py`, 몇 초 늦음). 둘 다 대기 중이면 `store.add_request` 가 같은 키로 합쳐 카드 하나가 된다. 실사용 시험 B(11-14)에서 승인을 2~4초 안에 누르면 늦게 온 훅이 이미 답한 요청과 합쳐지지 못해 같은 도구 카드가 한 번 더 떴다(12초 뒤 누르거나 훅이 없으면 한 번).

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/store.py` | `Request.sources`(기다린 경로 "hook"·"control") 를 둔다. `add_request(source=…)` 가 대기 요청이 없을 때, 훅이면 `LATE_JOIN_SECONDS`(30초) 안에 답한 같은 세션·종류·키·제안의 요청 중 control 만 기다린 것(`sources == {"control"}`)에 붙어 그 답을 받는다(새 카드 없음) |
| `plugins/harness/console/hooks_api.py` | 훅 승인은 `source="hook"` |
| `plugins/harness/console/managed.py` | control_request 승인은 `source="control"` |
| `checker/tests/test_web_console.py` | 빨리 답한 뒤 늦은 훅(허락·거부)이 카드 1개로 같은 답, 노랑은 늦게 합치지 않음, 같은 경로 재요청·제안 다른 훅·짝 없는 훅·30초 지난 훅은 묻기, 훅만 있는 세션은 같은 명령을 다시 물음 |

## 결정
- 늦는 쪽은 훅뿐이라 훅만 받아 간다. control 은 이전 답을 받아 가지 않는다 — 훅만 쓰는 터미널 세션에서 같은 명령을 곧 다시 실행해도 늘 묻는다.
- 요청 하나에 늦은 훅 한 번만 붙는다(붙으면 sources 가 {control, hook} 이 되어 다음 훅은 새 카드).
- 되돌릴 수 없는 일(노랑 카드)은 늦게 합치지 않고 늘 묻는다(노랑은 카드가 한 번 더 뜰 수 있다). 훅은 붙는 요청이 자기 호출 것인지 몰라서, A(`rm -rf docs`)를 control 로 허용했는데 A 의 훅이 안 오고 30초 안 같은 명령 B 의 훅이 B control 보다 먼저 오면 B 가 A 의 허락을 받아 카드 없이 실행될 수 있었다(558 점검, store 로 재현). 처음엔 노랑도 재사용했다.
- 제안(permission_suggestions)이 다르면 합치지 않는 기존 규칙은 그대로다.

## 알려진 한계
- 노랑이 아닌 일(판정 못 함)은 위 순서(앞 호출의 훅이 안 오고 다음 호출의 훅이 그 control 보다 먼저 옴)에서 앞 답을 받을 수 있다. 콘솔이 띄운 세션은 control_request 가 바로 오고 훅이 늦으므로 드물고, 되돌릴 수 있는 일이라 받아들였다.
