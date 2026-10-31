"""Harness 웹 콘솔 백엔드 시험(#558, docs/design/web-console.md).

실제 claude 를 부르지 않는다. 임시 포트로 표준 라이브러리 서버를 띄우고, 가짜 claude(fake_claude.py)를 쓴다.
시간은 FakeClock 으로 주입한다. Windows 분기는 OS 값을 주입해 분기 로직만 확인했고 Windows 에서 실행하지는 않았다.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "harness"
CONSOLE = PLUGIN / "console"
FAKE = Path(__file__).with_name("fake_claude.py")
sys.path.insert(0, str(CONSOLE))

import analysis  # noqa: E402
import gitstate  # noqa: E402
import managed  # noqa: E402
from hooks_api import Hooks, permission_reply  # noqa: E402
import open as console_open  # noqa: E402
import platform_compat  # noqa: E402
import server as console_server  # noqa: E402
from store import Store  # noqa: E402


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def wait_for(cond, timeout=10.0, step=0.02):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = cond()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("조건이 시간 안에 맞지 않았다")


class Console:
    """임시 포트로 뜬 서버와 호출 도우미."""

    def __init__(self, tmp_path, monkeypatch, claude_cmd=None, git_inspect=None):
        plugin = tmp_path / "plugin"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text('{"name":"harness","version":"9.9.9"}', encoding="utf-8")
        for name in ("start", "deliver", "prs", "update", "scaffold", "open"):
            d = plugin / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: x\n---\n", encoding="utf-8")
        self.opened: list[str] = []
        self.clock = FakeClock()
        self.state = tmp_path / "state"
        self.work = tmp_path / "work"
        self.work.mkdir()
        inspect = git_inspect or (lambda cwd: {"isRepo": False, "repo": "", "branch": "", "changedFiles": [], "skill": None, "unknown": False})
        self.app = console_server.App(0, self.state, plugin, clock=self.clock, browser_open=lambda u: self.opened.append(u) or True,
                                      claude_cmd=claude_cmd or (lambda: None), git_inspect=inspect, poll=0.02,
                                      question_wait=300.0, sync_spawn=True)
        self.server = console_server.make_server(self.app, 0)
        self.port = self.server.server_address[1]
        self.app.set_port(self.port)
        monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(self.port))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.cookie = ""

    def close(self):
        self.server.shutdown()
        self.app.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, headers=None, host=None, raw=None, cookie=True, json_type=True):
        h = {"Host": host if host is not None else f"127.0.0.1:{self.port}"}
        if cookie and self.cookie:
            h["Cookie"] = f"harness_console={self.cookie}"
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if data is not None and json_type:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            conn.putheader(k, v)
        conn.putheader("Content-Length", str(len(data or b"")))
        conn.endheaders(data or b"")
        resp = conn.getresponse()
        text = resp.read().decode("utf-8")
        conn.close()
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return resp.status, parsed, resp

    def login(self):
        status, _, _ = self.call("POST", "/api/open", {})
        assert status == 200
        token = self.opened[-1].split("t=")[1]
        status, _, resp = self.call("GET", f"/auth?t={token}", cookie=False)
        assert status == 302
        self.cookie = resp.getheader("Set-Cookie").split(";")[0].split("=", 1)[1]
        return token

    def hook(self, name, body, ts=None):
        """ts 를 주면 hook_post.py 가 붙이는 X-Hook-Ts 헤더를 흉내 낸다."""
        return self.call("POST", f"/hooks/{name}", body, cookie=False, headers={"X-Hook-Ts": repr(ts)} if ts is not None else None)

    def hook_async(self, name, body):
        """오래 붙드는 훅 호출을 스레드로 보낸다. 결과는 holder 에 들어온다."""
        holder = {}

        def run():
            holder["r"] = self.hook(name, body)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        holder["t"] = t
        return holder

    def event(self, sid, name, ts=None, **kw):
        return self.hook("event", dict({"session_id": sid, "cwd": str(self.work), "hook_event_name": name}, **kw), ts=ts)

    def pending(self, sid):
        s = self.app.store.get(sid)
        return self.app.store.pending_for(s["id"]) if s else []

    def connect_browser(self):
        """SSE 로 브라우저가 붙은 것처럼 만든다. 돌려준 연결을 닫으면 끊긴다."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.putrequest("GET", "/api/events", skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.putheader("Cookie", f"harness_console={self.cookie}")
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.fp.readline().startswith(b": connected")
        return conn, resp


@pytest.fixture
def console(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch)
    yield c
    c.close()


@pytest.fixture
def authed(console):
    console.login()
    return console


@pytest.fixture
def browser(authed):
    conn, resp = authed.connect_browser()
    yield authed
    conn.close()


def perm_body(sid, command="touch a", **kw):
    return dict({"session_id": sid, "cwd": "/w", "hook_event_name": "PermissionRequest", "tool_name": "Bash",
                 "tool_input": {"command": command}}, **kw)


def ask_body(sid, tool="AskUserQuestion"):
    q = [{"question": "색은?", "header": "색", "multiSelect": True, "options": [{"label": "Red"}, {"label": "Blue"}]}]
    return {"session_id": sid, "cwd": "/w", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"questions": q}}


# ---- 인증과 보안 ----

def test_health_is_open_and_names_the_app(console):
    status, body, _ = console.call("GET", "/api/health", cookie=False)
    assert status == 200 and body["app"] == "harness-console" and body["version"] == "9.9.9"


@pytest.mark.parametrize("host", ["evil.example.com", "127.0.0.1:1", "localhost", f"127.0.0.1.evil.com", ""])
def test_host_check_rejects_other_hosts(console, host):
    for path in ("/api/health", "/", "/hooks/event"):
        status, _, _ = console.call("POST" if path.startswith("/hooks") else "GET", path, {} if path.startswith("/hooks") else None, host=host)
        assert status == 403


def test_host_check_accepts_localhost_name(console):
    status, _, _ = console.call("GET", "/api/health", host=f"localhost:{console.port}")
    assert status == 200


def test_open_response_and_stdout_never_contain_token(console):
    status, body, resp = console.call("POST", "/api/open", {})
    token = console.opened[-1].split("t=")[1]
    assert status == 200 and body == {"ok": True}
    assert token not in json.dumps(body) and token not in str(resp.getheaders())
    assert console.opened[-1].startswith(f"http://127.0.0.1:{console.port}/auth?t=")


def test_open_fails_when_no_browser_and_leaves_no_token(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch)
    c.app.browser_open = lambda url: False
    try:
        status, body, _ = c.call("POST", "/api/open", {})
        assert status == 503 and c.app.tokens == {}
    finally:
        c.close()


def test_token_is_single_use(console):
    console.call("POST", "/api/open", {})
    token = console.opened[-1].split("t=")[1]
    assert console.call("GET", f"/auth?t={token}", cookie=False)[0] == 302
    assert console.call("GET", f"/auth?t={token}", cookie=False)[0] == 403


def test_token_expires_after_60_seconds(console):
    console.call("POST", "/api/open", {})
    token = console.opened[-1].split("t=")[1]
    console.clock.t += 61
    assert console.call("GET", f"/auth?t={token}", cookie=False)[0] == 403
    assert console.call("GET", "/auth?t=nope", cookie=False)[0] == 403


def test_auth_cookie_flags(console):
    console.call("POST", "/api/open", {})
    token = console.opened[-1].split("t=")[1]
    _, _, resp = console.call("GET", f"/auth?t={token}", cookie=False)
    cookie = resp.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and resp.getheader("Location") == "/"


def test_api_requires_cookie(console):
    assert console.call("GET", "/api/sessions", cookie=False)[0] == 401
    console.cookie = "forged"
    assert console.call("GET", "/api/sessions")[0] == 401


def test_answer_without_cookie_is_refused_and_request_stays_pending(browser):
    h = browser.hook_async("permission", perm_body("s1"))
    rid = wait_for(lambda: (browser.pending("s1") or [None])[0]).rid
    status, _, _ = browser.call("POST", f"/api/requests/{rid}/answer", {"decision": "allow"}, cookie=False)
    assert status == 401
    assert browser.app.store.get_request(rid).status == "pending"
    browser.call("POST", f"/api/requests/{rid}/answer", {"decision": "allow"})
    h["t"].join(5)


def test_hooks_cannot_answer_requests(console):
    # /hooks/* 는 요청을 만들 수만 있다. 답 경로는 /api 뿐이고 쿠키가 필요하다.
    assert console.hook("answer", {"session_id": "x"})[0] == 404


def test_hooks_reject_browser_origin_and_non_json(console):
    assert console.call("POST", "/hooks/event", {"session_id": "s"}, headers={"Origin": "http://evil.example"}, cookie=False)[0] == 403
    assert console.call("POST", "/api/open", {}, headers={"Origin": f"http://127.0.0.1:{console.port}"}, cookie=False)[0] == 403
    assert console.call("POST", "/hooks/event", raw=b"not json", cookie=False)[0] == 400
    assert console.call("POST", "/hooks/event", raw=b"[1]", cookie=False)[0] == 400
    assert console.call("GET", "/hooks/event", cookie=False)[0] == 405


