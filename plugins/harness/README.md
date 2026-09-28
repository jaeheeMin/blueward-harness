# harness 플러그인

고객사 Project Repository 에 설치해 쓰는 Blueward 하네스다. 새 저장소의 표준
구조를 만들고, 문서가 템플릿을 따르는지 검사하고(doc-guard), 협업 규칙과
`/harness:start` · `/harness:deliver` · `/harness:wrapup` Skill 을 한 번에 제공한다.

```
plugins/harness/
  .claude-plugin/plugin.json   플러그인 정의
  hooks/
    hooks.json                 네 훅을 선언
    pre_write_guard.py         문서 검사(doc-guard) — Write/Edit 직전에 막을지 정한다
    pre-bash-git-guard.sh      push 가드 — 스킬을 거치지 않은 git push 를 막는다
    session-start-sync.sh      세션 시작 때 원격과 동기화하고 남은 경고를 전한다
    stop-deliver.sh            세션 종료 때 커밋 안 된 변경을 알린다
  skills/
    start/SKILL.md             /harness:start — 이슈와 브랜치 생성
    deliver/SKILL.md           /harness:deliver — 커밋·동기화·푸시·PR
    wrapup/SKILL.md            /harness:wrapup — 남은 작업의 이슈화
    scaffold/                  /harness:scaffold — Project Repository 표준 구조 생성
    prd/SKILL.md               /harness:prd — PRD 작성·수정
    spec/SKILL.md              /harness:spec — 개발 Spec 작성·수정
  rules/                       위 Skill 이 참조하는 협업 규칙 5개
  conventions/common.md        어느 저장소에서나 같은 공통 개발 규칙(CR-001 ~ CR-008)
```

플러그인 이름은 `harness` 지만, 문서 검사 기능 자체는 여전히 **doc-guard** 라고
부른다. 훅 스크립트 이름(`pre_write_guard.py`), 검사 메시지("doc-guard: ..."),
문서 저장소가 불러 쓰는 재사용 워크플로(`.github/workflows/doc-guard.yml`),
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
  "enabledPlugins": ["harness@blueward-harness"]
}
```

플러그인은 저장소가 아니라 **사람** 에게 설치된다. 한 번 설치하면 어느
저장소를 열든 동작한다.

## 제공하는 것

### Skill 6개

플러그인 스킬은 이름 앞에 플러그인 이름이 붙으므로 아래 이름으로 나타난다.

| Skill | 하는 일 |
|---|---|
| `/harness:start` | 작업을 시작한다. 이슈를 만들고 규칙에 맞는 브랜치를 만든다 |
| `/harness:deliver` | 작업을 마무리한다. 커밋·동기화·푸시·PR 생성을 한 번에 |
| `/harness:wrapup` | 세션에서 끝내지 못한 작업을 이슈로 남긴다 |
| `/harness:scaffold` | 새 Project Repository 에 표준 구조를 만든다 |
| `/harness:prd` | PRD 를 새로 쓰거나, 요구사항이 바뀌었을 때 고친다 |
| `/harness:spec` | PRD 요구사항으로 개발 Spec 을 만들거나, PRD 가 바뀌어 고친다 |

### 훅 4개

| 훅 | 시점 | 하는 일 |
|---|---|---|
| `pre_write_guard.py` | `PreToolUse` (Write\|Edit) | 문서가 템플릿을 벗어나면 저장을 막는다(doc-guard). 코드(`.abap`, `.js`/`.ts`, `.cds`, `.asbdef`)는 공통 개발 규칙 CR-001·CR-002·CR-003·CR-007 을 어기면 막는다(#54, #72, #81. BDEF 는 CR-001 만, CR-003·CR-007 은 ABAP·JS/TS 만) |
| `pre-bash-git-guard.sh` | `PreToolUse` (Bash\|PowerShell) | 스킬을 거치지 않은 `git push` 와 main 직접 커밋을 막는다. `gh pr merge` 대상 PR 이 PRD 를 바꿨는데 승인이 없어도 막는다(#49) |
| `session-start-sync.sh` | `SessionStart` | 원격과 동기화하고 지난 세션에서 남은 경고를 전한다 |
| `stop-deliver.sh` | `Stop` | 커밋되지 않은 변경이 남았으면 `/harness:deliver` 를 안내한다 |

### 규칙 5개

`rules/branching.md`, `rules/commit-and-pr.md`, `rules/delegation.md`,
`rules/governance.md`, `rules/issue-and-release.md`. 위 Skill 들이 이 문서를
`<스킬의 base directory>/../../rules/`로 참조한다.

### 공통 개발 규칙

`conventions/common.md` 에 CR-001 ~ CR-008 여덟 개 규칙(한글 이름 금지,
반복문 안 DB 조회 금지, SELECT * 금지, 비밀정보 금지, 표준 객체 직접 수정
금지, 하드코딩 금지, 오류 삼키기 금지, 이름 접두어는 프로젝트 conventions
로)을 담는다. 어느 Project Repository 에서나 같은 규칙이고, 프로젝트마다
다른 규칙(이름 접두어, SAP naming rule 등)은 그 저장소 `conventions/` 에
둔다. 두 규칙이 부딪히면 프로젝트 Convention 이 이기지만, CR-004(비밀
정보)만은 예외 없이 지킨다.

Plugin 은 세션에 상시 로드되는 지침을 넣을 수 없으므로, `session-start-sync.sh`
훅이 세션 시작마다 이 목록을 짧게 요약해 맥락에 넣어 준다. `/harness:spec`
이 만드는 Spec 의 `## 참조` 도 이 문서와 그 저장소 `conventions/` 를 함께
링크한다.

