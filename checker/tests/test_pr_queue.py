"""열린 PR 상태·병합 순서 계산(#370). gh 호출은 가짜로 바꾼다."""
from __future__ import annotations

import base64
import json

from checker import pr_queue
from checker.pr_queue import (
    CHECK_FAILED,
    CHECKING,
    CONFLICT,
    DRAFT,
    EXIT_CANNOT_CHECK,
    EXIT_OK,
    MERGE_UNKNOWN,
    MERGEABLE,
    BEHIND,
    BLOCKED,
    NOT_STARTED,
    UNSTABLE,
    UNKNOWN,
    WAITING_APPROVAL,
)
from checker.ssot_approval import GhError

PJ = "plugins/harness/.claude-plugin/plugin.json"


def ok(name):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "SUCCESS"}


def bad(name):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "FAILURE"}


def running(name):
    return {"__typename": "CheckRun", "name": name, "status": "IN_PROGRESS", "conclusion": ""}


def pr(number, author="me", base="main", head=None, files=("a.py",), checks=None, **kw):
    raw = {
        "number": number,
        "title": f"제목 {number}",
        "author": {"login": author},
        "baseRefName": base,
        "headRefName": head or f"feat/{number}",
        "headRefOid": f"sha{number}",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [ok("doc-guard / check")] if checks is None else checks,
        "files": [{"path": f} for f in files],
        "body": "",
        "url": f"https://github.com/o/r/pull/{number}",
    }
    raw.update(kw)
    return raw


class FakeGh:
    def __init__(
        self, prs, login="me", approvers=None, human=None, reviews=None, versions=None, fail=None, comments=None
    ):
        self.prs = prs
        self.comments = comments or {}
        self.login = login
        self.approvers = approvers
        self.human = human
        self.reviews = reviews or {}
        self.versions = versions or {}
        self.fail = fail
        self.calls = []

    def run(self, args):
        self.calls.append(args)
        if self.fail:
            raise GhError(self.fail)
        if args[:2] == ["pr", "list"]:
            return json.dumps(self.prs)
        raise AssertionError(args)

    def get_json(self, path):
        self.calls.append([path])
        if path == "user":
            return {"login": self.login}
        raise AssertionError(path)

    def get_all(self, path):
        self.calls.append([path])
        if "/issues/" in path:
            n = int(path.split("/issues/")[1].split("/")[0])
            found = self.comments.get(n, [])
            if isinstance(found, Exception):
                raise found
            return found
        n = int(path.split("/pulls/")[1].split("/")[0])
        return self.reviews.get(n, [])

    def get_json_or_none_404(self, path):
        self.calls.append([path])
        if ".github/ssot-approvers" in path:
            return _content(self.approvers)
        if ".github/human-merge-paths" in path:
            return _content(self.human)
        if PJ in path:
            sha = path.split("ref=")[1]
            v = self.versions.get(sha)
            return _content(json.dumps({"version": v}) if v else None)
        raise AssertionError(path)


def _content(text):
    if text is None:
        return None
    return {"content": base64.b64encode(text.encode("utf-8")).decode()}


def gate_comment(body, login="github-actions[bot]"):
    return {"user": {"login": login}, "body": body}


NEED_APPROVAL = (
    "<!-- risk-gate -->\n## risk-gate\n\n⚠️ 위험도 높음 — 사람의 승인이 필요합니다.\n\n이유:\n"
    "- 변경이 큼(600줄)\n- 보호 경로를 바꿈\n\n승인 상태: 승인이 없다.\n\n다음"
)
OTHER_REASON = "<!-- risk-gate -->\n## risk-gate\n\n⚠️ 위험도 높음 — 다른 사유.\n\n이유:\n- AI 리뷰가 실패함\n\n끝"
UNABLE = "<!-- risk-gate -->\n## risk-gate\n\n⚠️ 위험도 검사 불능 — 이것은 이 PR 의 문제가 아니다.\n\n```\nx\n```"


