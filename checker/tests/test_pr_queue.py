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


def _at(entry, started, workflow="ai-review"):
    return {**entry, "startedAt": started, "workflowName": workflow}


def test_cancelled_then_passed_rerun_counts_latest_only():
    # #375: public-cloud #248 처럼 앞 실행이 취소되고 다시 돈 실행이 통과하면 통과다.
    cancelled = {**bad("ai-review / review"), "conclusion": "CANCELLED"}
    checks = [_at(cancelled, "2026-10-19T01:02:51Z"), _at(ok("ai-review / review"), "2026-10-19T01:03:32Z")]
    res, _ = compute([pr(1, checks=checks)])
    assert by_number(res)[1]["state"] != CHECK_FAILED


def test_passed_then_failed_rerun_is_failed():
    checks = [_at(ok("doc-guard / check"), "2026-10-19T01:00:00Z"), _at(bad("doc-guard / check"), "2026-10-19T02:00:00Z")]
    res, _ = compute([pr(1, checks=checks)])
    assert by_number(res)[1]["state"] == CHECK_FAILED


def test_rerun_without_times_stays_conservative():
    # 어느 것이 최신인지 모르면 줄이지 않는다 — 실패를 통과로 바꾸지 않는다.
    cancelled = {**bad("ai-review / review"), "conclusion": "CANCELLED"}
    res, _ = compute([pr(1, checks=[cancelled, ok("ai-review / review")])])
    assert by_number(res)[1]["state"] == CHECK_FAILED


def test_same_name_in_different_workflows_both_count():
    checks = [_at(bad("check"), "2026-10-19T01:00:00Z", "doc-guard"), _at(ok("check"), "2026-10-19T02:00:00Z", "other")]
    res, _ = compute([pr(1, checks=checks)])
    assert by_number(res)[1]["state"] == CHECK_FAILED


def test_alert_and_gate_do_not_count_as_failed_check():
    # alert 실패는 검사 실패로 세지 않는다. 게이트 실패는 승인 판정으로 간다.
    res, _ = compute([pr(1, checks=[bad("pr-tamper-alert / alert"), ok("doc-guard / check")])], approvers="")
    assert by_number(res)[1]["state"] != CHECK_FAILED


def status_ctx(context, state):
    return {"__typename": "StatusContext", "context": context, "state": state}


def test_merge_order_status_and_pr_queue_job_do_not_count():
    # 앞 PR 이 있어 merge-order 가 FAILURE 이면 GitHub 는 UNSTABLE 이라 하는데, 그것은 검사 불안정이 아니다.
    checks = [ok("doc-guard / check"), status_ctx("merge-order", "FAILURE"), bad("pr-queue / queue")]
    res, _ = compute([pr(1, checks=checks, mergeStateStatus="UNSTABLE")])
    assert by_number(res)[1]["state"] == MERGEABLE


def test_merge_order_pending_unstable_is_mergeable_not_checks_running():
    # 앞 PR 대기(#401)는 pending 이고 GitHub 는 이것도 UNSTABLE 로 본다. 검사 진행 중이 아니다.
    checks = [ok("doc-guard / check"), status_ctx("merge-order", "PENDING")]
    res, _ = compute([pr(1, checks=checks, mergeStateStatus="UNSTABLE")])
    assert by_number(res)[1]["state"] == MERGEABLE


def test_merge_order_alone_is_not_a_started_check():
    res, _ = compute([pr(1, checks=[status_ctx("merge-order", "SUCCESS")])])
    assert by_number(res)[1]["state"] == NOT_STARTED


def test_unstable_without_merge_order_failure_stays_unstable():
    res, _ = compute([pr(1, checks=[ok("doc-guard / check"), status_ctx("merge-order", "SUCCESS")], mergeStateStatus="UNSTABLE")])
    assert by_number(res)[1]["state"] == UNSTABLE


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


def test_render_max_rows_cuts_chains_and_counts_the_rest():
    # 줄기 5개(PR 2개씩) + 혼자 1개. --max-rows 3 이면 줄기 3줄만 싣고 "외 2개 줄기".
    prs = []
    for k in range(5):
        a, b = 10 * k + 1, 10 * k + 2
        prs += [pr(a), pr(b, body=f"먼저: #{a}")]
    prs.append(pr(99))
    gh = FakeGh(prs)
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--max-rows", "3"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_OK
    assert "[#22](" in text and "[#32](" not in text
    assert "… 외 2개 줄기 — /harness:prs" in text
    assert "[#99](https://github.com/o/r/pull/99)" in text  # 혼자인 PR 줄은 줄기 수 제한과 무관
    full = pr_queue.render(pr_queue.compute(gh, "o/r"), False)
    assert "개 줄기" not in full and "[#42](https://github.com/o/r/pull/42)" in full


