"""`checker.ssot_approval` 을 검증한다(#49).

순수 함수(`touches_ssot`, `load_approvers`, `is_approved`)는 `gh` 없이 그대로
부른다. CLI(`cmd_check_pr`, `cmd_check_commit`)는 `GhClient` 대신 fake 를
심어(monkeypatch) 네트워크 없이 종료코드 0/1/2 를 확인한다 — 실제 `gh` 호출은
`checker/tests/test_hook.py` 같은 통합 테스트의 몫이 아니라, 이 파일에서는
아예 발생하지 않는다.
"""
from __future__ import annotations

import json

import pytest

from checker import ssot_approval as mod
from checker.ssot_approval import (
    EXIT_NOT_APPROVED,
    EXIT_OK,
    EXIT_UNKNOWN,
    GhError,
    is_approved,
    load_approvers,
    touches_ssot,
)

# --- touches_ssot ------------------------------------------------------------


def test_touches_ssot_는_docs_ssot_아래만_본다():
    assert touches_ssot(["docs/ssot/PRD.md"]) is True
    assert touches_ssot(["README.md", "docs/ssot/PRD.md"]) is True
    assert touches_ssot(["docs/spec/DEV-001.md"]) is False
    assert touches_ssot([]) is False


def test_touches_ssot_는_역슬래시_경로도_본다():
    # Windows 러너나 gh api 응답에 역슬래시가 섞여 들어올 가능성을 대비한다.
    assert touches_ssot(["docs\\ssot\\PRD.md"]) is True


# --- load_approvers ----------------------------------------------------------


def test_load_approvers_는_주석과_빈_줄을_무시한다():
    text = "# 주석\n\nalice\n@bob\n  # 다른 주석\ncharlie # 뒤 주석\n"
    assert load_approvers(text) == {"alice", "bob", "charlie"}


def test_load_approvers_는_대소문자를_구분하지_않는다():
    assert load_approvers("Alice\n") == {"alice"}


def test_load_approvers_빈_내용은_빈_집합():
    assert load_approvers("") == set()
    assert load_approvers(None) == set()
    assert load_approvers("# 주석뿐\n\n") == set()


# --- is_approved ---------------------------------------------------------


def _review(login: str, state: str, submitted_at: str, commit_id: str | None = None) -> dict:
    review = {"user": {"login": login}, "state": state, "submitted_at": submitted_at}
    if commit_id is not None:
        review["commit_id"] = commit_id
    return review


def test_리뷰가_없으면_승인되지_않았다():
    approved, reason = is_approved("author", [], set())
    assert approved is False


def test_작성자_자신의_승인은_인정하지_않는다():
    reviews = [_review("author", "APPROVED", "2026-01-01T00:00:00Z")]
    approved, reason = is_approved("author", reviews, set())
    assert approved is False


def test_작성자가_아닌_사람이_승인하면_인정한다():
    reviews = [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z")]
    approved, reason = is_approved("author", reviews, set())
    assert approved is True
    assert "reviewer" in reason


def test_나중의_changes_requested가_앞선_approved를_취소한다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z"),
        _review("reviewer", "CHANGES_REQUESTED", "2026-01-02T00:00:00Z"),
    ]
    approved, reason = is_approved("author", reviews, set())
    assert approved is False


def test_승인자_목록이_있으면_그중에서만_인정한다():
    reviews = [_review("outsider", "APPROVED", "2026-01-01T00:00:00Z")]
    approved, _ = is_approved("author", reviews, {"insider"})
    assert approved is False

    reviews2 = [_review("insider", "APPROVED", "2026-01-01T00:00:00Z")]
    approved2, _ = is_approved("author", reviews2, {"insider"})
    assert approved2 is True


def test_commented는_상태를_바꾸지_않는다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z"),
        _review("reviewer", "COMMENTED", "2026-01-02T00:00:00Z"),
    ]
    approved, _ = is_approved("author", reviews, set())
    assert approved is True  # COMMENTED 가 APPROVED 를 지우지 않는다


def test_승인자만_있는_commented는_승인이_아니다():
    reviews = [_review("reviewer", "COMMENTED", "2026-01-01T00:00:00Z")]
    approved, _ = is_approved("author", reviews, set())
    assert approved is False


def test_리뷰어_로그인_대소문자를_가리지_않는다():
    reviews = [_review("Reviewer", "APPROVED", "2026-01-01T00:00:00Z")]
    approved, _ = is_approved("Author", reviews, set())
    assert approved is True