def by_number(result):
    return {it["number"]: it for it in result["prs"]}


def compute(prs, **kw):
    mine = kw.pop("mine", False)
    gh = FakeGh(prs, **kw)
    return pr_queue.compute(gh, "o/r", gh.login, mine=mine), gh


# --- 상태 ---------------------------------------------------------------------


def test_draft_first_even_with_conflict():
    res, _ = compute([pr(1, isDraft=True, mergeable="CONFLICTING")])
    assert by_number(res)[1]["state"] == DRAFT


def test_conflict():
    res, _ = compute([pr(1, mergeable="CONFLICTING", mergeStateStatus="DIRTY")])
    assert by_number(res)[1]["state"] == CONFLICT


def test_failed_check_named_and_beats_pending():
    res, _ = compute([pr(1, checks=[bad("doc-guard / check"), running("gitleaks / g")])])
    it = by_number(res)[1]
    assert it["state"] == CHECK_FAILED and "doc-guard / check" in it["detail"]


def test_pending_check():
    res, _ = compute([pr(1, checks=[running("doc-guard / check")])])
    assert by_number(res)[1]["state"] == CHECKING


def test_alert_and_gate_do_not_count_as_failed_check():
    # alert 실패는 검사 실패로 세지 않는다. 게이트 실패는 승인 판정으로 간다.
    res, _ = compute([pr(1, checks=[bad("pr-tamper-alert / alert"), ok("doc-guard / check")])], approvers="")
    assert by_number(res)[1]["state"] != CHECK_FAILED


def test_waiting_approval_names_approvers():
    res, gh = compute(
        [pr(1, checks=[bad("risk-gate / check")])],
        approvers="me: boss kim\n",
        comments={1: [gate_comment("<!-- risk-gate -->\n옛 코멘트"), gate_comment(NEED_APPROVAL)]},
    )
    it = by_number(res)[1]
    assert it["state"] == WAITING_APPROVAL
    assert "boss" in it["detail"] and "kim" in it["detail"]
    assert "변경이 큼(600줄) 외 1건" in it["detail"]


def test_waiting_approval_stale_approval_noted():
    reviews = {1: [{"user": {"login": "boss"}, "state": "APPROVED", "commit_id": "old", "submitted_at": "2026-01-01"}]}
    res, _ = compute(
        [pr(1, checks=[bad("ssot-approval / check")])], approvers="*: boss kim\n", reviews=reviews
    )
    it = by_number(res)[1]
    assert it["state"] == WAITING_APPROVAL and "낡은 승인" in it["detail"] and "boss" in it["detail"]


def test_gate_failed_but_approved_is_check_failed():
    reviews = {1: [{"user": {"login": "boss"}, "state": "APPROVED", "commit_id": "sha1", "submitted_at": "2026-01-01"}]}
    res, _ = compute(
        [pr(1, checks=[bad("risk-gate / check")])],
        approvers="*: boss\n",
        reviews=reviews,
        comments={1: [gate_comment(NEED_APPROVAL)]},
    )
    it = by_number(res)[1]
    assert it["state"] == CHECK_FAILED and "risk-gate" in it["detail"]


def test_review_read_failure_is_unknown_not_waiting():
    class Boom(FakeGh):
        def get_all(self, path):
            if "/issues/" in path:
                return super().get_all(path)
            raise GhError("reviews 실패")

    gh = Boom(
        [pr(1, checks=[bad("risk-gate / check")])], approvers="*: boss\n", comments={1: [gate_comment(NEED_APPROVAL)]}
    )
    res = pr_queue.compute(gh, "o/r", "me")
    assert by_number(res)[1]["state"] == UNKNOWN


