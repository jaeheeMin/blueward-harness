"""내 승인을 기다리는 PR 목록(#391). gh 호출은 test_pr_queue 의 가짜로 바꾼다."""
from __future__ import annotations

import json

from checker import pr_approvals
from checker.pr_approvals import NONE_WAITING, NOT_APPROVER
from checker.pr_queue import EXIT_CANNOT_CHECK, EXIT_OK
from checker.ssot_approval import GhError
from checker.tests.test_pr_queue import NEED_APPROVAL, FakeGh, bad, gate_comment, pr

ME = "boss"


def review(login, commit, state="APPROVED", at="2026-01-01"):
    return {"user": {"login": login}, "state": state, "commit_id": commit, "submitted_at": at}


def waiting(number, author="kim", **kw):
    return pr(number, author=author, checks=[bad("risk-gate / check")], **kw)


def run(prs, argv=(), **kw):
    kw.setdefault("login", ME)
    gh = FakeGh(prs, **kw)
    args = pr_approvals.build_parser().parse_args(["--repo", "o/r", *argv])
    code, text = pr_approvals.run(args, gh)
    return code, text, gh


def test_not_approver_when_login_not_listed():
    code, text, _ = run([waiting(1)], approvers="*: lee\n", comments={1: [gate_comment(NEED_APPROVAL)]})
    assert code == EXIT_OK and NOT_APPROVER in text and NONE_WAITING not in text


def test_no_approvers_file_means_anyone_non_author_can_approve():
    prs = [waiting(1), waiting(2, author=ME)]
    comments = {n: [gate_comment(NEED_APPROVAL)] for n in (1, 2)}
    for approvers in (None, "# 주석뿐\n\n"):
        code, text, _ = run(prs, approvers=approvers, comments=comments)
        assert code == EXIT_OK and NOT_APPROVER not in text
        assert text.splitlines()[0].endswith("작성자 아닌 누구든 승인할 수 있다.")
        assert "[#1]" in text and "[#2]" not in text and "누구든(작성자 제외)" in text


def test_approvers_file_unreadable_is_cannot_check_not_non_approver():
    class Boom(FakeGh):
        def get_json_or_none_404(self, path):
            if ".github/ssot-approvers" in path:
                raise GhError("HTTP 500")
            return super().get_json_or_none_404(path)

    class BadText(FakeGh):
        def get_json_or_none_404(self, path):
            if ".github/ssot-approvers" in path:
                import base64

                return {"content": base64.b64encode(b"\xff\xfe\xfa").decode()}
            return super().get_json_or_none_404(path)

    for cls in (Boom, BadText):
        gh = cls([waiting(1)], login=ME, comments={1: [gate_comment(NEED_APPROVAL)]})
        args = pr_approvals.build_parser().parse_args(["--repo", "o/r"])
        code, text = pr_approvals.run(args, gh)
        assert code == EXIT_CANNOT_CHECK and "승인 대기 PR 확인 불능" in text and NOT_APPROVER not in text


def test_front_pr_means_not_only_me():
    prs = [waiting(5), waiting(2, body="먼저: #5")]
    _, text, _ = run(prs, ["--json"], approvers="*: boss\n", comments={n: [gate_comment(NEED_APPROVAL)] for n in (2, 5)})
    by = {p["number"]: p for p in json.loads(text)["prs"]}
    assert by[5]["only_me"] is True and by[2]["only_me"] is False
    assert "병합 대기" in by[2]["remaining"][0]
    _, text, _ = run(prs, approvers="*: boss\n", comments={n: [gate_comment(NEED_APPROVAL)] for n in (2, 5)})
    row2 = [ln for ln in text.splitlines() if "[#2]" in ln][0]
    assert "내 승인만 남음" not in row2 and "앞 [#5]" in row2 and "병합 대기" in row2


