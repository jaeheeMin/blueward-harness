"""병합 순서를 PR 코멘트·커밋 status·차례 알림으로 남기는 엔진(#370 3단계). gh 는 가짜 클라이언트로 바꾼다."""
from __future__ import annotations

import argparse
import json

from checker import pr_queue_actions as qa
from checker.pr_queue import BOT_LOGIN
from checker.ssot_approval import GhError
from checker.tests.test_pr_queue import FakeGh, bad, by_number, pr

REPO = "o/r"


class ActionsGh(FakeGh):
    """FakeGh 에 쓰기(코멘트·status)를 더했다. 코멘트는 저장해 두고 다음 실행에서 다시 읽는다."""

    def __init__(self, prs, merged=(), fail_write=None, **kw):
        super().__init__(prs, **kw)
        self.store: dict[int, list[dict]] = {}
        self.statuses: dict[str, list[dict]] = {}
        self.merged = set(merged)
        self.writes: list[tuple] = []
        self.fail_write = fail_write
        self.fail_turn_post = False  # 차례 알림 코멘트 POST 만 실패시킨다
        self.fail_pull_read = False  # pulls/<n> 읽기를 실패시킨다
        self._next_id = 1

    def _post_comment(self, n, body):
        self.store.setdefault(n, []).append({"id": self._next_id, "user": {"login": BOT_LOGIN}, "body": body})
        self._next_id += 1

    def get_all(self, path):
        if "/issues/" in path and path.endswith("/comments"):
            self.calls.append([path])
            return [dict(c) for c in self.store.get(int(path.split("/issues/")[1].split("/")[0]), [])]
        return super().get_all(path)

    def get_json(self, path):
        if path.endswith("/status") and "/commits/" in path:
            return {"statuses": self.statuses.get(path.split("/commits/")[1].split("/")[0], [])}
        if "/pulls/" in path:
            if self.fail_pull_read:
                raise GhError("pulls 읽기 실패")
            n = int(path.rsplit("/", 1)[1])
            return {"merged": n in self.merged, "title": f"제목 {n}"}
        return super().get_json(path)

    def run(self, args):
        if args[:1] != ["api"]:
            return super().run(args)
        method = args[args.index("-X") + 1]
        path = args[args.index("-X") + 2]
        fields = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if "=" in a and not a.startswith("repos/")}
        self.writes.append((method, path, fields))
        if self.fail_write:
            raise GhError(self.fail_write)
        if self.fail_turn_post and method == "POST" and qa.TURN_MARKER in fields.get("body", ""):
            raise GhError("turn post 실패")
        if path.endswith("/comments"):
            self._post_comment(int(path.split("/issues/")[1].split("/")[0]), fields["body"])
            return json.dumps({"id": self._next_id - 1})
        elif "/issues/comments/" in path:
            cid = int(path.rsplit("/", 1)[1])
            for comments in self.store.values():
                for c in comments:
                    if c["id"] == cid:
                        c["body"] = fields["body"]
        elif "/statuses/" in path:
            sha = path.rsplit("/", 1)[1]
            self.statuses[sha] = [
                {"context": fields["context"], "state": fields["state"], "description": fields["description"]}
            ]
        return ""


def run_apply(gh, webhook="", teams=None, write=True):
    result = qa.pr_queue.compute(gh, REPO)
    sent: list[dict] = []
    report = qa.apply(gh, REPO, result, write=write, webhook=webhook, teams=teams or (lambda url, payload: sent.append(payload)))
    return result, report, sent


def status_writes(gh):
    return [w for w in gh.writes if "/statuses/" in w[1]]


def two_prs():
    return [pr(1), pr(2, author="kim", body="먼저: #1")]


# --- 코멘트·status 내용 -------------------------------------------------------


