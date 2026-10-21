# #391 내 승인을 기다리는 PR 을 보여 주는 스킬 `/harness:approvals` (2026-10-20)

승인자가 남의 PR 에 Approve 를 달아야 순서가 풀리는데, 어떤 PR 이 내 승인을 기다리는지는 GitHub 에서 하나씩 열어 봐야 했다. 부를 때만 보이는 스킬로 둔다(세션 시작·`/harness:prs` 출력은 그대로). 0.10.97.

## 한 것

- `checker/pr_approvals.py`(새 모듈, `pr_queue.py` 는 건드리지 않음): `pr_queue.compute` 의 상태·병합 순서·`after` 를 그대로 쓰고, "승인 대기" 인 PR 에서 내 승인이 필요한 것만 고른다. 조건: 작성자가 내가 아님, `.github/ssot-approvers` 가 그 작성자에게 정한 승인자에 내가 있음(`approvers_for`), `pr_queue._approval_state` 가 아직 미승인(낡은 승인 포함). 사유는 risk-gate 봇 코멘트(`_risk_gate_view`)와 ssot-approval 실패(SRS 변경).
- 표: 순서 · PR 링크+제목 · 왜 승인이 필요한가 · 다른 승인자 · 남은 것(내 승인만 남음, 아니면 뒤처짐·앞 PR 병합 대기·사람이 병합) · 낡은 승인. 앞 PR 이 있으면 "내 승인만 남음" 이라 쓰지 않는다.
- 승인자 파일 해석은 `judge_by_rules` 와 같다: 파일이 없거나 비면 작성자 아닌 누구든 승인할 수 있어 나도 승인자(머리 줄로 알림). "승인자 아님" 은 내용이 있는데 내 이름이 어느 작성자 줄에도 없을 때만. 승인자 파일은 `pr_queue` 의 읽기(해석 실패를 "내용 없음" 으로 삼킴)를 쓰지 않고 엄격하게 읽는다 — 404 가 아닌 오류·디코딩 실패는 확인 불능.
- 결과 구분(원칙 7): 승인자 아님 / "승인 대기 상태인 PR 중에는 내 승인을 기다리는 PR 없음" / 읽기 실패 "승인 대기 PR 확인 불능"(종료코드 2). 승인 여부를 못 읽은 PR(UNKNOWN, 내 PR·내 몫 아닌 작성자 PR 은 뺀 뒤 센다)이나 두 번 읽는 사이 생겨 확인 못 한 PR 이 있고 목록이 비면 "없음" 대신 불능. `--json`(`status`·`approver`·`anyone`·`prs[]`·`not_yet`·`unknown`·`unchecked`), `--quiet-empty`(경고·아직 차례 아닌 PR 이 있으면 조용히 끝내지 않는다).
- 표 아래 "내 승인도 필요하지만 검사 중·실패·충돌이라 아직 차례가 아닌 PR n건" 줄: 상태가 검사 중·검사 실패·충돌·검사 시작 전이고 risk-gate 봇이 "승인 필요" 사유를 냈거나 `docs/ssot/` 를 바꾼 PR 을 센다. 코멘트를 못 읽으면 "셀 수 없음".
- 스킬 `plugins/harness/skills/approvals/SKILL.md`: 엔진을 `engine_spec.py` + `uvx --from` 으로 부르고 출력을 그대로 보여 준다. Approve 는 사람이 GitHub 에서 하고 스킬이 대신 하지 않는다.
- CLAUDE.md 스킬 표, 길잡이 "내 PR 확인하기" 탭(callout 한 개), 시험 `checker/tests/test_pr_approvals.py`.

## 한계

- 승인자 목록은 `pr_queue` 와 같이 기준 브랜치의 `.github/ssot-approvers` 만 읽는다. `risk-gate.yaml` 의 `approvers_file` 을 다른 경로로 바꾼 저장소는 반영하지 않는다.
- 승인 대기가 아닌 상태(검사 중·실패 등)의 PR 은 표에 싣지 않고 위 한 줄로 센다. 위험 경로(risk-gate 설정)는 이 단계에서 직접 판정하지 않고 봇 코멘트와 SRS 변경만 본다 — 완전한 판정은 #396 뒤로 미룬다.
- `pr_queue.compute` 와 `_load_prs` 가 `gh pr list` 를 두 번 부른다(한 번으로 줄이는 건 #396 뒤).
- 새 판이 병합돼 태그가 붙기 전에는 스킬이 받는 엔진에 이 모듈이 없다.
