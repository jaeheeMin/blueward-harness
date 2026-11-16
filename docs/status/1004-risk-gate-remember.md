# #1004 risk-gate 가 한 번 위험 판정을 받은 PR 을 기억해 승인 요구 유지 (2026-11-16)

## 배경
risk-gate 는 마지막 커밋만 판정해서, 위험 사유(AI 리뷰 심각 지적 등)를 고친 커밋을 강제 푸시하면 사람이 한 번도 보지 않은 채 자동 병합됐다(public-cloud#745).

## 결정과 이유
| 결정 | 이유 |
|---|---|
| 기억 대상은 `ai_review`·`paths`·`secret` 사유만 | "다른 검사 실패·진행 중" failure 는 시간이 지나면 풀리는 사유라 기억하면 정상 PR 이 막힌다 |
| 기억 근거는 이전 SHA 의 봇 `risk-gate` failure commit status | 작성자가 지우는 API 가 없다. 라벨·봇 코멘트·Actions 실행은 작성자가 지울 수 있어 쓰지 않는다 |
| 사유 코드를 description **맨 앞** `[위험: a,b]` 에 적는다 | GitHub 이 description 을 140자로 자른다. 뒤에 두면 잘릴 수 있다 |
| 코드 없는 옛 failure 는 기억하지 않는다 | 이 변경 전 failure 는 대부분 검사 진행 중이던 기록이라, 기억하면 전환 때 열린 PR 이 전부 막힌다 |
| SHA 모음 = PR 커밋 목록 + activity API(PR 생성 뒤만) + `--before-sha` | 강제 푸시로 덮인 옛 head 는 PR 커밋 목록에 없고 activity 에만 남는다. 같은 브랜치 이름의 옛 PR 이력은 생성 시각으로 거른다 |
| 현재 head 의 status 이력도 본다(요청은 "현재 head 제외") | 같은 커밋에서 ai-review 를 다시 돌려 지적을 지우면(LLM 은 매번 결과가 다르다) 이력의 failure 가 남아 있어 막는다. 같은 판정에서 재평가될 뿐 정상 흐름은 안 막는다 |
| ai_review 는 심각 지적만이 아니라 대기 아닌 모든 ai_review 사유 | 코드(문장)로 심각 지적만 가를 근거가 없고, 못 봤거나 검사 불능이어도 사람이 봐야 한다 |
| fork head·조회 실패·SHA 50개 초과·activity 100건 이상은 검사 불능 | 원칙 7. 못 읽은 것을 통과로 뭉개지 않는다 |

## 바뀐 것
| 파일 | 내용 |
|---|---|
| `checker/risk_gate.py` | `remembered` 기준, `fetch_history_shas`·`fetch_risk_history`, 결과 `risk_codes`, `check-pr --before-sha`, `build_next` 안내 |
| `.github/workflows/pr-checks.yml`·`pr-review.yml` | failure status description 맨 앞에 사유 코드. pr-checks 는 `event.before` 를 넘김 |
| `checker/tests/test_risk_gate_remember.py`, `checker/tests/conftest.py` | 새 시험 26개. 다른 시험은 이전 기록 조회를 빈 값으로 대체(기본) |
| `plugins/harness/rules/governance.md`, `skills/deliver/SKILL.md`, `checker/README.md`, `docs/guide/harness-guide.html`, `console/whats_new.json` | 문서 |
| `plugins/harness/.claude-plugin/plugin.json` | 0.10.297 → 0.10.300 |

## 권한
caller 변경 없음. 추가로 읽는 것(PR commits·activity·commit statuses)은 caller 가 이미 주는 `contents: read`·`pull-requests: read|write`·`statuses: write` 로 된다.

## 남은 것
- 병합 뒤 길잡이 아티팩트 재게시(`docs/guide/README.md`).
- 실제 public-cloud 에서 첫 failure 에 코드가 붙는지는 이 변경이 `@stable` 로 배포된 뒤 확인.
