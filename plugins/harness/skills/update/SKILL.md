---
name: update
description: harness 플러그인을 최신 판으로 갱신하고, 현재 폴더에 실제로 반영됐는지 확인한다. 사용자가 `/harness:update` 를 입력하거나 "플러그인 갱신해줘", "harness 업데이트해줘", "플러그인 최신으로 맞춰줘" 라고 직접 말할 때만 사용한다. 이럴 땐 쓰지 않는다 — 훅이 갱신을 안내했다는 이유만으로 사용자가 부르지 않았는데 먼저 실행하지 않는다. 저장소의 브랜치·코드를 최신으로 받는 말이면 sync 스킬로, 플러그인 판만 보려는 말("harness 몇 버전이야?", "플러그인 최신이야?")이면 갱신하지 말고 version 스킬로.
compatibility: claude CLI, uv 가 필요하다. 갱신 명령은 사용자가 이 스킬을 부른 경우에만 실행하며, 저장소 파일·브랜치는 바꾸지 않는다.
---

# /harness:update

harness 플러그인을 갱신하는 스킬이다. 데스크톱 앱처럼 터미널이 없는 환경에서 갱신 명령을
대신 쳐 준다. **사용자가 이 스킬을 직접 불렀을 때만** 실행한다(세션 시작·갱신 안내 훅은
알리기만 하고 대신 실행하지 않는다).

## 왜 확인 단계가 따로 있나

project 범위 설치는 **폴더마다 항목이 따로** 생긴다(`installed_plugins.json` 의 `projectPath`).
`claude plugin update harness@blueward-harness --scope project` 는 성공했다고 하면서도 **현재 폴더가
아닌 다른 폴더의 항목을 갱신**한 일이 있다(2026-10-21, #404). 또 현재 폴더에 항목이 아예 없으면 옛 캐시
판이 계속 실리고 `update` 는 "이미 최신" 이라고만 한다. 그래서 "명령이 성공했다" 가 아니라
**현재 폴더 항목의 version** 으로 판단한다.

## 절차

모든 명령은 갱신하려는 폴더(저장소 루트)에서 Bash 도구로 실행한다. `<이 스킬의 base directory>` 는 이 스킬이
로드될 때 위에 표시되는 경로다. 판 확인은 아래 명령(이하 "판 확인 명령")이 JSON 한 줄을 내고, `state` 가
`current` · `stale` · `missing` · `unknown` · `unreadable` 중 하나다. Bash 도구는 호출마다 셸 변수를 버리므로
변수에 담아 두지 말고 **매번 이 명령을 그대로** 실행한다.

```bash
uv run --no-project python "<이 스킬의 base directory>/../../hooks/installed_version.py" --remote
```

1. **지금 상태 확인**: `pwd` 로 현재 폴더를 말하고 판 확인 명령을 실행한다. `installed`(현재 폴더 항목의 판),
   `latest`(원격 최신 `v*` 태그), `project_path`, `other_project_entries`(다른 폴더 항목 수)를 사용자에게 알린다.
   `state` 가 `current` 이면 이미 최신이니 6단계(`/reload-plugins` 안내)로 간다. 이 세션이 실제로 쓰는 판은
   `<이 스킬의 base directory>/../../.claude-plugin/plugin.json` 의 version 이다 — 설치 판과 다르면 갱신됐어도 reload 가 필요하다.
2. **마켓플레이스 새로고침**: `claude plugin marketplace update blueward-harness`
3. **갱신**: `claude plugin update harness@blueward-harness --scope project`. 출력의 `(…경로)` 가 현재 폴더와 다르면
   다른 폴더가 갱신된 것이니 성공으로 치지 않는다. 출력은 참고일 뿐이고 판정은 4단계로 한다.
4. **현재 폴더 항목 확인**: 판 확인 명령을 다시 실행한다.
   - `current`: 6단계로.
   - `stale` 또는 `missing`: 현재 폴더에 설치를 다시 한다 — `claude plugin install harness@blueward-harness --scope project`.
     그 뒤 판 확인 명령으로 다시 확인한다.
   - `unknown`(최신 판을 원격에서 못 읽음): `installed` 만 알리고 최신인지는 **확인하지 못했다** 고 말한다.
     최신이라고 하지 않는다. `claude plugin list` 로 이 폴더 줄의 판을 직접 보라고 안내한다.
   - `unreadable`: `config_file` 경로와 함께 읽지 못했다고 알린다.
5. **그래도 못 맞추면 "갱신 확인 불능"**: 설치 뒤에도 `current` 가 아니면 멈춘다. 아래를 그대로 전하고 통과라고
   말하지 않는다.
   - 사유(`state`, `installed`, `latest`, 각 명령의 종료코드와 오류 문구).
   - 사용자가 직접 할 수 있는 길: 터미널의 해당 폴더에서 `claude plugin list` 로 판을 확인하고, 그래도 안 맞으면
     `claude plugin uninstall harness@blueward-harness --scope project` 뒤 다시 `install`. **uninstall 은 이 스킬이
     대신 하지 않는다** — 어느 폴더 항목이 지워질지, 저장소의 `.claude/settings.json` 에서 모두의 설정이 빠질지
     (Claude Code 가 "Disable for me / Uninstall for everyone" 을 묻는다) 사람이 보고 정해야 한다.
6. **마무리 안내**: `current` 로 확인됐으면 "이 폴더 항목이 X 판이 됐다" 고 알리고, **`/reload-plugins` 를 직접
   입력하라** 고 안내한다(에이전트는 슬래시 명령을 칠 수 없다). 입력 뒤에도 세션 판이 그대로면 새 세션을 열라고 한다.
   `/reload-plugins` 를 입력하기 전까지는 이 세션이 옛 판을 쓴다는 점을 함께 말한다.

## 지켜야 할 것

- 갱신·설치 명령은 위 순서의 `marketplace update` · `update` · `install` 만 실행한다. `uninstall`, 설정 파일 직접 편집,
  `installed_plugins.json` 직접 수정은 하지 않는다.
- `claude plugin ...` 가 거부되거나 실패하면(훅이 막은 경우 포함) 우회하지 말고 멈춰 사유를 알린다.
- 판을 확인하지 못한 것(`unknown`, `unreadable`)을 "최신" 이나 "갱신 실패" 로 뭉개지 않는다. 확인 불능이라고 말한다.
- `install` 이 `.claude/settings.json` 의 키 순서만 바꿔 저장할 수 있다. 내용(JSON 값)이 같으면 그대로 둬도
  훅이 미커밋으로 세지 않는다. 원하면 `git restore .claude/settings.json` 으로 되돌린다(스킬이 대신 하지 않는다).
- `CLAUDE_CONFIG_DIR` 이 설정돼 있으면(Orca 같은 프로필 환경) 그 아래 `plugins/installed_plugins.json` 을 읽는다.
  스크립트가 알아서 하므로 `~/.claude` 를 직접 읽지 않는다.
