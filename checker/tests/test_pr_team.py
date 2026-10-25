"""팀원별 현황(#438). GitHub 호출은 가짜로 바꾼다."""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone

from checker import pr_queue, pr_team
from checker.pr_queue import EXIT_CANNOT_CHECK, EXIT_OK
from checker.ssot_approval import GhError
from checker.tests.test_pr_queue import FakeGh, bad, ok, pr

NOW = datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)  # KST 12:00


def ago(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat().replace("+00:00", "Z")


LEDGER = (
    "# 프로그램\n\n## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n"
    "| DEV-001 | 자재 출고 | - | alice | 진행 | #11 |\n"
    "| DEV-002 | 입고 | - |  | 대기 | #12 |\n"
    "| DEV-003 | 재고 | - | carol | 완료 | #5 |\n"
    "|  |  |  |  | 대기 |  |\n\n## 메모\n"
)


def check_node(name, reason=None, kind="annotation"):
    node = {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "FAILURE", "title": None, "summary": None, "annotations": {"nodes": []}}
    if kind == "annotation" and reason:
        node["annotations"]["nodes"] = [{"message": reason}]
    if kind == "title":
        node["title"] = reason
    return node


class TeamGh(FakeGh):
    def __init__(
        self, prs, meta=None, merged=None, issues=None, failures=None, ledger=None, fail_on=(),
        branch="main", branch_error=None, aliases=None, issue_pages=None, merged_count=None, more_prs=False, context_pages=None, **kw
    ):
        super().__init__(prs, **kw)
        self.branch = branch
        self.branch_error = branch_error
        self.issue_pages = issue_pages  # [[이슈…], [이슈…]]: 마지막 쪽 뒤에도 더 있으면 hasNextPage 가 계속 참
        self.merged_count = merged_count
        self.more_prs = more_prs
        self.context_pages = context_pages or {}  # {PR 번호: [첫 쪽 뒤의 추가 쪽 노드 목록…]}
        self.ledger_refs = []
        self.aliases = aliases  # None: 파일 없음(404), str: 본문, Exception: 읽기 실패
        self.issues_endless = False  # 쪽 수 제한에 걸릴 때까지 다음 쪽이 계속 있다
        self.contexts_endless = False
        self.meta = meta if meta is not None else {}
        self.merged = merged or []
        self.issues = issues or []
        self.failures = failures or {}
        self.ledger = ledger  # None: 디렉터리 없음, dict: {경로: 본문 또는 Exception}
        self.fail_on = set(fail_on)
        self.graphql_calls = 0

    def run(self, args):
        if args[:2] != ["api", "graphql"]:
            return super().run(args)
        self.graphql_calls += 1
        query = args[3][len("query=") :]
        for tag in self.fail_on:
            if tag in query:
                raise GhError(f"{tag} 실패")
        if "pullRequests(states:OPEN" in query:
            nodes = [_meta_node(n, m) for n, m in self.meta.items()]
            return json.dumps({"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": self.more_prs}, "nodes": nodes}}}})
        if "search(" in query:
            self.search_query = next(a for a in args if a.startswith("q="))
            count = self.merged_count if self.merged_count is not None else len(self.merged)
            return json.dumps({"data": {"search": {"issueCount": count, "nodes": self.merged}}})
        variables = dict(a.split("=", 1) for a in args[4:] if "=" in a and not a.startswith(("-f", "-F")))
        if "issues(states:OPEN" in query:
            if self.issue_pages is None:
                info, nodes = {"hasNextPage": False, "endCursor": None}, self.issues
            else:
                page = int(variables["after"][1:]) if "after" in variables else 0
                more = page + 1 < len(self.issue_pages) or self.issues_endless
                info = {"hasNextPage": more, "endCursor": f"c{page + 1}" if more else None}
                nodes = self.issue_pages[min(page, len(self.issue_pages) - 1)]
            return json.dumps({"data": {"repository": {"issues": {"pageInfo": info, "nodes": nodes}}}})
        if "$number:Int!" in query:
            n = int(variables["number"])
            extra = self.context_pages[n]
            idx = int(variables["after"][1:])
            info = {"hasNextPage": idx + 1 < len(extra) or self.contexts_endless, "endCursor": f"x{idx + 1}"}
            nodes = extra[min(idx, len(extra) - 1)]
            ctx = {"pageInfo": info, "nodes": nodes}
            return json.dumps({"data": {"repository": {"pullRequest": {"commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": ctx}}}]}}}}})
        repo = {}
        for n in re.findall(r"p(\d+):pullRequest", query):
            nodes = self.failures.get(int(n), [])
            more = int(n) in self.context_pages
            info = {"hasNextPage": more, "endCursor": "x0" if more else None}
            ctx = {"pageInfo": info, "nodes": nodes}
            repo[f"p{n}"] = {"commits": {"nodes": [{"commit": {"statusCheckRollup": {"contexts": ctx}}}]}}
        return json.dumps({"data": {"repository": repo}})

    def get_json(self, path):
        if path == "repos/o/r":
            if self.branch_error:
                raise GhError(self.branch_error)
            return {"default_branch": self.branch}
        return super().get_json(path)

    def get_json_or_none_404(self, path):
        if ".github/harness-team.yaml" in path:
            self.alias_ref = path.split("ref=")[1]
            if isinstance(self.aliases, Exception):
                raise self.aliases
            return None if self.aliases is None else {"content": base64.b64encode(self.aliases.encode("utf-8")).decode()}
        if "audit/ledger" in path:
            self.ledger_refs.append(path.split("ref=")[1])
            if self.ledger is None:
                return None
            if path.split("?")[0].endswith("audit/ledger"):
                return [{"type": "file", "path": p} for p in self.ledger]
            p = path.split("/contents/")[1].split("?")[0]
            body = self.ledger[p]
            if isinstance(body, Exception):
                raise body
            return {"content": base64.b64encode(body.encode("utf-8")).decode()}
        return super().get_json_or_none_404(path)


def _who(login, typename="User"):
    return {"login": login, "__typename": typename}


