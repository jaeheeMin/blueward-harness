"""#417 — 단계 결과를 commit status state 로 바꾸고 단다. gh 호출은 가짜로 바꾼다."""
from __future__ import annotations

import subprocess

import pytest

from checker import step_status
from checker.step_status import StatusError, main, post_status, state_for


@pytest.mark.parametrize("result, state", [("pass", "success"), ("fail", "failure"), ("unknown", "error")])
def test_결과_세_가지가_state_로_바뀐다(result, state):
    assert state_for(result) == state


@pytest.mark.parametrize("result", ["", "ok", "PASS", "success"])
def test_모르는_result_는_거부한다(result):
    with pytest.raises(StatusError):
        state_for(result)


def _fake_run(calls, returncode=0, stderr=""):
    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, stdout="{}", stderr=stderr)

    return run


def test_post_status_는_sha_와_context_로_gh_api_를_부른다(monkeypatch):
    calls: list = []
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run(calls))
    state = post_status("o/r", "abc123", "doc-guard", "unknown", "검사 불능", "https://x/y")
    assert state == "error"
    args = calls[0]
    assert args[:5] == ["gh", "api", "-X", "POST", "repos/o/r/statuses/abc123"]
    assert "state=error" in args and "context=doc-guard" in args
    assert "description=검사 불능" in args and "target_url=https://x/y" in args


def test_post_status_는_비어_있는_선택_인자를_보내지_않는다(monkeypatch):
    calls: list = []
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run(calls))
    post_status("o/r", "abc", "gitleaks", "pass")
    assert not any(a.startswith(("description=", "target_url=")) for a in calls[0])


def test_post_status_gh_가_실패하면_사유와_함께_예외(monkeypatch):
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run([], returncode=1, stderr="HTTP 403"))
    with pytest.raises(StatusError, match="HTTP 403"):
        post_status("o/r", "abc", "gitleaks", "pass")


def test_post_status_gh_가_없으면_예외(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(step_status.subprocess, "run", boom)
    with pytest.raises(StatusError):
        post_status("o/r", "abc", "gitleaks", "pass")


def test_main_gh_실패는_종료코드_2_와_stderr_사유(monkeypatch, capsys):
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run([], returncode=1, stderr="HTTP 403"))
    rc = main(["--repo", "o/r", "--sha", "abc", "--context", "risk-gate", "--result", "pass"])
    assert rc == 2
    assert "HTTP 403" in capsys.readouterr().err


def test_main_잘못된_result_는_종료코드_2(monkeypatch, capsys):
    calls: list = []
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run(calls))
    rc = main(["--repo", "o/r", "--sha", "abc", "--context", "risk-gate", "--result", "maybe"])
    assert rc == 2 and calls == []
    assert "maybe" in capsys.readouterr().err


def test_main_성공은_0(monkeypatch, capsys):
    monkeypatch.setattr(step_status.subprocess, "run", _fake_run([]))
    assert main(["--repo", "o/r", "--sha", "abc", "--context", "gitleaks", "--result", "fail"]) == 0
    assert "failure" in capsys.readouterr().out
