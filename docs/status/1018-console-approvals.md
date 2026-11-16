# #1018 웹 콘솔이 읽기 명령에도 승인을 묻는 문제와 승인 화면·보안 표시 수정

11-16 Windows(0.10.297) 시험 콘솔에서 "고객 양식 올리기" 한 작업에 승인 카드가 13번 떴고 대부분 읽기만 하는 명령이었다. 사용자 결정(11-16): **승인은 승인 절차가 있는 일에서만 묻는다**(GitHub 에 올리기·바꾸기, 파일 지우기, 작업 폴더 밖 쓰기, SAP 저장). 읽기와 하네스 자체 절차는 묻지 않는다. 보안상 비밀값 파일 읽기(`.env`, `.mcp.json`, `.claude/`, `.git/`)와 원격 임의 코드 실행은 계속 묻는다.

## 한 것

| # | 내용 | 곳 |
|---|---|---|
| 1 | `\` 전역 차단(`bs`)을 없앴다. 경로 인자에 `\` 가 있거나 따옴표 밖 `\` 이스케이프로 글자가 바뀐 낱말(`_Word.esc`)일 때만 그 경로를 판정하지 않는다. 사유도 실제 이유(경로에 `\`, 작업 폴더 밖, 비밀값 이름, 읽기 보호 경로, 변수)로 낸다 | `risk.py` `_path_why`·`tokenize` |
| 2 | `echo` 의 `---` 같은 낱말은 글(`bash_dash_text_commands`). `$ % ~` 백틱은 그대로 묻고 `printf` 는 그대로 | `risk.py`, `safe_tools.json` |
| 3 | Windows 의 Git Bash 경로 `/c/…` 를 `C:/…` 로 바꾼 뒤 작업 폴더 안인지 본다(`_gitbash_path`: `_path_why`·`_cd`·`no_dir_args`). 밖이면 그대로 unknown | `risk.py` |
| 4 | gh 읽기 `repo view`, `label list`, `release list/view`, `workflow list/view`, `auth status`(`--show-token`·`-t` 는 unknown). git `worktree list`, `pull --ff-only [원격 [브랜치]]` 만. 맨손 `pull`·`--rebase`·merge·rebase 는 unknown | `risk.py`, `safe_tools.json` |
| 5 | 읽기에서는 읽기 보호 목록(`read_protected`: `.git/` `.claude/` `.mcp.json` `.env*` + 비밀값 모양 이름)만 막는다. `CLAUDE.md`·`pyproject.toml`·`hooks/`·`.github/workflows` 읽기는 safe. 쓰기·`git add`·`commit` 은 쓰기 보호 목록 그대로 | `risk.py` `_read_protected`, `safe_tools.json` |
| 6 | 하네스 자체 스크립트·엔진(데이터 `harness_scripts`·`harness_modules`·`harness_engine_url`). 설치본(`read_roots`) 아래 `uv run --no-project python …/hooks|skills/….py`(engine_spec, installed_version, activation_gate check, reserve_number list/next/review-reason)와 `uvx --from git+https://github.com/jaeheeMin/blueward-harness@v숫자.숫자.숫자 python -P -m checker.<모듈>`(pr_queue, pr_approvals, branch_growth, cli, role_check). `e="$(… engine_spec.py)" && [ -n "$e" ] && timeout N uvx --from "$e" …`, `|| { echo "…" >&2; exit 1; }` 꼬리 모양을 지원(명령 맨 앞의 대입만, 변수 이름은 대입한 것과 같을 때만). `timeout 초 명령` 은 뒤 명령을 그대로 판정 | `risk.py` `_uv`·`_uvx`·`_check_args`·`_harness_parts`, `classify_bash` |
| 7 | Read/Glob/Grep 판정 사유를 실제 이유별로("작업 폴더 밖 경로야", "비밀값 모양 이름…", "git·Claude 설정 폴더…") | `risk.py` `classify` |
| 8 | (a) 되돌릴 수 없는 일이 아닌 카드도 판정기 한글 사유를 `note` 로 내려 "묻는 이유: …" 한 줄로 쓰고, AI 의 영어 `description` 은 "자세히" 안(설명 칸)으로. (b) 방금 처리한 건 제목 줄이 결과 제목(허락했어 등)이다(승인·계획·질문·MCP 질문). (c) 서버가 `resolution` 코드를 내리고 화면은 그 코드로만 판정(한글 outcome 정규식 제거) | `store.py`, `hooks_api.py`, `server.py`, `managed.py`, `static/app.js` |
| 9 | "허용하고 이 세션에서 다시 묻지 않기": 공식 문서로 `destination: "session"` 이 세션 한정임을 확인해, 서버가 허용 규칙 추가(`addRules` allow)만 `session` 으로 바꿔 돌려주고 `setMode` 등은 넘기지 않는다. 쓸 규칙이 없으면 단추를 숨기고 서버는 400 | `store.py` `session_suggestions`, `server.py` `a_answer`·`a_request` |
| 10 | 막힘 카드·"그렇게 고쳐 줘" 글·`fix` 에서 우회 문장(`DELIVER=1`, `--no-verify`, 훅 끄기 등, 데이터 `bypass_phrases.json`)을 문장 단위로 뺀다. 훅 스크립트 문구는 그대로, 원문은 "검사 원문" 안에만 | `bypass_filter.py`, `hooks_api.py`, `static/flow-logic.js`, `static/app.js` |
| 11 | 세션 제목·기록 줄·대화(+`fix`)를 저장 전에 서버에서 비밀값 가림. 규칙 데이터 `secret_rules.json`, 모듈 `secrets_mask.py`(`trouble.py` 가 같은 것을 가져다 쓴다). 화면은 세션 제목·기록 줄에도 `MS()` 적용 | `secrets_mask.py`, `store.py`, `static/app.js` |

