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


def _review(login: str, state: str, submitted_at: str) -> dict:
    return {"user": {"login": login}, "state": state, "submitted_at": submitted_at}


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
    monkeypatch.setattr(mod, "fetch_pr_info", lambda c, r, n: {"user": {"login": "author"}, "base": {"ref": "main"}})
    monkeypatch.setattr(mod, "fetch_pr_files", lambda c, r, n: ["docs/ssot/PRD.md"])
    monkeypatch.setattr(
        mod,
        "fetch_pr_reviews",
        lambda c, r, n: [_review("reviewer", "APPROVED", "2026-01-01T00:00:00Z")],
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
