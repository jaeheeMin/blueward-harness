# #1074 판 번호·새 소식 충돌을 사람 손 없이 풀기 (2026-11-18)

## 배경
배포되는 파일을 바꾸는 PR 은 모두 plugin.json version 과 `whats_new.json` 을 고쳐, 하나가 병합될 때마다 남은 열린 PR 이 같은 줄에서 충돌했다(#1063·#1068·#1071 이 #1050 병합 뒤 동시에 충돌). "후속 후보"(병합 뒤 Actions 가 판을 매기는 방안)는 이번 범위가 아니다.

## 한 일
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/whats_new.d/<이슈번호>.json`, `console/server.py` | 새 소식 조각 `{"version","lines"}`. 콘솔이 `whats_new.json` 의 판별 줄에 조각을 합쳐 읽는다(같은 판이면 파일 줄 먼저, 조각은 이슈 번호 순). 깨진 조각은 건너뛰고 이름만 `skipped` 로 알린다. `whats_new.json` 의 `_comment` 에 새 방식 설명 |
| `checker/version_rebase.py`, `hooks/run_engine.py` | 판 충돌 자동 해결 엔진(srs_automerge 와 같은 방식, mode=rebase·merge). 새 판 = max(origin/{base} 판, 다른 열린 PR head 판)+1. plugin.json 덩어리를 새 판 줄로 바꾸고 whats_new.json 은 양쪽 블록을 살려 내 블록을 새 판 키 맨 위로, 이 브랜치가 더한 조각의 version 도 바꾼다 |
| `skills/deliver/SKILL.md`, `skills/sync/SKILL.md` | "스스로 해결하지 않는다" 예외에 판 번호 충돌 추가(엔진 호출, merged 면 `rebase --continue`, 상한 20, PR 보고 문구) |
| `CLAUDE.md`, `rules/issue-and-release.md`, `rules/commit-and-pr.md`, `docs/guide/harness-guide.html`(sync·deliver 콜아웃, 요약표), `checker/README.md` | 새 소식은 조각에, 판만 겹친 충돌은 deliver·sync 가 다시 매김 |
| `plugin.json` | 0.10.323 → 0.10.326(열린 PR 이 324·325 사용) |
| 시험 | `checker/tests/test_version_rebase.py`(엔진), `test_web_console.py`(조각 읽기), `test_web_console_risk.py`(version_rebase 는 묻는 모듈) |

## 판단
- 기준 판은 stage 가 아니라 `origin/{base}` 에서 읽는다. 여러 커밋을 리베이스하다 또 충돌해도 같은 새 판이 나오게(stage 로 읽으면 이미 고친 판에서 또 올라간다).
- 열린 PR 의 판을 한 건이라도 못 읽으면 `cannot_check`(원칙 7). 이 브랜치 PR 은 진행 중 리베이스의 head-name 으로 뺀다(못 알아내면 빼지 않는다 — 판이 더 커질 뿐 겹치지는 않는다).
- plugin.json 충돌 파일이 목록에 없으면(whats_new.json 만 충돌) 판 충돌이 아니므로 거절한다.
- 이번 새 소식(`1074.json`)은 deliver·sync 를 쓰는 팀원이 겪는 변화라 한 줄 적었다.

## 남은 것·한계
- 이 브랜치가 더한 조각이 뒤 커밋에서 오고 plugin.json 충돌이 앞 커밋에서만 나면, 조각 version 이 옛 판으로 남을 수 있다(조각은 판 키 없이 콘솔이 version 만 본다). 한 PR 한 커밋 흐름이면 같은 커밋이다.
- 조각 파일은 쌓인다(옛 판은 콘솔이 안 띄운다). 오래된 조각을 `whats_new.json` 으로 접는 정리는 하지 않았다.
- 세션 시작 훅(session-start-sync.sh)의 자동 맞춤은 이 엔진을 부르지 않는다.
