---
name: prd
description: PRD 를 처음 만들 때, 또는 요구사항이 바뀌어 PRD 를 고칠 때 쓴다. 사용자가 "PRD 만들어줘", "요구사항 바뀌었어", "PRD 수정" 이라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 개발 Spec 을 만들거나 고치는 말이면 spec 스킬로(PRD 를 고친 뒤 Spec 에 반영하는 일도 spec).
---

# /harness:prd

`docs/ssot/PRD.md` 를 만들거나 고치는 입구다. PRD 는 이 프로젝트의 SSOT 라,
바꿀 때마다 근거와 영향을 남긴다. `<이 스킬의 base directory>` 는 이 스킬이
로드될 때 위에 표시되는 경로다.

`git rev-parse --show-toplevel` 로 Project Repository 루트를 확인하고,
그 아래 `docs/ssot/PRD.md` 를 대상으로 한다. 이 문서가 아직
`templates/harness/PRD.md` 의 빈 스텁 그대로면(각 절에 "아직 작성 전이다"
placeholder만 있으면) **만들기**, 이미 내용이 채워져 있으면 **고치기** 로
판단한다.

## 만들기

1. 입력 문서를 확인한다. 사용자가 경로를 줬으면 그것을 읽고, 안 줬으면
   `docs/` 아래에서 요구사항 정리·AS-IS 문서·회의록 같은 후보를 찾아 목록으로
   보여 주고 고르게 한다. 이 저장소의 Template 은 `templates/`, Convention
   은 `conventions/` 에 있다.
2. 입력 문서를 읽고, 불명확하거나 서로 부딪히는 점을 목록으로 만든 뒤 한
   번에 묶어 사용자에게 묻는다. `AskUserQuestion` 을 쓸 수 있으면 쓰고,
   질문은 쉬운 말로 하고 보기마다 무엇이 달라지는지 적는다. 답이 없는
   것은 추측으로 채우지 않고 `## 미결 사항` 에 남긴다.
3. `templates/harness/PRD.md` 틀대로 `docs/ssot/PRD.md` 를 쓴다. 요구사항은
   `REQ-001` 부터 번호를 붙이고 출처(입력 문서·회의·질문 답)를 적는다.
   Convention·Template·규칙은 본문에 옮기지 않고 링크만 적는다.
4. 변경 기록을 남긴다. `audit/changes/YYYYMMDD-PRD-최초작성.md` 를
   `templates/harness/audit-change.md` 틀로 쓴다. 종류는 "결정", 바뀐 것은
   전체 REQ 목록, 근거는 읽은 입력 문서 목록, 영향은 "이후 Spec 작성 대상"
   으로 적는다.
5. 저장 전에 doc-guard 훅이 이 틀을 검사한다. 막히면 사유를 읽고 빠진 절을
   채운다.
6. 마무리를 안내한다. PRD 는 SSOT 라 PRD 를 바꾸는 PR 은 사람이 승인해야
   한다(승인을 강제로 막는 장치는 아직 없다). 다음 단계는
   `/harness:spec` 으로 Spec 을 만드는 것이다.

## 고치기

1. 무엇이 왜 바뀌는지 받는다. 근거(고객 요청, 회의, 기술 제약 등) 없이
   고치지 않는다.
2. 해당 REQ 를 고친다. 번호는 새로 매기지 않는다. 바뀐 REQ 는 상태를
   `변경됨` 으로, 없앤 REQ 는 행을 지우지 않고 `폐기` 로 둔다. 새 요구사항은
   마지막 번호 다음부터 이어서 붙인다.
3. 영향을 찾는다. 바뀐 REQ 번호로 `docs/spec/`, `audit/ledger/`, 그 밖의
   `docs/` 를 검색해 영향받는 파일 목록을 사용자에게 보여 준다. 사용자가
   원하면 그 Spec 들도 고친다 — 개발자는 왜 바뀌었는지 모르므로, 고친 Spec
   에 바뀐 REQ 번호와 이번 변경 기록 링크를 남긴다.
4. 변경 기록 `audit/changes/YYYYMMDD-<요약>.md` 을 `templates/harness/
   audit-change.md` 틀로 남긴다. 바뀐 것에는 REQ 번호와 파일을, 근거에는
   왜 바뀌었는지를, 영향에는 3 에서 찾은 목록을 적는다.
5. 마무리를 안내한다. PRD 변경 PR 도 사람 승인이 필요하다.
   `/harness:deliver` 로 올릴 때는 PR 본문에 "PRD 변경" 이라는 표시와 이번
   변경 기록 링크를 적는다.

## 저장 전 검사

`docs/ssot/PRD.md` 를 쓰거나 고칠 때마다 doc-guard 훅(`pre_write_guard.py`)이
`rules/ssot.yaml` 로 파일 이름과 필수 절을 검사한다. 검사를 통과하지 못하면
저장이 막히고 사유가 나온다 — 그 사유대로 고친다. 훅이 죽어 검사를 못 한
경우에는 통과나 위반이 아니라 검사를 못 했다고 알린다.