def test_comment_body_has_order_before_pr_state_and_next():
    gh = ActionsGh(two_prs())
    result, report, _ = run_apply(gh)
    body = gh.store[2][0]["body"]
    assert qa.MARKER in body
    assert "**2번째** (열린 PR 2개 중)" in body
    assert "[#1](https://github.com/o/r/pull/1) 제목 1 — 본문의 먼저: 줄" in body
    assert "지금 상태: 병합 가능" in body
    assert "다음 할 일: 앞의 PR 이 병합된 뒤 병합하기" in body
    first = gh.store[1][0]["body"]
    assert "**1번째**" in first and "앞에 병합할 PR: 없음" in first
    assert report.comments == {"created": 2, "updated": 0, "unchanged": 0}


def test_unchanged_content_is_not_written_again():
    gh = ActionsGh(two_prs())
    run_apply(gh)
    gh.writes.clear()
    _, report, _ = run_apply(gh)
    assert gh.writes == []
    assert report.comments == {"created": 0, "updated": 0, "unchanged": 2}
    assert report.statuses == {"written": 0, "unchanged": 2}


def test_changed_state_updates_the_same_comment_not_a_new_one():
    gh = ActionsGh(two_prs())
    run_apply(gh)
    gh.prs[1]["statusCheckRollup"] = [bad("doc-guard / check")]
    _, report, _ = run_apply(gh)
    assert len(gh.store[2]) == 1
    assert "검사 실패" in gh.store[2][0]["body"]
    assert report.comments["updated"] == 1 and report.comments["unchanged"] == 1
    assert any(w[0] == "PATCH" for w in gh.writes)


def test_closed_prs_are_not_touched():
    gh = ActionsGh([pr(1)])
    run_apply(gh)
    assert set(gh.store) == {1}  # 목록에 없는 PR(닫힘)에는 어떤 호출도 없다
    assert all("/issues/2" not in w[1] for w in gh.writes)


def test_status_failure_when_a_pr_is_before_success_otherwise():
    gh = ActionsGh(two_prs())
    run_apply(gh)
    assert gh.statuses["sha1"] == [{"context": "merge-order", "state": "success", "description": "앞에 병합할 PR 없음"}]
    assert gh.statuses["sha2"][0]["state"] == "failure"
    assert gh.statuses["sha2"][0]["description"].startswith("#1 먼저 병합")
    posted = [w for w in status_writes(gh) if w[1].endswith("/sha2")][0]
    assert posted[2]["context"] == "merge-order"


def test_status_description_is_at_most_140_chars():
    prs = [pr(i) for i in range(1, 40)] + [pr(100, body="먼저: " + ", ".join(f"#{i}" for i in range(1, 40)))]
    gh = ActionsGh(prs)
    run_apply(gh)
    assert all(len(s[0]["description"]) <= qa.DESCRIPTION_LIMIT for s in gh.statuses.values())


def test_cycle_gives_error_status_not_success():
    prs = [pr(1, body="먼저: #2"), pr(2, body="먼저: #1"), pr(3)]
    gh = ActionsGh(prs)
    result, _, _ = run_apply(gh)
    assert gh.statuses["sha1"][0]["state"] == "error"
    assert "순환" in gh.statuses["sha1"][0]["description"]
    assert gh.statuses["sha3"][0]["state"] == "success"
    assert "판정 불능" in gh.store[1][0]["body"]
    assert "after=?" in gh.store[1][0]["body"]


def test_unread_plugin_version_gives_error_for_plugin_prs_only():
    pj = "plugins/harness/.claude-plugin/plugin.json"
    prs = [pr(1, files=(pj,)), pr(2, files=("b.py",))]
    gh = ActionsGh(prs, versions={})  # version 을 못 읽는다
    run_apply(gh)
    assert gh.statuses["sha1"][0]["state"] == "error"
    assert gh.statuses["sha2"][0]["state"] == "success"


def test_truncated_list_gives_error_not_success():
    result = {"prs": [], "truncated": True}
    item = {"number": 1, "order": 1, "after": [], "notes": [], "version": None}
    assert qa.decide_status(item, {**result, "prs": [item]})[0] == "error"


