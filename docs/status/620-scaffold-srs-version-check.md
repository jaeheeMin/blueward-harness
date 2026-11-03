## 새 저장소 첫 PR 의 SRS 버전 줄 검사 불능과 단독 관리자 승인 안내(#620, 2026-11-03)

시험 저장소(harness-console-sandbox) 첫 PR 에서 doc-guard 판 번호 겹침이 검사 불능이었다. scaffold 의 `docs/ssot/SRS.md` 스텁에 `버전:` 줄이 없었고, 안내는 "GitHub 일시 오류, 다시 돌리십시오" 였다. 또 ssot-approval 은 관리자가 작성자 혼자일 때 다음 할 일을 말하지 않았다.

**정한 것 — 스텁에 줄을 넣는 쪽:** 정본 템플릿 `templates/harness/SRS.md` 가 이미 `버전: 0.1` 머리 줄(첫 판 0.1)을 두고 `version_overlap.srs_version_of` 도 그 줄을 읽는다. 스텁만 어긋나 있었으므로 스텁 `skeleton/docs/ssot/SRS.md` 에 `버전: 0.1` 을 넣었다. 비교 대상에서 빼는 안은 쓰지 않았다(SRS 를 올린 PR 이 판 번호 검사 밖에 놓이는 예외가 생긴다). 이미 만든 저장소는 SKILL.md 에 손으로 한 줄 더하라고 적었다.

**판 번호 겹침:** `fetch_open_prs` 가 SRS 를 읽었는데 `버전:` 줄이 없는 경우 기록에 `srs_error_kind: "no_version_line"` 을 단다(404·API 오류는 그대로 읽기 실패). `version_overlap.check_version_overlap` 은 이 표시가 있으면 `read_failure` 대신 `no_version_line` 검사 불능을 낸다. 통과·위반이 아니라 검사 불능이되, 이 PR 이면 "docs/ssot/SRS.md 머리에 `버전: 0.1` 줄을 넣으십시오, 다시 돌려도 같습니다", 다른 PR 이면 그 PR(#번호) 작성자가 고칠 일이라고 말한다. `render_report` 도 이 경우 "다시 돌려 보십시오" 를 빼고 문서 내용 문제라고 안내한다. 처음에는 `exit2_cause` 가 이 경우를 `config` 로 보내 PR 체크 줄 설명이 "규칙 파일이나 검사 엔진 문제" 로 틀리게 나왔다(검토 지적). 그래서 `exit2_cause` 에 `doc`(이 PR 의 SRS 에 줄 없음)·`doc-other:<번호>`(다른 열린 PR 쪽, 이 PR 탓 아님) 값을 더하고 `pr-checks.yml`·`main-checks.yml` 판정 스텝에 분기를 더했다. 상태는 계속 검사 불능(unknown)이다. 다른 검사 불능이 섞이면 이전처럼 `config`.

**ssot-approval:** 작성자 외 관리자가 있는지는 코드가 알지 못한다(리뷰한 사람만 admin 여부를 묻는다). 그래서 `NO_ADMIN_APPROVAL` 안내에 일반 문구를 더했다: 관리자가 작성자 한 명뿐이면 `.github/ssot-approvers` 에 작성자가 아닌 승인자를 더하거나 다른 관리자를 두라.

**시험:** `checker/tests/test_version_overlap.py`(이 PR·다른 PR 버전 줄 없음, 읽기 실패 구분), `test_ssot_approval.py`(안내 문구). 길잡이 승인 절과 레일 표기(0.10.164)를 고쳤다. Plugin version 0.10.164(열린 PR #629 가 0.10.163 을 써서 한 칸 위로).
