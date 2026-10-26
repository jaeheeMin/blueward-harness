---
name: approvals
description: 내 Approve 를 기다리는 열린 PR 을 병합 순서대로 한 표로 보여 준다. 사용자가 "내가 승인해야 할 PR", "승인 대기 PR 보여줘", "승인할 거 있어?", "내 승인 기다리는 PR" 이라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 내가 만든 PR 의 상태·병합 순서면 prs 스킬로, 승인(Approve) 자체는 이 스킬이 하지 않으니 사람이 GitHub 에서 한다.
compatibility: GitHub CLI(gh, 로그인 상태)와 uv 가 필요하다. 읽기만 하며 PR·리뷰·브랜치·파일을 바꾸지 않는다.
---

# /harness:approvals

승인자가 "어떤 PR 이 내 Approve 를 기다리는지" 를 병합 순서대로 보는 스킬이다.
읽기만 한다. **`gh pr review --approve` 를 대신 하지 않는다** — 승인은 사람이 GitHub 에서
한다(`rules/delegation.md` 의 자기 승인 금지와 같은 결). 계산은 엔진(`checker.pr_approvals`)이
`checker.pr_queue` 의 상태·병합 순서를 그대로 쓴다.

내 승인이 필요한 PR = 승인 대기 상태이고, 작성자가 내가 아니고, `.github/ssot-approvers` 가 그 작성자에게
정한 승인자에 내가 들어 있고, 내 승인이 최신 커밋 기준으로 없는(없거나 낡은) PR. 승인자 파일이 없거나
비어 있으면 작성자 아닌 누구든 승인할 수 있다(나도 승인자).

## 절차

1. 저장소 루트에서 엔진 판을 정하고 부른다. Bash 도구로 실행한다.

   ```bash
   e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "승인 대기 PR 확인 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
   uvx --from "$e" python -P -m checker.pr_approvals
   ```

   첫 줄이 실패하거나 빈 값이면 `uvx` 로 넘어가지 말고 멈춰서 사유를 알리고 "승인 대기 PR 확인 불능" 이라고
   말한다. `@main` 이나 다른 판으로 대신 받지 않는다. PowerShell 도구는 `$e = uv run --no-project python
   "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py"; if ($LASTEXITCODE -ne 0 -or -not $e) { throw "승인 대기 PR 확인 불능" }`
   로 정한 뒤 `uvx --from $e python -P -m checker.pr_approvals` 로 부른다. 다른 저장소를 보려면
   `--repo owner/repo` 를 더한다(없으면 현재 폴더의 저장소).
2. 종료코드가 2 이거나 출력이 "승인 대기 PR 확인 불능" 으로 시작하면 **그 문구와 사유를 그대로 전하고 멈춘다.**
   "승인할 PR 이 없다" 로 말하지 않는다. 다음 할 일은 `gh auth status` 확인, 네트워크 확인, 다시 시도다.
3. 결과를 구분해서 전한다.
   - "이 저장소에서 나는 승인자가 아님" — 승인자 파일에 내용이 있는데 내 이름이 없다. "승인할 PR 없음" 이 아니다.
     파일이 없거나 비어 있으면 아니다 — 머리 줄 "승인자 파일이 없어 작성자 아닌 누구든 승인할 수 있다" 를 전한다.
   - "승인 대기 상태인 PR 중에는 내 승인을 기다리는 PR 없음" — 승인자인데 승인 대기 PR 중에 없다.
   - 표 아래 "내 승인도 필요하지만 검사 중·실패·충돌이라 아직 차례가 아닌 PR n건" 줄 — 아직 승인 단계에 못 온
     PR 이다. 그 PR 은 검사·충돌을 먼저 풀어야 한다고 알린다. "셀 수 없음" 이면 못 센 것이지 없다는 뜻이 아니다.
   - 표 — 순서·PR·왜 승인이 필요한가·다른 승인자·남은 것·낡은 승인. 출력을 그대로 보여 주고, 맨 위(앞 PR 이
     없는 것)부터 승인하면 된다고 알린다. "내 승인만 남음" 이 아니면 무엇이 더 남았는지(앞 PR 병합 대기 등) 말한다.
     "낡은 승인" 은 승인한 뒤 새 커밋이 올라와 다시 승인해야 한다는 뜻이다.
   - "주의" 줄(승인 여부를 읽지 못한 PR, 일부만 읽음)은 빼지 않고 전한다.
   - **PR 을 말할 때는 번호·제목과 함께 링크를 붙인다.** 표의 PR 칸과 "앞:" 은 이미
     `[#303](https://github.com/<repo>/pull/303)` 모양이니 풀어 쓸 때도 이 링크를 그대로 쓴다.
4. 승인은 사람이 표의 링크를 열어 GitHub 에서 최신 커밋을 보고 직접 한다고 안내한다.

## 하지 않는 것

- Approve, 병합, 닫기, 코멘트, 푸시 — 읽기만 한다. 승인 요청을 대신 달아 주겠다고 제안하지도 않는다.
- 엔진이 못 읽은 것을 "없음" 이나 "승인자 아님" 으로 말하는 것.
- 내 PR 의 상태를 여기서 풀이하는 것(`/harness:prs`).

## 관련 규칙

병합·리뷰 규칙은 `<이 스킬의 base directory>/../../rules/governance.md`, 자기 승인 금지는
`<이 스킬의 base directory>/../../rules/delegation.md` 를 따른다.
`<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는 경로다.
