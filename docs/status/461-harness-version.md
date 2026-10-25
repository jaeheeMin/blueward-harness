# #461 지금 폴더의 플러그인 판을 보여 주는 /harness:version 스킬 (2026-10-25)

## 배경

`claude plugin list` 는 project 범위 harness 가 폴더마다 따로 설치돼 있으면 줄만 여러 개 나와 어느 줄이 지금 폴더 것인지 알 수 없다. 사용자가 개인 스킬로 시험한 "이 폴더 판 표" 를 팀원도 쓰게 harness 에 넣었다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `hooks/installed_version.py` | `--all`(표)·`--json`·`--remote`(harness 만) 모드 추가. 경로 정규화·projectPath 매칭(`find_entries`)은 재사용. 기존 `check`·`--latest`·`--remote` 단일 판정은 그대로 |
| `skills/version/SKILL.md` (신규) | 위 모드를 불러 표를 보여 주고 상태별로 안내. 설치·갱신은 안 함 |
| `skills/update/SKILL.md` | description 에 "판만 보려면 version" 안내 |
| `skills/sync/SKILL.md` | "플러그인 버전 확인" 의 내려받은 판 읽기를 `installed_version.py` 로 바꾸고 전체 표는 version 으로 안내(판정 동작은 유지) |
| `CLAUDE.md`, 두 README, `docs/guide/harness-guide.html` | 스킬 목록·수, 길잡이 "플러그인 갱신" 에 한 줄, 레일 0.10.115 |
| `checker/tests/test_installed_version.py` | 여러 폴더 중 현재 폴더, user+project, 설치 없음, 사본 없음·깨짐·항목 없음 → 확인 불가, 갱신 있음, 원격 판, 표·JSON |

## 결정

- 상태는 최신 / 갱신 있음 / 이 폴더에 설치 없음 / 최신 판 확인 불가. 사본을 못 읽거나 판 문자열을 해석하지 못하면 확인 불가이고 최신이라 하지 않는다(원칙 7).
- 받아 둔 최신 판은 `known_marketplaces.json` 의 installLocation(없으면 `plugins/marketplaces/<이름>`)의 marketplace.json 에서 읽는다. 항목에 version 이 없으면 상대경로 source 의 plugin.json.
- 범위 우선순위: 공식 문서(plugins/loading)는 `enabledPlugins` 켜짐 우선순위(user < project < local)만 밝히고, 같은 플러그인이 두 범위에 설치됐을 때 어느 설치본이 실리는지는 적지 않았다. 그래서 설정 우선순위를 따라 project·local 을 고르고 user 판은 함께 보인다. "확인 못 함" 으로 적었다.
- git 루트는 따로 구하지 않는다. 상위 폴더까지 거슬러 올라가 projectPath 와 맞춰서 저장소 루트 설치도 잡힌다.
- sync 의 "플러그인 버전 확인" 은 지우지 않았다(세션 판 대 main 비교는 sync 끝에 필요). 내려받은 판 읽기만 같은 스크립트로 통일했다.
- 열린 PR #458 이 0.10.114 라서 이 변경은 0.10.115.