def _meta_node(number, m):
    """m: (사람 코멘트 시각, 커밋 시각) 짧은 꼴, 또는 {commit, created, comments, reviews, threads, *_total} 전체 꼴."""
    if isinstance(m, tuple):
        u, c = m
        m = {"commit": c, "created": c, "comments": [(u, "dev", "User")] if u else []}
    commit = m.get("commit")
    def items(key, field):
        return [{field: t, "author": _who(l, ty)} for t, l, ty in m.get(key, [])]
    comments, reviews = items("comments", "createdAt"), items("reviews", "submittedAt")
    threads = [{"comments": {"nodes": [{"createdAt": t, "author": _who(l, ty)}]}} for t, l, ty in m.get("threads", [])]
    return {
        "number": number,
        "createdAt": m.get("created", commit),
        "commits": {"nodes": [{"commit": {"committedDate": commit}}] if commit else []},
        "comments": {"totalCount": m.get("comments_total", len(comments)), "nodes": comments},
        "reviews": {"totalCount": m.get("reviews_total", len(reviews)), "nodes": reviews},
        "reviewThreads": {"totalCount": m.get("threads_total", len(threads)), "nodes": threads},
    }


def merged_pr(n, author, when, title="병합함"):
    return {"number": n, "title": title, "url": f"https://github.com/o/r/pull/{n}", "mergedAt": when, "author": {"login": author, "__typename": "User"}}


def issue(n, assignees, created, comments=(), total=None):
    """created: 생성 시각. comments: [(시각, 로그인, 형)]. 코멘트가 없으면 마지막 활동은 생성 시각이다."""
    nodes = [{"createdAt": t, "author": _who(l, ty)} for t, l, ty in comments]
    return {"number": n, "title": f"이슈 {n}", "url": f"https://github.com/o/r/issues/{n}", "createdAt": created,
            "assignees": {"nodes": [{"login": a, "__typename": "User"} for a in assignees]},
            "comments": {"totalCount": len(nodes) if total is None else total, "nodes": nodes}}


def team(gh, **kw):
    return pr_team.compute_team(gh, "o/r", now=NOW, **kw)


def person(res, login):
    return next(p for p in res["people"] if p["login"] == login)


# --- 사람별 묶기 ---------------------------------------------------------------


def test_groups_by_person_with_progress_and_last_commit():
    gh = TeamGh(
        [pr(1, author="alice"), pr(2, author="bob"), pr(3, author="alice")],
        meta={1: (ago(hours=2), ago(hours=5)), 2: (ago(days=1), ago(days=1)), 3: (ago(hours=1), ago(hours=1))},
        merged=[merged_pr(9, "alice", ago(days=2)), merged_pr(8, "bob", ago(days=6)), merged_pr(7, "bob", ago(days=8))],
        issues=[issue(20, ["bob"], ago(days=1))],
    )
    res = team(gh)
    assert [p["login"] for p in res["people"]] == ["alice", "bob"]
    alice, bob = person(res, "alice"), person(res, "bob")
    assert [o["number"] for o in alice["progress"]["open"]] == [1, 3]
    assert alice["progress"]["open"][0]["last_commit_at"] == ago(hours=5)
    assert alice["progress"]["merged_count"] == 1 and bob["progress"]["merged_count"] == 1  # 8일 전 병합은 7일 밖
    assert res["unknown"] == [] or all(u["item"] != "열린 PR 의 마지막 커밋·갱신 시각" for u in res["unknown"])


def test_blockers_conflict_approval_and_waiting_on_earlier_pr():
    gh = TeamGh(
        [
            pr(1, author="alice", mergeable="CONFLICTING", mergeStateStatus="DIRTY"),
            pr(2, author="alice", base="feat/1", head="feat/2"),
        ],
        meta={1: (ago(hours=1), ago(hours=1)), 2: (ago(hours=1), ago(hours=1))},
    )
    res = team(gh)
    kinds = {b["pr"]: [r["kind"] for r in b["reasons"]] for b in person(res, "alice")["blocked"]}
    assert kinds[1] == [pr_team.K_CONFLICT] and kinds[2] == [pr_team.K_AFTER]
    after = person(res, "alice")["blocked"][1]["reasons"][0]
    assert after["after"] == [1]


def test_bot_authors_are_not_people():
    gh = TeamGh([pr(1, author="dependabot[bot]"), pr(2, author="bob")], meta={})
    res = team(gh)
    assert [p["login"] for p in res["people"]] == ["bob"]


# --- 검사 실패 사유와 공통 원인 ----------------------------------------------------


def _failing(number, author, checks):
    return pr(number, author=author, checks=[bad(n) for n, _ in checks] + [ok("doc-guard / ok")])


def test_failure_reason_comes_from_annotation_then_title():
    gh = TeamGh(
        [_failing(1, "alice", [("doc-guard / lint", None)]), _failing(2, "bob", [("doc-guard / test", None)])],
        failures={1: [check_node("doc-guard / lint", "린트 오류 3건")], 2: [check_node("doc-guard / test", "테스트 2건 실패", kind="title")]},
        meta={1: (ago(hours=1), ago(hours=1)), 2: (ago(hours=1), ago(hours=1))},
    )
    res = team(gh)
    a = person(res, "alice")["blocked"][0]["reasons"][0]["checks"][0]
    b = person(res, "bob")["blocked"][0]["reasons"][0]["checks"][0]
    assert (a["name"], a["reason"]) == ("doc-guard / lint", "린트 오류 3건")
    assert b["reason"] == "테스트 2건 실패"
    assert res["common_causes"] == []
    assert a["common_cause"] is None


