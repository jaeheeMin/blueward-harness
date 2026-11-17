# #1060 PR 검사 시험 시간 줄이기 — 병렬 실행 (2026-11-17)

## 배경
PR 검사 시험이 성공 실행 기준 ubuntu 10월 초 1분 미만 → 11월 17일 10~11분, windows 4분 → 25~30분으로 늘었다.
로컬(macOS) 전체 6,158개가 한 줄 실행으로 28분 29초였고, 가장 느린 25개를 합쳐도 약 4분이라 시간은 6천 개에 고르게 퍼져 있었다.
저장소가 공개라 GitHub 러너는 ubuntu·windows 모두 4코어인데 시험은 한 줄로 돌았다.

## 한 것
| 파일 | 내용 |
|---|---|
| `pyproject.toml`, `uv.lock` | dev 의존성에 `pytest-xdist>=3.5`(3.8.0, execnet 2.1.2) |
| `.github/workflows/checker.yml` | 테스트 단계 `uv run pytest -q -rs -n auto --durations=30` |
| `plugins/harness/.claude-plugin/plugin.json` | 0.10.317 → 0.10.320(열린 PR #1050=0.10.318, #1057=0.10.319) |

## 측정 (코드·시험은 그대로, 병렬만 켬. PR #1061 run 44083529976)
| | 한 줄 실행 | 병렬 |
|---|---|---|
| ubuntu 테스트 단계 | 10~11분 | 2.9분(6167 passed, 11 skipped) |
| windows 테스트 단계 | 25~30분 | 8.8분(6170 passed, 8 skipped) |

병렬에서 깨진 시험 0개. 시험 수는 그대로이고 Windows 도 전부 돈다.

## 판단
- 로컬 기본 실행(`uv run pytest`)은 바꾸지 않았다(`addopts` 에 넣지 않음). 시험 하나를 고칠 때 병렬 시작 비용이 더 크다. 전체를 빨리 돌리려면 `uv run pytest -n auto`.
- 배포 파일(pyproject·uv.lock)을 바꿔 판을 올렸다. 엔진 실행(uvx)에는 dev 의존성이 들어가지 않는다.
- whats_new 에는 적지 않았다(팀원이 알 필요 없는 시험 변경).

## 남은 것
- 실제 시간 상한을 기다리는 시험(windows 기준 console_mockup 30s·13s, session_pr_block 23s, plugin_layout 17s, web_console open 11s, risk_gate 10s)은 그대로다. 병렬에서는 다른 시험과 겹쳐 돌아 전체 시간 영향이 작다.
- 가끔 실패한 `test_permission_change_rejects_values_outside_allowed_set`(실행 직후 읽기 타이밍)은 병렬 측정에서는 통과했다. 다시 나오면 따로 고친다.
