"""막는 훅이 막을 때 웹 콘솔에 사유를 알리는 모듈(`hooks/console_block.py`) 시험(#650).

핵심은 두 가지다. 보고가 어떤 상황(콘솔 없음·연결 거부·느린 서버)에서도 예외 없이 빨리 끝나고 아무것도 출력하지 않는 것,
그리고 훅의 종료코드·stdout·stderr 가 보고가 나가든 안 나가든 똑같은 것.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, _HAS_JQ, PLUGIN_ROOT, _add_fake_gh

HOOKS = PLUGIN_ROOT / "hooks"
sys.path.insert(0, str(HOOKS))
import console_block  # noqa: E402


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class Recorder:
    """/hooks/blocked 로 온 본문을 모으는 가짜 콘솔. delay 를 주면 응답을 늦춘다."""

    def __init__(self, delay: float = 0.0):
        got, owner = [], self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                got.append((self.path, json.loads(body.decode("utf-8"))))
                if owner.delay:
                    time.sleep(owner.delay)
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        self.delay, self.got = delay, got
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def recorder():
    r = Recorder()
    yield r
    r.close()


PAYLOAD = {"session_id": "s1", "tool_use_id": "tu1", "tool_name": "Write", "hook_event_name": "PreToolUse", "cwd": "/w"}


def test_report_without_console_is_silent_and_fast(monkeypatch, capfd):
    monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(_closed_port()))
    t = time.time()
    console_block.report(PAYLOAD, "pre_write_guard", "막았다. 다음: 고쳐라")
    assert time.time() - t < 4
    out = capfd.readouterr()
    assert out.out == "" and out.err == ""


def test_report_with_slow_server_gives_up_quickly(monkeypatch, capfd):
    slow = Recorder(delay=6)
    try:
        monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(slow.port))
        t = time.time()
        console_block.report(PAYLOAD, "pre_write_guard", "막았다")
        assert time.time() - t < 3.5
    finally:
        slow.close()
    out = capfd.readouterr()
    assert out.out == "" and out.err == ""


def test_report_ignores_bad_input_and_bad_port(monkeypatch, capfd):
    monkeypatch.setenv("HARNESS_CONSOLE_PORT", "abc")
    for payload in (None, "x", {}, {"session_id": ""}, {"session_id": 3}):
        console_block.report(payload, "h", "사유")
    console_block.report(PAYLOAD, "h", "사유")  # 포트가 숫자가 아니면 4873 으로 간다. 거기 콘솔이 없어도 조용하다
    out = capfd.readouterr()
    assert out.out == "" and out.err == ""


def test_report_posts_hook_input_fields_and_reason(monkeypatch, recorder):
    monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(recorder.port))
    console_block.report(PAYLOAD, "pre_write_guard", "막았다. 다음: 고쳐라")
    path, body = recorder.got[0]
    assert path == "/hooks/blocked"
    assert body == {"hook_event_name": "HarnessBlocked", "hook": "pre_write_guard", "reason": "막았다. 다음: 고쳐라",
                    "session_id": "s1", "tool_use_id": "tu1", "tool_name": "Write", "cwd": "/w"}


def _run_py(script: str, stdin: str, port: int, extra_env: dict | None = None, args: tuple = ()):
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port), **(extra_env or {}))
    return subprocess.run([sys.executable, str(HOOKS / script), *args], input=stdin.encode("utf-8"), env=env, capture_output=True, timeout=60)


def test_cli_sends_reason_from_env_and_prints_nothing(recorder):
    r = _run_py("console_block.py", json.dumps(PAYLOAD), recorder.port, {"HARNESS_BLOCK_REASON": "검사 불능: 읽지 못했다. 다음: 다시"}, ("pre-bash-git-guard",))
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert recorder.got[0][1]["reason"] == "검사 불능: 읽지 못했다. 다음: 다시"


def test_cli_without_reason_or_with_garbage_stdin_is_silent(recorder):
    for stdin, env in (("not json", {"HARNESS_BLOCK_REASON": "x"}), (json.dumps(PAYLOAD), {})):
        r = subprocess.run([sys.executable, str(HOOKS / "console_block.py"), "h"], input=stdin.encode(), capture_output=True, timeout=30,
                           env=dict(os.environ, HARNESS_CONSOLE_PORT=str(recorder.port), **{"HARNESS_BLOCK_REASON": "", **env}))
        assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")
    assert recorder.got == []


def _same_with_and_without_console(script, stdin, recorder):
    """같은 입력을 콘솔이 있을 때와 없을 때 돌려 (종료코드, stdout, stderr) 가 같은지 본다."""
    up = _run_py(script, stdin, recorder.port)
    down = _run_py(script, stdin, _closed_port())
    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    return up


def test_agent_delegation_guard_reports_and_output_is_unchanged(recorder):
    stdin = json.dumps(dict(PAYLOAD, tool_name="Agent", tool_input={"subagent_type": "general-purpose", "prompt": "x"}))
    r = _same_with_and_without_console("agent_delegation_guard.py", stdin, recorder)
    assert r.returncode == 0 and r.stderr == b""
    reason = json.loads(r.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    (path, body), = recorder.got
    assert path == "/hooks/blocked" and body["hook"] == "agent_delegation_guard" and body["reason"] == reason
    assert body["session_id"] == "s1" and body["tool_name"] == "Agent"


def test_pre_write_guard_reports_and_output_is_unchanged(recorder, tmp_path):
    bad = str(tmp_path / "깨진�경로.md")  # 깨진 경로는 검사 불능으로 막는다
    stdin = json.dumps(dict(PAYLOAD, tool_name="Write", tool_input={"file_path": bad, "content": "x"}), ensure_ascii=True)
    r = _same_with_and_without_console("pre_write_guard.py", stdin, recorder)
    assert r.returncode == 0 and r.stderr == b""
    reason = json.loads(r.stdout.decode("utf-8"))["hookSpecificOutput"]["permissionDecisionReason"]
    (path, body), = recorder.got
    assert body["hook"] == "pre_write_guard" and body["reason"] == reason and "판단할 수 없" in reason


def test_guards_do_not_report_when_they_allow(recorder, tmp_path):
    ok = dict(PAYLOAD, tool_name="Write", tool_input={"file_path": str(tmp_path / "a.txt"), "content": "x"})
    r = _run_py("pre_write_guard.py", json.dumps(ok), recorder.port)
    assert r.returncode == 0
    ok_agent = dict(PAYLOAD, tool_name="Agent", tool_input={"subagent_type": "harness:researcher", "prompt": "x"})
    r = _run_py("agent_delegation_guard.py", json.dumps(ok_agent), recorder.port)
    assert r.returncode == 0 and r.stdout == b""
    assert recorder.got == []


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 bash 훅이 보고를 보낼 수 없다")
def test_bash_git_guard_reports_and_output_is_unchanged(recorder, tmp_path):
    bin_dir = tmp_path / "gh-bin"
    bin_dir.mkdir()
    _add_fake_gh(bin_dir)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "feat/1-work", str(repo)], check=True)
    stdin = json.dumps({"session_id": "s1", "tool_use_id": "tu1", "tool_name": "Bash", "hook_event_name": "PreToolUse",
                        "cwd": str(repo), "tool_input": {"command": "git push origin HEAD"}})

    def run(port):
        env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port), PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
        return subprocess.run([_BASH, str(HOOKS / "pre-bash-git-guard.sh")], input=stdin.encode("utf-8"), env=env, capture_output=True, timeout=180)

    up, down = run(recorder.port), run(_closed_port())
    assert (up.returncode, up.stdout, up.stderr) == (down.returncode, down.stdout, down.stderr)
    out = json.loads(up.stdout.decode("utf-8"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    (path, body), = recorder.got
    assert body["hook"] == "pre-bash-git-guard" and body["session_id"] == "s1" and body["tool_name"] == "Bash"
    assert body["reason"] == out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 bash 훅이 보고를 보낼 수 없다")
def test_stop_deliver_does_not_report(recorder, tmp_path):
    # 커밋 안 된 변경 알림은 오류가 아니라 안내라서 콘솔 막힘 카드로 보내지 않는다(턴마다 빨간 카드가 쌓인다)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "feat/1-work", str(repo)], check=True)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    stdin = json.dumps({"session_id": "s1", "hook_event_name": "Stop", "cwd": str(repo), "stop_hook_active": False})
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(recorder.port))
    up = subprocess.run([_BASH, str(HOOKS / "stop-deliver.sh")], input=stdin.encode("utf-8"), env=env, capture_output=True, timeout=180)
    assert json.loads(up.stdout.decode("utf-8"))["decision"] == "block"
    assert recorder.got == []
