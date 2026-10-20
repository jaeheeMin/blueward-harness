# #370 내 PR 의 상태와 병합 순서를 한 곳에서 계산해 보여 주기 (2026-10-19)

팀원이 자기 PR 의 상태와 병합 순서를 모른다. 여러 세션에서 PR 을 만들면 세션끼리도 모른다. GitHub 에서 한 번 계산하고(`checker/pr_queue.py`), 세션 시작·`/harness:prs`·deliver 가 같은 계산을 쓴다. 이 기록은 1단계(읽기·표시·의존 기록)다.

## 1단계에서 한 것

- 엔진 `python -m checker.pr_queue --repo owner/repo [--mine | --all] [--json] [--quiet-empty]`. 열린 PR 을 `gh pr list --json …` 한 번으로 읽는다(100개 제한, 꽉 차면 "일부만 읽음").
- 상태(우선순위 하나 + 보조 표시): 초안 > 충돌 > 검사 시작 전(롤업이 비어 있음) > 검사 실패(이름) > 검사 중 > 승인 대기 > 충돌 여부 확인 중 > 뒤처짐·병합 막힘·검사 불안정(`mergeStateStatus` BEHIND·BLOCKED·UNSTABLE) > 병합 가능. `mergeable` UNKNOWN 은 충돌 없음이 아니라 "확인 중". `mergeStateStatus` 가 CLEAN·HAS_HOOKS 가 아니면 병합 가능이라 하지 않는다(모르는 값은 "충돌 여부 확인 중"). 병합 가능이어도 `.github/human-merge-paths` 에 걸리면 "사람이 GitHub 에서 병합".
- 승인 대기: `risk-gate` 실패를 곧바로 승인 대기라고 하지 않는다. risk-gate 가 실패한 PR 만 github-actions 봇의 마지막 `<!-- risk-gate -->` 코멘트를 읽는다. "사람의 승인이 필요합니다" 일 때만 그 PR 의 리뷰를 읽어 head 커밋 기준 남은 승인자를 계산해 "승인 대기(누구) — 이유 요약" 으로 말한다(`judge_by_rules` 재사용, 낡은 승인 표시). 위험도 검사 불능·그 밖의 사유는 "검사 실패: risk-gate: <사유 요약>", 코멘트가 없거나 못 읽으면 "risk-gate 실패(사유는 PR 코멘트)". 승인은 받았는데 게이트가 실패면 "검사 실패(risk-gate)". `ssot-approval` 실패는 SRS 승인 대기라 리뷰로 판정한다. 전체 PR 에 `decide_pr` 을 돌리지 않는다. 승인자 파일·human-merge-paths 는 base 브랜치당 한 번.
- 순서: (a) base 가 다른 열린 PR 의 head, (b) 본문 `먼저: #n, #m`, (c) 같은 DEV 의 SRS→Spec→개발, (d) plugin.json 을 바꾼 PR 끼리 head version 이 낮은 쪽 먼저. 위상 정렬(동률은 번호 오름차순). 실제 순환(강연결 성분)의 구성원만 "순서 판정 불능(순환)", 그 뒤에 기다리는 PR 은 "앞 PR 순서 판정 불능 #…". `reduce_edges` 는 ancestors 를 메모이제이션한다(순환을 건너뛴 불완전한 결과는 메모하지 않는다). 표의 "먼저 병합할 PR" 은 다른 앞 PR 을 거쳐 이미 앞서는 것을 뺀 직접 선행만 보인다(`--mine` 필터는 전이 포함). 같은 파일을 고친 PR 쌍은 경고만.
- 읽기 실패는 "PR 상태 확인 불능 — 사유", 종료코드 2(통과·문제없음으로 말하지 않는다, 원칙 7). 예상 못 한 예외도 "PR 상태 확인 불능 — 예상 못 한 오류 <종류>" 종료코드 2. 한 PR 의 리뷰·version 만 못 읽으면 그 PR 만 "확인 불능" 이나 경고로 남기고 나머지는 계산한다.
- SessionStart(`session-start-sync.sh`): fetch 가 성공했고 origin 이 github.com 일 때만 `--mine --quiet-empty --max-rows 10` 을 `timeout 20`(`HARNESS_PR_TIMEOUT` 로 조정) 으로 부른다. 내 PR 이 없으면 아무것도 안 낸다. PR 은 10줄까지, 나머지는 "외 n개 — /harness:prs"(`--max-rows`, 경고 줄도 줄임). 실패는 한 줄 "PR 상태 확인 불능(사유) - /harness:prs …". 시간 초과(124)는 "PR 상태 확인이 오래 걸려 건너뜀 — /harness:prs 로 확인" 한 줄을 내고 같은 엔진 판을 백그라운드로 받아 두어(분리 실행, 출력 버림) 다음 세션을 빠르게 한다. `timeout` 명령이 없으면 블록을 건너뛰고 한 줄 안내. 훅은 계속 exit 0. 새 훅 파일은 만들지 않았다(`hooks.json` 변경 없음). 테스트는 `checker/tests/test_session_pr_block.py`(가짜 uvx). 지난 세션 기록(format=2) 판정의 `tr -d '\r'` 한 줄이 깨졌던 것은 원래 동작으로 되돌렸고, CRLF 기록 + fetch 실패 경로를 같은 테스트가 잡는다.
- 스킬 `/harness:prs`(읽기 전용, `--all`).
- deliver: `--base` 를 `gh pr create --base` 에도 넘김을 명시. PR 본문의 `## 병합 순서` 와 `먼저: #n` 규칙(base 브랜치의 열린 PR, 같은 DEV 의 앞 단계 PR). PR 을 만든 뒤 `--mine` 으로 "n번째, 앞: #m" 을 알린다(2단계 항목이지만 deliver 가 이미 엔진을 부르므로 같이 넣었다).
- 문서: CLAUDE.md·README.md·plugins/harness/README.md 스킬 표, governance.md 병합 순서 한 줄, 길잡이 새 탭 "내 PR 확인하기".

