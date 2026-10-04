# blueward-harness 인계: SAP 플러그인 조사에서 나온 할 일

작성 2026-10-04, public-cloud 세션에서 넘김. 기준 상태: harness origin/main
`1956a01`(0.10.16, #126).

## 배경

2026-09-29 GitHub 에서 SAP 용 Claude Code 플러그인·MCP 서버를 조사하고, 그중 8개
(superclaude-for-sap, sap-skills, arc-1, abap-skills, claude-abap-skills,
sap-engineering-skill, cap-agentic-engineered, SAP/ai-skills-library)를
blueward-harness 와 나란히 놓고 비교했다. 같은 종류(협업 규칙 + 문서 템플릿 검사를
훅으로 강제)는 없었고, 가져올 것은 **SAP 시스템 쪽 안전**과 **플러그인 자체 검증**
두 영역이다.

public-cloud 쪽 선행 작업은 끝났다: PR jaeheeMin/public-cloud#111 (병합됨) 으로
`env/adt-tiers.yaml`(MCP 서버 → 테넌트 → 쓰기 허용 매핑)과
`.claude/rules/abap-src.md` 가 들어갔다. H2 는 이 파일을 읽는 것을 전제로 한다.

## 작업 방식

- 항목마다 `/harness:start` 로 이슈·브랜치를 따로 만든다. 한 PR 에 섞지 않는다.
- `plugins/harness/` 를 바꾸면 plugin.json version 을 올린다(원칙 8).
- 가드는 fail-closed 유지: 판단 못 하면 거절. (참고한 sc4sap 은 fail-open 이라 그 부분은 따라 하지 않는다.)
- 외부 저장소의 문장·코드를 그대로 가져오지 않는다. 특히 secondsky/sap-skills 는
  GPL-3.0 이라 아이디어만. 나머지(MIT/Apache-2.0)도 구조만 참고해 새로 쓴다.
- 조사·실행은 sonnet 서브에이전트에, 지시문에 "조회만, 상태 바꾸는 명령 금지" 를 넣는다.

## 할 일 (우선순위 순)

### H1. 엔진 스펙 `@main` → 버전 태그 고정 — 작음, 먼저

**현재(확인함)**: 세 훅이 매번 가변 브랜치에서 엔진을 받는다.
- `plugins/harness/hooks/pre_write_guard.py:36` `DEFAULT_ENGINE_SPEC = "git+https://github.com/jaeheeMin/blueward-harness@main"`
- `plugins/harness/hooks/mcp_source_guard.py:71` 같은 값
- `plugins/harness/hooks/pre-bash-git-guard.sh:155` `engine="${DOC_GUARD_ENGINE:-...@main}"`

**문제**: main 에 커밋이 들어가는 순간 모든 팀원 PC 의 훅 동작이 바뀐다. 플러그인
버전(원칙 8)과 엔진 버전이 따로 논다.

**할 일**: 플러그인 버전과 같은 git 태그(예: `@v0.10.17`)로 고정하고, 릴리즈
절차에 "plugin.json version 과 태그를 같이 올린다" 를 넣는다. 세 곳이 같은 값을
쓰도록 한 곳에서 읽게 하면 더 좋다. `DOC_GUARD_ENGINE` 환경변수 덮어쓰기는 유지.
`.github/workflows/doc-guard.yml` 등 Actions 쪽 `@main` 참조도 같이 본다.

**결정 필요(사용자)**: 엔진 수정이 태그 전까지 반영 안 되는 트레이드오프 수용 여부.

### H2. MCP 가드를 티어별 쓰기 차단으로 확장 — 작음~중간

**현재(확인함)**: `hooks.json` 의 MCP 매처는
`mcp__.*__(setObjectSource|renamePreview|renameExecute|extractMethodPreview|extractMethodExecute|createObject)`
6개뿐이고 서버(테넌트)를 구분하지 않는다. `activateObjects`, `deleteObject`,
`createTransport`, `transportRelease`, `runClass`, `tableContents`, `runQuery` 는
안 걸린다.

**할 일**:
1. 프로젝트 루트의 `env/adt-tiers.yaml` 을 읽어 `servers.<이름>.writes_allowed` 가
   false 인 서버에서 `write_tools` 목록 도구가 호출되면 거절.
   (형식은 public-cloud 의 파일 참고. 키 이름이 마음에 안 들면 harness 쪽에서
   정하고 public-cloud 파일을 맞춘다 — 아직 읽는 쪽이 없어 바꿔도 된다.)
2. `data_tools`(`tableContents`, `runQuery`)는 permissionDecision `ask` 로 되묻기.
   `SELECT *` 쿼리면 사유에 CR-003 언급.
3. 파일이 없으면? → 결정 필요. 제안: 쓰기 도구는 기존 동작(이름 검사만) 유지하고
   데이터 도구만 ask. 파일은 있는데 파싱 실패면 거절(fail-closed).
4. `mcp_tool_name` 에서 서버 이름은 `mcp__<서버>__<도구>` 로 뽑는다. 서버 이름에
   `__` 가 들어갈 수 없는지 확인.
5. scaffold 스켈레톤에 `env/adt-tiers.yaml` 예시를 넣을지 검토.

**참고**: babamba2/superclaude-for-sap 의 `scripts/hooks/tier-readonly-guard.mjs`
(접두어 Create/Update/Delete/... 로 판정, fail-open) 와 `block-forbidden-tables.mjs`.

### H3. 위임 규칙을 `agents/` 로 구조화 — 작음

**현재(확인함)**: `plugins/harness/agents/` 없음. `rules/delegation.md` 의
"서브에이전트는 sonnet 고정, 자기 승인 금지" 는 문서로만 있다.

**할 일**: `agents/researcher.md`(model: sonnet, disallowedTools: [Write, Edit],
조회만), `agents/reviewer.md`(읽기 전용 검토) 추가. `delegation.md` 가 이
에이전트를 쓰도록 안내. 플러그인 agents 의 frontmatter 필드(`model`,
`tools`, `disallowedTools`)는 claude-code-guide 로 공식 문서 확인 후 작성.

**참고**: sc4sap `agents/sap-code-reviewer.md` (model + tools + disallowedTools).

### H4. 플러그인 자체 검증 테스트 — 작음

**현재**: `checker/tests/test_plugin_layout.py` 가 있다(내용은 확인 안 함).

**할 일**: 다음을 pytest 로 추가(이미 있는 건 건너뜀).
- `plugins/harness/` 가 바뀐 PR 에서 plugin.json version 이 올랐는가 (Actions 에서 base 와 비교)
- `hooks.json` 이 가리키는 스크립트가 실제로 있는가
- 모든 SKILL.md 에 name·description 이 있고 name 이 디렉터리명과 같은가
- SKILL.md 가 참조하는 `../../rules/*.md` 경로가 실재하는가

**참고**: likweitan/abap-skills `scripts/validate_skills.py`(MIT, uv 기반),
shrek-abaper `tests/check_contract.py`.

### H5. 증거 수준 판정 게이트 / verify 스킬 — 중간

원칙 7("검사 못 했다 ≠ 통과")을 구현·릴리즈 단계로 넓힌다.
- 증거 수준 HIGH/MEDIUM/LOW/UNKNOWN 을 매기고, LOW 면 통과 판정 금지, UNKNOWN 이면 "증거 부족".
- finding 필드: id, severity, confidence, location, evidence(실제 코드, 지어내기 금지), requires_human_confirmation.
- 검증 결과에 `human_needed` 상태와 이유.
- 진행 원장에 "검증됨 / 종료" 상태 추가 검토(`rules/audit-ledger.yaml` 영향).

**참고**: shrek-abaper/sap-engineering-skill `skills/sap-transport-gate/references/decision-policy.md`,
SAP-samples/cap-agentic-engineered `spec/phases/01-*/01-VERIFICATION.md`.

### H6. ATC 처리 스킬 — 중간 (public-cloud P2 실측 뒤)

ATC 실행 → finding 을 카테고리별로 묶기 → 자동/확인 후/수동 3단계 처리 →
pseudo-comment(`"#EC`) 억제는 근거 없으면 거부 → 배치마다 재실행해 증감 보고.
우리 MCP 에 `createAtcRun`, `atcWorklists`, `atcCheckVariant` 가 있다.
variant 이름은 하드코딩 말고 프로젝트 설정에서(080 실측값
`ABAP_CLOUD_DEVELOPMENT_DEFAULT`, `conventions/common.md` 에 기록됨).
Clean Core A~D ↔ ATC 우선순위 표는 sap-docs 로 공식 확인된 것만 넣는다.

**참고**: matt1as/claude-abap-skills `abap-cloud-rap/atc-remediation/SKILL.md`,
arc-mcp/arc-1 `skills/sap-clean-core-atc/SKILL.md`.

### H7. 스킬 frontmatter 정비 — 작음

- description 에 "이럴 땐 쓰지 않는다 — X 스킬로" 추가. start/deliver/sync/wrapup 이
  비슷한 말("다 했어", "최신으로")로 겹친다.
- 공식 지원 필드(확인함, https://code.claude.com/docs/en/skills.md#frontmatter-reference):
  `when_to_use`, `allowed-tools`(제한이 아니라 **사전 승인** 목록), `disallowed-tools`,
  `paths`, `context: fork`, `agent`, `hooks`, `metadata`, `compatibility` 등.
  uv 필요 같은 전제는 `compatibility` 에.

### H8. gitleaks 로 CR-004 기계 검사 — 작음

CR-004(비밀정보)는 지금 문서만 있고 검사 없음. scaffold 스켈레톤
`dot-github/workflows/` 에 gitleaks 워크플로, `.githooks/pre-commit` 연결.
SAP 비밀번호·쿠키 패턴 커스텀 규칙 추가. (#126 이 이미 "비밀값" 위험도 판정을
넣었으니 겹치는지 먼저 확인.)

## 가져오지 않기로 한 것

- sc4sap `permission-approver`(SAP MCP 자동 승인) — 우리 철학과 정면 충돌
- sap-skills 콘텐츠 — GPL-3.0
- rap-bo-design — SAP 공식 MCP `abap_generators-*` 의존, 우리 MCP 에 없음
- sap-adt-cli, `npx skills add` 배포 — 쿠키 프록시·훅 구조와 안 맞음

## 권장 순서

1. H1, H3, H4 (서로 독립, 병렬 가능)
2. H2 → 끝나면 public-cloud 에서 실제 MCP 호출로 막히는지 확인 (그쪽 P6)
3. H5, H7, H8
4. H6 은 public-cloud P2(080 실측)·P3(공식 문서 확인) 결과 뒤