보완(실측): AI 가 하네스 규칙을 Bash 로 읽는 `B="<설치본 경로>"; cat "$B/rules/….md"; echo ----; …` 와 변수 없는 `cat "<설치본>/rules/….md"` 도 묻지 않는다. 읽기 명령(`bash_read` paths 명령·`sed -n`)의 경로가 설치본(판 폴더 포함) 안이면 safe(읽기 보호·비밀값·링크 푼 실제 경로 검사 그대로, `_harness_read_ok`). 명령 맨 앞 `NAME="<글자 그대로의 설치본 경로>"` 한 번만 `$NAME`·`${NAME}` 로 풀고(값이 설치본 밖·확장 글자 포함·`PATH` `IFS` `BASH_ENV` `ENV` `LD_*` `PS4` `CDPATH` `HOME` 등 위험한 이름이면 풀지 않아 unknown), `cd`·쓰기는 그대로다.

보완 2(실사용 시험에서 9번 중 5번 묻던 명령): 판정기가 모자랐던 곳을 고쳤다. (A) 엔진 대입·변수 대입은 명령 맨 앞 또는 맨 앞 `cd <폴더> &&` 바로 다음 조각일 때만(한 번), cd 는 작업 폴더 안일 때만 safe. (B) `echo "exit=$?"` 의 `$?` 만 글로 본다(다른 `$` 확장·`printf` 는 그대로). (C) `git pull` 맨손·`--rebase`·`--ff-only` safe(start 스킬 절차), 단독 `merge`·`rebase` 는 그대로, `git checkout -b`·`switch -c` 는 새 브랜치 이름 모양만. (E) `>`·`>>` 대상이 작업 폴더 안이고 쓰기 보호·비밀값 경로가 아니면 safe(Write 도구와 같은 기준, 조각마다 그때의 기준 폴더), 폴더 밖(`/tmp` 포함)·`.env`·`CLAUDE.md`·`.git/`·변수·와일드카드는 unknown, `2>&1`·`2>/dev/null`·`>/dev/null` 은 safe. (F) 설치본 숫자 판 폴더의 `sed -n`·`cat` 읽기, `git log --format`, `rev-list --count`, `activation_gate.py check .` 는 safe 였고 시험으로 못 박았다. 그대로 묻는 것: `cat > /tmp/x.md <<'EOF'` 뒤 `gh issue create`(irreversible), `gh label create`, `git push`, `gh pr create`. 실측 명령은 `test_web_console_risk.py::test_1018_field_commands_from_real_sessions` 의 입력이다.

보완 3(두 번째 실사용 시험): `git checkout <이름>`·`git switch <이름>` 은 이름 하나가 이 저장소의 로컬 브랜치(`refs/heads/<이름>` 파일 또는 `packed-refs`, worktree 는 commondir 까지)일 때만 safe(파일 이름·`--`·`-f`·여럿·원격 브랜치는 그대로 unknown/irreversible). 엔진 `e="$(…engine_spec.py)"` 대입은 명령 안 어느 조각 위치든 한 번 받고 `$e` 는 그 조각 뒤에서만 인정(두 번·앞쪽 사용·표지 글자 직접 쓰기는 unknown). 설치본 `grep -n -A25 …` 읽기는 고칠 것 없이 safe 였고(`_harness_read_ok` 는 grep 에도 적용) 시험으로 못 박았다. `echo "auto=$(gh api …)"`·`for i in $(seq …)` 는 unknown 유지. 시험: `test_1018_second_field_round_commands`.

보완 4(11-17 사용자 결정): 2차 시험에서 남은 즉석 셸 스크립트 2개(`r=…; echo "$(gh api …)"`, `for i in $(seq …)`)는 판정기로 안전을 가릴 수 없어 unknown 그대로 두고, 대신 콘솔이 띄우는 세션에 `--append-system-prompt` 로 "셸 명령은 하나씩, 명령 치환·반복문 대신 도구 호출을 나눠 써" 고정 지시를 덧붙였다(`managed.SIMPLE_COMMANDS_PROMPT`). 터미널 세션에는 붙지 않는다.

