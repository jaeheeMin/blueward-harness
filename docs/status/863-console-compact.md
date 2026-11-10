# #863 웹 콘솔 기억 요약(요약해서 계속하기) (2026-11-10)

## 배경

기억 90% 배너는 [새 세션으로 넘기기] 와 [계속하기] 뿐이라 앱의 `/compact` 같은 요약이 없었다. `claude -p` 에서 되는지 먼저 쟀다.

## 실측 (pexp/repo 안에서만, haiku `claude-haiku-5-5`, `managed.py` 와 같은 인자, claude 2.1.321)

콘솔 `Manager`(실제 코드)로 세션을 띄우고 3~4턴 쌓은 뒤 `Manager.compact()` 로 보냈다. 두 번 돌려 같은 결과.

| 항목 | 결과 |
|---|---|
| 보내는 것 | user 메시지 `/compact`(stream-json) |
| 받는 순서 | `system/status compacting` → 훅 몇 개(`SessionStart:compact`) → `system/status status:null compact_result:"success"` → `system/init` → `system/compact_boundary`(`compact_metadata`: `trigger:"manual"`, `pre_tokens`, `post_tokens`, `duration_ms`) → `result`(`is_error:false`, `num_turns:0`) |
| 예 | 48,519 → 12,721 토큰, 9.7초 / 48,753 → 12,794 토큰, 10.4초 |
| 화면 상태 | 보낸 직후 `status=running`, `currentAction=Compact`, `compact={state:running}`. 요약 중에 한 번 더 보내면 `busy` 로 거부 |
| 끝난 뒤 | `compact={state:done,pre,post}`, 대화에 "기억을 요약했어 · 48,519 → 12,721 토큰", 기억 칸은 `post_tokens` 로(12,721 · 1%) |
| 다음 답 뒤 | 대화 기록 값으로 돌아옴: 50,031(5%). 즉 `post_tokens` 는 시스템 프롬프트·도구 몫이 빠진 값처럼 보여 요약 직후 %는 낮게 나온다(이유는 확인 못 함, 같은 세션의 pre 값 48,519 는 대화 기록 값 48,498 과 거의 같았다) |
| 실패 모양 | 실제로 실패를 만들지 못했다. `compact_result` 가 `success` 가 아닌 값일 때의 문구·모양은 확인 못 함(시험은 가짜 이벤트로 했다) |
| 정리 | 시험 뒤 `claude-haiku-5-5` 명령줄의 프로세스 없음 확인. 사용자 저장소에선 돌리지 않았다 |

처음 한 번은 출력을 파이프로 받다 420초 안전 종료에 걸려 결과를 못 봤다(두 번째부터 `-u` 와 파일 출력). 한 번은 `/compact` 뒤 다음 턴에서 `api_retry` 만 오고 답이 안 왔다(원인은 확인 못 함, 같은 조건 재시험에선 정상).

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `console/managed.py` | `Manager.compact()`(`/compact` 보내기, 일하는 중·요약 중 거부), `_compact_event`(status·compact_boundary → `s["compact"]`, 대화 `note` 한 줄, 로그), 실패 처리(`compact_result` 가 success 가 아님 · boundary 없이 오류 result · 프로세스 끝남), 신호 없이 끝나면 `unknown` |
| `console/context_usage.py` | 요약 직후 새 답이 오기 전까지 기억 값을 `post_tokens` 로 |
| `console/store.py`, `console/server.py` | 세션 모델에 `compact`, `POST /api/sessions/<id>/compact`(터미널 세션 409) |
| `console/static/app.js`, `flow-logic.js`, `app.css` | 배너와 "자세히 > 기억 요약" 칸의 [요약해서 계속하기](일하는 중·요약 중 비활성), 대화 `note` 줄, "기억을 요약하는 중" 문구 |
| `docs/design/web-console.md`, `docs/guide/harness-guide.html`, `console/whats_new.json`, `plugin.json` | 설명, 판 0.10.260 |
| `checker/tests/test_web_console.py`, `test_web_console_ui.py` | 서버 4개, 화면 1개 |

## 결정

- **터미널 세션은 안내만**: 콘솔이 stdin 을 쥔 세션만 보낼 수 있다. 배너 문구는 그대로.
- **자세히 안에 칸 하나**: 기존 화면에 세션 메뉴가 없어서 "자세히" 안에 "기억 요약" 칸을 더했다(배너가 없는 80% 미만에도 누를 수 있다).
- **일하는 중엔 비활성**: 턴 끝나고 보내는 예약 대신 아예 막았다(누른 결과가 바로 보이게). 턴 도중 stdin 에 `/compact` 를 쌓았을 때의 동작은 실측하지 않았다.
- **자동 요약도 한 줄**: `trigger:"auto"` 의 boundary 도 같은 줄이 남는다(실측 못 함, 같은 모양이라 가정).

## 남은 것

- 실패 이벤트의 실제 모양, 요약 직후 % 가 낮게 나오는 이유, 자동 요약 이벤트는 확인 못 함.
