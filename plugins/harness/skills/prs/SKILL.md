---
name: prs
description: 내 열린 PR 의 상태와 병합 순서를 GitHub 에서 계산해 보여 주고, 다음에 할 일을 알려 준다. 사용자가 "내 PR 어때?", "PR 상태", "뭐부터 병합해?", "PR 순서 알려줘", "내 PR 지금 어디까지 왔어?" 라고 말할 때 사용한다. `--all` 을 주면 저장소의 열린 PR 전체를 본다. "팀원별로 보여 줘", "팀 현황", "누가 막혔어?" 라고 하면 `--team` 으로 팀원별 진행·막힘·오래 머문 일을 본다. 이럴 땐 쓰지 않는다 — PR 을 새로 만들거나 갱신하는 말이면 deliver 스킬로, 원격 변경을 로컬로 받는 말이면 sync 스킬로, 새 작업의 이슈와 브랜치면 start 스킬로.
compatibility: GitHub CLI(gh, 로그인 상태)와 uv 가 필요하다. 읽기만 하며 PR·브랜치·파일을 바꾸지 않는다.
---

# /harness:prs

내 열린 PR 이 어디까지 왔는지, 무엇부터 병합해야 하는지를 보여 주는 스킬이다.
읽기만 한다. 병합·푸시·코멘트는 하지 않는다. 계산은 엔진(`checker.pr_queue`)이
GitHub 에서 한 번에 하고, 세션을 시작할 때 나오는 "내 PR" 알림도 같은 계산이다.

인자: 없으면 내 PR 만(`--mine`), `--all` 이면 저장소의 열린 PR 전체를 본다.
`--verbose` 를 더하면 표 아래에 긴 승인 사유·다음 할 일·"같은 파일" 주의를 예전 표 형식으로 덧붙인다.
`--max-rows N` 은 줄기 표의 줄 수를 줄인다(세션 시작 알림용).
`--team` 은 팀원별 현황이다(아래 "팀원별 현황"). "팀원별로 보여 줘", "팀 현황", "누가 막혔어?" 라고 하면 이 옵션으로 부른다.

## 절차

1. 저장소 루트에서 엔진 판을 정하고 부른다. Bash 도구로 실행한다.

   ```bash
   e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "PR 상태 확인 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
   uvx --from "$e" python -m checker.pr_queue --mine      # --all 이면 --mine 대신 --all
   ```

   첫 줄이 실패하거나 빈 값이면 `uvx` 로 넘어가지 말고 멈춰서 사유를 알리고 "PR 상태 확인 불능" 이라고
   말한다. `@main` 이나 다른 판으로 대신 받지 않는다. PowerShell 도구는 `$e = uv run --no-project python
   "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py"; if ($LASTEXITCODE -ne 0 -or -not $e) { throw "PR 상태 확인 불능" }`
   로 정한 뒤 `uvx --from $e python -m checker.pr_queue --mine` 으로 부른다. 다른 저장소를 보려면
   `--repo owner/repo` 를 더한다(없으면 현재 폴더의 저장소).
2. 종료코드가 2 이거나 출력이 "PR 상태 확인 불능" 으로 시작하면 **그 문구와 사유를 그대로 전하고 멈춘다.**
   "PR 이 없다", "문제없다" 로 말하지 않는다. 다음 할 일은 `gh auth status` 확인, 네트워크 확인, 다시 시도다.
