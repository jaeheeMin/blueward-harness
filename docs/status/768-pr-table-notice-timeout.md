# #768 PR 표 첫 프롬프트 훅의 시간 제한을 10초에서 30초로 (2026-11-07)

`UserPromptSubmit` 훅 `pr_table_notice.py` 가 바쁜 PC 에서 "timed out after 10s" 를 냈다. 판은 0.10.221.

## 배경

스크립트가 하는 일은 파일 하나 읽기와 `git rev-parse` 한 번뿐이다. 느린 것은 일이 아니라 프로세스 기동이다.

| 측정 | 시간 |
|---|---|
| 훅 명령 그대로(uv 경유) | 평균 2.4초, 최대 2.9초 |
| `python` 직접 | 0.8초 |
| `uv run --no-project python -c pass` | 1.0초 |

PC 가 바쁘면 이 기동 시간이 몇 배로 늘어 10초를 넘을 수 있다.

## 바꾼 것

- `plugins/harness/hooks/hooks.json`: `pr_table_notice.py` 훅의 `timeout` 10 → 30. 다른 훅은 그대로.
- `plugins/harness/.claude-plugin/plugin.json`: 0.10.221(main·열린 PR 최고가 0.10.220).
- `checker/tests/test_plugin_layout.py`: 이 훅의 timeout 단언을 `<= 10` 에서 `== 30` 으로.

`docs/status/389-session-pr-table-background.md` 의 "timeout 10초" 는 그때의 기록이라 고치지 않았다. 웹 콘솔 `whats_new.json` 은 팀원이 알 변경이 아니라 넣지 않았다(판 키가 없으면 띄우지 않는다). 길잡이에는 이 timeout 이 나오지 않아 그대로다.

## 왜 uv 를 빼지 않았나

`python` 직접이 0.8초로 더 빠르지만, Windows 에는 `python3` 이 없어 훅 명령을 `python3` 으로 쓸 수 없다. 그래서 uv 를 유지한다. 같은 판단이 `docs/status/558-web-console.md` 의 콘솔 훅 측정 표에 이미 있다("`python3 hook_post.py` 직접 … Windows 의 `python3` 부재 때문에 uv 를 유지했다").

## 확인 못 한 것

- 10초를 실제로 넘기는 순간은 재현하지 못했다. 측정은 평소 상태의 값이고, 30초가 충분한지는 쓰다가 같은 오류가 다시 나오는지로 본다.