def test_not_yet_pr_with_approval_hint_is_counted_below_table():
    prs = [
        waiting(1),
        pr(2, author="kim", checks=[bad("risk-gate / check"), bad("doc-guard / check")]),
        pr(3, author="kim", files=("docs/ssot/SRS.md",), mergeable="CONFLICTING", mergeStateStatus="DIRTY"),
        pr(4, author="kim", checks=[bad("doc-guard / check")]),
    ]
    comments = {1: [gate_comment(NEED_APPROVAL)], 2: [gate_comment(NEED_APPROVAL)], 4: []}
    code, text, _ = run(prs, approvers="*: boss\n", comments=comments)
    last = [ln for ln in text.splitlines() if "아직 차례가 아닌" in ln]
    assert code == EXIT_OK and len(last) == 1
    assert "2건" in last[0] and "[#2]" in last[0] and "[#3]" in last[0] and "[#4]" not in last[0]


def test_not_yet_count_unreadable_says_cannot_count():
    comments = {1: [gate_comment(NEED_APPROVAL)], 2: GhError("코멘트 실패")}
    prs = [waiting(1), pr(2, author="kim", checks=[bad("doc-guard / check")])]
    _, text, _ = run(prs, approvers="*: boss\n", comments=comments)
    assert "셀 수 없음" in text


def test_unknown_only_counted_for_prs_i_may_approve():
    class Boom(FakeGh):
        def get_all(self, path):
            if "/issues/" in path:
                return super().get_all(path)
            raise GhError("reviews 실패")

    comments = {n: [gate_comment(NEED_APPROVAL)] for n in (1, 2)}
    # 내 PR(#1) 은 승인 여부를 못 읽어도 세지 않는다 → 내 몫 PR 이 없으니 "없음".
    gh = Boom([waiting(1, author=ME)], login=ME, approvers="*: boss lee\n", comments=comments)
    args = pr_approvals.build_parser().parse_args(["--repo", "o/r"])
    code, text = pr_approvals.run(args, gh)
    assert code == EXIT_OK and NONE_WAITING in text
    # 남의 PR(#2) 이면 불능.
    gh = Boom([waiting(2)], login=ME, approvers="*: boss lee\n", comments=comments)
    code, text = pr_approvals.run(args, gh)
    assert code == EXIT_CANNOT_CHECK


def test_pr_appearing_between_reads_is_surfaced():
    class Racy(FakeGh):
        def run(self, args):
            out = super().run(args)
            if args[:2] == ["pr", "list"]:
                self.calls_pr_list = getattr(self, "calls_pr_list", 0) + 1
                if self.calls_pr_list > 1:
                    return json.dumps([])  # 두 번째 읽기엔 보이지 않는다
            return out

    gh = Racy([waiting(1)], login=ME, approvers="*: boss\n", comments={1: [gate_comment(NEED_APPROVAL)]})
    args = pr_approvals.build_parser().parse_args(["--repo", "o/r"])
    code, text = pr_approvals.run(args, gh)
    assert code == EXIT_CANNOT_CHECK and "#1" in text


def test_approver_but_nothing_waiting():
    code, text, _ = run([pr(1, author="kim")], approvers="*: boss\n")
    assert code == EXIT_OK and NONE_WAITING in text and NOT_APPROVER not in text


def test_waiting_pr_listed_with_reason_other_approvers_and_stale():
    reviews = {1: [review("lee", "old"), review(ME, "old")]}
    code, text, _ = run(
        [waiting(1)],
        approvers="*: boss lee\n",
        reviews=reviews,
        comments={1: [gate_comment(NEED_APPROVAL)]},
    )
    assert code == EXIT_OK
    assert "[#1](https://github.com/o/r/pull/1)" in text
    assert "변경이 큼(600줄) 외 1건" in text
    assert "lee" in text and "내 승인이 낡음" in text and "lee 의 승인이 낡음" in text
    assert "내 승인만 남음" in text
    assert "Approve 를 대신 하지 않는다" in text