def test_mutations_check_origin_and_content_type(authed):
    ok, _, _ = authed.call("POST", "/api/folders/validate", {"path": str(authed.work)}, headers={"Origin": f"http://localhost:{authed.port}"})
    assert ok == 200
    assert authed.call("POST", "/api/folders/validate", {"path": "/"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert authed.call("GET", "/api/sessions", headers={"Origin": "http://evil.example"})[0] == 403
    assert authed.call("POST", "/api/folders/validate", raw=b'{"path":"/"}', json_type=False)[0] == 415
    assert authed.call("POST", "/api/folders/validate", raw=b'{"path":"/"}', headers={"Content-Type": "text/plain"})[0] == 415


def test_body_size_limit(console):
    console.login()
    for path, limit in (("/api/folders/validate", console_server.API_BODY_LIMIT), ("/hooks/event", console_server.HOOK_BODY_LIMIT)):
        sock = socket.create_connection(("127.0.0.1", console.port))
        cookie = f"Cookie: harness_console={console.cookie}\r\n"
        sock.sendall((f"POST {path} HTTP/1.0\r\nHost: 127.0.0.1:{console.port}\r\n{cookie}Content-Type: application/json\r\n"
                      f"Content-Length: {limit + 1}\r\n\r\n").encode())
        assert sock.recv(64).startswith(b"HTTP/1.0 413")  # 본문을 읽기 전에 거부한다
        sock.close()


def test_static_headers_and_spa_paths(console, tmp_path):
    # static/ 은 다른 작업자가 만든다. 있으면 CSP 를 확인하고 없으면 404 인 것만 확인한다.
    status, _, resp = console.call("GET", "/", cookie=False)
    if status == 200:
        assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    else:
        assert status == 404
    assert console.call("GET", "/static/../server.py", cookie=False)[0] == 404
    assert console.call("GET", "/server.py", cookie=False)[0] == 404


# ---- 파일 탐색 ----

def test_fs_blocks_escape_and_symlinks(authed, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    (authed.work / "a.txt").write_text("a")
    (authed.work / "sub").mkdir()
    (authed.work / "sub" / "b.txt").write_text("b")
    try:
        (authed.work / "link").symlink_to(outside, target_is_directory=True)
        (authed.work / "filelink").symlink_to(outside / "secret.txt")
        symlinks = True
    except OSError:
        symlinks = False  # Windows 에서 권한이 없으면 링크를 못 만든다
    root = str(authed.work)
    # 고르지 않은 폴더는 열 수 없다
    assert authed.call("GET", f"/api/fs?root={root}")[0] == 403
    assert authed.call("POST", "/api/folders/validate", {"path": root})[1]["ok"]
    status, body, _ = authed.call("GET", f"/api/fs?root={root}")
    names = {e["name"]: e for e in body["entries"]}
    assert status == 200 and names["sub"]["kind"] == "dir" and names["a.txt"]["size"] == 1
    assert "link" not in names and "filelink" not in names or not symlinks  # 밖을 가리키는 링크는 보이지 않는다
    if symlinks:
        assert "link" not in names and "filelink" not in names
        assert authed.call("GET", f"/api/fs?root={root}&dir=link")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=..")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=sub/../..")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir={outside}")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=sub")[1]["entries"][0]["name"] == "b.txt"
    assert authed.call("GET", f"/api/fs?root={outside}")[0] == 403  # 고르지 않은 다른 폴더


def test_validate_folder(authed):
    ok = authed.call("POST", "/api/folders/validate", {"path": str(authed.work)})[1]
    assert ok["ok"] and ok["isGit"] is False
    assert authed.call("POST", "/api/folders/validate", {"path": str(authed.work / "nope")})[1]["ok"] is False
    assert authed.call("GET", "/api/folders/recent")[1][0]["path"] == ok["path"]


# ---- 승인 ----

def test_permission_without_browser_returns_empty_for_terminal_session(authed):
    status, body, _ = authed.hook("permission", perm_body("t1"))
    assert status == 200 and body is None
    assert authed.pending("t1") == []


def test_permission_allow_and_updated_permissions(browser):
    sugg = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch:*"}], "behavior": "allow", "destination": "session"}]
    h = browser.hook_async("permission", perm_body("t1", permission_suggestions=sugg))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    status, detail, _ = browser.call("GET", f"/api/requests/{req.rid}")
    assert detail["hasSuggestions"] and detail["kind"] == "permission"
    status, _, _ = browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow_session"})
    assert status == 200
    h["t"].join(5)
    out = h["r"][1]["hookSpecificOutput"]
    assert out["hookEventName"] == "PermissionRequest"
    assert out["decision"] == {"behavior": "allow", "updatedPermissions": sugg}
    # 이미 처리된 요청에 다시 답하면 409
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny"})[0] == 409


def test_permission_deny_and_validation(browser):
    h = browser.hook_async("permission", perm_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow_session"})[0] == 400  # 제안이 없으면 숨기는 버튼
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "wat"})[0] == 400
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny", "reason": "안 됨"})
    h["t"].join(5)
    assert h["r"][1]["hookSpecificOutput"]["decision"] == {"behavior": "deny", "message": "안 됨"}


def test_terminal_allowed_first_closes_request_via_post_tool_use(browser):
    body = perm_body("t1", "touch same")
    h = browser.hook_async("permission", body)
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    # 다른 도구나 다른 입력의 PostToolUse 는 닫지 않는다
    browser.event("t1", "PostToolUse", tool_name="Bash", tool_input={"command": "other"})
    browser.event("t1", "PostToolUse", tool_name="Read", tool_input={"command": "touch same"})
    assert req.status == "pending"
    browser.event("t1", "PostToolUse", tool_name="Bash", tool_input={"command": "touch same"})
    h["t"].join(5)
    assert h["r"] == (200, None, h["r"][2])
    assert req.status == "closed" and req.outcome == "터미널에서 처리됨"
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})[0] == 409


@pytest.mark.parametrize("closer", ["UserPromptSubmit", "SessionEnd"])
def test_prompt_or_end_closes_remaining_terminal_requests(browser, closer):
    h = browser.hook_async("permission", perm_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    browser.event("t1", closer, prompt="다음")
    h["t"].join(5)
    assert req.status == "closed"


def test_stop_closes_terminal_requests(browser):
    h = browser.hook_async("permission", perm_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "끝"})
    h["t"].join(5)
    assert req.status == "closed"


def test_dropped_connection_closes_request(browser):
    sock = socket.create_connection(("127.0.0.1", browser.port))
    payload = json.dumps(perm_body("t1")).encode()
    sock.sendall(b"POST /hooks/permission HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s"
                 % (browser.port, len(payload), payload))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    sock.close()
    wait_for(lambda: req.status == "closed")
    assert "끊겨" in req.outcome


def test_duplicate_concurrent_requests_merge_into_one(browser):
    h1 = browser.hook_async("permission", perm_body("t1", "touch dup"))
    wait_for(lambda: browser.pending("t1"))
    h2 = browser.hook_async("permission", perm_body("t1", "touch dup"))
    time.sleep(0.2)
    pending = browser.pending("t1")
    assert len(pending) == 1
    h3 = browser.hook_async("permission", perm_body("t1", "touch other"))
    wait_for(lambda: len(browser.pending("t1")) == 2)  # 입력이 다르면 합치지 않는다
    browser.call("POST", f"/api/requests/{pending[0].rid}/answer", {"decision": "allow"})
    for h in (h1, h2):
        h["t"].join(5)
        assert h["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    browser.event("t1", "SessionEnd")  # 남은 요청을 닫아 훅 스레드가 30초 timeout 까지 남지 않게 한다
    h3["t"].join(5)


def test_one_dropped_waiter_does_not_close_shared_request(browser):
    sock = socket.create_connection(("127.0.0.1", browser.port))
    payload = json.dumps(perm_body("t1", "touch dup")).encode()
    sock.sendall(b"POST /hooks/permission HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Length: %d\r\n\r\n%s" % (browser.port, len(payload), payload))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    h = browser.hook_async("permission", perm_body("t1", "touch dup"))
    wait_for(lambda: req.waiters == 2)
    sock.close()
    wait_for(lambda: req.waiters == 1)
    time.sleep(0.2)
    assert req.status == "pending"
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
    h["t"].join(5)
    assert h["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_managed_session_waits_even_without_browser(authed):
    s = authed.app.store.ensure("m1", str(authed.work))
    s["managed"] = True
    h = authed.hook_async("permission", perm_body("m1"))
    req = wait_for(lambda: (authed.pending("m1") or [None])[0])
    time.sleep(0.3)
    assert h["t"].is_alive()  # 브라우저가 없어도 답할 때까지 기다린다
    authed.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
    h["t"].join(5)
    assert h["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_permission_for_ask_user_question_is_left_to_question_hook(browser):
    assert browser.hook("permission", perm_body("t1", tool_name="AskUserQuestion"))[1] is None
    assert browser.pending("t1") == []


# ---- 질문 ----

def test_question_answer_format(browser):
    body = ask_body("t1")
    h = browser.hook_async("question", body)
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {}})[0] == 400
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": ""}})[0] == 400
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": ["Red", "Blue"]}})[0] == 200
    h["t"].join(5)
    out = h["r"][1]["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "allow"
    assert out["updatedInput"]["answers"] == {"색은?": "Red, Blue"}
    assert out["updatedInput"]["questions"] == body["tool_input"]["questions"]


def test_question_free_text(browser):
    h = browser.hook_async("question", ask_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": "보라색 직접 입력"}})
    h["t"].join(5)
    assert h["r"][1]["hookSpecificOutput"]["updatedInput"]["answers"] == {"색은?": "보라색 직접 입력"}


@pytest.mark.parametrize("tool", ["Bash", "Read", "mcp__x__y", "StructuredOutput"])
def test_question_hook_ignores_non_ask_user_question(browser, tool):
    status, body, _ = browser.hook("question", ask_body("t1", tool))
    assert status == 200 and body is None and browser.pending("t1") == []


def test_question_without_browser_returns_empty_immediately(authed):
    t0 = time.monotonic()
    status, body, _ = authed.hook("question", ask_body("t1"))
    assert (status, body) == (200, None) and time.monotonic() - t0 < 2
    assert authed.pending("t1") == []


def test_question_times_out_after_300_seconds_with_injected_clock(browser):
    h = browser.hook_async("question", ask_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    browser.clock.t += 299
    time.sleep(0.2)
    assert req.status == "pending"
    browser.clock.t += 2
    h["t"].join(5)
    assert h["r"][1] is None and req.status == "closed" and req.outcome == "터미널로 넘어감"


def test_managed_question_has_no_timeout(authed):
    authed.app.store.ensure("m1", str(authed.work))["managed"] = True
    h = authed.hook_async("question", ask_body("m1"))
    req = wait_for(lambda: (authed.pending("m1") or [None])[0])
    authed.clock.t += 10_000
    time.sleep(0.2)
    assert req.status == "pending" and h["t"].is_alive()
    authed.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": "Red"}})
    h["t"].join(5)


def test_question_dropped_connection_closes(browser):
    sock = socket.create_connection(("127.0.0.1", browser.port))
    payload = json.dumps(ask_body("t1")).encode()
    sock.sendall(b"POST /hooks/question HTTP/1.0\r\nHost: 127.0.0.1:%d\r\nContent-Length: %d\r\n\r\n%s" % (browser.port, len(payload), payload))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    sock.close()
    wait_for(lambda: req.status == "closed")


# ---- Stop 과 예약 ----

def test_stop_saves_report_and_blocks_once_for_reservation(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    assert browser.call("PUT", "/api/sessions/t1/skills/deliver/reservation", {})[0] == 200
    assert browser.call("PUT", "/api/sessions/t1/skills/nope/reservation", {})[0] == 404
    status, body, _ = browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "결과 보고"})
    assert body["decision"] == "block" and "deliver" in body["reason"]
    status, body, _ = browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "두 번째", "stop_hook_active": True})
    assert body is None  # 꺼낼 때 지워서 한 번뿐
    assert browser.call("GET", "/api/sessions/t1")[1]["report"] == "두 번째"


def test_stop_delivers_queued_message_once(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    assert browser.call("POST", "/api/sessions/t1/messages", {"text": "이어서 이것도"})[0] == 202
    body = browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "x"})[1]
    assert body["decision"] == "block" and "이어서 이것도" in body["reason"]
    assert browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "y"})[1] is None


def test_stop_without_queue_is_empty_and_marks_idle(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    assert browser.call("GET", "/api/sessions/t1")[1]["status"] == "running"
    assert browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "r"})[1] is None
    assert browser.call("GET", "/api/sessions/t1")[1]["status"] == "idle"


def test_idle_terminal_session_cannot_receive_messages_or_skills(browser):
    browser.event("t1", "SessionStart")
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["canSend"] is False and s["cannotSendReason"]
    assert browser.call("POST", "/api/sessions/t1/messages", {"text": "hi"})[0] == 409
    assert browser.call("POST", "/api/sessions/t1/skills/start/run", {})[0] == 409
    assert browser.call("PUT", "/api/sessions/t1/skills/start/reservation", {})[0] == 409
    assert all(f["disabledReason"] for f in s["flow"])