def test_reviews_read_only_for_gate_failed_prs():
    res, gh = compute(
        [pr(1), pr(2, checks=[bad("risk-gate / check")])],
        approvers="*: boss\n",
        comments={2: [gate_comment(NEED_APPROVAL)]},
    )
    review_calls = [c for c in gh.calls if "/reviews" in c[0]]
    assert len(review_calls) == 1 and "/pulls/2/" in review_calls[0][0]
    comment_calls = [c for c in gh.calls if "/comments" in c[0]]
    assert len(comment_calls) == 1 and "/issues/2/" in comment_calls[0][0]
    approver_calls = [c for c in gh.calls if "ssot-approvers" in c[0]]
    assert len(approver_calls) == 1


def test_risk_gate_other_reason_is_not_waiting_approval():
    res, gh = compute(
        [pr(1, checks=[bad("risk-gate / check")])],
        approvers="*: boss\n",
        comments={1: [gate_comment(OTHER_REASON)]},
    )
    it = by_number(res)[1]
    assert it["state"] == CHECK_FAILED
    assert it["detail"] == "risk-gate: AI 리뷰가 실패함"
    assert not [c for c in gh.calls if "/reviews" in c[0]]


def test_risk_gate_unable_comment_is_not_waiting_approval():
    res, _ = compute([pr(1, checks=[bad("risk-gate / check")])], comments={1: [gate_comment(UNABLE)]})
    it = by_number(res)[1]
    assert it["state"] == CHECK_FAILED and "검사 불능" in it["detail"]


def test_risk_gate_comment_unreadable_or_missing_says_see_comment():
    boom = {1: GhError("코멘트 실패")}
    res, _ = compute([pr(1, checks=[bad("risk-gate / check")])], comments=boom)
    assert by_number(res)[1]["detail"] == "risk-gate 실패(사유는 PR 코멘트)"
    res, _ = compute([pr(1, checks=[bad("risk-gate / check")])])
    assert by_number(res)[1]["state"] == CHECK_FAILED
    assert by_number(res)[1]["detail"] == "risk-gate 실패(사유는 PR 코멘트)"


def test_risk_gate_comment_from_non_bot_is_ignored():
    res, _ = compute(
        [pr(1, checks=[bad("risk-gate / check")])],
        approvers="*: boss\n",
        comments={1: [gate_comment(NEED_APPROVAL, login="someone")]},
    )
    assert by_number(res)[1]["detail"] == "risk-gate 실패(사유는 PR 코멘트)"


def test_no_checks_is_not_started():
    res, _ = compute([pr(1, checks=[])])
    assert by_number(res)[1]["state"] == NOT_STARTED


def test_merge_state_not_clean_is_not_mergeable():
    for merge_state, expected in (("BEHIND", BEHIND), ("BLOCKED", BLOCKED), ("UNSTABLE", UNSTABLE)):
        res, _ = compute([pr(1, mergeStateStatus=merge_state)])
        assert by_number(res)[1]["state"] == expected, merge_state
    res, _ = compute([pr(1, mergeStateStatus="WEIRD")])
    assert by_number(res)[1]["state"] == MERGE_UNKNOWN
    res, _ = compute([pr(1, mergeStateStatus="HAS_HOOKS")])
    assert by_number(res)[1]["state"] == MERGEABLE


def test_mergeable_unknown_is_not_clean():
    res, _ = compute([pr(1, mergeable="UNKNOWN", mergeStateStatus="UNKNOWN")])
    assert by_number(res)[1]["state"] == MERGE_UNKNOWN


def test_mergeable_plain_and_human_merge():
    res, _ = compute([pr(1), pr(2, files=("plugins/x.md",))], human="plugins/\n")
    items = by_number(res)
    assert items[1]["state"] == MERGEABLE and not items[1]["human_merge"]
    assert items[2]["state"] == MERGEABLE and items[2]["human_merge"]
    assert "사람이" in items[2]["detail"]


# --- 순서 ---------------------------------------------------------------------


def order_of(res):
    return [it["number"] for it in res["prs"]]


def test_order_by_base_branch():
    prs = [pr(5, base="feat/9", head="feat/5"), pr(9, head="feat/9")]
    res, _ = compute(prs)
    assert order_of(res) == [9, 5]
    assert by_number(res)[5]["after"] == [9]


