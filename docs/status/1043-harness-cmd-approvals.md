# #1043 하네스가 스스로 쓰는 읽기 명령에 웹 콘솔이 승인을 묻지 않게 (2026-11-17)

## 배경
스킬 문서는 `e="$(…engine_spec.py)"` 다음 줄에 `uvx --from "$e" …` 를 적는데, AI 가 두 줄을 한 줄로 합치면 `$( )` 때문에 콘솔이 판정하지 못해 승인을 물었다. 인라인 `$( )` 허용으로 넓히면 우회 길이라, 명령 모양 자체를 `$( )` 없는 한 줄로 바꿨다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/hooks/run_engine.py` | 새 래퍼. `uv run --no-project python …/run_engine.py [--timeout 초] <모듈> 인자…` → `engine_spec` 으로 판을 정해 `uvx --from <판> python -P -m checker.<모듈> …` 실행. 종료 코드·출력 그대로. 판을 못 정하거나 uvx 가 없으면 `확인 불능: …` + 종료 2(통과·위반으로 뭉개지 않음), `--timeout` 초과는 124. 모듈은 허용 목록만. 셸 없이 리스트 인자 |
| `plugins/harness/console/risk.py` | `_uv` 가 `engine_module` 스크립트(run_engine)면 모듈 이름으로 `harness_modules` 규칙을 재사용. `irreversible_subcommands`(reserve·claim). `_gh_api_read`(저장소 설정 GET 경로만 safe). `git checkout/switch -b <이름> --no-track [시작점]` safe. `git branch --unset-upstream [이름]` safe |
| `plugins/harness/console/safe_tools.json` | `hooks/run_engine.py`, reserve·claim 사유, `gh_api_read_paths`, `gh_api_jq` |
| 스킬 11개 | `e="$(…)"` + `uvx --from "$e"` 를 run_engine 한 줄로. PowerShell 이중 설명 삭제(한 줄이 둘 다 된다). start 는 `--no-track`, 내 PR 알림은 `timeout 30` 대신 `--timeout 30` |
| `checker/tests/test_run_engine.py` | 래퍼 시험(가짜 uvx) |
| `checker/tests/test_web_console_risk.py` | run_engine·gh api·reserve/claim·`--no-track`·`--unset-upstream` 판정 시험, 스킬 문서 수확 시험 갱신 |
| `docs/guide/harness-guide.html`, `docs/design/web-console.md`, `whats_new.json`, `plugin.json` | 0.10.309 → 0.10.321(#1057 이 0.10.319, #1061 이 0.10.320 이라 main 위로 옮기며 올림) |

## 판단
- 래퍼의 모듈 허용 목록은 스킬이 부르는 모듈 전체(쓰기 모듈 포함)다. 읽기·쓰기 구분은 콘솔 `harness_modules` 가 따로 한다 — run_engine 으로 export 를 불러도 콘솔은 묻는다.
- `timeout` 명령은 Windows 의 `timeout.exe`(대기 명령)와 다르므로 쓰지 않고 래퍼의 `--timeout` 으로 대신한다.
- `--unset-upstream` 원인: `git checkout -b X origin/main` 은 시작점이 원격 추적 브랜치라 upstream 을 `origin/main` 으로 잡는다(autoSetupMerge 기본). `--no-track` 으로 없앤다.

## 못 한 것
- 실제 콘솔·Windows 에서의 한 바퀴(SRS 추가 → PR) 확인은 하지 않았다.