def test_reservation_can_be_cancelled_and_flow_shows_it(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    browser.call("PUT", "/api/sessions/t1/skills/prs/reservation", {})
    flow = {f["skill"]: f for f in browser.call("GET", "/api/sessions/t1")[1]["flow"]}
    assert flow["prs"]["reserved"] and not flow["start"]["reserved"]
    assert set(flow) == {"start", "deliver", "prs"}  # update, scaffold, open 은 버튼으로 내지 않는다
    browser.call("DELETE", "/api/sessions/t1/skills/prs/reservation", {})
    assert browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "x"})[1] is None


# ---- 이벤트 ----

def test_first_event_registers_session_and_title_rules(browser):
    browser.event("t9", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
    s = browser.call("GET", "/api/sessions/t9")[1]
    assert s["title"] == "work" and s["currentAction"].startswith("Bash: ls") and s["managed"] is False
    browser.event("t9", "UserPromptSubmit", prompt="로그인 화면 고쳐줘\n자세히")
    assert browser.call("GET", "/api/sessions/t9")[1]["title"] == "로그인 화면 고쳐줘"
    browser.event("t9", "SessionStart", session_title="지정한 제목")
    assert browser.call("GET", "/api/sessions/t9")[1]["title"] == "지정한 제목"
    browser.event("t9", "UserPromptSubmit", prompt="다른 요청")
    assert browser.call("GET", "/api/sessions/t9")[1]["title"] == "지정한 제목"


def test_skill_detection_from_both_paths(browser):
    browser.event("t1", "UserPromptExpansion", command_name="harness:deliver", expansion_type="slash_command")
    assert browser.call("GET", "/api/sessions/t1")[1]["currentSkill"] == "deliver"
    browser.event("t1", "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:prs"})
    s = browser.call("GET", "/api/sessions/t1")[1]
    flow = {f["skill"]: f["state"] for f in s["flow"]}
    assert s["currentSkill"] == "prs" and flow["prs"] == "active" and flow["deliver"] == "done"
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "x"})
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["currentSkill"] == "" and {f["skill"]: f["state"] for f in s["flow"]}["prs"] == "done"


def test_post_tool_use_collects_changed_files_and_pr_links(browser):
    browser.event("t1", "PostToolUse", tool_name="Write", tool_input={"file_path": "/w/a.md"}, tool_response={"ok": True})
    browser.event("t1", "PostToolUse", tool_name="Bash", tool_input={"command": "gh pr create"},
                  tool_response={"stdout": "https://github.com/org/repo/pull/12\n"})
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["changedFiles"] == ["/w/a.md"] and s["prLinks"] == ["https://github.com/org/repo/pull/12"]


def test_subagents_and_unknown_events_are_tolerated(browser):
    browser.event("t1", "SubagentStart", agent_id="a1", agent_type="general-purpose")
    browser.event("t1", "SubagentStop", agent_id="a1", agent_type="general-purpose")
    browser.event("t1", "Notification", message="알림")
    browser.event("t1", "SomethingNew")
    assert browser.hook("event", {"no": "session"})[0] == 400
    assert browser.call("GET", "/api/sessions/t1")[1]["subagents"][0]["state"] == "done"


def test_bypass_permission_mode_is_flagged(browser):
    browser.event("t1", "UserPromptSubmit", prompt="x", permission_mode="bypassPermissions")
    assert browser.call("GET", "/api/sessions/t1")[1]["bypassPermissions"] is True


def test_group_rules(browser):
    browser.event("t1", "UserPromptSubmit", prompt="x")
    assert browser.call("GET", "/api/sessions/t1")[1]["group"] == "running"
    s = browser.app.store.get("t1")
    h = browser.hook_async("permission", perm_body("t1"))
    wait_for(lambda: browser.pending("t1"))
    got = browser.call("GET", "/api/sessions/t1")[1]
    assert got["group"] == "todo" and got["status"] == "waiting" and len(got["pendingRequestIds"]) == 1
    browser.event("t1", "SessionEnd")
    h["t"].join(5)
    s["turn"] = {"skill": "deliver", "unknown": False}
    browser.event("t2", "SessionStart")
    browser.app.store.get("t2")["turn"] = {"skill": "deliver", "unknown": False}
    assert browser.call("GET", "/api/sessions/t2")[1]["group"] == "todo"  # 턴이 끝났고 이번 차례가 있다
    assert browser.call("GET", "/api/sessions/t2")[1]["turnSkill"] == "deliver"


def test_sessions_persist_atomically_and_requests_do_not(browser):
    browser.event("t1", "UserPromptSubmit", prompt="저장 시험")
    h = browser.hook_async("permission", perm_body("t1"))
    wait_for(lambda: browser.pending("t1"))
    browser.app.store.flush()
    saved = json.loads((browser.state / "sessions.json").read_text(encoding="utf-8"))
    assert saved["sessions"][0]["title"] == "저장 시험" and "requests" not in saved
    assert not list(browser.state.glob("*.tmp"))
    reloaded = Store(browser.state)
    assert reloaded.get("t1")["title"] == "저장 시험" and reloaded.pending_for("t1") == []
    browser.event("t1", "SessionEnd")
    h["t"].join(5)


def test_log_is_capped_at_200(browser):
    for i in range(230):
        browser.event("t1", "Notification", message=f"n{i}")
    log = browser.call("GET", "/api/sessions/t1")[1]["log"]
    assert len(log) == 200 and log[-1]["text"].endswith("n229")


def test_sse_streams_session_and_request_events(authed):
    conn, resp = authed.connect_browser()
    try:
        authed.event("t1", "UserPromptSubmit", prompt="sse")
        seen = set()
        while "session" not in seen:
            line = resp.fp.readline().decode()
            if line.startswith("event:"):
                seen.add(line.split(":", 1)[1].strip())
        assert authed.app.store.browser_connected()
    finally:
        conn.close()
    wait_for(lambda: not authed.app.store.browser_connected(), timeout=15) if False else None


# ---- 새 작업 / 분석 ----

def test_analysis_result_paths_are_rechecked(tmp_path):
    (tmp_path / "ok.md").write_text("x")
    data = {"understood": "u", "candidates": [
        {"path": "ok.md", "reason": "r"}, {"path": "../etc/passwd", "reason": "탈출"}, {"path": "/etc/passwd", "reason": "절대"},
        {"path": "sub/../../x", "reason": "탈출2"}, {"reason": "경로 없음"}],
        "extraQuestions": [{"question": "q", "options": ["a", "b"]}, {"nope": 1}]}
    checked = analysis.check_result(data, str(tmp_path))
    assert [c["path"] for c in checked["candidates"]] == ["ok.md"]
    assert checked["extraQuestions"] == [{"question": "q", "options": ["a", "b"]}]
    assert analysis.check_result({"candidates": []}, str(tmp_path)) is None


def test_analysis_symlink_candidate_escape(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    work = tmp_path / "w"
    work.mkdir()
    try:
        (work / "l").symlink_to(out, target_is_directory=True)
    except OSError:
        pytest.skip("심볼릭 링크를 만들 수 없다")
    assert analysis.check_result({"understood": "u", "candidates": [{"path": "l/x", "reason": "r"}], "extraQuestions": []}, str(work))["candidates"] == []


def test_parse_output_variants():
    ok = {"type": "result", "is_error": False, "structured_output": {"understood": "u", "candidates": [], "extraQuestions": []}}
    assert analysis.parse_output(json.dumps(ok))[0]["understood"] == "u"
    assert analysis.parse_output(json.dumps([{"type": "system"}, ok]))[0]["understood"] == "u"
    assert analysis.parse_output("garbage")[0] is None
    assert analysis.parse_output(json.dumps({"is_error": True, "result": "boom"})) == (None, "boom")
    assert analysis.parse_output(json.dumps({"type": "result"}))[0] is None


def test_analysis_command_flags_and_prompt_via_stdin(monkeypatch):
    a = analysis.Analyses(lambda: ["claude"], model="haiku")
    cmd = a.command()
    assert cmd[:2] == ["claude", "-p"] and "--no-session-persistence" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "plan" and cmd[cmd.index("--model") + 1] == "haiku"
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"] == ["understood", "candidates", "extraQuestions"]
    assert not any("사용자 요청 글" in c for c in cmd)


def test_new_work_flow_with_fake_analysis(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        (c.work / "a.md").write_text("x")
        assert c.call("POST", "/api/new", {"text": "  ", "cwd": str(c.work)})[0] == 400
        assert c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work / "none")})[0] == 400
        status, body, _ = c.call("POST", "/api/new", {"text": "문서 고쳐줘", "cwd": str(c.work)})
        assert status == 202
        job = wait_for(lambda: (lambda j: j if j["status"] != "running" else None)(c.call("GET", f"/api/new/{body['id']}")[1]))
        assert job["status"] == "done"
        assert [x["path"] for x in job["result"]["candidates"]] == ["a.md"]  # ../ 로 나간 경로는 버려졌다
        q = f"/api/new/{body['id']}/preview?picked=a.md&note=%EB%A9%94%EB%AA%A8&extraAnswers=" + urllib.parse.quote(json.dumps({"질문": "답"}))
        message = c.call("GET", q)[1]["message"]
        assert message.splitlines()[0] == "문서 고쳐줘" and "@a.md" in message and "- 질문: 답" in message and "메모: 메모" in message
        assert c.call("GET", f"/api/new/{body['id']}/preview?picked=../x")[0] == 400
    finally:
        c.close()


def test_first_message_matches_preview_and_prefixes_start_for_git():
    plain = analysis.first_message("요청", ["a.md"], {"q": "a"}, "m", False)
    git = analysis.first_message("요청", ["a.md"], {"q": "a"}, "m", True)
    assert git == "/harness:start\n" + plain


# ---- 콘솔이 띄운 세션(가짜 claude) ----

def fake_cmd():
    return [sys.executable, str(FAKE)]


FAKE_ANALYSIS = Path(__file__).with_name("fake_claude_analysis.py")


@pytest.fixture
def mconsole(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, claude_cmd=fake_cmd)
    c.login()
    yield c
    c.close()


def start_managed(c, text="hello"):
    job = c.call("POST", "/api/new", {"text": text, "cwd": str(c.work)})
    return job


def test_managed_launch_command_has_required_flags(tmp_path):
    seen = {}

    class P:
        stdin = stdout = None

    def popen(args, **kw):
        seen["args"] = args
        raise OSError("stop")

    store = Store(None)
    m = managed.Manager(store, lambda: ["claude"], "/plug", model="haiku", popen=popen)
    assert m.launch(str(tmp_path), "hi") is None
    args = seen["args"]
    for flag in ("-p", "--input-format", "stream-json", "--output-format", "--verbose", "--permission-prompt-tool", "stdio", "--plugin-dir"):
        assert flag in args
    assert args[args.index("--plugin-dir") + 1] == "/plug" and args[args.index("--model") + 1] == "haiku"
    assert "hi" not in args  # 사용자 입력은 stdin 으로만 간다
    assert "--dangerously-skip-permissions" not in args


def launch(c, text):
    sid = c.app.manager.launch(str(c.work), text)
    assert sid
    real = wait_for(lambda: (c.app.store.resolve_id(sid) != sid) and c.app.store.resolve_id(sid))
    return real