def test_truncated_marked_when_limit_reached():
    prs = [pr(n) for n in range(1, pr_queue.PR_LIMIT + 1)]
    res, _ = compute(prs)
    assert res["truncated"] is True
    assert "일부만 읽었다" in pr_queue.render(res, False)


def test_render_all_json_roundtrip():
    gh = FakeGh([pr(1), pr(2, mergeable="CONFLICTING")])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--all"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_OK and "| 줄기 | 순서 |" in text and "줄기 없음" in text
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--json"])
    code, text = pr_queue.run(args, gh)
    assert json.loads(text)["prs"][0]["number"] == 1


# --- 사람용 출력: 할 일 표 + 줄기 표(#390) -------------------------------------------


def link(n):
    return f"[#{n}](https://github.com/o/r/pull/{n})"


def run_text(prs, *argv, login="me", **kw):
    gh = FakeGh(prs, login=login, **kw)
    code, text = pr_queue.run(pr_queue.build_parser().parse_args(["--repo", "o/r", *argv]), gh)
    assert code == EXIT_OK
    return text


def todo_rows(text):
    """'## 내가 지금 할 수 있는 일' 표의 (할 일, PR 칸) 목록."""
    rows, on = [], False
    for ln in text.splitlines():
        if ln.startswith("## "):
            on = ln == "## 내가 지금 할 수 있는 일"
        elif on and ln.startswith("| ") and not ln.startswith(("| 할 일", "|---")):
            kind, cell = ln.strip("| ").split(" | ", 1)
            rows.append((kind, cell))
    return rows


def chain_rows(text):
    """줄기 표의 (줄기 이름, 순서 칸) 목록."""
    rows, on = [], False
    for ln in text.splitlines():
        if ln.startswith("## "):
            on = ln.startswith(("## 내 PR 과", "## 열린 PR 과"))
        elif on and ln.startswith("| ") and not ln.startswith(("| 줄기 | 순서", "|---")):
            name, cell = ln.strip("| ").split(" | ", 1)
            rows.append((name, cell.rstrip(" |")))
    return rows


def test_todo_three_kinds_and_their_boundaries():
    prs = [
        pr(1),  # 병합 가능, 앞 없음 -> 병합하기
        pr(2, files=("plugins/x.md",)),  # 사람이 병합 -> 병합하기 + 그 말
        pr(3, checks=[bad("ai-review / review")]),  # 검사 실패 -> 고치기
        pr(4, mergeable="CONFLICTING", mergeStateStatus="DIRTY"),  # 충돌 -> 고치기
        pr(5, checks=[running("doc-guard / check")]),  # 검사 중 -> 기다리기
        pr(6, isDraft=True),  # 초안 -> 기다리기
        pr(7, body="먼저: #1"),  # 병합 가능이지만 앞 PR -> 기다리기
        pr(8, body="먼저: #9"),
        pr(9, body="먼저: #8"),  # 순환 -> 고치기
        pr(10, checks=[bad("risk-gate / check")]),  # 승인 대기 -> 기다리기
    ]
    text = run_text(
        prs,
        "--mine",
        human="plugins/\n",
        approvers="*: blueward-huiseong csh-dot123\n",
        comments={10: [gate_comment(NEED_APPROVAL)]},
    )
    rows = {int(c.split("](")[0][2:]): (k, c) for k, c in todo_rows(text)}
    assert rows[1][0] == "병합하기" and " — " not in rows[1][1]
    assert rows[2][0] == "병합하기" and rows[2][1].endswith("— 사람이 GitHub 에서 병합")
    assert rows[3][0] == "고치기" and "— 검사 실패: ai-review / review" in rows[3][1]
    assert rows[4][0] == "고치기" and "— 충돌" in rows[4][1]
    assert rows[5] == ("기다리기", f"{link(5)} 제목 5 — 검사 중")
    assert rows[6][0] == "기다리기" and rows[6][1].endswith("— 초안")
    assert rows[7][0] == "기다리기" and f"앞 {link(1)} 대기" in rows[7][1]
    assert rows[8][0] == "고치기" and "순환" in rows[8][1] and rows[9][0] == "고치기"
    assert rows[10][0] == "기다리기" and rows[10][1].endswith("— blueward-huiseong·csh-dot123 승인")
    kinds = [k for k, _ in todo_rows(text)]
    assert kinds == sorted(kinds, key=["병합하기", "고치기", "기다리기"].index)
    # 긴 승인 사유는 표에 없다(--verbose 에만).
    assert "변경이 큼" not in text


