# 진행 상황과 미결 사항

CLAUDE.md 에서 옮겨 온 진행 이력이다. 매 세션 자동으로 읽히지 않으므로, 해당 영역(훅, Actions, 스캐폴드, 승인 검사, 코드 검사 등)을 건드리기 전에 관련 절을 읽는다.

## 지금 어디까지 왔나

검사 엔진이 동작한다. 규칙 종류 일곱(파일명, 위치, 필수 절, 필수 시트, 표 헤더, 슬라이드
레이아웃, 외부 흔적)과 리더 넷(md, docx, xlsx, pptx), `check` CLI 가 들어 있다.

**관할 안의 자리표시 파일은 건너뛰고 리포트에 남긴다(#15).** `.gitkeep` 처럼 도구가
자동으로 흘려 두는 파일은 위반도 검사 불능도 아니라 "건너뛴 파일"로 따로 세고
이유를 남긴다. 반면 `.hwp` 처럼 읽을 리더가 없는 진짜 문서 형식은 이 예외를 타지
않고 여전히 검사 불능(설정 오류)이다 — 둘을 섞으면 리더가 필요한 산출물이 검사
없이 통과한다(원칙 7).

외부 흔적 규칙만 묻는 것이 다르다. 나머지는 "이 회사 템플릿과 룰대로 썼나" 를 보지만
그것은 "이거 내보내도 되나" 를 본다. 걷어내는 것은 `--clean` 으로 사람이 직접 부른다.

**Actions 경로는 검증되었다.** 템플릿과 규칙이 함께 든 저장소(시험용
`client-docs`)의 PR 에 일부러 위반 문서를 올려, 슬라이드 레이아웃 위반과
파일명 위반을 잡아 PR 을 실패시키는 것까지 확인했다.

**훅이 엔진을 얻는 경로를 고쳤다(#12).** 예전에는 훅이 저장소 안의 `checker` 를
`sys.path` 로 끌어다 썼는데, 설치본에는 그 저장소 자체가 없어 `ModuleNotFoundError`
로 죽었고 죽으면 조용히 통과시켰다. 이제 훅은 `checker` 를 import 하지 않고(회사
폴더를 찾는 로직만 작게 옮겨 적었다), 검사 엔진은 매번 `uvx` 로 이 저장소의 GitHub
원격에서 받아 온다. 엔진을 받거나 실행하지 못하면(네트워크 없음, `uv` 없음,
알 수 없는 종료코드, 예상 못한 예외 포함) 통과가 아니라 거절로 답하도록 만들었다.
설치본을 저장소 밖 임시 폴더로 복사해 흉내 낸 테스트(`checker/tests/test_hook.py`)
로 확인했지만, 실제 마켓플레이스 설치본에서 발동시켜 본 것은 아직 아니다. 한글
경로 결함(#14)은 고쳤다 — 입출력 인코딩을 `_force_utf8_io()` 한 곳으로 모아 stdin
만 빠지는 일이 다시 생기지 않게 했고, 경로 문자열에 U+FFFD 나 서로게이트가 섞여
들어와 관할 판단 자체가 안 될 때를 진짜 관할 밖과 구분해 거절하도록 했다(원칙 7).
한글이 겹으로 섞인 경로와 한글 파일명, 깨진 경로를 각각 잡는 테스트를 더했다.

**검사 불능이 위반과 눈에 띄게 갈린다(#13).** 둘 다 job 이나 훅을 막는 것은 같지만
받는 사람이 다르므로, 훅의 거절 사유와 Actions 의 PR 코멘트·어노테이션·Step
Summary 모두 제목부터 "❌ 템플릿 위반"(문서를 고친다)과 "⚠️ 검사 불능"(규칙·설정을
고친다, 문서 문제가 아니다)으로 갈라 답한다. 기준점 아래에 있지 않은 파일이 관할
밖으로 위장되던 결함(`checker/cli.py::_relative`)도 설정 오류로 고쳐, 판단 실패를
통과로도 관할 밖으로도 뭉개지 않는다.

**Project Repository 에 붙이는 절차는 `/scaffold` Skill 이 만든다.** 엔진은
문서 위에서 `templates/` 와 `rules/` 를 찾으므로 두 폴더를 Project Repository
에 두기만 하면 동작한다. `/scaffold` Skill 이 그 구조(`templates/`, `rules/`,
`docs/ssot/`, `conventions/`, `audit/`, `env/`)와 caller workflow
(`.github/workflows/doc-guard.yml`)를 한 번에 만든다. 다만 Plugin 설치본에서
실제로 불러 본 적은 아직 없다 — 훅과 같은 결함(아래)을 이 경로도 안고 있을
수 있다.

**Actions 는 규칙 폴더가 없는 저장소를 통과시키지 않는다(#24).** `templates/` 와
`rules/` 를 함께 둔 폴더가 하나도 없는데 바뀐 문서가 있으면 `check_changed.py` 가
통과 대신 검사 불능으로 끝낸다.

열려 있는 결함은 GitHub 이슈로 관리한다. 검사 불능 구분(#13), 규칙 폴더 가드(#24),
한글 경로 결함(#14)은 마쳤고, 우선순위는 훅 배선을 실제 마켓플레이스 설치본에서
검증하는 것이 앞이다.

**협업 Skill·규칙·훅을 harness Plugin 에 담았다(#37).** `/start`, `/deliver`,
`/wrapup` Skill 과 공통 규칙 5개, 그것을 강제하는 훅 3개(push 가드, 세션 시작
동기화, 세션 종료 안내)를 `plugins/harness/` 에 옮겼다. **저장소 쪽 정리와 이
저장소 자신의 플러그인 설치를 마쳤다(#39).** 이 저장소가 쓰던 `.claude/skills`,
`.claude/hooks`, 루트 `rules/` 의 옛 사본은 지웠고, 이 저장소도 다른
저장소와 같은 방식으로 `.claude/settings.json` 의 `enabledPlugins` 로
`harness` 플러그인을 설치해 쓴다.

**Audit 기록 형식을 정하고 `/scaffold` 규칙으로 강제한다(#43).** 변경 기록
(`audit/changes/`)과 진행 원장(`audit/ledger/`)의 템플릿과 doc-guard 규칙을
스켈레톤에 추가해, 형식에 안 맞는 기록을 파일명 규칙과 필수 절 규칙이
위반으로 잡는다.

**`/harness:prd` Skill 을 추가했다(#44).** PRD 틀(`templates/harness/PRD.md`)과
그 필수 절을 강제하는 `rules/ssot.yaml` 을 스켈레톤에 추가해, PRD 를 새로
쓰거나 고칠 때 요구사항 목록과 변경 근거를 Audit 기록으로 남기게 했다.

**`/harness:spec` Skill 을 추가했다(#45).** Spec 틀(`templates/harness/
spec.md`)과 `rules/spec.yaml` 을 스켈레톤에 추가해, PRD 의 REQ 를 근거로
`docs/spec/DEV-xxx-<요약>.md` 를 만들고 진행 원장에 개발 건으로 등록하게
했다. `/harness:deliver` 도 관련 개발 건을 찾아 PR 에 진행 원장 링크를 넣고
PR 을 만든 뒤 원장 상태를 갱신하게 했다.

**무료 요금제에서 PRD 변경 PR 의 승인을 검사하고 기록한다(#49).** Project
Repository 는 개인 무료 계정의 비공개 저장소라 브랜치 보호·CODEOWNERS 를 쓸
수 없어, merge 자체를 서버 쪽에서 막을 방법이 없다. 그래서 "막는다" 대신
"승인 없이 넘어가면 반드시 드러나고 기록에 남는다" 를 세 겹으로 쌓았다 —
재사용 워크플로 `.github/workflows/ssot-approval.yml` 이 PR 마다 승인을
검사해 실패시키고, 같은 워크플로가 main 에 push(=merge)될 때마다 다시
판정해 승인 없이 들어온 것을 이슈로 열고, `pre-bash-git-guard.sh` 훅이
`gh pr merge` 자체를 가로채 미승인 PR 의 merge 를 거부한다. 판정 로직
(`checker/ssot_approval.py`)은 셋이 공유하고, 훅은 `uvx` 로 `python -m
checker.ssot_approval` 을 불러 GitHub Actions 와 같은 판정을 쓴다(#12 와
같은 사정). **한계** — 이 셋 중 어느 것도 GitHub 화면의 merge 버튼 자체를
잠그지 못하므로, PR 검사 실패를 무시하고 merge 하거나 훅이 없는 곳에서
merge 하면 그대로 넘어간다. 그런 경우에도 merge 뒤 감지가 이슈를 열어
드러내는 것이 마지막 안전망이고, 승인자 본인이 형식만 갖춰 부실하게
승인하는 것은 이 검사가 가려내지 못한다 — 그것은 사람의 검토가 할 몫으로
남는다.

**공통 개발 규칙을 harness Plugin 에 담고 세션과 Spec 에 연결했다(#53).**
`plugins/harness/conventions/common.md` 에 CR-001 ~ CR-008 을 적었고,
세션 시작 훅이 그 목록을 매번 요약해 맥락에 넣으며, `/harness:spec` 과
스켈레톤 `conventions/README.md` 가 이 문서를 링크한다.

**CR-001(한글 등 비ASCII 이름)과 CR-002(반복문 안 DB 조회)를 코드 저장 시 기계로
검사한다(#54).** 새 엔진 모듈 `checker/code_rules.py` 가 ABAP, JS/TS(CAP), CDS 를
본다 — 규칙이 아니라 데이터인 `checker/code_checks.yaml` 이 언어마다 어느 CR 을
적용할지 정한다(원칙 2). ABAP 은 주석(`*`, `"`)과 문자열(`'...'`, `` `...` ``,
`|...|`)을 가려내고 LOOP/DO/WHILE 과 SELECT...ENDSELECT 의 중첩을 세어 그 안의
SELECT·OPEN CURSOR 를 잡는다. JS/TS 는 `for`/`while`/`.forEach`/`.map` 의 몸통
`{ ... }` 안에서 `SELECT.from` 류 호출을 잡는 휴리스틱이라 중괄호 없는 한 줄
반복문이나 이름만 넘긴 콜백은 놓칠 수 있다 — 놓치는 쪽으로 기운 결정이다.
`harness:allow CR-00N <이유>` 주석으로 예외를 남길 수 있고, 이유가 없으면 예외로
인정하지 않는다. doc-guard 와 같은 두 관문을 그대로 쓴다 — `pre_write_guard.py`
훅이 코드를 저장할 때, `scripts/check_changed.py` 가 PR 마다 막는다. 코드 검사는
기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더)를 요구하지 않는다(#24 가드가 코드에는 적용되지
않는다) — 이 두 규칙은 어느 Project Repository, 어느 폴더에도 항상 같기
때문이다. PR 코멘트는 문서 위반과 코드 위반을 절을 나눠 보여준다. MCP 로 ABAP
오브젝트를 직접 쓰는 경로는 처음에 걸지 않았다 — 도구 이름과 소스 필드를
확인하기 전에 짐작으로 걸면 아무것도 안 보면서 통과시킬 위험이 있었다(원칙 7).
그 경로는 아래 #60 에서 확인한 뒤 걸었다.

**MCP 로 ABAP 소스를 SAP 에 바로 쓸 때도 CR-001·CR-002 를 검사한다(#60).** ADT
MCP 서버(npm `mcp-abap-abap-adt-api`)에서 소스를 쓰는 도구는 `setObjectSource`
하나고, 입력 `source` 에 전체 소스가 담긴다(부분 패치가 아니다). 새 훅
`plugins/harness/hooks/mcp_source_guard.py` 가 `PreToolUse` 매처
`mcp__.*__setObjectSource` 로 그 호출을 가로챈다 — 서버 이름은 프로젝트마다
다르므로 이름에 매이지 않는다. 언어는 `objectSourceUrl` 경로로 가리고, 그 매핑은
데이터(`mcp_object_source_map.json`)다(원칙 2). 판정은 파일 저장 때와 같은
`checker.code_rules` 를 `uvx` 로 부른다. 매핑에 없는 경로, `source`
누락, 엔진 실행 실패는 검사 불능으로 거절한다 — 실제로 막히는 경로가 나오면
매핑 파일에 한 줄 더해 넓힌다. public-cloud 에서 새 세션을 열어 080 테넌트를
대상으로 확인했다: 한글 이름 소스는 SAP 에 닿기 전에 막히고, 깨끗한 소스는 훅을
통과하며, 매핑에 없는 경로는 검사 불능으로 막힌다. 깨끗한 소스가 SAP 에 실제로
써지는 끝까지는 로그인 쿠키가 만료돼 보지 못했다. 이 훅은 harness Plugin 이 켜진
세션에서만 돈다. 그래서 MCP 서버 셋(`abap-adt`, `abap-adt-z5u`,
`abap-adt-z5u-dev`)을 사용자 범위로도 등록해, harness 가 켜진 Project
Repository 에서 바로 SAP 에 쓸 수 있게 했다. 이름 바꾸기·리팩터링 도구
(`renameExecute` 등)는 소스 본문 없이 서버에서 코드를 바꿔 이 훅에 걸리지 않았다
— 아래 #61 에서 걸었다.

**merge 가드가 엔진 빌드 로그 때문에 PRD 승인 판정을 읽지 못하던 결함을
고쳤다(#63).** `pre-bash-git-guard.sh` 가 판정 출력과 uv 의 빌드 로그(stderr)를
한데 받아, main 이 바뀐 뒤 첫 merge 가 정상 PR 인데도 막혔다. 막는 쪽으로
틀렸으니 원칙 7 은 지켰지만 헛된 거절이었다. 이제 둘을 나눠 받아 판정은 stdout
만 읽는다.

**Stop Hook 과 세션 시작 Hook 이 인계 메모를 미커밋으로 세지 않는다(#59).**
`/harness:deliver` 는 `.superpowers/` 와 `*handoff*.md` 를 스테이징에서 빼는데,
두 Hook 은 이것들을 걸러 내지 않아 인계 메모만 남아도 매 턴 deliver 를 요구했다.
같은 기준으로 걸러 내고, `--untracked-files=all` 로 파일 단위로 본다.

**MCP 리팩터링·생성 도구가 새로 붙이는 이름에도 CR-001 을 건다(#61).**
`mcp_source_guard.py` 매처를 `renamePreview`, `renameExecute`,
`extractMethodPreview`, `extractMethodExecute`, `createObject` 까지 넓혔다. 새
이름이 담기는 칸은 도구마다 다르다 — `renameRefactoring.newName`,
`refactoring.newName`, `proposal.name`(JSON 문자열), `name`. 이름을 한 줄 `.abap`
으로 엔진에 넣고 CR-001 결과만 본다. `extractMethodExecute` 는 이름 칸이 없어
`affectedObjects[].textReplaceDeltas[].contentNew` 코드 조각을 이어 붙여 검사한다.
이 경로는 코드를 옮기거나 이름만 바꾸므로 CR-002 는 보지 않는다. 칸이 없거나 JSON
을 풀지 못하면 검사 불능으로 거절한다. 입력 모양은 로컬 npx 캐시의 패키지
핸들러와 `abap-adt-api` 타입 정의로 확인했고, 실제 SAP 에 리팩터링을 걸어 본 끝까지는
아직 보지 않았다. 조사 중 `fixEdits` 도 소스 본문을 받아 따로 이슈(#69)로
남겼으나, `fixEdits` 는 빠른 수정의 수정안(범위 + 내용)을 계산해 돌려받을 뿐
저장하지 않는다(POST, `lockHandle` 없음). 저장은 결국 `setObjectSource` 를 거치므로
막을 구멍이 없어 구현하지 않고 닫았다.

**세션 Hook 이 지금 작업 폴더로 판단한다(#71).** `session-start-sync.sh`,
`stop-deliver.sh`, `pre-bash-git-guard.sh` 는 `CLAUDE_PROJECT_DIR`(세션을 처음 연
폴더)로 이동해 판단했으므로, 세션이 다른 worktree 로 옮기면 원래 폴더를 보고 경고나
거절을 냈다. 이제 모든 Hook 입력에 오는 `cwd`(Claude Code 문서상 worktree 를
따라간다)를 먼저 쓰고, 없거나 존재하지 않는 폴더면 `CLAUDE_PROJECT_DIR` 로
되돌아간다. `cd 다른폴더 && git commit` 처럼 명령 안에서 폴더를 바꾸는 경우는 여전히
`cwd` 기준으로 판단한다. 실제 세션에서 worktree 로 옮긴 뒤의 동작은 아직 보지 않았다.

**RAP 동작 정의(BDEF)에도 CR-001 을 건다(#72).** 전에는 MCP 로 쓸 때 언어를
판별하지 못해 늘 검사 불능으로 거절됐고, 파일로 저장할 때는 검사 없이 통과했다.
엔진에 `bdef` 언어를 넣었다 — `//`, `/* */` 주석과 `'...'` 문자열을 지운다(JS/CDS 용
마스킹은 `"`, `` ` `` 도 문자열로 봐서 BDEF 에 맞지 않는다). 반복문이 없으므로
CR-002 는 적용하지 않는다. ADT 주소 `/sap/bc/adt/bo/behaviordefinitions/` 는 080
테넌트에서 실제 BDEF 를 조회해 확인했고, abapGit 확장자 `.asbdef` 는 abapGit 의
`zcl_abapgit_object_bdef` 소스로 확인했다. BDEF 문자열의 이스케이프(`''`)는 실물이
드물어 ABAP 과 같다고 가정했다.

**"회사 폴더" 라는 옛 용어를 "기준 폴더" 로 정리했다(#36).** `templates/` 와
`rules/` 를 함께 가진 폴더를 가리키는 말이다. `find_company_root` →
`find_standards_root`, `group_by_company` → `group_by_standards_root`,
`has_company_folder` → `has_standards_root` 로 바꾸고 도움말·주석·README·Scaffold
Skill·테스트 이름을 맞췄다. 동작은 그대로다. 이 문서의 설계 이력 문장은 옛 구조를
설명하는 기록이라 옛 말을 그대로 둔다.

## 아직 정하지 않은 것

정한 것과 정하지 않은 것을 섞지 않기 위해 남겨 둔다.

- **새 Project Repository 에 caller workflow 를 넣는 방법.** `/scaffold` 가
  만들어 주지만, 사람이 매번 불러야 한다. 저장소 템플릿이나 조직 차원 설정과
  비교해 정하지는 않았다.
- **제안의 범위.** 지금은 무엇이 틀렸는지 알리고 쓸 템플릿을 안내하는 데까지다.
  고치는 방법을 행동 단위로 알려주거나 고쳐진 파일을 만들어 주는 것은 나중 일이다.
- **끝난 프로젝트 산출물의 보관.** 문서 저장소의 `docs/` 가 하던 자산 보관
  역할이 사라졌다. Project Repository 를 그대로 보관할지 정하지 않았다.

## 설계 배경 (CLAUDE.md 에서 줄이며 옮긴 것)

- **중앙 문서 저장소를 없앤 이유.** 예전에는 회사별 템플릿과 규칙을 모아 두는
  문서 저장소가 따로 있었다. 고객사 템플릿은 그 프로젝트 때 고객사에게서 받는
  것이라 중앙에 모아 둘 이유가 약하고, 고객사마다 저장소가 나뉘므로 접근권한
  분리 문제도 저절로 풀려 없앴다.
- **기준을 Project Repository 에 두는 것의 약점.** 같은 고객사의 다음
  프로젝트에서는 템플릿을 다시 넣어야 한다. 그때 고객사에게 다시 받는 것이
  보통이라 약점으로 보지 않지만, 실제로 아파지면 다시 본다.
- **Plugin Repository 에 앞으로 들어올 것.** Skill 과 공통 Rule 도 여기 산다.