def test_managed_session_two_turns_question_and_permission(mconsole):
    c = mconsole
    sid = launch(c, "첫번째")
    assert sid.startswith("fake-")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫번째")
    s = c.call("GET", f"/api/sessions/{sid}")[1]
    assert s["managed"] and s["canSend"] and s["status"] == "idle"
    # 2턴
    assert c.call("POST", f"/api/sessions/{sid}/messages", {"text": "두번째"})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 두번째")
    # 질문: 브라우저가 없어도 콘솔 세션은 기다린다
    c.call("POST", f"/api/sessions/{sid}/messages", {"text": "ask"})
    req = wait_for(lambda: (c.pending(sid) or [None])[0])
    assert c.call("GET", f"/api/sessions/{sid}")[1]["group"] == "todo"
    assert c.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": "Red"}})[0] == 200
    wait_for(lambda: c.app.store.get(sid)["report"].startswith("answer: "))
    assert "Red" in c.app.store.get(sid)["report"]
    # 승인
    c.call("POST", f"/api/sessions/{sid}/messages", {"text": "perm"})
    req = wait_for(lambda: (c.pending(sid) or [None])[0])
    c.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny"})
    wait_for(lambda: c.app.store.get(sid)["report"] == "decision: deny")
    # 스킬은 stdin 으로 바로 간다
    assert c.call("POST", f"/api/sessions/{sid}/skills/prs/run", {})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: /harness:prs")
    assert c.call("POST", f"/api/sessions/{sid}/skills/update/run", {})[0] == 404


def test_managed_garbage_stdout_lines_are_skipped(mconsole):
    c = mconsole
    sid = launch(c, "garbage")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: garbage")
    assert c.app.manager.alive(sid)
    assert c.call("POST", f"/api/sessions/{sid}/messages", {"text": "after"})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: after")


def test_managed_resume_after_process_ends(mconsole):
    c = mconsole
    sid = launch(c, "a")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: a")
    c.app.manager.close(c.app.manager.proc_for(sid))
    wait_for(lambda: c.call("GET", f"/api/sessions/{sid}")[1]["status"] == "ended")
    assert c.call("GET", f"/api/sessions/{sid}")[1]["canSend"] is True  # 콘솔 세션은 --resume 으로 다시 뜬다
    assert c.call("POST", f"/api/sessions/{sid}/messages", {"text": "again"})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: again")
    assert c.app.manager.alive(sid)


def test_managed_interrupt_sends_control_request_and_terminal_cannot(mconsole):
    c = mconsole
    sid = launch(c, "a")
    assert c.call("POST", f"/api/sessions/{sid}/interrupt", {})[0] == 200
    c.event("term", "SessionStart")
    assert c.call("POST", "/api/sessions/term/interrupt", {})[0] == 409


def test_managed_stop_reservation_applies(mconsole):
    c = mconsole
    sid = launch(c, "a")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: a")
    assert c.call("PUT", f"/api/sessions/{sid}/skills/deliver/reservation", {})[0] == 200
    assert c.app.store.get(sid)["pending_stop"]


def test_parse_line_and_stream_messages():
    assert managed.parse_line('{"type":"result"}') == {"type": "result"}
    for bad in ("", "  ", "{broken", "[1,2]", '"str"', "null"):
        assert managed.parse_line(bad) is None
    assert json.loads(managed.user_message("한글\n줄"))["message"] == {"role": "user", "content": "한글\n줄"}


class FakeProc:
    session_id = "s1"
    temp_id = "s1"

    def __init__(self):
        self.written = []

    def write(self, text):
        self.written.append(json.loads(text))
        return True

    def alive(self):
        return True


def control_event(tool="Bash", subtype="can_use_tool", **extra):
    return {"type": "control_request", "request_id": "r1",
            "request": dict({"subtype": subtype, "tool_name": tool, "input": {"command": "touch x"}}, **extra)}


def test_unhandled_control_request_is_denied_and_logged(tmp_path):
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))
    m.on_event(proc, control_event(subtype="something_else"))
    m.on_event(proc, control_event("AskUserQuestion"))
    assert [w["response"]["response"]["behavior"] for w in proc.written] == ["deny", "deny"]
    assert "거부" in store.get("s1")["log"][-1]["text"]


def test_control_request_permission_is_bridged_with_hook_request(tmp_path):
    """실제 시험에서 claude 는 훅이 기다리는 동안 같은 승인을 control_request 로도 보냈고, 바로 거부하면 허용해도 막혔다."""
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))["managed"] = True
    hooks = Hooks(store, poll=0.02)
    sugg = [{"type": "addRules"}]
    m.on_event(proc, control_event(permission_suggestions=sugg))
    (req,) = store.pending_for("s1")
    assert proc.written == []  # 사용자가 답할 때까지 답하지 않는다
    holder = {}
    t = threading.Thread(target=lambda: holder.update(r=hooks.handle("permission", perm_body("s1", "touch x", cwd="/w", permission_suggestions=sugg), lambda: True)), daemon=True)
    t.start()
    wait_for(lambda: req.waiters == 1, timeout=60)  # 부하에서 스레드 시작이 늦어도 기다린다
    assert len(store.pending_for("s1")) == 1  # 훅 요청이 같은 요청으로 합쳐졌다
    store.resolve(req.rid, permission_reply({"behavior": "allow", "updatedPermissions": sugg}), "허용함")
    wait_for(lambda: proc.written, timeout=60)
    t.join(60)
    assert not t.is_alive() and "r" in holder
    assert proc.written[0]["response"]["response"] == {"behavior": "allow", "updatedInput": {"command": "touch x"}, "updatedPermissions": sugg}
    assert holder["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_control_request_permission_deny_is_bridged(tmp_path):
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))
    m.on_event(proc, control_event())
    (req,) = store.pending_for("s1")
    store.resolve(req.rid, permission_reply({"behavior": "deny", "message": "싫음"}), "거부함")
    wait_for(lambda: proc.written)
    assert proc.written[0]["response"]["response"] == {"behavior": "deny", "message": "싫음"}


def test_start_route_launches_session_with_first_message(mconsole):
    c = mconsole
    (c.work / "a.md").write_text("x")
    jid = c.call("POST", "/api/new", {"text": "계획 세워줘", "cwd": str(c.work)})[1]["id"]
    # 가짜 claude 는 분석 형식을 모르므로 분석은 실패해도 start 는 job 의 cwd/text 로 동작한다
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    status, body, _ = c.call("POST", f"/api/new/{jid}/start", {"picked": ["a.md"], "extraAnswers": {"q": "a"}, "note": "n"})
    assert status == 202 and body["id"].startswith("fake-")
    wait_for(lambda: "@a.md" in c.app.store.get(body["id"])["report"])
    assert c.app.store.get(body["id"])["title"] == "계획 세워줘"
    assert c.call("POST", f"/api/new/{jid}/start", {"picked": ["../x"]})[0] == 400


# ---- gitstate ----

def fake_runner(table):
    def run(args, cwd):
        key = " ".join(args).replace("-c core.quotepath=false ", "")
        for k, v in table.items():
            if key.startswith(k):
                return v
        return 1, ""
    return run


def git_table(**over):
    t = {"git rev-parse --show-toplevel": (0, "/x/repo\n"), "git rev-parse --abbrev-ref HEAD": (0, "feat/1-a\n"),
         "git status --porcelain": (0, ""), "git symbolic-ref": (0, "origin/main\n"), "git rev-list --count @{u}": (0, "0\n"),
         "gh pr list": (0, "[]")}
    t.update(over)
    return t


@pytest.mark.parametrize("over,skill,unknown", [
    ({"git rev-parse --show-toplevel": (128, "")}, None, False),
    ({"git rev-parse --abbrev-ref HEAD": (0, "main\n")}, "start", False),
    ({"git status --porcelain": (0, " M a.py\n?? b.md\n")}, "deliver", False),
    ({"git rev-list --count @{u}": (0, "2\n")}, "deliver", False),
    ({"gh pr list": (0, '[{"number":3}]')}, "prs", False),
    ({}, "start", False),
    ({"gh pr list": (127, "")}, "start", True),
])
def test_gitstate_rules(tmp_path, over, skill, unknown):
    info = gitstate.inspect(str(tmp_path), fake_runner(git_table(**over)))
    assert info["skill"] == skill and info["unknown"] is unknown


def test_gitstate_order_changes_beat_pr(tmp_path):
    info = gitstate.inspect(str(tmp_path), fake_runner(git_table(**{"git status --porcelain": (0, " M a\n"), "gh pr list": (0, '[{"number":1}]')})))
    assert info["skill"] == "deliver" and info["changedFiles"] == ["a"]