CR-001(한글 등 비ASCII 이름), CR-002(반복문 안 DB 조회), CR-003(SELECT *, ABAP 만),
CR-007(빈 CATCH, ABAP·JS/TS)은 기계로도 검사한다(#54, #81). 검사 엔진은
`checker/code_rules.py` 이고, `pre_write_guard.py` 훅이 코드를 저장할 때,
MCP ADT 도구 경로는 `mcp_source_guard.py` 가, `.github/workflows/doc-guard.yml` 이
PR 마다 각각 부른다 — doc-guard 와 같은 엔진 저장소, 같은 관문 구조를 그대로 쓴다.
나머지 CR-004~CR-006, CR-008 은 사람이 리뷰로만 본다 — CR-004(비밀정보)는 범용
시크릿 스캐너가, CR-005(표준 객체 수정)는 SAP 메타데이터가, CR-006(하드코딩)은
프로젝트별 도메인 지식이 있어야 하고, CR-008 은 코드 검사 대상이 아니다.

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
잡는다. 문서 저장소 쪽에서 `.github/workflows/doc-guard.yml` 로 재사용
워크플로를 부른다.

## Skill: /harness:scaffold

새 고객사 Project Repository 를 처음 만들었을 때, 검사기가 기대하는 표준
구조 — 저장소 루트의 `templates/` 와 `rules/`, `docs/ssot/PRD.md`,
`conventions/`, `audit/`, `env/`, 그리고 PR·main 커밋마다 doc-guard 를
부르는 `.github/workflows/doc-guard.yml` — 를 한 번에 만들어 준다. 자세한
절차는 `skills/scaffold/SKILL.md` 를 읽는다.

## Audit

`/harness:scaffold` 가 `audit/changes/`(변경 기록)와 `audit/ledger/`(진행
원장)의 템플릿과 doc-guard 규칙도 함께 만든다(#43). 변경 기록은
`YYYYMMDD-<요약>.md` 로 기록 하나에 파일 하나를 써 여러 사람이 동시에
기록해도 PR 이 충돌하지 않게 하고, 진행 원장은 프로그램 하나에 파일 하나로
개발 건의 진행 상태를 표로 담는다. `/harness:prd` · `/harness:spec` ·
`/harness:deliver` Skill 이 이 형식으로 기록을 남길 예정이고, 사람이 직접
적어도 된다. 형식에 맞지 않는 기록(파일 이름, 필수 절)은
`rules/audit-changes.yaml` 과 `rules/audit-ledger.yaml` 이 doc-guard 로
검사한다.

## PRD 변경 승인(#49)

`docs/ssot/`(PRD) 를 바꾼 PR 은 작성자가 아닌 사람의 Approve 가 있어야 한다.
Project Repository 는 개인 무료 계정의 비공개 저장소라 브랜치 보호·ruleset·
CODEOWNERS 를 강제할 수 없으므로(무료 요금제 한계), 이 규칙은 "막는다" 가
아니라 "승인 없이 넘어가면 반드시 드러나고 기록에 남는다" 로 세 겹을 쌓는다.
세 곳 모두 같은 판정 로직(`checker.ssot_approval`)을 부르므로 "승인됐다" 의
의미가 갈라지지 않는다.

1. **PR 검사** — `.github/workflows/ssot-approval.yml`(`/harness:scaffold`
   가 만든다)이 `pull_request` 와 `pull_request_review` 마다 판정하고, 승인이
   없으면 job 을 실패시키고 PR 코멘트로 사유를 알린다.
2. **merge 뒤 감지** — 같은 워크플로가 `push` 마다 그 커밋의 PR 을 찾아, PRD
   를 바꿨는데 승인이 없었으면 이슈를 연다. PR 없이 main 에 직접 push 된
   경우도 잡는다.
3. **harness 훅** — `pre-bash-git-guard.sh` 가 `gh pr merge` 명령을 가로채,
   대상 PR 이 PRD 를 바꿨는데 승인이 없으면 거부한다. 판정 자체를 할 수
   없으면(네트워크 없음, `gh`·`uvx` 없음) 통과가 아니라 거부로 답한다
   (CLAUDE.md 원칙 7).

승인자 목록은 `.github/ssot-approvers` 에 GitHub 아이디로 한 줄씩 적는다.
비어 있으면 작성자가 아닌 누구의 승인이든 인정한다.

**한계.** 무료 요금제에서는 위 세 겹 중 어느 것도 GitHub 화면의 merge 버튼
자체를 잠그지 못한다 — PR 검사 실패를 무시하고 merge 하거나, harness 훅이
설치되지 않은 곳(다른 사람의 PC, GitHub 웹 화면)에서 merge 하면 그대로
넘어간다. 그런 경우에도 **merge 뒤 감지가 반드시 이슈를 열어 드러낸다는
것**이 이 설계의 마지막 안전망이다. 또한 "작성자가 아닌 사람" 만 볼 뿐,
승인자 본인이 공모해 스스로에게 유리하게 승인하는 것(형식은 지키되 내용은
부실한 승인)은 이 검사가 가려내지 못한다 — 그것은 사람이 하는 검토의 몫이다.
