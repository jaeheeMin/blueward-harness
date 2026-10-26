# #479 대표 이슈를 닫는데 원장이 완료가 아닌 PR 을 pr-checks 에서 막기 (2026-10-26)

## 배경

public-cloud #347(DEV-010)이 원장 `리뷰` 인 채로 병합돼 ledger-complete 가 병합 뒤 #377 을 열었다. 옛 판으로 만든 PR 은 deliver·세션 알림(#454)이 닿지 않는다. public-cloud main 은 `pr-checks / check` 가 필수라 이 검사에서 막는다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `checker/ledger_stale.py` | `check_pr`(PR 본문·head 를 API 로 읽어 `judge` 재사용), `render_markdown`, CLI `check-pr`. 종료 0 통과 / 1 위반(pending) / 2 판정 불능. pending 과 불능이 섞이면 위반 |
| `scripts/ledger_ready.py` | 얇은 진입점(`ssot_approval.py` 와 같은 모양) |
| `.github/workflows/pr-checks.yml` | `ledger-ready` 단계와 코멘트 단계를 ssot-approval 뒤·risk-gate 앞에 추가, 종합에 `judge "ledger-ready"` |
| `docs/guide/harness-guide.html` | 검사 표에 `ledger-ready` 한 줄 |
| `checker/tests/` | `test_ledger_ready.py` 신규, `test_pr_checks_workflow.py` 에 새 단계·종합 포함 |

## 결정

- 판정 불능은 다른 단계와 같이 종합에서 "검사 불능" 으로 세어 job 을 실패시킨다(통과로 뭉개지 않는다). 대표 이슈 없음·하위 작업만·원장 없는 저장소·완료는 통과.
- Closes 읽기는 `ledger_complete.closing_issues` 를 그대로 쓴다. 단 이벤트 페이로드가 아니라 API 로 본문을 읽는다(낡은 본문 방지).
- 새 commit status(`ledger-ready`)는 달지 않는다. 읽는 엔진·훅이 없고, 종합(`pr-checks / check`)에 들어가므로 ruleset 필수 검사는 그대로다. 코멘트는 마커 `<!-- ledger-ready -->` 한 개를 갱신하고 통과하면 지운다. 같은 내용을 job 요약에도 쓴다.
- 권한: contents·issues 읽기와 PR 코멘트 쓰기뿐이라 caller 권한(contents read, pull-requests·issues·statuses write)을 늘리지 않는다. caller 변경 없음.

## 한계와 남은 일

- 트리거에 `edited` 가 없어(#411, Actions 분 절감) PR 본문의 `Closes` 만 고친 경우는 다시 판정되지 않는다. 원장을 고쳐 푸시하면 synchronize 로 다시 돈다. `edited` 를 넣을지는 분 소모 때문에 사용자 결정이 필요하다(넣으면 본문 수정마다 pr-checks 한 번 더).
- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