# --- is_approved: 새 커밋이 올라오면 옛 승인은 낡는다(#119) ---------------------

HEAD = "bbbbbbb1111111111111111111111111111111bb"
OLD = "aaaaaaa2222222222222222222222222222222aa"


def test_옛_커밋에_대한_승인만_있으면_낡아서_미승인이다():
    reviews = [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", OLD)]
    approved, reason = is_approved("author", reviews, set(), HEAD)
    assert approved is False
    assert "reviewer" in reason
    assert "이전 커밋(aaaaaaa)" in reason
    assert "새 커밋이 올라와 다시 승인이 필요합니다" in reason
    assert "다음: 사람이 할 일" in reason


def test_head_를_안_주면_커밋을_보지_않는다():
    reviews = [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", OLD)]
    approved, _ = is_approved("author", reviews, set())
    assert approved is True


def test_옛_승인_뒤_head_에_다시_승인하면_통과한다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", OLD),
        _review("reviewer", "APPROVED", "2026-01-02T00:00:00Z", HEAD),
    ]
    approved, reason = is_approved("author", reviews, set(), HEAD)
    assert approved is True
    assert "reviewer" in reason


def test_head_에_승인한_뒤_changes_requested_면_미승인이고_낡은_것도_아니다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", HEAD),
        _review("reviewer", "CHANGES_REQUESTED", "2026-01-02T00:00:00Z", HEAD),
    ]
    approved, reason, stale = mod.evaluate_approval("author", reviews, set(), HEAD)
    assert approved is False
    assert stale == []
    assert "이전 커밋" not in reason


def test_head_에_승인한_뒤_commented_는_승인을_지우지_않는다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", HEAD),
        _review("reviewer", "COMMENTED", "2026-01-02T00:00:00Z", HEAD),
    ]
    approved, _ = is_approved("author", reviews, set(), HEAD)
    assert approved is True


def test_옛_승인_뒤_head_에서_commented_만_하면_여전히_낡았다():
    reviews = [
        _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", OLD),
        _review("reviewer", "COMMENTED", "2026-01-02T00:00:00Z", HEAD),
    ]
    approved, _ = is_approved("author", reviews, set(), HEAD)
    assert approved is False


def test_한_사람의_옛_승인과_다른_사람의_head_승인이_있으면_통과한다():
    reviews = [
        _review("old-one", "APPROVED", "2026-01-01T00:00:00Z", OLD),
        _review("new-one", "APPROVED", "2026-01-02T00:00:00Z", HEAD),
    ]
    approved, reason, stale = mod.evaluate_approval("author", reviews, set(), HEAD)
    assert approved is True
    assert "new-one" in reason
    assert stale == []


def test_작성자의_head_승인은_여전히_인정하지_않는다():
    reviews = [_review("author", "APPROVED", "2026-01-01T00:00:00Z", HEAD)]
    approved, _, stale = mod.evaluate_approval("author", reviews, set(), HEAD)
    assert approved is False
    assert stale == []


def test_작성자의_옛_승인은_낡은_승인으로_세지_않는다():
    reviews = [_review("author", "APPROVED", "2026-01-01T00:00:00Z", OLD)]
    approved, reason, stale = mod.evaluate_approval("author", reviews, set(), HEAD)
    assert approved is False
    assert stale == []
    assert "이전 커밋" not in reason


def test_승인자_목록에_없는_사람의_head_승인은_인정하지_않는다():
    reviews = [_review("outsider", "APPROVED", "2026-01-01T00:00:00Z", HEAD)]
    approved, _, stale = mod.evaluate_approval("author", reviews, {"insider"}, HEAD)
    assert approved is False
    assert stale == []


def test_승인자_목록에_없는_사람의_옛_승인은_낡은_승인으로_세지_않는다():
    reviews = [_review("outsider", "APPROVED", "2026-01-01T00:00:00Z", OLD)]
    approved, reason, stale = mod.evaluate_approval("author", reviews, {"insider"}, HEAD)
    assert approved is False
    assert stale == []
    assert "이전 커밋" not in reason


def test_승인자_목록의_사람이_head_에_승인하면_통과한다():
    reviews = [_review("insider", "APPROVED", "2026-01-01T00:00:00Z", HEAD)]
    approved, _ = is_approved("author", reviews, {"insider"}, HEAD)
    assert approved is True