def test_todo_none_actionable_says_all_waiting():
    text = run_text([pr(1, checks=[running("doc-guard / check")])], "--mine")
    assert "지금 할 수 있는 일: 없음(모두 기다리는 중)" in text
    assert todo_rows(text)[0][0] == "기다리기"
    text = run_text([pr(1)], "--mine")
    assert "없음(모두 기다리는 중)" not in text


def test_symbols_map_from_existing_states():
    cases = {
        MERGEABLE: pr(1),
        WAITING_APPROVAL: pr(2, checks=[bad("ssot-approval / check")]),
        CHECKING: pr(3, checks=[running("doc-guard / check")]),
        NOT_STARTED: pr(4, checks=[]),
        MERGE_UNKNOWN: pr(5, mergeable="UNKNOWN", mergeStateStatus="UNKNOWN"),
        CHECK_FAILED: pr(6, checks=[bad("doc-guard / check")]),
        CONFLICT: pr(7, mergeable="CONFLICTING", mergeStateStatus="DIRTY"),
        BEHIND: pr(8, mergeStateStatus="BEHIND"),
        DRAFT: pr(9, isDraft=True),
        BLOCKED: pr(10, mergeStateStatus="BLOCKED"),
        UNSTABLE: pr(11, mergeStateStatus="UNSTABLE"),
    }
    expect = {MERGEABLE: "✅", WAITING_APPROVAL: "⏳", CHECKING: "⏳", NOT_STARTED: "⏳", MERGE_UNKNOWN: "⏳",
              CHECK_FAILED: "❌", CONFLICT: "❌", BEHIND: "❌", DRAFT: "📝", BLOCKED: "❓", UNSTABLE: "❓"}
    text = run_text(list(cases.values()), "--mine", approvers="*: boss\n")
    (_, cell), = [r for r in chain_rows(text) if r[0] == "줄기 없음"]
    got = {}
    for part in cell.split(" · "):
        n = int(part.split("](")[0].lstrip("*[#"))
        got[n] = part.rsplit(" ", 1)[1]
    for state, raw in cases.items():
        assert got[raw["number"]] == expect[state], state
    # 순환은 상태와 상관없이 ❓
    text = run_text([pr(1, body="먼저: #2"), pr(2, body="먼저: #1")], "--mine")
    assert "❓" in chain_rows(text)[0][1] and "✅" not in chain_rows(text)[0][1]
    # UNKNOWN(승인 여부를 못 읽음)도 ❓
    assert pr_queue.SYMBOLS[UNKNOWN] == "❓"


def test_chain_of_seven_in_one_row_with_names_and_bold():
    prs = [pr(244, title="docs: SRS REQ-007 반복제조 자재출고 추가", files=("docs/ssot/SRS.md",), author="x")]
    prev = 244
    for n in (248, 252, 260, 261, 270, 271):
        prs.append(pr(n, body=f"먼저: #{prev}", title=f"feat: 개발 DEV-007 {n}", author="me" if n == 252 else "x"))
        prev = n
    text = run_text(prs, "--mine")
    (name, cell), = chain_rows(text)
    assert name == "DEV-007(반복제조 자재출고 추가)"
    assert cell == " → ".join(
        (f"**{link(n)}**" if n == 252 else link(n)) + " ✅" for n in (244, 248, 252, 260, 261, 270, 271)
    )


def test_chain_fork_groups_branches_and_loner_row():
    prs = [
        pr(1, title="기반 작업"),
        pr(2, body="먼저: #1"),
        pr(3, body="먼저: #1"),
        pr(4, body="먼저: #2, #3"),
        pr(20),
        pr(21),
    ]
    text = run_text(prs, "--all")
    rows = chain_rows(text)
    assert rows[0] == ("기반 작업", f"{link(1)} ✅ → ({link(2)} ✅, {link(3)} ✅) → {link(4)} ✅")
    assert rows[-1] == ("줄기 없음", f"{link(20)} ✅ · {link(21)} ✅")
    assert len(rows) == 2
    assert "할 수 있는 일" not in text  # --all 은 할 일 표가 없다
    assert "**" not in text  # --all 은 누가 내 것인지 모른다