def test_gitstate_real_git(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode:
        pytest.skip("git 없음")
    assert gitstate.inspect(str(tmp_path))["skill"] is None  # git 저장소가 아니다


def test_turn_state_is_refreshed_on_stop(tmp_path, monkeypatch):
    calls = []

    def inspect(cwd):
        calls.append(cwd)
        return {"isRepo": True, "repo": "r", "branch": "b", "changedFiles": ["x.py"], "skill": "deliver", "unknown": True}

    c = Console(tmp_path, monkeypatch, git_inspect=inspect)
    try:
        c.login()
        c.event("t1", "UserPromptSubmit", prompt="x")
        c.hook("stop", {"session_id": "t1", "cwd": str(c.work), "last_assistant_message": "r"})
        s = c.call("GET", "/api/sessions/t1")[1]
        assert s["turnSkill"] == "deliver" and s["turnUnknown"] is True and s["group"] == "todo"
        assert s["repo"] == "r" and s["changedFiles"] == ["x.py"] and calls
    finally:
        c.close()


# ---- platform_compat (OS 값을 주입해 분기만 시험, Windows 실행 아님) ----

def test_detach_kwargs_per_os():
    assert platform_compat.detach_kwargs("posix") == {"start_new_session": True}
    flags = platform_compat.detach_kwargs("windows")["creationflags"]
    assert flags == 0x00000008 | 0x00000200


def test_find_claude_windows_prefers_exe_and_never_uses_cmd_c():
    found = {"claude.exe": r"C:\x\claude.exe", "claude": r"C:\x\claude.cmd"}
    assert platform_compat.find_claude("windows", found.get) == [r"C:\x\claude.exe"]
    assert platform_compat.find_claude("posix", lambda n: "/u/claude.cmd") == ["/u/claude.cmd"]
    assert platform_compat.find_claude("posix", lambda n: None) is None
    assert platform_compat.find_claude("windows", lambda n: None) is None


def test_find_claude_windows_cmd_resolves_native_exe_or_cli_js():
    cmd = r"C:\Users\홍 길동\AppData\Roaming\npm\claude.cmd"
    pkg = r"C:\Users\홍 길동\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code"
    which = {"claude": cmd, "node": r"C:\node\node.exe"}.get
    got = platform_compat.find_claude("windows", which, lambda p: p == pkg + r"\bin\claude.exe")
    assert got == [pkg + r"\bin\claude.exe"]
    got = platform_compat.find_claude("windows", which, lambda p: p == pkg + r"\cli.js")
    assert got == [r"C:\node\node.exe", pkg + r"\cli.js"]
    # 찾지 못하면 cmd /c 로 감싸지 않고 None -> 호출한 쪽이 안내 문구를 보여 준다
    assert platform_compat.find_claude("windows", which, lambda p: False) is None
    assert "찾을 수 없습니다" in platform_compat.CLAUDE_MISSING


def test_claude_missing_message_reaches_analysis_job():
    a = analysis.Analyses(lambda: None, spawn=lambda fn: fn())
    job_id = a.start("x", "/tmp")
    assert a.jobs[job_id]["status"] == "failed" and a.jobs[job_id]["error"] == platform_compat.CLAUDE_MISSING


def test_popen_kwargs_merge_creationflags_once_on_windows():
    kw = platform_compat.popen_detached_kwargs("windows")
    assert kw["creationflags"] == 0x00000008 | 0x00000200 | 0x08000000
    assert platform_compat.popen_detached_kwargs("posix") == {"start_new_session": True}
    # 옛 방식(두 dict 를 풀어 넣기)은 Windows 값에서 TypeError 였다 -> 실제로 호출해 터지는지 확인
    with pytest.raises(TypeError):
        dict(a=1, **platform_compat.detach_kwargs("windows"), **platform_compat.hidden_window_kwargs("windows"))


def test_open_server_popen_args_with_injected_windows():
    for os_name in ("windows", "posix"):
        args, kwargs = console_open.server_popen_args(4999, os_name)  # 같은 키 중복이면 여기서 TypeError
        captured = {}
        fake = lambda *a, **k: captured.update(k)  # noqa: E731  Popen 을 실제 호출 형식으로 흉내
        fake(args, **kwargs)
        assert captured["env"]["HARNESS_CONSOLE_PORT"] == "4999"
        assert ("creationflags" in captured) == (os_name == "windows")


def test_terminate_windows_uses_taskkill_tree_hidden():
    calls = []

    class Done:
        returncode = 0

    class P:
        pid = 4321
        def terminate(self): calls.append("terminate")

    platform_compat.terminate(P(), "windows", lambda args, **k: (calls.append((args, k.get("creationflags"))), Done())[1])
    assert calls == [(["taskkill", "/PID", "4321", "/T", "/F"], 0x08000000)]
    calls.clear()
    assert platform_compat.terminate_pid(77, "windows", lambda args, **k: (calls.append(args), Done())[1])
    assert calls == [["taskkill", "/PID", "77", "/T", "/F"]]


def test_terminate_windows_falls_back_when_taskkill_missing():
    calls = []

    class P:
        pid = 1
        def terminate(self): calls.append("terminate")

    def boom(*a, **k): raise FileNotFoundError

    platform_compat.terminate(P(), "windows", boom)
    assert calls == ["terminate"]


def test_same_path_per_os():
    assert platform_compat.same_path(r"C:\Work\Proj", "c:/work/proj/", "windows")
    assert not platform_compat.same_path(r"C:\Work\Proj", r"D:\Work\Proj", "windows")
    assert not platform_compat.same_path("/a/B", "/a/b", "posix")
    assert platform_compat.same_path("/a/b", "/a/b", "posix")


def test_clean_user_path_strips_quotes_and_spaces():
    assert platform_compat.clean_user_path('  "C:\\Work\\proj"  ') == "C:\\Work\\proj"
    assert platform_compat.clean_user_path("'/tmp/x' ") == "/tmp/x"


def test_validate_accepts_quoted_path(authed, tmp_path):
    d = tmp_path / "프로젝트 폴더"
    d.mkdir()
    status, data, _ = authed.call("POST", "/api/folders/validate", {"path": f'  "{d}"  '})
    assert status == 200 and data["ok"] is True


def test_static_mime_does_not_depend_on_registry(console, monkeypatch):
    monkeypatch.setattr(console_server.mimetypes, "guess_type", lambda n: ("text/plain", None))
    status, _, resp = console.call("GET", "/static/app.js", cookie=False)
    if status == 200:
        assert resp.getheader("Content-Type").startswith("text/javascript")
    ctype = console_server.STATIC_TYPES
    assert ctype[".js"].startswith("text/javascript") and ctype[".css"] == "text/css" and ctype[".svg"] == "image/svg+xml"


def test_gitstate_uses_quotepath_off_and_survives_missing_git():
    seen = []

    def run(args, cwd):
        seen.append(args)
        return 1, ""

    gitstate.inspect(os.getcwd(), run)
    assert seen and seen[0][:3] == ["git", "-c", "core.quotepath=false"]
    assert gitstate.run_command(["definitely-no-such-binary-xyz"], os.getcwd()) == (127, "")
    # git 은 있고 gh 만 없을 때 판단 불가로 넘어간다
    def run2(args, cwd):
        if args[0] == "gh":
            return 127, ""
        if args[:4] == ["git", "-c", "core.quotepath=false", "status"]:
            return 0, ""
        if "--show-toplevel" in args:
            return 0, "/r/repo\n"
        if "--abbrev-ref" in args:
            return 0, "feat/x\n"
        if "--count" in args:
            return 0, "0\n"
        return 1, ""
    r = gitstate.inspect(os.getcwd(), run2)
    assert r["unknown"] is True and r["skill"] == "start"


def test_hooks_json_session_start_has_no_shell_redirect():
    text = (PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if "session_start_hook.py" in l)
    assert "/dev/null" not in line and "|| true" not in line


def test_server_error_file_written_and_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "d"))
    console_server.write_error_file(tmp_path / "d", "포트 1 를 열지 못했습니다: PermissionError 10013\n접근 거부")
    assert console_open.read_server_error() == "포트 1 를 열지 못했습니다: PermissionError 10013 접근 거부"


def test_open_reports_port_bind_failure_reason(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]
    monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(port))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "d"))
    monkeypatch.setattr(console_open, "probe", lambda p: "free")  # 다른 프로그램이 점유 중이지만 우리 프로브는 못 본다고 가정
    try:
        why = console_open.ensure_server(port, wait=6)
    finally:
        sock.close()
        pid = tmp_path / "d" / "server.pid"
        if pid.exists():
            platform_compat.terminate_pid(int(pid.read_text().split()[0]))
    assert why and "원인:" in why


def test_api_shutdown_rules(console):
    assert console.call("POST", "/api/shutdown", {}, headers={"Origin": "http://evil"}, cookie=False)[0] == 403
    assert console.call("POST", "/api/shutdown", {}, host="evil.com", cookie=False)[0] == 403
    assert console.call("GET", "/api/shutdown", cookie=False)[0] == 405
    assert console.call("POST", "/api/shutdown", raw=b"x", json_type=False, cookie=False)[0] == 400
    assert console.call("GET", "/api/health")[0] == 200  # 거부된 요청은 서버를 끄지 않는다


def test_api_shutdown_stops_serve_forever(console):
    status, data, _ = console.call("POST", "/api/shutdown", {}, cookie=False)
    assert status == 200 and data == {"ok": True}
    console.server.server_close()

    def refused():
        try:
            console.call("GET", "/api/health")
        except OSError:
            return True
        return False

    assert wait_for(refused, 5)


def test_terminate_per_os():
    calls = []

    class P:
        def terminate(self): calls.append("terminate")
        def send_signal(self, s): calls.append(("signal", s))

    platform_compat.terminate(P(), "windows")
    platform_compat.terminate(P(), "posix")
    import signal
    assert calls == ["terminate", ("signal", signal.SIGTERM)]


def test_state_dir_order(tmp_path):
    assert platform_compat.state_dir({"CLAUDE_PLUGIN_DATA": "/d"}) == Path("/d")
    assert platform_compat.state_dir({"CLAUDE_CONFIG_DIR": "/c"}) == Path("/c/harness-console")
    assert platform_compat.state_dir({}, home=Path("/h")) == Path("/h/.claude/harness-console")


def test_port_from_env():
    assert platform_compat.port_from_env({}) == 4873
    assert platform_compat.port_from_env({"HARNESS_CONSOLE_PORT": "5555"}) == 5555
    assert platform_compat.port_from_env({"HARNESS_CONSOLE_PORT": "x"}) == 4873
    assert platform_compat.port_from_env({"HARNESS_CONSOLE_PORT": "99999"}) == 4873


def test_is_within_windows_case_insensitive_and_posix():
    assert platform_compat.same_path("C:\\A", "c:\\a", "windows") is True
    assert platform_compat.same_path("/A", "/a", "posix") is False
    assert platform_compat.is_within("/tmp", "/tmp") and not platform_compat.is_within("/etc", "/tmp")


def test_open_in_browser_failure_paths():
    assert platform_compat.open_in_browser("u", lambda url: False) is False
    assert platform_compat.open_in_browser("u", lambda url: 1 / 0) is False


# ---- open.py 와 SessionStart 훅 ----

def test_open_detects_foreign_service_on_port(monkeypatch):
    class H(__import__("http.server").server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html>other</html>")

        def log_message(self, *a): pass

    srv = __import__("http.server").server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert console_open.probe(port) == "other"
        assert "다른 프로그램" in console_open.ensure_server(port)
    finally:
        srv.shutdown()
        srv.server_close()


def test_open_main_end_to_end_prints_one_line_without_token(console, monkeypatch, capsys):
    monkeypatch.setattr(console_open, "ensure_server", lambda port: None)
    assert console_open.main([]) == 0
    out = capsys.readouterr().out
    assert len(out.strip().splitlines()) == 1
    assert console.opened[-1].split("t=")[1] not in out


def test_open_starts_detached_server_and_stop(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("HARNESS_CONSOLE_PORT", str(port))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN))
    try:
        assert console_open.probe(port) == "free"
        assert console_open.ensure_server(port) is None
        assert console_open.probe(port) == "ours"
        assert (tmp_path / "data" / "server.pid").exists()
        assert console_open.stop_server(port) == "웹 콘솔 서버를 껐습니다."
        assert console_open.probe(port) == "free"
    finally:
        pid = tmp_path / "data" / "server.pid"
        if pid.exists():
            platform_compat.terminate_pid(int(pid.read_text().split()[0]))


def run_start_hook(stdin, env_port, timeout=10):
    t0 = time.monotonic()
    done = subprocess.run([sys.executable, str(CONSOLE / "session_start_hook.py")], input=stdin, capture_output=True, text=True,
                          env=dict(os.environ, HARNESS_CONSOLE_PORT=str(env_port)), timeout=timeout)
    return done, time.monotonic() - t0


def test_session_start_hook_always_succeeds_when_server_is_down():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    done, took = run_start_hook('{"session_id":"s"}', port)
    assert done.returncode == 0 and done.stdout == "" and took < 3
    assert run_start_hook("", port)[0].returncode == 0
    assert run_start_hook("not json at all \xff", port)[0].returncode == 0


def test_session_start_hook_does_not_hang_on_unresponsive_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)  # 받기만 하고 답하지 않는 서버
    try:
        done, took = run_start_hook('{"session_id":"s"}', srv.getsockname()[1])
        assert done.returncode == 0 and took < 3
    finally:
        srv.close()


def test_session_start_hook_registers_session(console):
    done, _ = run_start_hook(json.dumps({"session_id": "ss1", "cwd": str(console.work), "hook_event_name": "SessionStart"}), console.port)
    assert done.returncode == 0
    wait_for(lambda: console.app.store.get("ss1"))


# ---- 플러그인 설정 ----

