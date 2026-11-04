# 648 웹 콘솔 세션 기억(context) 사용량 표시

이슈: https://github.com/jaeheeMin/blueward-harness/issues/648 (조사: `docs/status/636-console-design-rest.md` "기억 % 조사")

## 한 일

- 훅 이벤트(`Hooks.handle`)가 입력의 `transcript_path` 를 세션의 `transcriptPath` 로 저장한다. 절대 경로의 `.jsonl` 만 받는다. 터미널 세션과 콘솔 세션이 같은 훅이라 같은 방법이다.
- `plugins/harness/console/context_usage.py`: jsonl 을 256KB 덩어리로 **끝에서 거꾸로** 읽어 마지막 `type: "assistant"` 줄(`isSidechain` 아님, `<synthetic>` 아님, 합이 0 이면 건너뜀)의 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 를 얻는다. 파일의 mtime·크기가 같으면 다시 읽지 않는다. 깨진 줄은 건너뛰고, 읽기 실패·usage 없음·64MB 를 거꾸로 읽어도 없음은 `null`.
- `public_session` 이 `context: {tokens, window, pct}` 를 내린다. 모르는 값은 `null`.
- 화면: 세션 목록 링(% 링 / 토큰 수 점선 링 / `?`), 홈 "내 세션" 표 기억 열, 세션 화면 숫자 띠 "기억" 칸, 갈래가 끝난 뒤 다음 일 카드 문장, 시안 18 배너(90% 이상. [새 세션으로 넘기기] = 지금 갈래를 새 세션에서 이어 가는 기존 인계 `/flow/next` 와 확인 창, [계속하기] = 이 화면을 다시 열 때까지 닫음). 링 색은 80% 초과 노랑, 90% 이상 빨강.

## 창 크기 표와 근거

jsonl 에 창 크기는 없다. 공식 문서 https://code.claude.com/docs/en/model-config (2026-11-04 WebFetch 로 확인) 에 적힌 모델만 쓴다.

| 모델 | 창 크기 | 문서 문장 |
|---|---|---|
| Fable 5 / 5.1 이상, Sonnet 5 이상, Haiku 5.5 이상, Opus 4.7 이상 | 100만 | "Fable 5.1, Fable 5, Sonnet 5 and later, Haiku 5.5, and Opus 4.7 and later run with the 1M window by default, with no `[1m]` suffix needed." |
| Opus 4.6, Sonnet 4.6 | 20만 (`[1m]` 이 이름이나 고른 값에 있으면 100만) | "Opus 4.6 and Sonnet 4.6 reach 1M only through their `[1m]` variant ... a model that reaches 1M only through its `[1m]` variant, such as Opus 4.6, runs at 200K without it." |
| 그 밖(Haiku 4.5, 옛 이름 등) | 모름 → % 없음, 토큰 수만 | 문서 발췌에 없음 |

한계(지어내지 않고 남김)
- 문서 페이지 전체(13만 자)를 두 번에 나눠 읽었다. 문서에도 "`CLAUDE_CODE_DISABLE_1M_CONTEXT=1` 이면 Sonnet 5·Fable 처럼 100만 창 모델도 200K 에서 압축한다" 고 적혀 있다. 세션이 그렇게 떴는지는 훅·jsonl 에서 알 수 없어서, 그런 세션은 %가 실제보다 낮게 나온다.
- 문서는 "모르는 모델 ID(게이트웨이 별칭 등)는 Claude Code 가 200K 로 가정한다" 고 하지만, 그건 Claude Code 안의 가정이라 콘솔은 따르지 않고 %를 비워 토큰 수만 보인다.
- 모델 이름은 마지막 assistant 줄의 `message.model`(없으면 훅의 `model`, 콘솔이 고른 값)에서 읽는다. 이름 형식이 `claude-<계열>-<주>-<부>` 가 아니면 모름으로 둔다.

## 시험

`test_web_console.py` + `test_web_console_ui.py` (끝에서 읽기·큰 파일·sidechain·깨진 줄·usage 없음, 창 크기 표, 훅→세션 `context`, 배너·링 색·토큰만·확인 못 함). 결과 숫자는 PR 본문에 적는다.