def test_chain_name_without_dev_uses_first_title_clipped():
    long_title = "가" * 40
    text = run_text([pr(1, title=long_title), pr(2, body="먼저: #1")], "--mine")
    assert chain_rows(text)[0][0] == "가" * 27 + "…"


def names_of(*titles):
    """같은 DEV 번호(제목에 든 번호)의 PR 둘 이상으로 줄기를 만들어 그 이름을 본다."""
    prs = [pr(n, title=t) for n, t in enumerate(titles, 1)]
    return [name for name, _ in chain_rows(run_text(prs, "--all"))]


def test_chain_name_rules():
    # ① 제목 끝이 (DEV-xxx) 인 PR: 접두어와 (DEV-xxx) 를 뗀다.
    assert names_of("feat: 판매문서 일괄 취소 요청 BO 골격 추가 (DEV-004)", "docs: x DEV-004") == [
        "DEV-004(판매문서 일괄 취소 요청 BO 골격 추가)"
    ]
    # 24자를 넘으면 자른다.
    assert names_of("fix: " + "가" * 30 + " [DEV-004]", "DEV-004 b") == ["DEV-004(" + "가" * 23 + "…)"]
    # ② 끝 표기가 없으면 DEV-xxx 뒤 문구를 ` Spec`·` SRS`·`·`·` 에 ` 앞에서 자른다.
    assert names_of("docs: DEV-009 생산오더 실적 엑셀 업로드 Spec 최종", "feat: DEV-009 b") == [
        "DEV-009(생산오더 실적 엑셀 업로드)"
    ]
    assert names_of("docs: DEV-009 입고·출고 정리", "x DEV-009") == ["DEV-009(입고)"]
    assert names_of("docs: DEV-009 자재 SRS 에 추가", "x DEV-009") == ["DEV-009(자재)"]
    # ③ 문구가 비면 번호만.
    assert names_of("DEV-003", "[DEV-003]") == ["DEV-003"]


def test_dev_number_of_a_pr_with_two_numbers_or_only_in_branch():
    assert pr_queue._dev_of({"title": "REQ-004 와 (DEV-005)", "head": "feat/x"}) == 5  # 제목 끝
    assert pr_queue._dev_of({"title": "DEV-006 에서 DEV-007 로", "head": ""}) == 6  # 맨 앞
    assert pr_queue._dev_of({"title": "x", "head": "feat/DEV-009-a"}) == 9  # 브랜치
    assert pr_queue._dev_of({"title": "x", "head": "feat/x"}) is None


def test_two_devs_linked_by_first_line_stay_two_rows_with_tail():
    prs = [
        pr(1, title="a (DEV-007)"),
        pr(2, title="b (DEV-007)", body="먼저: #1"),
        pr(4, title="c (DEV-009)"),
        pr(5, title="d (DEV-009)", body="먼저: #4, #1"),  # DEV-007 의 #1 이 앞
    ]
    rows = chain_rows(run_text(prs, "--all"))
    assert rows == [
        ("DEV-007(a)", f"{link(1)} ✅ → {link(2)} ✅"),
        ("DEV-009(c)", f"{link(4)} ✅ → {link(5)} ✅(앞: {link(1)})"),
    ]


def test_unnumbered_prs_touching_one_dev_group_join_it_transitively():
    prs = [
        pr(1, title="a (DEV-007)"),
        pr(2, title="번호 없음", body="먼저: #1"),
        pr(3, title="번호 없음 둘", body="먼저: #2"),  # #1 과 직접 이어지지 않아도 같은 묶음이라 합류
        pr(10, title="자기들끼리"),
        pr(11, title="자기들끼리 뒤", body="먼저: #10"),
    ]
    rows = chain_rows(run_text(prs, "--all"))
    assert rows == [
        ("DEV-007(a)", f"{link(1)} ✅ → {link(2)} ✅ → {link(3)} ✅"),
        ("자기들끼리", f"{link(10)} ✅ → {link(11)} ✅"),
    ]


def test_unnumbered_pr_touching_two_dev_groups_goes_to_no_chain_with_tail():
    prs = [
        pr(1, title="a (DEV-007)"),
        pr(2, title="b (DEV-008)"),
        pr(3, title="둘 다 뒤", body="먼저: #1, #2"),
    ]
    rows = chain_rows(run_text(prs, "--all"))
    assert rows == [("줄기 없음", f"{link(1)} ✅ · {link(2)} ✅ · {link(3)} ✅(앞: {link(1)}, {link(2)})")]