def test_order_by_body_first_line():
    prs = [pr(3, body="## 병합 순서\n먼저: #7, #8\n"), pr(7), pr(8)]
    res, _ = compute(prs)
    assert order_of(res) == [7, 8, 3]
    assert by_number(res)[3]["after"] == [7, 8]


def test_first_line_ignores_closed_pr():
    res, _ = compute([pr(3, body="먼저: #99")])
    assert by_number(res)[3]["after"] == []


def test_order_srs_spec_dev_same_dev_number():
    prs = [
        pr(10, files=("src/app.py",), title="feat: 화면 [DEV-004]"),
        pr(11, files=("docs/spec/DEV-004-x.md",), title="docs: 스펙 (DEV-004)"),
        pr(12, files=("docs/ssot/SRS.md",), title="docs: SRS REQ-004 추가"),
    ]
    res, _ = compute(prs)
    assert order_of(res) == [12, 11, 10]
    assert by_number(res)[10]["after"] == [11]  # 12 는 11 을 거쳐 이미 앞선다


def test_different_dev_numbers_not_linked():
    prs = [
        pr(1, files=("docs/ssot/SRS.md",), title="SRS REQ-001"),
        pr(2, files=("src/a.py",), title="feat [DEV-002]"),
    ]
    res, _ = compute(prs)
    assert by_number(res)[2]["after"] == []


def test_order_by_plugin_version():
    prs = [pr(20, files=(PJ,)), pr(21, files=(PJ,)), pr(22, files=(PJ,))]
    res, _ = compute(prs, versions={"sha20": "0.10.9", "sha21": "0.10.17", "sha22": "0.10.8"})
    assert order_of(res) == [22, 20, 21]


def test_plugin_version_read_failure_warns_and_skips():
    prs = [pr(20, files=(PJ,)), pr(21, files=(PJ,))]
    res, _ = compute(prs, versions={"sha21": "0.10.17"})
    assert any("#20" in w for w in res["warnings"])
    assert by_number(res)[21]["after"] == []


def test_tie_broken_by_number_and_unrelated_unordered():
    res, _ = compute([pr(30), pr(4), pr(17)])
    assert order_of(res) == [4, 17, 30]


def test_cycle_marked_and_listed_last():
    prs = [pr(1, body="먼저: #2"), pr(2, body="먼저: #1"), pr(3)]
    res, _ = compute(prs)
    items = by_number(res)
    assert items[3]["order"] == 1
    assert items[1]["order"] is None and "순서 판정 불능(순환)" in items[1]["notes"]
    assert "순서 판정 불능(순환)" in items[2]["notes"]


def test_only_real_cycle_members_are_cyclic_dependents_wait():
    # 1 <-> 2 가 순환이고 3 은 2 뒤에 기다릴 뿐이다. 4 는 무관.
    prs = [pr(1, body="먼저: #2"), pr(2, body="먼저: #1"), pr(3, body="먼저: #2"), pr(4)]
    res, _ = compute(prs)
    items = by_number(res)
    assert items[4]["order"] == 1
    assert pr_queue.CYCLE_NOTE in items[1]["notes"] and pr_queue.CYCLE_NOTE in items[2]["notes"]
    assert pr_queue.CYCLE_NOTE not in items[3]["notes"]
    assert "앞 PR 순서 판정 불능 #2" in items[3]["notes"]
    assert items[3]["order"] is None


def test_topo_order_returns_cycle_and_blocked():
    before = {1: {2}, 2: {1}, 3: {2}, 4: set()}
    ordered, cyclic, blocked = pr_queue.topo_order([1, 2, 3, 4], before)
    assert ordered == [4] and cyclic == [1, 2] and blocked == {3: [2]}


