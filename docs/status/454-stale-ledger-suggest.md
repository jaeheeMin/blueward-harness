# #454 옛 판 PR 의 원장 미완료를 알아채 제안하고 deliver 가 원장만 고쳐 올리기 (2026-10-25)

## 배경

#445(0.10.111)부터 대표 `[DEV-xxx]` 이슈를 Closes 하는 PR 은 deliver 가 원장 행을 처음부터 `완료` 로 담는다. 옛 판으로 만든 열린 PR 은 원장이 `리뷰` 로 남는데 팀원은 알아채지 못했고, 고친 파일이 없으면 deliver 가 "변경 없음" 으로 멈췄다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `checker/ledger_stale.py` (신규) | 내 PR 의 `closes` 이슈 중 `[DEV-xxx]` 대표 이슈마다 PR head 의 `audit/ledger/*.md` 에서 그 행을 읽어 `완료` 가 아니면 `pending`, 못 읽으면 `unknown`. 원장 폴더가 없거나 대표 이슈를 안 닫으면 조용히 건너뜀 |
| `checker/ledger_complete.py` | `_find_rows` 의 본문을 `find_rows_text` 로 분리(파일이 아닌 텍스트에서 행 찾기). 동작은 그대로 |
| `checker/pr_queue.py` | 항목에 `closes`·`ledger` 추가, `--mine` 일 때만 `ledger_stale.annotate`. 표 아래 `⚠`/`❓` 원장 줄, PR 칸 `⚠` |
| `hooks/pr_table_notice.py` | 원장 줄(`원장 고쳐서 다시 올려줘`)이 있으면 Claude 에게 먼저 제안·브랜치 이동·미커밋 확인 안내를 덧붙임 |
| `skills/prs/SKILL.md`, `skills/deliver/SKILL.md` | prs: 원장 줄 읽는 법과 제안. deliver: 2단계 예외와 9단계 "옛 판 PR 의 원장 고치기" |
| `docs/guide/harness-guide.html` | "내 PR 확인하기"·"작업 올리기" 탭에 설명 |
| `checker/tests/test_ledger_stale.py` | 판정·출력 시험 |

## 결정

- 판정 불능(행 0개·2개 이상, 표 형식, 조회 실패)은 `unknown` 으로 `❓` 줄에 따로 낸다. 완료도 미완료도 아니다(원칙 7).
- API 는 대표 이슈를 닫는 것으로 보이는 내 PR(본문에 Closes 있음)만 더 읽는다. `--all` 은 판정하지 않는다.
- 세션 시작 셸(`session-start-sync.sh`)은 바꾸지 않았다. 엔진 출력이 그대로 첫 프롬프트에 실린다.
- deliver 예외는 푸시 한 번 원칙(#410)을 지킨다: 원장만 고친 커밋 하나, 푸시 하나.