def test_same_reason_on_two_prs_becomes_one_common_cause():
    msg = "The job was not started because recent account payments have failed"
    gh = TeamGh(
        [_failing(1, "alice", [("doc-guard / check", None)]), _failing(2, "bob", [("doc-guard / check", None)]),
         _failing(3, "bob", [("doc-guard / check", None)]), _failing(4, "carol", [("doc-guard / check", None)])],
        failures={1: [check_node("doc-guard / check", msg)], 2: [check_node("doc-guard / check", msg)],
                  3: [check_node("doc-guard / check", msg)], 4: [check_node("doc-guard / check", "다른 사유")]},
        meta={n: (ago(hours=1), ago(hours=1)) for n in (1, 2, 3, 4)},
    )
    res = team(gh)
    assert len(res["common_causes"]) == 1
    cause = res["common_causes"][0]
    assert cause["id"] == 1 and cause["mark"] == "①" and cause["reason"] == msg
    assert [p["number"] for p in cause["prs"]] == [1, 2, 3]
    assert person(res, "alice")["blocked"][0]["reasons"][0]["checks"][0]["common_cause"] == 1
    assert person(res, "carol")["blocked"][0]["reasons"][0]["checks"][0]["common_cause"] is None
    text = pr_team.render_team(res)
    assert text.count(msg) == 1  # 사람별 칸에서는 반복하지 않는다
    assert "공통 원인 ①" in text


def test_failure_reason_unreadable_is_unknown_not_blank():
    gh = TeamGh([_failing(1, "alice", [("doc-guard / lint", None)])], meta={1: (ago(hours=1), ago(hours=1))}, fail_on=("pullRequest(number",))
    res = team(gh)
    c = person(res, "alice")["blocked"][0]["reasons"][0]["checks"][0]
    assert c["reason"] is None and c["reason_status"] == "unknown" and "실패" in c["unknown_reason"]
    assert any(u["item"] == "검사 실패 사유" for u in res["unknown"])
    assert "사유 확인 불능" in pr_team.render_team(res)


def test_job_that_never_started_shows_annotation_reason():
    # Actions 결제 실패: pr-checks job 하나만 실패하고 병합이 막힌 상태(BLOCKED)로 보인다. 사유는 그 job 의 annotation 에 있다.
    msg = "The job was not started because recent account payments have failed"
    prs = [pr(n, author=a, checks=[bad("pr-checks / check")], mergeStateStatus="BLOCKED") for n, a in ((1, "alice"), (2, "bob"))]
    gh = TeamGh(prs, failures={n: [check_node("pr-checks / check", msg)] for n in (1, 2)}, meta={})
    res = team(gh)
    b = person(res, "alice")["blocked"][0]
    r = b["reasons"][0]
    assert r["kind"] == pr_team.K_CHECK and r["state"] == pr_queue.BLOCKED
    assert len(res["common_causes"]) == 1 and res["common_causes"][0]["reason"] == msg


def test_not_started_without_failed_run_is_other_not_check():
    gh = TeamGh([pr(1, author="alice", checks=[bad("pr-checks / check")], mergeStateStatus="BLOCKED")], failures={1: []}, meta={})
    assert person(team(gh), "alice")["blocked"][0]["reasons"][0]["kind"] == pr_team.K_OTHER


def test_failed_check_without_text_is_marked_no_text():
    gh = TeamGh([_failing(1, "alice", [("doc-guard / lint", None)])], failures={1: [check_node("doc-guard / lint", None)]}, meta={1: (ago(hours=1), ago(hours=1))})
    c = person(team(gh), "alice")["blocked"][0]["reasons"][0]["checks"][0]
    assert c["reason"] is None and c["reason_status"] == "no_text"


# --- 오래 머문 일 경계 -------------------------------------------------------------


def test_stale_pr_boundary_is_strictly_more_than_n_days():
    gh = TeamGh(
        [pr(1, author="alice"), pr(2, author="alice"), pr(3, author="alice")],
        meta={1: (ago(days=3), ago(days=3)), 2: (ago(days=3, seconds=1), ago(days=4)), 3: (ago(days=2, hours=23), ago(days=5))},
    )
    stale = [s["number"] for s in person(team(gh), "alice")["stale"]["prs"]]
    assert stale == [2]


def test_stale_days_option_changes_threshold():
    gh = TeamGh([pr(1, author="alice")], meta={1: (ago(days=2), ago(days=2))})
    assert person(team(gh), "alice")["stale"]["prs"] == []
    assert [s["number"] for s in person(team(gh, stale_days=1), "alice")["stale"]["prs"]] == [1]


def test_stale_issue_boundary_14_days_and_unassigned():
    gh = TeamGh(
        [pr(1, author="alice")], meta={1: (ago(hours=1), ago(hours=1))},
        issues=[issue(10, ["alice"], ago(days=14)), issue(11, ["alice"], ago(days=14, minutes=1)), issue(12, [], ago(days=30))],
    )
    res = team(gh)
    assert [s["number"] for s in person(res, "alice")["stale"]["issues"]] == [11]
    assert [i["number"] for i in res["unassigned_issues"]] == [12]


# --- 원장 ---------------------------------------------------------------------


def test_ledger_items_by_owner_and_last_pr_author():
    gh = TeamGh(
        [pr(11, author="alice"), pr(12, author="bob")], meta={},
        merged=[merged_pr(5, "carol", ago(days=1))],
        ledger={"audit/ledger/prog.md": LEDGER},
    )
    res = team(gh)
    assert res["ledger"]["status"] == "ok"
    assert [d["id"] for d in person(res, "alice")["dev_items"]] == ["DEV-001"]
    assert [d["id"] for d in person(res, "bob")["dev_items"]] == ["DEV-002"]  # 담당 칸이 비면 마지막 PR 작성자
    carol = person(res, "carol")["dev_items"][0]
    assert (carol["id"], carol["status"], carol["last_pr"], carol["title"]) == ("DEV-003", "완료", "#5", "재고")


def test_no_ledger_is_skipped_not_unknown():
    res = team(TeamGh([pr(1, author="alice")], meta={}, ledger=None))
    assert res["ledger"]["status"] == "none"
    assert person(res, "alice")["dev_items"] is None
    assert not any(u["item"] == "진행 원장" for u in res["unknown"])
    assert "원장 없음" in pr_team.render_team(res)


def test_ledger_read_failure_is_unknown():
    gh = TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": GhError("읽기 실패 500")})
    res = team(gh)
    assert res["ledger"]["status"] == "unknown" and "읽기 실패" in res["ledger"]["reason"]
    assert any(u["item"] == "진행 원장" for u in res["unknown"])
    assert person(res, "alice")["dev_items"] is None
    assert "맡은 개발 건: 확인 불능" in pr_team.render_team(res)


