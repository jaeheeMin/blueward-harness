# #445 ledger-complete 를 쓰기 없는 검사기로 (2026-10-25)

## 배경

public-cloud main 에 ruleset 을 켰다. PR 이 필수라 ledger-complete 가 GITHUB_TOKEN 으로 병합 뒤 main 에 원장을 직접 push 하던 길이 막힌다. GitHub 은 github-actions 를 ruleset bypass 에 넣지 못한다(422).

## 폐기한 안: deploy key

bypass 에 DeployKey 를 넣고 ledger-complete 가 deploy key secret(`LEDGER_DEPLOY_KEY`)으로 push 하게 고쳤었다(PR #446 의 첫 커밋). 폐기했다. 쓰기 권한이 있는 팀원이 브랜치 push 로 도는 워크플로를 하나 만들어 그 secret 을 읽으면 main 보호 규칙을 우회할 수 있다. 우회로가 되는 secret 은 두지 않는다.

## 이미 켠 설정 (public-cloud)

| 항목 | 값 |
|---|---|
| 대상 | 기본 브랜치(main) |
| 규칙 | PR 필수(승인 0, 새 커밋 시 승인 취소) |
| 필수 상태 검사 | `pr-checks` / `check` (integration 15368) |
| 막은 것 | 브랜치 삭제, 강제 푸시 |
| bypass | Owner 만(DeployKey 는 뺐다) |
| 저장소 설정 | `allow_auto_merge` 켬 |

## 새 동작

| 곳 | 내용 |
|---|---|
| `/harness:deliver` 9단계 | 이 PR 본문의 `Closes\|Fixes\|Resolves #N` 이 가리키는 이슈 중 제목이 `[DEV-xxx]` 로 시작하는 대표 이슈면(판정 기준은 엔진 `closing_issues`·`representative_id`) 원장 행을 `리뷰` 대신 처음부터 `완료`, 마지막 PR 을 `#<PR번호>` 로 써서 PR 에 담는다. PR 이 병합되면 main 원장도 완료가 되고, 병합 안 되면 main 은 그대로다. 하위 작업 PR 은 지금처럼 `리뷰`, 완료는 사람이 쓴다 |
| `ledger-complete.yml` | 쓰기를 뺐다. 병합 뒤 처리 대상 커밋의 병합 PR 이 대표 이슈를 닫았는데 main 원장의 그 행이 `완료` 가 아니면 이슈를 열고 job 을 실패시킨다. 완료면 아무것도 안 한다. 판정 불능(gh 실패, 행 없음·둘 이상, 표 못 읽음)은 통과도 위반도 아니라 job 실패 + 이슈(원칙 7). permissions 는 `contents: read`, `pull-requests: read`, `issues: write` |
| `checker/ledger_complete.py` | `apply`(쓰기)를 `check` 로 바꿨다. 대표 이슈 찾기·원장 행 찾기·표 파싱·squash 제목 `(#N)` 대체 조회는 그대로 쓴다. 종료 0 통과, 1 완료 아닌 행, 2 판정 불능. push 한 번의 커밋 범위(`--before`)도 엔진이 푼다 |
| 지운 것 | `scripts/ledger_complete_loop.sh`(push 재시도 루프)와 `checker/tests/test_ledger_complete_loop.py`. 쓰기 전용이라 쓸모가 없어졌다. 엔진 안의 쓰기 코드(행 고쳐 쓰기, 줄 끝·BOM 보존)와 자기 커밋 건너뛰기(`docs: 진행 원장 완료 표시`)도 지웠다 |
| scaffold skeleton `ledger-complete.yml` | caller permissions 를 `contents: read` 로, 주석 갱신 |
| 문서 | deliver·start·srs·scaffold SKILL, `skeleton/audit/README.md`, `templates/harness/audit-ledger.md`, plugin README, 길잡이의 "병합 뒤 Actions 가 완료로 바꾼다" 문장을 새 동작으로 |
| `plugin.json` | 0.10.111 그대로 |

`scripts/ledger_complete.py`(진입점)는 `check` 를 부르므로 남겼다.

## 남은 일

- public-cloud 의 ledger-complete caller permissions 를 `contents: read` 로 줄인다(선택. `write` 로 남아도 이 워크플로는 쓰지 않는다).
- 이 판이 `stable` 로 배포된 뒤 public-cloud 의 deliver 가 새 방식으로 원장을 `완료` 로 담는지 실제 PR 로 확인한다.

## 그 사이 동작

새 판이 배포되기 전에는 deliver 가 대표 이슈를 닫는 PR 에도 `리뷰` 를 쓴다. 새 ledger-complete 가 먼저 돌면 그런 PR 이 병합될 때 원장이 `리뷰` 라서 이슈가 열릴 수 있다. 그 이슈는 원장을 PR 로 `완료` 로 고치면 닫는다. 새 deliver 판이 퍼진 뒤에는 대표 이슈를 닫는 PR 이 `완료` 를 담으므로 열리지 않는다.

**전환 안내**: 이 판이 `stable` 이 된 때 열려 있는, 옛 deliver(0.10.110 이하)로 만든 대표 이슈 PR 은 병합 전에
원장 행을 손으로 `완료`·마지막 PR 번호로 고친다. 고치지 않고 병합하면 위 이슈가 열린다.

## 알려진 한계

- deliver 는 PR 을 만들기 전에 본문에 넣을 `Closes` 를 보고 `완료` 를 쓴다. 뒤에 본문에서 `Closes #N` 이 빠지면 병합 뒤
  검사는 건너뛰어(`skipped`) 원장은 `완료` 인데 대표 이슈는 열린 채로 남을 수 있다. 반대로 사이드바로만 이슈를 연결하거나
  `owner/repo#N` 형식이면 엔진이 읽지 못해 `리뷰` 가 남아도 건너뛴다. 둘 다 엔진이 PR 본문 키워드만 읽는 기존 한계다.
- push 의 `before` 가 히스토리에 없으면(강제 푸시) 마지막 커밋 하나만 본다. main 은 강제 푸시가 막혀 있다.