def test_chain_name_boundaries_period_two_numbers_and_spec_lead():
    # 제목 끝 (DEV-004) 뒤의 마침표.
    assert names_of("feat: 판매문서 취소 (DEV-004).", "x DEV-004") == ["DEV-004(판매문서 취소)"]
    # (DEV-004, DEV-005): 앞의 번호가 줄기 번호이고 괄호는 이름에서 빠진다.
    assert pr_queue._primary_dev({"title": "a (DEV-004, DEV-005)", "headRefName": ""}) == 4
    assert names_of("feat: 두 번호 (DEV-004, DEV-005)", "x (DEV-004)") == ["DEV-004(두 번호)"]
    # `DEV-004 Spec 에 …` 로 시작하는 제목은 이름으로 쓰지 않고 다음 PR 의 제목을 쓴다(①).
    assert names_of("docs: DEV-004 Spec 에 반영 (DEV-004)", "feat: 취소 요청 추가 (DEV-004)") == ["DEV-004(취소 요청 추가)"]
    # ② 도 Spec 으로 시작하면 버리고 ③ 첫 PR 제목으로 간다(`(Spec)` 이 이름이 되지 않는다).
    assert names_of("docs: DEV-004 Spec 에 반영", "x DEV-004") == ["DEV-004(Spec 에 반영)"]
    # ② 앞머리의 `.` 는 떼고 이름으로 삼지 않는다.
    assert names_of("docs: DEV-004. 결과 반영", "x DEV-004") == ["DEV-004(결과 반영)"]


def test_req_number_groups_like_dev_and_shows_as_dev():
    assert names_of("docs: 자재출고 요구 추가 (REQ-004)", "feat: x (DEV-004)") == ["DEV-004(자재출고 요구 추가)"]


def test_notes_show_warning_mark_and_line_without_verbose():
    class NoHumanPaths(FakeGh):
        def get_json_or_none_404(self, path):
            if ".github/human-merge-paths" in path:
                raise GhError("권한 없음")
            return super().get_json_or_none_404(path)

    prs = [
        pr(1, title="a (DEV-007)", author="other"),
        pr(2, title="b (DEV-007)", body="먼저: #1", author="me"),
    ]
    for argv in (["--all"], ["--mine"]):
        gh = NoHumanPaths(prs, login="me")
        code, text = pr_queue.run(pr_queue.build_parser().parse_args(["--repo", "o/r", *argv]), gh)
        assert code == EXIT_OK
        lines = text.splitlines()
        assert f"{link(1)} ✅⚠" in text, argv  # 남의 PR 도
        want = f"주의: {link(1)} 사람이 병합할 경로인지 확인 불능(권한 없음)"
        assert want in lines, argv
        row = max(i for i, ln in enumerate(lines) if ln.startswith("| DEV-007"))
        assert lines[row + 1].startswith("주의: ") and lines[row + 2].startswith("주의: ")  # 표 바로 아래
        assert any("⚠ 주의 있음(아래 줄)" in ln for ln in lines)
    # 주의가 없으면 ⚠ 도 주의 줄도 없다.
    text = run_text(prs, "--all")
    assert "⚠ 주의 있음" in text and "✅⚠" not in text and "\n주의:" not in text


def test_dev_number_from_body_or_spec_file_groups_prs():
    prs = [
        pr(244, title="docs: SRS 반영", body="진행 원장: DEV-007"),
        pr(248, title="docs: 스펙 작성", files=("docs/spec/DEV-007-x.md",), body="먼저: #244"),
        pr(252, title="feat: 반복제조 자재출고 업로드", body="DEV-007 하위 작업\n먼저: #248"),
        pr(260, title="무관", body="DEV-006 결함"),
    ]
    res, _ = compute(prs)
    assert by_number(res)[248]["devs"] == [7] and by_number(res)[260]["devs"] == [6]
    rows = chain_rows(run_text(prs, "--all"))
    assert rows == [
        ("DEV-007(SRS 반영)", f"{link(244)} ✅ → {link(248)} ✅ → {link(252)} ✅"),
        ("줄기 없음", f"{link(260)} ✅"),
    ]


