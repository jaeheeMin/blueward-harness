# #445 ledger-complete 를 deploy key 로 push (2026-10-25)

## 배경

public-cloud main 에 ruleset 을 켰다. PR 이 필수라 ledger-complete 가 GITHUB_TOKEN 으로 main 에 직접 push 하던 길이 막힌다. GitHub 은 github-actions 를 ruleset bypass 에 넣지 못한다. 그래서 bypass 에 DeployKey 를 넣고, ledger-complete 가 deploy key(SSH)로 push 하게 바꿨다.

## 이미 켠 설정 (public-cloud)

| 항목 | 값 |
|---|---|
| 대상 | 기본 브랜치(main) |
| 규칙 | PR 필수(승인 0, 새 커밋 시 승인 취소) |
| 필수 상태 검사 | `pr-checks` / `check` (integration 15368) |
| 막은 것 | 브랜치 삭제, 강제 푸시 |
| bypass | OrganizationAdmin, DeployKey |
| 저장소 설정 | `allow_auto_merge` 켬 |

github-actions 를 bypass actor 로 넣으려 하니 422 로 거부됐다(GitHub 이 Actions 를 bypass 대상으로 허용하지 않는다).

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `.github/workflows/ledger-complete.yml` | `workflow_call` 에 선택 secret `LEDGER_DEPLOY_KEY` 추가. "Project Repository 받기" checkout 에 `ssh-key` 로 넘김. 비면 checkout 이 토큰을 그대로 써서 secret 없는 저장소는 동작이 같다. 머리 주석에 등록 절차와 caller 예시의 secrets 줄 |
| scaffold skeleton `ledger-complete.yml` | caller 에 `secrets: LEDGER_DEPLOY_KEY` 와 주석 |
| `skills/scaffold/SKILL.md` | 보호 규칙을 켠 저장소는 deploy key 가 필요하다는 안내 |
| `docs/guide/harness-guide.html` | ledger-complete 행에 같은 안내 |
| `plugin.json` | 0.10.109 → 0.10.111 (0.10.110 은 다른 PR) |

deploy key 로 push 하면 GITHUB_TOKEN 과 달리 main push 워크플로가 다시 돈다. 원장 완료 커밋 하나마다 main-checks 와
ledger-complete 가 한 번 더 돌고, ledger-complete 는 자기 커밋 제목을 보고 건너뛴다(되풀이 없음, 분은 1~2분 더 든다).

`scripts/ledger_complete_loop.sh` 는 고치지 않았다. fetch·push 가 checkout 이 잡은 `origin` 을 그대로 쓰고 origin URL 을 다시 설정하는 곳이 없다.

## 남은 일

- public-cloud 에 deploy key 생성(`ssh-keygen -t ed25519 -N "" -f ledger_key`), 공개키를 Deploy keys 에 "Allow write access" 로 등록, 비밀키를 Actions secret `LEDGER_DEPLOY_KEY` 로 등록.
- public-cloud 의 ledger-complete caller 에 `secrets: LEDGER_DEPLOY_KEY` 적용(스캐폴드 갱신 또는 손으로).
- 병합 뒤 실제 PR 병합으로 원장 완료 push 가 되는지 확인.
