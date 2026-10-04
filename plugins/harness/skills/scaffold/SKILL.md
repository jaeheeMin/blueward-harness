---
name: scaffold
description: 새 고객사 Project Repository 를 처음 만들었을 때 표준 구조(templates/, rules/, docs/ssot/ 등)를 만든다. 사용자가 "스캐폴딩 해줘", "프로젝트 구조 만들어줘", "초기 세팅해줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 작업(이슈·브랜치)을 시작하는 말이면 start 스킬로, 구조가 이미 있는 저장소에서 문서를 만들거나 고치는 말이면 prd·spec 스킬로.
compatibility: uv 가 있으면 uv 로, 없으면 python 으로 돌린다. 시크릿 등록 안내에 GitHub CLI(gh)를 쓴다.
---

# /harness:scaffold

새로 만든 Project Repository 에 doc-guard 가 기대하는 표준 구조를 만드는
입구다. `templates/` 와 `rules/` 를 저장소 루트에 두면, 검사 엔진이 문서에서
위로 올라가며 이 둘을 찾아 "여기가 기준 폴더(`templates/` 와 `rules/` 를 함께 가진
폴더)다" 라고 판단한다.

1. 고객사 이름과 프로젝트 이름이 인자로 주어지지 않았으면, 한 번에 같이
   물어본다("어느 고객사, 어느 프로젝트인가요?"). PRD(`docs/ssot/`) 변경 PR 을
   승인할 사람의 GitHub 아이디도 물어본다("PRD 변경을 승인할 사람이 있나요?
   없으면 작성자가 아닌 누구의 승인이든 인정합니다"). 없다고 하면 비워 둔다.
2. `git rev-parse --show-toplevel` 로 현재 위치가 이 Project Repository 의
   루트인지 확인한다. 스캐폴딩은 항상 저장소 루트에서 실행한다.
3. 먼저 `--dry-run` 으로 돌려 무엇을 만들고 무엇을 건너뛸지 보여준 뒤, 문제가
   없으면 `--dry-run` 없이 다시 돌린다. 승인자를 여러 명 받았으면
   `--ssot-approver` 를 그 수만큼 반복한다.

   ```bash
   uv run --no-project python "<이 스킬의 base directory>/harness:scaffold.py" \
     --client "<고객사>" --project "<프로젝트>" \
     --ssot-approver "<GitHub 아이디>" --dry-run
   ```

   `<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는 경로다.
   `uv` 가 없으면 `python` 으로 바로 부른다. `--ssot-approver` 는 생략할 수
   있다.
4. 스크립트는 이미 있는 파일을 절대 덮어쓰지 않고 건너뛴다(`skipped`). 만든
   목록(`created`)과 건너뛴 목록을 사용자에게 보고한다. `.claude/settings.json`
   만은 예외로, 이미 있어도 harness Plugin 자동 설치에 쓰는 두 항목
   (`enabledPlugins`·`extraKnownMarketplaces` 안의 `harness@blueward-harness`
   ·`blueward-harness`)이 없으면 그 항목만 채워 넣고 나머지 키는 그대로
   둔다(`merged`). 마켓플레이스 항목에는 Plugin 자동 업데이트를 켜는
   `"autoUpdate": true` 도 들어가며, 예전에 만든 설정에 이 키만 없으면 채운다
   (#99). 이미 같은 값이면 손대지 않는다. 다른 값이 이미 있거나
   JSON 을 못 읽으면 손대지 않고 `warnings` 로 알린다 — 이때는 사용자에게
   그 내용을 그대로 보여주고, 두 항목을 손으로 넣어야 한다고 안내한다.
5. 다음에 할 일을 안내한다.
   - `.claude/settings.json` 덕분에 이 저장소 폴더를 여는 팀원은 별도 설치
     없이 blueward-harness 마켓플레이스와 harness Plugin 설치 안내를
     자동으로 받는다. 자동 업데이트도 켜져 있어 새 버전이 나오면 세션 중
     `Plugin updated: harness · Run /reload-plugins to apply` 로 알림을
     받는다. `merged` 나 `warnings` 가 있었으면 그 사실도 알린다.
   - 고객사에게 받은 Template 원본을 `templates/` 에 그대로 넣는다.
   - 그 Template 을 대조할 규칙을 `rules/` 에 추가한다(`rules/README.md`
     예시 참고).
   - 환경별 접속 URL 을 `env/` 에 적는다.
   - `.github/workflows/doc-guard.yml` 이 이제부터 이 저장소의 PR 과 main
     커밋마다 검사를 돌린다. `.github/workflows/ssot-approval.yml` 은 같은
     자리에서 PRD 변경 PR 의 승인 여부를 검사한다(#49).
   - 승인자를 나중에 추가·변경하려면 `.github/ssot-approvers` 를 직접 고친다.
     비어 있으면(주석뿐이면) 작성자가 아닌 누구의 승인이든 인정한다.
   - `.github/workflows/risk-gate.yml` 과 `.github/risk-gate.yaml` 은 PR 위험도에 따라
     승인을 요구한다(#102). 위험한 PR(크기·위험 경로·비밀값·검사 실패)만 승인자 목록
     (`.github/ssot-approvers`)의 사람이 Approve 해야 통과하고 나머지는 승인 없이
     병합된다. **승인자 목록에 작성자가 아닌 사람이 한 명도 없으면 위험한 PR 을
     승인으로 통과시킬 수 없다** — 사용자에게 승인자를 꼭 넣도록 안내한다. 기준은
     `.github/risk-gate.yaml` 에서 고치고(주석 참고), 파일을 지우면 게이트가 꺼진다.
   - `.github/workflows/ai-review.yml` 은 위험도가 낮은 PR 에만 Claude AI 리뷰를 돌린다(#125).
     **기본은 꺼짐**이라 아무것도 하지 않는다. 켜려면 (1) `claude setup-token` 으로 만든 토큰을
     `gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <owner/repo>` 로 등록하고 (2)
     `.github/risk-gate.yaml` 의 `ai_review` 를 `true` 로 바꾼다. 켰는데 시크릿이 없으면
     통과가 아니라 검사 불능으로 실패하니 사용자에게 두 단계를 함께 안내한다.
   - PRD 는 `/harness:prd` Skill 로 만든다. 지금은 `docs/ssot/PRD.md` 가
     빈 스텁으로만 있다.

## 만들어지는 구조

```
CLAUDE.md                          이 저장소가 무엇인지, 디렉터리와 규칙 요약
docs/ssot/PRD.md                   요구사항의 정본(SSOT). 아직 빈 스텁
docs/spec/.gitkeep                 개발 Spec 이 쌓일 자리
templates/README.md                고객사 템플릿 원본을 두는 자리
templates/harness/PRD.md           PRD 틀
templates/harness/spec.md          개발 Spec 틀
templates/harness/audit-change.md  변경 기록 템플릿
templates/harness/audit-ledger.md  진행 원장 템플릿
rules/README.md                    규칙 작성법과 예시
rules/ssot.yaml                    PRD 파일명·필수 절 규칙
rules/spec.yaml                    Spec 파일명·필수 절 규칙
rules/audit-changes.yaml           변경 기록의 파일명·필수 절 규칙
rules/audit-ledger.yaml            진행 원장의 파일명·필수 절 규칙
conventions/README.md              이 프로젝트에서만 통하는 Convention
audit/README.md                    Audit 두 종류(변경 기록·진행 원장) 설명
audit/changes/.gitkeep             변경 기록이 쌓일 자리
audit/ledger/.gitkeep              진행 원장이 쌓일 자리
env/README.md                      환경별 접속 URL(Credential 은 안 둠)
env/adt-tiers.example.yaml         SAP MCP 서버별 쓰기 허용 표 예시(#148). 훅은 읽지 않는다 — 복사해 env/adt-tiers.yaml 로 고쳐 쓴다
.github/workflows/doc-guard.yml    PR·main 커밋마다 doc-guard 를 부르는 워크플로
.github/workflows/ssot-approval.yml PR·main 커밋마다 PRD 변경 승인을 검사하는 워크플로(#49)
.github/ssot-approvers             PRD 변경 PR 을 승인할 수 있는 GitHub 아이디 목록
.github/workflows/risk-gate.yml    PR·main 커밋마다 PR 위험도를 판정하는 워크플로(#102)
.github/risk-gate.yaml             위험도 기준(크기·위험 경로·비밀값·검사 통과). 위험한 PR 만 승인자가 Approve 해야 통과
.github/workflows/ai-review.yml    위험도 낮은 PR 에만 Claude AI 리뷰를 돌리는 워크플로(#125). 기본 꺼짐
.claude/settings.json              harness Plugin 자동 설치 안내(#89). 이미 있으면 두 항목만 합친다
```

`rules/ssot.yaml`, `rules/spec.yaml`, `rules/audit-changes.yaml`,
`rules/audit-ledger.yaml` 을 지우지 않는다. `rules/` 에 `*.yaml` 이 하나도
없으면 모든 검사가 설정 오류로 실패한다.

## 안전장치

- 기존 파일을 덮어쓰지 않으므로 이미 세팅된 저장소에 다시 돌려도 안전하다.
- `src/` 처럼 아직 내용이 정해지지 않은 빈 폴더는 만들지 않는다. git 은 빈
  폴더를 추적하지 못하고, 그 구조는 나중 Skill 이 정한다. `docs/spec/` 은
  `audit/changes/`·`audit/ledger/` 와 같은 이유로 `.gitkeep` 을 둬 미리
  만들어 둔다 — `/harness:spec` 이 그 안에 파일을 쓰기 때문이다.