def test_primary_dev_priority_title_branch_spec_file_then_first_body_mention():
    raw = {"title": "x", "headRefName": "feat/x", "files": [], "body": ""}
    assert pr_queue._primary_dev({**raw, "title": "x (DEV-005)", "body": "DEV-003"}) == 5
    assert pr_queue._primary_dev({**raw, "headRefName": "feat/DEV-009-a", "body": "DEV-003"}) == 9
    # 결함 PR 이 "DEV-006 과 같은 결함" 이라 적어도, 바꾼 Spec 이 DEV-007 이면 7.
    spec7 = [{"path": "docs/spec/DEV-007-x.md"}, {"path": "docs/manual/DEV-006-m.md"}]
    assert pr_queue._primary_dev({**raw, "files": spec7, "body": "DEV-006 과 DEV-007"}) == 7
    assert pr_queue._primary_dev({**raw, "body": "DEV-006(앱)에 DEV-007 과 같은 결함"}) == 6
    assert pr_queue._primary_dev(raw) is None


def test_dev_of_prefers_title_and_branch_then_smallest_body_number():
    assert pr_queue._dev_of({"title": "x (DEV-005)", "head": "", "devs": [3, 5]}) == 5
    assert pr_queue._dev_of({"title": "x", "head": "feat/DEV-009-a", "devs": [3, 9]}) == 9
    assert pr_queue._dev_of({"title": "x", "head": "feat/x", "devs": [7, 4]}) == 4
    assert pr_queue._dev_of({"title": "x", "head": "feat/x", "devs": []}) is None


def test_chain_name_falls_back_to_first_pr_title():
    prs = [
        pr(1, title="feat: 첫 작업 제목", body="DEV-007"),
        pr(2, title="fix: 둘째", body="DEV-007\n먼저: #1"),
    ]
    assert [n for n, _ in chain_rows(run_text(prs, "--all"))] == ["DEV-007(첫 작업 제목)"]


def test_mine_with_no_prs_says_so_not_just_no_open_prs():
    text = run_text([pr(1, author="other")], "--mine")
    assert text.splitlines() == ["o/r 내 PR 0개", "내 열린 PR 이 없다."]


def test_mine_shows_only_chains_with_my_pr_but_whole_chain():
    prs = [
        pr(1, author="a"),
        pr(2, author="me", body="먼저: #1"),
        pr(3, author="b", body="먼저: #2"),  # 내 뒤에 올 남의 PR 도 줄기 안이라 보인다
        pr(10, author="a"),
        pr(11, author="b", body="먼저: #10"),  # 내 PR 이 없는 줄기
        pr(30, author="a"),  # 남의 혼자 PR
        pr(31, author="me"),
    ]
    text = run_text(prs, "--mine")
    rows = chain_rows(text)
    assert [n for n, _ in rows] == ["제목 1", "줄기 없음"]
    assert rows[0][1] == f"{link(1)} ✅ → **{link(2)}** ✅ → {link(3)} ✅"
    assert rows[1][1] == f"**{link(31)}** ✅"
    assert "[#10]" not in text and "[#30]" not in text
    assert [k for k, _ in todo_rows(text)] == ["병합하기", "기다리기"]  # 내 PR 2(앞 1 대기)·31 만, 남의 PR 은 할 일 표에 없다
    assert text.splitlines()[0] == "o/r 내 PR 2개"


def test_all_lists_whole_repo_chains_loners_last():
    prs = [pr(30), pr(1), pr(2, body="먼저: #1"), pr(10), pr(11, body="먼저: #10")]
    rows = chain_rows(run_text(prs, "--all"))
    assert [n for n, _ in rows] == ["제목 1", "제목 10", "줄기 없음"]
    assert rows[-1][1] == f"{link(30)} ✅"


def test_verbose_adds_reasons_and_shared_file_warning_only_then():
    prs = [pr(1, files=("y.md",), checks=[bad("risk-gate / check")]), pr(2, files=("y.md",), author="me")]
    kw = dict(approvers="*: boss\n", comments={1: [gate_comment(NEED_APPROVAL)]})
    plain = run_text(prs, "--mine", **kw)
    assert "변경이 큼" not in plain and "같은 파일" not in plain and "자세히" not in plain
    verbose = run_text(prs, "--mine", "--verbose", **kw)
    assert "## 자세히(--verbose)" in verbose and "| 순서 | PR | 상태 | 다음 할 일 | 먼저 병합할 PR |" in verbose
    assert "변경이 큼(600줄) 외 1건" in verbose and "같은 파일: y.md" in verbose