def test_commit_id_가_없는_승인은_head_와_같다고_볼_수_없어_낡은_것으로_친다():
    reviews = [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z")]
    approved, reason, stale = mod.evaluate_approval("author", reviews, set(), HEAD)
    assert approved is False
    assert stale == [{"login": "reviewer", "commit": None}]


# --- CLI: check-pr -----------------------------------------------------------


class _FakeArgs:
    def __init__(self, repo="owner/repo", pr=1, sha="deadbeef"):
        self.repo = repo
        self.pr = pr
        self.sha = sha


def test_check_pr_는_ssot를_안_건드리면_통과(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "decide_pr", lambda client, repo, pr: {"touches_ssot": False, "approved": True, "reason": "무관"}
    )
    code = mod.cmd_check_pr(_FakeArgs())
    assert code == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["touches_ssot"] is False


def test_check_pr_는_승인되면_통과(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "decide_pr", lambda client, repo, pr: {"touches_ssot": True, "approved": True, "reason": "승인됨"}
    )
    code = mod.cmd_check_pr(_FakeArgs())
    assert code == EXIT_OK


def test_check_pr_는_미승인이면_1(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "decide_pr", lambda client, repo, pr: {"touches_ssot": True, "approved": False, "reason": "승인 없음"}
    )
    code = mod.cmd_check_pr(_FakeArgs())
    assert code == EXIT_NOT_APPROVED
    out = json.loads(capsys.readouterr().out)
    assert out["approved"] is False


def test_check_pr_는_gh_오류면_2(monkeypatch, capsys):
    def _raise(client, repo, pr):
        raise GhError("네트워크가 없다")

    monkeypatch.setattr(mod, "decide_pr", _raise)
    code = mod.cmd_check_pr(_FakeArgs())
    assert code == EXIT_UNKNOWN
    out = json.loads(capsys.readouterr().out)
    assert out["approved"] is None
    assert "네트워크가 없다" in out["reason"]


# --- CLI: check-commit ---------------------------------------------------


def test_check_commit_는_승인됐으면_0(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "decide_commit", lambda client, repo, sha: {"approved": True, "reason": "다 승인됨", "prs": [1]}
    )
    code = mod.cmd_check_commit(_FakeArgs())
    assert code == EXIT_OK


def test_check_commit_는_미승인이면_1(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "decide_commit",
        lambda client, repo, sha: {
            "approved": False,
            "reason": "PR 없이 main 에 직접 들어왔다",
            "prs": [],
        },
    )
    code = mod.cmd_check_commit(_FakeArgs())
    assert code == EXIT_NOT_APPROVED
    out = json.loads(capsys.readouterr().out)
    assert "직접 들어왔다" in out["reason"]


def test_check_commit_는_gh_오류면_2(monkeypatch, capsys):
    def _raise(client, repo, sha):
        raise GhError("API 오류")

    monkeypatch.setattr(mod, "decide_commit", _raise)
    code = mod.cmd_check_commit(_FakeArgs())
    assert code == EXIT_UNKNOWN


# --- decide_pr / decide_commit: fetch_* 를 fake 로 갈아 끼운다 -----------------


def test_decide_pr_는_fetch_함수들을_조합한다(monkeypatch):
    monkeypatch.setattr(
        mod,
        "fetch_pr_info",
        lambda c, r, n: {"user": {"login": "author"}, "base": {"ref": "main"}, "head": {"sha": "head1"}},
    )
    monkeypatch.setattr(mod, "fetch_pr_files", lambda c, r, n: ["docs/ssot/PRD.md"])
    monkeypatch.setattr(
        mod,
        "fetch_pr_reviews",
        lambda c, r, n: [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", "head1")],
    )
    monkeypatch.setattr(mod, "fetch_approvers", lambda c, r, ref: set())

    result = mod.decide_pr(mod.GhClient(), "owner/repo", 1)
    assert result == {"touches_ssot": True, "approved": True, "reason": "reviewer 가 승인했다"}


def test_decide_pr_는_ssot를_안_건드리면_리뷰를_보지_않는다(monkeypatch):
    monkeypatch.setattr(mod, "fetch_pr_info", lambda c, r, n: {"user": {"login": "author"}, "base": {"ref": "main"}})
    monkeypatch.setattr(mod, "fetch_pr_files", lambda c, r, n: ["README.md"])

    def _boom(*a, **k):
        raise AssertionError("호출되면 안 된다")

    monkeypatch.setattr(mod, "fetch_pr_reviews", _boom)
    monkeypatch.setattr(mod, "fetch_approvers", _boom)

    result = mod.decide_pr(mod.GhClient(), "owner/repo", 1)
    assert result["touches_ssot"] is False
    assert result["approved"] is True


def test_decide_commit_는_merge된_pr이_없으면_커밋_파일을_본다(monkeypatch):
    monkeypatch.setattr(mod, "fetch_commit_associated_prs", lambda c, r, s: [])
    monkeypatch.setattr(mod, "fetch_commit_files", lambda c, r, s: ["docs/ssot/PRD.md"])

    result = mod.decide_commit(mod.GhClient(), "owner/repo", "sha")
    assert result["approved"] is False
    assert "PR 없이" in result["reason"]


def test_decide_commit_는_merge된_pr이_미승인이면_실패(monkeypatch):
    monkeypatch.setattr(
        mod,
        "fetch_commit_associated_prs",
        lambda c, r, s: [{"number": 7, "merged_at": "2026-01-01T00:00:00Z", "html_url": "https://x/7"}],
    )
    monkeypatch.setattr(
        mod, "decide_pr", lambda c, r, n: {"touches_ssot": True, "approved": False, "reason": "승인 없음"}
    )

    result = mod.decide_commit(mod.GhClient(), "owner/repo", "sha")
    assert result["approved"] is False
    assert result["prs"][0]["pr"] == 7


def test_decide_commit_는_merge된_pr이_승인됐으면_통과(monkeypatch):
    monkeypatch.setattr(
        mod,
        "fetch_commit_associated_prs",
        lambda c, r, s: [{"number": 7, "merged_at": "2026-01-01T00:00:00Z", "html_url": "https://x/7"}],
    )
    monkeypatch.setattr(
        mod, "decide_pr", lambda c, r, n: {"touches_ssot": True, "approved": True, "reason": "승인됨"}
    )

    result = mod.decide_commit(mod.GhClient(), "owner/repo", "sha")
    assert result["approved"] is True


def _client_for_pr(reviews, head_sha="bbbbbbb1111"):
    return _FakeClient(
        {
            "repos/o/r/pulls/7": {
                "user": {"login": "author"},
                "base": {"ref": "main"},
                "head": {"sha": head_sha},
            },
            "repos/o/r/pulls/7/files": [{"filename": "docs/ssot/PRD.md"}],
            "repos/o/r/pulls/7/reviews": reviews,
            "repos/o/r/contents/.github/ssot-approvers?ref=main": None,
        }
    )


def test_decide_pr_는_옛_커밋_승인이면_stale_approvers_를_담아_미승인으로_답한다():
    client = _client_for_pr([_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", "aaaaaaa9999")])
    result = mod.decide_pr(client, "o/r", 7)
    assert result["touches_ssot"] is True
    assert result["approved"] is False
    assert result["stale_approvers"] == ["reviewer"]
    assert "이전 커밋(aaaaaaa)" in result["reason"]


def test_decide_pr_는_head_에_다시_승인하면_통과한다():
    client = _client_for_pr(
        [
            _review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", "aaaaaaa9999"),
            _review("reviewer", "APPROVED", "2026-01-02T00:00:00Z", "bbbbbbb1111"),
        ]
    )
    result = mod.decide_pr(client, "o/r", 7)
    assert result == {"touches_ssot": True, "approved": True, "reason": "reviewer 가 승인했다"}


def test_decide_pr_는_head_를_모르면_통과시키지_않고_판정_불가로_답한다():
    client = _client_for_pr([_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", "x")])
    client.responses["repos/o/r/pulls/7"] = {"user": {"login": "author"}, "base": {"ref": "main"}}
    with pytest.raises(GhError):
        mod.decide_pr(client, "o/r", 7)


def test_decide_commit_는_merge_시점_head_에_대한_승인만_인정한다():
    # merge 된 PR 의 head.sha 는 merge 시점의 마지막 커밋이다.
    client = _client_for_pr([_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z", "aaaaaaa9999")])
    client.responses["repos/o/r/commits/msha/pulls"] = [
        {"number": 7, "merged_at": "2026-01-03T00:00:00Z", "html_url": "https://x/7"}
    ]
    result = mod.decide_commit(client, "o/r", "msha")
    assert result["approved"] is False
    assert result["prs"][0]["pr"] == 7
    assert "이전 커밋" in result["prs"][0]["reason"]

    client.responses["repos/o/r/pulls/7/reviews"].append(
        _review("reviewer", "APPROVED", "2026-01-02T00:00:00Z", "bbbbbbb1111")
    )
    assert mod.decide_commit(client, "o/r", "msha")["approved"] is True


# --- 재사용 워크플로 권한 ------------------------------------------------------


def test_after_merge_job_은_판정에_필요한_읽기_권한을_가진다():
    """job 에 permissions 를 적으면 빠진 권한은 none 이 된다. issues 만 주면
    commits/{sha}/pulls 조회가 403 으로 막혀 사후 감지가 판정 불가로 끝난다(#77)."""
    from pathlib import Path

    import yaml

    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ssot-approval.yml"
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    permissions = jobs["after-merge"]["permissions"]

    assert permissions.get("contents") in ("read", "write")
    assert permissions.get("pull-requests") in ("read", "write")
    assert permissions.get("issues") == "write"


# --- 사람이 merge 해야 하는 경로(#104) -----------------------------------------


def test_load_human_merge_paths_는_주석과_빈_줄을_무시한다():
    text = "# 설명\n\nplugins/\n  checker/  # 엔진\n\\.github\\\n"
    assert mod.load_human_merge_paths(text) == ["plugins/", "checker/", ".github/"]


def test_load_human_merge_paths_빈_내용은_빈_목록():
    assert mod.load_human_merge_paths("") == []
    assert mod.load_human_merge_paths(None) == []
    assert mod.load_human_merge_paths("# 주석뿐\n") == []


def test_human_merge_hits_는_접두어_아래_파일만_돌려준다():
    files = ["README.md", "plugins/harness/a.sh", "checker/x.py", "docs/plugins/a.md"]
    assert mod.human_merge_hits(files, ["plugins/", "checker/"]) == [
        "plugins/harness/a.sh",
        "checker/x.py",
    ]


def test_human_merge_hits_는_역슬래시와_앞_슬래시를_정규화한다():
    files = ["plugins\\harness\\a.sh", "/checker/x.py"]
    assert mod.human_merge_hits(files, ["plugins/", "checker/"]) == files


def test_human_merge_hits_목록이_비면_아무것도_걸리지_않는다():
    assert mod.human_merge_hits(["plugins/a"], []) == []


class _FakeClient:
    """`GhClient` 의 읽기 메서드만 흉내 내는 fake. 경로 -> 응답 사전."""

    def __init__(self, responses):
        self.responses = responses
        self.asked = []

    def get_json(self, path):
        self.asked.append(path)
        return self.responses[path]

    def get_all(self, path, per_page=100):
        self.asked.append(path)
        return self.responses[path]

    def get_json_or_none_404(self, path):
        self.asked.append(path)
        return self.responses.get(path)


def _human_client(list_text, files):
    import base64

    responses = {
        "repos/o/r/pulls/5": {"base": {"ref": "main"}},
        "repos/o/r/pulls/5/files": [{"filename": f} for f in files],
    }
    if list_text is not None:
        content = base64.b64encode(list_text.encode("utf-8")).decode("ascii")
        responses["repos/o/r/contents/.github/human-merge-paths?ref=main"] = {"content": content}
    return _FakeClient(responses)


def test_decide_human_merge_는_보호_경로를_바꾸면_사람이_필요하다():
    client = _human_client("plugins/\n", ["README.md", "plugins/harness/a.sh"])
    result = mod.decide_human_merge(client, "o/r", 5)
    assert result == {
        "requires_human": True,
        "paths": ["plugins/harness/a.sh"],
        "pr": 5,
        "repo": "o/r",
    }
    # 목록은 head 가 아니라 base 브랜치에서 읽는다.
    assert any("human-merge-paths?ref=main" in p for p in client.asked)


def test_decide_human_merge_는_보호_경로를_안_바꾸면_사람이_필요없다():
    client = _human_client("plugins/\n", ["README.md"])
    assert mod.decide_human_merge(client, "o/r", 5)["requires_human"] is False


def test_decide_human_merge_는_목록_파일이_없으면_제한이_없다():
    client = _human_client(None, ["plugins/harness/a.sh"])
    result = mod.decide_human_merge(client, "o/r", 5)
    assert result["requires_human"] is False
    assert result["paths"] == []


def test_check_human_merge_종료코드(monkeypatch, capsys):
    monkeypatch.setattr(
        mod, "decide_human_merge",
        lambda c, r, n: {"requires_human": False, "paths": [], "pr": n, "repo": r},
    )
    assert mod.cmd_check_human_merge(_FakeArgs()) == EXIT_OK

    monkeypatch.setattr(
        mod, "decide_human_merge",
        lambda c, r, n: {"requires_human": True, "paths": ["plugins/a"], "pr": n, "repo": r},
    )
    assert mod.cmd_check_human_merge(_FakeArgs()) == mod.EXIT_HUMAN_REQUIRED == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["requires_human"] is True


def test_check_human_merge_는_gh_오류를_통과로_뭉개지_않고_2(monkeypatch, capsys):
    def _raise(c, r, n):
        raise GhError("네트워크가 없다")

    monkeypatch.setattr(mod, "decide_human_merge", _raise)
    assert mod.cmd_check_human_merge(_FakeArgs()) == EXIT_UNKNOWN
    out = json.loads(capsys.readouterr().out)
    assert out["requires_human"] is None


# --- GhClient 의 "파일 없음" 판정은 HTTP 404 로만 한다(#129) ---------------------

import subprocess  # noqa: E402

_SHA_404 = "a4041b2c3d4e5f60718293a4b5c6d7e8f9012340"  # 40자리 SHA 에 "404" 가 든다
_CONTENTS = f"repos/o/r/contents/.github/risk-gate.yaml?ref={_SHA_404}"


def _fake_gh(monkeypatch, *, returncode=1, stderr="", stdout="", exc=None):
    def _run(cmd, **kwargs):
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(mod.subprocess, "run", _run)


def test_진짜_404_는_파일_없음_None(monkeypatch):
    _fake_gh(monkeypatch, stderr="gh: Not Found (HTTP 404)\n")
    assert mod.GhClient().get_json_or_none_404(_CONTENTS) is None


def test_ref_가_없어서_나는_404_도_HTTP_404_라서_None(monkeypatch):
    _fake_gh(monkeypatch, stderr="gh: No commit found for the ref abc (HTTP 404)\n")
    assert mod.GhClient().get_json_or_none_404(_CONTENTS) is None


@pytest.mark.parametrize(
    "stderr",
    [
        "gh: Server Error (HTTP 502)\n",
        "gh: Service Unavailable (HTTP 503)\n",
        "gh: Not Found for a moment, try again (HTTP 500)\n",  # 본문에 Not Found 가 있어도
        "gh: API rate limit exceeded (HTTP 403)\n",
        "",
        "error connecting to api.github.com\n",
    ],
)
def test_요청_경로에_404_가_있어도_5xx_등은_GhError(monkeypatch, stderr):
    _fake_gh(monkeypatch, stderr=stderr)
    with pytest.raises(GhError):
        mod.GhClient().get_json_or_none_404(_CONTENTS)


def test_시간_초과는_경로에_404_가_있어도_GhError(monkeypatch):
    _fake_gh(monkeypatch, exc=subprocess.TimeoutExpired(["gh", "api", _CONTENTS], 30))
    with pytest.raises(GhError) as info:
        mod.GhClient().get_json_or_none_404(_CONTENTS)
    assert "404" in str(info.value)  # 메시지에 경로가 섞여도
    assert info.value.status is None


def test_stderr_중간에_HTTP_404_가_있어도_마지막_줄이_아니면_404_가_아니다(monkeypatch):
    _fake_gh(monkeypatch, stderr="gh: x (HTTP 404)\nlater: connection reset\n")
    with pytest.raises(GhError):
        mod.GhClient().get_json_or_none_404(_CONTENTS)


def test_세_호출부는_5xx_를_파일_없음으로_읽지_않는다(monkeypatch):
    from checker import risk_gate as rg

    _fake_gh(monkeypatch, stderr="gh: Bad Gateway (HTTP 502)\n")
    client = mod.GhClient()
    with pytest.raises(GhError):
        rg.fetch_text(client, "o", _SHA_404, ".github/risk-gate.yaml")
    with pytest.raises(GhError):
        mod.fetch_approvers(client, "o/r", _SHA_404)
    with pytest.raises(GhError):
        mod.fetch_human_merge_paths(client, "o/r", _SHA_404)


def test_세_호출부는_진짜_404_에서_기존_의미를_지킨다(monkeypatch):
    from checker import risk_gate as rg

    _fake_gh(monkeypatch, stderr="gh: Not Found (HTTP 404)\n")
    client = mod.GhClient()
    assert rg.fetch_text(client, "o", _SHA_404, ".github/risk-gate.yaml") is None
    assert mod.fetch_approvers(client, "o/r", _SHA_404) == set()
    assert mod.fetch_human_merge_paths(client, "o/r", _SHA_404) == []