def test_ledger_without_section_is_unknown():
    gh = TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": "# 제목\n내용 없음\n"})
    res = team(gh)
    assert res["ledger"]["status"] == "unknown" and "개발 건" in res["ledger"]["reason"]


# --- 확인 불능 -----------------------------------------------------------------


def test_each_unreadable_section_is_unknown_and_null():
    gh = TeamGh(
        [pr(1, author="alice")], meta={}, fail_on=("pullRequests(states:OPEN", "search(", "issues(states:OPEN"),
    )
    res = team(gh)
    items = {u["item"] for u in res["unknown"]}
    assert "열린 PR 의 마지막 커밋·갱신 시각" in items and "열린 이슈와 담당자" in items
    assert any("병합한 PR" in i for i in items)
    p = person(res, "alice")
    assert p["progress"]["merged"] is None and p["stale"]["prs"] is None and p["stale"]["issues"] is None
    assert p["progress"]["open"][0]["last_commit_at"] is None
    assert res["unassigned_issues"] is None
    text = pr_team.render_team(res)
    assert "## 확인 불능" in text and "확인 불능" in text.split("### @alice")[1]


def test_open_pr_list_failure_is_cannot_check_exit_2():
    gh = TeamGh([], fail="연결 안 됨")
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--team", "--json"])
    code, text = pr_queue.run(args, gh)
    assert code == EXIT_CANNOT_CHECK and json.loads(text)["status"] == "cannot_check"


# --- 호출 수 · 시간 · 출력 --------------------------------------------------------


def test_graphql_calls_do_not_grow_with_pr_count():
    prs = [pr(n, author="alice") for n in range(1, 31)]
    gh = TeamGh(prs, meta={n: (ago(hours=1), ago(hours=1)) for n in range(1, 31)})
    team(gh)
    assert gh.graphql_calls == 3  # 열린 PR 시각 + 병합 + 이슈. 실패 PR 이 없으면 사유 조회는 없다


def test_failure_detail_queries_are_batched():
    n = 40
    prs = [_failing(i, "alice", [("doc-guard / x", None)]) for i in range(1, n + 1)]
    gh = TeamGh(prs, failures={i: [check_node("doc-guard / x", f"사유 {i}")] for i in range(1, n + 1)}, meta={})
    team(gh)
    assert gh.graphql_calls == 3 + 3  # 40개 / 15개씩 = 3번


def test_time_budget_exceeded_marks_unknown(monkeypatch):
    monkeypatch.setattr(pr_team, "TIME_BUDGET_SEC", -1)
    res = team(TeamGh([pr(1, author="alice")], meta={}))
    assert {u["item"] for u in res["unknown"]} >= {"열린 PR 의 마지막 커밋·갱신 시각", "열린 이슈와 담당자"}
    assert all("시간 제한" in u["reason"] for u in res["unknown"])


def test_kst_display():
    assert pr_team.kst(datetime(2026, 10, 25, 3, 0, tzinfo=timezone.utc)) == "10-25 12:00 KST"
    assert pr_team.kst(None) == "시각 확인 불능"
    gh = TeamGh([pr(1, author="alice")], meta={1: (ago(hours=1), "2026-10-24T15:30:00Z")})
    assert "10-25 00:30 KST" in pr_team.render_team(team(gh))


def test_json_keys_are_stable():
    gh = TeamGh(
        [_failing(1, "alice", [("doc-guard / x", None)])], failures={1: [check_node("doc-guard / x", "깨짐")]},
        meta={1: (ago(days=5), ago(days=5))}, merged=[merged_pr(9, "alice", ago(days=1))],
        issues=[issue(3, [], ago(days=1))], ledger={"audit/ledger/prog.md": LEDGER},
    )
    args = pr_queue.build_parser().parse_args(["--repo", "o/r", "--team", "--all", "--json"])
    code, text = pr_queue.run(args, gh)
    res = json.loads(text)
    assert code == EXIT_OK
    assert set(res) == {"status", "repo", "generated_at", "days", "stale_days", "issue_stale_days", "common_causes", "people", "unassigned_issues", "ledger", "truncated", "aliases_applied", "unknown", "warnings"}
    p = res["people"][0]
    assert set(p) == {"login", "progress", "blocked", "stale", "dev_items"}
    assert set(p["progress"]) == {"merged", "merged_count", "open"}
    assert set(p["progress"]["open"][0]) == {"number", "title", "url", "state", "last_commit_at", "last_activity_at", "last_activity_kind"}
    assert set(p["progress"]["merged"][0]) == {"number", "title", "url", "merged_at"}
    assert set(p["stale"]) == {"prs", "issues", "unknown_prs", "unknown_issues"}
    assert set(p["stale"]["prs"][0]) == {"number", "title", "url", "state", "last_activity_at", "last_activity_kind", "idle_days"}
    assert set(p["blocked"][0]) == {"pr", "title", "url", "author", "reasons"}
    assert set(p["blocked"][0]["reasons"][0]) == {"kind", "state", "detail", "checks", "checks_truncated"}
    assert set(p["blocked"][0]["reasons"][0]["checks"][0]) == {"name", "reason", "reason_status", "common_cause"}
    assert set(p["dev_items"][0]) == {"id", "title", "owner", "status", "last_pr", "file"}
    assert set(res["ledger"]) == {"status", "reason", "branch", "files", "unowned"}
    assert set(res["unassigned_issues"][0]) == {"number", "title", "url", "created_at"}


def test_team_rejects_mine():
    import pytest

    with pytest.raises(SystemExit):
        pr_queue.main(["--repo", "o/r", "--team", "--mine"])


def test_options_default_values():
    args = pr_queue.build_parser().parse_args(["--team"])
    assert (args.days, args.stale_days) == (7, 3)


# --- 공통 원인 열쇠 · 한 PR 한 줄 ------------------------------------------------------