## 설계상 판단·한계

- SRS PR 의 DEV 번호는 SRS 파일 diff 를 읽지 않고 제목·브랜치·본문(과 Spec 파일 이름)의 `DEV-n`·`REQ-n` 에서 읽는다. 본문이 다른 번호를 언급하면 불필요한 순서가 생길 수 있다. 번호를 못 읽은 PR 은 (c) 에 들어가지 않는다.
- `statusCheckRollup` 의 이름은 `risk-gate / check` 처럼 워크플로 이름이 앞에 붙는다. 알림 job(`… / alert`)은 검사로 세지 않는다.
- 같은 version 인 plugin.json PR 끼리는 순서를 정하지 않는다(겹침은 #324 검사가 경고한다).
- 훅은 엔진을 플러그인 판 태그 `v{version}` 으로 받으므로, 새 판이 병합돼 태그가 붙기 전에는 이 알림이 "확인 불능" 으로 나온다.

## 고친 것 (#375, 0.10.89)

롤업을 검사 이름별 최신 실행으로 줄이지 않아, 다시 돌린 검사의 앞 실행(취소)이 남은 PR 을 "검사 실패" 로 보여 줬다(public-cloud #248~#264). 이제 같은 검사(워크플로+이름, 커밋 status 는 context)는 시작 시각이 가장 늦은 실행 하나만 본다. 같은 검사 가운데 시각을 모르는 실행이 있으면 줄이지 않는다(실패를 통과로 바꾸지 않음).

## 2단계 (0.10.90)

- 엔진 `--pr N [--json]`(`compute_before`): 그 PR 보다 먼저 병합해야 하는 **열린** PR 의 직접 선행(`reduce_edges`)과 이유(`after_reasons`)만 묻는다. 종료코드 0 앞 PR 없음, 1 있음, 2 확인 불능. 상태 판정(승인·risk-gate 코멘트 조회)은 하지 않아 `compute` 보다 gh 호출이 적다(`gh pr list` 한 번 + plugin.json 을 바꾼 PR 의 version 조회).
- 확인 불능(2)인 경우: GitHub 읽기 실패, 그 PR 이 열린 목록에 없음, 열린 PR 이 100개 이상, 그 PR 이 순환에 들었거나 순환 뒤에 기다림, 그 PR 이 plugin.json 을 바꿨는데 열린 PR 의 version 을 못 읽음. 순환이 다른 PR 에만 있으면 무관한 PR 은 막지 않는다. 같은 파일 경고는 막지 않는다.
- 훅 `pre-bash-git-guard.sh` `check_one_merge`: `gh pr checks` 검사(-1)와 `uvx` 확인 다음, SRS 승인 검사 앞에 둔다(`engine_spec` 으로 정한 엔진 판 + `uvx`). 앞 PR 이 열려 있으면 "#m(제목) - 이유: …" 와 "먼저 #m 을 병합 / 순서가 틀렸으면 본문의 `먼저:` 줄을 고쳐라 / /harness:prs" 로 거부한다. 종료코드 2·JSON 아님·`status` 가 ok 가 아님·ok 인데 종료코드가 0/1 이 아님은 모두 사유와 함께 거부한다(원칙 7). 위치를 앞쪽에 둔 이유: 순서가 틀린 PR 은 어차피 병합할 수 없으니 승인·위험도 조회(gh 여러 번)를 헛되이 하지 않게 하려는 것이다. 비용은 병합 한 번에 엔진 호출 한 번 더.
- 한계: 사람이 GitHub 화면에서 병합하는 것은 막을 수 없다(무료 요금제). 훅은 Claude 의 `gh pr merge` 만 막는다. 엔진 판 태그가 아직 없으면 이 검사도 "확인 불능" 으로 거부한다(다른 엔진 검사와 같다).
- `/harness:start`: 이슈·브랜치를 만든 뒤 `--mine --max-rows 5 --quiet-empty` 로 내 PR 을 알린다(병합 가능한 것, 승인 대기·검사 실패 한 줄 요약). 막지 않고, 엔진 실패는 "PR 상태 확인 불능" 한 줄만 말하고 계속한다.
- 테스트: `test_pr_queue.py`(`--pr` 열림·없음·체인·version·경고만·순환·무관 순환·읽기 실패·목록에 없음·version 못 읽음·100개), `test_plugin_layout.py`(가짜 uvx 의 `checker.pr_queue` 응답으로 통과·거부·확인 불능·JSON 아님). 가짜 uvx 의 기본 응답은 "앞 PR 없음" 이다.
- 문서: governance.md, plugins/harness/README.md, 길잡이 "작업 시작하기"·"리뷰·병합하기"·"내 PR 확인하기".

## 3단계 (0.10.91)

Claude 를 안 쓰는 사람도 같은 정보를 받게 Actions 로 옮겼다.

- 재사용 워크플로 `.github/workflows/pr-queue.yml`(`workflow_call`, 입력 `engine-ref` 기본 stable, 선택 secret `TEAMS_PLUGIN_ALERT_WEBHOOK`)이 `scripts/pr_queue_actions.py` → `checker/pr_queue_actions.py` 를 부른다. 엔진 체크아웃·uv 실행은 risk-gate.yml 과 같다. job 에 permissions 를 적지 않고(부르는 쪽 권한 그대로), concurrency `pr-queue-<저장소>` cancel-in-progress.
- 한 번에 `compute` 로 열린 PR 전체를 계산하고 열린 PR 마다: (1) 코멘트 하나(github-actions 봇, 마커 `<!-- pr-queue -->`) 만들기·갱신 — 시각 같은 값이 없어 같은 내용이면 쓰지 않는다. (2) 커밋 status `merge-order`: 앞 PR 열림 failure("#m 먼저 병합", 140자), 없음 success, 순환 등 순서 판정 불능 error(통과로 두지 않음), 열린 PR 100개 이상이거나 plugin.json version 을 못 읽은 PR 이 순서에 걸리면 앞 PR 이 없다고 말하지 않고 error. 이미 같은 state·description 이 달려 있으면 쓰지 않는다(commit·context 당 status 한도). 닫힌 PR 은 건드리지 않는다.
- 쓰기 횟수: 실행 한 번에 PR 마다 읽기(코멘트 목록, 현재 status) 2회, 쓰기는 내용이 바뀐 것만(코멘트 최대 1회, status 최대 1회). 변화가 없는 실행의 쓰기는 0회. 상태가 바뀐 PR(예: 검사 중 → 병합 가능)은 코멘트 갱신이 생긴다.
- 차례 알림: 이벤트가 병합인지에 기대지 않고, 코멘트에 숨겨 둔 직전 앞 PR 목록(`<!-- pr-queue:after=… -->`)과 비교한다. 앞 PR 이 있었는데 이제 없고(order 가 정해짐), 사라진 앞 PR 이 모두 병합(`pulls/<n>.merged`)이면 알린다. 닫기만 한 경우는 알리지 않는다. 이렇게 한 까닭: 병합이 만드는 main push 실행이 병합 실행을 concurrency 로 취소하면 이벤트 기반 알림이 사라진다. 알림은 마커 코멘트 갱신으로는 푸시 알림이 안 가서 `@작성자` 가 든 짧은 새 코멘트(`<!-- pr-queue-turn:… -->`, 같은 앞 PR 집합이면 한 번만) 하나와 Teams. Teams 는 pr-tamper-alert·human-merge-alert 와 같은 secret `TEAMS_PLUGIN_ALERT_WEBHOOK` 의 Adaptive Card 방식이고, 비어 있으면 건너뛴다고 job 요약에만 남긴다. Teams 전송 실패는 PR 코멘트가 이미 남은 뒤라 경고(job 요약)로만 두고 웹훅 URL 은 출력하지 않는다. 이전 코멘트가 없는 첫 실행은 알리지 않는다.
- 실패: 열린 PR 을 못 읽으면 "PR 순서 확인 불능" 을 job 요약에 쓰고 종료코드 2 → job 실패(통과 아님). 한 PR 의 코멘트 목록을 못 읽어도 2. 코멘트·status 쓰기 실패는 종료코드 1 → job 실패, 요약에 사유와 caller permissions 안내. 포크에서 온 PR 의 이벤트는 토큰이 읽기 전용이라 쓰지 않고 계산표만 요약에 남긴다(ssot-approval 도 포크 PR 을 범위 밖으로 둔다).
- `merge-order` 를 다른 판정에서 뺐다: `checker/risk_gate.py` `EXCLUDED_CHECK_GROUPS`(`merge-order`, 그 워크플로 job `pr-queue / …`), `checker/pr_queue.py` 의 검사 판정(실패·진행 중 제외, `merge-order` 가 failure 라 UNSTABLE 이 된 것은 검사 불안정으로 말하지 않음, 그것만 있으면 "검사 시작 전"), 훅 `pre-bash-git-guard.sh` (-1) 의 `gh pr checks` 판정(순서는 바로 다음 -1-1 이 정확한 메시지로 막는다). `pr-queue / …` job 도 같이 뺀 까닭: 저장소 하나에 concurrency 그룹이라 다른 PR 의 실행이 이 실행을 취소하면 그 PR 커밋에 취소된 검사가 남아 병합 훅이 "검사 실패" 로 막기 때문이다.
- scaffold caller `skeleton/dot-github/workflows/pr-queue.yml`(이벤트 PR opened·synchronize·reopened·ready_for_review·closed·edited, 리뷰 submitted·dismissed, main push; 권한 contents read, pull-requests·issues·statuses write; job id `pr-queue`)과 SKILL.md·test_scaffold 목록.
- 이 저장소 자신의 caller: 필요하다(plugin.json version 순서가 이 저장소의 병합 순서 문제다). 다만 이 저장소는 자기 재사용 워크플로를 부르는 caller 를 하나도 두지 않았고(checker.yml 만 직접 돈다), caller 가 `@stable` 을 쓰면 0.10.91 태그가 붙기 전에는 엔진에 `pr_queue_actions` 가 없어 모든 PR 에서 빨갛게 실패한다. 그래서 이번 PR 에서는 넣지 않고, 0.10.91 병합으로 `stable` 이 붙은 뒤 후속으로 `.github/workflows/pr-queue-self.yml`(`uses: ./.github/workflows/pr-queue.yml`)을 넣는다. human-merge-paths 는 그대로.
- 검토 반영: (1) 차례 알림 코멘트를 못 남기거나 앞 PR 병합 여부를 못 읽으면 마커 `after=` 를 이전 값으로 두어 다음 실행에서 다시 시도한다. Teams 전송 여부는 알림 코멘트의 표식(`<!-- pr-queue-teams:sent -->`, 웹훅이 없었으면 `:na`)으로 남기고, 코멘트는 있는데 표식이 없으면(웹훅이 있을 때) Teams 만 다시 보낸다. (2) `post_teams` 는 어떤 예외든 메시지 없이 종류(HTTP 면 상태코드)만 남겨 웹훅 값이 요약에 안 나간다. (3) 트리거 한계: 코멘트는 PR·리뷰·main 이벤트 때 갱신될 뿐 검사 결과가 바뀐 것만으로는 돌지 않아 검사 상태가 다음 이벤트까지 낡을 수 있다(정확한 지금 상태는 `/harness:prs`). 트리거에 `converted_to_draft` 추가. (4) 턴 표식 중복 확인은 봇(`github-actions[bot]`) 코멘트만 본다. (5) 코멘트에 넣는 PR 제목·검사 이름·detail·참고는 `@` 무력화(risk_gate `_defuse`)에 더해 `<`·`>`·백틱을 escape 한다. (6) Dependabot(`sender.login`/`GITHUB_ACTOR` 가 `dependabot[bot]`)이 일으킨 실행은 토큰이 읽기 전용이라 포크 PR 처럼 쓰기를 건너뛰고 요약만 남긴다. (7) `apply` 안 예상 못 한 예외는 "PR 순서 처리 중 예상 못 한 오류 <종류>" + 종료코드 2(쓰기 실패 1 과 구분).
- 알려진 한계(이름 기반 제외): `merge-order`·`pr-queue` 를 다른 검사 판정에서 빼는 것은 이름으로 거른다. 다른 워크플로가 같은 이름의 검사를 달면 위조가 가능하다. 기존 `ssot-approval` 제외와 같은 한계이고, 이 저장소는 무료 요금제라 서버 강제로 막지 못한다.
- 테스트: `test_pr_queue_actions.py`(코멘트 본문, 변경 없으면 쓰기 0, 같은 코멘트 갱신, status 상태·140자·순환 error·version 못 읽음·100개, 차례 알림 대상·중복 방지·닫기만 한 경우·Teams 없음/실패, 읽기 실패·쓰기 실패·포크), `test_pr_queue_workflow.py`(트리거·권한·concurrency·engine-ref), `test_pr_queue.py`·`test_risk_gate.py`·`test_plugin_layout.py`(merge-order 제외), `test_scaffold.py`.

### public-cloud 에 넣을 것

재사용 워크플로는 `@stable` 로 받으므로 0.10.91 병합 뒤 자동으로 받지만, caller 가 없으면 아무 일도 안 한다. public-cloud 에 `.github/workflows/pr-queue.yml` 을 새로 넣는다(스캐폴드 caller 와 같은 내용).

```yaml
name: pr-queue
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review, converted_to_draft, closed, edited]
  pull_request_review:
    types: [submitted, dismissed]
  push:
    branches: [main]

jobs:
  pr-queue:
    uses: jaeheeMin/blueward-harness/.github/workflows/pr-queue.yml@stable
    secrets:
      TEAMS_PLUGIN_ALERT_WEBHOOK: ${{ secrets.TEAMS_PLUGIN_ALERT_WEBHOOK }}
    permissions:
      contents: read
      pull-requests: write
      issues: write
      statuses: write
```

- 필요한 secret: `TEAMS_PLUGIN_ALERT_WEBHOOK`(이미 pr-tamper-alert·human-merge-alert 가 쓰는 것. 없으면 Teams 만 건너뜀). 새 secret 은 없다.
- 이 파일은 `.github/` 아래라 risk-gate 위험 경로다(승인자 Approve 필요, human-merge-paths 에 걸리면 사람이 병합).
- 한계: 무료 요금제라 `merge-order` 빨간불로 Merge 버튼이 잠기지 않는다(훅은 Claude 의 `gh pr merge` 만 막는다). 조직·유료로 옮기면 `merge-order` 를 required status 로 바꿀 자리다.