# --- 차례 알림 ----------------------------------------------------------------


def test_turn_notice_when_the_pr_before_is_merged():
    gh = ActionsGh(two_prs(), merged={1})
    run_apply(gh)  # 병합 전: 코멘트에 "앞: #1" 이 숨어 있다
    gh.prs = [gh.prs[1]]  # #1 이 병합돼 열린 목록에서 사라졌다
    _, report, sent = run_apply(gh, webhook="https://hook")
    mention = [c for c in gh.store[2] if qa.TURN_MARKER in c["body"]]
    assert len(mention) == 1
    assert mention[0]["body"].splitlines()[1].startswith(
        "@kim 이제 [#2](https://github.com/o/r/pull/2) 이 병합할 차례"
    )
    assert "[#1](https://github.com/o/r/pull/1)(제목 1)" in mention[0]["body"]
    assert len(sent) == 1
    card = json.dumps(sent[0], ensure_ascii=False)
    assert "PR [#2](https://github.com/o/r/pull/2): 이제 병합할 차례" in card
    assert "[#1](https://github.com/o/r/pull/1)" in card  # 병합된 앞 PR
    assert sent[0]["attachments"][0]["content"]["actions"][0]["url"] == "https://github.com/o/r/pull/2"
    assert report.notified and "Teams" in report.notified[0]
    # 마커 코멘트는 갱신돼 앞 PR 이 비었다
    marker = [c for c in gh.store[2] if qa.MARKER in c["body"]][0]
    assert "after=-->" not in marker["body"] and "<!-- pr-queue:after= -->" in marker["body"]
    # 다음 실행은 같은 알림을 되풀이하지 않는다
    gh.writes.clear()
    _, report2, sent2 = run_apply(gh, webhook="https://hook")
    assert sent2 == [] and report2.notified == []
    assert gh.writes == []


def test_no_turn_notice_when_the_pr_before_was_closed_without_merge():
    gh = ActionsGh(two_prs(), merged=set())
    run_apply(gh)
    gh.prs = [gh.prs[1]]
    _, report, sent = run_apply(gh, webhook="https://hook")
    assert sent == [] and report.notified == []
    assert not any(qa.TURN_MARKER in c["body"] for c in gh.store[2])


def test_no_turn_notice_while_another_pr_is_still_before():
    prs = [pr(1), pr(2), pr(3, body="먼저: #1, #2")]
    gh = ActionsGh(prs, merged={1})
    run_apply(gh)
    gh.prs = prs[1:]
    _, report, _ = run_apply(gh)
    assert report.notified == []


def test_first_run_without_previous_comment_does_not_notify():
    gh = ActionsGh([pr(2)])
    _, report, sent = run_apply(gh, webhook="https://hook")
    assert report.notified == [] and sent == []


def test_turn_notice_without_webhook_skips_teams_and_says_so():
    gh = ActionsGh(two_prs(), merged={1})
    run_apply(gh)
    gh.prs = [gh.prs[1]]
    _, report, sent = run_apply(gh, webhook="")
    assert sent == []
    assert any(qa.TURN_MARKER in c["body"] for c in gh.store[2])
    assert any("TEAMS_PLUGIN_ALERT_WEBHOOK" in s for s in report.skipped)


def test_teams_failure_is_a_warning_and_the_comment_notice_stays():
    def boom(url, payload):
        raise OSError("HTTP 500")

    gh = ActionsGh(two_prs(), merged={1})
    run_apply(gh)
    gh.prs = [gh.prs[1]]
    _, report, _ = run_apply(gh, webhook="https://secret-hook", teams=boom)
    assert report.write_errors == []
    assert any("Teams 전송 실패" in s for s in report.skipped)
    assert not any("secret-hook" in s for s in report.skipped)


# --- 읽기·쓰기 실패와 CLI -----------------------------------------------------


def _args(tmp_path, event=None):
    summary = tmp_path / "summary.md"
    return argparse.Namespace(repo=REPO, event_path=str(event) if event else None, summary_file=str(summary)), summary


