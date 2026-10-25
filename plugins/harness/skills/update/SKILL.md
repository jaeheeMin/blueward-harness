---
name: update
description: harness 플러그인을 최신 판으로 갱신하고, 이 세션에 실제로 실린 판이 최신인지 확인한다. 사용자가 `/harness:update` 를 입력하거나 "플러그인 갱신해줘", "harness 업데이트해줘", "플러그인 최신으로 맞춰줘" 라고 직접 말할 때만 사용한다. 이럴 땐 쓰지 않는다 — 훅이 갱신을 안내했다는 이유만으로 사용자가 부르지 않았는데 먼저 실행하지 않는다. 저장소의 브랜치·코드를 최신으로 받는 말이면 sync 스킬로, 플러그인 판만 보려는 말("harness 몇 버전이야?", "플러그인 최신이야?")이면 갱신하지 말고 version 스킬로.
compatibility: claude CLI, uv 가 필요하다. 갱신 명령은 사용자가 이 스킬을 부른 경우에만 실행하며, 저장소 파일·브랜치는 바꾸지 않는다.
---

# /harness:update

harness 플러그인을 갱신하는 스킬이다. 데스크톱 앱처럼 터미널이 없는 환경에서 갱신 명령을
대신 쳐 준다. **사용자가 이 스킬을 직접 불렀을 때만** 실행한다(세션 시작·갱신 안내 훅은
알리기만 하고 대신 실행하지 않는다).

## 왜 확인 단계가 따로 있나

