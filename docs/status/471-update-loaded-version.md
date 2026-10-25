# #471 worktree 가 여러 개일 때 /harness:update 판정을 실제로 실린 판으로 바꾸고 uninstall 위험 막기 (2026-10-26)

## 재현

같은 저장소의 worktree 마다 `installed_plugins.json` 에 project 범위 항목이 따로 있는 환경(work1 ~ work5 처럼 5개)에서 work2 에 붙은 세션으로 시험했다.

| 단계 | 결과 |
|---|---|
| 설치 항목 | work2 는 옛 판, work3 는 0.10.115(최신). 나머지도 따로 있음 |
| work2 에서 `claude plugin update harness@blueward-harness --scope project` | work2 가 아니라 work3 항목을 골라 "already at the latest (0.10.115)" 라고 답했다. work2 항목은 그대로 옛 판 |
| work2 에서 `claude plugin install ... --scope project` | "already installed" 로 거부 |
| `/reload-plugins` 뒤 work2 세션 | 0.10.115 에만 있는 스킬이 생겼다 — 세션이 work3 항목의 판을 실었다 |
| 옛 `installed_version.py` | work2 항목(옛 판)만 봐서 "갱신 있음(stale)" 이라 판정 — 실제로는 최신이라 거짓 stale |
| 옛 스킬 5단계의 `uninstall → install` 수동 안내를 따름 | 묻는 창 없이 공유 `.claude/settings.json` 의 `enabledPlugins` 가 `{}` 로 비워졌다. 커밋됐다면 팀원 전체의 harness 가 꺼진다 |

세션이 실제로 싣는 판은 스킬 본문의 `${CLAUDE_PLUGIN_ROOT}` 가 치환된 폴더(`cache/blueward-harness/harness/<version>`)로 확인했다(Bash 환경변수로는 없고 스킬 본문에서만 치환된다. 훅 명령에는 환경변수 `CLAUDE_PLUGIN_ROOT` 가 있다).

## 공식 문서 근거

- worktree: https://code.claude.com/docs/en/worktrees.md#what-worktrees-share-with-the-main-checkout — project 범위로 설치한 플러그인은 같은 저장소의 worktree 에서도 실린다고만 한다. worktree 별 항목이 여럿일 때 어느 것을 고르는지는 적혀 있지 않다.
- CLI 레퍼런스: https://code.claude.com/docs/en/plugins/cli-reference.md — `plugin update`·`install` 에 projectPath 를 지정하는 옵션이 없다.
- 로딩: https://code.claude.com/docs/en/plugins/loading.md — 실리는 판의 선택 규칙이 없다.

그래서 어느 항목이 고르는지는 동작으로만 알 수 있고 기대할 수 없다. 판정은 항목이 아니라 실제로 실린 판으로 한다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `hooks/installed_version.py` | `--loaded-root DIR` 추가. DIR 의 plugin.json version 을 `loaded` 로 내고 state 를 loaded 와 latest 비교로 정한다(못 읽으면 `unreadable` + `loaded_error`). cwd 항목(`installed`, `other_project_entries`)과 같은 저장소(git common dir 이 같음) 다른 worktree 항목(`same_repo_entries`: 끝 폴더 이름·판)은 참고 필드. `--loaded-root` 없는 호출은 그대로 |
| `hooks/installed_version.py --all` | 표에 "이 세션에 실린 판" 칸, harness 행 상태는 실린 판 기준. 이 폴더에서 쓰이지 않는 플러그인 줄은 기본으로 빼고(harness 는 남김) `--all-entries` 로 모두 본다. projectPath 폴더가 디스크에 없는 항목은 "다른 폴더 설치" 에서 뺀다 |
| `skills/update/SKILL.md` | 판 확인 명령에 `--loaded-root "${CLAUDE_PLUGIN_ROOT}"`. 절차를 실린 판이 최신이면 끝 → 아니면 marketplace update, update → `/reload-plugins` 후 다시 확인 → reload 뒤에도 최신이 아니면 "갱신 확인 불능" 으로 멈추고 새 세션 안내. `install` 은 "not installed" 로 실패할 때만. uninstall 안내 삭제, 하지 않는 이유를 "지켜야 할 것" 에 적음 |
| `skills/version/SKILL.md`, `skills/sync/SKILL.md` | 같은 기준(`${CLAUDE_PLUGIN_ROOT}`)으로 실린 판을 보이고 판정 |
| `hooks/update_notice.py` | 뒤처짐 판정은 원래부터 실린 판(`CLAUDE_PLUGIN_ROOT`) 기준이라 동작은 그대로. 안내 문구에서 "`claude plugin list` 로 이 폴더 판 확인" 을 실린 판 확인으로 바꿈 |
| `hooks/enabled_plugin_guard.py` (신규), `hooks/pre-bash-git-guard.sh` | `git commit`(staged 와 HEAD 비교)과 `git push`(upstream 또는 origin/main 과의 공통 조상과 HEAD 비교)에서 `.claude/settings.json` 의 `enabledPlugins["harness@blueward-harness"]` 가 true 에서 빠지거나 true 가 아니게 되면 거절. 키 순서만 바뀐 것, 파일·항목이 원래 없던 것, 이미 꺼져 있던 것은 통과. JSON 을 못 읽거나 git 이 실패하면 검사 불능으로 거절 |
| `README.md`, `docs/guide/harness-guide.html` | 위 동작 설명, 레일 0.10.117 |
| `checker/tests/` | 실린 판 기준 판정, worktree 시나리오, `--all` 표(줄 숨김·디스크 없는 폴더), 훅의 enabledPlugins 거절 |

## 결정

- 채택: A(판정을 실린 판으로) + C(스킬에서 uninstall 안내 삭제, enabledPlugins 제거를 훅이 막기).
- B(저장소당 설치를 하나로 정리)는 하지 않는다. 정리하려면 uninstall 이 필요한데 uninstall 이 공유 `enabledPlugins` 를 묻지 않고 비우기 때문이다.
- 푸시 검사에 견줄 기준이 전혀 없을 때(받아 둔 원격 브랜치가 하나도 없음)는 통과한다. 기준이 있어야 할 것 같은데 못 찾으면(upstream 도 origin/main 도 없는데 원격 브랜치는 있음) 검사 불능으로 거절한다.
- 훅은 `.claude/settings.json` 을 건드린 적이 없으면 python 을 부르지 않는다(모든 커밋·푸시에 uv 를 띄우지 않으려고).
- 열린 PR #468 이 0.10.116 을 쓰므로 이 변경은 0.10.117.

## 남은 일

- Claude Code 에 버그 피드백: worktree 별 project 항목이 여럿일 때 `claude plugin update --scope project` 와 세션이 cwd 가 아닌 다른 worktree 항목을 고른다. `update`/`install` 이 대상 경로를 지정할 수 없다. `uninstall` 이 확인 없이 공유 `.claude/settings.json` 의 `enabledPlugins` 를 비운다.
- 이 변경이 병합된 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
