# #649 웹 콘솔은 꼭 필요할 때만 묻기 / #684 권한 모드에 auto

필요 없는 허락까지 카드로 물어 사람이 지쳤다. 안전한 일은 묻지 않고 허용하고, 되돌릴 수 없는 일은 노랑 카드(시안 17)로 묻고, 판정 못 하는 일은 일반 카드로 묻는다.
결정 표의 정본은 #649 마지막 댓글 "결정 (2026-11-05)".

## 바꾼 것

- `console/risk.py`(새, 순수 함수): `classify(tool_name, tool_input, cwd) -> ("safe" | "irreversible" | "unknown", 쉬운 말 사유)`.
  - 셸은 직접 만든 토크나이저로 `;` `&&` `||` `|` 조각을 나눠 조각이 모두 safe 일 때만 safe. 따옴표 밖의 `$(` 백틱 `( )` 줄바꿈 `&` 리디렉션(`> file`, `< file`)은 해석하지 않고 unknown
    (`2>&1`, `>/dev/null` 만 넘어감). 조각 하나라도 irreversible 이면 irreversible. `A=1 cmd` 는 읽기여도 unknown, 지우기·올리기는 그대로 irreversible.
  - git: 읽기 하위 명령, `branch` 목록만, `remote -v`, `add`, `commit`(`-a`·`--amend`·`--no-verify` 는 unknown), `checkout -b`·`switch -c` 가 safe. `push`, `clean`(`-n` 은 safe), `reset --hard`, `checkout --`·`checkout .`, `restore`(`--staged` 만이면 unknown), `branch -d/-D`, `stash drop/clear` 가 irreversible. `git -c ...` 는 읽기여도 unknown.
  - gh: pr view/list/checks/diff/status, issue view/list/status, run view/list 가 safe. pr·issue 쓰기와 `gh api` 의 `-X`(GET 아님)·`-f/-F/--field/--input` 이 irreversible. 그냥 `gh api` GET 은 목록에 없어 unknown.
  - 파일 도구: cwd 안 Edit/Write/MultiEdit/NotebookEdit 는 safe, cwd 밖은 irreversible, `.git/`·`.claude/settings*.json` 은 unknown, cwd 를 모르면 unknown. Read/Glob/Grep 은 경로가 cwd 밖이면 unknown(claude 가 원래 묻는 경우가 그 경우뿐이다).
  - MCP: 도구 이름 끝(`mcp__<서버>__<도구>`)이 읽기 목록이면 safe, 쓰기 목록이면 irreversible, 아니면 unknown(`tableContents`·`runQuery` 는 일부러 unknown — 하네스 훅이 따로 판정, #699).
  - PowerShell 도구는 지우기·올리기만 irreversible 로 가리고 나머지는 unknown(따옴표 규칙이 달라 safe 판정을 하지 않는다).
- `console/safe_tools.json`(새, 데이터): 상태 없는 도구 · 경로를 보는 도구 · 고치는 도구 · SAP 읽기/쓰기 도구 이름 · 읽기 셸 명령 · 지우기·설치 명령 · git 읽기 하위 명령 · gh 읽기/쓰기 표. 못 읽으면 빈 목록이라 아무것도 safe 가 되지 않는다.
  쓰기 목록은 `env/adt-tiers.yaml` 의 `write_tools` 와 같은 이름(setObjectSource … pushRepo)에 `createTestInclude`, `createTransportsConfig`, `setTransportsConfig`, `transportAddUser`, `transportSetOwner`, `transportReference`, `atc*` 쓰기, `git*` 쓰기, `stageRepo`, `switchRepoBranch`, `setPrettyPrinterSetting`, `fixEdits` 를 더했다.
- 서버 설정 "AI가 묻는 범위": `ask.json`(상태 폴더, `notify.json` 과 같은 방식) `{"level": "needed" | "edits" | "all"}`. `GET/PUT /api/settings/ask`. 못 읽거나 값이 이상하면 `needed`.
- `Hooks.decide` / `auto_allowed` / `risk_of` (`hooks_api.py`): `permission()` 이 카드를 만들기 전에 판정한다.
  - safe 이고 level 이 `needed`, 또는 `edits` 인데 고치는 도구가 아니면 → 카드 없이 바로 `{"behavior": "allow"}` 응답 + 세션 로그 "자동 허용: 도구: 내용 (사유)". chat 에는 안 남긴다. 같은 호출을 훅과 콘솔 연결이 둘 다 물어도 로그는 한 줄(`lastAutoKey`).
  - irreversible → 어느 level 에서도 카드. 요청에 `risk: "irreversible"`, `riskNote`(쉬운 말 사유). 이 요청은 `allow_session`(다시 묻지 않기)을 서버가 400 으로 거절한다.
  - unknown, level `all` → 지금처럼 일반 카드.
  - 터미널만 있는 세션(브라우저 없음)은 판정 전에 `None` 을 돌려주는 기존 동작 그대로다.
- `managed.py` `_bridge_permission`: 콘솔 세션은 훅과 별개로 `can_use_tool` control_request 를 보내므로 같은 판정(`manager.auto_allowed`, `manager.risk_of`, 서버가 Hooks 의 것을 끼워 준다)을 쓴다. 끼워 주지 않으면 전부 묻는다.
- 화면 `app.js`: 요청 카드가 `req.risk === 'irreversible'` 이면 `확인 필요 · 되돌릴 수 없어` 꼬리표, 제목은 `riskNote`, 한 줄 "하네스는 되돌릴 수 없는 일은 항상 사람에게 물어.", 버튼은 `이번만 허락` / `하지 마` 만(`.bad.irrev`). 설정은 "AI가 묻는 범위"(세 단계, 시안 19 글, 서버 설정과 연결, 읽기 전에는 고르지 못함)와 "기본 권한"(새 작업 기본 모드, 이전에 이 이름으로 있던 칸)으로 나눴다.

## 검토 지적과 반영

별도 reviewer 검토에서 safe 로 새는 구멍이 나왔다. 원칙을 "확실히 안전하다고 아는 것만 safe, 애매하면 unknown" 으로 바꿨고 목록·옵션은 모두 `safe_tools.json` 에 둔다. 위 "바꾼 것"의 git 읽기·MCP·설정 기본값 설명은 이 절이 앞선다.

| 지적 | 반영 |
|---|---|
| 읽기 명령의 옵션으로 임의 명령 실행(`git fetch --upload-pack=x .`, `rg --hostname-bin x y`, `rg --pre`) | `git fetch` 를 safe 에서 뺐다. git 읽기·add·commit, ls cat head tail wc grep rg find cut tr sort uniq 는 **옵션 허용 목록**(정규식 전체 일치)으로 바꿔, 목록에 없는 옵션이 하나라도 있으면 unknown. git 전역 옵션은 `--no-pager` 만 허용하고 `-c` `-C` `--git-dir` `--work-tree` `--exec-path` 는 unknown. `--ext-diff` `--textconv` `--output` 은 목록에 없어 unknown. |
| `git checkout -b x -f origin/main`, `git switch -c x --discard-changes main` 이 safe | checkout·switch 에 `-f` `--force` `--discard-changes` `--merge` `-m` `-B` `-C`(묶음 `-fb` 포함)가 **어디 있든** irreversible. `-b`/`-c` 는 `이름 [시작점]` 만 있을 때 safe. |
| `pytest --basetemp=d`, `pytest -p mod` 로 파일 쓰기·모듈 실행 | pytest(`pytest`, `uv run pytest`, `python -m pytest`)는 허용 목록(`-q -v -x -s -k 식 -m 식 -p no:cacheprovider --tb=값 -r글자 --maxfail=숫자` 등)과 작업 폴더 안 경로(`::` 앞)만 safe. `-n` 은 뺐다. |
| 쓰기 보호 경로 | Edit/Write/NotebookEdit 이 `.git/**` `.claude/**` 전체 `.githooks/**` `.mcp.json` `hooks.json` `CLAUDE.md` `AGENTS.md` `conftest.py` `.envrc` `.env*` `package.json` `pyproject.toml` `setup.cfg` `tox.ini` `pytest.ini` 면 unknown(대소문자 무시). 세션 scratchpad(`…/Temp/claude/…/scratchpad/…`, `..` 로 벗어나면 제외)는 작업 폴더 밖이어도 safe. 메모리 폴더(`~/.claude/projects/*/memory/`)는 safe 가 아니라 작업 폴더 밖이라 irreversible 카드로 묻는다. |
| 작업 폴더 밖·비밀값 읽기 | Bash 읽기 명령의 경로 인자가 작업 폴더 밖(절대경로 · `~` · `..` · 다른 드라이브)이면 unknown. 안이어도 `.env*` `*.pem` `*.key` `id_rsa*` `*.pfx` `credentials*` `.netrc` `.npmrc` 와 `.ssh/.aws/.gnupg` 폴더는 unknown(`*` 가 든 이름은 그 이름이 비밀값 이름과 맞을 수 있으면 unknown). `$HOME` 등 변수·`%VAR%`·`~` 확장은 unknown. `\` 가 든 명령은 Windows 경로일 수 있어 경로를 읽는 명령은 판정하지 않는다. `cd` 는 작업 폴더 안일 때만 safe 이고 뒤 명령의 기준 폴더가 따라 바뀐다. Glob 의 `pattern`·`path`, Grep 의 `path`, Read 도 같은 기준. |
| MCP 서버 이름 | safe 는 서버 이름이 `abap-adt` 로 시작하거나 cwd `env/adt-tiers.yaml` 의 servers 에 있을 때만(`hooks/adt_tiers.py` 의 파서를 불러 쓴다). 그 밖 서버는 unknown. 쓰기 도구 이름은 서버와 상관없이 irreversible. safe 목록에서 `gitExternalRepoInfo` `remoteRepoInfo` `renamePreview` `extractMethodPreview` `renameEvaluate` `extractMethodEvaluate` `atcCustomizing` `checkRepo` 를 뺐다. |
| 설정 파일이 깨졌는데 `needed` 로 | `ask.json` 이 **아예 없을 때만** 기본 `needed`. 있는데 못 읽거나 깨졌거나 값이 이상하면 `all`(가장 엄격)로 보고 `GET /api/settings/ask` 가 `problem` 을 함께 주며 설정 화면이 "설정을 읽지 못해 모든 명령마다 물어" 를 보인다. 다시 저장하면 풀린다. |
| 추가 안전 명령 | `sed -n '3,5p' 파일`·`sed -n '7p' 파일` 만(그 밖 sed 스크립트 unknown), `cut` `tr` `sort`(`-o` `--output` unknown) `uniq`(마지막 낱말이 출력 파일이 될 수 있어 낱말 하나까지만). 경로 규칙 적용. |

시험표에 reviewer 가 실측한 우회 입력을 모두 넣었다(`test_risk_classify_table`).

### 2차 지적 (재검토에서 처음 7건은 막혔고 새 구멍이 나왔다)

방향: **셸은 정말 단순한 읽기만 safe, 나머지는 묻기.** 파일 쓰기(작업 폴더 안, 보호 경로 제외)와 ADT 읽기 도구(정확한 서버만)는 그대로 safe. 위 1차 표에서 pytest · `git remote` · `git cat-file` · 서버 접두어 · 재귀 grep 관련 설명은 이 절이 앞선다.

| 지적 | 반영 |
|---|---|
| ① `git clean -f -e -n` 이 safe (실제로 지운다) | 인자가 `-n` `--dry-run` `-d`(묶음 `-nd`)뿐일 때만 safe. `-f`/`--force` 가 있으면 어디 있든 irreversible. 그 밖(`-e` `-x` `-X` 값 받는 옵션, 경로, 인자 없음)은 unknown. |
| ② scratchpad 글자 조각 비교로 뚫림(`…\evil\temp\claude\foo\scratchpad\a`, `C:\Windows\Temp\claude\a\scratchpad\x.dll`, `docs/temp/claude/s/scratchpad/CLAUDE.md`, `.claude/commands/Temp/Claude/a/Scratchpad/evil.md`, `.git/hooks/temp/claude/s/scratchpad/pre-commit`) | 글자 비교를 버렸다. `tempfile.gettempdir()` 의 realpath 아래 `claude/<폴더>/<폴더>/scratchpad/<파일…>` 구조(깊이 정확히)이고 `platform_compat.is_within` 으로 판정. 작업 폴더 안 하위 폴더 이름이 temp/claude/scratchpad 여도 scratchpad 가 아니라서 일반 쓰기 규칙(보호 경로 포함)을 받는다. 다섯 개 모두 safe 아님. **콘솔 서버와 Claude 의 `TEMP` 가 다르면(예: 이 PC 의 시험 환경은 `CreatorTemp`) scratchpad 쓰기는 safe 가 아니라 묻는다** — 안전한 쪽으로 틀린다. |
| ③ `cd` 가 중간·`;`·`\|` 뒤에서도 safe | safe 는 맨 앞 `cd <폴더> && <명령>` 꼴(바로 뒤가 `&&`)이고 그 폴더가 `os.path.isdir` 로 실제 있는 작업 폴더 안일 때만. `;` `\|` `\|\|` 뒤, cd 가 중간에 나옴, 두 번째 cd, 없는 폴더, 파일, `~`·변수는 unknown. |
| ④ `startswith("abap-adt")` 로 서버 위장 | 접두어를 버렸다(`sap_server_prefixes` 삭제). cwd `env/adt-tiers.yaml` servers 에 **정확히 같은 이름**이 있을 때만 읽기 도구 safe. 파일이 없거나 못 읽으면 unknown. 쓰기 도구 이름은 서버와 상관없이 irreversible. |
| ⑤ WebFetch 로 사설망·로컬 접근 | 공개 http(s) 호스트 이름일 때만 safe. localhost · IP 글자 그대로(공개 IP 포함, 10진·16진 표기 포함) · `.local` `.localhost` `.internal` `.lan` `.home.arpa` `.corp` `.intranet` · 점 없는 이름 · 사용자 정보가 든 주소 · http(s) 가 아닌 주소는 unknown. WebSearch 는 safe 유지. **남는 위험: WebFetch 로 읽은 내용을 URL 에 실어 보내는 유출 위험은 남는다(사용자 결정: 웹 읽기 묻지 않음).** 이름이 사설 주소로 풀리는 DNS 도 이 판정으로는 알 수 없다. |
| ⑥ pytest 로 임의 코드 실행 | `pytest` · `uv run pytest` · `python -m pytest` 를 safe 에서 뺐다(unknown). 쓰기 보호 경로에 `.husky/**` `.pre-commit-config.yaml` `Makefile` `.vscode/**` `.github/workflows/**` `sitecustomize.py` `usercustomize.py` `*.pth` `.npmrc` `.pypirc` `**/hooks/*.py` `**/hooks/*.sh` `.gitattributes` `.gitconfig` 를 더했다. |
| ⑦ echo/printf 변수 확장, `nul` 리디렉션 | `echo`/`printf` 인자에 `$` `%` `~` 백틱이 있으면 unknown. 리디렉션은 `/dev/null`·`>&숫자` 만(`nul` 은 POSIX 셸에서 파일을 만든다). |
| ⑧ 비밀값 | 재귀 읽기는 unknown: `grep` 의 `-r/-R/--recursive` 와 `ls -R` 는 허용 옵션에서 뺐고, `rg` 는 파일 경로가 하나도 없거나 폴더 경로가 있으면 unknown, `--hidden` `--no-ignore` `-u` `-e` 도 unknown. 옵션이 따로 받는 값(`-n 5`, `-g 글롭`, `-A 3`)은 경로 취급하지 않는다. git 위치 인자(`<rev>:<경로>` 의 경로 포함)와 `git add` 인자도 비밀값·보호 경로 이름 규칙으로 검사(`git show HEAD:.env`, `git diff -- .env`, `git log -p -- .env` → unknown). `git cat-file`(읽기 목록에서 뺌) · `git remote`(`-v` `get-url` 포함) · `git config` 는 unknown. cat 등으로 쓰기 보호 목록과 `.git/**` 를 읽는 것도 unknown(`cat CLAUDE.md` · `cat package.json` 도 묻는다). 비밀값 이름에 `id_*` `*.p12` `*.key*` `*.pem*` `*secret*` `*token*` `*credential*` `*.tfvars` `service-account*.json` `.docker/config.json` `*.env` `.env*` `.netrc` `_netrc` `.git-credentials` 를 더했다. 심볼릭 링크는 realpath 의 이름도 본다. |
| ⑨ 시험 | `test_risk_second_review_table`(위 입력 전부 + 진짜 안전한 흔한 명령이 여전히 safe 인 표), cd · rg 폴더 · 심볼릭 링크 · scratchpad · ADT 서버 이름 시험. |

한계: 이름 규칙은 일부러 넓어서 `fix-token-bug` 같은 브랜치 이름을 git 읽기 인자로 쓰면 묻는다(안전한 쪽으로 틀림). `git diff` 처럼 경로 없이 변경된 추적 파일의 내용을 전부 보이는 명령은 막지 못한다. 심볼릭 링크 시험은 만들 수 없는 환경(이 Windows 개발 PC)에서는 건너뛰어 실제로 돌려 보지 못했다.

## #684 auto 모드

- 근거: https://code.claude.com/docs/en/permission-modes ("Eliminate prompts with auto mode"). 값 이름 `auto`, 실행 인자 `--permission-mode auto`(`managed.Manager.command` 가 이미 `PERMISSION_VALUES` 안의 값을 그대로 붙인다). 요금제 All plans, Team·Enterprise 는 기본 켜짐(관리자가 `permissions.disableAutoMode` 로 끔), 모델은 Anthropic API 의 Opus 4.6+ · Sonnet 4.6+ · Haiku 5.5 · Fable. 분류기가 연속 3번·누적 20번 막으면 묻기로 돌아간다. 2026-11-05 페이지를 다시 열어 확인: 플래그·설정 값 모두 `auto`, Opus 4.6+ · Sonnet 4.6+ · Haiku 5.5 · Fable(Bedrock 등은 Sonnet 5+ · Opus 4.7+), **쓸 수 없으면 오류 없이 Manual(`default`) 로 시작**, 관리자 끔(`permissions.disableAutoMode`)이면 실행 중 `auto mode disabled by settings` 가 뜬다. 막은 행동은 알림과 `/permissions` 의 Recently blocked 탭에 남는다. stream-json 에서의 모습은 이 페이지에 없다(페이지 뒤 19,751자는 못 읽음).
- `PERMISSION_OPTIONS` 에 `("auto", "알아서 하되 위험한 건 AI가 막기")` 를 더했다 → 새 작업 "고급 설정", 세션 화면 "권한 모드", 설정 "기본 권한"에 모두 보인다. `bypassPermissions`·`dontAsk` 는 여전히 허용 집합 밖(400)이고 `--dangerously-skip-permissions` 도 없다.
- 쓸 수 없는 환경: 공식 문서상 조용히 Manual 로 시작하므로 ① 이 주된 경로다. 실제 claude 로는 확인하지 못해 세 경우를 모두 잡는다 — ① init 이벤트의 `permissionMode` 가 `auto` 가 아님, ② 오류 result 글에 `auto` 가 들어 있음, ③ init 도 못 보내고 프로세스가 끝남. 모두 세션 `permissionNote`(화면 배너 + "자세히"의 권한 모드 칸)와 세션 로그에 "auto 모드를 쓸 수 없는 것 같아 … 이유는 확인 못 함" + claude 가 낸 원문을 남긴다. 세션 도중 `set_permission_mode` 가 실패해도 같은 말로 원문을 붙인다. stderr 는 파일로 가므로 읽지 못한다(원문이 없으면 "확인 못 함").
- 분류기가 막은 행동을 콘솔에서 보이기는 하지 못했다(stream-json 에 그 이벤트가 있는지 확인하지 못함) → 남은 것.

## 시험

- `test_web_console.py`: `risk.classify` 표 시험(safe · irreversible · unknown 각 여러 개, 복합 명령, cwd 밖, `.git`, SAP 읽기·쓰기), 설정 API(기본·검증·저장·깨진 파일·로그인), 자동 허용(응답 · 로그 한 줄 · chat 에 안 남음), level 세 단계, irreversible 카드와 `allow_session` 400, 모든 level 에서 irreversible 은 카드, 터미널 전용 세션 그대로, AskUserQuestion 제외, 콘솔 세션 다리, auto 모드 경고 세 경로.
  바꾼 기존 시험: 권한 모드 목록이 `["", acceptEdits, plan]` → `[…, auto]`, `auto` 를 "허용 밖" 목록에서 뺐다(대신 `AUTO`·`auto --x` 를 넣음).
- `test_web_console_ui.py`: 시안 17 카드(꼬리표 · 제목 · 안내 · 다시 묻지 않기 없음 · 일반 카드는 그대로), 설정 세 단계와 서버 연결(읽기 · 누르면 PUT · 못 읽으면 안내), "기본 권한"에 auto 선택지, bypass 없음, 세션 화면 auto 경고.

## 남은 것 · 확인 못 한 것

- 실제 claude 로 auto 를 켠 실시험(관리자 끔 · 모델 미지원일 때의 실제 메시지)은 못 했다.
- 분류기 차단 이벤트 표시(#684 세 번째 항목)는 못 했다.
- 실제 브라우저 화면 확인은 못 했다(가짜 DOM 시험만).
- PowerShell 도구의 읽기 명령(`Get-ChildItem` 등)은 목록이 없어 계속 묻는다.
- `git switch <기존 브랜치>`, `git pull`, `touch` 같은 흔한 명령도 목록에 없어 묻는다. 필요하면 `safe_tools.json` 과 `risk.py` 의 해당 줄에 더한다.
- 길잡이는 이 PR 에서 `docs/guide/harness-guide.html` 을 고쳤고, 병합 뒤 아티팩트에 다시 올려야 한다.
- 메인 세션 실데이터 대입(최근 transcript 80개, 도구 호출 약 1만 4천 건): 1차 판에서 safe 셸 1,120 → 2차 판 529 로 줄었고, safe 로 분류된 명령 중 지우기·올리기·쓰기 리디렉션은 없었다(남은 위험 낱말은 커밋 메시지·검색어 안의 글자). 2차 뒤 직접 찔러 본 흔한 읽기(`git status`, `gh pr view`, `cat README.md`, `cd 폴더 && git status`)는 safe, 우회 입력은 unknown/irreversible.
- 이 PC 는 `TEMP` 가 `C:\Users\Public\Documents\ESTsoft\CreatorTemp` 라 콘솔 서버의 `tempfile.gettempdir()` 가 Claude scratchpad(`AppData\Local\Temp\claude\…`)와 달라 scratchpad 쓰기도 묻는다(안전한 쪽으로 틀림).
- WebFetch 는 IP·localhost·사설 이름만 막는다. 공개 이름인데 내 PC 로 풀리는 주소(예: `localtest.me`)는 막지 못한다(DNS 확인 안 함).
- `CLAUDE.md` 처럼 쓰기 보호 경로는 읽기도 묻는다(`head CLAUDE.md` 등) — 읽기만은 풀어도 되지만 이번엔 엄격하게 뒀다.
