"""콘솔에 막힘을 알리지 않던 훅 넷이 이제 알리는지 시험한다(#765).

실제 콘솔 서버(test_web_console 의 Console)를 띄우고 훅을 진짜로 돌려, 그 세션 대화에 ✕ 막힘(blocked) 또는
? 확인 못 함(cannot_check) 항목이 쌓이는 것을 본다. 화면이 그 항목을 카드로 그리는 것은 test_web_console_ui 의
chat_draws_hook_block_cards 가 맡는다. 어느 경우든 콘솔이 꺼져 있을 때와 (종료코드, stdout, stderr) 가 같아야 한다.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, _HAS_JQ, PLUGIN_ROOT
from checker.tests.test_web_console import authed, browser, console  # noqa: F401 - 픽스처

HOOKS = PLUGIN_ROOT / "hooks"
SID = "blk765"


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "feat/1-work")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("a\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _blocks(browser):
    """그 세션 대화의 막힘 항목. 콘솔이 그 세션을 아직 모르면 없는 것이다."""
    status, body, _ = browser.call("GET", f"/api/sessions/{SID}")
    return [c for c in body["chat"] if c["role"] == "block"] if status == 200 else []


def _only_card(browser, kind, hook):
    items = _blocks(browser)
    assert len(items) == 1, items
    assert items[0]["kind"] == kind and items[0]["hook"] == hook
    return items[0]


# ---- 1. subagent_edit_guard ------------------------------------------------

def test_subagent_edit_guard_block_shows_blocked_card(browser, repo):
    hook = HOOKS / "subagent_edit_guard.py"
    base = {"session_id": SID, "cwd": str(repo), "agent_id": "ag1", "agent_type": "implementer"}

    def run(port, mode, payload):
        env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
        return subprocess.run([sys.executable, str(hook), mode], input=json.dumps(payload).encode("utf-8"), env=env,
                              capture_output=True, timeout=60)

    start = run(_closed_port(), "start", {**base, "hook_event_name": "SubagentStart"})
    assert start.returncode == 0
    (repo / "a.txt").write_text("스크립트로 고침\n", encoding="utf-8")  # Edit/Write 기록 없이 바뀐 파일
    stop_payload = {**base, "hook_event_name": "SubagentStop", "stop_hook_active": False}

    down = run(_closed_port(), "stop", stop_payload)
    # 첫 stop 이 blocks 를 올렸으니 같은 상태로 다시 돌리려면 기준 기록을 되돌린다
    for item in (repo / ".git" / "harness-subagent-guard").glob("*.agent.json"):
        meta = json.loads(item.read_text(encoding="utf-8"))
        meta["blocks"], meta["blocked"] = 0, {}
        item.write_text(json.dumps(meta), encoding="utf-8")
    up = run(browser.port, "stop", stop_payload)

    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    out = json.loads(up.stdout.decode("utf-8"))
    assert out["decision"] == "block"
    card = _only_card(browser, "blocked", "subagent_edit_guard")
    assert card["text"] == out["reason"] and "a.txt" in card["text"]


def test_subagent_edit_guard_does_not_report_when_it_passes(browser, repo):
    hook = HOOKS / "subagent_edit_guard.py"
    base = {"session_id": SID, "cwd": str(repo), "agent_id": "ag1", "agent_type": "implementer"}
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(browser.port))
    for mode, extra in (("start", {"hook_event_name": "SubagentStart"}), ("stop", {"hook_event_name": "SubagentStop"})):
        done = subprocess.run([sys.executable, str(hook), mode], input=json.dumps({**base, **extra}).encode("utf-8"), env=env,
                              capture_output=True, timeout=60)
        assert done.returncode == 0 and done.stdout == b""
    assert _blocks(browser) == []


# ---- 2. stop-deliver.sh -----------------------------------------------------

@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 사유를 시험 입력대로 읽을 수 없다")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 bash 훅이 보고를 보낼 수 없다")
def test_stop_deliver_block_shows_blocked_card(browser, repo):
    (repo / "a.txt").write_text("x\n", encoding="utf-8")  # 커밋 안 된 변경
    stdin = json.dumps({"session_id": SID, "hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": False})

    def run(port):
        env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
        return subprocess.run([_BASH, str(HOOKS / "stop-deliver.sh")], input=stdin.encode("utf-8"), env=env,
                              capture_output=True, timeout=180)

    down = run(_closed_port())
    (repo / ".git" / f"{repo.name}-unfinished").unlink(missing_ok=True)  # 같은 상태에서 다시 돌린다
    up = run(browser.port)
    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    out = json.loads(up.stdout.decode("utf-8"))
    assert out["decision"] == "block"
    card = _only_card(browser, "blocked", "stop-deliver")
    assert card["text"] == out["reason"]


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 사유를 시험 입력대로 읽을 수 없다")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 bash 훅이 보고를 보낼 수 없다")
def test_stop_deliver_does_not_report_when_clean_or_already_retried(browser, repo):
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(browser.port))
    clean = json.dumps({"session_id": SID, "hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": False})
    done = subprocess.run([_BASH, str(HOOKS / "stop-deliver.sh")], input=clean.encode("utf-8"), env=env, capture_output=True, timeout=180)
    assert done.returncode == 0 and done.stdout == b""
    (repo / "a.txt").write_text("x\n", encoding="utf-8")
    retried = json.dumps({"session_id": SID, "hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": True})
    done = subprocess.run([_BASH, str(HOOKS / "stop-deliver.sh")], input=retried.encode("utf-8"), env=env, capture_output=True, timeout=180)
    assert done.returncode == 0 and b"decision" not in done.stdout  # 막지 않고 경고만 한다
    assert _blocks(browser) == []


# ---- 3. mcp_activation_tracker.py -------------------------------------------

def _tracker_payload(repo):
    return {"session_id": SID, "hook_event_name": "PostToolUse", "cwd": str(repo), "tool_name": "mcp__abap-adt__setObjectSource",
            "tool_input": {"objectSourceUrl": "/sap/bc/adt/oo/classes/zcl_a/source/main"}, "tool_response": {}}


def test_mcp_activation_tracker_failure_shows_cannot_check_card(browser, repo):
    (repo / ".git" / "harness-adt-activation.json").write_text("{깨진 기록", encoding="utf-8")  # 읽지 못하면 실패한다
    stdin = json.dumps(_tracker_payload(repo)).encode("utf-8")

    def run(port):
        env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
        return subprocess.run([sys.executable, str(HOOKS / "mcp_activation_tracker.py")], input=stdin, env=env, capture_output=True, timeout=60)

    down = run(_closed_port())
    (repo / ".git" / "harness-adt-activation.error").unlink(missing_ok=True)
    up = run(browser.port)
    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    assert up.returncode == 2 and "활성화" in up.stderr.decode("utf-8")
    card = _only_card(browser, "cannot_check", "mcp_activation_tracker")
    assert "확인하지 못했다" in card["text"] and "mcp__abap-adt__setObjectSource" in card["text"]
    assert card["fix"].startswith("inactiveObjects")


def test_mcp_activation_tracker_success_does_not_report(browser, repo):
    done = subprocess.run([sys.executable, str(HOOKS / "mcp_activation_tracker.py")], input=json.dumps(_tracker_payload(repo)).encode("utf-8"),
                          env=dict(os.environ, HARNESS_CONSOLE_PORT=str(browser.port)), capture_output=True, timeout=60)
    assert done.returncode == 0
    assert _blocks(browser) == []


# ---- 4. hooks.json 의 "uv 없음" 폴백 ----------------------------------------

def _fallback_command(script: str) -> str:
    hooks = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    found = [h["command"] for entries in hooks.values() for e in entries for h in e["hooks"]
             if f"hooks/{script}" in h["command"] and "console-block-nouv.sh" in h["command"]]
    assert len(found) == 1, script
    return found[0]


def _path_without_uv() -> str:
    keep = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if part and not any(os.path.isfile(os.path.join(part, n)) for n in ("uv", "uv.exe")):
            keep.append(part)
    return os.pathsep.join(keep)


NO_UV_CASES = [
    ("pre_write_guard.py", "pre_write_guard", "Write"),
    ("agent_delegation_guard.py", "agent_delegation_guard", "Agent"),
    ("mcp_source_guard.py", "mcp_source_guard", "mcp__abap-adt__setObjectSource"),
    ("mcp_activation_tracker.py", "mcp_activation_tracker", "mcp__abap-adt__setObjectSource"),
]


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 폴백을 실행해 볼 수 없다")
@pytest.mark.parametrize("script,hook,tool", NO_UV_CASES)
def test_no_uv_fallback_shows_cannot_check_card_and_keeps_exit_2(browser, repo, script, hook, tool):
    command = _fallback_command(script)
    payload = {"session_id": SID, "tool_use_id": "tu765", "tool_name": tool, "cwd": str(repo), "hook_event_name": "PreToolUse"}
    stdin = json.dumps(payload).encode("utf-8")

    def run(port):
        env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port), PATH=_path_without_uv(), CLAUDE_PLUGIN_ROOT=PLUGIN_ROOT.as_posix())
        return subprocess.run([_BASH, "-c", command], input=stdin, env=env, cwd=repo, capture_output=True, timeout=60)

    assert shutil.which("uv", path=_path_without_uv()) is None
    down = run(_closed_port())
    (repo / ".git" / "harness-adt-activation.error").unlink(missing_ok=True)
    up = run(browser.port)
    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    assert up.returncode == 2 and b"winget install" in up.stderr
    # 안내 문구가 echo 로 그대로 나가야 한다("echo\"..." 처럼 띄어쓰기가 빠지면 command not found 오류 속에 같은 글이 섞여 통과해 버린다)
    lines = up.stderr.decode("utf-8").splitlines()
    assert any(l.startswith(("doc-guard:", "harness:")) and "winget install" in l for l in lines), lines
    assert not any("command not found" in l and "uv:" not in l for l in lines), lines  # uv 없음 줄만 허용
    card = _only_card(browser, "cannot_check", hook)  # 막힘이 아니라 확인 못 함이다
    assert card["tool"] == tool and ("검사하지 못했다" in card["text"] or "확인하지 못했다" in card["text"])
    assert card["fix"].startswith("PowerShell 에서 winget install")


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 폴백을 실행해 볼 수 없다")
def test_no_uv_fallback_without_session_id_is_silent(browser, repo):
    command = _fallback_command("pre_write_guard.py")
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(browser.port), PATH=_path_without_uv(), CLAUDE_PLUGIN_ROOT=PLUGIN_ROOT.as_posix())
    done = subprocess.run([_BASH, "-c", command], input=b'{"tool_name":"Write"}', env=env, cwd=repo, capture_output=True, timeout=60)
    assert done.returncode == 2 and done.stdout == b""
    assert _blocks(browser) == []  # 세션을 모르면 보낼 곳이 없다
