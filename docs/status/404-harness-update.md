# #404 플러그인 갱신 스킬 `/harness:update` 와 project 범위 갱신이 다른 폴더를 갱신하는 문제 (2026-10-21)

터미널 없이도 갱신할 수 있게 `/harness:update` 를 추가하고, 갱신 뒤 **현재 폴더 항목의 판**으로 반영을 확인한다. 0.10.99.

## 조사로 확인한 것

- 공식 문서(code.claude.com/docs/en/plugins/cli-reference, /plugins/loading, /plugins/install):
  - `installed_plugins.json` 의 각 항목에 `scope`·`installPath`·`version`, project·local 범위는 `projectPath`(설치가 속한 프로젝트). 캐시는 `cache/<marketplace>/<plugin>/<version>/` 로 **폴더 간에 공유**된다.
  - `claude plugin update` 는 `--scope` 를 생략하면 "현재 프로젝트 기준 가장 구체적 범위"(local→project→user→managed)를 고른다고 되어 있다. 같은 범위 안에서 어느 projectPath 항목을 고르는지는 문서에 없고, **현재 프로젝트를 지정하는 옵션도 없다**(`--help` 에 `-s/--scope`, `--json`, `-y`, `--accept-command` 뿐). 2026-10-21 재현은 이 선택이 틀릴 수 있음을 보인다.
  - 이미 열린 세션은 `/reload-plugins` 전까지 옛 판을 쓴다. `claude plugin update` 는 "이미 최신" 이면 캐시를 바꾸지 않는다.
  - `install` 은 `--scope project` 로 현재 프로젝트에 설치한다(`claude plugin install --help`). 이미 항목이 있을 때 재설치가 판을 올리는지는 문서에 없다.
- 이 PC: `CLAUDE_CONFIG_DIR`(Orca 프로필 home)과 `~/.claude` 모두 같은 구조의 `installed_plugins.json`(version 2)이고 harness 항목이 폴더마다(0.10.94 analyze-plugin-project / 0.10.34 project-repo-layout / 0.10.98 update-project-github / 0.10.96 public-work) 따로 있다. 이슈 본문과 일치. `claude plugin list` 도 같은 항목을 한 줄씩 보인다.
- 갱신 안내 훅 `update_notice.py`: **세션 판**(`CLAUDE_PLUGIN_ROOT/.claude-plugin/plugin.json`)은 이 세션이 실제 올린 판이라 맞다. 틀린 곳은 "새 판을 이미 내려받았다" 판정 — 캐시 폴더 `…/harness/<최신>` 존재만 봐서, **다른 폴더의 설치가 받아 둔 캐시**를 이 폴더가 받은 것으로 읽고 `/reload-plugins` 만 안내했다. `sync` 스킬의 "내려받은 버전"은 이미 현재 projectPath 항목을 읽는다(변경 없음).

## 한 것

- `plugins/harness/hooks/installed_version.py`(새, stdlib): `CLAUDE_CONFIG_DIR`(없으면 `~/.claude`)의 `plugins/installed_plugins.json` 에서 현재 폴더(또는 상위) projectPath 항목의 판을 읽어 `current`·`stale`·`missing`·`unknown`·`unreadable` 로 판정. 경로는 `\`/`/`·끝 구분자·`.`/`..`·(Windows)대소문자를 정규화해 비교. 사용자 범위 항목은 현재 폴더 항목으로 치지 않는다. `--remote` 는 `update_notice` 의 `ls-remote` 로 최신 태그를 얻고, 못 얻으면 `unknown`(최신이라고 하지 않음).
- `plugins/harness/skills/update/SKILL.md`(새): 상태 확인 → marketplace update → update → 현재 폴더 항목 확인 → `stale`/`missing` 이면 `install --scope project` → 재확인 → 그래도 아니면 "갱신 확인 불능"(사유 포함) → `/reload-plugins` 직접 입력 안내. `uninstall` 은 대신 하지 않는다(어느 항목이 지워질지·`.claude/settings.json` 에서 모두의 설정이 빠질지 사람이 정해야 함).
- `update_notice.py`: "이미 새 판" 을 캐시 폴더 존재가 아니라 현재 폴더 항목 판으로 판정(항목을 못 읽거나 없으면 갱신 명령 안내). 안내 문구에 `/harness:update` 추가.
- 시험: `checker/tests/test_installed_version.py`(새), `test_update_notice.py`(캐시만 있고 이 폴더가 옛 판이면 업데이트 안내 등).
- CLAUDE.md 스킬 표, README 스킬 목록·훅 표, 길잡이 "처음 준비하기 › 플러그인 갱신" 과 레일 아래 기준 표기(0.10.99, 2026-10-21), plugin.json 0.10.99.

## 한계

- 실제 `claude plugin update/install` 은 사용자 설치 상태를 바꾸므로 개발 중 돌리지 않았다. 아래는 **실동작 미확인**이다. 병합·설치 뒤 여러 폴더 설치 상태에서 `/harness:update` 를 한 번 시험해야 한다.
  - `update --scope project` 가 항상 다른 폴더를 고르는지, 아니면 일부 조건에서만인지.
  - 이미 (옛 판) 항목이 있는 폴더에서 `install --scope project` 가 판을 올리는지. 안 오르면 스킬은 "갱신 확인 불능" 으로 끝나고 uninstall→install 은 사람이 한다.
  - 하위 폴더에서 부를 때 projectPath 가 저장소 루트가 맞는지(상위 폴더 일치로 처리하지만 Claude Code 가 쓰는 기준 폴더는 확인하지 못했다).
- 길잡이 아티팩트 재게시는 병합 뒤 `docs/guide/README.md` 절차로 한다.