def test_cannot_read_github_fails_with_reason_in_summary(tmp_path):
    args, summary = _args(tmp_path)
    code = qa.run(args, client=ActionsGh([], fail="gh api 실패"))
    assert code == qa.EXIT_CANNOT_READ
    text = summary.read_text(encoding="utf-8")
    assert "PR 순서 확인 불능" in text and "gh api 실패" in text and "통과로 보지 않는다" in text


def test_unexpected_error_is_cannot_read_too(tmp_path):
    class Boom(ActionsGh):
        def run(self, args):
            raise ValueError("x")

    args, summary = _args(tmp_path)
    assert qa.run(args, client=Boom([pr(1)])) == qa.EXIT_CANNOT_READ
    assert "ValueError" in summary.read_text(encoding="utf-8")


def test_write_failure_exits_1_and_names_the_reason(tmp_path):
    args, summary = _args(tmp_path)
    code = qa.run(args, client=ActionsGh([pr(1)], fail_write="403 Resource not accessible"))
    assert code == qa.EXIT_WRITE_FAILED
    text = summary.read_text(encoding="utf-8")
    assert "쓰기 실패" in text and "403" in text and "statuses: write" in text


def test_success_exit_0_and_summary_counts(tmp_path):
    args, summary = _args(tmp_path)
    assert qa.run(args, client=ActionsGh(two_prs())) == qa.EXIT_OK
    text = summary.read_text(encoding="utf-8")
    assert "코멘트: 만듦 2" in text and "merge-order status: 씀 2" in text


def test_comment_read_failure_is_cannot_read(tmp_path):
    gh = ActionsGh([pr(1)], comments={})
    gh.get_all = lambda path: (_ for _ in ()).throw(GhError("읽기 실패")) if "/comments" in path else []
    args, _ = _args(tmp_path)
    assert qa.run(args, client=gh) == qa.EXIT_CANNOT_READ


def test_fork_pr_event_writes_nothing_but_still_reports(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"repo": {"full_name": "fork/r"}}}}), encoding="utf-8")
    args, summary = _args(tmp_path, event)
    gh = ActionsGh(two_prs())
    assert qa.run(args, client=gh) == qa.EXIT_OK
    assert gh.writes == []
    text = summary.read_text(encoding="utf-8")
    assert "쓰지 않음" in text and "포크" in text and "| #2 |" in text


def test_same_repo_pr_event_writes(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"head": {"repo": {"full_name": "O/R"}}}}), encoding="utf-8")
    assert qa.fork_reason(str(event), REPO) is None
    assert qa.fork_reason(None, REPO) is None
    assert qa.fork_reason(str(tmp_path / "없음.json"), REPO) is None


def _after_of(gh, n):
    return qa.previous_after_mark(gh.store[n])


def _turn_ready(webhook="https://hook"):
    """#1 이 병합돼 #2 의 차례가 된 상태까지 만든 가짜 gh(아직 알림 전)."""
    gh = ActionsGh(two_prs(), merged={1})
    run_apply(gh)
    gh.prs = [gh.prs[1]]
    return gh


def test_turn_comment_post_failure_keeps_previous_after_and_retries_next_run():
    gh = _turn_ready()
    gh.fail_turn_post = True
    _, report, sent = run_apply(gh, webhook="https://hook")
    assert any("차례 알림 코멘트" in e for e in report.write_errors)
    assert _after_of(gh, 2) == "1"  # 비우지 않고 이전 값을 유지
    assert sent == []
    gh.fail_turn_post = False
    _, report2, sent2 = run_apply(gh, webhook="https://hook")
    assert any(qa.TURN_MARKER in c["body"] for c in gh.store[2])
    assert len(sent2) == 1 and report2.notified
    assert _after_of(gh, 2) == ""


