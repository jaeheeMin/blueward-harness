# harness 플러그인

고객사 Project Repository 에 설치해 쓰는 Blueward 하네스다. 새 저장소의 표준
구조를 만들고, 문서가 템플릿을 따르는지 검사하고(doc-guard), 협업 규칙과
`/harness:start` · `/harness:deliver` · `/harness:wrapup` · `/harness:sync` 를 비롯한
Skill 12개를 한 번에 제공한다.

```
plugins/harness/
  .claude-plugin/plugin.json   플러그인 정의
  hooks/
    hooks.json                 훅 7개를 선언
    pre_write_guard.py         문서·코드 검사(doc-guard) — Write/Edit 직전에 막을지 정한다. src/ 쓰기는 활성화 관문도 건다
    pre-bash-git-guard.sh      git 가드 — 스킬을 거치지 않은 git push, 비밀정보가 든 커밋, 활성화 안 된 ABAP 오브젝트가 있는 푸시를 막는다
    mcp_source_guard.py        SAP ADT MCP 도구 가드 — 코드 규칙 검사, 테넌트별 쓰기 차단, 데이터 추출 되묻기
    mcp_activation_tracker.py  ADT MCP 호출 뒤 ABAP 오브젝트의 활성화 상태를 기록한다(PostToolUse, #190)
    activation_gate.py         기록에 활성화 안 된 오브젝트가 있으면 푸시·src/ 쓰기를 막는 관문(adt_activation.py 공용)
    adt_activation.py          활성화 기록·관문의 공용 로직
    adt_object_types.json      ADT URL 로 오브젝트 TYPE 을 찾는 표
    adt_tiers.py               env/adt-tiers.yaml 해석(mcp_source_guard.py 가 씀)
    mcp_default_tools.json     adt-tiers.yaml 이 없을 때 쓰는 기본 데이터 추출 도구 목록
    mcp_object_source_map.json objectSourceUrl 패턴으로 언어(ABAP·CDS·BDEF)를 가리는 표(UIAD JSON 은 코드 검사 없는 갈래)
    gitleaks-harness.toml      하네스 기본 gitleaks 설정(checker/gitleaks/harness.toml 의 복사본)
    session-start-sync.sh      세션 시작 때 원격과 동기화하고 남은 경고를 전한다
    ensure-tools.sh            세션 시작 때 uv·jq·gh·gitleaks 가 있는지 보고 없으면 설치한다(session-start-sync.sh 가 부름)
    stop-deliver.sh            세션 종료 때 커밋 안 된 변경을 알린다
  skills/
    start/SKILL.md             /harness:start — 이슈와 브랜치 생성
    deliver/SKILL.md           /harness:deliver — 커밋·동기화·푸시·PR
    wrapup/SKILL.md            /harness:wrapup — 남은 작업의 이슈화
    scaffold/                  /harness:scaffold — Project Repository 표준 구조 생성
    srs/SKILL.md               /harness:srs — SRS 작성·수정
    spec/SKILL.md              /harness:spec — 개발 Spec 작성·수정(양식 지도: form-map.md)
    sync/SKILL.md              /harness:sync — 원격 최신 상태를 로컬 브랜치로 당겨받기
    prs/SKILL.md               /harness:prs — 내 열린 PR 의 상태와 병합 순서 확인
    approvals/SKILL.md         /harness:approvals — 내 승인을 기다리는 PR 을 병합 순서대로 확인
    atc/SKILL.md               /harness:atc — SAP ATC 지적 실행·분류·처리
    update/SKILL.md            /harness:update — 플러그인 갱신과 현재 폴더 판 확인
    version/SKILL.md           /harness:version — 설치된 플러그인의 이 폴더 판 표(읽기만)
  agents/
    researcher.md              harness:researcher — 조회 전용 조사(sonnet, 쓰기 도구 없음)
    reviewer.md                harness:reviewer — 읽기 전용 검토(sonnet, 쓰기 도구 없음)
    implementer.md             harness:implementer — 구현(sonnet)
  rules/                       위 Skill 이 참조하는 협업 규칙 5개
  conventions/common.md        어느 저장소에서나 같은 공통 개발 규칙(CR-001 ~ CR-009)
```