project 범위 설치는 **폴더(worktree)마다 항목이 따로** 생긴다(`installed_plugins.json` 의 `projectPath`).
`claude plugin update harness@blueward-harness --scope project` 는 성공했다고 하면서도 **현재 폴더가
아닌 다른 폴더(같은 저장소의 다른 worktree)의 항목을 갱신**한 일이 있다(#404). 그 반대도 일어난다 —
이 세션이 실제로 싣는 판이 현재 폴더 항목이 아니라 다른 worktree 항목의 판이었다(#471). 공식 문서는
worktree 들이 project 설치를 공유한다고만 하고 어느 항목을 고르는지는 적지 않았고, 경로를 지정하는
옵션도 없다. 그래서 "명령이 성공했다" 도, 현재 폴더 항목의 version 도 아니라 **이 세션에 실제로 실린 판**
(`${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` 의 version)으로 판단한다. 설치 항목은 참고로만 쓴다.

## 절차

모든 명령은 갱신하려는 폴더(저장소 루트)에서 Bash 도구로 실행한다. 판 확인은 아래 명령(이하 "판 확인 명령")이
JSON 한 줄을 내고, `state` 가 `current` · `stale` · `unknown` · `unreadable` 중 하나다. 이 스킬 본문의
`${CLAUDE_PLUGIN_ROOT}` 는 스킬이 로드될 때 지금 세션에 실린 판 폴더로 치환된다(Bash 환경변수로는 없다).
Bash 도구는 호출마다 셸 변수를 버리므로 변수에 담아 두지 말고 **매번 이 명령을 그대로** 실행한다.

```bash
uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/installed_version.py" --loaded-root "${CLAUDE_PLUGIN_ROOT}" --remote
```

JSON 의 `loaded` 가 실린 판, `latest` 가 원격 최신 `v*` 태그다. `installed`(현재 폴더 항목의 판),
`other_project_entries`, `same_repo_entries`(같은 저장소의 다른 worktree 항목의 폴더 이름·판)는 참고 정보다.

1. **지금 상태 확인**: `pwd` 로 현재 폴더를 말하고 판 확인 명령을 실행한다. `loaded` 와 `latest` 를 사용자에게
   알린다. 설치 항목이 실린 판과 다르면 참고로 함께 알린다. `state` 에 따라:
   - `current`: **이미 최신이니 여기서 끝낸다**(갱신 명령을 실행하지 않는다). reload 뒤에 다시 불렸을 때도 여기서 끝난다.
   - `unknown`(최신 판을 원격에서 못 읽음): `loaded` 만 알리고 최신인지는 **확인하지 못했다** 고 말한 뒤 멈춘다. 최신이라고 하지 않는다.
   - `unreadable`: 실린 판의 plugin.json 을 읽지 못했다(`loaded_error`). 사유와 함께 알리고 멈춘다.
   - `stale`: **이 대화에서 이미 2~4단계를 실행하고 reload 를 안내했는지 본다.** 이미 했으면(사용자가 reload 했다고
     하거나, 이 대화 앞쪽에 그 실행 기록이 남아 있으면) 갱신 명령을 **다시 실행하지 않고** 곧바로 5단계 "갱신 확인
     불능" 으로 간다. 아직 안 했으면 2단계로 간다. update → reload 를 되풀이하지 않는다.
2. **마켓플레이스 새로고침**: `claude plugin marketplace update blueward-harness`. 출력을 기억해 둔다(5단계에서 인용한다).
3. **갱신**: `claude plugin update harness@blueward-harness --scope project`. 출력의 `(…경로)` 가 현재 폴더와 다르면
   다른 폴더가 갱신된 것일 수 있다. 출력은 참고일 뿐이고 판정은 판 확인 명령으로 한다. 출력을 기억해 둔다 —
   "already at the latest" 같은 문구가 나왔는데 `loaded` 가 `stale` 이면 update 로는 더 할 일이 없다는 근거다.
   "not installed" 류로 실패할 때만 `claude plugin install harness@blueward-harness --scope project` 를 실행한다
   (이미 설치돼 있다고 거부하면 그대로 멈춰 사유를 알린다).
4. **reload 안내**: 갱신 명령은 **이 세션이 실은 판을 바꾸지 못한다.** 에이전트는 슬래시 명령을 칠 수 없으니, 사용자에게
   `/reload-plugins` 를 직접 입력한 뒤 `/harness:update`(또는 `/harness:version`)를 다시 입력해 확인하라고 안내하고
   멈춘다. 그 전까지는 이 세션이 옛 판을 쓴다는 점을 함께 말한다. 안내했다는 사실을 대화에 남긴다(1단계의 반복 차단 근거).
5. **갱신 확인 불능**: 1단계에서 이미 reload 를 안내한 뒤에도 `stale` 이면 멈춘다. 근거를 **명령 출력으로** 그대로 전한다.
   - 사유: `loaded`, `latest`, `installed`, `same_repo_entries`, 앞서 `marketplace update`·`update` 가 낸 출력
     (예: `update` 가 "already at the latest" 인데 `loaded` 는 `stale` → 설치 기록은 최신인데 세션이 다른 판을 싣고
     있다는 뜻), 각 명령의 종료코드와 오류 문구.
   - 안내: 새 세션을 열어 보라고 한다. 통과라고 말하지 않는다.

## 지켜야 할 것

- 갱신·설치 명령은 위 순서의 `marketplace update` · `update` · (필요할 때만) `install` 만 실행한다. 설정 파일 직접 편집,
  `installed_plugins.json` 직접 수정도 하지 않는다.
- **`uninstall` 은 하지 않고 안내하지도 않는다.** uninstall 은 묻지 않고 공유 `.claude/settings.json` 의
  `enabledPlugins` 를 비우므로, 커밋되면 팀원 전체의 harness 가 꺼진다(#471).
- `claude plugin ...` 가 거부되거나 실패하면(훅이 막은 경우 포함) 우회하지 말고 멈춰 사유를 알린다.
- 판을 확인하지 못한 것(`unknown`, `unreadable`)을 "최신" 이나 "갱신 실패" 로 뭉개지 않는다. 확인 불능이라고 말한다.
- `install` 이 `.claude/settings.json` 의 키 순서만 바꿔 저장할 수 있다. 내용(JSON 값)이 같으면 그대로 둬도
  훅이 미커밋으로 세지 않는다. 원하면 `git restore .claude/settings.json` 으로 되돌린다(스킬이 대신 하지 않는다).
  반대로 enabledPlugins 에서 harness 가 빠지거나 꺼진 변경은 git 훅이 커밋·푸시를 거절한다.
- `CLAUDE_CONFIG_DIR` 이 설정돼 있으면(Orca 같은 프로필 환경) 그 아래 `plugins/installed_plugins.json` 을 읽는다.
  스크립트가 알아서 하므로 `~/.claude` 를 직접 읽지 않는다.