def test_merged_read_failure_keeps_previous_after_and_retries_next_run():
    gh = _turn_ready()
    gh.fail_pull_read = True
    _, report, sent = run_apply(gh, webhook="https://hook")
    assert sent == [] and report.notified == []
    assert _after_of(gh, 2) == "1"
    gh.fail_pull_read = False
    _, report2, sent2 = run_apply(gh, webhook="https://hook")
    assert len(sent2) == 1 and report2.notified
    assert _after_of(gh, 2) == ""


def test_closed_without_merge_still_clears_after():
    gh = ActionsGh(two_prs(), merged=set())
    run_apply(gh)
    gh.prs = [gh.prs[1]]
    run_apply(gh, webhook="https://hook")
    assert _after_of(gh, 2) == ""


def test_teams_failure_is_retried_alone_and_then_marked_sent():
    gh = _turn_ready()
    calls: list[dict] = []

    def flaky(url, payload):
        calls.append(payload)
        if len(calls) == 1:
            raise OSError("HTTP 500")

    _, report, _ = run_apply(gh, webhook="https://hook", teams=flaky)
    turn = [c for c in gh.store[2] if qa.TURN_MARKER in c["body"]]
    assert len(turn) == 1 and qa.TEAMS_SENT not in turn[0]["body"]
    assert any("Teams 전송 실패" in s for s in report.skipped)
    # 다음 실행: 알림 코멘트는 새로 쓰지 않고 Teams 만 다시 보낸다
    gh.writes.clear()
    _, report2, _ = run_apply(gh, webhook="https://hook", teams=flaky)
    assert len(calls) == 2
    turn = [c for c in gh.store[2] if qa.TURN_MARKER in c["body"]]
    assert len(turn) == 1 and qa.TEAMS_SENT in turn[0]["body"]
    assert not any(w[0] == "POST" and w[1].endswith("/comments") for w in gh.writes)
    # 그다음 실행은 아무것도 다시 보내지 않는다
    _, _, _ = run_apply(gh, webhook="https://hook", teams=flaky)
    assert len(calls) == 2


def test_turn_comment_made_without_webhook_never_sends_teams_later():
    gh = _turn_ready()
    run_apply(gh, webhook="")
    sent: list[dict] = []
    run_apply(gh, webhook="https://hook", teams=lambda url, payload: sent.append(payload))
    assert sent == []


def test_turn_marker_from_a_non_bot_comment_does_not_block_the_notice():
    gh = _turn_ready()
    gh.store[2].append({"id": 99, "user": {"login": "mallory"}, "body": "<!-- pr-queue-turn:1 -->"})
    _, report, sent = run_apply(gh, webhook="https://hook")
    assert len(sent) == 1 and report.notified
    assert any(c["user"]["login"] == BOT_LOGIN and qa.TURN_MARKER in c["body"] for c in gh.store[2])


def test_teams_failure_summary_has_no_webhook_value_even_in_exception_message():
    secret = "https://secret-hook.example/abc"

    def boom(url, payload):
        raise ValueError(f"bad url {url}")

    gh = _turn_ready()
    _, report, _ = run_apply(gh, webhook=secret, teams=boom)
    text = report.render(REPO, None)
    assert secret not in text and "secret-hook" not in text
    assert any("ValueError" in s for s in report.skipped)


def test_post_teams_raises_only_the_kind_never_the_url(monkeypatch):
    import urllib.error
    import urllib.request

    secret = "https://secret-hook.example/abc"

    def raising(exc):
        def fake(req, timeout=0):
            raise exc

        return fake

    cases = [
        (urllib.error.HTTPError(secret, 500, f"err {secret}", {}, None), "HTTP 500"),
        (urllib.error.URLError(f"cannot reach {secret}"), "URLError"),
        (ValueError(f"weird {secret}"), "ValueError"),
    ]
    for exc, expected in cases:
        monkeypatch.setattr(urllib.request, "urlopen", raising(exc))
        try:
            qa.post_teams(secret, {})
        except qa.TeamsError as caught:
            assert caught.reason == expected
            assert secret not in str(caught) and secret not in repr(caught)
        else:
            raise AssertionError("TeamsError 가 나야 한다")
    # URL 모양이 아닌 값은 Request 생성에서 ValueError 가 나는데 그 메시지에도 값이 들어 있다
    monkeypatch.undo()
    try:
        qa.post_teams("not-a-url-secret", {})
    except qa.TeamsError as caught:
        assert "not-a-url-secret" not in str(caught) and caught.reason == "ValueError"