def test_warnings_and_truncation_stay_without_verbose():
    res = {"status": "ok", "repo": "o/r", "login": None, "truncated": True, "prs": [], "shared_files": [],
           "warnings": ["w1"], "unread_versions": []}
    assert pr_queue.render(res, False) == "o/r 열린 PR 0개\n열린 PR 이 없다."
    text = run_text([pr(n) for n in range(1, pr_queue.PR_LIMIT + 1)], "--all")
    assert "일부만 읽었다" in text
    prs = [pr(20, files=(PJ,)), pr(21, files=(PJ,))]
    assert "#20 의 plugin.json version 을 읽지 못해" in run_text(prs, "--all", versions={"sha21": "0.10.17"})


def test_json_and_pr_outputs_unchanged_by_render_change():
    prs = [pr(1, author="other"), pr(2, author="me", body="먼저: #1"), pr(3, author="other", body="먼저: #2")]
    gh = FakeGh(prs)
    parse = pr_queue.build_parser().parse_args
    _, js = pr_queue.run(parse(["--repo", "o/r", "--mine", "--json"]), gh)
    expected = pr_queue.compute(gh, "o/r", "me", mine=True)
    assert json.loads(js) == json.loads(json.dumps(expected))
    assert [it["number"] for it in json.loads(js)["prs"]] == [1, 2]  # 내 뒤의 남의 PR(#3)은 JSON 에 없다
    # 기존 필드는 그대로이고 `devs` 만 늘었다(#390).
    old_keys = {"number", "sha", "title", "author", "url", "base", "head", "state", "detail", "next", "notes",
                "human_merge", "order", "after", "after_reasons", "version", "mine"}
    for it in json.loads(js)["prs"]:
        assert set(it) == old_keys | {"devs", "dev"} and it["dev"] is None and it["devs"] == []
    _, js_all = pr_queue.run(parse(["--repo", "o/r", "--json"]), gh)
    assert [it["number"] for it in json.loads(js_all)["prs"]] == [1, 2, 3]
    code, text = pr_queue.run(parse(["--repo", "o/r", "--pr", "2"]), gh)
    assert code == pr_queue.EXIT_BEFORE_OPEN and text.startswith(f"{link(2)} 보다 먼저 병합해야 하는 열린 PR:")


# --- --pr: 병합 직전에 앞 PR 만 묻기(#370) ----------------------------------------


def ask_before(gh, number, as_json=True):
    argv = ["--repo", "o/r", "--pr", str(number)] + (["--json"] if as_json else [])
    code, text = pr_queue.run(pr_queue.build_parser().parse_args(argv), gh)
    return code, (json.loads(text) if as_json else text)


def test_pr_option_lists_open_predecessors_with_reasons():
    gh = FakeGh([pr(7, title="앞 작업"), pr(3, body="먼저: #7")])
    code, res = ask_before(gh, 3)
    assert code == pr_queue.EXIT_BEFORE_OPEN
    assert res["status"] == "ok" and res["pr"] == 3
    assert res["before"] == [
        {"number": 7, "title": "앞 작업", "url": "https://github.com/o/r/pull/7", "reasons": ["본문의 먼저: 줄"]}
    ]
    assert res["url"] == "https://github.com/o/r/pull/3"


def test_pr_option_without_predecessor_exits_0():
    gh = FakeGh([pr(7), pr(3)])
    code, res = ask_before(gh, 3)
    assert code == EXIT_OK and res["before"] == []


def test_pr_option_lists_only_direct_predecessor_in_a_chain():
    gh = FakeGh([pr(1), pr(2, body="먼저: #1"), pr(3, body="먼저: #2, #1")])
    _, res = ask_before(gh, 3)
    assert [e["number"] for e in res["before"]] == [2]


def test_pr_option_orders_by_plugin_version():
    gh = FakeGh([pr(20, files=(PJ,)), pr(21, files=(PJ,))], versions={"sha20": "0.10.9", "sha21": "0.10.10"})
    code, res = ask_before(gh, 21)
    assert code == pr_queue.EXIT_BEFORE_OPEN and res["before"][0]["number"] == 20
    assert "version" in res["before"][0]["reasons"][0]
    assert ask_before(gh, 20)[0] == EXIT_OK


def test_pr_option_same_file_warning_is_not_a_predecessor():
    gh = FakeGh([pr(1, files=("y.md",)), pr(2, files=("y.md",))])
    assert ask_before(gh, 2)[0] == EXIT_OK


def test_pr_option_cycle_is_cannot_check():
    gh = FakeGh([pr(1, body="먼저: #2"), pr(2, body="먼저: #1"), pr(3, body="먼저: #2")])
    for n in (1, 3):
        code, res = ask_before(gh, n)
        assert code == EXIT_CANNOT_CHECK and res["status"] == "cannot_check"
    assert "순환" in ask_before(gh, 1)[1]["message"]
    assert "순서 판정 불능" in ask_before(gh, 3)[1]["message"]