플러그인 이름은 `harness` 지만, 문서 검사 기능 자체는 여전히 **doc-guard** 라고
부른다. 훅 스크립트 이름(`pre_write_guard.py`), 검사 메시지("doc-guard: ..."),
문서 저장소가 불러 쓰는 재사용 워크플로(`.github/workflows/pr-checks.yml` 안의 doc-guard 단계. 옛 `doc-guard.yml` 은 #452 에서 지웠다),
검사 엔진의 CLI 이름(`doc-guard`)은 이름을 바꾸지 않았다. 바뀐 것은 이
플러그인 자체의 이름뿐이다.

실제 검사는 `checker/` 엔진이 한다. 이 플러그인은 껍데기이고, 엔진을 왜
플러그인 밖에 두는지는 `checker/README.md` 를 읽는다.

## 설치

```
/plugin marketplace add jaeheeMin/blueward-harness
/plugin install harness@blueward-harness
```

또는 프로젝트 설정(`.claude/settings.json`)의 `enabledPlugins` 에 추가해도 된다.

```json
{
  "enabledPlugins": { "harness@blueward-harness": true }
}
```

플러그인은 저장소가 아니라 **사람** 에게 설치된다. 한 번 설치하면 어느
저장소를 열든 동작한다.

## 제공하는 것

### Skill 12개

플러그인 스킬은 이름 앞에 플러그인 이름이 붙으므로 아래 이름으로 나타난다.

| Skill | 하는 일 |
|---|---|
| `/harness:start` | 작업을 시작한다. 이슈를 만들고 규칙에 맞는 브랜치를 만든다. 먼저 병합할 수 있는 내 PR 이 있으면 알린다(막지 않음, #370) |
| `/harness:deliver` | 작업을 마무리한다. 커밋·동기화·푸시·PR 생성을 한 번에 |
| `/harness:wrapup` | 세션에서 끝내지 못한 작업을 이슈로 남긴다 |
| `/harness:scaffold` | 새 Project Repository 에 표준 구조를 만든다 |
| `/harness:srs` | SRS(요구사항정의서)를 새로 쓰거나, 요구사항이 바뀌었을 때 고친다. 먼저 브랜치를 확인한다(main 이면 start 를 대신, 다른 작업 브랜치면 이어 쓸지 묻는다, #281) |
| `/harness:spec` | SRS 요구사항으로 개발 Spec 을 만들거나, SRS 가 바뀌어 고친다. srs 와 같이 먼저 브랜치를 확인한다 |
| `/harness:sync` | GitHub 의 최신 상태를 지금 로컬 브랜치로 당겨받는다. 지금 세션의 플러그인 버전이 main 보다 낮으면 `/reload-plugins`·Update now 를 안내한다(#203). 판정은 실제로 실린 판(`${CLAUDE_PLUGIN_ROOT}`)이 기준이고 이 폴더의 설치 항목 판은 `installed_version.py --loaded-root` 로 참고만 한다. 전체 표는 `/harness:version` 으로 안내한다 |
| `/harness:prs` | 내 열린 PR 의 상태(초안·충돌·검사 실패·검사 중·승인 대기·병합 가능)와 병합 순서를 GitHub 에서 계산해 보여 주고 다음 할 일을 알려 준다. `--all` 이면 저장소 전체. 읽기만 한다(#370) |
| `/harness:approvals` | 내 Approve 를 기다리는 남의 PR 을 병합 순서대로 한 표로 보여 준다(사유·다른 승인자·낡은 승인·앞 PR). 승인자 파일이 없으면 작성자 아닌 누구든 승인 가능으로 본다. 읽기만 하고 Approve 는 사람이 GitHub 에서 한다(#391) |
| `/harness:update` | 플러그인을 갱신하고 **이 세션에 실제로 실린 판**(`${CLAUDE_PLUGIN_ROOT}` 의 plugin.json)이 최신인지 확인한다. 같은 저장소의 worktree 마다 설치 항목이 따로 있으면 update 가 다른 worktree 항목을 갱신하고 세션도 그 판을 싣기도 해서 설치 항목은 참고로만 본다(#471). 갱신 뒤 `/reload-plugins` 를 입력하고 다시 부르게 안내하며, reload 뒤에도 최신이 아니면 "갱신 확인 불능" 으로 멈추고 새 세션을 안내한다. `install` 은 "not installed" 로 실패할 때만 하고 `uninstall` 은 하지도 안내하지도 않는다(공유 `.claude/settings.json` 의 `enabledPlugins` 를 묻지 않고 비운다). 사용자가 직접 부를 때만 실행한다(#404) |
| `/harness:version` | 설치된 플러그인의 범위·**이 폴더 판**·**이 세션에 실린 판**·받아 둔 최신 판·상태(최신 / 갱신 있음 / 이 폴더에 설치 없음 / 최신 판 확인 불가)·다른 폴더 설치 수를 표로 보여 준다. harness 의 상태는 실린 판으로 정한다(#471). `hooks/installed_version.py --all --loaded-root "${CLAUDE_PLUGIN_ROOT}"`(`--remote` 는 harness 만 원격 태그, `--json`). 이 폴더에서 쓰이지 않는 플러그인 줄은 기본으로 빼고(harness 는 남김) `--all-entries` 로 모두 본다. 디스크에 없는 폴더의 항목은 "다른 폴더 설치" 에서 뺀다. 읽기만 하며 갱신은 `/harness:update` 로 안내한다. project·local 과 user 가 함께 있으면 project·local 쪽 판을 보인다(#461) |
| `/harness:atc` | SAP ATC 지적을 돌려 자동·확인 후·수동으로 나눠 처리하고 재실행해 증감을 보고한다(`env/adt-tiers.yaml` 이 있는 Project Repository 에서만. variant 는 서버 항목의 `atc_variant`) |

### 서브에이전트 3개(#139)

`agents/` 의 정의 파일이 모델과 도구를 고정한다. 이름은 `harness:` 가 앞에 붙고,
`@agent-harness:researcher` 처럼 부를 수 있다. 언제 쓰는지는 `rules/delegation.md` 를 읽는다.

| 에이전트 | 하는 일 |
|---|---|
| `harness:researcher` | 조회 전용 조사. 쓰기·편집 도구가 없고 상태를 바꾸는 명령을 금한다 |
| `harness:reviewer` | 읽기 전용 검토. 쓰기·편집 도구가 없고 자기 승인을 하지 않는다 |
| `harness:implementer` | 범위를 정해 준 구현. 커밋·푸시는 하지 않는다 |

### 훅 7개

`hooks.json` 이 선언하는 훅은 일곱 개다(아래 표의 `ensure-tools.sh` 는 선언된 훅이 아니라
`session-start-sync.sh` 가 부르는 도우미다).

| 훅 | 시점 | 하는 일 |
|---|---|---|
| `pre_write_guard.py` | `PreToolUse` (Write\|Edit) | 문서가 템플릿을 벗어나면 저장을 막는다(doc-guard). 코드(`.abap`, `.js`/`.ts`, `.cds`, `.asbdef`)는 공통 개발 규칙 CR-001·CR-002·CR-003·CR-007 을 어기면 막는다(#54, #72, #81. BDEF 는 CR-001 만, CR-003·CR-007 은 ABAP·JS/TS 만). 저장소 루트 `src/` 아래에 쓸 때는 활성화 안 된 ABAP 오브젝트가 있으면 막는다(활성화 관문, #190, 아래 절) |
| `pre-bash-git-guard.sh` | `PreToolUse` (Bash\|PowerShell) | 스킬을 거치지 않은 `git push` 와 main 직접 커밋을 막는다. 공유 `.claude/settings.json` 의 `enabledPlugins` 에서 `harness@blueward-harness` 가 빠지거나 꺼지는 변경은 커밋(staged)·푸시(origin 기준 범위) 모두 막는다 — 키 순서만 바뀐 것과 원래 없던 경우는 통과하고 JSON 을 못 읽으면 검사 불능으로 막는다(`enabled_plugin_guard.py`, #471). `gh pr merge` 대상 PR 이 SRS 를 바꿨는데 승인이 없어도 막는다(#49). `.github/human-merge-paths` 에 적힌 경로를 바꾼 PR 의 `gh pr merge` 도 막는다(#104). 대상 PR 의 검사가 실패·진행 중이거나 상태를 확인할 수 없어도 막는다(#120). 먼저 병합해야 하는 PR(base 브랜치가 그 PR 의 브랜치, 본문 `먼저: #n`, 같은 DEV 의 SRS→Spec→개발 순, 하네스 저장소의 plugin.json version 순)이 아직 열려 있으면 `checker.pr_queue --pr` 로 확인해 막고, 순서를 정하지 못해도(순환·GitHub 못 읽음·엔진 실패) 통과시키지 않는다(#370, 사람이 GitHub 화면에서 하는 병합은 막지 못한다). `git commit` 은 staged 변경을 gitleaks 로 검사해 비밀값이 있으면 막는다(#170, 아래 "비밀정보 검사" 참고). `git push` 는 080 에 쓴 ABAP 오브젝트 중 활성화 안 된 것이 있어도 막는다(활성화 관문, #190, 아래 절) |
| `mcp_source_guard.py` | `PreToolUse` (SAP ADT MCP 도구 22개) | MCP 로 SAP 에 쓰거나 이름을 붙이는 경로의 코드 규칙 CR-001·CR-002·CR-003·CR-007 검사(#60, #61)와, `env/adt-tiers.yaml` 기준 테넌트별 쓰기 차단·데이터 추출 되묻기(#148). 아래 "테넌트별 쓰기 차단" 참고 |
| `mcp_activation_tracker.py` | `PostToolUse` (SAP ADT MCP 도구 6개: `setObjectSource`·`createObject`·`deleteObject`·`activateObjects`·`activateByName`·`inactiveObjects`) | ADT MCP 로 쓴 ABAP 오브젝트와 활성화 결과를 `.git` 아래 기록 파일에 남긴다(#190, 아래 절). 기록하지 못하면 표식 파일을 남기고 exit 2 로 알린다 |
| `session-start-sync.sh` | `SessionStart` | 원격과 동기화하고, 지난 세션 기록을 원격 반영 뒤에 판정해 커밋되거나 병합된 것은 조용히 지우고 사라진 파일(`git restore --source=<사본>` 안내)과 push 안 한 커밋만 전한다(#224, 옛 형식 기록은 한 번 보여 주고 지운다). upstream 이 있으면 그것을, 없으면 origin/main 을 기준으로 리베이스하고(#87), 미커밋 변경이 있거나 이미 리베이스·병합이 진행 중이면 자동 동기화를 건너뛴다(자동 stash·자동 커밋은 하지 않는다 — `/harness:sync` 로 직접 처리). 내 열린 PR 이 있으면 상태와 병합 순서를 `checker.pr_queue` 로 20초 안에 읽어 알리고, 읽지 못하면 "PR 상태 확인 불능" 한 줄만 남긴다(#370, GitHub 원격일 때만, 훅은 항상 exit 0). 저장소 안(꼭대기에서 3단계까지)에 `templates/` 와 `rules/` 를 함께 가진 폴더가 없으면 `/harness:scaffold` 를 안내한다(#128, 자동 실행은 하지 않는다. 플러그인 저장소(`.claude-plugin/marketplace.json` 이 꼭대기에 있다)와 git 저장소가 아닌 곳은 말하지 않고, `HARNESS_NO_SCAFFOLD_HINT=1` 로 끈다) |
| `update_notice.py` | `UserPromptSubmit` | 이 세션의 플러그인 판이 원격 최신 `v*` 태그보다 낮으면 Claude 가 사용자에게 한 번 알리게 한다(#314). 원격은 `git ls-remote` 5초 제한, 10분 캐시(`${CLAUDE_PLUGIN_DATA}`), 같은 세션·같은 판은 한 번. **이 폴더의 설치 항목**(`installed_plugins.json` 의 현재 projectPath, `installed_version.py`)이 이미 새 판이면 `/reload-plugins`, 아니면 `/harness:update` 또는 업데이트 명령을 안내한다(다른 폴더가 받아 둔 캐시 폴더만 보면 틀린다, #404). 뒤처졌는지의 기준은 설치 항목이 아니라 이 세션에 실린 판(`CLAUDE_PLUGIN_ROOT`)이다(#471). 갱신은 사용자가 직접 하거나 `/harness:update` 를 부른다. 실패하면 조용히 넘어가 프롬프트를 막지 않는다. 플러그인 저장소와 `HARNESS_NO_UPDATE_NOTICE=1` 에서는 말하지 않는다 |
| `ensure-tools.sh` | `SessionStart` (session-start-sync.sh 가 부름) | uv·jq·gh·gitleaks 가 없으면 Windows 에서 winget 으로 설치하고 결과를 알린다(#116, gitleaks 는 #170). 아래 "도구 자동 설치" 참고 |
| `stop-deliver.sh` | `Stop` | 커밋되지 않은 변경이 남았으면 `/harness:deliver` 를 안내한다. 대답마다 변경이 있으면 작업 사본을 임시 index 로 떠 `refs/harness/unfinished/<worktree>` 에 붙잡고(실제 index·작업 트리는 그대로, 새 파일 포함, `.gitignore`·`*handoff*.md`·`.superpowers/` 와 50MB 넘는 새 파일 제외, 변화가 없으면 다시 뜨지 않는다) 덮어쓰는 기록 파일(`<git-dir>/<repo>-unfinished`, 첫 줄 `format=2`)에 사본·push 안 된 커밋 정보를 남긴다(#224) |

### 테넌트별 쓰기 차단과 데이터 추출 되묻기(#148)

SAP ADT MCP 서버는 테넌트(클라이언트)마다 하나씩 붙는다. 프로젝트 루트의
`env/adt-tiers.yaml` 에 서버별로 쓰기를 허용하는지 적어 두면 `mcp_source_guard.py` 가
그것을 읽는다. 훅 입력의 `cwd` 에서 위로 올라가며(저장소 루트까지) 찾는다.

```yaml
servers:
  abap-adt-z5u:            # .mcp.json 의 서버 이름과 같아야 한다
    client: "100"          # client, role 은 안내문용
    role: customizing
    writes_allowed: false
    data_access: deny      # 선택(기본 ask). deny 면 데이터 도구를 막는다
  abap-adt-z5u-dev:
    client: "080"
    writes_allowed: true
write_tools: [setObjectSource, createObject, deleteObject, activateObjects, ...]
data_tools: [tableContents, runQuery]
```

| 상황 | 동작 |
|---|---|
| 서버가 `writes_allowed: false` 이고 도구가 `write_tools` 에 있다 | 거절. 쓰기가 허용된 서버 이름을 파일에서 읽어 알리되, "다음:" 은 멈추고 사람에게 알려 다른 서버에서 할 일인지 정하게 한다(Claude 가 서버를 바꿔 다시 시도하지 않는다) |
| 서버가 `servers` 에 없고 도구가 `write_tools` 에 있다 | 거절(모르는 서버는 쓰기 허용으로 보지 않는다) |
| `writes_allowed: true` 서버의 쓰기 도구 | 테넌트 판정은 통과하고, 기존 코드 규칙(CR) 검사가 이어진다 |
| 도구가 `data_tools`(기본 `tableContents`, `runQuery`)에 있고 서버가 `data_access: deny` 다(#161) | 거절. 운영 실데이터 서버처럼 승인을 받아도 데이터를 꺼내면 안 되는 서버에 쓴다. "다음:" 은 멈추고 사람에게 알려 데이터가 필요한지 정하게 한다(다른 서버로 옮겨 다시 하지 않는다) |
| 도구가 `data_tools` 에 있고 `data_access` 가 없거나 `ask` 이거나 서버가 `servers` 에 없다 | 사용자에게 되묻는다(`ask`). 쿼리에 `SELECT *` 나 `FIELDS *` 가 있으면 사유에 CR-003 을 적는다 |
| 파일이 없다 | 쓰기 도구는 기존 CR 검사만, 데이터 도구는 기본 목록으로 되묻는다. 세션 시작 때 `.mcp.json` 이 있는 저장소에만 "꺼져 있다" 고 알린다 |
| 파일이 있는데 읽거나 해석하지 못한다(필수 키 `servers`·`write_tools`, 서버마다 `writes_allowed` true/false, `data_access` 는 있으면 `ask`·`deny` 만) | 거절(검사 불능). 파일을 고치라고 안내한다 |

파일은 PyYAML 없이 작은 해석기로 읽는다 — 맵, 글자 목록, `[a, b]` 한 줄 목록, 주석,
따옴표 글자만 지원하고, 그 밖의 문법(앵커, 여러 줄 글자, 탭 들여쓰기)은 해석 못 함으로
거절한다. 도구 이름은 `mcp__<서버>__<도구>` 에서 마지막 `__` 를 기준으로 나눈다.
scaffold 는 `env/adt-tiers.example.yaml`(예시, 훅은 읽지 않음)을 만든다.

**한계.** 훅 매처(`hooks.json`)는 이름 목록 정규식이라 목록에 있는 22개 도구만
가로챈다 — 코드 규칙 검사 6개(`setObjectSource`, `renamePreview`, `renameExecute`,
`extractMethodPreview`, `extractMethodExecute`, `createObject`), 쓰기 14개(`deleteObject`,
`activateObjects`, `activateByName`, `createTransport`, `transportRelease`,
`transportDelete`, `publishServiceBinding`, `unPublishServiceBinding`, `deployUi5App`,
`undeployUi5App`, `publishBusinessCatalog`, `runClass`, `gitPullRepo`, `pushRepo`), 데이터 2개. **`write_tools` 나
`data_tools` 에 새 이름을 적어도 매처에 없으면 훅이 불리지 않아 막히지 않는다** — 이름을
늘리려면 매처도 함께 고쳐야 한다. 모든 MCP 도구(`mcp__.*__.*`)를 잡지 않은 것은 ADT 가 아닌
MCP 서버의 모든 호출마다 훅(`uv` 기동)을 띄우는 비용 때문이다. 플러그인이 번들한 MCP 서버
이름은 `plugin_<플러그인>_<서버>` 꼴이라 `servers` 에 그대로 적어야 한다.

### 080 에 쓴 오브젝트의 활성화 확인(#190)

`setObjectSource` 로 쓰고 활성화하지 않았거나 활성화가 실패한 채로 푸시나 `src/` 스냅샷으로 넘어가는 일을
막는다. `mcp_activation_tracker.py`(PostToolUse)가 ADT MCP 호출을 `.git` 아래
`harness-adt-activation.json` 에 기록하고(worktree 별, 세션을 넘어 남는다), `activation_gate.py` 가 그
기록을 읽어 세 곳에서 건다 — `git push`(`pre-bash-git-guard.sh`), 저장소 루트 `src/` 아래 Write/Edit
(`pre_write_guard.py`), `/harness:deliver` 2단계.

| 상태 | 뜻 |
|---|---|
| `written` | 썼고 활성화 확인 전 |
| `active` | 활성화 성공 |
| `failed` | 활성화 응답이 실패 |
| `unknown` | 활성화 응답을 해석하지 못해 확인 불능 |

`active` 가 아니면 모두 막는다 — 확인하지 못한 것을 통과로 두지 않는다. 기록을 읽지 못하는 것도 통과가 아니라
검사 불능으로 막는다.

**막혔을 때.**
- 다시 활성화한다(`activateObjects`·`activateByName`). 실패면 메시지를 읽고 소스를 고친다.
- Eclipse 등 다른 도구로 활성화했으면 `inactiveObjects` 를 불러 기록을 서버 상태에 맞춘다(서버에 비활성으로
  남지 않은 항목은 `active` 가 된다).
- 서버에서 지울 오브젝트면 `deleteObject` 로 지워 기록에서 뺀다.
- 기록 실패 표식 `.git/harness-adt-activation.error` 가 있으면 훅이 기록을 못 남긴 것이다. `inactiveObjects` 로
  남은 비활성이 없음을 사람이 확인한 뒤 그 파일을 지운다. Claude 는 이 파일을 지우지 않는다.

**한계.** `git -C 다른곳 push` 나 `cd other && git push` 는 현재 worktree 의 기록만 본다. Bash 로 `src/` 에
쓰는 경로(`cp`, 리다이렉션)는 막지 못한다(Write/Edit 만). 기록은 worktree 별이라 다른 worktree 에서 쓴 것은
보지 못한다. PostToolUse 는 이미 끝난 호출을 막을 수 없어 관문을 푸시와 `src/` 쓰기에 건다. 설계 상세와 실측은
`docs/status/archive-until-2026-10-13.md` 의 #190 절에 있다.

### 고객사 양식으로 Spec 쓰고 양식 파일 산출(#191·#192)

고객사 양식(xlsx)이 있는 프로젝트는 Spec 을 그 양식대로 쓰고 양식 파일로 뽑는다.

- **양식 지도.** Project Repository 의 `templates/forms/<양식>.yaml` 이 양식의 시트·칸·표·서술 위치와 산출
  파일명 규칙을 적는다. 형식 정본은 [`skills/spec/form-map.md`](skills/spec/form-map.md). 엔진은 `rules/` 만 읽으므로
  지도는 doc-guard 검사 대상이 아니고, 스킬이 읽는다.
- **작성(`/harness:spec`).** 지도가 있으면 쓸 양식을 매번 묻는다. 파일명에 들어가는 항목(예: 개발 ID, Title,
  처음엔 버전 0.1)부터 받아 산출될 파일명을 보여 주고 확인받은 뒤, 나머지를 Spec 의 `## 양식 항목` 절에 적는다.
  모르는 값은 추측하지 않고 묻고, 그래도 없으면 `미정` 이다. 지도가 없으면 기존처럼 `spec.md` 틀만 쓴다.
- **산출.** 작업본이 다 채워지면 `python -m checker.export` 로 지도의 템플릿 복사본에 값을 채워
  `산출.폴더` 에 만든다. 플러그인 설치본에는 엔진이 없어 `uvx` 로 받아 부른다. 명령은
  [`skills/spec/SKILL.md`](skills/spec/SKILL.md) 의 "양식 파일 산출" 절 그대로 쓴다. 옵션과 JSON 출력은
  `checker/README.md` 에 있다.
- **종료코드.** 0 산출함, 1 거부(필수 항목이 `미정`, `최대_행` 초과, 같은 이름 파일이 이미 있음 등 — 아무 파일도
  쓰지 않는다), 2 읽지 못함(작업본·지도·템플릿을 못 읽음, 지도에 없는 항목 — 검사 불능이지 통과도 위반도
  아니다). stdout 이 JSON 으로 읽히지 않으면 산출 불능으로 알린다.
- **이전 판은 덮어쓰지 않는다.** 내용이 바뀌면 양식의 변경이력 표에 행을 더해 버전을 올리고 다시 산출한다.
  파일명의 `v<버전>` 이 달라져 새 파일이 생기고 이전 판은 남는다.
- **경고(`warnings`).** 지도에 없는 템플릿 샘플(해당 없음 시트에 남은 그림·셀)은 산출이 지우지 않고 경고로
  알린다. 사람이 엑셀에서 열어 확인하고 지운다.
- **SRS 를 양식 xlsx 로(#228).** 지도 표에 `원본: SRS` 가 있으면(예: Backlog List) `/harness:srs` 가 지도의 열과
  템플릿 드롭다운 허용 값(`--list-values`)을 읽어 SRS 요구사항 표·상세 절을 쓰고, `docs/ssot/SRS.md` 를 직접 읽어
  xlsx 를 산출한다. 목록 밖 값은 종료코드 3(`warning`)과 행·열·값·허용 값으로 알린다. 형식은
  [`skills/spec/form-map.md`](skills/spec/form-map.md) 의 "원본이 SRS 인 지도".
- **xlsx 검사는 Actions 몫.** 훅은 바이너리를 못 보므로 산출한 xlsx 는 PR 에서 `pr-checks` 의 doc-guard 단계가 `검사_규칙` 으로 검사한다.

### 도구 자동 설치(#116)

Hook 은 검사 Engine 을 받는 데 uv, 명령을 읽는 데 jq, GitHub 작업에 gh, 커밋 전 비밀정보 검사에
gitleaks(`Gitleaks.Gitleaks`, #170)를 쓴다. 세션을 시작할 때 넷이 있는지 보고, **Windows 에서 winget 이 있으면 없는 것을
묻지 않고 설치한 뒤 알린다**(gh 를 뺀 나머지는 `--scope user` 로 먼저 시도). 다 있으면 아무
말도 하지 않는다.

- 설치한 프로그램은 이미 열린 세션의 PATH 에 없다. 실행 파일이 생긴 것을 확인한
  뒤 "Claude Code 를 새로 여십시오" 라고 안내한다.
- gh 는 설치만 한다. 로그인이 안 되어 있으면 `gh auth login` 을 안내한다.
- winget 이 없거나, 설치가 실패하거나(권한·회사 정책 포함), Windows 가 아니면
  설치 명령만 안내한다(macOS 는 `brew install uv jq gh gitleaks`).
- 실패한 도구는 24시간 동안 다시 설치를 시도하지 않는다. 기록은
  `${CLAUDE_PLUGIN_DATA:-$HOME/.claude/harness}/tool-install-failures` 에 있다.
- **설치에 쓰는 시간에는 상한이 있다(#131).** 세션 시작 훅은 600초에 끊기므로, 설치
  전체는 300초(`HARNESS_TOOLS_BUDGET`), winget 한 번은 90초(`HARNESS_INSTALL_TIMEOUT`)까지만
  기다린다. 상한을 넘으면 남은 도구 설치를 건너뛰고 "다음 세션을 열면 자동으로 다시
  시도합니다" 와 수동 설치 명령을 알린다. 상한에 걸린 것은 실패 기록에 넣지 않아 다음
  세션에 바로 다시 시도한다. 그 뒤의 동기화와 지난 경고 전달은 그대로 실행된다.
- **끄려면** 환경 변수 `HARNESS_NO_AUTO_INSTALL=1` 을 설정한다. 설치는 하지 않고
  안내만 한다.

### 규칙 5개

`rules/branching.md`, `rules/commit-and-pr.md`, `rules/delegation.md`,
`rules/governance.md`, `rules/issue-and-release.md`. 위 Skill 들이 이 문서를
`<스킬의 base directory>/../../rules/`로 참조한다.

### 공통 개발 규칙

`conventions/common.md` 에 CR-001 ~ CR-009 아홉 개 규칙(한글 이름 금지,
반복문 안 DB 조회 금지, SELECT * 금지, 비밀정보 금지, 표준 객체 직접 수정
금지, 하드코딩 금지, 오류 삼키기 금지, 이름 접두어는 프로젝트 conventions
로, 데이터를 바꾸는 앱은 권한 검사)을 담는다. 어느 Project Repository 에서나 같은 규칙이고, 프로젝트마다
다른 규칙(이름 접두어, SAP naming rule 등)은 그 저장소 `conventions/` 에
둔다. 두 규칙이 부딪히면 프로젝트 Convention 이 이기지만, CR-004(비밀
정보)만은 예외 없이 지킨다.

Plugin 은 세션에 상시 로드되는 지침을 넣을 수 없으므로, `session-start-sync.sh`
훅이 세션 시작마다 이 목록을 짧게 요약해 맥락에 넣어 준다. `/harness:spec`
이 만드는 Spec 의 `## 참조` 도 이 문서와 그 저장소 `conventions/` 를 함께
링크한다.

CR-001(한글 등 비ASCII 이름), CR-002(반복문 안 DB 조회), CR-003(SELECT *, ABAP 만),
CR-007(빈 CATCH, ABAP·JS/TS)은 기계로도 검사한다(#54, #81). CR-009(데이터를 바꾸는 앱의
권한 검사, #361)는 ABAP 에서 경고만 한다 — behavior pool 의 `FOR GLOBAL/INSTANCE AUTHORIZATION` 메서드가
`auth-allowed` 만 대입하거나 비어 있고 그 클래스에 `AUTHORITY-CHECK` 가 없을 때다. 훅은 막지 않고 저장 때
경고를 알려 주며(`allow_with_notice`), PR 코멘트에 경고로 나오고, risk-gate 가 "쓰기 앱인데 권한 검사 없음" 사유로 승인을 요구한다.
Spec 의 선택 절 `## 권한` 표가 검사 방식·권한 객체·활동·검사 기준 필드를 미리 정하게 한다. 검사 엔진은
`checker/code_rules.py` 이고, `pre_write_guard.py` 훅이 코드를 저장할 때,
MCP ADT 도구 경로는 `mcp_source_guard.py` 가, `pr-checks` 의 doc-guard 단계가
PR 마다 각각 부른다 — doc-guard 와 같은 엔진 저장소, 같은 관문 구조를 그대로 쓴다.
CR-005(표준 객체 수정)는 기본 대상인 Public Cloud(ABAP Cloud)에서 플랫폼이
막으므로 하네스가 검사하지 않는다. CR-004 는 아래 gitleaks 가 잡고, 나머지 CR-006, CR-008 은 사람이
리뷰로만 본다 — CR-006(하드코딩)은 프로젝트별 도메인 지식이 있어야 하고, CR-008 은
코드 검사 대상이 아니다. CR-004(비밀정보)는 이 검사기가 아니라 범용 시크릿 스캐너인
gitleaks 가 맡는다(아래 "비밀정보 검사").
SAP ATC 와의 관계는 `conventions/common.md` 의 "기본 대상과 ATC 와의 관계" 에
있다 — 080 실측으로 ATC 기본 variant 가 CR-002·CR-003 패턴을 잡지 않는 것을
확인했다(#85).

## 주의: 저장소에 같은 훅이 남아 있으면 두 번 돈다

이 플러그인을 설치한 저장소에 `.claude/hooks/` 와 `.claude/settings.json` 에
같은 훅(세션 시작 동기화, 세션 종료 안내, push 가드)이 이미 저장소 자체의
파일로 남아 있으면, 플러그인 훅과 저장소 훅이 **같은 이벤트에서 두 번** 돈다.
플러그인을 설치했다면 저장소 쪽 `.claude/hooks/` 의 같은 항목과
`.claude/settings.json` 의 같은 훅 등록을 지운다.

## 항상 지켜야 할 핵심은 각 저장소 CLAUDE.md 에 짧게 둔다

Plugin 은 세션에 상시 로드되는 지침(CLAUDE.md 같은 것)을 넣을 수 없다. "main
에는 직접 커밋하지 않는다", "푸시는 `/harness:deliver` 로 한다" 처럼 항상
지켜야 할 세 가지 원칙은 이 플러그인이 강제하더라도, 그 사실 자체는 각
Project Repository 의 CLAUDE.md 에 짧게 적어 둬야 세션이 매번 상기한다.

## 한계 — doc-guard 훅으로 잡을 수 없는 것

| 경로 | 훅이 도나 |
|---|---|
| Claude 가 md 문서를 쓰거나 고칠 때 | **돈다** |
| 팀원이 엑셀·워드·파워포인트에서 작업해 폴더에 넣을 때 | 안 돈다 |
| 사람이 편집기로 직접 저장할 때 | 안 돈다 |
| Bash 로 `cp`, `mv`, 리다이렉션을 쓸 때 | 안 돈다 |

**그래서 이 훅만으로는 절반이다.** 나머지는 GitHub Actions 가 커밋 시점에
잡는다. 문서 저장소 쪽에서 `.github/workflows/pr-checks.yml` 로 재사용
워크플로를 부른다.

## Skill: /harness:scaffold

새 고객사 Project Repository 를 처음 만들었을 때, 검사기가 기대하는 표준
구조 — 저장소 루트의 `templates/` 와 `rules/`, `docs/ssot/SRS.md`,
`conventions/`, `audit/`, `env/`, 그리고 PR 검사(`pr-checks.yml`)·승인 재판정(`pr-review.yml`)·
병합 뒤 검사(`main-checks.yml`)를 부르는 호출 워크플로 셋 — 를 한 번에 만들어 준다(#420).
`.github/workflows/ai-review.yml` 은 위험한 PR 을 포함해 코드(`src/`)를 바꾼 PR 에 Claude AI 리뷰를 돌리는
호출 워크플로로(`paths: ['src/**']`, `risk-gate.yaml` 의 `ai_review_paths` 와 짝, #411), **기본은 꺼짐**이다(#125, #360). 켜려면 `claude setup-token` 으로 만든 토큰을
`gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <owner/repo>` 로 등록하고 `.github/risk-gate.yaml`
의 `ai_review` 를 `true` 로 바꾼다. 심각한 지적이 나오거나 큰 PR 을 일부만 봤으면 `ai-review`
검사가 실패해 risk gate 가 "승인 필요" 로 판정한다(위험한 PR 은 AI 리뷰에 더해 승인자 Approve 도 필요).
단 새로 들어온 줄에 비밀값 패턴이 보이면 diff 를 외부 AI 에 보내지 않으려고 리뷰를 돌리지 않고, `ai-review`
를 "검사 불능 - 비밀값 의심" 으로 실패시킨다(**값**은 어디에도 남지 않는다. 위치(파일:줄)는 risk-gate 사유처럼 job 로그에 남고 코멘트·표식에는 패턴 이름만
적는다. 승인자가 직접 확인). 변경이 너무 커서 비밀값 검사를 못 한 경우는 이 예외가 아니라 리뷰가 그대로 돈다
(그 파일 안의 비밀값은 AI 리뷰로 나갈 수 있다). 엔진이 옛 판이라 비밀값 확인 결과를 내지 않으면 검사 불능으로 실패한다.
`.claude/settings.json` 도 함께 만들어, 이 저장소 폴더를 여는 팀원이 별도
설치 없이 blueward-harness 마켓플레이스와 harness Plugin 설치 안내를 받게
한다(#89) — 이미 그 파일이 있으면 통째로 덮어쓰지 않고 없는 두 항목만
채워 넣는다. `conventions/` 에는 블루어드 사내 표준 두 개(`naming.md` — SAP Public
Cloud & BTP 이름 규칙, `cap-ui5.md` — CAP·SAPUI5 개발 표준)를 기본값으로 함께
둔다(#187). 고객사 표준이 정해지면 그 파일을 고치고, 이미 있는 파일은 덮어쓰지
않는다. 자세한 절차는 `skills/scaffold/SKILL.md` 를 읽는다.

`pr-checks` 의 pr-queue 단계는 Claude 를 안 쓰는 사람도 병합 순서를 알게 한다(#370, 별도 호출 워크플로는 #420 에서 없어졌다).
이벤트(PR 열림·갱신·초안 전환·닫힘·본문 수정, 리뷰, main push)마다 열린 PR 전체를 한 번 계산해(검사 결과가 바뀐 것만으로는 돌지
않아 코멘트의 검사 상태는 다음 이벤트까지 낡을 수 있다 — 정확한 지금 상태는 `/harness:prs`), PR 마다 순서·앞에
병합할 PR·상태·다음 할 일을 담은 코멘트 하나(`<!-- pr-queue -->`)를 갱신하고(내용이 같으면 쓰지 않는다) 커밋
status `merge-order` 를 단다(앞 PR 이 열려 있으면 pending 노란 대기, 없으면 success, 순서를 정하지 못하면 error).
앞 PR 이 병합돼 차례가 된 PR 은 작성자를 멘션하고, `TEAMS_PLUGIN_ALERT_WEBHOOK` secret 이 있으면 Teams 로도
알린다(없으면 건너뜀). 무료 요금제라 노란 대기여도 Merge 버튼은 잠기지 않는다. 호출 쪽(`pr-checks.yml` caller) permissions 는
`contents: read`, `pull-requests: write`, `issues: write`, `statuses: write`, `checks: read`, `actions: read`(열린 PR 의 검사 결과와 그 워크플로 실행을
읽는다 — 없으면 "Resource not accessible by integration" 으로 실패). GitHub 를 못 읽으면 순서를 계산하지 못해 status 를 쓰기
전에 끝나므로 `merge-order` status 는 이전 값 그대로 남고, job 은 초록이며 경고만 남는다(이 단계는 판정에 넣지 않는다).
main 병합 뒤의 차례 알림은 PR 이 닫힐 때 도는 이 단계가 맡는다(`main-checks` 에는 이 단계가 없다, #508).
기존 Project Repository 는 옛 호출 파일 다섯을 지우고 새 호출 파일 셋을 넣어야 받는다.

## 비밀정보 검사(#159)

CR-004 는 `pr-checks`·`main-checks` 의 gitleaks 단계가 PR·main 커밋마다 gitleaks 로
검사한다(`/harness:scaffold` 가 호출 워크플로를 만든다). gitleaks-action 은 조직 계정에 라이선스
키가 필요해 쓰지 않고, 릴리즈 바이너리를 버전과 sha256 으로 고정해 받는다. PR 은 base..head 커밋
범위만, main push 는 그 push 범위만 훑고, 값은 `--redact` 로 가려서 출력한다. 위험도 검사
(risk-gate)의 비밀값 기준은 그대로 두고 별도 빨간불로 병행한다.

- **세 갈래 판정.** 유출 발견(위반), 통과, 검사 불능(gitleaks 오류, 설정 오류, 검사 범위를 못 찾음)이
  서로 다른 메시지로 갈린다. 검사 불능을 통과로 두지 않는다. 판정은 `scripts/gitleaks_scan.sh`.
- **기본 설정**은 `checker/gitleaks/harness.toml` — gitleaks 기본 규칙에 SAP 로그온 쿠키
  `MYSAPSSO2`, 세션 쿠키 `SAP_SESSIONID_<SID>_<client>`, SAP 접속 비밀번호 대입 규칙을 더했다.
- **Project Repository 가 설정을 바꾸려면** 저장소 꼭대기에 `.gitleaks.toml` 을 둔다. 있으면 하네스
  기본 설정 대신 그것만 쓰므로, 하네스 규칙을 유지하려면 워크플로가 엔진을 내려받는 자리를 이어받는다.
  PR 은 자기가 낸 파일이 아니라 **base 커밋의 `.gitleaks.toml`** 로 검사한다(PR 이 자기 allowlist 로
  자기 비밀값을 통과시키지 못하게). PR 이 이 파일을 바꾸면 경고가 뜨고, 변경은 병합 뒤부터 적용된다.
  base 에 파일이 없으면 하네스 기본 설정을 쓴다.

  ```toml
  [extend]
  path = ".harness-engine/checker/gitleaks/harness.toml"

  [allowlist]
  paths = ['''^docs/samples/''']
  ```

  `[extend] path` 는 저장소 꼭대기(현재 폴더) 기준이다.

### 커밋 전 검사(#170)

PR 에서 막혀도 원격으로 올리는 순간 비밀값은 이미 GitHub 에 올라간다(그 값은 폐기·교체해야 한다). 그래서
`pre-bash-git-guard.sh` 가 **Claude 의 `git commit`** 에도 같은 규칙으로 staged 변경을 검사한다. 사람이
터미널에서 직접 한 커밋은 이 훅을 거치지 않으므로 Actions 가 잡는다. 커밋일 때만 gitleaks 를 부른다
(앞에 `cd x &&` 같은 git 이 아닌 조각이 있어도 잡는다). `git add x && git commit` 처럼 commit 앞에 git 명령이
  있으면 훅 시점의 staged 가 커밋될 내용과 달라 "검사 불능" 으로 막는다 — `git add` 를 먼저 따로 실행한 뒤
  `git commit` 을 별도 명령으로 실행한다(읽기 전용 status·diff·log·show·rev-parse 는 예외).

- **판정.** `gitleaks git --pre-commit --staged --redact --exit-code 2`. 종료 0 은 통과, 2 는 "비밀값 발견"
  (규칙·파일·줄만 알리고 값은 가린다), 그 밖은 "검사 불능"으로 서로 다른 문구로 막는다. gitleaks 가 없을
  때도 "검사 불능"이며 `winget install --id Gitleaks.Gitleaks -e` 를 안내한다(세션 시작 때 자동 설치도
  시도한다). staged 변경이 없으면 검사할 것이 없어 gitleaks 를 부르지 않는다.
- **설정.** 저장소 꼭대기의 `.gitleaks.toml` 이 있으면 그것, 없으면 하네스 기본 설정이다. 플러그인 설치본엔
  `checker/` 가 없어 훅은 `hooks/gitleaks-harness.toml`(`checker/gitleaks/harness.toml` 과 같아야 하고 테스트가
  지킨다)을 쓴다. `[extend] path` 는 현재 폴더 기준이라, 훅은 그 복사본을 `.harness-engine/checker/gitleaks/harness.toml`
  자리에 둔 임시 폴더에서 gitleaks 를 불러 Actions 용 `.gitleaks.toml` 이 로컬에서도 풀린다. PR 과 달리 로컬은
  작업 폴더의 `.gitleaks.toml` 을 쓴다.
- **staged 밖 변경이 들어가는 커밋은 막는다.** `-a`, `--all`, `-i`, `--include`, `-o`, `--only` 는 working tree
  내용을 커밋에 넣어 staged 만 보는 검사로는 범위를 알 수 없다(검사 불능). `git add` 로 올린 뒤 옵션 없이
  커밋한다. `--amend` 는 새로 들어가는 것이 staged 변경뿐이라 그대로 검사한다. 경로를 직접 지정하는
  `git commit 파일명` 은 알아내지 못한다(Actions 가 잡는다). merge·rebase·cherry-pick·revert 진행 중이거나
  git 저장소가 아닌 곳은 검사하지 않고 지나간다.
- **건너뛰기는 사람만.** 훅 프로세스의 환경 변수 `HARNESS_SKIP_SECRET_SCAN=1` 일 때만 건너뛰며, 건너뛰면
  "비밀정보 검사를 건너뜀" 을 알림으로 남긴다. 명령 앞에 붙인 `HARNESS_SKIP_SECRET_SCAN=1 git commit` 은 훅의
  환경이 아니므로 무시한다. Claude 는 이 변수를 스스로 켜지 않는다(`rules/governance.md`).
- 테스트는 `checker/tests/test_git_guard_secret_scan.py`(가짜 gitleaks 로 분기, `GITLEAKS_BIN_REAL` 이 있으면
  진짜 바이너리로 SAP 규칙·설정 이어받기까지).

## Audit

`/harness:scaffold` 가 `audit/changes/`(변경 기록)와 `audit/ledger/`(진행
원장)의 템플릿과 doc-guard 규칙도 함께 만든다(#43). 변경 기록은
`YYYYMMDD-<요약>.md` 로 기록 하나에 파일 하나를 써 여러 사람이 동시에
기록해도 PR 이 충돌하지 않게 하고, 진행 원장은 프로그램 하나에 파일 하나로
개발 건의 진행 상태를 표로 담는다. `/harness:srs` · `/harness:start` ·
`/harness:spec` · `/harness:deliver` Skill 이 이 형식으로 기록을 남기고, 사람이
직접 적어도 된다(#173: feat·fix 작업을 start 하면 원장에 개발 건 줄이 `진행` 으로
생기고 Spec 칸은 `-` 다. spec 이 같은 번호로 Spec 칸을 채우고, deliver 가 `리뷰`
로 바꾸되 대표 `[DEV-xxx]` 이슈를 Closes 하는 PR 이면 처음부터 `완료` 로 써 PR 에 담는다. 하위 작업 PR 은 `리뷰` 이고 `완료` 는 사람이 쓴다. 병합 뒤 `ledger-complete` 는 원장을 쓰지 않고 `완료` 인지만 확인한다. #346, #445). 형식에 맞지 않는 기록(파일 이름, 필수 절)은
`rules/audit-changes.yaml` 과 `rules/audit-ledger.yaml` 이 doc-guard 로
검사한다.

## SRS 변경 승인(#49)

`docs/ssot/`(SRS) 를 바꾼 PR 은 작성자가 아닌 사람의 Approve 가 있어야 한다.
Project Repository 는 개인 무료 계정의 비공개 저장소라 브랜치 보호·ruleset·
CODEOWNERS 를 강제할 수 없으므로(무료 요금제 한계), 이 규칙은 "막는다" 가
아니라 "승인 없이 넘어가면 반드시 드러나고 기록에 남는다" 로 세 겹을 쌓는다.
세 곳 모두 같은 판정 로직(`checker.ssot_approval`)을 부르므로 "승인됐다" 의
의미가 갈라지지 않는다.

1. **PR 검사** — `pr-checks.yml`(PR 을 열거나 고칠 때)과 `pr-review.yml`(리뷰가 달릴 때)의
   ssot-approval 단계(`/harness:scaffold` 가 호출 파일을 만든다)가 판정하고, 승인이
   없으면 job 을 실패시키고 PR 코멘트로 사유를 알린다.
2. **merge 뒤 감지** — `main-checks.yml` 이 `push` 마다 그 커밋의 PR 을 찾아, SRS
   를 바꿨는데 승인이 없었으면 이슈를 연다. PR 없이 main 에 직접 push 된
   경우도 잡는다.
3. **harness 훅** — `pre-bash-git-guard.sh` 가 `gh pr merge` 명령을 가로채,
   대상 PR 이 SRS 를 바꿨는데 승인이 없으면 거부한다. 판정 자체를 할 수
   없으면(네트워크 없음, `gh`·`uvx` 없음) 통과가 아니라 거부로 답한다
   (CLAUDE.md 원칙 7).

승인자 목록은 `.github/ssot-approvers` 에 적는다. 한 줄에 `<PR 작성자>: <승인자> <승인자> ...`
(공백이나 쉼표로 나눈다, `@`·대소문자 무시, `#` 뒤는 주석). 작성자 자리의 `*` 는 전용 줄이
없는 모든 작성자이고, 콜론 없이 아이디만 적은 옛 형식 줄은 `*:` 줄과 같다. 어떤 작성자의
전용 줄이 있으면 그 줄의 사람만, 없으면 `*:` 줄과 옛 형식 줄의 합이 승인자다. 작성자 본인은
늘 승인자에서 빠진다.

```
jaeheeMin: CSH-DOT123 Blueward-Huiseong
*: jaeheeMin
```

파일이 비어 있으면(주석뿐이면) 작성자가 아닌 누구의 승인이든 인정한다. 내용이 있는데 어떤
작성자의 PR 을 승인할 사람이 없으면 그 작성자의 PR 은 미승인이다.

승인은 PR 의 **현재 최신 커밋**에 대한 것일 때만 인정한다(#119). 승인한 뒤 새
커밋이 올라오면 그 승인은 낡은 것이라 다시 Approve 를 받아야 한다(무료
요금제에는 "새 커밋이 올라오면 승인 취소" 기능이 없어 검사기가 대신한다).

**한계.** 무료 요금제에서는 위 세 겹 중 어느 것도 GitHub 화면의 merge 버튼
자체를 잠그지 못한다 — PR 검사 실패를 무시하고 merge 하거나, harness 훅이
설치되지 않은 곳(다른 사람의 PC, GitHub 웹 화면)에서 merge 하면 그대로
넘어간다. 그런 경우에도 **merge 뒤 감지가 반드시 이슈를 열어 드러낸다는
것**이 이 설계의 마지막 안전망이다. 또한 "작성자가 아닌 사람" 만 볼 뿐,
승인자 본인이 공모해 스스로에게 유리하게 승인하는 것(형식은 지키되 내용은
부실한 승인)은 이 검사가 가려내지 못한다 — 그것은 사람이 하는 검토의 몫이다.