def test_untrusted_strings_are_defused_in_the_comment():
    prs = [pr(1, title="@everyone <script>alert(1)</script> `x`"), pr(2, body="먼저: #1")]
    gh = ActionsGh(prs)
    gh.prs[1]["statusCheckRollup"] = [bad("@org/team <b>x</b> `y`")]
    run_apply(gh)
    body = gh.store[2][0]["body"]
    assert "@everyone" not in body and "@org/team" not in body
    assert "@​everyone" in body
    assert "<script>" not in body and "<b>" not in body
    assert "&lt;script&gt;" in body and "&lt;b&gt;" in body
    assert "\\`x\\`" in body


def test_turn_body_defuses_titles_and_next():
    item = {"number": 2, "author": "kim", "state": "병합 가능", "detail": "@a <i>", "next": "@b `c`"}
    text = qa.turn_body(item, [1], {1: "@evil <u>t</u>"}, REPO)
    assert "@evil" not in text and "@a" not in text and "@b" not in text
    assert "<u>" not in text and "<i>" not in text
    assert text.splitlines()[1].startswith("@kim ")


def test_titles_cannot_forge_links():
    title = "[#1](https://evil.example) 승인됨"
    item = {"number": 2, "author": "kim", "state": "병합 가능", "detail": "[d](https://evil.example)",
            "next": "[n](https://evil.example)", "title": title}
    text = qa.turn_body(item, [1], {1: title}, REPO)
    assert "[#1](https://evil" not in text and "[d](https://evil" not in text and "[n](https://evil" not in text
    assert "\\[#1\\]" in text
    details = qa.teams_payload(item, [1], REPO)["attachments"][0]["content"]["body"][1]["text"]
    assert "[#1](https://evil" not in details and "[d](https://evil" not in details
    assert "[n](https://evil" not in details and "\\[#1\\]" in details


def test_dependabot_event_writes_nothing(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"sender": {"login": "dependabot[bot]"}, "pull_request": {"head": {"repo": {"full_name": REPO}}}}),
        encoding="utf-8",
    )
    assert "dependabot[bot]" in (qa.fork_reason(str(event), REPO) or "")
    args, summary = _args(tmp_path, event)
    gh = ActionsGh(two_prs())
    assert qa.run(args, client=gh) == qa.EXIT_OK
    assert gh.writes == []
    assert "쓰지 않음" in summary.read_text(encoding="utf-8")


def test_unexpected_error_inside_apply_is_exit_2_not_write_failure(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise KeyError("x")

    monkeypatch.setattr(qa, "apply", boom)
    args, summary = _args(tmp_path)
    code = qa.run(args, client=ActionsGh(two_prs()))
    assert code == qa.EXIT_UNEXPECTED == 2 and code != qa.EXIT_WRITE_FAILED
    assert "PR 순서 처리 중 예상 못 한 오류 KeyError" in summary.read_text(encoding="utf-8")


def test_comment_says_updates_come_on_events_and_points_to_prs_skill():
    gh = ActionsGh(two_prs())
    run_apply(gh)
    body = gh.store[2][0]["body"]
    assert "바뀔 때마다" not in body
    assert "이벤트 때 갱신" in body and "/harness:prs" in body


def test_compute_gives_head_sha_and_unread_versions():
    gh = ActionsGh(two_prs())
    result = qa.pr_queue.compute(gh, REPO)
    assert by_number(result)[2]["after"] == [1] and by_number(result)[2]["sha"] == "sha2"
    assert result["unread_versions"] == []