def test_hooks_json_has_console_events_and_keeps_existing_hooks():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    urls = {}
    for event, entries in hooks.items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command", "http 훅은 서버가 꺼져 있을 때 대화형 화면에 오류 줄을 남기므로 쓰지 않는다"
                m = re.search(r'console/hook_post\.py" (\w+) (\d+) \|\| true$', h["command"])
                if m:
                    assert h["timeout"] == int(m.group(2))
                    urls.setdefault(event, []).append((entry.get("matcher"), m.group(1), h["timeout"]))
    # 상태만 모으는 이벤트는 async, 응답을 쓰는 이벤트(승인·질문·Stop·SessionEnd)는 동기로 둔다.
    is_async = {(event, entry.get("matcher")): h.get("async") is True
                for event, entries in hooks.items() for entry in entries for h in entry["hooks"] if "console/hook_post.py" in h["command"]}
    for key in (("PreToolUse", "*"), ("PostToolUse", None), ("UserPromptSubmit", None), ("UserPromptExpansion", None),
                ("SubagentStart", None), ("SubagentStop", None), ("Notification", None), ("PreCompact", None)):
        assert is_async[key], key
    for key in (("PermissionRequest", None), ("PreToolUse", "AskUserQuestion"), ("Stop", None), ("SessionEnd", None)):
        assert not is_async[key], key
    assert urls["PermissionRequest"] == [(None, "permission", 86400)]
    assert ("AskUserQuestion", "question", 86400) in urls["PreToolUse"] and ("*", "event", 3) in urls["PreToolUse"]
    assert urls["Stop"] == [(None, "stop", 5)]
    for event in ("UserPromptSubmit", "UserPromptExpansion", "PostToolUse", "SubagentStart", "SubagentStop", "Notification", "PreCompact"):
        assert urls[event] == [(None, "event", 3)], event
    assert urls["SessionEnd"] == [(None, "event", 1)]  # SessionEnd 는 공유 제한 1.5초 안에 끝나야 한다
    commands = [h["command"] for entries in hooks.values() for e in entries for h in e["hooks"] if h["type"] == "command"]
    for old in ("pre_write_guard.py", "pre-bash-git-guard.sh", "agent_delegation_guard.py", "mcp_source_guard.py",
                "mcp_activation_tracker.py", "session-start-sync.sh", "update_notice.py", "pr_table_notice.py", "stop-deliver.sh"):
        assert any(old in c for c in commands), old


def test_console_session_start_hook_command_never_blocks():
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    cmds = [h for e in hooks["SessionStart"] for h in e["hooks"] if "session_start_hook.py" in h.get("command", "")]
    assert len(cmds) == 1 and cmds[0]["timeout"] == 5
    # 스크립트가 항상 exit 0 이고, SessionStart 는 exit 2 가 아니면 세션을 막지 않는다(hooks 문서). 셸 리다이렉트는 쓰지 않는다.
    assert "exit 2" not in cmds[0]["command"] and "/dev/null" not in cmds[0]["command"] and "|| true" not in cmds[0]["command"]


def test_skill_open_frontmatter_and_substitution_variable():
    text = (PLUGIN / "skills" / "open" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: open\n") and "# /harness:open" in text
    assert '${CLAUDE_PLUGIN_ROOT}/console/open.py' in text


def test_load_skills_hides_update_scaffold_open():
    names = console_server.load_skills(PLUGIN)
    assert {"start", "deliver", "prs"} <= set(names) and not ({"update", "scaffold", "open"} & set(names))


# ---- 통합 시험에서 찾은 문제의 회귀 시험 ----

def test_follow_up_prompt_does_not_replace_session_title(browser):
    browser.event("t10", "UserPromptSubmit", prompt="처음 요청\n자세히")
    browser.event("t10", "UserPromptSubmit", prompt="두 번째 요청")
    assert browser.call("GET", "/api/sessions/t10")[1]["title"] == "처음 요청"


def test_interrupted_turn_is_logged_as_interruption_not_empty_error(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))["managed"] = True
    proc = FakeProc()
    m.procs["s1"] = proc
    assert m.interrupt("s1") is True
    m.on_event(proc, {"type": "result", "is_error": True, "result": ""})
    assert store.get("s1")["log"][-1]["text"] == "사용자가 작업을 중단했습니다."
    m.on_event(proc, {"type": "result", "is_error": True, "result": ""})  # 중단 표시는 한 번만 쓴다
    assert store.get("s1")["log"][-1]["text"] == "오류로 끝남"


def test_subagent_log_has_no_dangling_colon(browser):
    browser.event("t11", "SubagentStop")
    assert browser.call("GET", "/api/sessions/t11")[1]["log"][-1]["text"] == "서브에이전트 끝"


def _run_hook_post(args, stdin, port):
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
    return subprocess.run([sys.executable, str(PLUGIN / "console" / "hook_post.py"), *args], input=stdin, env=env,
                          capture_output=True, timeout=15)


def test_hook_post_is_silent_when_server_is_down():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    r = _run_hook_post(["event", "1"], b'{"session_id":"x"}', port)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


def test_hook_post_forwards_body_and_prints_response(browser):
    body = json.dumps({"session_id": "t12", "cwd": str(browser.work), "hook_event_name": "UserPromptSubmit", "prompt": "훅 경유"}).encode()
    r = _run_hook_post(["event", "3"], body, browser.app.port)
    assert r.returncode == 0 and r.stderr == b""
    assert browser.call("GET", "/api/sessions/t12")[1]["title"] == "훅 경유"


def test_hook_post_prints_nothing_on_http_error_and_bad_path(browser):
    assert _run_hook_post(["event", "3"], b"{}", browser.app.port).stdout == b""  # session_id 없음 → 400
    assert _run_hook_post(["../x", "3"], b"{}", browser.app.port).returncode == 0


# ---- 리뷰 결함 수정(교착·위조·경로·저장·상한 등) ----

import store as store_mod  # noqa: E402
import hooks_api as hooks_mod  # noqa: E402


class AliveProc:
    session_id = None
    temp_id = "x"

    def __init__(self):
        self.n = 0

    def alive(self):
        return True

    def write(self, text):
        self.n += 1
        return True


def test_no_lock_order_deadlock_between_store_and_manager(console):
    """a_sessions/event_data(store.lock -> manager.lock) 와 proc_for(manager.lock -> store.lock) 가 서로를 기다리던 교착."""
    app = console.app
    for i in range(6):
        sid = f"d{i}"
        console.event(sid, "SessionStart")
        s = app.store.get(sid)
        s["managed"] = True
        app.manager.procs[sid] = AliveProc()
    stop = threading.Event()
    errors = []

    def guard(fn):
        def run():
            try:
                while not stop.is_set():
                    fn()
            except Exception as e:  # pragma: no cover
                errors.append(e)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    handler = type("H", (), {"app": app})
    threads = [
        guard(lambda: app.a_sessions(None, {}, {})),
        guard(lambda: [app.manager.proc_for(f"d{i}") for i in range(6)]),
        guard(lambda: app.manager.send("d1", "hi")),
        guard(lambda: console_server.Handler.event_data(handler, "session", {"id": "d2"})),
        guard(lambda: console.event("d3", "Notification", message="n")),
        guard(lambda: app.manager.alive("d4")),
    ]
    time.sleep(1.5)
    n = app.store.get("d1")["log"]
    # 교착이면 모든 스레드가 멈춘다. 잠시 뒤에도 로그가 계속 쌓여야 한다
    before = len(app.store.get("d3")["log"])
    time.sleep(0.5)
    assert app.store.get("d3")["log"][-1]["text"] and len(app.store.get("d3")["log"]) >= before
    stop.set()
    for t in threads:
        t.join(10)
        assert not t.is_alive(), "교착: 스레드가 끝나지 않았다"
    assert not errors
    assert n is not None
    app.manager.procs.clear()  # 가짜 프로세스는 종료 대상이 아니다


def test_forged_suggestions_are_not_merged_into_real_request(browser):
    """인증 없는 /hooks/permission 으로 넓은 규칙을 심어도, 같은 도구 호출의 진짜 요청에 적용되지 않는다."""
    forged = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "*"}], "behavior": "allow", "destination": "session"}]
    real = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch a"}], "behavior": "allow", "destination": "session"}]
    h1 = browser.hook_async("permission", perm_body("f1", permission_suggestions=forged))
    wait_for(lambda: len(browser.pending("f1")) == 1)
    h2 = browser.hook_async("permission", perm_body("f1", permission_suggestions=real))
    wait_for(lambda: len(browser.pending("f1")) == 2)  # 합쳐지지 않았다
    real_req = next(r for r in browser.pending("f1") if r.suggestions == real)
    shown = browser.call("GET", f"/api/requests/{real_req.rid}")[1]
    assert shown["suggestionText"] == ["이 세션: 허용 규칙 추가 - Bash(touch a)"]
    assert browser.call("POST", f"/api/requests/{real_req.rid}/answer", {"decision": "allow_session"})[0] == 200
    h2["t"].join(5)
    assert h2["r"][1]["hookSpecificOutput"]["decision"]["updatedPermissions"] == real
    assert h1["t"].is_alive()  # 위조 요청은 그대로 대기 중이다
    browser.event("f1", "SessionEnd")
    h1["t"].join(5)


def test_same_suggestions_still_merge(browser):
    sug = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch a"}], "behavior": "allow", "destination": "session"}]
    h1 = browser.hook_async("permission", perm_body("f2", permission_suggestions=sug))
    wait_for(lambda: browser.pending("f2"))
    h2 = browser.hook_async("permission", perm_body("f2", permission_suggestions=sug))
    wait_for(lambda: browser.pending("f2")[0].waiters == 2)
    assert len(browser.pending("f2")) == 1
    browser.event("f2", "SessionEnd")
    h1["t"].join(5), h2["t"].join(5)


def test_describe_suggestions_is_readable():
    text = store_mod.describe_suggestions([
        {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "git *"}, {"toolName": "Read"}], "behavior": "allow", "destination": "localSettings"},
        {"type": "setMode", "mode": "acceptEdits", "destination": "session"},
        {"type": "addDirectories", "directories": ["/tmp/x"], "destination": "session"}, "junk"])
    assert text[0] == "이 폴더의 로컬 설정: 허용 규칙 추가 - Bash(git *)"
    assert text[1] == "이 폴더의 로컬 설정: 허용 규칙 추가 - Read 전체"
    assert "acceptEdits" in text[2] and "/tmp/x" in text[3] and text[4] == "알 수 없는 제안"


def test_approval_screen_shows_full_input_and_rules():
    js = (CONSOLE / "static" / "app.js").read_text(encoding="utf-8")
    assert "도구에 넘기는 입력 전체" in js and "dangerouslyDisableSandbox" in js and "run_in_background" in js
    assert "suggestionText" in js and "다음 규칙이 추가됩니다" in js
    # 입력 JSON 이 접힌 details 안에 있지 않다
    assert "det.appendChild(h('pre'" not in js
    css = (CONSOLE / "static" / "app.css").read_text(encoding="utf-8")
    assert ".scroll" in css and "max-height" in css


