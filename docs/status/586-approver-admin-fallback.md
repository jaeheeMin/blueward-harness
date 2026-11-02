# #586 승인자 파일이 없을 때 엔진도 저장소 관리자만 승인자로 판정 (2026-11-02)

## 배경

승인 규칙: `.github/ssot-approvers` 에 적힌 사람은 관리자 PR 만 승인하고, 그 밖의 PR 은 관리자만 승인한다. 파일이 있으면 엔진·approvals·웹 콘솔이 같은 판정을 냈지만, 파일이 없거나 비면 엔진은 "작성자 아닌 누구나", 웹 콘솔(`flows.json` `whenNoFile: "admin"`)은 "저장소 admin 만" 으로 어긋났다(risk-gate 는 "승인자 없음" 으로 막았다).

## 바꾼 것

- `checker/ssot_approval.py`: `AdminChecker`(`GET repos/{repo}/collaborators/{login}/permission` 의 `permission == "admin"`, 로그인별 캐시, 못 읽거나 응답이 이상하면 `GhError`), `judge_admin_only`(승인 리뷰를 남긴 사람에게만 권한을 묻는다, 작성자 제외), `judge_by_rules` 에 `is_admin` 인자 추가. 파일이 없거나 비면 admin 승인만 인정.
- `checker/risk_gate.py`: `_judge_approval` 이 같은 경로를 쓴다(파일 없음 → admin 판정).
- `checker/pr_queue.py`: `_Context.is_admin`, 응답 키 `anyone` → `admin_only`. `checker/pr_approvals.py`: 내가 승인자인지도 admin 여부로 본다.
- 문구: approvals·scaffold SKILL.md, governance.md, README.md, scaffold.py 도움말, 스캐폴드 `ssot-approvers` 견본 주석, 길잡이(`harness-guide.html`). plugin.json 0.10.151, 길잡이 기준 판 0.10.151.

## 실측: `GET /repos/{o}/{r}/collaborators/{u}/permission` (2026-11-02, 메인 세션이 실제 호출)

| 대상 | 응답 |
|---|---|
| 공개 저장소의 비협업자(octocat) | 200 `read` |
| 비공개 저장소의 비협업자 | 200 `none` |
| 봇(github-actions[bot]) | 200 `none` |
| 소유자 | 200 `admin` |
| 협업자(write) | 200 `write` |
| 존재하지 않는(삭제된) 계정 | 404 `{"message":"<u> is not a user"}` |

## 검토 지적 반영

- `judge_admin_only`: 권한 조회 대상을 "작성자 제외, 리뷰어별 최신 리뷰가 APPROVED 이고 그 승인이 head 커밋 기준인 사람" 으로 좁혔다(`_latest_states` 를 `evaluate_approval` 과 공유). 낡은 승인·이후 CHANGES_REQUESTED 로 바뀐 사람·과거 승인자는 조회하지 않는다. 부작용: 파일이 없을 때는 낡은 승인자가 admin 인지 모르므로 "이전 커밋 기준이라 다시 승인" 안내(`stale_approvers`)가 나가지 않고 "관리자 승인 없음" 으로 답한다. 파일에 내용이 있을 때는 그대로다.
- `AdminChecker`: 404 이면서 메시지에 `is not a user` 가 있으면(없는 계정은 admin 일 수 없다는 확인된 사실) GhError 가 아니라 "admin 아님"(승인 불인정)으로 답하고 캐시한다. 그 밖의 404·403·5xx·네트워크·응답 모양 이상은 GhError(검사 불능). 상태·메시지는 `GhError.status`(stderr 끝 `(HTTP nnn)`)와 메시지 문자열에서 얻는다.
- `pr_approvals.py`: "내가 admin 인가" 는 collaborators API 대신 `gh repo view <repo> --json viewerPermission` 으로 읽는다(호출자에게 push 권한이 없으면 collaborators API 가 403 일 수 있다). 다른 사람의 승인 판정(ssot_approval·risk_gate·pr_queue)은 collaborators API 를 유지한다.
- 웹 콘솔: `gitstate.py` 의 `WHEN_NO_FILE_ANYONE`("작성자 아닌 누구든") 분기를 없앴고, `flows.py` 검증이 `approver` 조건의 `whenNoFile` 이 `"admin"` 이 아니면 오류를 낸다.
- 시험: 404 not-a-user → 승인 불인정, 다른 404·403·500·네트워크 → GhError, 낡은/바뀐 승인자는 조회하지 않음, pr_approvals 의 viewerPermission 경로·빈 값 검사 불능, `whenNoFile` 검증.

## 시험

`test_ssot_approval.py`(파일 없음·빈 파일·admin·비admin·작성자 admin·권한 조회 실패 GhError, AdminChecker), `test_risk_gate.py`, `test_pr_approvals.py`, `test_pr_queue.py`(FakeGh 에 권한 조회), `test_web_console.py`(`whenNoFile == "admin"` 과 엔진 판정 일치).

## 확인 못 한 것

- Actions 토큰으로 collaborators permission 을 읽을 수 있는지는 실제 실행으로 확인하지 못했다. 공식 문서상 이 API 는 Metadata(read)만 요구하고 GITHUB_TOKEN 은 늘 갖는다. 읽지 못하면 검사 불능(종료코드 2)으로 끝난다. 워크플로 permissions 는 바꾸지 않았다.
- 웹 콘솔 `gitstate.py` 는 `viewerPermission` 으로 내 권한만 본다.
- 전체 checker/tests 는 돌리지 않았다.
