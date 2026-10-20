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

## 남은 일

- 3단계: Actions 로 PR 코멘트·체크에 병합 순서 표시.