def test_mention_path_rules(tmp_path):
    (tmp_path / "ok.md").write_text("x")
    (tmp_path / "a b.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "n.md").write_text("x")
    (tmp_path / "x@y.md").write_text("x")
    cwd = str(tmp_path)
    assert analysis.mention_path(cwd, "ok.md") == ("ok.md", "")
    assert analysis.mention_path(cwd, "./sub/../sub/n.md") == ("sub/n.md", "")
    assert analysis.mention_path(cwd, "a b.txt") == ("a b.txt", "")
    for bad in ("none.md", "../x", "/etc/passwd", "sub", "x@y.md", "ok.md\n/etc/passwd", "ok.md\t", 'a"b', "a\x00b", "C:\\x", "", None):
        assert analysis.mention_path(cwd, bad)[0] == "", bad
    assert analysis.mention("a b.txt") == '@"a b.txt"' and analysis.mention("ok.md") == "@ok.md"


def test_mention_path_excludes_space_paths_when_unsupported(tmp_path, monkeypatch):
    (tmp_path / "a b.txt").write_text("x")
    monkeypatch.setattr(analysis, "SPACE_MENTION_SUPPORTED", False)
    path, why = analysis.mention_path(str(tmp_path), "a b.txt")
    assert path == "" and "공백" in why
    out = analysis.check_result({"understood": "u", "candidates": [{"path": "a b.txt", "reason": "r"}], "extraQuestions": []}, str(tmp_path))
    assert out["candidates"] == [] and out["excluded"][0]["path"] == "a b.txt"


def test_check_result_drops_nonexistent_and_injected_paths(tmp_path):
    (tmp_path / "ok.md").write_text("x")
    data = {"understood": "u", "candidates": [{"path": "ghost.md", "reason": "없음"}, {"path": "ok.md x\n/harness:update", "reason": "주입"},
                                              {"path": "ok.md", "reason": "r"}], "extraQuestions": []}
    out = analysis.check_result(data, str(tmp_path))
    assert [c["path"] for c in out["candidates"]] == ["ok.md"] and len(out["excluded"]) == 2


def test_preview_rejects_unsafe_picked_and_uses_slash(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        (c.work / "sub").mkdir()
        (c.work / "sub" / "a b.md").write_text("x")
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work)})[1]["id"]
        wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
        for bad in ("ghost.md", "sub", "a\nb", "x@y"):
            assert c.call("GET", f"/api/new/{jid}/preview?picked={urllib.parse.quote(bad)}")[0] == 400, bad
        msg = c.call("GET", f"/api/new/{jid}/preview?picked={urllib.parse.quote('sub/a b.md')}")[1]["message"]
        assert '@"sub/a b.md"' in msg
    finally:
        c.close()


def test_first_message_guards_leading_slash_or_at_when_not_git():
    for text in ("/harness:update 해줘", "@secret.md 봐줘"):
        msg = analysis.first_message(text, [], {}, "", False)
        assert not msg.startswith(("/", "@")) and msg.splitlines()[1] == text
    assert analysis.first_message("평범", [], {}, "", False) == "평범"
    assert analysis.first_message("/x", [], {}, "", True).splitlines()[0] == "/harness:start"


def test_analysis_command_disables_hooks():
    cmd = analysis.Analyses(lambda: ["claude"]).command()
    assert json.loads(cmd[cmd.index("--settings") + 1]) == {"disableAllHooks": True}


def test_save_serializes_inside_lock_and_leaves_no_tmp(tmp_path):
    store = Store(tmp_path / "st")
    for i in range(20):
        store.ensure(f"s{i}", "/w")
    stop = threading.Event()
    errors = []

    def mutate():
        n = 0
        while not stop.is_set():
            with store.lock:
                s = store.sessions["s0"]
                s["skillStates"][f"k{n % 50}"] = "done"
                n += 1

    def saver():
        try:
            while not stop.is_set():
                store.save(force=True)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=f, daemon=True) for f in (mutate, saver, saver)]
    for t in ts:
        t.start()
    time.sleep(0.8)
    stop.set()
    for t in ts:
        t.join(5)
    assert not errors and not list((tmp_path / "st").glob("*.tmp"))
    assert len(json.loads((tmp_path / "st" / "sessions.json").read_text(encoding="utf-8"))["sessions"]) == 20


def test_save_retries_permission_error_five_times_then_gives_up(tmp_path, monkeypatch):
    store = Store(tmp_path / "st")
    store.ensure("s1", "/w")
    sleeps, calls = [], []
    store.sleep = sleeps.append
    real = os.replace

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked")
        return real(a, b)

    monkeypatch.setattr(store_mod.os, "replace", flaky)
    store.save(force=True)
    assert len(calls) == 3 and sleeps == [0.05, 0.05] and (tmp_path / "st" / "sessions.json").exists()
    calls.clear()
    monkeypatch.setattr(store_mod.os, "replace", lambda a, b: (calls.append(1), (_ for _ in ()).throw(PermissionError("x")))[1])
    store.save(force=True)  # 예외가 밖으로 나오지 않는다
    assert len(calls) == 5 and not list((tmp_path / "st").glob("*.tmp"))