def test_ordered_by_merge_order_with_front_pr_and_srs_reason():
    prs = [
        pr(2, author="kim", checks=[bad("ssot-approval / check")], body="먼저: #5"),
        waiting(5),
    ]
    code, text, _ = run(prs, approvers="*: boss\n", comments={5: [gate_comment(NEED_APPROVAL)]})
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "#" in ln]
    assert code == EXIT_OK and len(rows) == 2
    assert "#5" in rows[0].split("|")[2] and "#2" in rows[1].split("|")[2]
    assert "SRS 변경" in rows[1]
    assert "앞 [#5](https://github.com/o/r/pull/5) 병합 대기" in rows[1] and "내 승인만 남음" not in rows[1]
    assert "없음(나만)" in rows[0] and "내 승인만 남음" in rows[0]


def test_my_own_pr_and_not_my_author_excluded():
    prs = [waiting(1, author=ME), waiting(2, author="kim"), waiting(3, author="park")]
    approvers = "kim: boss\npark: lee\n"
    comments = {n: [gate_comment(NEED_APPROVAL)] for n in (1, 2, 3)}
    code, text, _ = run(prs, ["--json"], approvers=approvers, comments=comments)
    data = json.loads(text)
    assert code == EXIT_OK and data["status"] == "ok" and data["approver"] is True
    assert [p["number"] for p in data["prs"]] == [2]


def test_already_approved_at_head_not_listed():
    reviews = {1: [review(ME, "sha1")]}
    code, text, _ = run(
        [waiting(1)], approvers="*: boss\n", reviews=reviews, comments={1: [gate_comment(NEED_APPROVAL)]}
    )
    assert code == EXIT_OK and NONE_WAITING in text


def test_read_failure_is_cannot_check():
    code, text, _ = run([waiting(1)], approvers="*: boss\n", fail="네트워크 끊김")
    assert code == EXIT_CANNOT_CHECK and "승인 대기 PR 확인 불능" in text and NONE_WAITING not in text


def test_unreadable_review_is_cannot_check_not_none():
    class Boom(FakeGh):
        def get_all(self, path):
            if "/issues/" in path:
                return super().get_all(path)
            raise GhError("reviews 실패")

    gh = Boom([waiting(1)], login=ME, approvers="*: boss\n", comments={1: [gate_comment(NEED_APPROVAL)]})
    args = pr_approvals.build_parser().parse_args(["--repo", "o/r", "--json"])
    code, text = pr_approvals.run(args, gh)
    assert code == EXIT_CANNOT_CHECK and json.loads(text)["status"] == "cannot_check"


def test_quiet_empty():
    code, text, _ = run([pr(1, author="kim")], ["--quiet-empty"], approvers="*: boss\n")
    assert (code, text) == (EXIT_OK, "")
    code, text, _ = run([pr(1, author="kim")], ["--quiet-empty"], approvers="*: lee\n")
    assert (code, text) == (EXIT_OK, "")
    code, text, _ = run([waiting(1)], ["--quiet-empty"], approvers="*: boss\n", comments={1: [gate_comment(NEED_APPROVAL)]})
    assert code == EXIT_OK and "[#1]" in text


def test_quiet_empty_still_shows_warnings():
    from checker import pr_queue

    pr_queue_limit = pr_queue.PR_LIMIT
    pr_queue.PR_LIMIT = 1  # 열린 PR 이 한도 이상 → 일부만 읽음 경고
    try:
        code, text, _ = run([pr(1, author="kim")], ["--quiet-empty"], approvers="*: boss\n")
    finally:
        pr_queue.PR_LIMIT = pr_queue_limit
    assert code == EXIT_OK and "일부만 읽었다" in text


def test_quiet_empty_still_reports_cannot_check():
    code, text, _ = run([pr(1)], ["--quiet-empty"], fail="x")
    assert code == EXIT_CANNOT_CHECK and text