def test_pr_option_cycle_elsewhere_does_not_block_unrelated_pr():
    gh = FakeGh([pr(1, body="먼저: #2"), pr(2, body="먼저: #1"), pr(4)])
    assert ask_before(gh, 4)[0] == EXIT_OK


def test_pr_option_read_failure_is_cannot_check():
    code, res = ask_before(FakeGh([], fail="네트워크 실패"), 3)
    assert code == EXIT_CANNOT_CHECK and "네트워크 실패" in res["message"]


def test_pr_option_pr_not_open_is_cannot_check():
    code, res = ask_before(FakeGh([pr(1)]), 99)
    assert code == EXIT_CANNOT_CHECK and "#99" in res["message"]


def test_pr_option_unread_version_of_plugin_pr_is_cannot_check():
    gh = FakeGh([pr(20, files=(PJ,)), pr(21, files=(PJ,))], versions={"sha21": "0.10.10"})
    code, res = ask_before(gh, 21)
    assert code == EXIT_CANNOT_CHECK and "#20" in res["message"]
    # plugin.json 을 안 바꾼 PR 은 version 순서와 무관하다.
    gh = FakeGh([pr(20, files=(PJ,)), pr(5)], versions={})
    assert ask_before(gh, 5)[0] == EXIT_OK


def test_pr_option_too_many_open_prs_is_cannot_check():
    prs = [pr(n) for n in range(1, pr_queue.PR_LIMIT + 1)]
    code, res = ask_before(FakeGh(prs), 1)
    assert code == EXIT_CANNOT_CHECK and "앞 PR" in res["message"]


def test_pr_option_does_not_classify_states():
    gh = FakeGh([pr(1, checks=[bad("x")]), pr(2)])
    ask_before(gh, 2)
    assert not any("/pulls/" in c[0] or "/issues/" in c[0] for c in gh.calls if c and c[0] != "pr")


def test_pr_option_text_output():
    gh = FakeGh([pr(7, title="앞 작업"), pr(3, body="먼저: #7")])
    code, text = ask_before(gh, 3, as_json=False)
    assert code == pr_queue.EXIT_BEFORE_OPEN and "[#7](https://github.com/o/r/pull/7) 앞 작업" in text
    assert "먼저: 줄" in text and "[#3](https://github.com/o/r/pull/3) 보다" in text


def test_pr_links_use_gh_url_or_build_one():
    assert pr_queue.pr_link("o/r", 5) == "[#5](https://github.com/o/r/pull/5)"
    assert pr_queue.pr_link("o/r", 5, "https://example/x/5") == "[#5](https://example/x/5)"
    raw = pr(1)
    raw.pop("url")
    res, _ = compute([raw, pr(2, body="먼저: #1")])
    by_n = {it["number"]: it for it in res["prs"]}
    assert by_n[1]["url"] == "https://github.com/o/r/pull/1"


def test_tables_link_prs_and_json_has_urls():
    gh = FakeGh([pr(1), pr(2, body="먼저: #1")])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--mine"])
    _, text = pr_queue.run(args, gh)
    assert "| 병합하기 | [#1](https://github.com/o/r/pull/1) 제목 1 |" in text
    assert "| 기다리기 | [#2](https://github.com/o/r/pull/2) 제목 2 — 앞 [#1](https://github.com/o/r/pull/1) 대기 |" in text
    assert "| 제목 1 | [#1](https://github.com/o/r/pull/1) ✅ → **[#2]" not in text  # 둘 다 내 PR 이라 #1 도 굵게
    assert "**[#1](https://github.com/o/r/pull/1)** ✅ → **[#2](https://github.com/o/r/pull/2)** ✅" in text
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--json"])
    _, js = pr_queue.run(args, gh)
    assert all(it["url"].startswith("https://github.com/o/r/pull/") for it in json.loads(js)["prs"])


def test_clip_neutralizes_link_and_table_syntax():
    out = pr_queue._clip("[#1](https://evil) a|b", 40)
    assert out == "\\[#1\\](https://evil) a\\|b"
    gh = FakeGh([pr(1, title="[#9](https://evil) 승인됨")])
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--mine"])
    _, text = pr_queue.run(args, gh)
    assert "\\[#9\\](https://evil) 승인됨" in text and "[#9](https://evil" not in text
