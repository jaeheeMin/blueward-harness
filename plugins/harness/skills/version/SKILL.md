---
name: version
description: 설치된 플러그인(harness 등)이 지금 폴더에서 몇 판인지, 이 세션에 실제로 실린 harness 판이 몇인지, 받아 둔 최신 판과 같은지 표로 보여 준다. 사용자가 `/harness:version` 을 입력하거나 "harness 몇 버전이야?", "플러그인 버전 알려줘", "플러그인 최신이야?", "이 폴더 플러그인 판 보여줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 플러그인을 갱신·설치하는 말이면 update 스킬로(이 스킬은 읽기만 한다), 저장소의 브랜치·코드를 최신으로 받는 말이면 sync 스킬로.
compatibility: uv 가 필요하다. installed_plugins.json 과 marketplace 사본을 읽기만 하며 설치·갱신·파일 변경을 하지 않는다.
---

# /harness:version

`claude plugin list` 는 project 범위 설치가 폴더마다 따로 있으면 줄만 여러 개 나와 **어느 줄이 지금 폴더
것인지** 알 수 없다. 이 스킬은 `installed_plugins.json` 의 `projectPath` 를 지금 폴더(또는 그 상위 폴더,
저장소 루트 포함)와 맞춰 **이 폴더에서 쓰이는 판**을 골라 표로 보여 준다(#461). 읽기만 한다.
harness 의 상태(최신 / 갱신 있음)는 설치 항목이 아니라 **이 세션에 실제로 실린 판**으로 정한다 — 같은 저장소의
worktree 가 여러 개면 세션이 다른 worktree 항목의 판을 싣기도 한다(#471).

## 절차

1. 보려는 폴더에서 Bash 도구로 실행한다. 스킬 본문의 `${CLAUDE_PLUGIN_ROOT}` 는 스킬이 로드될 때 지금 세션에 실린 판
   폴더로 치환된다(Bash 환경변수로는 없다).

   ```bash
   uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/installed_version.py" --all --loaded-root "${CLAUDE_PLUGIN_ROOT}"
   ```

   harness 만 원격 최신 `v*` 태그와도 비교하려면 `--remote` 를 더한다(`git ls-remote`, 5초 제한. 실패하면
   받아 둔 사본의 판으로 대신하고 표에 원격이라고 적히지 않는다). 기계가 읽을 JSON 은 `--json` 을 더한다.
   기본 표는 4칸이고 이 폴더에서 쓰이지 않는 플러그인 줄은 빠진다(harness 는 남는다). 이 폴더 판·다른 폴더 설치까지
   칸 전부와 빠진 줄을 보려면 `--all-entries` 를 더한다. 표 아래에 "자세히 보려면 `--all-entries`" 안내가 있을 때만(갱신 있음이거나
   실린 판을 못 읽었을 때) 더 보여 줄지 묻는다.

2. 나온 표를 그대로 보여 주고 한두 줄로 요약한다. 칸은 플러그인 · 판 · 최신 판 · 상태다. 판은 harness 면 이 세션에 실린 판,
   다른 플러그인은 설치 판이고, harness 의 상태도 실린 판으로 정해진다. `--all-entries` 표는 범위 · 이 폴더 판 · 이 세션에 실린 판 ·
   받아 둔 최신 판 · 상태 · 다른 폴더 설치 칸을 쓴다. "이 폴더 판" 은 설치 항목이라 참고다.
   "다른 폴더 설치" 는 디스크에 있는 폴더만 센다. 같은 저장소의 다른 worktree 항목은 폴더 이름·판이 괄호로 붙는다.
   - **최신**: harness 는 실린 판이, 다른 플러그인은 이 폴더 판이 받아 둔 최신 판과 같거나 높다.
   - **갱신 있음**: harness 면 `/harness:update` 를 안내한다. 이 폴더 설치 항목은 새 판인데 실린 판이 낮다면
     `/reload-plugins` 를 먼저 입력해 보라고 한다. 다른 플러그인은 `claude plugin update <id>` 를 사람이
     치도록 안내한다. 이 스킬이 대신 실행하지 않는다. 갱신 뒤 `/reload-plugins` 를 직접 입력해야 이 세션에 반영된다.
     방금 reload 했다면 "`/reload-plugins` 직후 첫 호출은 옛 판으로 보일 수 있다. 한 번 더 부르면 바로잡힌다" 고 한 줄 덧붙인다(#485).
   - **이 폴더에 설치 없음**: project 범위 플러그인이 이 폴더에 항목이 없다는 뜻이다. 옛 캐시 판이 실릴 수 있다고
     알리고, harness 면 `/harness:update` 가 이 폴더에 설치한다고 안내한다.
   - **최신 판 확인 불가**: 받아 둔 사본을 못 읽었거나 판 문자열을 해석하지 못했다. **최신이라고 말하지 않는다.**
     확인하지 못했다고 말한다.
   - (`--all-entries` 표) 범위 칸에 `(user X 도 있음)` 이 붙으면 project 와 user 에 둘 다 설치돼 있다는 뜻이다. 표의 판은 project 쪽이다.
     어느 설치본이 실제로 실리는지는 공식 문서에 적혀 있지 않아(설정의 켜짐 우선순위만 user < project < local)
     "확인 못 함" 이라고 덧붙인다.
3. 표가 아니라 `확인 불능` 이 나오면(installed_plugins.json 을 못 읽음) 경로와 함께 그대로 알리고 멈춘다.

## 알아 둘 것

- "받아 둔 최신 판" 은 마지막 `claude plugin marketplace update` 때 내려받은 사본의 판이다. 원격 최신과 다를 수 있다.
  원격까지 보고 싶으면 harness 에 한해 `--remote`.
- "이 세션에 실린 판" 은 `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` 의 version 이다. 세션을 연 뒤 갱신했으면
  `/reload-plugins` 를 입력해야 바뀐다. 실린 판을 읽지 못하면 표 아래에 사유가 나오고 harness 상태는 확인 불가다.

## 하지 않는 것

- 설치·갱신·삭제 명령(`claude plugin install/update/uninstall`)을 실행하지 않는다.
- `installed_plugins.json` 이나 설정 파일을 고치지 않는다.
- 읽지 못한 판을 "최신" 이나 "없음" 으로 뭉개지 않는다.
