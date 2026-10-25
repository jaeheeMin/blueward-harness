# #437 deliver 의 PR 판단과 자동 병합 예약 (2026-10-25)

## 배경

PR 나누기 기준을 다시 정했다(한 PR = 한 DEV 의 한 단계 / 안 끝난 개발은 브랜치에만 / 끝난 PR 은 자동 병합 / 개발 PR 은 쌓지 않음 / 승인된 PR 에는 더 얹지 않음). 팀원이 외우지 않도록 `/harness:deliver` 가 상황을 보고 추천 하나를 쉬운 말로 제안하고 `AskUserQuestion` 으로 확인받는다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `skills/deliver/SKILL.md` | 8단계 "PR 을 낼지 판단" 추가(섞임 → 나눠서 / 안 끝남·쌓기·앞 단계 열림 → 브랜치에만 / 승인된 PR → 먼저 병합 / 그 밖 → PR 내기). 뒤 단계 번호를 하나씩 밀었다. 14단계에서 자동 병합 예약, 즉시 병합(15단계)은 예약했으면 건너뜀 |
| `pre-bash-git-guard.sh`, `checker/merge_command.py` | `gh pr merge --auto` 는 검사 진행 중·앞 PR 대기·SRS 승인·사람 병합 경로 판정을 건너뛰고 허용(서버가 필수 검사·승인을 기다림). 남의 PR 금지는 그대로. `--admin` 은 어떤 PR 에도 거부(이전에는 훅이 막지 않았다) |
| `rules/governance.md`, `rules/commit-and-pr.md` | 기준 1~5, 자동 병합 정책, 한 PR = 한 DEV 의 한 단계 |
| `docs/guide/harness-guide.html` | deliver 탭에 세 갈래, merge 탭에 자동 병합 |

## 자동 병합을 거는 조건

`gh api repos/{repo} --jq .allow_auto_merge` 가 true 이고, base 에 필수 상태 검사가 있을 때만(`gh api repos/{repo}/rules/branches/{base}` 의 `required_status_checks`, 또는 옛 보호 `.../protection/required_status_checks` 의 contexts/checks). 사람이 병합해야 하는 경로를 바꾼 PR 에는 걸지 않는다. 판정 못 하면 걸지 않고 사유를 알린다. 필수 검사 없이 걸면 바로 병합되기 때문이다(원칙 7).

## 하지 않은 것

- `stop-deliver.sh` 는 고치지 않았다. 변경이 없으면 조용히 끝나고(원격 PR 유무를 보지 않는다) 미커밋 변경이 있을 때만 막으므로, 브랜치에만 올린 작업을 막지 않는다.
- `/harness:prs` 의 "브랜치에만 올려 둔 작업" 표시와 깊이 3 이상 줄기 경고는 넣지 않았다. 앞의 것은 GitHub 에서 "PR 없는 내 브랜치" 를 읽어야 해 별도 이슈가 낫다.
- 훅은 `--auto` 라도 사람 병합 경로(`.github/human-merge-paths`)를 바꾼 PR 은 거부한다(메인 세션 결정). `--auto` 가 건너뛰는 것은 검사 진행 중·앞 PR 대기·SRS 승인·위험도 판정뿐이다. deliver 도 그런 PR 에는 예약을 걸지 않는다.