3. 엔진이 내는 두 표를 보여 주고, 사용자가 바로 움직일 수 있게 쉬운 말로 풀어 준다. `--all` 이면 할 일 표 없이 줄기
   표만 나온다.
   - **내가 지금 할 수 있는 일** 표(할 일 · PR): `병합하기` = 병합 가능이고 앞 PR 이 없는 것, `고치기` = 검사 실패·충돌·
     판정 불능처럼 내가 손볼 것, `기다리기` = 승인 대기·검사 중·앞 PR 대기·초안. 맨 앞에서 병합하기부터 말한다.
     "사람이 GitHub 에서 병합" 이라고 적힌 PR 은 에이전트가 병합하지 않고 사람이 병합한다고 알린다.
     "지금 할 수 있는 일: 없음(모두 기다리는 중)" 이면 그대로 전한다.
   - `—` 뒤의 사유를 구분해서 말한다. 충돌(`/harness:sync` 후 해결), 검사 실패(어떤 검사인지), 승인(누구의 승인이
     필요한지, "새 커밋 뒤 재승인" 이면 낡은 승인이라 다시 필요하다는 것), "검사 시작 전"(푸시 직후, 잠시 뒤 다시),
     "base 보다 뒤처짐"(`/harness:sync`)·"병합 막힘"·"검사 불안정", "충돌 여부 확인 중"(충돌 없음이 아니다, 잠시 뒤 다시),
     "앞 [#n] 대기"(그 PR 이 병합된 뒤에). 자세한 사유(승인 사유 전문, risk-gate 사유 등)는 `--verbose` 로 다시 불러 보여 준다.
   - **내 PR 과 그 줄기** 표: 줄기는 같은 DEV 번호를 가진 PR 묶음이고 한 줄이다(번호는 PR 제목 끝 `(DEV-007)`, 제목 앞,
     브랜치, 바꾼 Spec 파일 `docs/spec/DEV-007-*.md`, 본문 순으로 읽는다). `→` 로 병합 순서를 잇고(`(#a, #b)` 는 같은
     단계의 갈래), 다른 줄기에 있는 앞 PR 은 `✅(앞: [#244])` 꼬리표로 보인다. 내 PR 은 굵게, 기호는 ✅ 병합 가능 ·
     ⏳ 기다리는 중 · ❌ 고쳐야 함 · 📝 초안 · ❓ 판정 불능이다. 줄기 이름은 `DEV-007(제목)` 이다. DEV 번호를 읽지 못한 PR 은
     앞뒤로 이어진 DEV 줄기가 하나뿐이면 그 줄기에 들어가고, 둘 이상에 걸치거나 혼자면 번호 없는 PR 끼리 이어진 줄이나
     "줄기 없음" 한 줄에 모인다. ❓ 이거나 "순서 판정 불능(순환)" 이면
     순서를 정하지 못한 것이니 PR 본문의 `먼저:` 줄을 확인하라고 알린다. 남의 PR 이 내 줄기 안에 있으면 내 앞뒤라서 보이는 것이다.
   - "주의" 줄(일부만 읽음, version 을 읽지 못함, 줄기 표 아래의 `⚠` PR 주의 — 예: 사람이 병합할 경로인지 확인 불능)은
     빼지 않고 전한다. "같은 파일을 고친 PR 쌍" 주의는 `--verbose` 에만 나온다.
   - **원장 줄(#454).** 표 아래에 `⚠ [#n](링크) 원장 DEV-xxx(제목) 이 '리뷰' 야 …` 줄이 있으면, 내 PR 이 대표
     `[DEV-xxx]` 이슈를 Closes 하는데 PR 브랜치의 진행 원장 행이 `완료` 가 아니라는 뜻이다(옛 판 deliver 로 만든 PR.
     병합 뒤 `ledger-complete` 가 위반으로 잡는다). 이 줄이 있으면 **Claude 가 먼저** "그 PR 의 원장을 완료로 고쳐 다시
     올릴까?" 를 쉬운 말로 묻는다. 그 PR 이 이미 승인(Approved)됐으면 "커밋을 올리면 main 규칙 때문에 승인이 취소돼 다시 승인받아야 하고 검사도 다시 돈다" 를 먼저 알리되, 병합 전에 고쳐야 하니 고치는 쪽을 추천한다. 응하면 그 PR 의 브랜치(`gh pr view <번호> --json headRefName`)에서 `/harness:deliver`
     를 부른다 — 지금 브랜치가 그 PR 브랜치가 아니면 먼저 옮겨야 하고, 미커밋 변경이 있으면 옮기기 전에 사용자에게 묻는다.
     `❓ … 판정 불능` 줄은 원장 행을 못 읽었다(행 0개·2개 이상, 표 형식, 조회 실패)는 뜻이다. 완료라고도 아니라고도
     말하지 말고 사유를 전한다(이슈를 읽지 못한 경우는 `이 닫는 이슈 #N 을 읽지 못해 원장 확인 불능` 으로 나온다). 하위 작업 PR·이미 `완료`·원장 없는 저장소는 줄이 나오지 않는다. `--all` 은 판정하지 않는다.
   - **PR 을 말할 때는 번호·제목과 함께 링크를 붙인다.** 엔진 표의 PR 은 이미
     `[#303](https://github.com/<repo>/pull/303)` 모양의 링크다. 풀어 쓸 때도 번호만 적지 말고 이 링크를 그대로
     쓴다(저장소가 여럿이라 링크가 어느 저장소의 PR 인지 보여 준다).
4. 순서 판정의 근거(base 브랜치, 본문 `먼저:` 줄, 같은 DEV 의 SRS→Spec→개발, plugin.json version)가 궁금하다고 하면
   `--json` 으로 다시 불러 `after_reasons` 를 보여 준다.

## 팀원별 현황(`--team`)

어드민이 팀원 각자의 진행·막힘·오류를 판단하는 보기다. 저장소 전체를 보므로 `--mine`·`--pr` 과 함께 쓰지 않는다(`--all` 은 붙여도 된다).
절차 1 의 명령에서 `--mine` 대신 `--team` 을 쓴다: `python -m checker.pr_queue --team [--days N] [--stale-days N] [--json]`.
`--days` 는 병합한 PR 을 볼 최근 일수(기본 7), `--stale-days` 는 열린 PR 이 이 일수를 **넘게** 움직임이 없으면 "오래 머문 일"
로 보는 기준(기본 3)이다. 담당 이슈는 14일을 넘게 움직임이 없을 때다. 시각은 KST 로 나온다.
"움직임" 은 **사람이 마지막으로 손댄 때**다(봇 갱신에 흔들리는 `updatedAt` 은 쓰지 않는다). PR 은 마지막 커밋·열린 때·사람(봇 제외)의 마지막 코멘트·리뷰·리뷰 코멘트 중 가장 늦은 것, 이슈는 사람의 마지막 코멘트(없으면 생성 시각)다. 라벨·담당자 변경은 읽지 않는다. 출력은 "n일 움직임 없음(마지막 커밋/코멘트/리뷰 … 시각)" 으로 근거를 보인다. 코멘트가 많아 사람 활동을 다 읽지 못했거나 커밋 시각이 없어 단정할 수 없으면 "판정 불능" 이다(정체 아님이 아니다).

출력 순서: 확인 불능 목록 → **공통 원인**(같은 사유로 PR 둘 이상에서 실패한 것. 사유가 구체적이면 검사가 달라도 한 건으로 묶고 검사 이름을 목록으로 붙이며, `exit code N` 이 든 문구나 20자 미만의 흔한 문구는 같은 검사끼리만 묶는다. 사람별 칸에는 "공통 원인 ①" 만 적힌다) →
팀원 요약 표 → 팀원별 상세(진행: 병합한 PR·열린 PR 의 마지막 커밋 시각, 막힘: PR 한 건에 한 줄로 검사 실패(검사 이름과 사유)·충돌·리뷰·승인 대기·앞 PR 대기를 이어 붙임, 요약 표의 "막힌 PR" 은 PR 수,
오래 머문 PR·이슈, 맡은 개발 건 DEV 번호(제목)·상태·마지막 PR) → 담당자 없는 열린 이슈.

- 맡은 개발 건은 **저장소 기본 브랜치**(조회한 값, main 이 아닐 수 있다)의 `audit/ledger/*.md` 에서 읽는다. 기본 브랜치에 원장 디렉터리가 실제로 없을 때만 "원장 없음" 으로 건너뛴다(확인 불능이 아니다).
  기본 브랜치를 못 읽거나 원장을 읽지 못하면 "확인 불능" 이다. `담당` 칸에 적힌 사람은 이번 기간에 활동이 없어도 팀원 칸에 나온다.
- **팀 별칭 파일**: 원장 `담당` 칸에 실명이 적혀 같은 사람이 두 칸으로 갈릴 때, 원장을 고치지 않고 Project Repository 의 기본 브랜치에 `.github/harness-team.yaml` 을 두어 이름을 GitHub 아이디로 잇는다(`.github/ssot-approvers` 같은 저장소 데이터 파일 위치). 형식(예시 값):

  ```yaml
  별칭:
    홍길동: hong-gd    # 원장에 적힌 이름 → GitHub 아이디
  ```

  원장 담당에 먼저 적용한 뒤 사람 칸을 배정한다(이름 대소문자는 구분하지 않는다). 적용한 내용은 출력 맨 끝 `별칭 적용: 홍길동 → hong-gd(DEV-003)` 한 줄과 JSON `aliases_applied` 에 나온다. 파일이 없으면(404) 별칭 없음이고 경고도 없다. 읽기 실패·형식 오류·값이 GitHub 아이디 형식이 아닌 별칭은 "주의" 로 알리고 그 부분만 빼고 계속한다(사람 묶기를 확인 불능으로 만들지 않는다). 별칭이 적용된 담당은 "GitHub 아이디 형식이 아니다" 경고에서 빠진다.
- 열린 이슈·병합 PR 이 읽는 한도(이슈 500개, 병합 100개)를 넘으면 "오래 머문 이슈" 는 "확인 불능(부분)" 이고 병합 수는 "n+ (부분)" 으로 나온다. 갱신 시각을 읽지 못한 열린 PR 은 "판정 불능" 이지 정체 아님이 아니다.
- **"확인 불능" 으로 적힌 칸은 없다거나 정상이라고 말하지 않는다.** 사유를 그대로 전한다. 검사 실패 사유 문구가 비어 있으면 "사유 문구 없음" 이다.
- 사람마다 "누가 잘하고 못하는지" 평가하지 않는다. 숫자와 막힌 이유를 전하고, 막힘은 공통 원인부터 말한다.

`--json` 키(안정):

| 위치 | 키 |
|---|---|
| 최상위 | `status`(`ok`; 열린 PR 을 못 읽으면 `cannot_check`+`message`), `repo`, `generated_at`(UTC), `days`, `stale_days`, `issue_stale_days`, `common_causes`, `people`, `unassigned_issues`, `ledger`, `truncated`, `unknown`, `warnings` |
| `common_causes[]` | `id`, `mark`(①…), `checks[]`(해당 검사 이름 목록), `reason`(전체 문구, 300자를 넘으면 문장 끝에서 자르고 `…`), `prs[]`(`number`,`title`,`url`,`author`) |
| `people[]` | `login`, `progress`, `blocked`, `stale`, `dev_items` |
| `progress` | `merged[]`(`number`,`title`,`url`,`merged_at`), `merged_count`, `open[]`(`number`,`title`,`url`,`state`,`last_commit_at`,`last_activity_at`,`last_activity_kind`(`commit`·`opened`·`comment`·`review`·`review_comment`; 판정 불능이면 둘 다 null)) |
| `blocked[]` | 막힌 PR 하나당 한 항목: `pr`,`title`,`url`,`author`,`reasons[]`. `reasons[]` 항목은 `kind`(`check_failed`·`conflict`·`approval`·`after`·`other`·`unknown`),`state`,`detail`, 그리고 `checks[]`(`name`,`reason`,`reason_status`(`ok`·`no_text`·`unknown`),`common_cause`(공통 원인 `id` 또는 null),`unknown_reason`은 `unknown` 일 때만) 또는 `after[]`(앞 PR 번호); 검사 실패 항목에는 `checks_truncated`(검사가 너무 많아 일부를 읽지 못했으면 true) |
| `stale` | `unknown_prs[]`·`unknown_issues[]`(사람 활동 시각을 다 읽지 못해 정체 여부를 판정하지 못한 번호), `prs[]`(`number`,`title`,`url`,`state`,`last_activity_at`,`last_activity_kind`,`idle_days`), `issues[]`(`number`,`title`,`url`,`last_activity_at`,`last_activity_kind`(`comment`·`created`),`idle_days`) |
| `dev_items[]` | `id`(DEV-007), `title`, `owner`(원장 `담당` 칸, 비면 마지막 PR 작성자로 배정했다는 뜻으로 빈 문자열), `status`, `last_pr`, `file` |
| 그 밖 | `unassigned_issues[]`(`number`,`title`,`url`,`created_at`), `aliases_applied[]`(`name`,`login`,`items`: 원장 담당 이름이 어느 GitHub 아이디로 합쳐졌는지), `truncated`(`open_prs`·`merged`·`issues`: 쪽수·개수 제한으로 일부만 읽었으면 true), `ledger`(`status`(`ok`·`none`·`unknown`),`reason`,`branch`(저장소 기본 브랜치),`files`,`unowned[]` 담당을 못 정한 개발 건), `unknown[]`(`item`,`reason`), `warnings[]` |

읽지 못한 칸의 값은 `null`(빈 목록이 아니다)이고 `unknown[]` 에 사유가 있다. 병합·시각·이슈·원장이 각각 따로 확인 불능이 될 수 있다.

## 하지 않는 것

- PR 병합, 닫기, 코멘트, 푸시 — 이 스킬은 읽기만 한다. 병합은 `rules/governance.md` 와 훅이 정한 길로 한다.
- 엔진이 못 읽은 것을 "통과" 나 "문제없음" 으로 말하는 것.
- 남의 PR 을 대신 손보자고 제안하는 것(영향만 알린다).

## 관련 규칙

병합·리뷰 규칙은 `<이 스킬의 base directory>/../../rules/governance.md` 를 따른다.
`<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는 경로다.