PAYMENT = (
    "The job was not started because recent account payments have failed or your spending limit needs to be increased. "
    "Please check the 'Billing & plans' section in your settings."
)
CHECKS4 = ["ai-review / review", "doc-guard / check", "gitleaks / g", "ops-guard / o"]


def _payment_gh(numbers=(1, 2, 3)):
    prs = [pr(n, author="alice", checks=[bad(c) for c in CHECKS4]) for n in numbers]
    failures = {n: [check_node(c, PAYMENT) for c in CHECKS4] for n in numbers}
    return TeamGh(prs, failures=failures, meta={})


def test_specific_reason_groups_across_checks_into_one_cause():
    res = team(_payment_gh())
    assert len(res["common_causes"]) == 1
    cause = res["common_causes"][0]
    assert cause["reason"] == PAYMENT and cause["checks"] == sorted(CHECKS4)
    assert [p["number"] for p in cause["prs"]] == [1, 2, 3]
    text = pr_team.render_team(res)
    assert text.count(PAYMENT) == 1  # 전체 문구, 한 번만


def test_generic_reasons_stay_per_check():
    assert pr_team.is_generic_reason("Process completed with exit code 1.")
    assert pr_team.is_generic_reason("Failure")  # 20자 미만
    assert not pr_team.is_generic_reason(PAYMENT)
    prs = [pr(n, author="alice", checks=[bad("doc-guard / a"), bad("gitleaks / g")]) for n in (1, 2)]
    failures = {n: [check_node("doc-guard / a", "Process completed with exit code 1."), check_node("gitleaks / g", "Process completed with exit code 1.")] for n in (1, 2)}
    res = team(TeamGh(prs, failures=failures, meta={}))
    assert [c["checks"] for c in res["common_causes"]] == [["doc-guard / a"], ["gitleaks / g"]]


def test_no_text_reason_is_never_a_common_cause():
    prs = [pr(n, author="alice", checks=[bad("doc-guard / a")]) for n in (1, 2)]
    res = team(TeamGh(prs, failures={n: [check_node("doc-guard / a", None)] for n in (1, 2)}, meta={}))
    assert res["common_causes"] == []
    assert "사유 문구 없음" in pr_team.render_team(res)


def test_long_reason_is_cut_at_sentence_end_with_ellipsis():
    long = " ".join(["The job failed because of a very long explanation."] * 10)
    cut = pr_team._clean(long)
    assert cut.endswith("explanation.…") and len(cut) <= pr_team.REASON_LIMIT + 1
    words = " ".join(["abcdefghij"] * 60)
    cut = pr_team._clean(words)
    assert cut.endswith("abcdefghij…")
    assert pr_team._clean("짧은 사유.") == "짧은 사유."


def test_one_line_per_pr_and_blocked_count_is_pr_count():
    res = team(_payment_gh((1, 2)))
    alice = person(res, "alice")
    assert len(alice["blocked"]) == 2 and len(alice["blocked"][0]["reasons"]) == 1
    assert len(alice["blocked"][0]["reasons"][0]["checks"]) == 4
    text = pr_team.render_team(res)
    lines = [l for l in text.splitlines() if l.startswith("- 막힘")]
    assert len(lines) == 2
    assert "공통 원인 ①" in lines[0] and "ai-review" in lines[0] and "ops-guard" in lines[0]
    assert "| @alice | 0 | 2 | 2 |" in text  # 막힌 PR 수(검사 8개가 아니다)


def test_reasons_of_one_pr_share_a_line():
    prs = [pr(1, author="alice", mergeable="CONFLICTING", mergeStateStatus="DIRTY"), pr(2, author="alice", base="feat/1", head="feat/2", checks=[bad("doc-guard / a")])]
    gh = TeamGh(prs, failures={2: [check_node("doc-guard / a", "린트 오류가 3건 있다는 긴 사유 문구")]}, meta={})
    lines = [l for l in pr_team.render_team(team(gh)).splitlines() if l.startswith("- 막힘")]
    assert len(lines) == 2
    assert "검사 실패: doc-guard / a: 린트 오류가 3건 있다는 긴 사유 문구" in lines[1] and "앞 [#1]" in lines[1]


# --- 검토 지적(기본 브랜치·시각 없는 PR·담당자·쪽수 제한·검사 50개 초과) --------------------


def test_ledger_read_from_default_branch_master():
    gh = TeamGh([pr(1, author="alice")], meta={}, branch="master", ledger={"audit/ledger/prog.md": LEDGER})
    res = team(gh)
    assert res["ledger"]["status"] == "ok" and res["ledger"]["branch"] == "master"
    assert set(gh.ledger_refs) == {"master"}


def test_default_branch_lookup_failure_is_unknown_not_none():
    gh = TeamGh([pr(1, author="alice")], meta={}, branch_error="403 rate limit", ledger=None)
    res = team(gh)
    assert res["ledger"]["status"] == "unknown" and "기본 브랜치" in res["ledger"]["reason"]
    assert any(u["item"] == "진행 원장" for u in res["unknown"])
    assert person(res, "alice")["dev_items"] is None
    assert gh.ledger_refs == []  # 브랜치를 모르면 원장 경로를 추측해 조회하지 않는다
    assert "원장 없음" not in pr_team.render_team(res)


def test_no_ledger_names_the_checked_branch():
    text = pr_team.render_team(team(TeamGh([pr(1, author="alice")], meta={}, branch="master", ledger=None)))
    assert "원장 없음(기본 브랜치 master" in text


def test_open_pr_without_time_is_unknown_not_fresh():
    gh = TeamGh([pr(1, author="alice"), pr(2, author="alice")], meta={1: (ago(days=9), ago(days=9))})
    res = team(gh)
    a = person(res, "alice")
    assert a["stale"]["unknown_prs"] == [2] and [s["number"] for s in a["stale"]["prs"]] == [1]
    assert any(u["item"] == "PR 활동 시각(정체 판정 불능)" and "#2" in u["reason"] for u in res["unknown"])
    text = pr_team.render_team(res)
    assert "오래 머문 PR 판정 불능" in text and "+ 판정 불능 1" in text