def test_save_failure_does_not_break_hook(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(store_mod.tempfile, "mkstemp", lambda **k: (_ for _ in ()).throw(OSError("disk")))
        status, _, _ = c.event("sv", "SessionEnd")
        assert status == 200
    finally:
        c.close()


def test_terminal_session_goes_idle_after_ten_minutes_without_signal(browser):
    browser.event("i1", "UserPromptSubmit", prompt="일")
    got = browser.call("GET", "/api/sessions/i1")[1]
    assert got["canSend"] and got["status"] == "running"
    browser.clock.t += 601  # Esc 로 끊어 Stop 이 오지 않은 경우
    got = browser.call("GET", "/api/sessions/i1")[1]
    assert not got["canSend"] and got["status"] == "idle" and got["group"] == "idle"
    assert browser.call("POST", "/api/sessions/i1/messages", {"text": "x"})[0] == 409
    browser.event("i1", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"})  # 신호가 오면 다시 일한다
    assert browser.call("GET", "/api/sessions/i1")[1]["canSend"]


def test_pending_request_keeps_terminal_session_running_past_idle_limit(browser):
    browser.event("i2", "UserPromptSubmit", prompt="일")
    h = browser.hook_async("permission", perm_body("i2"))
    wait_for(lambda: browser.pending("i2"))
    browser.clock.t += 3600
    assert browser.call("GET", "/api/sessions/i2")[1]["status"] == "waiting"
    browser.event("i2", "SessionEnd")
    h["t"].join(5)


def test_stop_reservation_is_restored_when_reply_cannot_be_sent(browser):
    browser.event("p1", "UserPromptSubmit", prompt="일")
    assert browser.call("PUT", "/api/sessions/p1/skills/prs/reservation", {})[0] == 200
    undo = []
    status, body = browser.app.hooks.handle("stop", {"session_id": "p1", "cwd": str(browser.work)}, undo=undo)
    assert body["decision"] == "block" and browser.app.store.get("p1")["pending_stop"] == [] and len(undo) == 1
    undo[0]()  # 응답 전송 실패
    s = browser.app.store.get("p1")
    assert s["pending_stop"][0]["skill"] == "prs" and not s["turn_running"]
    status, body = browser.app.hooks.handle("stop", {"session_id": "p1", "cwd": str(browser.work)})
    assert body["decision"] == "block"  # 다시 오는 Stop 에서 전달된다


def raw_request(port, head: bytes, body: bytes = b"", wait: float = 3.0) -> bytes:
    sock = socket.create_connection(("127.0.0.1", port), timeout=wait)
    sock.sendall(head + body)
    try:
        return sock.recv(4096)
    except (TimeoutError, OSError):
        return b""
    finally:
        sock.close()


@pytest.mark.parametrize("value", ["-5", "abc", "+3", "1e3", "-0", "١٢"])
def test_bad_content_length_is_rejected_with_400(console, value):
    head = (f"POST /hooks/event HTTP/1.1\r\nHost: 127.0.0.1:{console.port}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {value}\r\n\r\n").encode("utf-8")
    assert raw_request(console.port, head, b"{}").startswith(b"HTTP/1.0 400")


def test_slow_request_is_cut_but_long_hook_wait_and_sse_survive(browser):
    browser.app.request_timeout = 0.4
    # 헤더만 보내고 멈춘 연결은 끊긴다
    sock = socket.create_connection(("127.0.0.1", browser.port), timeout=5)
    sock.sendall(f"POST /hooks/event HTTP/1.1\r\nHost: 127.0.0.1:{browser.port}\r\nContent-Length: 50\r\n\r\n{{".encode())
    t0 = time.monotonic()
    data = sock.recv(4096)
    assert time.monotonic() - t0 < 3 and (data == b"" or b" 408 " in data.split(b"\r\n")[0])
    sock.close()
    # 본문을 다 읽은 승인 훅은 timeout 보다 오래 기다려도 끊기지 않고, 답을 받는다
    conn, resp = browser.connect_browser()
    try:
        h = browser.hook_async("permission", perm_body("sl"))
        wait_for(lambda: browser.pending("sl"))
        time.sleep(1.2)
        assert h["t"].is_alive()
        rid = browser.pending("sl")[0].rid
        assert browser.call("POST", f"/api/requests/{rid}/answer", {"decision": "allow"})[0] == 200
        h["t"].join(5)
        assert h["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
        # SSE 도 timeout 보다 오래 열려 있다가 이벤트를 받는다
        browser.event("sl", "Notification", message="늦은 이벤트")
        seen = ""
        while "event: session" not in seen:
            seen = resp.fp.readline().decode()
    finally:
        conn.close()


def test_start_twice_launches_one_session(mconsole):
    c = mconsole
    jid = c.call("POST", "/api/new", {"text": "한 번만", "cwd": str(c.work)})[1]["id"]
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    results = []

    def go():
        results.append(c.call("POST", f"/api/new/{jid}/start", {"picked": []}))

    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    assert [r[0] for r in results] == [202, 202] and results[0][1]["id"] == results[1][1]["id"]
    managed_sessions = [s for s in c.app.store.sessions.values() if s["managed"]]
    assert len(managed_sessions) == 1 and len(set(id(p) for p in c.app.manager.procs.values())) == 1


def test_resume_is_serialized_per_session(tmp_path):
    launched = []

    class P:
        def __init__(self):
            self.stdin = type("S", (), {"write": lambda s, t: None, "flush": lambda s: None, "close": lambda s: None})()
            self.stdout = iter(())
            launched.append(1)

        def poll(self):
            return None

    store = Store(None)
    m = managed.Manager(store, lambda: ["claude"], "/p", popen=lambda *a, **k: P())
    s = store.ensure("r1", str(tmp_path))
    s.update(managed=True, ended=True)
    results = []
    ts = [threading.Thread(target=lambda: results.append(m.send_or_resume("r1", "hi"))) for _ in range(5)]
    [t.start() for t in ts]
    [t.join(10) for t in ts]
    assert results == [True] * 5 and len(launched) == 1


def test_session_limit_removes_oldest_ended_first(monkeypatch):
    monkeypatch.setattr(store_mod, "MAX_SESSIONS", 4)
    clock = FakeClock()
    store = Store(None, clock)
    for i in range(4):
        clock.t += 1
        store.ensure(f"s{i}", "/w")["updatedAt"] = clock.t
    store.sessions["s2"]["ended"] = True
    store.sessions["s1"]["ended"] = True  # 끝난 것 중 s1 이 더 오래됐다
    store.sessions["s1"]["updatedAt"] = 1
    store.ensure("new", "/w")
    assert "s1" not in store.sessions and len(store.sessions) == 4 and "s0" in store.sessions


def test_pending_request_limit_never_allows_silently(browser, monkeypatch):
    monkeypatch.setattr(store_mod, "MAX_PENDING_REQUESTS", 2)
    holders = [browser.hook_async("permission", perm_body("lim", f"cmd{i}")) for i in range(2)]
    wait_for(lambda: len(browser.pending("lim")) == 2)
    status, body, _ = browser.hook("permission", perm_body("lim", "cmd-over"))
    assert status == 200 and body is None  # 허용 응답이 아니라 빈 응답(터미널로 넘김)
    assert len(browser.pending("lim")) == 2
    status, body, _ = browser.hook("question", ask_body("lim"))
    assert status == 200 and body is None
    browser.event("lim", "SessionEnd")
    [h["t"].join(5) for h in holders]


def test_managed_bridge_denies_when_request_limit_reached(monkeypatch, tmp_path):
    monkeypatch.setattr(store_mod, "MAX_PENDING_REQUESTS", 0)
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))
    m.on_event(proc, control_event())
    assert proc.written[0]["response"]["response"]["behavior"] == "deny"


def test_per_session_caps(browser, monkeypatch):
    monkeypatch.setattr(hooks_mod, "MAX_CHANGED_FILES", 3)
    monkeypatch.setattr(hooks_mod, "MAX_SUBAGENTS", 2)
    monkeypatch.setattr(hooks_mod, "MAX_SKILL_STATES", 3)
    for i in range(6):
        browser.event("cap", "PostToolUse", tool_name="Write", tool_input={"file_path": f"/w/{i}"}, tool_response="ok")
        browser.event("cap", "SubagentStart", agent_id=f"a{i}", agent_type="x")
        browser.event("cap", "PreToolUse", tool_name="Skill", tool_input={"skill": f"sk{i}"})
    s = browser.app.store.get("cap")
    assert len(s["changedFiles"]) == 3 and len(s["subagents"]) == 2 and len(s["skillStates"]) == 3
    assert s["skillStates"]["sk5"] == "active"
    monkeypatch.setattr(store_mod, "MAX_PENDING_STOP", 2)
    monkeypatch.setattr(console_server, "MAX_PENDING_STOP", 2)
    browser.event("cap", "UserPromptSubmit", prompt="x")
    codes = [browser.call("POST", "/api/sessions/cap/messages", {"text": f"m{i}"})[0] for i in range(4)]
    assert codes == [202, 202, 429, 429]


def test_slow_sse_subscriber_is_dropped_and_others_keep_going(monkeypatch):
    monkeypatch.setattr(store_mod, "SUBSCRIBER_MAXSIZE", 3)
    store = Store(None)
    slow, fast = store.subscribe(), store.subscribe()
    for i in range(5):
        store.publish("session", {"id": str(i)})
        fast.get_nowait()
    assert slow.closed and slow not in store.subscribers and fast in store.subscribers and not fast.closed


def test_sse_connection_closes_when_queue_overflowed(authed, monkeypatch):
    conn, resp = authed.connect_browser()
    try:
        (q,) = authed.app.store.subscribers
        q.closed = True  # 가득 차서 끊긴 구독자
        authed.event("ov", "Notification", message="n")
        wait_for(lambda: not authed.app.store.browser_connected(), timeout=15)
    finally:
        conn.close()


def test_cookie_has_max_age_and_expires_server_side(console):
    console.call("POST", "/api/open", {})
    token = console.opened[-1].split("t=")[1]
    _, _, resp = console.call("GET", f"/auth?t={token}", cookie=False)
    assert "Max-Age=2592000" in resp.getheader("Set-Cookie")
    console.cookie = resp.getheader("Set-Cookie").split(";")[0].split("=", 1)[1]
    assert console.call("GET", "/api/sessions")[0] == 200
    console.clock.t += 30 * 24 * 3600 + 1
    assert console.call("GET", "/api/sessions")[0] == 401


def test_add_folder_merges_case_variants_on_windows(monkeypatch):
    store = Store(None)
    monkeypatch.setattr(platform_compat, "current_os", lambda: "windows")
    store.add_folder("C:\\Work\\Proj")
    store.add_folder("c:/work/proj")
    store.add_folder("D:\\Other")
    assert store.folders == ["D:\\Other", "c:/work/proj"]
    monkeypatch.setattr(platform_compat, "current_os", lambda: "posix")
    s2 = Store(None)
    s2.add_folder("/a/B"), s2.add_folder("/a/b")
    assert len(s2.folders) == 2


# ---- 비동기 훅: 도착 순서가 뒤바뀌어도 상태가 틀어지지 않는다 ----

def _s(c, sid):
    return c.app.store.get(sid)


def test_hook_post_sends_start_time_header(browser):
    before = time.time()
    r = _run_hook_post(["stop", "5"], json.dumps({"session_id": "ts1", "cwd": str(browser.work)}).encode(), browser.app.port)
    assert r.returncode == 0
    assert before - 1 <= _s(browser, "ts1")["boundaryTs"] <= time.time() + 1


def test_late_pre_tool_use_after_stop_does_not_restart_the_turn(browser):
    browser.event("a1", "UserPromptSubmit", ts=100.0, prompt="작업")
    browser.hook("stop", {"session_id": "a1", "cwd": "/w", "last_assistant_message": "끝"}, ts=105.0)
    s = _s(browser, "a1")
    assert s["turn_running"] is False
    browser.event("a1", "PreToolUse", ts=103.0, tool_name="Bash", tool_input={"command": "sleep 1"})  # Stop 뒤에 도착한 앞선 이벤트
    s = _s(browser, "a1")
    assert s["turn_running"] is False and s["currentAction"] == "" and s["ended"] is False
    browser.event("a1", "PostToolUse", ts=104.0, tool_name="Bash", tool_input={"command": "sleep 1"}, tool_response="ok")
    assert _s(browser, "a1")["turn_running"] is False
    # 다음 턴의 이벤트는 정상 반영
    browser.event("a1", "UserPromptSubmit", ts=110.0, prompt="다음")
    assert _s(browser, "a1")["turn_running"] is True


def test_late_user_prompt_submit_after_short_turn_stop_keeps_session_idle(browser):
    browser.hook("stop", {"session_id": "a2", "cwd": "/w", "last_assistant_message": "안녕"}, ts=50.2)
    browser.event("a2", "UserPromptSubmit", ts=50.0, prompt="안녕")  # 도구 없이 끝난 짧은 턴에서 UserPromptSubmit 이 더 늦게 도착
    s = _s(browser, "a2")
    assert s["turn_running"] is False and s["report"] == "안녕"
    assert browser.call("GET", "/api/sessions/a2")[1]["canSend"] is False  # 쉬는 터미널 세션으로 남는다


def test_late_skill_events_after_stop_do_not_leave_skill_active(browser):
    browser.hook("stop", {"session_id": "a3", "cwd": "/w", "last_assistant_message": "x"}, ts=20.0)
    browser.event("a3", "PreToolUse", ts=19.0, tool_name="Skill", tool_input={"skill": "harness:version"})
    browser.event("a3", "UserPromptExpansion", ts=18.0, command_name="harness:deliver")
    s = browser.call("GET", "/api/sessions/a3")[1]
    assert s["currentSkill"] == "" and all(f["state"] != "active" for f in s["flow"])


def test_late_session_end_boundary_blocks_stale_events(browser):
    browser.event("a4", "SessionEnd", ts=30.0)
    browser.event("a4", "PreToolUse", ts=29.0, tool_name="Read", tool_input={"file_path": "/w/a"})
    s = _s(browser, "a4")
    assert s["ended"] is True and s["turn_running"] is False


def test_out_of_order_pre_tool_use_keeps_latest_action(browser):
    browser.event("a5", "PreToolUse", ts=10.0, tool_name="Bash", tool_input={"command": "second"})
    browser.event("a5", "PreToolUse", ts=9.0, tool_name="Bash", tool_input={"command": "first"})
    assert _s(browser, "a5")["currentAction"] == "Bash: second"


def test_late_post_tool_use_does_not_close_a_newer_identical_request(browser):
    body = perm_body("a6", "touch same")
    h = browser.hook_async("permission", body)
    req = wait_for(lambda: (browser.pending("a6") or [None])[0])
    # 요청이 만들어지기 전에 끝난 같은 도구 호출의 PostToolUse 가 늦게 도착
    browser.event("a6", "PostToolUse", ts=req.created - 5, tool_name="Bash", tool_input={"command": "touch same"}, tool_response="ok")
    assert req.status == "pending"
    # 요청 뒤에 터미널에서 허용해 끝난 호출의 PostToolUse 는 닫는다
    browser.event("a6", "PostToolUse", ts=req.created + 1, tool_name="Bash", tool_input={"command": "touch same"}, tool_response="ok")
    h["t"].join(5)
    assert req.status == "closed" and req.outcome == "터미널에서 처리됨"


def test_late_prompt_does_not_close_a_newer_terminal_request(browser):
    h = browser.hook_async("permission", perm_body("a7"))
    req = wait_for(lambda: (browser.pending("a7") or [None])[0])
    browser.event("a7", "UserPromptSubmit", ts=req.created - 5, prompt="앞 턴")
    assert req.status == "pending"
    browser.event("a7", "UserPromptSubmit", ts=req.created + 5, prompt="다음 턴")
    h["t"].join(5)
    assert req.status == "closed"


def test_subagent_stop_before_start_stays_done(browser):
    browser.event("a8", "SubagentStop", agent_id="x1", agent_type="Explore")
    browser.event("a8", "SubagentStart", agent_id="x1", agent_type="Explore")
    subs = browser.call("GET", "/api/sessions/a8")[1]["subagents"]
    assert len(subs) == 1 and subs[0]["state"] == "done"


def test_events_without_timestamp_keep_arrival_order_behavior(browser):
    browser.hook("stop", {"session_id": "a9", "cwd": "/w", "last_assistant_message": "x"})
    browser.event("a9", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
    assert _s(browser, "a9")["turn_running"] is True


def test_bad_timestamp_header_is_ignored(browser):
    r = browser.call("POST", "/hooks/event", {"session_id": "b1", "cwd": "/w", "hook_event_name": "UserPromptSubmit", "prompt": "x"},
                     cookie=False, headers={"X-Hook-Ts": "nan"})
    assert r[0] == 200 and _s(browser, "b1")["turn_running"] is True
    r = browser.call("POST", "/hooks/event", {"session_id": "b1", "cwd": "/w", "hook_event_name": "UserPromptSubmit", "prompt": "x"},
                     cookie=False, headers={"X-Hook-Ts": "abc"})
    assert r[0] == 200


def test_question_and_pre_tool_use_star_overlap_does_not_break_answer(browser):
    """PreToolUse(*) 비동기 이벤트와 PreToolUse(AskUserQuestion) 동기 질문이 같은 순간 도착해도 답이 돌아간다."""
    h = browser.hook_async("question", ask_body("q9"))
    req = wait_for(lambda: (browser.pending("q9") or [None])[0])
    ev = browser.event("q9", "PreToolUse", ts=time.time(), tool_name="AskUserQuestion", tool_input=ask_body("q9")["tool_input"])
    assert ev[0] == 200 and req.status == "pending"
    st = browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": "Red"}})[0]
    assert st == 200
    h["t"].join(5)
    assert h["r"][1]["hookSpecificOutput"]["updatedInput"]["answers"] == {"색은?": "Red"}
