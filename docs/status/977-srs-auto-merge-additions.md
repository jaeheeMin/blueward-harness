# #977 SRS 같은 자리 줄 추가 충돌 자동 합치기 (0.10.295)

## 배경
여럿이 SRS 를 동시에 고치면 같은 자리 줄 추가 충돌이 반복된다. deliver(rebase)·sync(merge)·세션 시작 훅이 충돌을 만나면 abort 하고 사람에게 넘겼다. 충돌 파일이 `docs/ssot/SRS.md` 하나뿐이고 양쪽이 줄만 추가한 경우에 한해 자동으로 합친다.

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/srs_automerge.py` | 새 CLI. index stage 로 base·main·내 쪽을 읽어 `git merge-file -p --zdiff3` 로 다시 합치고, 덩어리마다 조건을 보고, 결과를 `srs_shape` + 같은 줄 중복 검사한 뒤 작업 폴더에 쓰고 `git add`. 결과 `merged`/`refused`/`cannot_check` |
| `checker/tests/test_srs_automerge.py` | 임시 저장소에서 merge·rebase 각각 28개: 표 끝·상세 절·공통 줄 섞인 추가(자동, main 먼저), 버전 줄·표 머리글·열 수·같은 REQ 번호·같은 줄 수정·다른 파일도 충돌·모양 검사 걸림(거절), 커밋·continue, CLI |
| `checker/tests/test_srs_automerge_hook.py` | 세션 시작 훅: merge 자동 합침·커밋, rebase 커밋 여럿 이어 합침, 버전 충돌 거절·되돌림, 엔진 실패, merged 아닌 출력 |
| `plugins/harness/hooks/session-start-sync.sh` | `try_srs_automerge`·`srs_auto_note` 추가. `run_rebase` 는 충돌 때 합치고 `GIT_EDITOR=true git rebase --continue` 를 상한 20번 되풀이, `run_merge` 는 합친 뒤 커밋. 아니면 지금처럼 abort. 합쳤으면 "승인을 다시 받아야 해" 알림 |
| `plugins/harness/skills/sync/SKILL.md`, `skills/deliver/SKILL.md` | "충돌은 스스로 풀지 않는다" 에 이 예외와 절차(엔진 호출 → merged 면 continue/커밋, 아니면 abort 보고), deliver 는 PR 보고에 "다시 승인 받아야 해" |
| `docs/guide/harness-guide.html` | sync 탭·deliver 탭 충돌 설명, 약속 표의 리베이스 충돌 줄 (병합 뒤 아티팩트에 다시 올린다) |
| `checker/README.md` | `srs_automerge` 절 |
| `plugins/harness/console/whats_new.json`, `.claude-plugin/plugin.json` | 0.10.295 |

## 결정
- 같은 줄 중복 검사에서 제목 줄(`#`)을 뺐다. 상세 절 하나를 더하면 `#### Short Description` 이 늘어 항상 걸렸다(실험으로 확인). 같은 번호 제목은 REQ 번호 겹침과 `srs_shape` 가 따로 잡는다. base 에 이미 있던 줄이 늘어나는 것도 중복으로 보지 않는다.
- 번호 겹침은 덩어리별이 아니라 파일 전체에서 "base 에 없던 번호" 끼리 본다(표 행과 상세 절이 다른 덩어리여도 잡는다).
- 표 행은 새 표를 시작하면(바로 앞 줄이 표 행이 아님) 거절한다. 새 표의 머리글을 검사할 수 없어서다.
- 충돌 표시 모양이 예상과 다르거나 줄바꿈이 CRLF/LF 로 섞이면 거절·검사 불능으로 둔다.
- 훅은 충돌 파일이 SRS 하나일 때만 엔진(uvx)을 부른다 — 다른 충돌에서 엔진을 받느라 세션 시작이 늦어지지 않게.
- 엔진 호출 실패·종료코드≠0·`merged` 없는 출력은 모두 합치지 않은 것으로 보고 abort 한다(통과로 뭉개지 않음).
- `skeleton` rules·`workflow.json` 은 건드리지 않았다(quote 가 "충돌" 문장을 담지 않음).

## 시험
`test_srs_automerge.py` 28, `test_srs_automerge_hook.py` 6 통과(최종 보고에 나머지).