def test_reduce_edges_with_cycle_and_long_chain_terminates():
    chain = {n: {n - 1} for n in range(2, 60)} | {1: set()}
    chain[60] = {59, 1}  # 1 은 59 를 거쳐 이미 앞선다
    assert pr_queue.reduce_edges(chain)[60] == {59}
    cyc = {1: {2}, 2: {1}, 3: {2, 1}}
    reduced = pr_queue.reduce_edges(cyc)
    assert reduced[3] <= {1, 2}


def test_shared_file_warning_only():
    res, _ = compute([pr(1, files=("x.md", "y.md")), pr(2, files=("y.md",))])
    assert res["shared_files"] == [{"first": 1, "second": 2, "files": ["y.md"]}]
    assert by_number(res)[2]["after"] == []


# --- --mine -------------------------------------------------------------------


def test_mine_keeps_my_prs_and_their_predecessors():
    prs = [
        pr(1, author="other"),
        pr(2, author="other"),
        pr(3, author="Me", base="feat/2", head="feat/3"),
        pr(4, author="other", base="feat/1", head="feat/4"),
    ]
    prs[2]["body"] = "먼저: #1"
    res, _ = compute(prs, login="me", mine=True)
    assert set(order_of(res)) == {1, 2, 3}
    assert res["mine_count"] == 1
    assert not by_number(res)[1]["mine"] and by_number(res)[3]["mine"]


def test_mine_filters_shared_file_warnings():
    prs = [pr(1, author="a", files=("x",)), pr(2, author="b", files=("x",)), pr(3, author="me", files=("z",))]
    res, _ = compute(prs, mine=True)
    assert res["shared_files"] == []


def test_mine_quiet_empty_prints_nothing():
    gh = FakeGh([pr(1, author="other")])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--mine", "--quiet-empty"])
    assert pr_queue.run(args, gh) == (EXIT_OK, "")


# --- 읽기 실패·출력 -------------------------------------------------------------


def test_read_failure_is_cannot_check_exit_2():
    gh = FakeGh([], fail="네트워크 실패")
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--all"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_CANNOT_CHECK and "PR 상태 확인 불능" in text and "네트워크 실패" in text


def test_read_failure_json():
    gh = FakeGh([], fail="x")
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--json"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_CANNOT_CHECK and json.loads(text)["status"] == "cannot_check"


def test_unexpected_exception_is_cannot_check_exit_2():
    class Weird(FakeGh):
        def run(self, args):
            raise KeyError("x")

    args = pr_queue.build_parser().parse_args(["--repo", "o/r"])
    code, text = pr_queue.run(args, Weird([]))
    assert code == EXIT_CANNOT_CHECK
    assert text == "PR 상태 확인 불능 — 예상 못 한 오류 KeyError"
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--json"])
    code, text = pr_queue.run(args, Weird([]))
    assert code == EXIT_CANNOT_CHECK and json.loads(text)["status"] == "cannot_check"


def test_render_max_rows_cuts_and_counts_the_rest():
    gh = FakeGh([pr(n) for n in range(1, 16)])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--max-rows", "10"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_OK
    assert text.count("\n| ") == 10 + 1  # 머리글 + PR 10줄
    assert "#10 " in text and "#11 " not in text
    assert "외 5개 — /harness:prs" in text
    full = pr_queue.render(pr_queue.compute(gh, "o/r"), False)
    assert "외 " not in full and "#15 " in full


def test_truncated_marked_when_limit_reached():
    prs = [pr(n) for n in range(1, pr_queue.PR_LIMIT + 1)]
    res, _ = compute(prs)
    assert res["truncated"] is True
    assert "일부만 읽었다" in pr_queue.render(res, False)


def test_render_table_and_json_roundtrip():
    gh = FakeGh([pr(1), pr(2, mergeable="CONFLICTING")])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_OK and "| 순서 | PR | 상태 |" in text and "충돌" in text
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--json"])
    code, text = pr_queue.run(args, gh)
    assert json.loads(text)["prs"][0]["number"] == 1