def test_open_pr_without_commit_and_human_activity_is_unknown():
    gh = TeamGh([pr(1, author="alice")], meta={1: (None, None)})
    assert person(team(gh), "alice")["stale"]["unknown_prs"] == [1]


def test_more_open_prs_than_limit_warns():
    res = team(TeamGh([pr(1, author="alice")], meta={1: (ago(hours=1), ago(hours=1))}, more_prs=True))
    assert res["truncated"]["open_prs"] and any("시각을 일부만" in w for w in res["warnings"])


def test_ledger_owner_without_activity_gets_a_column():
    gh = TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": LEDGER.replace("| carol |", "| @Dave |")})
    res = team(gh)
    dave = person(res, "Dave")
    assert [d["id"] for d in dave["dev_items"]] == ["DEV-003"] and dave["dev_items"][0]["owner"] == "Dave"
    assert all(d["id"] != "DEV-003" for d in res["ledger"]["unowned"])
    assert "담당 @Dave" in pr_team.render_team(res)


def test_ledger_owner_that_is_not_a_github_login_warns():
    gh = TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": LEDGER.replace("| carol |", "| 홍길동 |")})
    res = team(gh)
    assert any("'홍길동'" in w and "GitHub 아이디" in w for w in res["warnings"])
    assert not any("GitHub 아이디" in w for w in team(TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": LEDGER}))["warnings"])


def test_ledger_owner_matches_existing_login_case_insensitively():
    gh = TeamGh([pr(1, author="Alice")], meta={}, ledger={"audit/ledger/prog.md": LEDGER})
    res = team(gh)
    assert [p["login"] for p in res["people"]].count("Alice") == 1 and "alice" not in [p["login"] for p in res["people"]]
    assert [d["id"] for d in person(res, "Alice")["dev_items"]] == ["DEV-001"]


def test_issue_pages_are_followed_with_has_next_page():
    pages = [[issue(1, ["alice"], ago(days=1))], [issue(2, ["alice"], ago(days=20)), issue(3, [], ago(days=21))]]
    gh = TeamGh([pr(1, author="alice")], meta={}, issue_pages=pages)
    res = team(gh)
    assert not res["truncated"]["issues"]
    assert [s["number"] for s in person(res, "alice")["stale"]["issues"]] == [2]
    assert [i["number"] for i in res["unassigned_issues"]] == [3]


def test_issue_page_limit_marks_stale_issues_partial(monkeypatch):
    monkeypatch.setattr(pr_team, "ISSUE_PAGES", 2)
    pages = [[issue(1, ["alice"], ago(days=1))], [issue(2, ["alice"], ago(days=2))]]
    gh = TeamGh([pr(1, author="alice")], meta={}, issue_pages=pages)
    gh.issues_endless = True
    res = team(gh)
    assert res["truncated"]["issues"] and any("오래된 것부터 빠져" in w for w in res["warnings"])
    text = pr_team.render_team(res)
    assert "오래 머문 이슈: 확인 불능(부분)" in text and "확인 불능, 부분" in text
    assert "일부만 읽음" in text.split("## 담당자 없는 열린 이슈")[1]


def test_merged_over_100_is_marked_and_search_sorted_newest_first():
    merged = [merged_pr(9, "alice", ago(days=1))]
    gh = TeamGh([pr(1, author="alice")], meta={}, merged=merged, merged_count=130)
    res = team(gh)
    assert res["truncated"]["merged"] and any("100개를 넘어" in w for w in res["warnings"])
    assert "sort:updated-desc" in gh.search_query
    text = pr_team.render_team(res)
    assert "| @alice | 1+ (부분) |" in text and "1개이상, 일부만 읽음" in text


def test_more_than_50_checks_are_paged_and_read_fully():
    gh = TeamGh(
        [_failing(1, "alice", [("doc-guard / a", None)])],
        failures={1: [ok_node(f"c{i}") for i in range(3)]}, meta={1: (ago(hours=1), ago(hours=1))},
        context_pages={1: [[check_node("doc-guard / a", "두 번째 쪽에서 읽은 사유 문구입니다")]]},
    )
    res = team(gh)
    r = person(res, "alice")["blocked"][0]["reasons"][0]
    assert r["checks_truncated"] is False and r["checks"][0]["reason"] == "두 번째 쪽에서 읽은 사유 문구입니다"
    assert gh.graphql_calls == 3 + 1 + 1  # 시각·병합·이슈 + 사유 묶음 + 추가 쪽


def test_checks_beyond_page_limit_say_too_many_not_none():
    gh = TeamGh(
        [_failing(1, "alice", [("doc-guard / a", None)])], failures={1: []}, meta={1: (ago(hours=1), ago(hours=1))},
        context_pages={1: [[ok_node("x")]]},
    )
    gh.contexts_endless = True
    res = team(gh)
    r = person(res, "alice")["blocked"][0]["reasons"][0]
    assert r["checks_truncated"] is True and "검사가" in r["checks"][0]["unknown_reason"]
    assert any(u["item"] == "검사 목록 일부" for u in res["unknown"])
    assert "를 넘어 일부를 읽지 못함" in pr_team.render_team(res)


def ok_node(name):
    return {"__typename": "CheckRun", "name": name, "status": "COMPLETED", "conclusion": "SUCCESS", "title": None, "summary": None, "annotations": {"nodes": []}}


# --- 정체 판정: 사람이 마지막으로 손댄 때 -----------------------------------------------------


def _stale_of(res, login="alice"):
    return {s["number"]: s for s in person(res, login)["stale"]["prs"]}


def test_only_recent_bot_comment_stays_stale():
    # 봇 코멘트가 방금 달려도(updatedAt 이 최근이어도) 사람이 3일 넘게 손대지 않았으면 정체다.
    old = ago(days=5)
    meta = {1: {"commit": old, "comments": [(ago(hours=1), "github-actions", "Bot"), (ago(hours=2), "github-actions[bot]", "User")],
                "reviews": [(ago(minutes=5), "dependabot", "Bot")]}}
    res = team(TeamGh([pr(1, author="alice")], meta=meta))
    s = _stale_of(res)[1]
    assert s["last_activity_kind"] == "commit" and s["idle_days"] == 5.0
    assert "마지막 커밋" in pr_team.render_team(res)


def test_recent_human_review_is_not_stale():
    old = ago(days=9)
    meta = {1: {"commit": old, "comments": [(ago(days=8), "bob", "User")], "reviews": [(ago(hours=3), "bob", "User")]}}
    res = team(TeamGh([pr(1, author="alice")], meta=meta))
    assert person(res, "alice")["stale"]["prs"] == []
    o = person(res, "alice")["progress"]["open"][0]
    assert o["last_activity_kind"] == "review" and o["last_activity_at"] == ago(hours=3)


def test_recent_human_review_comment_counts():
    meta = {1: {"commit": ago(days=9), "threads": [(ago(hours=2), "bob", "User")]}}
    o = person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["progress"]["open"][0]
    assert o["last_activity_kind"] == "review_comment"


def test_latest_commit_is_the_last_activity():
    meta = {1: {"commit": ago(days=4), "created": ago(days=10), "comments": [(ago(days=6), "bob", "User")]}}
    res = team(TeamGh([pr(1, author="alice")], meta=meta))
    s = _stale_of(res)[1]
    assert s["last_activity_kind"] == "commit" and s["idle_days"] == 4.0
    assert "(마지막 커밋 10-21 12:00 KST)" in pr_team.render_team(res)  # NOW = 10-25 12:00 KST, 4일 전


def test_pr_opened_recently_with_old_commits_is_not_stale():
    meta = {1: {"commit": ago(days=30), "created": ago(hours=2)}}
    o = person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["progress"]["open"][0]
    assert o["last_activity_kind"] == "opened"


def test_all_bot_window_with_more_comments_is_unknown_not_stale():
    # 최근 20개가 전부 봇이고 그 앞에 더 있다: 사람이 그 앞에 댓글을 달았는지 알 수 없다.
    meta = {1: {"commit": ago(days=9), "comments": [(ago(hours=1), "github-actions", "Bot")], "comments_total": 55}}
    res = team(TeamGh([pr(1, author="alice")], meta=meta))
    a = person(res, "alice")
    assert a["stale"]["prs"] == [] and a["stale"]["unknown_prs"] == [1]
    assert any("PR 활동 시각" in u["item"] and "코멘트" in u["reason"] for u in res["unknown"])


def test_all_bot_window_but_recent_commit_is_definitely_not_stale():
    meta = {1: {"commit": ago(hours=1), "comments": [(ago(minutes=1), "github-actions", "Bot")], "comments_total": 55}}
    a = person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")
    assert a["stale"]["prs"] == [] and a["stale"]["unknown_prs"] == []


def test_missing_commit_time_is_unknown_even_with_old_activity():
    meta = {1: {"commit": None, "created": ago(days=9)}}
    assert person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["stale"]["unknown_prs"] == [1]


def test_issue_without_comments_uses_creation_time():
    gh = TeamGh([pr(1, author="alice")], meta={}, issues=[issue(10, ["alice"], ago(days=15)), issue(11, ["alice"], ago(days=13))])
    res = team(gh)
    st = person(res, "alice")["stale"]["issues"]
    assert [(s["number"], s["last_activity_kind"]) for s in st] == [(10, "created")]
    assert "(마지막 이슈 생성" in pr_team.render_team(res)


def test_issue_human_comment_refreshes_but_bot_comment_does_not():
    gh = TeamGh(
        [pr(1, author="alice")], meta={},
        issues=[
            issue(10, ["alice"], ago(days=40), comments=[(ago(days=1), "bob", "User")]),
            issue(11, ["alice"], ago(days=40), comments=[(ago(hours=1), "github-actions", "Bot"), (ago(days=20), "bob", "User")]),
        ],
    )
    st = person(team(gh), "alice")["stale"]["issues"]
    assert [(s["number"], s["last_activity_kind"]) for s in st] == [(11, "comment")]


def test_issue_with_only_bot_comments_beyond_window_is_unknown():
    gh = TeamGh([pr(1, author="alice")], meta={}, issues=[issue(10, ["alice"], ago(days=40), comments=[(ago(hours=1), "github-actions", "Bot")], total=60)])
    res = team(gh)
    a = person(res, "alice")["stale"]
    assert a["issues"] == [] and a["unknown_issues"] == [10]
    assert any(u["item"] == "이슈 활동 시각(정체 판정 불능)" for u in res["unknown"])
    assert "오래 머문 이슈 판정 불능" in pr_team.render_team(res)


def test_updated_at_is_never_requested_for_staleness():
    assert "updatedAt" not in pr_team._OPEN_META and "updatedAt" not in pr_team._ISSUES


# --- 팀 별칭 파일 ---------------------------------------------------------------------

ALIASES = "별칭:\n  홍길동: hong-gd   # 원장에 적힌 이름 → GitHub 아이디\n"


def _alias_gh(aliases, ledger_text=LEDGER.replace("| carol |", "| 홍길동 |"), **kw):
    return TeamGh([pr(1, author="hong-gd")], meta={}, aliases=aliases, ledger={"audit/ledger/prog.md": ledger_text}, **kw)


def test_alias_merges_real_name_into_the_login_column():
    gh = _alias_gh(ALIASES)
    res = team(gh)
    hong = person(res, "hong-gd")
    assert [d["id"] for d in hong["dev_items"]] == ["DEV-003"] and hong["dev_items"][0]["owner"] == "hong-gd"
    assert "홍길동" not in [p["login"] for p in res["people"]]
    assert res["aliases_applied"] == [{"name": "홍길동", "login": "hong-gd", "items": ["DEV-003"]}]
    assert not any("GitHub 아이디" in w for w in res["warnings"])  # 별칭으로 바꾼 담당은 형식 경고에서 뺀다
    assert pr_team.render_team(res).splitlines()[-1] == "별칭 적용: 홍길동 → hong-gd(DEV-003)"
    assert gh.alias_ref == "main"


def test_alias_lookup_follows_default_branch_and_is_case_insensitive():
    gh = _alias_gh("별칭:\n  HONGGILDONG: hong-gd\n", ledger_text=LEDGER.replace("| carol |", "| honggildong |"), branch="master")
    res = team(gh)
    assert gh.alias_ref == "master" and res["aliases_applied"][0]["login"] == "hong-gd"


def test_without_alias_file_nothing_changes_and_no_warning():
    res = team(_alias_gh(None))
    assert res["aliases_applied"] == []
    assert [w for w in res["warnings"] if "harness-team" in w] == []
    assert "홍길동" in [p["login"] for p in res["people"]]  # 형식 경고는 그대로 난다(별칭이 없으므로)
    assert any("GitHub 아이디 형식" in w for w in res["warnings"])
    assert "별칭 적용" not in pr_team.render_team(res)


def test_alias_file_format_error_warns_and_continues():
    for body in ("별칭: [a, b]\n", "이름: x\n", "별칭: {홍길동: [", "- 하나\n"):
        res = team(_alias_gh(body))
        assert any("harness-team.yaml" in w and "형식 오류" in w for w in res["warnings"]), body
        assert res["aliases_applied"] == [] and res["ledger"]["status"] == "ok"  # 사람 묶기는 계속된다
        assert res["people"]


def test_alias_file_read_failure_warns_and_continues():
    res = team(_alias_gh(GhError("500 서버 오류")))
    assert any("harness-team.yaml" in w and "읽지 못했다" in w for w in res["warnings"])
    assert res["ledger"]["status"] == "ok" and res["aliases_applied"] == []


def test_alias_value_that_is_not_a_login_warns_and_is_not_applied():
    res = team(_alias_gh("별칭:\n  홍길동: 길동 아이디\n  이순신: lee-ss\n"))
    assert any("'홍길동'" in w and "아이디 형식이 아니다" in w for w in res["warnings"])
    assert res["aliases_applied"] == []  # 이순신 은 원장에 없어 적용되지 않았다
    assert "홍길동" in [p["login"] for p in res["people"]]


def test_empty_alias_file_is_no_aliases():
    res = team(_alias_gh(""))
    assert res["aliases_applied"] == [] and not any("harness-team" in w for w in res["warnings"])


# --- 재검토: 스레드 창 · 별칭 읽기 실패 · 계정 형식 -----------------------------------------


def test_threads_beyond_window_with_old_visible_activity_is_unknown():
    meta = {1: {"commit": ago(days=9), "threads": [(ago(days=6), "bob", "User")], "threads_total": 25}}
    res = team(TeamGh([pr(1, author="alice")], meta=meta))
    a = person(res, "alice")["stale"]
    assert a["prs"] == [] and a["unknown_prs"] == [1]
    assert any("PR 활동 시각" in u["item"] and "리뷰 코멘트" in u["reason"] for u in res["unknown"])


def test_threads_beyond_window_with_recent_visible_activity_is_not_stale():
    meta = {1: {"commit": ago(days=9), "threads": [(ago(hours=5), "bob", "User")], "threads_total": 25}}
    a = person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")
    assert a["stale"]["prs"] == [] and a["stale"]["unknown_prs"] == []
    assert a["progress"]["open"][0]["last_activity_kind"] == "review_comment"


def test_threads_within_window_still_decide_stale():
    meta = {1: {"commit": ago(days=9), "threads": [(ago(days=6), "bob", "User")], "threads_total": 1}}
    assert [s["number"] for s in person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["stale"]["prs"]] == [1]


def test_alias_read_failure_is_also_unknown_but_format_errors_are_warnings_only():
    res = team(_alias_gh(GhError("500 서버 오류")))
    assert any(u["item"] == "팀 별칭 파일" and "500" in u["reason"] for u in res["unknown"])
    for body in ("별칭: [a]\n", "별칭:\n  홍길동: 길동 아이디\n"):
        res = team(_alias_gh(body))
        assert not any(u["item"] == "팀 별칭 파일" for u in res["unknown"])
        assert any("harness-team.yaml" in w for w in res["warnings"])
    assert not any(u["item"] == "팀 별칭 파일" for u in team(_alias_gh(None))["unknown"])  # 404 는 별칭 없음


def test_case_only_duplicate_alias_names_warn_and_first_wins():
    res = team(_alias_gh("별칭:\n  Hong: first-id\n  hong: second-id\n", ledger_text=LEDGER.replace("| carol |", "| Hong |")))
    assert any("대소문자만 다른 중복" in w and "first-id" in w for w in res["warnings"])
    assert res["aliases_applied"] == [{"name": "Hong", "login": "first-id", "items": ["DEV-003"]}]


def test_github_login_allows_underscore_for_managed_users():
    assert pr_team.GITHUB_LOGIN.fullmatch("hong_acme") and pr_team.GITHUB_LOGIN.fullmatch("a-b_c")
    assert not pr_team.GITHUB_LOGIN.fullmatch("홍길동") and not pr_team.GITHUB_LOGIN.fullmatch("-abc") and not pr_team.GITHUB_LOGIN.fullmatch("a--b")
    res = team(TeamGh([pr(1, author="alice")], meta={}, ledger={"audit/ledger/prog.md": LEDGER.replace("| carol |", "| hong_acme |")}))
    assert not any("GitHub 아이디 형식" in w for w in res["warnings"])


def test_bot_names_limited_to_confirmed_accounts():
    assert pr_team.BOT_LOGINS == {"github-actions", "dependabot"}
    meta = {1: {"commit": ago(days=9), "comments": [(ago(hours=1), "claude", "User"), (ago(hours=2), "copilot", "User")]}}
    o = person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["progress"]["open"][0]
    assert o["last_activity_kind"] == "comment"  # 같은 이름의 사람 계정은 봇으로 빼지 않는다
    meta = {1: {"commit": ago(days=9), "comments": [(ago(hours=1), "claude", "Bot"), (ago(hours=2), "copilot[bot]", "User")]}}
    assert person(team(TeamGh([pr(1, author="alice")], meta=meta)), "alice")["stale"]["prs"]  # __typename·접미사로는 잡힌다