## 공식 문서 근거(9번)

code.claude.com/docs/en/hooks, PermissionRequest 의 "Permission update entries"(2026-11-16 확인):

> The `updatedPermissions` output field and the `permission_suggestions` input field both use the same array of entry objects. Each entry has a `type` that determines its other fields, and a `destination` that controls where the change is written.
> The `destination` field on every entry determines whether the change stays in memory or persists to a settings file.

| `destination` | Writes to |
|---|---|
| `session` | in-memory only, discarded when the session ends |
| `localSettings` | `.claude/settings.local.json` |
| `projectSettings` | `.claude/settings.json` |
| `userSettings` | `~/.claude/settings.json` |

> A hook can also reuse a suggestion: "A hook can echo one of the `permission_suggestions` it received as its own `updatedPermissions` output."

그래서 지금까지는 claude 가 준 제안(보통 `localSettings`)을 그대로 돌려줘 "이 세션에서 다시 묻지 않기" 가 `.claude/settings.local.json` 에 영구 저장되거나 `setMode acceptEdits` 로 세션 전체 쓰기 자동 허용이 됐다. 이제 허용 규칙만 `session` 으로 바꿔 돌려준다.

## 결정·한계

- 하네스 모듈 중 `srs_export_check compare` 는 읽기만 하지만 저장소 밖 임시 경로에 엑셀을 만들어 목록에 넣지 않았다. `export`·`cts_fill`·`manual_capture`·`srs_automerge`·`ledger_complete` 등 쓰는 모듈과 `reserve_number.py reserve|claim`·`scaffold.py`·`console/open.py` 도 목록에 없다(묻는다).
- `\` 로 줄을 잇는 여러 줄 `uvx` 명령(cts·role·manual·spec 의 산출 명령)은 줄 잇기를 해석하지 않아 계속 묻는다. 산출은 쓰는 명령이라 어차피 목록 밖이다.
- 비밀값 가림 규칙은 서버(`secret_rules.json`)와 화면(`flow-logic.js` 의 `maskSecrets`)에 각각 있다. 화면 쪽을 JSON 하나로 합치지 못한 이유: 정적 스크립트가 동기로 JSON 을 읽을 수 없다. 대신 시험(`test_trouble_console.py`)이 두 쪽 결과를 맞춰 보고, 우회 문장 목록은 시험이 JSON 과 `BYPASS_PATTERNS` 를 같은지 비교한다.
- `.gitconfig` 같은 쓰기 보호 이름은 이제 읽기가 safe 다(사용자가 정한 읽기 보호 목록에 없다).
- 읽기 safe 로 바뀐 것: `git show HEAD:CLAUDE.md`, `cat package.json`, `cat .github/workflows/*.yml`, `Read plugins/*/hooks/*.py`.

## 시험

- 새 시험: `checker/tests/test_web_console_risk.py`(128, 실제 `skills/*/SKILL.md` 의 `uv run`·`e="$(…)"` 명령 문자열을 설치본 경로로 바꿔 읽기 전용만 safe, 쓰기 스크립트·모듈·남의 주소·변수 장난·비밀값·밖 경로는 safe 아님), `test_web_console.py`(note·resolution·세션 한정 규칙·우회 문장·비밀값 가림), `test_web_console_ui.py`(설명 줄·방금 처리 제목·결과 코드·우회 문장 JS=JSON 일치·제목·기록 가림).
- 바꾼 기존 시험: 읽기 보호가 좁아져 `cat CLAUDE.md` 등이 safe, `echo -E` safe, 다시 묻지 않기 안내 문구, 비밀값이 저장 전에 가려져 `test_trouble_console` 의 가린 줄 수.
- 결과(Windows, 한 번에): `test_web_console` · `_ui` · `_risk` · `test_trouble_console` · `test_console_block` · `test_console_mockup_compare` · `test_hook_block_cards` · `test_plugin_layout` · `test_workflow_source` · `test_hook` 1926 통과 · 1 실패 · 4 건너뜀 · 2 xfail. 실패 1건(`test_approval_screen_shows_full_input_and_rules` 의 화면 소스 글 비교)은 시험 글을 고쳐 다시 돌려 통과(이어 705 통과·1 건너뜀, 해당 범위만). 그 한 건 뒤로 전체를 다시 돌리지는 않았다.

## 남은 것

- 완료 조건의 실사용 확인(같은 "양식 올리기" 작업을 Windows 시험 콘솔에서 진짜 claude 로 돌려 승인 횟수 전후 비교, 우회 문장·비밀값이 화면에 안 남는 것)은 하지 못했다.
- 길잡이(`docs/guide/harness-guide.html`)는 이 PR 에서 고쳤고, 병합 뒤 아티팩트에 다시 올려야 한다.
