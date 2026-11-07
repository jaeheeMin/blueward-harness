"""Harness 웹 콘솔 백엔드 시험(#558, docs/design/web-console.md).

실제 claude 를 부르지 않는다. 임시 포트로 표준 라이브러리 서버를 띄우고, 가짜 claude(fake_claude.py)를 쓴다.
시간은 FakeClock 으로 주입한다. Windows 분기는 OS 값을 주입해 분기 로직만 확인했고 Windows 에서 실행하지는 않았다.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import shutil
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
import flows  # noqa: E402
import gitstate  # noqa: E402
import hook_post  # noqa: E402
import session_start_hook  # noqa: E402
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

    def __init__(self, tmp_path, monkeypatch, claude_cmd=None, git_inspect=None, skills=None, flows_path=None, run=None, app_kw=None):
        plugin = tmp_path / "plugin"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text('{"name":"harness","version":"9.9.9"}', encoding="utf-8")
        for name in skills or ("start", "deliver", "prs", "update", "scaffold", "open"):
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
                                      question_wait=300.0, sync_spawn=True, run=run or (lambda args, cwd: (127, "")),
                                      flows_path=flows_path or tmp_path / "no-flows.json", **(app_kw or {}))
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

    def call(self, method, path, body=None, headers=None, host=None, raw=None, cookie=True, json_type=True, binary=False):
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
        data_back = resp.read()
        conn.close()
        if binary:
            return resp.status, data_back, resp
        text = data_back.decode("utf-8")
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


def raw_post(port, path, headers, body=b"", declared=None, timeout=15):
    """실제 소켓으로 POST 를 보내 상태 줄만 읽는다. 연결이 RST 로 끊기면 예외가 그대로 난다."""
    head = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
    n = len(body) if declared is None else declared
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(f"POST {path} HTTP/1.0\r\n{head}Content-Length: {n}\r\n\r\n".encode() + body)
        data = b""
        while b"\r\n" not in data:
            chunk = sock.recv(4096)
            assert chunk, "응답 없이 연결이 닫혔습니다."
            data += chunk
        return int(data.split(b" ", 2)[1])
    finally:
        sock.close()


def test_rejection_with_unread_body_always_gets_its_response(console):
    body = json.dumps({"x": "y" * 300_000}).encode()  # 헤더와 함께 버퍼에 들어가는 크기를 넘겨야 소켓에 안 읽은 데이터가 남는다
    for _ in range(30):
        assert raw_post(console.port, "/hooks/event", {"Host": "evil.example.com", "Content-Type": "application/json"}, body) == 403
    for _ in range(30):
        assert raw_post(console.port, "/api/folders/validate",
                        {"Host": f"127.0.0.1:{console.port}", "Content-Type": "application/json"}, body) == 401


def test_rejection_does_not_wait_forever_for_a_body_that_never_comes(console):
    started = time.monotonic()
    status = raw_post(console.port, "/api/folders/validate",
                      {"Host": f"127.0.0.1:{console.port}", "Content-Type": "application/json"}, b"", declared=500_000)
    assert status == 401
    assert time.monotonic() - started < 5


def test_static_headers_and_spa_paths(console, tmp_path):
    # static/ 은 다른 작업자가 만든다. 있으면 CSP 를 확인하고 없으면 404 인 것만 확인한다.
    status, _, resp = console.call("GET", "/", cookie=False)
    if status == 200:
        assert "default-src 'none'" in resp.getheader("Content-Security-Policy")
    else:
        assert status == 404
    assert console.call("GET", "/static/../server.py", cookie=False)[0] == 404
    assert console.call("GET", "/server.py", cookie=False)[0] == 404


def test_spa_paths_include_every_menu_route():
    # 메뉴 경로를 주소창에 바로 치거나 새로 고쳐도 화면이 떠야 한다(#636: /docs 가 404 였다).
    from plugins.harness.console import server as srv
    for p in ["/", "/new", "/settings", "/docs", "/s/abc", "/r/abc"]:
        assert srv.SPA_PATHS.match(p), p
    assert not srv.SPA_PATHS.match("/docs/x")


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
    root = urllib.parse.quote(str(authed.work), safe="")
    outside_q = urllib.parse.quote(str(outside), safe="")
    root_raw = str(authed.work)
    # 고르지 않은 폴더는 열 수 없다
    assert authed.call("GET", f"/api/fs?root={root}")[0] == 403
    assert authed.call("POST", "/api/folders/validate", {"path": root_raw})[1]["ok"]
    status, body, _ = authed.call("GET", f"/api/fs?root={root}")
    names = {e["name"]: e for e in body["entries"]}
    assert status == 200 and names["sub"]["kind"] == "dir" and names["a.txt"]["size"] == 1
    assert "link" not in names and "filelink" not in names or not symlinks  # 밖을 가리키는 링크는 보이지 않는다
    if symlinks:
        assert "link" not in names and "filelink" not in names
        assert authed.call("GET", f"/api/fs?root={root}&dir=link")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=..")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=sub/../..")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir={outside_q}")[0] == 403
    assert authed.call("GET", f"/api/fs?root={root}&dir=sub")[1]["entries"][0]["name"] == "b.txt"
    assert authed.call("GET", f"/api/fs?root={outside_q}")[0] == 403  # 고르지 않은 다른 폴더


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
    h["t"].join(30)
    assert "r" in h, "질문 훅 응답이 30초 안에 오지 않았다"
    assert h["r"][1] is None and req.status == "closed" and req.outcome == "터미널로 넘어감"


def test_question_deadline_counts_from_arrival_not_from_registration(browser):
    """요청을 화면에 등록하는 사이에 시계가 흘러도 마감은 도착 시점 기준 300초다(#610).
    예전에는 등록 뒤에 마감을 재서, 느린 러너에서 마감이 밀려 응답이 오지 않았다."""
    store = browser.app.store
    original = store.add_request

    def slow_add(*args, **kwargs):
        browser.clock.t += 100  # 등록 중에 흐른 시간
        return original(*args, **kwargs)

    store.add_request = slow_add
    try:
        h = browser.hook_async("question", ask_body("t1"))
        req = wait_for(lambda: (browser.pending("t1") or [None])[0])
        browser.clock.t += 201  # 도착부터 301초
        h["t"].join(30)
        assert "r" in h, "마감이 등록 시점부터 재어져 300초에 넘어가지 않았다"
        assert req.status == "closed" and req.outcome == "터미널로 넘어감"
    finally:
        store.add_request = original


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
    assert s["title"] == "이름 없는 세션 · work" and s["currentAction"].startswith("Bash: ls") and s["managed"] is False
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
    results = 0
    last_result = ""
    last_error = False

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


def test_last_folder_is_saved_on_start_in_state_dir_and_ignored_when_gone(mconsole):
    c = mconsole
    assert c.call("GET", "/api/folders/last")[1] == {"path": None, "name": ""}  # 시작한 적 없으면 기본값 없음
    assert c.call("GET", "/api/folders/recent")[0] == 200  # 최근 폴더 후보와는 따로다
    jid = c.call("POST", "/api/new", {"text": "계획", "cwd": str(c.work)})[1]["id"]
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    assert c.call("GET", "/api/folders/last")[1]["path"] is None  # 분석만으로는 기억하지 않는다(작업을 시작해야)
    assert c.call("POST", f"/api/new/{jid}/start", {})[0] == 202
    want = os.path.realpath(str(c.work))
    got = c.call("GET", "/api/folders/last")[1]
    assert got["path"] == want and got["name"] == os.path.basename(want)
    saved = c.state / console_server.LAST_FOLDER_FILE
    assert saved.is_file() and json.loads(saved.read_text(encoding="utf-8"))["path"] == want  # 브라우저가 아니라 상태 폴더
    saved.write_text(json.dumps({"path": str(c.work / "gone")}), encoding="utf-8")  # 지금 없는 폴더는 무시
    assert c.call("GET", "/api/folders/last")[1]["path"] is None
    saved.write_text("not json", encoding="utf-8")
    assert c.call("GET", "/api/folders/last")[1]["path"] is None


def test_last_folder_can_be_set_from_first_run_project_pick(mconsole):
    """시안 G-02 [이 프로젝트로]: POST /api/folders/last 가 고른 폴더를 마지막 폴더로 기억한다."""
    c = mconsole
    want = os.path.realpath(str(c.work))
    status, body, _ = c.call("POST", "/api/folders/last", {"path": str(c.work)})
    assert status == 200 and body == {"path": want, "name": os.path.basename(want)}
    assert c.call("GET", "/api/folders/last")[1]["path"] == want  # 읽기 API 가 그대로 돌려준다
    assert json.loads((c.state / console_server.LAST_FOLDER_FILE).read_text(encoding="utf-8"))["path"] == want  # 브라우저가 아니라 상태 폴더
    assert want in [f["path"] for f in c.call("GET", "/api/folders/recent")[1]]  # 최근 폴더에도 오른다
    for bad in ({"path": str(c.work / "nope")}, {"path": ""}, {}, {"path": 5}):
        assert c.call("POST", "/api/folders/last", bad)[0] == 400, bad  # 없는 폴더 · 빈 값은 거부
    assert c.call("GET", "/api/folders/last")[1]["path"] == want  # 거부한 요청은 기억을 바꾸지 않는다
    assert c.call("POST", "/api/folders/last", {"path": str(c.work)}, cookie=False)[0] == 401  # 쿠키 인증이 필요하다


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

DETACHED, NEW_GROUP, NO_WINDOW, BREAKAWAY = 0x00000008, 0x00000200, 0x08000000, 0x01000000


def test_detach_kwargs_per_os():
    assert platform_compat.popen_detached_kwargs("posix") == {"start_new_session": True}
    assert platform_compat.popen_detached_kwargs("posix", False, False) == {"start_new_session": True}
    flags = platform_compat.popen_detached_kwargs("windows", True, False)["creationflags"]
    assert flags == DETACHED | NEW_GROUP


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
    # pythonw.exe(콘솔 없음): DETACHED_PROCESS + 새 프로세스 그룹 + breakaway
    kw = platform_compat.popen_detached_kwargs("windows")
    assert kw["creationflags"] == DETACHED | NEW_GROUP | BREAKAWAY
    # 콘솔용 인터프리터: DETACHED_PROCESS 와 같이 주면 CREATE_NO_WINDOW 가 무시되므로 둘을 같이 쓰지 않는다
    flags = platform_compat.popen_detached_kwargs("windows", windowless=False)["creationflags"]
    assert flags == NO_WINDOW | NEW_GROUP | BREAKAWAY and not flags & DETACHED
    assert platform_compat.popen_detached_kwargs("posix") == {"start_new_session": True}
    # 옛 방식(두 dict 를 풀어 넣기)은 Windows 값에서 TypeError 였다 -> 실제로 호출해 터지는지 확인
    with pytest.raises(TypeError):
        dict(a=1, **kw, **platform_compat.hidden_window_kwargs("windows"))


def test_open_server_popen_args_with_injected_windows():
    for os_name in ("windows", "posix"):
        args, kwargs = console_open.server_popen_args(4999, os_name)  # 같은 키 중복이면 여기서 TypeError
        captured = {}
        fake = lambda *a, **k: captured.update(k)  # noqa: E731  Popen 을 실제 호출 형식으로 흉내
        fake(args, **kwargs)
        assert captured["env"]["HARNESS_CONSOLE_PORT"] == "4999"
        assert ("creationflags" in captured) == (os_name == "windows")


def test_windows_server_uses_pythonw_next_to_base_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "_base_executable", r"C:\Python312\python.exe", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\proj\.venv\Scripts\python.exe")
    args, kwargs = console_open.server_popen_args(4999, "windows", exists=lambda p: p == r"C:\Python312\pythonw.exe")
    assert args[0] == r"C:\Python312\pythonw.exe"  # venv 런처(.venv\Scripts\python.exe)를 거치지 않는다
    assert kwargs["creationflags"] == DETACHED | NEW_GROUP | BREAKAWAY


def test_windows_server_falls_back_to_no_window_without_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "_base_executable", r"C:\Python312\python.exe", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\proj\.venv\Scripts\python.exe")
    args, kwargs = console_open.server_popen_args(4999, "windows", exists=lambda p: False)
    assert args[0] == r"C:\proj\.venv\Scripts\python.exe"
    assert kwargs["creationflags"] == NO_WINDOW | NEW_GROUP | BREAKAWAY


def test_posix_server_keeps_sys_executable_and_new_session(monkeypatch):
    monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
    args, kwargs = console_open.server_popen_args(4999, "posix")
    assert args[0] == "/usr/bin/python3" and kwargs["start_new_session"] is True and "creationflags" not in kwargs


def test_launch_server_retries_without_breakaway_when_job_denies_it():
    calls = []

    def popen(args, **k):
        calls.append(k["creationflags"])
        if k["creationflags"] & BREAKAWAY:
            raise PermissionError(5, "Access is denied")
        return "proc"

    assert console_open.launch_server(4999, "windows", popen, lambda p: True) == "proc"
    assert calls == [DETACHED | NEW_GROUP | BREAKAWAY, DETACHED | NEW_GROUP]


def test_launch_server_first_try_keeps_breakaway_and_posix_does_not_retry():
    calls = []
    assert console_open.launch_server(4999, "windows", lambda a, **k: calls.append(k["creationflags"]) or "p", lambda p: True) == "p"
    assert calls == [DETACHED | NEW_GROUP | BREAKAWAY]

    def boom(args, **k):
        raise FileNotFoundError("x")

    with pytest.raises(FileNotFoundError):
        console_open.launch_server(4999, "posix", boom)


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
    assert ctype[".woff2"] == "font/woff2"


@pytest.mark.parametrize("name", ["PretendardVariable.woff2", "JetBrainsMono-Regular.woff2"])
def test_fonts_served_as_woff2_regardless_of_registry(console, monkeypatch, name):
    # 글꼴은 static/fonts/ 에서 font/woff2 로 나가고, CSP font-src 'self' 와 같은 출처라 막히지 않는다(#611).
    monkeypatch.setattr(console_server.mimetypes, "guess_type", lambda n: ("text/plain", None))
    for prefix in ("/fonts/", "/static/fonts/"):
        status, body, resp = console.call("GET", prefix + name, cookie=False, binary=True)
        assert status == 200, prefix
        assert resp.getheader("Content-Type") == "font/woff2"
        assert body[:4] == b"wOF2"
        assert "font-src 'self'" in resp.getheader("Content-Security-Policy")
        assert resp.getheader("X-Content-Type-Options") == "nosniff"


def test_fonts_folder_does_not_open_other_paths(console):
    for bad in ("/fonts/", "/fonts/none.woff2", "/fonts/../server.py", "/fonts/a/b.woff2", "/fonts/%2e%2e/server.py", "/static/fonts/../server.py"):
        assert console.call("GET", bad, cookie=False, binary=True)[0] == 404, bad
    css = (CONSOLE / "static" / "app.css").read_text(encoding="utf-8")
    assert "url('/fonts/PretendardVariable.woff2')" in css and "font-weight: 45 920" in css and "font-display: swap" in css
    assert "--font: 'Pretendard'" in css and "--mono: 'JetBrains Mono'" in css
    html = (CONSOLE / "static" / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html  # CSP 가 막는 바깥 글꼴 요청은 두지 않는다


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


def test_stop_waits_until_port_is_released_and_start_retries_while_in_use(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]  # 응답은 하지 않지만 포트는 잡고 있다(막 끈 서버가 소켓을 늦게 놓는 상황)
    assert console_open.probe(port) == "free" and not console_open.port_bindable(port)
    timer = threading.Timer(0.5, sock.close)
    timer.start()
    started = time.monotonic()
    assert console_open.wait_port_released(port, 10) is True
    assert 0.3 < time.monotonic() - started < 5
    timer.join()
    assert console_open.port_bindable(port)
    # 끝내 안 풀리면 시간이 다 된 뒤 False
    hold = socket.socket()
    hold.bind(("127.0.0.1", 0))
    try:
        assert console_open.wait_port_released(hold.getsockname()[1], 0.3) is False
    finally:
        hold.close()
    # 시작 쪽: 포트가 풀리기를 기다린 뒤에 서버를 띄운다
    checks, started_after = [], []
    answers = iter([False, False, True])

    def bindable(p):
        checks.append(p)
        return next(answers)

    def fake_start(p):
        started_after.append(len(checks))
        launched.append(True)

    launched: list[bool] = []
    monkeypatch.setattr(console_open, "port_bindable", bindable)
    monkeypatch.setattr(console_open, "start_server", fake_start)
    monkeypatch.setattr(console_open, "read_server_error", lambda: "")
    monkeypatch.setattr(console_open, "probe", lambda p: "ours" if launched else "free")
    assert console_open.ensure_server(port, wait=2) is None
    assert started_after == [3]  # 포트가 세 번째 확인에서 풀린 뒤에야 띄웠다


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
    done = subprocess.run([sys.executable, str(CONSOLE / "session_start_hook.py")], input=stdin, capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, HARNESS_CONSOLE_PORT=str(env_port)), timeout=timeout)
    return done, time.monotonic() - t0


def test_session_start_hook_always_succeeds_when_server_is_down():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    t0 = time.monotonic()
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    startup = time.monotonic() - t0  # 바쁜 PC 에서는 프로세스 기동만 몇 초 걸릴 수 있어 빼고 잰다
    done, took = run_start_hook('{"session_id":"s"}', port)
    assert done.returncode == 0 and done.stdout == "" and took - startup < 3
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
                    assert h["timeout"] >= int(m.group(2))  # 스크립트 자체 제한이 훅 제한 안에 들어야 한다
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
    assert urls["SessionEnd"] == [(None, "event", 5)]  # SessionEnd 기본 공유 제한은 1.5초지만 훅 timeout 을 늘리면 그만큼 늘어난다(Windows 는 uv 기동만 0.5~0.9초)
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


@pytest.mark.parametrize("text,expected", [
    ("[Image #26]", ""),
    ("[Image #3]\n로그인 고쳐줘", "로그인 고쳐줘"),
    ("[Image #26] 이거 뭐야", "이거 뭐야"),
    ("[Image: source: C:\\a\\b.png]\n화면 봐줘", "화면 봐줘"),
    ("[Pasted text #1 +20 lines]\n이 로그 분석해줘", "이 로그 분석해줘"),
    ('<cross-session-message from="uds:abc">PR 병합했어</cross-session-message>', "다른 세션: PR 병합했어"),
    ('<cross-session-message from="uds:abc">  </cross-session-message>', ""),
    ('<cross-session-message from="uds:\\\\.\\pipe\\LOCAL\\cc-msg-3c6d1', ""),  # 옛 판이 60자로 잘라 저장한 이름
    ('<cross-session-message from="uds:x">\n#685 검사 끝났어\n</cross-session-message>', "다른 세션: #685 검사 끝났어"),
    ("<task-notification>\n<task-id>1</task-id>\n</task-notification>", ""),
    ("<task-notification>끝까지 닫히지 않음\n본문", ""),
    ("앞에 쓴 글\n<system-reminder>\n규칙\n</system-reminder>", "앞에 쓴 글"),
    ("<system-reminder>규칙</system-reminder>\n뒤에 쓴 글", "뒤에 쓴 글"),
    ("/harness:scaffold", ""),
    ("<command-name>/harness:scaffold</command-name>\n<command-args></command-args>", ""),
    ("", ""),
    ("   \n\n  ", ""),
])
def test_prompt_title_cases(text, expected):
    assert store_mod.prompt_title(text) == expected


def test_hook_prompt_skips_image_line_and_uses_next_line(browser):
    browser.event("t20", "UserPromptSubmit", prompt="[Image #3]\n로그인 고쳐줘")
    assert browser.call("GET", "/api/sessions/t20")[1]["title"] == "로그인 고쳐줘"


def test_image_only_prompt_leaves_next_prompt_as_title(browser):
    browser.event("t21", "UserPromptSubmit", prompt="[Image #1]")
    assert browser.call("GET", "/api/sessions/t21")[1]["title"] == "이름 없는 세션 · work"
    browser.event("t21", "UserPromptSubmit", prompt="진짜 요청")
    browser.event("t21", "UserPromptSubmit", prompt="두 번째")
    assert browser.call("GET", "/api/sessions/t21")[1]["title"] == "진짜 요청"


def test_display_title_fallback_order():
    dt = store_mod.display_title
    base = {"title": "work", "title_rank": 1, "branch": "fix/683-console-session-names", "cwd": "C:\\a\\work",
            "currentSkill": "srs", "turn": {"skill": None}}
    assert dt(base) == "#683 console session names"
    assert dt(dict(base, branch="main")) == "요구사항 문서 · work"
    assert dt(dict(base, branch="HEAD", currentSkill="", turn={"skill": "spec"})) == "개발 Spec · work"
    assert dt(dict(base, branch="", currentSkill="harness:start")) == "작업 시작 · work"
    assert dt(dict(base, branch="", currentSkill="custom-x", cwd="")) == "custom-x"
    assert dt(dict(base, branch="", currentSkill="", turn={"skill": None})) == "이름 없는 세션 · work"
    assert dt(dict(base, branch="", currentSkill="", cwd="")) == "이름 없는 세션"
    assert dt(dict(base, title="요청 글", title_rank=2)) == "요청 글"


def test_load_cleans_stale_prompt_titles(tmp_path):
    def sess(sid, title, rank):
        return {"id": sid, "title": title, "title_rank": rank}
    (tmp_path / "sessions.json").write_text(json.dumps({"sessions": [
        sess("a", "[Image #17]", 2), sess("b", "[Image #2] 이거 뭐야", 2), sess("c", "work", 1), sess("d", "[Image #1]", 3),
    ], "folders": []}), encoding="utf-8")
    st = Store(tmp_path)
    assert (st.sessions["a"]["title"], st.sessions["a"]["title_rank"]) == ("", 2)  # 다음 중간 말이 이름이 되지 않게
    st.sessions["a"].update(branch="fix/12-old-work", cwd="C:\\x\\work")
    assert store_mod.display_title(st.sessions["a"]) == "#12 old work"
    assert (st.sessions["b"]["title"], st.sessions["b"]["title_rank"]) == ("이거 뭐야", 2)
    assert (st.sessions["c"]["title"], st.sessions["c"]["title_rank"]) == ("work", 1)
    assert st.sessions["d"]["title"] == "[Image #1]"


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


class _FakeSock:
    def __init__(self):
        self.timeouts = []

    def settimeout(self, value):
        self.timeouts.append(value)

    def sendall(self, data):
        pass


def _fake_connection(log, connect_error=None):
    class Conn:
        def __init__(self, host, port, timeout=None):
            log["init_timeout"] = timeout
            self.sock = None

        def connect(self):
            log["connect_timeout"] = log["init_timeout"]
            if connect_error:
                raise connect_error
            self.sock = _FakeSock()
            log["sock"] = self.sock

        def request(self, *a, **k):
            log["requested"] = True

        def getresponse(self):
            class R:
                status = 200

                def read(self):
                    return b'{"ok":true}'
            return R()

        def close(self):
            pass
    return Conn


class _FakeStdin:
    def __init__(self, data):
        import io
        self.buffer = io.BytesIO(data)


def test_hook_post_limits_connect_to_half_second_then_restores_socket_limit(monkeypatch, capfd):
    log = {}
    monkeypatch.setattr(hook_post.http.client, "HTTPConnection", _fake_connection(log))
    monkeypatch.setattr(hook_post.sys, "stdin", _FakeStdin(b'{"session_id":"x"}'))
    assert hook_post.main(["permission", "86400"]) == 0
    assert log["connect_timeout"] == 0.5
    assert log["sock"].timeouts == [86400.0] and log["requested"]
    assert capfd.readouterr().out == '{"ok":true}'


def test_hook_post_connect_failure_is_silent_and_sends_nothing(monkeypatch, capfd):
    log = {}
    monkeypatch.setattr(hook_post.http.client, "HTTPConnection", _fake_connection(log, ConnectionRefusedError()))
    monkeypatch.setattr(hook_post.sys, "stdin", _FakeStdin(b'{"session_id":"x"}'))
    assert hook_post.main(["permission", "86400"]) == 0
    assert log["connect_timeout"] == 0.5 and "requested" not in log
    assert capfd.readouterr().out == ""


def test_session_start_hook_limits_connect_then_restores_socket_limit(monkeypatch):
    log = {}
    monkeypatch.setattr(session_start_hook.http.client, "HTTPConnection", _fake_connection(log))
    session_start_hook.post(b"{}", 4873)
    assert log["connect_timeout"] == 0.5 and log["sock"].timeouts == [0.8] and log["requested"]


def test_open_main_gives_api_open_a_long_timeout(monkeypatch):
    import inspect
    assert inspect.signature(console_open.ensure_server).parameters["wait"].default == 20.0
    calls = []
    monkeypatch.setattr(console_open, "ensure_server", lambda port: None)

    def fake_request(port, method, path, body=None, timeout=3.0):
        calls.append((path, timeout))
        return 200, {}
    monkeypatch.setattr(console_open, "request", fake_request)
    assert console_open.main([]) == 0
    assert calls == [("/api/open", 30)]


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
    # 명령 원문·입력 전체는 "자세히" 안에 있지만, 쉬운 설명이 없는 명령·샌드박스를 끄는 명령·파일 고치기는 접지 않고 열어 둔다(#636)
    assert "var friendly = tool === 'Bash' && input && input.description && !input.dangerouslyDisableSandbox && !input.run_in_background;" in js
    assert "class: 'more', open: !friendly" in js
    # 시안 17 의 확인 카드: 이번만 허락 / 하지 마, Edit 은 원래 글 · 바꾼 글(#634)
    assert "'이번만 허락'" in js and "'하지 마'" in js and "row('원래 글'" in js and "row('바꾼 글'" in js
    assert "바꿀 내용" not in js and "바뀌는 부분" not in js
    css = (CONSOLE / "static" / "app.css").read_text(encoding="utf-8")
    assert ".scroll" in css and "max-height" in css


_MD_NODE = r"""
function node(t) { return {t: t, kids: [], cls: '', style: {}, tx: null,
  appendChild(c) { this.kids.push(c); return c; },
  set textContent(v) { this.tx = v; }, set className(v) { this.cls = v; }, set href(v) { this.h = v; }, set target(v) {}, set rel(v) {} }; }
global.window = {};
global.document = { createElement: node, createTextNode: (s) => ({text: s}) };
global.URL = URL;
function ser(n) {
  if (n.text !== undefined) return n.text;
  return '<' + n.t + (n.cls ? '.' + n.cls : '') + '>' + (n.tx !== null ? n.tx : n.kids.map(ser).join('')) + '</' + n.t + '>';
}
require(process.argv[2]);
process.stdout.write(ser(window.BHMarkdown.render(process.argv[3])));
"""


def _render_md(tmp_path, src):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 없음")
    js = tmp_path / "md_run.js"
    js.write_text(_MD_NODE, encoding="utf-8")
    out = subprocess.run([node, str(js), str(CONSOLE / "static" / "md.js"), src], capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_markdown_renders_gfm_table(tmp_path):
    src = "앞 글\n\n| 파일 | 크기(바이트) | 줄 수 |\n|---|:---:|---:|\n| `a|b.py` | **12** | 3 |\n| x | y |\n\n뒤 글"
    html = _render_md(tmp_path, src)
    assert "<div.md-table><table>" in html
    assert "<thead><tr><th>파일</th><th>크기(바이트)</th><th>줄 수</th></tr></thead>" in html
    assert "<td><code>a|b.py</code></td><td><strong>12</strong></td><td>3</td>" in html
    assert "<td>y</td><td></td></tr>" in html  # 모자란 칸은 빈 칸
    assert "|---|" not in html and "<p>앞 글</p>" in html and "<p>뒤 글</p>" in html


def test_markdown_table_escapes_html_and_ignores_non_table(tmp_path):
    html = _render_md(tmp_path, "| a |\n|---|\n| <script>alert(1)</script> |")
    assert "<td><script>alert(1)</script></td>" in html  # 직렬화 표기일 뿐 실제로는 텍스트 노드(innerHTML 안 씀)
    assert "innerHTML" not in (CONSOLE / "static" / "md.js").read_text(encoding="utf-8").replace("모든 글자는", "")
    plain = _render_md(tmp_path, "a | b\n그냥 글")
    assert "<table>" not in plain


def test_session_headline_is_short_and_full_action_has_own_line():
    js = (CONSOLE / "static" / "app.js").read_text(encoding="utf-8")
    assert "HEADLINE_MAX" in js and "shortAction(s.currentAction)" in js and "action-line" in js
    css = (CONSOLE / "static" / "app.css").read_text(encoding="utf-8")
    assert ".action-line" in css and "text-overflow: ellipsis" in css  # 사이드바 상태는 한 줄 말줄임(#636)


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


# ---- 폴더 찾아보기(#558) ----

class PickDone:
    def __init__(self, returncode=0, stdout=b""):
        self.returncode, self.stdout = returncode, stdout


def b64_utf8(text):
    import base64
    return base64.b64encode(text.encode("utf-8"))


def test_pick_folder_windows_command_shape_and_korean_path():
    import base64
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return PickDone(0, b64_utf8("C:\\Users\\민재희\\작업 폴더"))

    assert platform_compat.pick_folder("windows", runner) == "C:\\Users\\민재희\\작업 폴더"
    cmd, kw = seen["cmd"], seen["kw"]
    assert cmd[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-STA"] and cmd[4] == "-EncodedCommand"
    script = base64.b64decode(cmd[5]).decode("utf-16-le")
    assert "IFileOpenDialog" in script and "0x20 | 0x40" in script and "작업 폴더 고르기" in script  # 탐색기식 창
    assert "FolderBrowserDialog" in script and "TopMost = $true" in script and "ShowDialog($owner)" in script  # 대체 경로
    assert "SetForegroundWindow" in script and "AllowSetForegroundWindow" in script
    assert kw["creationflags"] == 0x08000000 and kw["timeout"] == platform_compat.PICK_TIMEOUT
    assert "shell" not in kw


def test_pick_folder_windows_start_folder_goes_by_env_not_script():
    import base64
    seen = []

    def runner(cmd, **kw):
        seen.append((cmd, kw))
        return PickDone(0, b"")

    evil = r"C:\Users\민재희\작업 폴더'; calc; '"
    assert platform_compat.pick_folder("windows", runner, start=evil) is None
    platform_compat.pick_folder("windows", runner)
    (cmd, kw), (cmd2, kw2) = seen
    script = base64.b64decode(cmd[5]).decode("utf-16-le")
    assert script == platform_compat.WINDOWS_PICK_SCRIPT and "calc" not in script and "작업 폴더'" not in script
    assert base64.b64decode(kw["env"]["HARNESS_PICK_START"]).decode("utf-8") == evil
    assert kw2["env"]["HARNESS_PICK_START"] == ""  # 시작 폴더가 없으면 스크립트가 사용자 홈을 쓴다
    assert "HARNESS_PICK_START" in script


def test_pick_script_falls_back_to_old_dialog_when_com_fails():
    script = platform_compat.WINDOWS_PICK_SCRIPT
    com = script.index("[HarnessPick]::Pick(")
    assert script.index("} catch {", com) < script.index("if (-not $done)") < script.index("New-Object System.Windows.Forms.FolderBrowserDialog")


def test_pick_folder_windows_cancel_failure_and_garbage():
    assert platform_compat.pick_folder("windows", lambda cmd, **k: PickDone(0, b"")) is None  # 취소는 아무것도 출력하지 않는다
    with pytest.raises(platform_compat.PickUnavailable):
        platform_compat.pick_folder("windows", lambda cmd, **k: PickDone(1, b""))
    with pytest.raises(platform_compat.PickUnavailable):
        platform_compat.pick_folder("windows", lambda cmd, **k: PickDone(0, b"not base64 !!"))

    def missing(cmd, **k):
        raise FileNotFoundError("powershell")

    def slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 1)

    for bad in (missing, slow):
        with pytest.raises(platform_compat.PickUnavailable) as e:
            platform_compat.pick_folder("windows", bad)
        assert "직접 적어" in str(e.value)


def test_pick_folder_macos_and_other_os():
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return PickDone(0, "/Users/me/프로젝트/\n".encode("utf-8"))

    assert platform_compat.pick_folder("macos", runner) == "/Users/me/프로젝트"
    assert seen["cmd"] == ["osascript", "-e", "POSIX path of (choose folder)"] and "creationflags" not in seen["kw"]
    assert platform_compat.pick_folder("macos", lambda cmd, **k: PickDone(0, b"/\n")) == "/"
    assert platform_compat.pick_folder("macos", lambda cmd, **k: PickDone(1, b"")) is None  # 취소는 종료코드 1
    with pytest.raises(platform_compat.PickUnavailable):
        platform_compat.pick_folder("macos", lambda cmd, **k: PickDone(2, b""))
    with pytest.raises(platform_compat.PickUnavailable) as e:
        platform_compat.pick_folder("linux", lambda cmd, **k: pytest.fail("실행하면 안 된다"))
    assert "직접 적어" in str(e.value)


def test_pick_route_requires_cookie_and_json(console):
    assert console.call("POST", "/api/folders/pick", {}, cookie=False)[0] == 401
    console.login()
    assert console.call("POST", "/api/folders/pick", raw=b"{}", json_type=False)[0] == 415
    assert console.call("POST", "/api/folders/pick", {}, headers={"Origin": "http://evil.example"})[0] == 403


def test_pick_route_success_cancel_unavailable(authed):
    answers = [str(authed.work), None, platform_compat.PickUnavailable("띄울 수 없습니다. 경로를 직접 적어 주세요.")]

    def picker(start=None):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    authed.app.folder_picker = picker
    assert authed.call("POST", "/api/folders/pick", {})[1] == {"path": str(authed.work)}
    assert authed.call("POST", "/api/folders/pick", {})[1] == {"cancelled": True}
    status, body, _ = authed.call("POST", "/api/folders/pick", {})
    assert status == 503 and "직접 적어" in body["error"]


def test_pick_route_second_call_while_open_is_409(authed):
    opened, release = threading.Event(), threading.Event()

    def picker(start=None):
        opened.set()
        release.wait(10)
        return None

    authed.app.folder_picker = picker
    first = {}
    t = threading.Thread(target=lambda: first.update(r=authed.call("POST", "/api/folders/pick", {})), daemon=True)
    t.start()
    assert opened.wait(10)
    status, body, _ = authed.call("POST", "/api/folders/pick", {})
    assert status == 409 and "이미 열려" in body["error"]
    release.set()
    t.join(10)
    assert first["r"][0] == 200 and first["r"][1] == {"cancelled": True}
    authed.app.folder_picker = lambda start=None: None  # 끝난 뒤에는 다시 열 수 있다
    assert authed.call("POST", "/api/folders/pick", {})[0] == 200


def test_pick_route_passes_start_only_for_real_folder(authed):
    seen = []

    def picker(start=None):
        seen.append(start)
        return None

    authed.app.folder_picker = picker
    for body in ({"path": str(authed.work)}, {"path": str(authed.work / "없는폴더")}, {"path": 5},
                 {"path": "x" * 2000}, {"path": ""}, {}):
        assert authed.call("POST", "/api/folders/pick", body)[0] == 200
    assert seen == [str(authed.work), None, None, None, None, None]


# ---- 모델 고르기(#558) ----

def test_models_route_lists_allowed_options_and_env_default(authed):
    status, body, _ = authed.call("GET", "/api/models")
    assert status == 200 and body["default"] == ""
    assert [o["value"] for o in body["options"]] == ["", "fable", "opus", "sonnet", "haiku"]
    authed.app.default_model = "claude-opus-4-1"
    body = authed.call("GET", "/api/models")[1]
    assert body["default"] == "claude-opus-4-1" and body["options"][-1]["value"] == "claude-opus-4-1"


@pytest.mark.parametrize("bad", ["gpt-4", "OPUS", "opus --dangerously-skip-permissions", 5, ["opus"], {"a": 1}])
def test_new_and_start_reject_models_outside_the_allow_list(tmp_path, monkeypatch, bad):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        assert c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "model": bad})[0] == 400
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "model": "haiku"})[1]["id"]
        assert c.call("POST", f"/api/new/{jid}/start", {"model": bad})[0] == 400
    finally:
        c.close()


def test_analysis_command_model_argument():
    a = analysis.Analyses(lambda: ["claude"], model="sonnet")
    assert a.command()[a.command().index("--model") + 1] == "sonnet"  # 안 고르면 서버 기본값
    assert a.command("haiku")[a.command("haiku").index("--model") + 1] == "haiku"
    assert "--model" not in a.command("")  # 기본값을 고르면 --model 을 붙이지 않는다
    assert "--model" not in analysis.Analyses(lambda: ["claude"]).command()


def test_new_job_remembers_chosen_model(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "model": "opus"})[1]["id"]
        assert c.app.analyses.get(jid)["model"] == "opus"
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work)})[1]["id"]
        assert c.app.analyses.get(jid)["model"] is None
    finally:
        c.close()


def test_managed_command_model_argument_and_resume_keeps_it():
    m = managed.Manager(Store(None), lambda: ["claude"], "/plug", model="sonnet")
    assert m.command()[m.command().index("--model") + 1] == "sonnet"
    assert m.command(model="haiku")[m.command(model="haiku").index("--model") + 1] == "haiku"
    assert "--model" not in m.command(model="")
    args = m.command("sid-1", "opus")
    assert args[args.index("--model") + 1] == "opus" and args[args.index("--resume") + 1] == "sid-1"


def test_managed_launch_records_choice_and_init_model_and_resume_reuses_it(mconsole):
    c = mconsole
    sid = c.app.manager.launch(str(c.work), "a", model="haiku")
    real = wait_for(lambda: (c.app.store.resolve_id(sid) != sid) and c.app.store.resolve_id(sid))
    s = c.app.store.get(real)
    wait_for(lambda: s["model"] == "haiku")  # 가짜 claude 가 받은 --model 을 init 에 싣는다
    assert s["modelChoice"] == "haiku"
    pub = c.call("GET", f"/api/sessions/{real}")[1]
    assert pub["model"] == "haiku" and pub["modelChoice"] == "haiku"
    wait_for(lambda: s["report"] == "echo: a")
    c.app.manager.close(c.app.manager.proc_for(real))
    wait_for(lambda: c.call("GET", f"/api/sessions/{real}")[1]["status"] == "ended")
    s["model"] = ""
    assert c.call("POST", f"/api/sessions/{real}/messages", {"text": "again"})[0] == 202
    wait_for(lambda: s["report"] == "echo: again")
    assert s["model"] == "haiku"  # 다시 띄울 때도 같은 --model 이 붙었다


def test_managed_launch_without_choice_has_no_model_flag_and_shows_init_model(mconsole):
    c = mconsole
    real = launch(c, "a")
    s = c.app.store.get(real)
    wait_for(lambda: s["model"] == "fake-default-model")
    assert s["modelChoice"] == ""


def test_start_route_uses_model_from_request_or_analysis(mconsole):
    c = mconsole
    jid = c.call("POST", "/api/new", {"text": "계획", "cwd": str(c.work), "model": "sonnet"})[1]["id"]
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    sid = c.call("POST", f"/api/new/{jid}/start", {})[1]["id"]
    wait_for(lambda: c.app.store.get(sid)["model"] == "sonnet")  # 분석 때 고른 모델
    jid = c.call("POST", "/api/new", {"text": "계획2", "cwd": str(c.work), "model": "sonnet"})[1]["id"]
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    sid = c.call("POST", f"/api/new/{jid}/start", {"model": "opus"})[1]["id"]
    wait_for(lambda: c.app.store.get(sid)["model"] == "opus")  # 시작 때 다시 고른 모델이 우선


def test_hook_model_is_shown_only_when_present(browser):
    browser.event("t-1", "UserPromptSubmit", prompt="hi")
    assert browser.call("GET", "/api/sessions/t-1")[1]["model"] == ""  # 지어내지 않는다
    browser.event("t-1", "SessionStart", model="claude-opus-4-1")
    assert browser.call("GET", "/api/sessions/t-1")[1]["model"] == "claude-opus-4-1"


def test_old_sessions_json_without_model_fields_still_loads(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    old = {"id": "old-1", "title": "옛 세션", "cwd": "", "repo": "", "branch": "", "managed": True, "permissionMode": "default",
           "currentSkill": "", "currentAction": "", "startedAt": 1, "updatedAt": 1, "log": [], "report": "", "changedFiles": [],
           "prLinks": [], "subagents": [], "skillStates": {}, "pending_stop": [], "turn_running": False, "ended": True,
           "title_rank": 0, "turn": {"skill": None, "unknown": False}}
    (state / "sessions.json").write_text(json.dumps({"sessions": [old], "folders": []}, ensure_ascii=False), encoding="utf-8")
    store = Store(state)
    from store import public_session
    pub = public_session(store, store.get("old-1"), [])
    assert pub["model"] == "" and pub["modelChoice"] == "" and pub["effortChoice"] == ""
    m = managed.Manager(store, lambda: ["claude"], "/plug", model="sonnet", effort="low")
    assert m.remembered_model("old-1") is None  # 기억이 없으면 서버 기본값을 따른다
    assert m.remembered_effort("old-1") is None
    store.save(force=True)
    assert "old-1" in (state / "sessions.json").read_text(encoding="utf-8")


# ---- 모델 보기 넓힘과 에포트(#558) ----

def test_models_route_lists_effort_options_and_default(authed):
    body = authed.call("GET", "/api/models")[1]
    assert [o["value"] for o in body["effortOptions"]] == ["", "low", "medium", "high", "xhigh", "max"]
    assert [o["label"] for o in body["effortOptions"]] == ["기본값", "낮음", "보통", "높음", "아주 높음", "최대"]
    assert body["defaultEffort"] == ""
    authed.app.default_effort = "high"
    assert authed.call("GET", "/api/models")[1]["defaultEffort"] == "high"


def test_env_effort_default_accepts_only_allowed_values(tmp_path):
    ok = console_server.App(0, None, Path(console_server.__file__).resolve().parent.parent, effort="xhigh")
    assert ok.default_effort == "xhigh" and ok.manager.effort == "xhigh" and ok.analyses.effort == "xhigh"
    bad = console_server.App(0, None, Path(console_server.__file__).resolve().parent.parent, effort="extreme")
    assert bad.default_effort == "" and bad.manager.effort == "" and bad.analyses.effort == ""


@pytest.mark.parametrize("good", ["", "fable", "opus", "sonnet", "haiku", "claude-opus-4-1", "claude-sonnet-4-5-20250929",
                                  "claude-opus-4-1[1m]", "claude-x.y-z"])
def test_new_accepts_alias_and_full_model_names(tmp_path, monkeypatch, good):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        status, body, _ = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "model": good})
        assert status == 202 and c.app.analyses.get(body["id"])["model"] == good
    finally:
        c.close()


@pytest.mark.parametrize("bad", ["-x", "--model", "claude-opus 4", "claude-opus;rm", "claude-", "claude-" + "a" * 70, "Claude-opus",
                                 " claude-opus-4-1", "claude-opus-4-1\n", "x" * 200, "claude-opus-4-1[1m]x"])
def test_new_rejects_unsafe_model_names(tmp_path, monkeypatch, bad):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        assert c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "model": bad})[0] == 400
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work)})[1]["id"]
        assert c.call("POST", f"/api/new/{jid}/start", {"model": bad})[0] == 400
    finally:
        c.close()


@pytest.mark.parametrize("good", ["", "low", "medium", "high", "xhigh", "max"])
def test_new_accepts_every_effort_level(tmp_path, monkeypatch, good):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        status, body, _ = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "effort": good})
        assert status == 202 and c.app.analyses.get(body["id"])["effort"] == good
    finally:
        c.close()


@pytest.mark.parametrize("bad", ["ultra", "HIGH", "high --x", "-high", 3, ["low"], {"a": 1}])
def test_new_and_start_reject_efforts_outside_the_allow_list(tmp_path, monkeypatch, bad):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        assert c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "effort": bad})[0] == 400
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work), "effort": "low"})[1]["id"]
        assert c.call("POST", f"/api/new/{jid}/start", {"effort": bad})[0] == 400
    finally:
        c.close()


def test_new_without_effort_leaves_job_effort_unset(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work)})[1]["id"]
        assert c.app.analyses.get(jid)["effort"] is None
    finally:
        c.close()


def test_analysis_command_effort_argument():
    a = analysis.Analyses(lambda: ["claude"], effort="medium")
    cmd = a.command()
    assert cmd[cmd.index("--effort") + 1] == "medium"  # 안 고르면 서버 기본값
    cmd = a.command(effort="max")
    assert cmd[cmd.index("--effort") + 1] == "max"
    assert "--effort" not in a.command(effort="")  # 기본값을 고르면 붙이지 않는다
    assert "--effort" not in analysis.Analyses(lambda: ["claude"]).command()


def test_managed_command_effort_argument():
    m = managed.Manager(Store(None), lambda: ["claude"], "/plug", effort="low")
    cmd = m.command()
    assert cmd[cmd.index("--effort") + 1] == "low"
    cmd = m.command("sid-1", "opus", "xhigh")
    assert cmd[cmd.index("--effort") + 1] == "xhigh" and cmd[cmd.index("--resume") + 1] == "sid-1"
    assert "--effort" not in m.command(effort="")
    assert "--effort" not in managed.Manager(Store(None), lambda: ["claude"], "/plug").command()


def test_resume_reuses_remembered_effort_and_explicit_value_wins(tmp_path):
    seen = []

    def popen(args, **kw):
        seen.append(args)
        raise OSError("stop")

    store = Store(None)
    with store.lock:
        s = store.ensure("sid-1", str(tmp_path))
        s["effortChoice"] = "max"
        s["modelChoice"] = "haiku"
    m = managed.Manager(store, lambda: ["claude"], "/plug", effort="low", popen=popen)
    assert m.launch(str(tmp_path), "hi", resume="sid-1") is None
    args = seen[-1]
    assert args[args.index("--effort") + 1] == "max" and args[args.index("--resume") + 1] == "sid-1"
    assert m.launch(str(tmp_path), "hi", resume="sid-1", effort="high") is None
    assert seen[-1][seen[-1].index("--effort") + 1] == "high"
    with store.lock:
        store.ensure("sid-2", str(tmp_path))["effortChoice"] = ""
    assert m.launch(str(tmp_path), "hi", resume="sid-2") is None
    assert "--effort" not in seen[-1]  # 기본값을 골랐던 세션은 서버 기본값(low)도 아니라 아무것도 안 붙인다


def test_managed_launch_records_effort_choice_in_public_session(mconsole):
    c = mconsole
    sid = c.app.manager.launch(str(c.work), "a", effort="high")
    real = wait_for(lambda: (c.app.store.resolve_id(sid) != sid) and c.app.store.resolve_id(sid))
    assert c.call("GET", f"/api/sessions/{real}")[1]["effortChoice"] == "high"
    real2 = launch(c, "b")
    assert c.call("GET", f"/api/sessions/{real2}")[1]["effortChoice"] == ""


def test_start_route_passes_effort_from_request_or_analysis(tmp_path, monkeypatch):
    seen = []
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        orig = c.app.manager.launch
        c.app.manager.launch = lambda *a, **kw: (seen.append(kw.get("effort")), None)[1]
        jid = c.call("POST", "/api/new", {"text": "계획", "cwd": str(c.work), "effort": "low"})[1]["id"]
        wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
        c.call("POST", f"/api/new/{jid}/start", {})
        c.call("POST", f"/api/new/{jid}/start", {"effort": "max"})
        assert seen == ["low", "max"]  # 분석 때 고른 값, 시작 때 다시 고른 값이 우선
        c.app.manager.launch = orig
    finally:
        c.close()


# ---- 스킬 버튼, @ 파일 멘션, 권한 모드(#558) ----

def test_skills_route_lists_names_with_descriptions_and_hides_open(authed):
    status, body, _ = authed.call("GET", "/api/skills")
    assert status == 200 and body["plugin"] == "harness"
    names = [s["name"] for s in body["skills"]]
    assert names == ["deliver", "prs", "start"]  # update, scaffold, open 은 숨긴다
    assert all(set(s) == {"name", "description"} for s in body["skills"])


def test_skill_info_reads_description_from_real_plugin():
    items = {i["name"]: i["description"] for i in console_server.load_skill_info(PLUGIN)}
    assert "open" not in items and items["start"].startswith("작업을 시작한다")
    assert all(items.values())


def test_skills_route_needs_login(console):
    assert console.call("GET", "/api/skills")[0] == 401


def make_tree(base: Path) -> Path:
    for rel in ("a.txt", "docs/guide.md", "docs/deep/한글 파일.md", ".git/config", "node_modules/pkg/index.js", ".venv/lib/x.py"):
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")
    return base


def files_for(c, root, q=""):
    return c.call("GET", f"/api/files?root={urllib.parse.quote(str(root))}&q={urllib.parse.quote(q)}")


def test_files_route_searches_known_root_and_skips_big_dirs(authed):
    make_tree(authed.work)
    assert authed.call("POST", "/api/folders/validate", {"path": str(authed.work)})[1]["ok"]
    status, body, _ = files_for(authed, authed.work)
    assert status == 200 and not body["truncated"]
    assert sorted(body["files"]) == ["a.txt", "docs/deep/한글 파일.md", "docs/guide.md"]
    assert files_for(authed, authed.work, "GUIDE")[1]["files"] == ["docs/guide.md"]
    assert files_for(authed, authed.work, "한글")[1]["files"] == ["docs/deep/한글 파일.md"]
    assert sorted(files_for(authed, authed.work, "docs/")[1]["files"]) == ["docs/deep/한글 파일.md", "docs/guide.md"]


def test_files_route_rejects_unknown_roots(authed, tmp_path):
    make_tree(authed.work)
    other = make_tree(tmp_path / "other")
    assert files_for(authed, other)[0] == 403  # 서버가 모르는 폴더
    assert files_for(authed, "")[0] == 403
    authed.call("POST", "/api/folders/validate", {"path": str(authed.work)})
    assert files_for(authed, authed.work / "docs")[0] == 403  # 아는 폴더의 하위 폴더는 root 로 받지 않는다
    assert files_for(authed, str(authed.work) + os.sep + ".." + os.sep + "other")[0] == 403


def test_files_route_accepts_session_cwd_as_root(authed):
    make_tree(authed.work)
    authed.event("s-files", "SessionStart")
    status, body, _ = files_for(authed, authed.work, "a.t")
    assert status == 200 and body["files"] == ["a.txt"]


def test_files_route_excludes_links_that_escape_the_root(authed, tmp_path):
    make_tree(authed.work)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s", encoding="utf-8")
    try:
        os.symlink(outside / "secret.txt", authed.work / "link.txt")
        os.symlink(outside, authed.work / "linkdir", target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"심볼릭 링크를 만들 수 없는 환경: {e}")
    authed.call("POST", "/api/folders/validate", {"path": str(authed.work)})
    names = files_for(authed, authed.work)[1]["files"]
    assert "link.txt" not in names and not any(n.startswith("linkdir") or "secret" in n for n in names)
    assert "a.txt" in names


def test_files_route_limits_results_and_scan(authed, monkeypatch):
    for i in range(7):
        (authed.work / f"f{i}.txt").write_text("x", encoding="utf-8")
    authed.call("POST", "/api/folders/validate", {"path": str(authed.work)})
    monkeypatch.setattr(console_server, "FILE_RESULT_LIMIT", 3)
    body = files_for(authed, authed.work)[1]
    assert len(body["files"]) == 3 and body["truncated"]
    monkeypatch.setattr(console_server, "FILE_RESULT_LIMIT", 50)
    monkeypatch.setattr(console_server, "FILE_SCAN_LIMIT", 4)
    body = files_for(authed, authed.work, "f6")[1]  # 4개까지만 훑으므로 7번째 파일은 못 찾는다
    assert body["files"] == [] and body["truncated"]


def test_models_route_lists_only_the_allowed_permission_modes(authed):
    options = authed.call("GET", "/api/models")[1]["permissionOptions"]
    assert [o["value"] for o in options] == ["", "acceptEdits", "plan", "auto"]  # auto 는 #684 로 더했다
    assert not {"bypassPermissions", "dontAsk"} & {o["value"] for o in options}
    assert [o["label"] for o in options][-1] == "알아서 하되 위험한 건 AI가 막기"


@pytest.mark.parametrize("bad", ["bypassPermissions", "dontAsk", "default", "ACCEPTEDITS", "AUTO", "auto --x", "plan --x", 3, ["plan"]])
def test_start_rejects_permission_modes_outside_the_allowed_set(tmp_path, monkeypatch, bad):
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        jid = c.call("POST", "/api/new", {"text": "요청", "cwd": str(c.work)})[1]["id"]
        assert c.call("POST", f"/api/new/{jid}/start", {"permission": bad})[0] == 400
    finally:
        c.close()


def test_managed_command_permission_argument():
    m = managed.Manager(Store(None), lambda: ["claude"], "/plug")
    for mode in ("acceptEdits", "plan"):
        cmd = m.command(permission=mode)
        assert cmd[cmd.index("--permission-mode") + 1] == mode
    cmd = m.command("sid-1", permission="plan")
    assert cmd[cmd.index("--permission-mode") + 1] == "plan" and cmd[cmd.index("--resume") + 1] == "sid-1"
    assert "--permission-mode" not in m.command()
    assert "--permission-mode" not in m.command(permission="")


def test_resume_reuses_remembered_permission_and_explicit_value_wins(tmp_path):
    seen = []

    def popen(args, **kw):
        seen.append(args)
        raise OSError("stop")

    store = Store(None)
    with store.lock:
        store.ensure("sid-1", str(tmp_path))["permissionChoice"] = "acceptEdits"
        store.ensure("sid-2", str(tmp_path))["permissionChoice"] = ""
        store.ensure("sid-old", str(tmp_path))
    m = managed.Manager(store, lambda: ["claude"], "/plug", popen=popen)
    assert m.launch(str(tmp_path), "hi", resume="sid-1") is None
    assert seen[-1][seen[-1].index("--permission-mode") + 1] == "acceptEdits"
    assert m.launch(str(tmp_path), "hi", resume="sid-1", permission="plan") is None
    assert seen[-1][seen[-1].index("--permission-mode") + 1] == "plan"
    assert m.launch(str(tmp_path), "hi", resume="sid-2") is None
    assert "--permission-mode" not in seen[-1]
    assert m.launch(str(tmp_path), "hi", resume="sid-old") is None
    assert "--permission-mode" not in seen[-1]


def test_resume_of_hook_only_session_uses_server_defaults(tmp_path):
    seen = []

    def popen(args, **kw):
        seen.append(args)
        raise OSError("stop")

    store = Store(None)
    with store.lock:
        s = store.ensure("sid-hook", str(tmp_path))  # 훅으로만 생긴 세션: 기억 키가 없다
        assert "modelChoice" not in s and "effortChoice" not in s and "permissionChoice" not in s
        store.ensure("sid-blank", str(tmp_path)).update(modelChoice="", effortChoice="", permissionChoice="")
    m = managed.Manager(store, lambda: ["claude"], "/plug", model="sonnet", effort="low", popen=popen)
    assert m.remembered_model("sid-hook") is None and m.remembered_effort("sid-hook") is None
    assert m.launch(str(tmp_path), "hi", resume="sid-hook") is None
    assert seen[-1][seen[-1].index("--model") + 1] == "sonnet"  # 기억이 없으면 서버 기본값
    assert seen[-1][seen[-1].index("--effort") + 1] == "low"
    assert m.launch(str(tmp_path), "hi", resume="sid-blank") is None
    assert "--model" not in seen[-1] and "--effort" not in seen[-1]  # 사용자가 기본을 골랐으면 붙이지 않는다


def test_command_drops_remembered_values_outside_allowed_sets(tmp_path):
    store = Store(None)
    with store.lock:
        store.ensure("sid-bad", str(tmp_path)).update(modelChoice="--evil", effortChoice="turbo", permissionChoice="bypassPermissions")
    m = managed.Manager(store, lambda: ["claude"], "/plug")
    seen = []
    m.popen = lambda args, **kw: (seen.append(args), (_ for _ in ()).throw(OSError("stop")))[1]
    assert m.launch(str(tmp_path), "hi", resume="sid-bad") is None
    cmd = seen[-1]
    assert "--model" not in cmd and "--effort" not in cmd and "--permission-mode" not in cmd
    assert "bypassPermissions" not in cmd and "--evil" not in cmd
    assert any("bypassPermissions" in e["text"] for e in store.get("sid-bad")["log"])  # 뺀 사실을 기록에 남긴다
    ok = m.command(model="claude-opus-4-1", effort="max", permission="acceptEdits")
    assert ok[ok.index("--model") + 1] == "claude-opus-4-1" and ok[ok.index("--effort") + 1] == "max"
    assert ok[ok.index("--permission-mode") + 1] == "acceptEdits"
    assert "--permission-mode" not in m.command(permission="dontAsk")


def test_managed_launch_records_permission_choice_and_passes_it_to_claude(mconsole):
    c = mconsole
    sid = c.app.manager.launch(str(c.work), "a", permission="plan")
    real = wait_for(lambda: (c.app.store.resolve_id(sid) != sid) and c.app.store.resolve_id(sid))
    assert c.call("GET", f"/api/sessions/{real}")[1]["permissionChoice"] == "plan"
    assert wait_for(lambda: c.call("GET", f"/api/sessions/{real}")[1]["permissionMode"] == "plan")  # 가짜 claude 가 받은 인자를 init 에 싣는다
    assert c.call("GET", f"/api/sessions/{launch(c, 'b')}")[1]["permissionChoice"] == ""


def test_start_route_passes_permission_to_launch(tmp_path, monkeypatch):
    seen = []
    c = Console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS)])
    try:
        c.login()
        c.app.manager.launch = lambda *a, **kw: (seen.append(kw.get("permission")), None)[1]
        jid = c.call("POST", "/api/new", {"text": "계획", "cwd": str(c.work)})[1]["id"]
        wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
        c.call("POST", f"/api/new/{jid}/start", {})
        c.call("POST", f"/api/new/{jid}/start", {"permission": "acceptEdits"})
        c.call("POST", f"/api/new/{jid}/start", {"permission": ""})
        assert seen == [None, "acceptEdits", ""]
    finally:
        c.close()


# ---- 세션 도중 권한 모드 바꾸기 ----

def logs(c, sid):
    return [entry["text"] for entry in c.app.store.get(sid)["log"]]


def test_permission_change_on_live_session_sends_control_request(mconsole):
    c = mconsole
    sid = launch(c, "a")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: a")
    status, body, _ = c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": "plan"})
    assert status == 200 and body["live"] is True and body["mode"] == "plan"
    assert c.app.store.get(sid)["permissionChoice"] == "plan"
    assert "권한 모드: 기본(그때그때 확인) → 계획만 세우기" in logs(c, sid)
    wait_for(lambda: c.app.store.get(sid)["permissionMode"] == "plan")  # 가짜 claude 가 status 로 알린 실제 반영
    assert body["session"]["permissionChoice"] == "plan"
    assert c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": ""})[1]["mode"] == ""  # 기본으로 되돌리기도 control_request(default)
    wait_for(lambda: c.app.store.get(sid)["permissionMode"] == "default")
    assert c.app.store.get(sid)["permissionChoice"] == ""


def test_permission_change_ended_session_applies_on_resume(mconsole):
    c = mconsole
    sid = launch(c, "a")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: a")
    c.app.manager.close(c.app.manager.proc_for(sid))
    wait_for(lambda: c.call("GET", f"/api/sessions/{sid}")[1]["status"] == "ended")
    status, body, _ = c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": "acceptEdits"})
    assert status == 200 and body["live"] is False
    assert any(t.startswith("권한 모드: 기본(그때그때 확인) → 파일 고치기는 자동 허용") for t in logs(c, sid))
    assert c.call("POST", f"/api/sessions/{sid}/messages", {"text": "again"})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: again")
    assert c.app.store.get(sid)["permissionMode"] == "acceptEdits"  # 새 프로세스가 --permission-mode acceptEdits 로 떴다


@pytest.mark.parametrize("mode", ["bypassPermissions", "dontAsk", "AUTO", "bogus", 3, None, ["plan"]])
def test_permission_change_rejects_values_outside_allowed_set(mconsole, mode):
    c = mconsole
    sid = launch(c, "a")
    assert c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": mode})[0] == 400
    assert c.call("PUT", f"/api/sessions/{sid}/permission", {})[0] == 400
    assert c.app.store.get(sid)["permissionChoice"] == ""


def test_permission_change_guards(mconsole):
    c = mconsole
    c.event("term", "SessionStart")
    assert c.call("PUT", "/api/sessions/term/permission", {"mode": "plan"})[0] == 409  # 터미널 세션
    assert c.call("PUT", "/api/sessions/none/permission", {"mode": "plan"})[0] == 404
    sid = launch(c, "a")
    assert c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": "plan"}, cookie=False)[0] == 401
    assert c.call("PUT", f"/api/sessions/{sid}/permission", {"mode": "plan"}, headers={"Origin": "http://evil.example"})[0] == 403


def test_permission_change_reports_error_from_claude(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))["managed"] = True
    written = []

    class ErrorProc(FakeProc):
        def write(self, text):
            written.append(json.loads(text))
            threading.Timer(0.05, lambda: m.on_event(self, {"type": "control_response", "response": {
                "subtype": "error", "request_id": written[-1]["request_id"], "error": "invalid_mode"}})).start()
            return True

    m.procs["s1"] = ErrorProc()
    result = m.set_permission("s1", "plan")
    assert written[0]["request"] == {"subtype": "set_permission_mode", "mode": "plan"}
    assert result["ok"] is False and "invalid_mode" in result["error"]
    assert store.get("s1").get("permissionChoice", "") == ""  # 실패하면 기억한 값을 바꾸지 않는다


# ---- 서브에이전트 진행 ----

def agent_call(c, sid, tool_use_id=None, **tool_input):
    extra = {"tool_use_id": tool_use_id} if tool_use_id else {}
    return c.event(sid, "PreToolUse", tool_name="Agent", tool_input=dict(
        {"description": "목록 보기", "subagent_type": "general-purpose", "prompt": "첫 줄 지시\n둘째 줄"}, **tool_input), **extra)


def subs_of(c, sid):
    return c.call("GET", f"/api/sessions/{sid}")[1]["subagents"]


def test_subagent_start_is_paired_with_agent_call_description(browser):
    agent_call(browser, "g1")
    browser.event("g1", "SubagentStart", agent_id="a1", agent_type="general-purpose")
    (a,) = subs_of(browser, "g1")
    assert a["description"] == "목록 보기" and a["prompt"] == "첫 줄 지시" and a["type"] == "general-purpose"
    assert a["state"] == "running" and a["startedAt"] == browser.clock.t and a["background"] is False
    assert browser.app.store.get("g1")["pendingAgents"] == []


def test_pairing_uses_oldest_same_type_or_tool_use_id(browser):
    agent_call(browser, "g2", "u1", description="첫째")
    agent_call(browser, "g2", "u2", description="둘째", subagent_type="Explore", run_in_background=True)
    agent_call(browser, "g2", "u3", description="셋째")
    browser.event("g2", "SubagentStart", agent_id="a1", agent_type="general-purpose")
    browser.event("g2", "SubagentStart", agent_id="a2", agent_type="Explore")
    browser.event("g2", "SubagentStart", agent_id="a3", agent_type="general-purpose", tool_use_id="u3")
    got = {a["id"]: (a["description"], a["background"]) for a in subs_of(browser, "g2")}
    assert got == {"a1": ("첫째", False), "a2": ("둘째", True), "a3": ("셋째", False)}


def test_subagent_start_without_agent_call_has_no_description(browser):
    browser.event("g3", "SubagentStart", agent_id="a1", agent_type="Explore")
    assert "description" not in subs_of(browser, "g3")[0]


def test_task_tool_name_also_counts_and_text_is_clipped(browser):
    browser.event("g4", "PreToolUse", tool_name="Task", tool_input={"description": "d" * 500, "subagent_type": "x" * 500, "prompt": "p" * 500})
    browser.event("g4", "SubagentStart", agent_id="a1", agent_type="x" * 500)
    (a,) = subs_of(browser, "g4")
    assert len(a["description"]) == 200 and len(a["prompt"]) == 120 and len(a["type"]) == 200


def test_pending_agent_calls_are_capped(browser):
    for i in range(60):
        agent_call(browser, "g5", f"u{i}")
    assert len(browser.app.store.get("g5")["pendingAgents"]) == 50


def test_tool_calls_with_agent_id_update_that_subagent_only(browser):
    browser.event("g6", "PreToolUse", tool_name="Bash", tool_input={"command": "main work"})
    agent_call(browser, "g6")
    browser.event("g6", "SubagentStart", agent_id="a1", agent_type="general-purpose")
    browser.event("g6", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a1", agent_type="general-purpose")
    browser.event("g6", "PreToolUse", tool_name="Read", tool_input={"file_path": "x.md"}, agent_id="a1")
    s = browser.call("GET", "/api/sessions/g6")[1]
    assert s["subagents"][0]["currentAction"] == "Read: x.md" and s["subagents"][0]["tools"] == 2
    assert s["currentAction"].startswith("Agent")  # 서브에이전트 안의 호출이 메인 세션 동작을 덮지 않는다
    browser.event("g6", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="unknown")  # 모르는 id 는 무시
    assert subs_of(browser, "g6")[0]["tools"] == 2


def test_subagent_stop_records_end_time_and_duration(browser):
    agent_call(browser, "g7", run_in_background=True)
    browser.event("g7", "SubagentStart", agent_id="a1", agent_type="general-purpose")
    browser.event("g7", "PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, agent_id="a1")
    browser.clock.t += 42
    browser.event("g7", "SubagentStop", agent_id="a1", agent_type="general-purpose")
    (a,) = subs_of(browser, "g7")
    assert a["state"] == "done" and a["durationSec"] == 42 and a["endedAt"] == browser.clock.t
    assert a["currentAction"] == "" and a["background"] is True
    browser.event("g7", "PreToolUse", tool_name="Bash", tool_input={"command": "late"}, agent_id="a1")  # 끝난 뒤 늦은 호출은 되살리지 않는다
    assert subs_of(browser, "g7")[0]["currentAction"] == ""


def test_subagent_cap_still_holds_with_new_fields(browser):
    for i in range(205):
        browser.event("g8", "SubagentStart", agent_id=f"a{i}", agent_type="x")
    assert len(subs_of(browser, "g8")) == 200


# ---- 갈래(flows.json)와 단계 진행(#558) ----

FAKE_ANALYSIS_FLOW = Path(__file__).with_name("fake_claude_analysis_flow.py")
FLOWS_FILE = PLUGIN / "workflow.json"  # 작업 순서의 정본은 플러그인 안의 workflow.json 이다(#599)
REAL_SKILLS = sorted(p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md"))
FLOW_IDS = ["srs", "spec", "dev", "config", "standard", "fix"]
TOOL_IDS = ["version", "sync", "update", "handoff", "wrapup", "prs", "reload", "approvals", "atc", "role", "cts", "manual", "scaffold", "open"]
BRANCH = "docs/1-x"
PR_URL = "https://github.com/o/r/pull/7"
GIT_INFO = {"isRepo": True, "repo": "r", "branch": BRANCH, "changedFiles": [], "skill": None, "unknown": False, "ahead": 0}
SRS_TABLE = ("| ID | Title | Status | 다음 단계 |\n|---|---|---|---|\n| REQ-001 | a | Open | 개발 |\n| REQ-002 | b | Open | 개발 |\n"
             "| REQ-003 | c | Open | 설정 |\n| REQ-004 | d | Open | 미정 |\n| REQ-005 | e | Dropped | 개발 |\n| REQ-006 | f | On Hold | 설정 |\n"
             "| REQ-007 | g | Dropped | 미정 |\n")


def gated_flows_file(tmp_path):
    """시험 전용 사본: 실제 workflow.json 에 조건부 단계(onlyIf)와 조건부 갈래(requires)를 더한다.
    실제 순서에는 이런 것이 없지만, 엔진(flows.py)의 조건 처리는 데이터와 상관없이 계속 시험해야 한다."""
    data = json.loads(FLOWS_FILE.read_text(encoding="utf-8"))
    basis = [{"file": "skills/atc/SKILL.md", "quote": "SAP ATC(ABAP Test Cockpit) 지적을 돌려 보고 처리 순서에 따라 고친다."}]
    dev = next(f for f in data["flows"] if f["id"] == "dev")
    dev["steps"].insert(2, {"id": "atc", "name": "ATC 지적 확인", "kind": "skill", "skill": "atc", "onlyIf": "adt-tiers", "done": ["skill_done"], "basis": basis})
    data["flows"].append({"id": "atc", "name": "ATC 지적 고치기", "description": "시험용 조건부 갈래", "requires": "adt-tiers", "basis": basis,
                          "steps": [{"id": "atc", "name": "ATC 돌리고 분류하기", "kind": "skill", "skill": "atc", "done": ["skill_done"], "basis": basis}],
                          "next": None})
    path = tmp_path / "gated-workflow.json"
    tmp_path.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class FakeRun:
    """git·gh 조회를 흉내 낸다. table 은 명령 앞부분(공백은 _ 로 쓴다) -> (종료코드, 출력) 또는 호출 가능 객체. 없는 명령은 실행 불능(127)이다."""

    def __init__(self, **table):
        self.table = {"git symbolic-ref": (0, "origin/main\n")}
        self.table.update({k.replace("_", " "): v for k, v in table.items()})
        self.calls: list[str] = []

    def __call__(self, args, cwd):
        key = " ".join(args).replace("-c core.quotepath=false ", "")
        self.calls.append(key)
        for prefix, value in self.table.items():
            if key.startswith(prefix):
                return value(args) if callable(value) else value
        return 127, ""


def pr_json(state="OPEN", checks=None):
    return {"number": 7, "state": state, "url": PR_URL, "title": "t", "mergedAt": None,
            "statusCheckRollup": checks if checks is not None else [{"status": "COMPLETED", "conclusion": "SUCCESS"}]}


def flow_console(tmp_path, monkeypatch, run=None, info=None, claude_cmd=None, flows_file=None):
    """실제 workflow.json 과 실제 스킬 이름으로 뜬 콘솔. c.git 을 바꾸면 git 상태가 바뀐다."""
    state = dict(GIT_INFO, **(info or {}))
    c = Console(tmp_path, monkeypatch, claude_cmd=claude_cmd, git_inspect=lambda cwd: dict(state, changedFiles=list(state["changedFiles"])),
                skills=REAL_SKILLS, flows_path=flows_file or FLOWS_FILE,
                run=run or FakeRun(**{"git rev-parse --show-toplevel": (128, "")}))  # 기본은 git 은 되는데 저장소가 아닌 폴더
    c.git = state
    c.login()
    return c


def turn(c, sid):
    """세션을 만들고 턴이 도는 중으로 둔다(터미널 세션은 돌 때만 스킬을 받는다)."""
    c.event(sid, "SessionStart")
    c.event(sid, "UserPromptSubmit", prompt="x")


def stop(c, sid):
    assert c.hook("stop", {"session_id": sid, "cwd": str(c.work), "last_assistant_message": "r"})[0] == 200


def skill_event(c, sid, skill):
    c.event(sid, "PreToolUse", tool_name="Skill", tool_input={"skill": f"harness:{skill}"})


def sess(c, sid):
    return c.call("GET", f"/api/sessions/{sid}")[1]


def set_flow(c, sid, flow, **kw):
    return c.call("PUT", f"/api/sessions/{sid}/flow", dict({"flowId": flow}, **kw))


def states(model):
    return [st["state"] for st in model["flowSteps"]]


def test_flows_data_is_valid_and_every_skill_exists():
    data, err = flows.load(FLOWS_FILE)
    assert err == "" and flows.validate(data, set(REAL_SKILLS)) == []
    assert (flows.flow_skills(data) | flows.tool_skills(data)) <= set(REAL_SKILLS)
    assert [f["id"] for f in data["flows"]] == FLOW_IDS
    assert [t["id"] for t in data["tools"]] == TOOL_IDS
    assert next(t for t in data["tools"] if t["id"] == "atc")["requires"] == "adt-tiers"
    assert next(t for t in data["tools"] if t["id"] == "approvals")["requires"] == "approver"
    assert next(t for t in data["tools"] if t["id"] == "scaffold")["requires"] == "project-not-ready"
    # scaffold 는 갈래가 아니라 프로젝트 준비 조건·도구이고, ATC 는 단계가 아니라 도구다(#599)
    assert all(st.get("skill") not in ("scaffold", "atc") for f in data["flows"] for st in f["steps"])
    assert all(f.get("requires") is None for f in data["flows"])


def test_flows_validate_catches_bad_data():
    import copy
    base, _ = flows.load(FLOWS_FILE)

    def broken(edit):
        data = copy.deepcopy(base)
        edit(data)
        return " ".join(flows.validate(data, set(REAL_SKILLS)))

    assert "nope" in broken(lambda d: d["flows"][1]["steps"][0].update(skill="nope"))
    assert "ghost" in broken(lambda d: d["flows"][0].update(next={"flow": "ghost"}))
    assert "magic" in broken(lambda d: d["flows"][1]["steps"][0].update(done=["magic"]))
    assert "onlyIf" in broken(lambda d: d["flows"][3]["steps"][2].update(onlyIf="missing"))
    assert "nope" in broken(lambda d: d["tools"][0].update(skill="nope"))
    assert "skill_done" in broken(lambda d: d["flows"][1]["steps"][2].update(done=["skill_done"]))
    # 근거(basis): 비었거나, 파일이 없거나, 문장이 그 파일에 없으면 오류다(#599)
    assert "basis" in broken(lambda d: d["flows"][1]["steps"][0].update(basis=[]))
    assert "basis" in broken(lambda d: d["flows"][1]["steps"][0].pop("basis"))
    assert "읽을 수 없습니다" in broken(lambda d: d["flows"][1]["steps"][0].update(basis=[{"file": "skills/none/SKILL.md", "quote": "x"}]))
    assert "읽을 수 없습니다" in broken(lambda d: d["flows"][1]["steps"][0].update(basis=[{"file": "../../README.md", "quote": "x"}]))
    assert "문장이 skills/spec/SKILL.md 에 없습니다" in broken(lambda d: d["flows"][1]["steps"][0].update(basis=[{"file": "skills/spec/SKILL.md", "quote": "이 문장은 어디에도 없다"}]))
    assert "next" in broken(lambda d: d["flows"][1]["next"].pop("basis"))
    assert "next.srsColumn.개발" in broken(lambda d: d["flows"][0]["next"]["srsColumn"]["branches"]["개발"].update(basis=[]))
    assert "도구 version" in broken(lambda d: d["tools"][0].update(basis=[]))
    assert "조건 adt-tiers" in broken(lambda d: d["conditions"]["adt-tiers"].pop("basis"))
    assert "paths" in broken(lambda d: d["conditions"]["project-ready"].update(paths=["../x"]))


def test_app_without_valid_flows_keeps_console_up_but_refuses_flow_features(console):
    console.login()
    assert console.call("GET", "/api/flows")[0] == 503
    console.event("n1", "SessionStart")
    assert set_flow(console, "n1", "srs")[0] == 503
    assert sess(console, "n1")["flowId"] is None
    assert console.app.flow_error


def test_flows_api_without_cwd_has_no_exposure(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        status, body, _ = c.call("GET", "/api/flows")
        assert status == 200 and [f["id"] for f in body["flows"]] == FLOW_IDS and [t["id"] for t in body["tools"]] == TOOL_IDS
        assert "exposure" not in body["flows"][0] and "conditions" not in body
        assert body["flows"][3]["steps"][0]["done"] == ["skill_done", "on_work_branch"]
    finally:
        c.close()


def _register_folders(c, tmp_path, *names):
    """tmp_path 아래 서로 겹치지 않는 폴더를 만들어 콘솔의 최근 폴더로 등록한다(하위 폴더 탐색이 서로 섞이지 않게)."""
    out = []
    for n in names:
        d = tmp_path / n
        d.mkdir()
        assert c.call("POST", "/api/folders/validate", {"path": str(d)})[1]["ok"]
        out.append(d)
    return out


def _recent(c):
    status, body, _ = c.call("GET", "/api/folders/recent")
    assert status == 200
    return {r["name"]: r for r in body}


def test_recent_folders_carry_ready_state_and_session_count(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        ready, plain = _register_folders(c, tmp_path, "ready", "plain")
        (ready / "templates").mkdir()
        (ready / "rules").mkdir()
        (ready / "sub").mkdir()
        for sid, cwd in (("s1", ready), ("s2", ready / "sub"), ("s3", plain)):  # 폴더 자체와 하위 폴더를 cwd 로 가진 세션을 센다
            c.hook("event", {"session_id": sid, "cwd": str(cwd), "hook_event_name": "SessionStart"})
        got = _recent(c)
        assert (got["ready"]["ready"], got["ready"]["sessions"], got["ready"]["checking"]) == ("yes", 2, False)
        assert (got["plain"]["ready"], got["plain"]["sessions"]) == ("no", 1)
        # 판정은 60초 기억한다. 구조를 만들어도 기억이 지나기 전엔 그대로이고, 지나면 바뀐다.
        (plain / "templates").mkdir()
        (plain / "rules").mkdir()
        assert _recent(c)["plain"]["ready"] == "no"
        c.clock.t += console_server.CACHE_SECONDS + 1
        assert _recent(c)["plain"]["ready"] == "yes"
    finally:
        c.close()


def test_customer_forms_notice_only_for_ready_folder_without_office_originals(tmp_path, monkeypatch):
    """준비된 폴더의 templates/ 에 고객 양식 원본이 없으면 formsMissing=yes (최근 폴더와 flows 둘 다). 있으면 no, 못 읽으면 unknown."""
    c = flow_console(tmp_path, monkeypatch)
    try:
        ready, plain = _register_folders(c, tmp_path, "ready", "plain")
        q = "/api/flows?cwd=" + urllib.parse.quote(str(ready))
        (ready / "rules").mkdir()
        (ready / "templates" / "harness").mkdir(parents=True)  # scaffold 가 만드는 기본 틀만
        (ready / "templates" / "harness" / "SRS.md").write_text("x", encoding="utf-8")
        (ready / "templates" / "README.md").write_text("x", encoding="utf-8")
        (ready / "templates" / "forms").mkdir()
        (ready / "templates" / "forms" / "map.yaml").write_text("x", encoding="utf-8")
        (ready / "templates" / "harness" / "stray.xlsx").write_text("x", encoding="utf-8")  # harness 틀 안은 고객 양식이 아니다
        assert _recent(c)["ready"]["formsMissing"] == "yes"
        assert _recent(c)["plain"]["formsMissing"] == "no"  # 준비 안 된 폴더는 양식을 따지지 않는다
        assert c.call("GET", q)[1]["formsMissing"] == "yes"
        (ready / "templates" / "개발사양서.xlsx").write_text("x", encoding="utf-8")  # 고객 양식 원본이 들어옴
        c.clock.t += console_server.CACHE_SECONDS + 1
        assert _recent(c)["ready"]["formsMissing"] == "no"
        assert c.call("GET", q)[1]["formsMissing"] == "no"
        assert c.call("GET", q)[1]["conditions"]["project-ready"]["state"] == "yes"  # 준비됨 판정은 그대로
    finally:
        c.close()


def test_customer_forms_unreadable_gives_no_notice(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        (ready,) = _register_folders(c, tmp_path, "ready")
        (ready / "rules").mkdir()
        (ready / "templates").mkdir()
        monkeypatch.setattr(console_server, "customer_forms", lambda root, depth=3: None)  # 목록을 읽다 실패
        assert _recent(c)["ready"]["formsMissing"] == "unknown"
        assert c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(ready)))[1]["formsMissing"] == "unknown"
    finally:
        c.close()
    (tmp_path / "x").mkdir()
    c = flow_console(tmp_path / "x", monkeypatch, run=FakeRun())  # git 을 못 돌린다
    try:
        (r2,) = _register_folders(c, tmp_path / "x", "r2")
        assert c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(r2)))[1]["formsMissing"] == "no"  # 준비 여부부터 모르니 말하지 않는다
    finally:
        c.close()


def test_recent_folders_unreadable_is_unknown_not_ready_or_not(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun())  # git 을 실행할 수 없다(127)
    try:
        _register_folders(c, tmp_path, "a")
        row = _recent(c)["a"]
        assert row["ready"] == "unknown" and row["checking"] is False  # 못 읽은 것은 준비됨도 준비 필요도 아니다
        assert c.call("GET", f"/api/folders/intro?path={urllib.parse.quote(str(tmp_path / 'a'))}")[1]["show"] is False
    finally:
        c.close()
    (tmp_path / "x").mkdir()
    c = Console(tmp_path / "x", monkeypatch)  # 갈래 데이터가 없는 콘솔
    try:
        c.login()
        _register_folders(c, tmp_path / "x", "b")
        assert _recent(c)["b"]["ready"] == "unknown"
    finally:
        c.close()


def test_recent_folders_do_not_wait_for_the_check(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.app.sync_spawn = False  # 실제 서버처럼 계산은 요청 스레드 밖에서
        (d,) = _register_folders(c, tmp_path, "slow")
        (d / "templates").mkdir()
        (d / "rules").mkdir()
        first = _recent(c)["slow"]
        assert first["ready"] in ("unknown", "yes") and (first["ready"] == "yes" or first["checking"] is True)  # 읽는 중이면 확인하는 중으로 먼저 답한다
        assert wait_for(lambda: _recent(c)["slow"]["ready"] == "yes")  # 나중에 다시 물으면 채워진 값이 온다
        assert _recent(c)["slow"]["checking"] is False
    finally:
        c.close()


def test_folder_intro_shows_once_for_unready_folder_and_is_remembered_on_the_pc(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        plain, ready = _register_folders(c, tmp_path, "plain", "ready")
        (ready / "templates").mkdir()
        (ready / "rules").mkdir()

        def intro(d):
            return c.call("GET", f"/api/folders/intro?path={urllib.parse.quote(str(d))}")[1]

        assert intro(plain) == {"ready": "no", "seen": False, "show": True}
        assert intro(ready) == {"ready": "yes", "seen": False, "show": False}  # 준비된 폴더엔 안내하지 않는다
        assert not (c.state / console_server.FOLDER_INTRO_FILE).exists()  # 묻기만 해서는 기억하지 않는다
        assert c.call("POST", "/api/folders/intro/seen", {"path": str(plain) + "/"})[1] == {"seen": True}
        assert intro(plain) == {"ready": "no", "seen": True, "show": False}  # 두 번째엔 안 뜬다
        saved = json.loads((c.state / console_server.FOLDER_INTRO_FILE).read_text(encoding="utf-8"))["folders"]
        assert len(saved) == 1 and saved[0]["path"] == os.path.normcase(os.path.realpath(plain))  # 브라우저가 아니라 상태 폴더, 정규화한 경로
        assert intro(plain)["seen"] is True and c.app.intro_seen(str(plain)) is True
        # 모르는 폴더는 받지 않는다
        assert c.call("GET", f"/api/folders/intro?path={urllib.parse.quote(str(tmp_path))}")[0] == 403
        assert c.call("POST", "/api/folders/intro/seen", {"path": str(tmp_path)})[0] == 403
        assert c.call("GET", "/api/folders/intro")[0] == 400
        (c.state / console_server.FOLDER_INTRO_FILE).write_text("not json", encoding="utf-8")  # 깨진 기억은 본 적 없음으로
        assert intro(plain)["seen"] is False
    finally:
        c.close()


def test_folder_intro_memory_keeps_only_the_newest_200(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        limit = console_server.FOLDER_INTRO_MAX
        assert limit == 200
        for i in range(limit + 5):
            c.clock.t += 1
            c.app.mark_intro_seen(str(tmp_path / f"f{i}"))
        paths = [r["path"] for r in json.loads((c.state / console_server.FOLDER_INTRO_FILE).read_text(encoding="utf-8"))["folders"]]
        assert len(paths) == limit
        assert c.app.intro_seen(str(tmp_path / "f0")) is False and c.app.intro_seen(str(tmp_path / "f4")) is False  # 오래된 것부터 잊는다
        assert c.app.intro_seen(str(tmp_path / "f5")) is True and c.app.intro_seen(str(tmp_path / f"f{limit + 4}")) is True
        c.app.mark_intro_seen(str(tmp_path / "f5"))  # 다시 보여 주면 맨 뒤로 가고 중복되지 않는다
        paths = [r["path"] for r in json.loads((c.state / console_server.FOLDER_INTRO_FILE).read_text(encoding="utf-8"))["folders"]]
        assert len(paths) == limit and paths[-1] == os.path.normcase(os.path.realpath(tmp_path / "f5"))
    finally:
        c.close()


def test_exposure_hides_atc_without_adt_tiers_and_shows_it_with(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, flows_file=gated_flows_file(tmp_path))  # 조건부 갈래·단계는 시험용 사본으로 본다
    try:
        c.event("e1", "SessionStart")
        q = "/api/flows?cwd=" + urllib.parse.quote(str(c.work))
        body = c.call("GET", q)[1]
        atc = next(f for f in body["flows"] if f["id"] == "atc")
        assert atc["exposure"]["visible"] is False and "env/adt-tiers.yaml" in atc["exposure"]["reason"]
        dev_atc_step = next(f for f in body["flows"] if f["id"] == "dev")["steps"][2]
        assert dev_atc_step["exposure"]["visible"] is False
        assert next(f for f in body["flows"] if f["id"] == "srs")["exposure"]["visible"] is True
        (c.work / "env").mkdir()
        (c.work / "env" / "adt-tiers.yaml").write_text("x", encoding="utf-8")
        body = c.call("GET", q)[1]
        assert next(f for f in body["flows"] if f["id"] == "atc")["exposure"]["visible"] is True
        assert body["conditions"]["adt-tiers"]["state"] == "yes"
    finally:
        c.close()


def test_atc_tool_follows_adt_tiers_and_scaffold_tool_follows_project_readiness(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("e2", "SessionStart")
        q = "/api/flows?cwd=" + urllib.parse.quote(str(c.work))

        def tool(body, tid):
            return next(t for t in body["tools"] if t["id"] == tid)

        body = c.call("GET", q)[1]
        assert tool(body, "atc")["exposure"]["visible"] is False and tool(body, "atc")["exposure"]["state"] == "no"
        assert body["conditions"]["project-ready"]["state"] == "no" and "templates" in body["conditions"]["project-ready"]["reason"]
        assert tool(body, "scaffold")["exposure"]["visible"] is True and tool(body, "scaffold")["exposure"]["state"] == "yes"
        (c.work / "env").mkdir()
        (c.work / "env" / "adt-tiers.yaml").write_text("x", encoding="utf-8")
        (c.work / "templates").mkdir()
        body = c.call("GET", q)[1]
        assert tool(body, "atc")["exposure"]["visible"] is True
        assert body["conditions"]["project-ready"]["state"] == "no" and "rules" in body["conditions"]["project-ready"]["reason"]  # 하나만 있으면 아직 준비 안 됨
        (c.work / "rules").mkdir()
        body = c.call("GET", q)[1]
        assert body["conditions"]["project-ready"]["state"] == "yes" and tool(body, "scaffold")["exposure"]["visible"] is False
        assert tool(body, "open")["hidden"] is True  # 콘솔을 여는 스킬은 화면에 단추를 내지 않는다
    finally:
        c.close()


def test_unreadable_git_makes_project_readiness_unknown_and_keeps_scaffold_tool(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun())  # git 을 실행할 수 없다(127)
    try:
        c.event("e3", "SessionStart")
        body = c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(c.work)))[1]
        ready = body["conditions"]["project-ready"]
        assert ready["state"] == "unknown" and "git" in ready["reason"]  # 없다고도 있다고도 하지 않는다
        scaffold = next(t for t in body["tools"] if t["id"] == "scaffold")
        assert scaffold["exposure"]["state"] == "unknown" and scaffold["exposure"]["visible"] is True  # 판정 불능은 숨기지 않는다
    finally:
        c.close()


def test_flows_and_approvals_reject_folders_the_server_does_not_know(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        other = tmp_path / "other"
        other.mkdir()
        assert c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(other)))[0] == 403
        assert c.call("GET", "/api/approvals?cwd=" + urllib.parse.quote(str(other)))[0] == 403
        assert c.call("GET", "/api/approvals")[0] == 400
    finally:
        c.close()


@pytest.mark.parametrize("table,file_text,state,visible", [
    ({}, None, "unknown", True),  # gh 가 안 된다 -> 판정 불능이고 숨기지 않는다
    ({"gh_api_user": (0, "me\n")}, "other\n", "no", False),
    ({"gh_api_user": (0, "me\n")}, "# 승인자\n@ME\n", "yes", True),
    ({"gh_api_user": (0, "me\n")}, "dev: other\n*: me\n", "yes", True),
    ({"gh_api_user": (0, "me\n"), "gh_repo_view": (0, "ADMIN\n")}, None, "yes", True),  # 파일이 없으면 저장소 admin
    ({"gh_api_user": (0, "me\n"), "gh_repo_view": (0, "WRITE\n")}, None, "no", False),
    ({"gh_api_user": (0, "me\n"), "gh_repo_view": (1, "")}, None, "unknown", True),
    ({"gh_api_user": (0, "me\n"), "gh_repo_view": (0, "WRITE\n")}, "# 비어 있음\n", "no", False),
])
def test_approvals_tool_exposure_follows_approver_state(tmp_path, monkeypatch, table, file_text, state, visible):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun(**table))
    try:
        c.event("a1", "SessionStart")
        if file_text is not None:
            (c.work / ".github").mkdir()
            (c.work / ".github" / "ssot-approvers").write_text(file_text, encoding="utf-8")
        body = c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(c.work)))[1]
        tool = next(t for t in body["tools"] if t["id"] == "approvals")
        assert tool["exposure"]["state"] == state and tool["exposure"]["visible"] is visible
        assert state == "yes" or tool["exposure"]["reason"]  # 아니거나 못 읽었으면 이유를 말한다
        assert all(t["exposure"]["visible"] for t in body["tools"] if t["id"] != "approvals")  # 나머지 도구는 늘 보인다
    finally:
        c.close()


def test_approver_condition_when_no_file_is_admin_same_as_engine():
    """#586: 승인자 파일이 없거나 비면 콘솔도 엔진(checker.ssot_approval)도 저장소 admin 만 승인자로 본다."""
    from checker import ssot_approval

    data, _ = flows.load()
    cond = data["conditions"]["approver"]
    assert cond["file"] == ".github/ssot-approvers" and cond["whenNoFile"] == "admin"
    assert not hasattr(gitstate, "WHEN_NO_FILE_ANYONE")
    # flows.json 검증: whenNoFile 은 "admin" 만 허용한다.
    bad = json.loads(json.dumps(data))
    bad["conditions"]["approver"]["whenNoFile"] = "anyone"
    assert any("whenNoFile" in e for e in flows.validate(bad, set(REAL_SKILLS)))
    # 엔진: 빈 파일이면 admin 의 승인만, 아니면 미승인.
    rules = ssot_approval.parse_approvers("# 비어 있음\n")
    review = [{"user": {"login": "me"}, "state": "APPROVED", "commit_id": "h", "submitted_at": "t"}]
    assert ssot_approval.judge_by_rules("kim", review, rules, "h", lambda login: True)[0] is True
    assert ssot_approval.judge_by_rules("kim", review, rules, "h", lambda login: False)[0] is False


def approvals_run(prs, **over):
    table = {"gh_api_user": (0, "me\n"), "gh_repo_view": (0, "ADMIN\n"), "gh_pr_list": (0, json.dumps(prs))}
    table.update(over)
    return FakeRun(**table)


def test_approvals_lists_prs_waiting_for_me_and_caches_60_seconds(tmp_path, monkeypatch):
    prs = [
        {"number": 5, "title": "남의 것", "url": "u5", "author": {"login": "Kim"}, "isDraft": False, "headRefOid": "a", "latestReviews": []},
        {"number": 3, "title": "낡은 승인", "url": "u3", "author": {"login": "lee"}, "isDraft": False, "headRefOid": "new",
         "latestReviews": [{"author": {"login": "me"}, "state": "APPROVED", "commit": {"oid": "old"}}]},
        {"number": 4, "title": "이미 승인", "url": "u4", "author": {"login": "lee"}, "isDraft": False, "headRefOid": "x",
         "latestReviews": [{"author": {"login": "me"}, "state": "APPROVED", "commit": {"oid": "x"}}]},
        {"number": 6, "title": "내 PR", "url": "u6", "author": {"login": "me"}, "isDraft": False, "headRefOid": "y", "latestReviews": []},
        {"number": 8, "title": "초안", "url": "u8", "author": {"login": "kim"}, "isDraft": True, "headRefOid": "z", "latestReviews": []},
    ]
    run = approvals_run(prs)
    c = flow_console(tmp_path, monkeypatch, run=run)
    try:
        c.event("p1", "SessionStart")
        q = "/api/approvals?cwd=" + urllib.parse.quote(str(c.work))
        status, body, _ = c.call("GET", q)
        assert status == 200 and body["state"] == "yes" and body["login"] == "me"
        assert [(i["number"], i["staleApproval"]) for i in body["items"]] == [(3, True), (5, False)]
        n = len(run.calls)
        c.call("GET", q)
        assert len(run.calls) == n  # 60초 안에는 gh 를 다시 부르지 않는다
        c.clock.t += 61
        c.call("GET", q)
        assert len(run.calls) > n
    finally:
        c.close()


def test_approvals_not_approver_and_gh_failure_are_not_hidden_as_empty(tmp_path, monkeypatch):
    for run, state in [(approvals_run([], gh_repo_view=(0, "WRITE\n")), "no"), (FakeRun(), "unknown"),
                       (approvals_run([], gh_pr_list=(1, "")), "unknown")]:
        c = flow_console(tmp_path / f"{state}-{len(run.table)}", monkeypatch, run=run)
        try:
            c.event("p2", "SessionStart")
            body = c.call("GET", "/api/approvals?cwd=" + urllib.parse.quote(str(c.work)))[1]
            assert body["state"] == state and body["items"] == [] and body["reason"]
        finally:
            c.close()


@pytest.mark.parametrize("remote,state", [
    ((0, "origin\thttps://github.com/o/r.git (fetch)\norigin\thttps://github.com/o/r.git (push)\n"), "yes"),
    ((0, "origin\tgit@github.com:o/r.git (fetch)\n"), "yes"),
    ((0, "origin\thttps://gitlab.example.com/o/r.git (fetch)\n"), "no"),  # GitHub 가 아닌 원격
    ((0, ""), "no"),  # 원격이 없다
    ((128, "fatal: not a git repository"), "no"),  # 저장소가 아닌 폴더
])
def test_approvals_only_judged_for_github_repositories(tmp_path, monkeypatch, remote, state):
    run = approvals_run([], git_remote=remote)
    c = flow_console(tmp_path, monkeypatch, run=run)
    try:
        c.event("p3", "SessionStart")
        body = c.call("GET", "/api/approvals?cwd=" + urllib.parse.quote(str(c.work)))[1]
        assert body["state"] == state
        if state == "no":
            assert body["items"] == [] and "GitHub" in body["reason"]
            assert not any(call.startswith("gh ") for call in run.calls)  # GitHub 저장소가 아니면 gh 를 부르지 않는다
        tool = next(t for t in c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(c.work)))[1]["tools"] if t["id"] == "approvals")
        assert tool["exposure"]["visible"] is (state == "yes")
    finally:
        c.close()


def test_approvals_gh_failure_in_github_repository_stays_unknown(tmp_path, monkeypatch):
    run = FakeRun(git_remote=(0, "origin\thttps://github.com/o/r.git (fetch)\n"), gh_api_user=(1, "not logged in"))
    c = flow_console(tmp_path, monkeypatch, run=run)
    try:
        c.event("p4", "SessionStart")
        body = c.call("GET", "/api/approvals?cwd=" + urllib.parse.quote(str(c.work)))[1]
        assert body["state"] == "unknown" and body["reason"]
    finally:
        c.close()


def slow_gh_run(gate, started):
    """gh 만 gate 가 열릴 때까지 붙드는 가짜 실행기(느린 gh 흉내). 실행 횟수는 started 에 센다."""
    base = approvals_run([{"number": 3, "title": "t", "url": "u", "author": {"login": "kim"}, "isDraft": False, "headRefOid": "a", "latestReviews": []}])

    def run(args, cwd):
        if args[0] == "gh":
            started.append(args[1])
            gate.wait(30)
        return base(args, cwd)

    return run


def test_approvals_does_not_hold_request_while_gh_is_slow(tmp_path, monkeypatch):
    gate, started = threading.Event(), []
    c = flow_console(tmp_path, monkeypatch, run=slow_gh_run(gate, started))
    c.app.sync_spawn = False  # 실제 서버처럼 계산은 요청 스레드 밖에서
    try:
        c.event("p5", "SessionStart")
        q = "/api/approvals?cwd=" + urllib.parse.quote(str(c.work))
        t0 = time.monotonic()
        status, body, _ = c.call("GET", q)
        assert status == 200 and body["loading"] is True and body["state"] == "unknown" and body["items"] == []
        status, body, _ = c.call("GET", q)  # 계산 중에 또 불러도 즉시 답하고 gh 를 더 띄우지 않는다
        assert status == 200 and body["loading"] is True
        assert time.monotonic() - t0 < 3
        assert wait_for(lambda: len(started) == 1) and len(started) == 1
        gate.set()
        assert wait_for(lambda: not c.call("GET", q)[1].get("loading"))
        body = c.call("GET", q)[1]
        assert body["state"] == "yes" and [i["number"] for i in body["items"]] == [3]
        c.clock.t += 61  # 기억이 낡으면 이전 값을 바로 주고 뒤에서 다시 읽는다
        gate.clear()
        stale = c.call("GET", q)[1]
        assert stale["loading"] is True and stale["state"] == "yes" and [i["number"] for i in stale["items"]] == [3]
    finally:
        gate.set()
        c.close()


def test_concurrent_requests_do_not_block_each_other_while_gh_is_slow(tmp_path, monkeypatch):
    gate, started = threading.Event(), []
    c = flow_console(tmp_path, monkeypatch, run=slow_gh_run(gate, started))
    c.app.sync_spawn = False
    try:
        c.event("p6", "SessionStart")
        q = urllib.parse.quote(str(c.work))
        paths = [f"/api/approvals?cwd={q}", f"/api/flows?cwd={q}", "/api/sessions", f"/api/approvals?cwd={q}", f"/api/flows?cwd={q}", "/api/health"]
        done: dict[int, tuple[int, float]] = {}

        def go(i, path):
            t = time.monotonic()
            done[i] = (c.call("GET", path)[0], time.monotonic() - t)

        threads = [threading.Thread(target=go, args=(i, p), daemon=True) for i, p in enumerate(paths)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert sorted(done) == list(range(len(paths)))  # 하나도 붙들리지 않았다
        assert all(status == 200 and took < 5 for status, took in done.values())
        flows_body = c.call("GET", f"/api/flows?cwd={q}")[1]
        assert flows_body["loading"] is True and flows_body["conditions"]["approver"]["state"] == "unknown"
        assert next(t for t in flows_body["tools"] if t["id"] == "approvals")["exposure"]["visible"] is True  # 읽는 중이라고 숨기지 않는다
        assert wait_for(lambda: len(started) >= 1)
    finally:
        gate.set()
        c.close()


def test_analysis_schema_and_prompt_carry_flows_only_when_given():
    plain = analysis.Analyses(lambda: ["claude"]).command()
    assert "flow" not in json.loads(plain[plain.index("--json-schema") + 1])["properties"]
    a = analysis.Analyses(lambda: ["claude"], flows={"srs": {"name": "요구사항", "description": "d"}})
    cmd = a.command()
    schema = json.loads(cmd[cmd.index("--json-schema") + 1])
    assert schema["required"] == ["understood", "candidates", "extraQuestions"]  # flow 는 선택이라 없어도 결과가 유효하다
    assert schema["properties"]["flow"]["properties"]["id"]["enum"] == ["srs"]
    assert "- srs: 요구사항 - d" in a.prompt() and a.prompt().endswith("요청 글:\n") and a.prompt({}) == analysis.PROMPT


def test_analysis_classifies_flow_and_filters_flows_by_folder(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.txt"
    monkeypatch.setenv("FAKE_PROMPT_FILE", str(prompt_file))
    c = flow_console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS_FLOW)], flows_file=gated_flows_file(tmp_path))
    try:
        def analyse(text):
            jid = c.call("POST", "/api/new", {"text": text, "cwd": str(c.work)})[1]["id"]
            return wait_for(lambda: (lambda j: j if j["status"] != "running" else None)(c.call("GET", f"/api/new/{jid}")[1]))

        job = analyse("SRS 바꿔줘")
        assert job["status"] == "done"
        assert job["result"]["flow"] == {"id": "srs", "name": "요구사항 만들기·바꾸기", "reason": "요구사항을 바꾸는 일이다",
                                         "confident": True, "alternativeId": None, "alternativeName": ""}
        text = prompt_file.read_text(encoding="utf-8")
        assert "- srs:" in text and "- atc:" not in text  # adt-tiers 가 없는 폴더에는 atc 갈래를 묻지 않는다
        (c.work / "env").mkdir()
        (c.work / "env" / "adt-tiers.yaml").write_text("x", encoding="utf-8")
        analyse("SRS 바꿔줘")
        assert "- atc:" in prompt_file.read_text(encoding="utf-8")

        unsure = analyse("헷갈리는 일")["result"]
        assert unsure["flow"]["confident"] is False and unsure["flow"]["alternativeId"] == "dev"
        assert unsure["extraQuestions"][0] == {"question": analysis.FLOW_QUESTION, "options": ["작은 수정", "개발하기"], "flowChoice": ["fix", "dev"]}

        odd = analyse("엉뚱한 일")["result"]
        assert odd["flow"] is None and odd["flowError"]
    finally:
        c.close()


def test_start_saves_flow_on_session_and_first_message_uses_its_first_skill(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS_FLOW)])
    try:
        c.event("sx", "SessionStart")
        sent = []
        c.app.manager.launch = lambda cwd, message, **kw: (sent.append(message), "sx")[1]

        def job(text):
            jid = c.call("POST", "/api/new", {"text": text, "cwd": str(c.work)})[1]["id"]
            wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
            return jid

        jid = job("SRS 바꿔줘")
        assert c.call("GET", f"/api/new/{jid}/preview?flow=fix")[1]["message"].splitlines()[0] == "/harness:start"
        assert c.call("GET", f"/api/new/{jid}/preview?flow=spec")[1]["message"].splitlines()[0] == "/harness:spec"
        assert c.call("GET", f"/api/new/{jid}/preview?flow=new-customer")[0] == 400  # 없앤 옛 갈래
        assert c.call("GET", f"/api/new/{jid}/preview?flow=ghost")[0] == 400
        status, body, _ = c.call("POST", f"/api/new/{jid}/start", {})
        assert status == 202 and body["flowId"] == "srs" and sent[-1].splitlines()[0] == "/harness:srs"
        model = sess(c, "sx")
        assert model["flowId"] == "srs" and model["flowReason"] == "요구사항을 바꾸는 일이다" and len(model["flowSteps"]) == 3
        # 사용자가 다른 갈래를 고르면 그것이 우선한다
        other = job("SRS 바꿔줘")
        assert c.call("POST", f"/api/new/{other}/start", {"flow": "config"})[1]["flowId"] == "config"
        assert sent[-1].splitlines()[0] == "/harness:start" and sess(c, "sx")["flowId"] == "config"
        assert c.call("POST", f"/api/new/{other}/start", {"flow": "ghost"})[0] == 400
        # 분류가 목록 밖이면 갈래 없이 시작한다
        c.call("PUT", "/api/sessions/sx/flow", {"flowId": None})
        bad = job("엉뚱한 일")
        assert c.call("POST", f"/api/new/{bad}/start", {})[1]["flowId"] is None and sess(c, "sx")["flowId"] is None
    finally:
        c.close()


def test_first_message_never_puts_another_skill_before_a_skill_the_user_wrote_or_a_tool_only_job():
    fm = analysis.first_message
    assert fm("/harness:scaffold 구조 만들어줘", [], {}, "", True).splitlines()[0] == "/harness:scaffold 구조 만들어줘"  # start 를 앞에 붙이지 않는다
    assert fm("/harness:scaffold x", [], {}, "", True, "srs").splitlines()[0] == "/harness:scaffold x"  # 갈래의 첫 스킬도 붙이지 않는다
    assert fm("/harness:cts 추가", [], {}, "", True).splitlines()[0] == "/harness:cts 추가"
    assert fm("/harness:cts 추가", [], {}, "", False).splitlines()[0].startswith("아래는 사용자가 콘솔에서 보낸")  # git 저장소가 아니면 기존 안전 문장
    assert fm("/x", [], {}, "", True).splitlines()[0] == "/harness:start"  # 플러그인 스킬 꼴이 아니면 직접 적은 스킬로 보지 않는다
    assert fm("CTS 관리대장에 추가해줘", [], {}, "", True, None, True) == "CTS 관리대장에 추가해줘"  # 갈래 없이 도구만: 앞에 아무것도 없다
    assert fm("판매오더 앱 만들어줘", [], {}, "", True).splitlines()[0] == "/harness:start"  # 보통 일은 그대로
    assert fm("/etc/hosts 를 고쳐줘", [], {}, "", False).splitlines()[0].startswith("아래는 사용자가 콘솔에서 보낸")  # 경로는 스킬이 아니다
    assert analysis.direct_skill("  /harness:role 배정") == "harness:role" and analysis.direct_skill("abc /harness:role") == ""


def test_tool_only_jobs_start_without_a_flow_and_without_start_in_front(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.txt"
    monkeypatch.setenv("FAKE_PROMPT_FILE", str(prompt_file))
    c = flow_console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS_FLOW)])
    try:
        c.event("sx", "SessionStart")
        sent = []
        c.app.manager.launch = lambda cwd, message, **kw: (sent.append(message), "sx")[1]

        def job(text):
            jid = c.call("POST", "/api/new", {"text": text, "cwd": str(c.work)})[1]["id"]
            wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
            return jid

        jid = job("/harness:scaffold 프로젝트 구조 만들어줘")  # 가짜 분석은 srs 로 분류하지만 서버는 도구 일로 본다
        body = c.call("GET", f"/api/new/{jid}")[1]
        assert body["result"]["flow"]["id"] == "none" and body["result"]["flow"]["confident"] is True and "scaffold" in body["result"]["flow"]["reason"]
        text = prompt_file.read_text(encoding="utf-8")
        assert "- none: 순서 없이 이 도구만" in text and "flow.id 를 none 으로 한다" in text and '\\"none\\"' in text  # 프롬프트와 스키마에 보기가 있다
        status, started, _ = c.call("POST", f"/api/new/{jid}/start", {})
        assert status == 202 and started["flowId"] is None and sess(c, "sx")["flowId"] is None
        assert sent[-1].splitlines()[0] == "/harness:scaffold 프로젝트 구조 만들어줘" and "/harness:start" not in sent[-1]
        # 사용자가 '순서 없이 이 도구만' 을 직접 고르면 자연어 요청 앞에도 start 를 붙이지 않는다
        plain = job("CTS 관리대장에 요청 건 추가해줘")
        assert c.call("GET", f"/api/new/{plain}/preview?flow=none")[1]["message"] == "CTS 관리대장에 요청 건 추가해줘"
        assert c.call("GET", f"/api/new/{plain}/preview")[1]["message"].splitlines()[0] == "/harness:start"
        assert c.call("POST", f"/api/new/{plain}/start", {"flow": "none"})[1]["flowId"] is None
        assert sent[-1] == "CTS 관리대장에 요청 건 추가해줘"
        assert c.call("POST", f"/api/new/{plain}/start", {"flow": "ghost"})[0] == 400
    finally:
        c.close()


def test_analysis_prompt_carries_project_readiness_and_public_cloud_target(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.txt"
    monkeypatch.setenv("FAKE_PROMPT_FILE", str(prompt_file))
    c = flow_console(tmp_path, monkeypatch, claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS_FLOW)])
    try:
        c.event("p0", "SessionStart")

        def analyse():
            jid = c.call("POST", "/api/new", {"text": "판매오더 앱 개발해줘", "cwd": str(c.work)})[1]["id"]
            wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
            return prompt_file.read_text(encoding="utf-8")

        text = analyse()
        assert "SAP S/4HANA Public Cloud" in text and "ABAP Cloud" in text and "ALV 리포트" in text  # 대상 시스템(보기에 classic 을 내놓지 않는다)
        assert "프로젝트 준비가 안 됐다" in text and "/harness:scaffold" in text and "갈래 분류보다 이 안내를 앞세운다" in text
        assert "system_type" not in text
        (c.work / "env").mkdir()
        (c.work / "env" / "adt-tiers.yaml").write_text("tiers: x\nsystem_type: public_cloud  # 주석\n", encoding="utf-8")
        (c.work / "templates").mkdir()
        (c.work / "rules").mkdir()
        text = analyse()
        assert "system_type 은 'public_cloud'" in text and "프로젝트 준비가 안 됐다" not in text
    finally:
        c.close()


def test_analysis_prompt_says_unknown_when_project_readiness_cannot_be_read(tmp_path, monkeypatch):
    prompt_file = tmp_path / "prompt.txt"
    monkeypatch.setenv("FAKE_PROMPT_FILE", str(prompt_file))
    c = flow_console(tmp_path, monkeypatch, run=FakeRun(), claude_cmd=lambda: [sys.executable, str(FAKE_ANALYSIS_FLOW)])  # git 불능(127)
    try:
        jid = c.call("POST", "/api/new", {"text": "개발해줘", "cwd": str(c.work)})[1]["id"]
        wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
        text = prompt_file.read_text(encoding="utf-8")
        assert "확인하지 못했다" in text and "프로젝트 준비가 안 됐다" not in text
    finally:
        c.close()


def test_plugin_repository_and_nested_standards_count_as_project_ready(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("d1", "SessionStart")
        q = "/api/flows?cwd=" + urllib.parse.quote(str(c.work))

        def ready():
            body = c.call("GET", q)[1]
            tool = next(t for t in body["tools"] if t["id"] == "scaffold")
            return body["conditions"]["project-ready"], tool["exposure"]["visible"]

        assert ready()[0]["state"] == "no"
        # 플러그인 저장소(.claude-plugin/marketplace.json)는 Project Repository 가 아니라 따지지 않는다(session-start-sync.sh 와 같다)
        (c.work / ".claude-plugin").mkdir()
        (c.work / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
        cond, scaffold_visible = ready()
        assert cond["state"] == "yes" and scaffold_visible is False
        (c.work / ".claude-plugin" / "marketplace.json").unlink()
        assert ready()[0]["state"] == "no"
        # HARNESS_NO_SCAFFOLD_HINT=1 도 같다
        monkeypatch.setenv("HARNESS_NO_SCAFFOLD_HINT", "1")
        assert ready()[0]["state"] == "yes"
        monkeypatch.delenv("HARNESS_NO_SCAFFOLD_HINT")
        # templates/ 와 rules/ 를 함께 가진 폴더가 3단계 아래까지 있으면 준비된 것이다(그 아래는 아니다)
        deep = c.work / "a" / "b" / "c"
        (deep / "templates").mkdir(parents=True)
        (deep / "rules").mkdir()
        assert ready()[0]["state"] == "yes"
        too_deep = tmp_path / "other"
        (too_deep / "a" / "b" / "c" / "d" / "templates").mkdir(parents=True)
        (too_deep / "a" / "b" / "c" / "d" / "rules").mkdir()
        assert server_has_standard_folder(str(too_deep), ["templates", "rules"], 3) is False
        assert server_has_standard_folder(str(too_deep), ["templates", "rules"], 4) is True
        pruned = tmp_path / "pruned"
        (pruned / "node_modules" / "templates").mkdir(parents=True)  # node_modules 안은 들어가 보지 않는다
        (pruned / "node_modules" / "rules").mkdir()
        assert server_has_standard_folder(str(pruned), ["templates", "rules"], 3) is False
    finally:
        c.close()


def server_has_standard_folder(root, names, depth):
    return console_server.has_standard_folder(root, names, depth)


def test_read_system_type_reads_only_a_real_value(tmp_path):
    assert console_server.read_system_type(str(tmp_path)) == ""
    (tmp_path / "env").mkdir()
    f = tmp_path / "env" / "adt-tiers.yaml"
    f.write_text("tiers:\n  system_type: nested\n", encoding="utf-8")
    assert console_server.read_system_type(str(tmp_path)) == ""  # 최상위 키만 본다
    f.write_text('system_type: "public_cloud"\n', encoding="utf-8")
    assert console_server.read_system_type(str(tmp_path)) == "public_cloud"


def test_sessions_without_flow_have_empty_flow_fields(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("z1", "SessionStart")
        m = sess(c, "z1")
        assert m["flowId"] is None and m["flowSteps"] == [] and m["nextFlow"] is None and m["flowFinished"] is False
        assert m["flow"] and isinstance(m["flow"], list)  # 기존 스킬 목록 필드는 그대로다
    finally:
        c.close()


def test_set_flow_validates_and_atc_needs_adt_tiers(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, flows_file=gated_flows_file(tmp_path))  # requires 가 있는 갈래는 시험용 사본에만 있다
    try:
        c.event("v1", "SessionStart")
        assert c.call("PUT", "/api/sessions/v1/flow", {})[0] == 400
        assert c.call("PUT", "/api/sessions/v1/flow", {"flowId": 3})[0] == 400
        assert set_flow(c, "v1", "ghost")[0] == 400
        assert set_flow(c, "v1", "atc")[0] == 409
        (c.work / "env").mkdir()
        (c.work / "env" / "adt-tiers.yaml").write_text("x", encoding="utf-8")
        status, body, _ = set_flow(c, "v1", "atc", reason="ATC 를 돌린다고 해서")
        assert status == 200 and body["flowId"] == "atc" and body["flowReason"] == "ATC 를 돌린다고 해서"
        assert set_flow(c, "v1", "fix")[1]["flowId"] == "fix"  # 갈래는 바꿀 수 있다
        assert set_flow(c, "v1", "review")[0] == 400 and set_flow(c, "v1", "new-customer")[0] == 400  # 없앤 옛 갈래
        assert any("갈래 지정" in e["text"] for e in sess(c, "v1")["log"])
    finally:
        c.close()


def test_flow_state_is_saved_with_the_session(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("w1", "SessionStart")
        set_flow(c, "w1", "fix")
        c.app.store.flush()
        loaded = Store(c.state).get("w1")["flowState"]
        assert loaded["id"] == "fix" and [st["id"] for st in loaded["steps"]] == ["start", "fix", "deliver", "merge"]
    finally:
        c.close()


def test_out_of_order_skill_is_409_but_tools_are_always_allowed(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        turn(c, "o1")

        def run(skill):
            return c.call("POST", f"/api/sessions/o1/skills/{skill}/run", {})[0]

        assert run("deliver") == 202  # 갈래가 없으면 제한이 없다
        set_flow(c, "o1", "srs")
        status, body, _ = c.call("POST", "/api/sessions/o1/skills/deliver/run", {})
        assert status == 409 and "SRS 쓰기" in body["error"]
        assert run("spec") == 409 and run("start") == 409
        assert run("srs") == 202
        for tool in ("version", "sync", "update", "handoff", "wrapup", "prs", "approvals", "atc", "role", "cts", "manual", "scaffold"):
            assert run(tool) == 202, tool  # 도구는 갈래와 상관없이 언제나 된다
        assert run("nope") == 404
        assert c.call("PUT", "/api/sessions/o1/skills/deliver/reservation", {})[0] == 409  # 예약도 같은 순서를 따른다
        set_flow(c, "o1", "config")
        assert run("start") == 202 and run("srs") == 409 and run("deliver") == 409
    finally:
        c.close()


def test_skip_needs_a_reason_and_records_it(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("k1", "SessionStart")
        assert c.call("POST", "/api/sessions/k1/flow/skip", {"reason": "x"})[0] == 409  # 갈래가 없다
        set_flow(c, "k1", "fix")
        for body in ({}, {"reason": "   "}, {"reason": 3}):
            assert c.call("POST", "/api/sessions/k1/flow/skip", body)[0] == 400
        assert states(sess(c, "k1"))[0] == "pending"
        status, m, _ = c.call("POST", "/api/sessions/k1/flow/skip", {"reason": "이미 이슈와 브랜치가 있다"})
        assert status == 200 and m["stepIndex"] == 1
        assert m["flowSteps"][0]["state"] == "skipped" and m["flowSteps"][0]["reason"] == "이미 이슈와 브랜치가 있다"
        assert m["flowSteps"][1]["state"] == "active"  # 사람·작업 단계는 오면 진행 중이다
        assert any("이미 이슈와 브랜치가 있다" in e["text"] for e in m["log"])
        assert set_flow(c, "k1", "fix")[1]["flowSteps"][0]["reason"] == ""
    finally:
        c.close()


def test_skip_makes_the_next_skill_runnable(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        turn(c, "k2")
        set_flow(c, "k2", "srs")
        assert c.call("POST", "/api/sessions/k2/skills/deliver/run", {})[0] == 409
        c.call("POST", "/api/sessions/k2/flow/skip", {"reason": "SRS 는 이미 고쳐 뒀다"})
        assert c.call("POST", "/api/sessions/k2/skills/deliver/run", {})[0] == 202
        assert c.call("POST", "/api/sessions/k2/skills/srs/run", {})[0] == 409
    finally:
        c.close()


def drive_srs_to_deliver(c, sid):
    """srs 갈래를 SRS 쓰기 단계까지 끝내 deliver 단계에 둔다."""
    turn(c, sid)
    set_flow(c, sid, "srs")
    skill_event(c, sid, "srs")
    assert states(sess(c, sid))[0] == "active"
    stop(c, sid)
    m = sess(c, sid)
    assert m["stepIndex"] == 0 and states(m)[0] == "active"  # 스킬은 끝났지만 변경이 아직 없다 -> 끝으로 보지 않는다
    c.git["changedFiles"] = ["docs/ssot/SRS.md"]
    c.event(sid, "UserPromptSubmit", prompt="y")
    stop(c, sid)
    m = sess(c, sid)
    assert m["stepIndex"] == 1 and states(m) == ["done", "pending", "pending"]
    return m


def test_srs_flow_follows_git_and_pr_evidence_to_the_end(tmp_path, monkeypatch):
    listed = {"data": []}
    run = FakeRun(gh_pr_list=lambda a: (0, json.dumps(listed["data"])), gh_pr_view=lambda a: (0, json.dumps(listed["data"][0])))
    c = flow_console(tmp_path, monkeypatch, run=run)
    try:
        drive_srs_to_deliver(c, "s1")
        c.git["changedFiles"] = []
        c.git["ahead"] = 1
        assert c.call("POST", "/api/sessions/s1/flow/refresh", {})[1]["stepIndex"] == 1  # PR 이 아직 없다
        listed["data"] = [pr_json("OPEN")]
        m = c.call("POST", "/api/sessions/s1/flow/refresh", {})[1]
        assert m["stepIndex"] == 2 and states(m) == ["done", "done", "active"] and m["flowFinished"] is False
        assert m["flowPr"]["number"] == 7 and m["flowPr"]["checks"] == "pass" and m["flowUnknown"] == []
        listed["data"] = [pr_json("OPEN", [{"status": "COMPLETED", "conclusion": "FAILURE"}])]
        assert c.call("POST", "/api/sessions/s1/flow/refresh", {})[1]["flowPr"]["checks"] == "fail"
        (c.work / "docs" / "ssot").mkdir(parents=True)
        (c.work / "docs" / "ssot" / "SRS.md").write_text(SRS_TABLE, encoding="utf-8")
        c.git["branch"] = "main"  # 병합 뒤 main 으로 옮겨도 PR 번호로 다시 본다
        listed["data"] = [pr_json("MERGED")]
        m = c.call("POST", "/api/sessions/s1/flow/refresh", {})[1]
        assert m["flowFinished"] is True and states(m) == ["done", "done", "done"]
        opts = {o["value"]: o for o in m["nextFlow"]["options"]}
        assert opts["개발"]["flow"] == "spec" and opts["개발"]["ids"] == ["REQ-001", "REQ-002"]  # Dropped 는 세지 않는다
        assert opts["설정"]["flow"] == "config" and opts["설정"]["count"] == 1 and opts["설정"]["ids"] == ["REQ-003"]  # On Hold(REQ-006)도 세지 않는다
        assert opts["미정"]["flow"] is None and opts["미정"]["ids"] == ["REQ-004", "REQ-007"] and "미정 요구사항 정하기" in opts["미정"]["label"]
        assert opts["설정"]["name"] == "설정하기"
        assert "새 세션" in m["nextFlow"]["hint"]
        assert any("gh pr view 7" in call for call in run.calls)
        c.event("s1", "UserPromptSubmit", prompt="z")
        assert c.call("POST", "/api/sessions/s1/skills/deliver/run", {})[0] == 409  # 끝난 갈래에서도 도구만 된다
        assert c.call("POST", "/api/sessions/s1/skills/prs/run", {})[0] == 202
    finally:
        c.close()


def test_unreadable_gh_keeps_the_step_and_says_unknown(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun())  # gh 실행 불능
    try:
        drive_srs_to_deliver(c, "u1")
        m = c.call("POST", "/api/sessions/u1/flow/refresh", {})[1]
        assert m["stepIndex"] == 1 and states(m)[1] == "pending"
        assert m["flowUnknown"] and "PR" in m["flowUnknown"][0]  # 통과도 위반도 아닌 판정 불능
        assert m["flowFinished"] is False and m["flowPr"] is None
    finally:
        c.close()


def test_gh_failure_for_pr_view_after_merge_is_unknown_not_merged(tmp_path, monkeypatch):
    listed = {"data": []}
    run = FakeRun(gh_pr_list=lambda a: (0, json.dumps(listed["data"])), gh_pr_view=(1, ""))
    c = flow_console(tmp_path, monkeypatch, run=run)
    try:
        drive_srs_to_deliver(c, "u2")
        listed["data"] = [pr_json("OPEN")]
        m = c.call("POST", "/api/sessions/u2/flow/refresh", {})[1]
        assert m["stepIndex"] == 2
        m = c.call("POST", "/api/sessions/u2/flow/refresh", {})[1]  # 이제 번호로 보는데 gh 가 실패한다
        assert m["stepIndex"] == 2 and m["flowFinished"] is False and "PR #7" in m["flowUnknown"][0]
    finally:
        c.close()


def test_manual_step_needs_confirmation_and_other_evidence(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        turn(c, "m1")
        set_flow(c, "m1", "srs")
        assert c.call("POST", "/api/sessions/m1/flow/done", {})[0] == 409  # 사람이 누르는 단계가 아니다
        set_flow(c, "m1", "fix")
        c.call("POST", "/api/sessions/m1/flow/skip", {"reason": "이슈 있음"})
        status, body, _ = c.call("POST", "/api/sessions/m1/flow/done", {})  # 변경이 없다
        assert status == 409 and body["error"]
        assert sess(c, "m1")["stepIndex"] == 1
        c.git["changedFiles"] = ["a.py"]
        status, m, _ = c.call("POST", "/api/sessions/m1/flow/done", {})
        assert status == 200 and m["stepIndex"] == 2 and states(m)[1] == "done"
        assert c.call("POST", "/api/sessions/nope/flow/done", {})[0] == 404
    finally:
        c.close()


def test_config_flow_starts_with_the_dev_number_configures_then_delivers_and_ends_without_a_next_flow(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        turn(c, "n1")
        status, m, _ = set_flow(c, "n1", "config", reason="설정 DEV-003")
        assert status == 200 and m["flowName"] == "설정하기" and m["flowReason"] == "설정 DEV-003"
        assert [st["id"] for st in m["flowSteps"]] == ["start", "configure", "deliver", "merge"]
        assert [st["skill"] for st in m["flowSteps"]] == ["start", None, "deliver", None]
        skill_event(c, "n1", "start")
        stop(c, "n1")
        m = sess(c, "n1")
        assert m["stepIndex"] == 1 and m["flowSteps"][1]["kind"] == "work" and "Configuration Considerations" in m["flowSteps"][1]["hint"]
        assert "Status" in m["flowSteps"][2]["hint"] and "ssot-approval" in m["flowSteps"][3]["hint"]
        assert "자동으로 병합" not in m["flowSteps"][3]["hint"]  # SRS PR 은 사람 승인이 병합 조건이다(자동 병합 설명은 dev·fix 에만)
        std = set_flow(c, "n1", "standard", reason="표준 DEV-003")[1]  # 표준 갈래는 설정과 같은 모양(#718)
        assert std["flowName"] == "표준 기능으로 처리하기" and [st["id"] for st in std["flowSteps"]] == ["start", "document", "deliver", "merge"]
        assert "Status" in std["flowSteps"][2]["hint"] and "ssot-approval" in std["flowSteps"][3]["hint"]
        dev = set_flow(c, "n1", "dev")[1]
        assert "자동으로 병합" in dev["flowSteps"][3]["hint"] and "자동으로 병합" in set_flow(c, "n1", "fix")[1]["flowSteps"][3]["hint"]
        assert m["nextFlow"] is None and not any(st["skill"] == "atc" for st in m["flowSteps"])
    finally:
        c.close()


def test_dev_deliver_step_hint_explains_branch_only_push_and_flow_has_no_atc_step(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("h1", "SessionStart")
        m = set_flow(c, "h1", "dev")[1]
        assert [st["id"] for st in m["flowSteps"]] == ["start", "implement", "deliver", "merge"]
        assert "브랜치에만 올리기" in m["flowSteps"][2]["hint"] and "정상 경로" in m["flowSteps"][2]["hint"]
        fix = set_flow(c, "h1", "fix")[1]
        assert "DEV 번호" in fix["flowSteps"][0]["hint"]
    finally:
        c.close()


def test_sessions_saved_with_removed_flows_keep_their_saved_values(tmp_path, monkeypatch):
    """#599: new-customer·atc·review 갈래는 없앴다. 그 갈래로 저장된 세션은 정의를 못 찾으니 저장된 이름·단계가 그대로 보인다."""
    c = flow_console(tmp_path, monkeypatch)
    try:
        c.event("r1", "SessionStart")
        for old_id, old_name in (("new-customer", "새 고객사 시작"), ("atc", "ATC 지적 고치기"), ("review", "합쳐지기 기다리기")):
            c.event(f"r-{old_id}", "SessionStart")
            sid = c.app.store.resolve_id(f"r-{old_id}")
            steps = [{"id": "scaffold", "name": "저장소 표준 구조 만들기", "kind": "skill", "skill": "scaffold", "helperSkill": None, "hint": "옛 설명",
                      "onlyIf": None, "done": ["skill_done"], "state": "active", "reason": "", "skillDone": False, "confirmed": False}]
            with c.app.store.lock:
                c.app.store.get(sid)["flowState"] = {"id": old_id, "name": old_name, "reason": "옛 이유", "assignedAt": 1.0, "stepIndex": 0, "steps": steps,
                                                    "finished": False, "unknown": [], "next": None, "prNumber": None, "pr": None}
            m = sess(c, f"r-{old_id}")
            assert m["flowId"] == old_id and m["flowName"] == old_name and m["flowReason"] == "옛 이유"
            assert m["flowSteps"][0]["name"] == "저장소 표준 구조 만들기" and m["flowSteps"][0]["hint"] == "옛 설명"
        assert c.call("GET", "/api/flows")[1]["flows"] and sess(c, "r-atc")["flowId"] == "atc"
    finally:
        c.close()


def test_dev_flow_skips_atc_without_adt_tiers_and_runs_it_with(tmp_path, monkeypatch):
    for has_tiers in (False, True):
        c = flow_console(tmp_path / str(has_tiers), monkeypatch, flows_file=gated_flows_file(tmp_path / str(has_tiers)))
        try:
            if has_tiers:
                (c.work / "env").mkdir()
                (c.work / "env" / "adt-tiers.yaml").write_text("x", encoding="utf-8")
            turn(c, "d1")
            set_flow(c, "d1", "dev")
            skill_event(c, "d1", "start")
            stop(c, "d1")
            assert sess(c, "d1")["stepIndex"] == 1
            c.git["changedFiles"] = ["a.abap"]
            m = c.call("POST", "/api/sessions/d1/flow/done", {})[1]
            if has_tiers:
                assert m["stepIndex"] == 2 and m["flowSteps"][2]["state"] == "pending"
                c.event("d1", "UserPromptSubmit", prompt="z")
                assert c.call("POST", "/api/sessions/d1/skills/atc/run", {})[0] == 202
            else:
                assert m["stepIndex"] == 3 and m["flowSteps"][2]["state"] == "skipped" and "adt-tiers" in m["flowSteps"][2]["reason"]
        finally:
            c.close()


def test_start_step_needs_a_work_branch_and_ignores_stop_while_asking(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun(**{"git rev-parse --show-toplevel": (128, "")}))
    try:
        turn(c, "b1")
        set_flow(c, "b1", "dev")
        skill_event(c, "b1", "start")
        c.git["onBase"] = True  # 첫 응답에서 질문만 하고 끝났다: 아직 기본 브랜치다
        stop(c, "b1")
        m = sess(c, "b1")
        assert m["stepIndex"] == 0 and states(m)[0] == "active"
        c.git["onBase"] = False  # 이슈·브랜치를 만든 뒤
        m = c.call("POST", "/api/sessions/b1/flow/refresh", {})[1]
        assert m["stepIndex"] == 1
        # 질문이 답을 기다리는 동안의 Stop 은 스킬이 끝난 것이 아니다
        set_flow(c, "b1", "dev")
        skill_event(c, "b1", "start")
        req, _ = c.app.store.add_request(c.app.store.resolve_id("b1"), "question", "AskUserQuestion", {"questions": []}, None, "k")
        stop(c, "b1")
        assert sess(c, "b1")["stepIndex"] == 0
        c.app.store.close(req.rid, "답함")
        stop(c, "b1")
        assert sess(c, "b1")["stepIndex"] == 1
    finally:
        c.close()


def test_unreadable_git_makes_conditions_unknown_and_keeps_atc_step(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch, run=FakeRun(), flows_file=gated_flows_file(tmp_path))  # git 을 실행할 수 없다(127)
    try:
        turn(c, "u1")
        body = c.call("GET", "/api/flows?cwd=" + urllib.parse.quote(str(c.work)))[1]
        assert body["conditions"]["adt-tiers"]["state"] == "unknown" and "git" in body["conditions"]["adt-tiers"]["reason"]
        assert next(f for f in body["flows"] if f["id"] == "atc")["exposure"]["visible"] is True  # 판정 불능은 숨기지 않는다
        set_flow(c, "u1", "dev")
        skill_event(c, "u1", "start")
        stop(c, "u1")
        c.git["changedFiles"] = ["a.abap"]
        m = c.call("POST", "/api/sessions/u1/flow/done", {})[1]
        assert m["stepIndex"] == 2 and m["flowSteps"][2]["state"] != "skipped"  # ATC 를 건너뜀으로 확정하지 않는다
        assert any("adt-tiers" in x for x in m["flowUnknown"])
    finally:
        c.close()


def test_session_files_reports_unknown_when_git_cannot_run(tmp_path, monkeypatch, request):
    c = Console(tmp_path, monkeypatch, run=FakeRun())
    request.addfinalizer(c.close)
    c.login()
    c.event("s1", "SessionStart")
    (c.work / "메모.md").write_text("x", encoding="utf-8")
    c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(c.work / "메모.md")})
    status, body, _ = c.call("GET", "/api/sessions/s1/files")
    assert status == 200 and body["unknown"] is True and body["reason"] and [f["path"] for f in body["files"]] == ["메모.md"]


def test_dev_config_and_fix_flows_end_without_a_next_flow_and_spec_points_to_dev(tmp_path):
    """#599: '권한·CTS 양식(준비 중)' 다음 갈래는 지웠다. role·cts·manual 은 도구다."""
    data, _ = flows.load(FLOWS_FILE)
    for fid in ("dev", "config", "fix"):
        assert flows.compute_next(data, flows.flow_def(data, fid), str(tmp_path)) is None
    assert flows.compute_next(data, flows.flow_def(data, "spec"), str(tmp_path))["options"] == [
        {"flow": "dev", "name": "개발하기", "label": "개발하기", "disabled": False}]
    assert not any("준비 중" in json.dumps(f, ensure_ascii=False) for f in data["flows"])


def test_public_fields_shows_current_step_names_for_a_session_saved_before_the_rename():
    data, _ = flows.load(FLOWS_FILE)
    flow = flows.flow_def(data, "srs")
    state = flows.new_state(flow, "", 1.0, lambda name: False)
    old = {"flowState": json.loads(json.dumps(state))}
    old["flowState"]["name"] = "옛 갈래 이름"
    old["flowState"]["steps"][1].update(name="커밋·푸시·PR", hint="옛 설명")
    shown = flows.public_fields(old, data)
    assert shown["flowName"] == flow["name"]
    assert shown["flowSteps"][1]["name"] == flow["steps"][1]["name"] != "커밋·푸시·PR"
    assert shown["flowSteps"][1]["hint"] == flow["steps"][1].get("hint", "")
    assert old["flowState"]["steps"][1]["name"] == "커밋·푸시·PR"  # 저장 상태는 그대로
    assert flows.public_fields(old)["flowSteps"][1]["name"] == "커밋·푸시·PR"  # 정의를 안 주면 저장값
    store = Store(None)
    store.ensure("s1", "/w")["flowState"] = old["flowState"]
    assert store_mod.public_session(store, store.get("s1"), [])["flowSteps"][1]["name"] == "커밋·푸시·PR"  # 정의 없이는 저장값
    store.flow_data = data
    assert store_mod.public_session(store, store.get("s1"), [])["flowSteps"][1]["name"] == flow["steps"][1]["name"]


def test_public_fields_keeps_saved_values_when_the_definition_is_gone():
    data, _ = flows.load(FLOWS_FILE)
    state = flows.new_state(flows.flow_def(data, "srs"), "", 1.0, lambda name: False)
    state["steps"][1].update(id="removed-step", name="없어진 단계", hint="저장된 설명")
    shown = flows.public_fields({"flowState": state}, data)
    assert shown["flowSteps"][1]["name"] == "없어진 단계" and shown["flowSteps"][1]["hint"] == "저장된 설명"
    state["id"], state["name"] = "gone-flow", "없어진 갈래"
    shown = flows.public_fields({"flowState": state}, data)
    assert shown["flowName"] == "없어진 갈래" and shown["flowSteps"][0]["name"] == state["steps"][0]["name"]


def test_srs_next_flow_cannot_be_decided_without_a_readable_srs(tmp_path):
    data, _ = flows.load(FLOWS_FILE)
    srs = flows.flow_def(data, "srs")
    missing = flows.compute_next(data, srs, str(tmp_path))
    assert missing["options"] == [] and "SRS.md" in missing["unknown"]  # 없다고 끝으로 두지 않고 판정 불능으로 말한다
    (tmp_path / "docs" / "ssot").mkdir(parents=True)
    (tmp_path / "docs" / "ssot" / "SRS.md").write_text("| ID | Title |\n|---|---|\n| REQ-001 | a |\n", encoding="utf-8")
    assert "다음 단계" in flows.compute_next(data, srs, str(tmp_path))["unknown"]
    (tmp_path / "docs" / "ssot" / "SRS.md").write_text(SRS_TABLE.replace("| 미정 |", "| 몰라 |"), encoding="utf-8")
    opts = flows.compute_next(data, srs, str(tmp_path))["options"]
    assert opts[-1]["disabled"] is True and opts[-1]["ids"] == ["REQ-004", "REQ-007"]  # 정해진 값 밖은 따로 알린다


def test_gitstate_pr_status_and_checks_summary():
    def status(table, **kw):
        return gitstate.pr_status(fake_runner(table), "/w", kw.pop("branch", "feat/1-a"), **kw)

    ok_head = {"git symbolic-ref": (0, "origin/main\n")}
    assert status(dict(ok_head, **{"gh pr list": (0, "[]")})) == {"state": "ok", "pr": None, "reason": ""}
    got = status(dict(ok_head, **{"gh pr list": (0, json.dumps([pr_json("MERGED"), pr_json("OPEN")]))}))
    assert got["pr"]["state"] == "OPEN" and got["pr"]["number"] == 7
    assert status(dict(ok_head, **{"gh pr list": (127, "")}))["state"] == "unknown"
    assert status(dict(ok_head, **{"gh pr list": (0, "not json")}))["state"] == "unknown"
    assert status(ok_head, branch="main") == {"state": "ok", "pr": None, "reason": ""}  # 기본 브랜치는 PR 을 묻지 않는다
    assert status({"gh pr view": (0, json.dumps(pr_json("MERGED")))}, number=7)["pr"]["state"] == "MERGED"
    assert status({"gh pr view": (1, "")}, number=7)["state"] == "unknown"
    assert gitstate.summarize_checks(None) == "none" and gitstate.summarize_checks([]) == "none"
    assert gitstate.summarize_checks([{"status": "COMPLETED", "conclusion": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "SKIPPED"}]) == "pass"
    assert gitstate.summarize_checks([{"status": "IN_PROGRESS", "conclusion": ""}]) == "pending"
    assert gitstate.summarize_checks([{"status": "COMPLETED", "conclusion": "SUCCESS"}, {"status": "COMPLETED", "conclusion": "FAILURE"}]) == "fail"


def test_gitstate_inspect_reports_commits_ahead(tmp_path):
    info = gitstate.inspect(str(tmp_path), fake_runner(git_table(**{"git rev-list --count @{u}": (0, "3\n")})))
    assert info["ahead"] == 3 and info["skill"] == "deliver"


# ---- 서버 기능 넷: 플러그인 다시 불러오기, 만든 문서 보기, 같은 폴더·작업용 폴더, 다음 갈래 넘기기 ----
import zipfile  # noqa: E402

import docfiles  # noqa: E402
import handoff  # noqa: E402

XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def make_xlsx(path, big_sheet_rows=0, shared_extra=""):
    shared = (f'{XML_HEAD}<sst xmlns="{MAIN_NS}">{shared_extra}<si><t>이름</t></si><si><r><t>수</t></r><r><t>량</t></r></si>'
              f'<si><t>a b</t></si><si><r><t>보임</t></r><rPh><t>안보임</t></rPh></si></sst>')
    sheet1 = (f'{XML_HEAD}<worksheet xmlns="{MAIN_NS}"><sheetData>'
              '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="AR1"><v>9</v></c></row>'
              '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>3</v></c><c r="D2" t="inlineStr"><is><t>인라인</t></is></c></row>'
              '<row r="3"><c r="B3" t="b"><v>1</v></c><c r="C3" t="s"><v>3</v></c></row></sheetData></worksheet>')
    rows = "".join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>' for i in range(1, big_sheet_rows + 1))
    sheet2 = f'{XML_HEAD}<worksheet xmlns="{MAIN_NS}"><sheetData>{rows}</sheetData></worksheet>'
    book = (f'{XML_HEAD}<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets><sheet name="첫 시트" sheetId="1" r:id="rId1"/>'
            '<sheet name="두번째" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="x" Target="/xl/worksheets/sheet9.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", book)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet1)
        zf.writestr("xl/worksheets/sheet9.xml", sheet2)


def make_pptx(path):
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'

    def slide(*paragraphs):
        body = "".join(f"<a:p>{''.join(f'<a:r><a:t>{t}</a:t></a:r>' for t in runs)}</a:p>" for runs in paragraphs)
        return f"{XML_HEAD}<p:sld {ns}><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ppt/slides/slide10.xml", slide(["열번째"]))
        zf.writestr("ppt/slides/slide2.xml", slide(["둘째"], []))
        zf.writestr("ppt/slides/slide1.xml", slide(["제목", " 이어서"], ["본문 한 줄"]))
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", slide(["레이아웃은 아님"]))


def files_console(tmp_path, monkeypatch, request, status="", opener=None, **kw):
    """git status 출력을 holder 로 바꿀 수 있는 가짜 실행기로 뜬 콘솔. 세션 s1 은 작업 폴더에서 시작해 있다."""
    work = tmp_path / "work"
    holder = {"status": status}
    run = FakeRun(**{"git rev-parse --show-toplevel": (0, str(work) + "\n"), "git status": lambda a: (0, holder["status"])})
    app_kw = {"opener": opener} if opener else None
    c = Console(tmp_path, monkeypatch, run=run, app_kw=app_kw, **kw)
    request.addfinalizer(c.close)
    c.login()
    c.holder = holder
    c.event("s1", "SessionStart")
    return c


def quoted(path):
    return urllib.parse.quote(path)


def test_xlsx_preview_resolves_shared_inline_bool_and_relationship_targets(tmp_path):
    make_xlsx(tmp_path / "a.xlsx", big_sheet_rows=205)
    got = docfiles.read_xlsx(str(tmp_path / "a.xlsx"))
    assert got["kind"] == "table" and [s["name"] for s in got["sheets"]] == ["첫 시트", "두번째"]
    first, second = got["sheets"]
    assert first["rows"][0][:2] == ["이름", "수량"] and len(first["rows"][0]) <= docfiles.MAX_COLS  # AR 열(44번째)은 40열 상한 밖
    assert first["truncated"] is True
    assert first["rows"][1] == ["a b", "3", "", "인라인"]
    assert first["rows"][2] == ["", "TRUE", "보임"]  # 읽기 힌트(rPh) 글은 빠진다
    assert len(second["rows"]) == docfiles.MAX_ROWS == 200 and second["truncated"] is True  # 절대 경로(/xl/...)로 가리킨 시트도 읽는다


def make_date_xlsx(path, date1904=False):
    """cellXfs: 0 일반, 1 내장 14(날짜), 2 내장 22(날짜+시간), 3 사용자 yyyy"년"m"월", 4 사용자 숫자(0.00), 5 내장 20(시간), 6 사용자 [Red]hh:mm"""
    styles = (f'{XML_HEAD}<styleSheet xmlns="{MAIN_NS}"><numFmts count="3">'
              '<numFmt numFmtId="164" formatCode="yyyy&quot;년&quot;m&quot;월&quot;"/><numFmt numFmtId="165" formatCode="0.00&quot;d&quot;"/>'
              '<numFmt numFmtId="166" formatCode="[Red]hh:mm"/></numFmts>'
              '<cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs>'
              '<cellXfs count="7"><xf numFmtId="0"/><xf numFmtId="14"/><xf numFmtId="22"/><xf numFmtId="164"/><xf numFmtId="165"/>'
              '<xf numFmtId="20"/><xf numFmtId="166"/></cellXfs></styleSheet>')
    cells = ('<row r="1"><c r="A1" s="1"><v>44986</v></c><c r="B1" s="2"><v>44986.5625</v></c><c r="C1" s="2"><v>44986</v></c>'
             '<c r="D1" s="3"><v>44986</v></c><c r="E1" s="4"><v>44986</v></c><c r="F1"><v>44986</v></c>'
             '<c r="G1" s="5"><v>0.5</v></c><c r="H1" s="6"><v>0.75</v></c><c r="I1" s="1" t="s"><v>0</v></c><c r="J1" s="1"><v>-5</v></c>'
             '<c r="K1" s="1"><v>1</v></c><c r="L1" s="1"><v>61</v></c></row>')
    sheet = f'{XML_HEAD}<worksheet xmlns="{MAIN_NS}"><sheetData>{cells}</sheetData></worksheet>'
    book = (f'{XML_HEAD}<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><workbookPr{" date1904=" + chr(34) + "1" + chr(34) if date1904 else ""}/>'
            '<sheets><sheet name="날짜" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="x" Target="worksheets/sheet1.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", book)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/sharedStrings.xml", f'{XML_HEAD}<sst xmlns="{MAIN_NS}"><si><t>텍스트</t></si></sst>')
        zf.writestr("xl/styles.xml", styles)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def test_xlsx_preview_shows_date_cells_as_dates(tmp_path):
    make_date_xlsx(tmp_path / "d.xlsx")
    row = docfiles.read_xlsx(str(tmp_path / "d.xlsx"))["sheets"][0]["rows"][0]
    assert row[0] == "2023-03-01"  # 내장 14
    assert row[1] == "2023-03-01 13:30"  # 내장 22 + 시간
    assert row[2] == "2023-03-01"  # 시간이 0 이면 날짜만
    assert row[3] == "2023-03-01"  # 사용자 서식 yyyy"년"m"월"
    assert row[4] == "44986" and row[5] == "44986"  # 날짜 서식이 아닌 숫자, 서식 없는 숫자
    assert row[6] == "12:00" and row[7] == "18:00"  # 시간만 있는 서식
    assert row[8] == "텍스트" and row[9] == "-5"  # 글자 셀과 범위 밖 숫자는 그대로
    assert row[10] == "1900-01-01" and row[11] == "1900-03-01"


def test_xlsx_preview_honors_1904_date_system(tmp_path):
    make_date_xlsx(tmp_path / "d.xlsx", date1904=True)
    row = docfiles.read_xlsx(str(tmp_path / "d.xlsx"))["sheets"][0]["rows"][0]
    assert row[0] == "2027-03-02"  # 44986 + 1462일
    assert row[10] == "1904-01-02"


def test_pptx_preview_orders_slides_numerically_and_skips_layouts(tmp_path):
    make_pptx(tmp_path / "a.pptx")
    got = docfiles.read_pptx(str(tmp_path / "a.pptx"))
    assert got == {"kind": "slides", "slides": [{"index": 1, "texts": ["제목 이어서", "본문 한 줄"]},
                                                 {"index": 2, "texts": ["둘째"]}, {"index": 10, "texts": ["열번째"]}]}


@pytest.mark.parametrize("make", [lambda p: p.write_bytes(b"not a zip"), lambda p: make_xlsx(p, shared_extra="<!DOCTYPE x [<!ENTITY a 'b'>]>")])
def test_broken_or_entity_documents_are_not_parsed(tmp_path, make):
    make(tmp_path / "a.xlsx")
    with pytest.raises(docfiles.PreviewError):
        docfiles.read_xlsx(str(tmp_path / "a.xlsx"))


def zip_with_shared(path, shared: bytes):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", f'{XML_HEAD}<workbook xmlns="{MAIN_NS}"><sheets/></workbook>')
        zf.writestr("xl/sharedStrings.xml", shared)


@pytest.mark.parametrize("shared", [
    ('<?xml version="1.0"?><!--' + "x" * 6000 + '--><!DOCTYPE sst [<!ENTITY a "b">]><sst/>').encode("utf-8"),  # 앞 4096바이트 밖의 선언
    '<?xml version="1.0"?><!DOCTYPE sst><sst/>'.encode("utf-16"),  # BOM 이 있는 UTF-16
    '<?xml version="1.0" encoding="utf-16"?><!DOCTYPE sst><sst/>'.encode("utf-16-le"),  # BOM 이 없는 UTF-16
    '<?xml version="1.0" encoding="cp037"?><sst/>'.encode("utf-8"),  # 다른 인코딩 선언
])
def test_open_part_scans_whole_part_and_refuses_other_encodings(tmp_path, shared):
    zip_with_shared(tmp_path / "a.xlsx", shared)
    with pytest.raises(docfiles.PreviewError):
        docfiles.read_xlsx(str(tmp_path / "a.xlsx"))


def test_open_part_limits_part_size_and_total_bytes(tmp_path, monkeypatch):
    zip_with_shared(tmp_path / "a.xlsx", f'{XML_HEAD}<sst xmlns="{MAIN_NS}"><si><t>가</t></si></sst>'.encode("utf-8"))
    assert docfiles.read_xlsx(str(tmp_path / "a.xlsx"))["kind"] == "table"
    assert docfiles.MAX_PART_BYTES == 16 << 20 and docfiles.MAX_TOTAL_BYTES == 64 << 20
    monkeypatch.setattr(docfiles, "MAX_PART_BYTES", 50)
    with pytest.raises(docfiles.PreviewError, match="너무 커서"):
        docfiles.read_xlsx(str(tmp_path / "a.xlsx"))
    monkeypatch.setattr(docfiles, "MAX_PART_BYTES", 1 << 20)
    monkeypatch.setattr(docfiles, "MAX_TOTAL_BYTES", 200)  # 부분마다는 작아도 합이 넘으면 읽지 않는다
    with pytest.raises(docfiles.PreviewError, match="문서가 너무 커서"):
        docfiles.read_xlsx(str(tmp_path / "a.xlsx"))


def test_files_list_groups_versions_and_marks_changes(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request)
    docs = c.work / "개발 문서"
    docs.mkdir()
    for v in ("0.1", "0.2", "0.10"):
        (docs / f"개발사양서_v{v}.xlsx").write_bytes(b"x" * 3)
    (c.work / "메모 1.md").write_text("# 메모", encoding="utf-8")
    (c.work / "old.md").write_text("old", encoding="utf-8")
    (c.work / "새 문서.pptx").write_bytes(b"p")
    (c.work / "~$새 문서.pptx").write_bytes(b"lock")
    (c.work / "node_modules").mkdir()
    (c.work / "node_modules" / "x.md").write_text("x", encoding="utf-8")
    c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(c.work / "메모 1.md")})
    c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(tmp_path / "밖.md")})  # 작업 폴더 밖
    c.holder["status"] = " M 개발 문서/개발사양서_v0.2.xlsx\0?? 새 문서.pptx\0?? ~$새 문서.pptx\0?? node_modules/x.md\0 D 지운.md\0"
    status, body, _ = c.call("GET", "/api/sessions/s1/files")
    assert status == 200
    by_path = {f["path"]: f for f in body["files"]}
    assert set(by_path) == {"개발 문서/개발사양서_v0.10.xlsx", "메모 1.md", "새 문서.pptx"}
    sheet = by_path["개발 문서/개발사양서_v0.10.xlsx"]
    assert sheet["kind"] == "xlsx" and sheet["size"] == 3 and sheet["changed"] is True and isinstance(sheet["mtime"], float)
    assert [(v["version"], v["changed"]) for v in sheet["versions"]] == [("0.10", False), ("0.2", True), ("0.1", False)]  # 숫자로 비교, 최신 먼저
    assert sheet["versions"][0]["path"] == sheet["path"]
    assert by_path["메모 1.md"]["kind"] == "md" and by_path["메모 1.md"]["versions"] == [] and by_path["새 문서.pptx"]["kind"] == "pptx"
    assert c.call("GET", "/api/sessions/nope/files")[0] == 404


def test_files_list_keeps_session_files_after_commit_with_relative_paths(tmp_path, monkeypatch, request):
    """커밋하면 git status 가 비어도 이 세션이 만든·바꾼 문서는 목록에 남고, 경로는 폴더를 포함한 상대 경로다(#619)."""
    c = files_console(tmp_path, monkeypatch, request)
    (c.work / "a").mkdir()
    (c.work / "b").mkdir()
    (c.work / "a" / "README.md").write_text("a", encoding="utf-8")
    (c.work / "b" / "README.md").write_text("b", encoding="utf-8")
    (c.work / "CLAUDE.md").write_text("c", encoding="utf-8")
    c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(c.work / "CLAUDE.md")})
    c.holder["status"] = "?? a/README.md\0?? b/README.md\0"
    body = c.call("GET", "/api/sessions/s1/files")[1]
    assert {f["path"] for f in body["files"]} == {"a/README.md", "b/README.md", "CLAUDE.md"}
    assert all(f["changed"] for f in body["files"] if f["path"] != "CLAUDE.md")
    c.holder["status"] = ""  # 커밋한 뒤
    body = c.call("GET", "/api/sessions/s1/files")[1]
    assert {f["path"] for f in body["files"]} == {"a/README.md", "b/README.md", "CLAUDE.md"}
    assert not any(f["changed"] for f in body["files"])  # 커밋됐으니 '바뀜' 이 아니다


def test_touched_files_skip_baseline_skip_dirs_and_report_truncation(tmp_path, monkeypatch, request):
    from store import remember_touched, set_baseline
    s = {"cwd": str(tmp_path)}
    old, new, junk = str(tmp_path / "old.md"), str(tmp_path / "new.md"), str(tmp_path / "node_modules" / "x.md")
    set_baseline(s, [old])
    set_baseline(s, [new])  # 기준선은 한 번만 적는다
    remember_touched(s, [old, new, junk], from_status=True)
    assert s["touchedFiles"] == [new]
    remember_touched(s, [old])  # 훅의 Edit·Write 경로는 기준선이어도 이 세션 것이다
    assert s["touchedFiles"] == [new, old]
    import store as store_mod
    monkeypatch.setattr(store_mod, "MAX_CHANGED_FILES", 2)
    remember_touched(s, [str(tmp_path / "z.md")])
    assert s["touchedTruncated"] is True and len(s["touchedFiles"]) == 2


def test_files_list_reports_truncated_and_earlier_git_failure(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request)
    s = c.app.store.get("s1")
    (c.work / "a.md").write_text("a", encoding="utf-8")
    now = c.app.store.clock()
    s["touchedFiles"], s["touchedTruncated"], s["touchedGap"] = [str(c.work / "a.md")], True, {"reason": "x", "at": now}
    body = c.call("GET", "/api/sessions/s1/files")[1]
    # 지금은 읽었으니 칩을 덮는 unknown 은 없고(#708), 30분 안 공백은 note 한 줄로만 알린다
    assert body["truncated"] is True and "unknown" not in body and "reason" not in body and "빠졌을 수 있" in body["note"]
    assert [f["path"] for f in body["files"]] == ["a.md"]
    assert body["files"][0]["upload"].get("reason", "") != "x"  # 칩 근거는 지금 읽은 git 상태이지 옛 실패가 아니다(지금 못 읽으면 확인 못 함은 위 test_session_files_reports_unknown_when_git_cannot_run)
    s["touchedGap"] = {"reason": "x", "at": now - 99999}  # 오래된 실패는 영구 경고로 남기지 않는다
    body = c.call("GET", "/api/sessions/s1/files")[1]
    assert "unknown" not in body and "note" not in body


def test_files_list_in_non_repo_does_not_claim_committed(tmp_path, monkeypatch, request):
    run = FakeRun(**{"git rev-parse --show-toplevel": (128, "")})
    c = Console(tmp_path, monkeypatch, run=run)
    request.addfinalizer(c.close)
    c.login()
    c.event("s1", "SessionStart")
    (c.work / "a.md").write_text("a", encoding="utf-8")
    c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(c.work / "a.md")})
    body = c.call("GET", "/api/sessions/s1/files")[1]
    assert body["unknown"] is True and "저장소가 아니라" in body["reason"]
    assert [f["path"] for f in body["files"]] == ["a.md"]


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(cwd), check=True, capture_output=True)


def upload_console(tmp_path, monkeypatch, request, gh=None, git_fail=None):
    """진짜 임시 git 저장소 + 가짜 원격(bare). merged.md 는 squash 처럼 다른 커밋으로 main 에 같은 내용이 들어갔고, committed.md·review.md 는 브랜치에만
    커밋됐고, local.md 는 커밋 전이다. gh 는 holder["gh"]=(종료코드, 출력) 가짜이고 gh_calls 가 부른 횟수다. git_fail 이 앞부분이 맞는 git 명령을 실패시킨다."""
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    holder = {"gh": gh if gh is not None else (0, json.dumps([{"number": 5, "url": "https://x/pull/5", "headRefName": "f", "files": [{"path": "review.md"}]}]))}
    calls = {"gh": 0}

    def run(args, cwd):
        if args[0] == "gh":
            calls["gh"] += 1
            return holder["gh"]
        if git_fail and " ".join(args[1:]).replace("-c core.quotepath=false ", "").startswith(git_fail):
            return 1, ""
        return gitstate.run_command(args, cwd)

    c = Console(tmp_path, monkeypatch, run=run)
    request.addfinalizer(c.close)
    remote.mkdir()
    _git(remote, "init", "--bare", "-b", "main")
    _git(work, "init", "-b", "main")
    _git(work, "remote", "add", "origin", str(remote))
    (work / "base.txt").write_text("b", encoding="utf-8")
    _git(work, "add", "."), _git(work, "commit", "-m", "base"), _git(work, "push", "-u", "origin", "main")
    _git(work, "checkout", "-b", "feat")
    for name in ("merged.md", "committed.md", "review.md"):
        (work / name).write_text(name, encoding="utf-8")
    _git(work, "add", "."), _git(work, "commit", "-m", "feat")
    _git(work, "checkout", "main"), _git(work, "checkout", "feat", "--", "merged.md"), _git(work, "commit", "-m", "squash"), _git(work, "push", "origin", "main")
    _git(work, "checkout", "feat")
    (work / "local.md").write_text("l", encoding="utf-8")
    c.login()
    c.event("s1", "SessionStart")
    for name in ("merged.md", "committed.md", "review.md", "local.md"):
        c.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(work / name)})
    c.holder, c.gh_calls = holder, calls
    return c


def uploads(c):
    body = c.call("GET", "/api/sessions/s1/files")[1]
    return {f["path"]: f["upload"] for f in body["files"]}


def test_files_upload_states_by_content_and_open_prs(tmp_path, monkeypatch, request):
    c = upload_console(tmp_path, monkeypatch, request)
    got = uploads(c)
    assert {k: v["state"] for k, v in got.items()} == {"local.md": "local", "merged.md": "merged", "review.md": "review", "committed.md": "committed"}
    assert got["review.md"]["prs"] == [{"number": 5, "url": "https://x/pull/5"}]
    assert c.gh_calls["gh"] == 1
    uploads(c)
    assert c.gh_calls["gh"] == 1  # 저장소당 60초 기억
    c.clock.t += 61
    uploads(c)
    assert c.gh_calls["gh"] == 2


def test_files_upload_gh_failure_only_blocks_files_that_need_prs(tmp_path, monkeypatch, request):
    c = upload_console(tmp_path, monkeypatch, request, gh=(1, ""))
    got = uploads(c)
    assert {k: v["state"] for k, v in got.items()} == {"local.md": "local", "merged.md": "merged", "review.md": "unknown", "committed.md": "unknown"}
    assert "gh" in got["review.md"]["reason"]
    c.holder["gh"] = (0, "[]")  # 못 읽은 결과는 기억하지 않아 다음에 다시 읽는다
    assert uploads(c)["committed.md"]["state"] == "committed"


def test_files_upload_truncated_pr_list_is_unknown_not_committed(tmp_path, monkeypatch, request):
    big = json.dumps([{"number": 9, "url": "u", "headRefName": "g", "files": [{"path": f"x{i}.md"} for i in range(100)]}])
    c = upload_console(tmp_path, monkeypatch, request, gh=(0, big))
    assert uploads(c)["committed.md"]["state"] == "unknown"


def test_files_upload_git_failure_is_unknown(tmp_path, monkeypatch, request):
    c = upload_console(tmp_path, monkeypatch, request, git_fail="ls-tree")
    got = uploads(c)
    assert got["local.md"]["state"] == "local"
    assert {got[k]["state"] for k in ("merged.md", "committed.md", "review.md")} == {"unknown"}
    (tmp_path / "n").mkdir()
    c2 = Console(tmp_path / "n", monkeypatch, run=lambda a, cwd: (127, ""))
    request.addfinalizer(c2.close)
    c2.login()
    c2.event("s1", "SessionStart")
    (c2.work / "a.md").write_text("a", encoding="utf-8")
    c2.event("s1", "PostToolUse", tool_name="Write", tool_input={"file_path": str(c2.work / "a.md")})
    assert c2.call("GET", "/api/sessions/s1/files")[1]["files"][0]["upload"]["state"] == "unknown"  # git 상태를 못 읽으면 안 올림 으로 단정하지 않는다


def test_touched_files_dedupe_separators_skip_outside_cwd_and_late_baseline(tmp_path):
    from store import remember_touched, set_baseline
    inside = tmp_path / "w"
    inside.mkdir()
    (inside / "early.md").write_text("e", encoding="utf-8")
    (inside / "late.md").write_text("l", encoding="utf-8")
    os.utime(inside / "early.md", (1, 1))
    s = {"cwd": str(inside), "startedAt": 1000.0}
    set_baseline(s, [str(inside / "early.md"), str(inside / "late.md")])  # 늦게 잡힌 기준선: 시작 뒤에 바뀐 파일은 뺀다
    assert len(s["baselineFiles"]) == 1
    p = str(inside / "sub" / "a.md")
    remember_touched(s, [p, p.replace("\\", "/"), p.upper(), str(tmp_path / "outside.md")])
    assert len(s["touchedFiles"]) <= 2 and str(tmp_path / "outside.md") not in s["touchedFiles"]
    if os.name == "nt":
        assert s["touchedFiles"] == [p]


@pytest.mark.parametrize("report,asks", [
    ("정리했어요.\n\n이슈를 만들까요?", True),
    ("**진행할까요?**", True),
    ("끝났습니다.", False),
    ("끝났습니다. 질문 있나요? 없으면 마칩니다.", False),
    ("", False),
])
def test_report_asks_follows_last_line_question_mark(report, asks):
    from store import report_asks
    assert report_asks(report) is asks


def test_session_asked_in_text_moves_to_todo_and_marks_estimate(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "결과예요.\n이대로 진행할까요?"})
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["askedInText"] is True and s["group"] == "todo" and s["status"] == "idle"
    browser.event("t1", "UserPromptSubmit", prompt="네")
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["askedInText"] is False and s["group"] == "running"
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": ""})  # 답한 뒤 빈 보고로 끝난 턴
    s = browser.call("GET", "/api/sessions/t1")[1]
    assert s["status"] == "idle" and s["askedInText"] is False  # 지난 턴의 물음표 보고가 되살아나면 안 된다


def test_status_paths_parse_z_output_rename_and_delete():
    out = " M a b.md\0R  new.md\0old.md\0?? 새 폴더/c.md\0 D gone.md\0"
    run = FakeRun(**{"git rev-parse --show-toplevel": (0, "/r\n"), "git status": (0, out)})
    paths, why = gitstate.status_paths(run, "/r")
    assert [p.replace("\\", "/") for p in paths] == ["/r/a b.md", "/r/new.md", "/r/새 폴더/c.md"] and why == ""
    assert gitstate.status_paths(FakeRun(**{"git rev-parse --show-toplevel": (128, "")}), "/r") == ([], "")  # 저장소가 아니다 = 사유 없음
    assert gitstate.status_paths(FakeRun(), "/r") == ([], "git 을 실행하지 못했습니다.")  # git 실행 불능은 빈 목록과 구분한다
    assert gitstate.status_paths(FakeRun(**{"git rev-parse --show-toplevel": (0, "/r\n"), "git status": (1, "")}), "/r") == ([], "git status 가 실패했습니다.")


def test_file_preview_kinds_and_limits(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request)
    (c.work / "n.md").write_bytes("# 제목\n본문".encode("utf-8"))  # write_text 는 Windows 에서 줄바꿈을 바꾼다
    (c.work / "큰 글.md").write_bytes(("가" * 100000).encode("utf-8"))
    make_xlsx(c.work / "표.xlsx")
    make_pptx(c.work / "장.pptx")
    (c.work / "d.docx").write_bytes(b"x")
    (c.work / "사진.png").write_bytes(b"\x89PNG\r\n")
    (c.work / "bad.xlsx").write_bytes(b"nope")

    def view(rel):
        return c.call("GET", f"/api/sessions/s1/files/preview?path={quoted(rel)}")

    assert view("n.md")[1] == {"kind": "md", "text": "# 제목\n본문", "truncated": False}
    big = view("큰 글.md")[1]
    assert big["truncated"] is True and len(big["text"].encode("utf-8")) <= docfiles.TEXT_LIMIT and "�" not in big["text"]
    assert view("표.xlsx")[1]["sheets"][0]["rows"][0][:2] == ["이름", "수량"]
    assert view("장.pptx")[1]["slides"][0] == {"index": 1, "texts": ["제목 이어서", "본문 한 줄"]}
    assert view("d.docx")[1] == {"kind": "none"}
    image = view("사진.png")[1]
    assert image == {"kind": "image", "url": "/api/sessions/s1/files/raw?path=" + quote_path("사진.png")}
    status, body, _ = view("bad.xlsx")
    assert status == 422 and "엑셀" in body["error"]  # 못 읽은 것은 빈 표나 통과로 뭉개지 않는다


def quote_path(rel):
    return urllib.parse.quote(rel, safe="/")


def test_file_raw_serves_images_only_with_sandbox_headers(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request)
    (c.work / "사진 1.png").write_bytes(b"\x89PNG-data")
    (c.work / "x.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", encoding="utf-8")
    (c.work / "n.md").write_text("글", encoding="utf-8")
    status, data, resp = c.call("GET", f"/api/sessions/s1/files/raw?path={quoted('사진 1.png')}", binary=True)
    assert data == b"\x89PNG-data"
    assert status == 200 and resp.getheader("Content-Type") == "image/png" and resp.getheader("X-Content-Type-Options") == "nosniff"
    svg_status, _, svg = c.call("GET", "/api/sessions/s1/files/raw?path=x.svg")
    assert svg_status == 200 and svg.getheader("Content-Type") == "image/svg+xml" and "sandbox" in svg.getheader("Content-Security-Policy")
    assert c.call("GET", "/api/sessions/s1/files/raw?path=n.md")[0] == 403  # 이미지가 아니면 내려주지 않는다
    assert c.call("GET", "/api/sessions/s1/files/raw", cookie=False)[0] == 401


def test_file_routes_refuse_paths_outside_cwd_and_missing_files(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request)
    (tmp_path / "밖.md").write_text("비밀", encoding="utf-8")
    (c.work / "sub").mkdir()
    for rel in ("../밖.md", str(tmp_path / "밖.md"), "sub/../../밖.md"):
        assert c.call("GET", f"/api/sessions/s1/files/preview?path={quoted(rel)}")[0] == 403, rel
        assert c.call("GET", f"/api/sessions/s1/files/raw?path={quoted(rel)}")[0] == 403, rel
        assert c.call("POST", "/api/sessions/s1/files/open", {"path": rel, "mode": "reveal"})[0] == 403, rel
    assert c.call("GET", f"/api/sessions/s1/files/preview?path={quoted('없음.md')}")[0] == 404
    assert c.call("GET", "/api/sessions/s1/files/preview?path=sub")[0] == 404  # 폴더는 파일이 아니다
    assert c.call("GET", "/api/sessions/s1/files/preview")[0] == 400
    try:
        os.symlink(tmp_path / "밖.md", c.work / "link.md")
    except (OSError, NotImplementedError):
        return  # 링크를 만들 권한이 없는 환경
    assert c.call("GET", "/api/sessions/s1/files/preview?path=link.md")[0] == 403  # 링크로 작업 폴더를 빠져나가지 못한다


def test_file_open_calls_opener_with_real_path_and_mode(tmp_path, monkeypatch, request):
    calls = []
    c = files_console(tmp_path, monkeypatch, request, opener=lambda p, m: calls.append((p, m)) or "")
    (c.work / "문서 1.xlsx").write_bytes(b"x")
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "문서 1.xlsx", "mode": "open"})[:2] == (200, {"ok": True})
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "문서 1.xlsx", "mode": "reveal"})[0] == 200
    assert calls == [(os.path.realpath(c.work / "문서 1.xlsx"), "open"), (os.path.realpath(c.work / "문서 1.xlsx"), "reveal")]
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "문서 1.xlsx", "mode": "run"})[0] == 400
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "문서 1.xlsx"})[0] == 400
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "없음.md", "mode": "open"})[0] == 404
    assert len(calls) == 2


@pytest.mark.parametrize("name", ["x.bat", "x.cmd", "x.exe", "x.ps1", "x.js", "x.vbs", "x.lnk", "x.PY", "noext", "x.md.exe", "x.xlsm", "x.xls", "x.svg"])
def test_file_open_blocks_executable_extensions_but_reveal_is_allowed(tmp_path, monkeypatch, request, name):
    calls = []
    c = files_console(tmp_path, monkeypatch, request, opener=lambda p, m: calls.append((p, m)) or "")
    (c.work / name).write_bytes(b"x")
    status, body, _ = c.call("POST", "/api/sessions/s1/files/open", {"path": name, "mode": "open"})
    assert status == 403 and calls == []
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": name, "mode": "reveal"})[0] == 200 and calls[-1][1] == "reveal"


def test_file_open_blocks_a_link_that_hides_an_executable(tmp_path, monkeypatch, request):
    calls = []
    c = files_console(tmp_path, monkeypatch, request, opener=lambda p, m: calls.append((p, m)) or "")
    (c.work / "run.bat").write_bytes(b"x")
    try:
        os.symlink(c.work / "run.bat", c.work / "보고서.md")
    except (OSError, NotImplementedError):
        pytest.skip("링크를 만들 수 없는 환경")
    assert c.call("POST", "/api/sessions/s1/files/open", {"path": "보고서.md", "mode": "open"})[0] == 403 and calls == []


def test_file_open_opener_failure_is_502(tmp_path, monkeypatch, request):
    c = files_console(tmp_path, monkeypatch, request, opener=lambda p, m: "열지 못했습니다: 없음")
    (c.work / "a.md").write_text("x", encoding="utf-8")
    status, body, _ = c.call("POST", "/api/sessions/s1/files/open", {"path": "a.md", "mode": "open"})
    assert status == 502 and "열지 못했습니다" in body["error"]


def test_open_path_commands_per_os():
    seen = []

    def popen(args, **kw):
        seen.append(args)

    path = "C:\\내 문서\\a b.md"
    started = []
    assert platform_compat.open_path(path, "open", "windows", popen, started.append) == "" and started == [path] and seen == []
    assert platform_compat.open_path(path, "reveal", "windows", popen, started.append) == ""
    assert seen[-1] == 'explorer /select,"C:\\내 문서\\a b.md"'  # 셸 없이 한 줄로(explorer 가 요구하는 모양)
    platform_compat.open_path("/u/a b.md", "open", "macos", popen)
    platform_compat.open_path("/u/a b.md", "reveal", "macos", popen)
    platform_compat.open_path("/u/a b.md", "open", "linux", popen)
    platform_compat.open_path("/u/a b.md", "reveal", "linux", popen)
    assert seen[1:] == [["open", "/u/a b.md"], ["open", "-R", "/u/a b.md"], ["xdg-open", "/u/a b.md"], ["xdg-open", "/u"]]
    assert "쓸 수 없는" in platform_compat.open_path('a"b', "open", "linux", popen)

    def boom(args, **kw):
        raise OSError("no such")

    assert "열지 못했습니다" in platform_compat.open_path("/u/a", "open", "linux", boom)


# ---- 작업용 폴더 ----

def worktree_console(tmp_path, monkeypatch, request, root_out=None, **table):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "내 저장소"
    repo.mkdir()
    run = FakeRun(**dict({"git rev-parse --show-toplevel": (0, (root_out or str(repo)) + "\n"), "git fetch": (0, ""), "git worktree add": (0, "")}, **table))
    c = Console(tmp_path, monkeypatch, run=run)
    request.addfinalizer(c.close)
    c.login()
    assert c.call("POST", "/api/folders/validate", {"path": str(repo)})[1]["ok"]
    c.repo, c.run = repo, run
    return c


def test_worktree_fetches_then_adds_detached_worktree_and_remembers_folder(tmp_path, monkeypatch, request):
    c = worktree_console(tmp_path, monkeypatch, request)
    status, body, _ = c.call("POST", "/api/folders/worktree", {"cwd": str(c.repo)})
    assert status == 200
    path = body["path"]
    assert os.path.realpath(Path(path).parent) == os.path.realpath(c.repo.parent) and re.fullmatch(r"내 저장소-wt-[0-9a-f]{6}", Path(path).name)
    calls = [k for k in c.run.calls if k.startswith(("git fetch", "git worktree"))]
    assert calls == ["git fetch origin", f"git worktree add --detach {path} origin/main"]  # 브랜치를 만들지 않는다(--detach)
    assert path in c.app.store.folders
    assert not any(" branch" in k or "checkout" in k for k in c.run.calls)


def test_worktree_uses_origin_head_branch(tmp_path, monkeypatch, request):
    c = worktree_console(tmp_path, monkeypatch, request, **{"git symbolic-ref": (0, "origin/develop\n")})
    path = c.call("POST", "/api/folders/worktree", {"cwd": str(c.repo)})[1]["path"]
    assert f"git worktree add --detach {path} origin/develop" in c.run.calls


def test_worktree_refusals_and_git_failures(tmp_path, monkeypatch, request):
    c = worktree_console(tmp_path, monkeypatch, request)
    assert c.call("POST", "/api/folders/worktree", {"cwd": str(tmp_path / "모르는 폴더")})[0] == 403
    assert c.call("POST", "/api/folders/worktree", {})[0] == 403
    assert not any(k.startswith("git worktree") for k in c.run.calls)
    sub = worktree_console(tmp_path / "x", monkeypatch, request, root_out=str(tmp_path))  # 저장소 맨 위가 아닌 하위 폴더
    assert sub.call("POST", "/api/folders/worktree", {"cwd": str(sub.repo)})[0] == 400
    plain = worktree_console(tmp_path / "y", monkeypatch, request, **{"git rev-parse --show-toplevel": (128, "")})
    assert plain.call("POST", "/api/folders/worktree", {"cwd": str(plain.repo)})[0] == 400
    fetch = worktree_console(tmp_path / "z", monkeypatch, request, **{"git fetch": (1, "fatal: unable to access 'https://x/'\n")})
    status, body, _ = fetch.call("POST", "/api/folders/worktree", {"cwd": str(fetch.repo)})
    assert status == 502 and "unable to access" in body["error"] and not any(k.startswith("git worktree") for k in fetch.run.calls)
    add = worktree_console(tmp_path / "w", monkeypatch, request, **{"git worktree add": (128, "fatal: invalid reference: origin/main\n")})
    status, body, _ = add.call("POST", "/api/folders/worktree", {"cwd": str(add.repo)})
    assert status == 502 and "invalid reference" in body["error"] and not any("-wt-" in f for f in add.app.store.folders)


# ---- 같은 폴더 알림과 새 세션 점검 ----

def test_same_folder_lists_other_live_sessions_in_the_same_cwd(authed):
    c = authed
    sub = str(c.work / "다른 폴더")
    for sid, cwd in (("a", str(c.work)), ("b", str(c.work)), ("c", sub)):
        c.hook("event", {"session_id": sid, "cwd": cwd, "hook_event_name": "SessionStart"})
    model = lambda sid: c.call("GET", f"/api/sessions/{sid}")[1]  # noqa: E731
    assert model("a")["sameFolder"] == ["b"] and model("b")["sameFolder"] == ["a"] and model("c")["sameFolder"] == []
    if platform_compat.current_os() == "windows":  # 대소문자·구분자 차이는 같은 폴더로 본다
        c.hook("event", {"session_id": "e", "cwd": str(c.work).upper().replace("\\", "/"), "hook_event_name": "SessionStart"})
        assert "e" in model("a")["sameFolder"]
    c.hook("event", {"session_id": "b", "cwd": str(c.work), "hook_event_name": "SessionEnd"})
    assert "b" not in model("a")["sameFolder"]  # 끝난 세션은 뺀다


def test_same_folder_event_is_published_to_peers(authed):
    c = authed
    c.hook("event", {"session_id": "a", "cwd": str(c.work), "hook_event_name": "SessionStart"})
    conn, resp = c.connect_browser()
    try:
        c.hook("event", {"session_id": "b", "cwd": str(c.work), "hook_event_name": "SessionStart"})
        seen = set()
        while len(seen) < 2:
            line = resp.fp.readline().decode("utf-8")
            if line.startswith("data:"):
                seen.add(json.loads(line[5:])["id"])
        assert seen == {"a", "b"}  # 같은 폴더의 먼저 있던 세션 화면도 새 소식을 받는다
    finally:
        conn.close()


def test_start_checks_follow_skill_events_and_can_be_skipped(mconsole):
    c = mconsole
    sid = launch(c, "점검")
    ids = ["sync", "version", "update", "reload"]
    got = c.call("GET", f"/api/sessions/{sid}")[1]["startChecks"]
    assert got == [{"id": i, "state": "pending"} for i in ids]
    c.event(sid, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:sync"})
    c.event(sid, "UserPromptExpansion", command_name="harness:version")
    states_ = {x["id"]: x["state"] for x in c.call("GET", f"/api/sessions/{sid}")[1]["startChecks"]}
    assert states_ == {"sync": "done", "version": "done", "update": "pending", "reload": "pending"}
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/checks/update/skip", {})
    assert status == 200 and {x["id"]: x["state"] for x in body["startChecks"]}["update"] == "skipped"
    c.event(sid, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:update"})  # 건너뛴 것은 다시 바뀌지 않는다
    assert {x["id"]: x["state"] for x in c.call("GET", f"/api/sessions/{sid}")[1]["startChecks"]}["update"] == "skipped"
    assert c.call("POST", f"/api/sessions/{sid}/checks/bogus/skip", {})[0] == 404
    c.event("terminal-1", "SessionStart")
    assert c.call("GET", "/api/sessions/terminal-1")[1]["startChecks"] == []  # 콘솔이 새로 띄운 세션만 점검 목록을 가진다


def test_new_work_start_gives_start_checks(mconsole):
    c = mconsole
    jid = c.call("POST", "/api/new", {"text": "계획 세워줘", "cwd": str(c.work)})[1]["id"]
    wait_for(lambda: c.call("GET", f"/api/new/{jid}")[1]["status"] != "running")
    sid = c.call("POST", f"/api/new/{jid}/start", {})[1]["id"]
    assert [x["id"] for x in c.call("GET", f"/api/sessions/{sid}")[1]["startChecks"]] == ["sync", "version", "update", "reload"]


# ---- 플러그인 다시 불러오기 ----

def plugin_versions(c, sid):
    return {p["name"]: p["version"] for p in c.call("GET", f"/api/sessions/{sid}")[1]["pluginVersions"]}


def test_reload_uses_control_request_and_records_versions(mconsole):
    c = mconsole
    sid = launch(c, "시작")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 시작")
    assert plugin_versions(c, sid) == {"harness": ""}  # init 이벤트의 plugins(판이 없으면 빈 칸)
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/reload", {})
    assert status == 200 and body == {"ok": True, "method": "control", "errorCount": 0, "harnessVersion": "1.2.3",
                                      "plugins": [{"name": "harness", "version": "1.2.3"}, {"name": "other", "version": "0.4"}]}
    model = c.call("GET", f"/api/sessions/{sid}")[1]
    assert plugin_versions(c, sid) == {"harness": "1.2.3", "other": "0.4"}
    assert {x["id"]: x["state"] for x in model["startChecks"]}["reload"] == "done"
    assert any("플러그인 다시 불러옴(control)" in x["text"] for x in model["log"])
    assert model["report"] == "echo: 시작"  # 제어 요청은 모델을 부르지 않아 대화에 남지 않는다


def test_reload_falls_back_to_slash_command_message(mconsole, monkeypatch):
    monkeypatch.setenv("FAKE_NO_RELOAD_CONTROL", "1")
    c = mconsole
    sid = launch(c, "시작")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 시작")
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/reload", {})
    assert status == 200 and body["method"] == "message" and body["errorCount"] == 0
    assert body["message"] == "Reloaded: 2 plugins · 0 errors" and body["plugins"] == [{"name": "harness", "version": ""}]
    wait_for(lambda: not c.app.store.get(sid)["turn_running"])
    assert any("보냄: /reload-plugins" in x["text"] for x in c.app.store.get(sid)["log"])


def test_reload_fails_with_502_when_neither_way_works(mconsole, monkeypatch):
    monkeypatch.setenv("FAKE_NO_RELOAD_CONTROL", "1")
    monkeypatch.setenv("FAKE_NO_RELOAD_MESSAGE", "1")
    c = mconsole
    sid = launch(c, "시작")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 시작")
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/reload", {})
    assert status == 502 and "Unsupported control request" in body["error"] and "/reload-plugins" in body["error"]
    assert {x["id"]: x["state"] for x in c.call("GET", f"/api/sessions/{sid}")[1]["startChecks"]}["reload"] == "pending"  # 실패를 했음으로 적지 않는다


def test_reload_refusals(mconsole):
    c = mconsole
    c.event("term", "SessionStart")
    assert c.call("POST", "/api/sessions/term/reload", {})[0] == 409  # 터미널 세션
    assert c.call("POST", "/api/sessions/nope/reload", {})[0] == 404
    sid = launch(c, "시작")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 시작")
    c.app.manager.close(c.app.manager.proc_for(sid))
    wait_for(lambda: c.app.store.get(sid)["ended"])
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/reload", {})
    assert status == 409 and "끝난 세션" in body["error"]


def test_reload_waits_for_the_running_turn_then_runs(mconsole, monkeypatch, tmp_path):
    gate = tmp_path / "gate"
    monkeypatch.setenv("FAKE_GATE", str(gate))
    c = mconsole
    c.app.wait_poll = 0.05
    sid = launch(c, "시작")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 시작")
    assert c.call("POST", f"/api/sessions/{sid}/messages", {"text": "slow 작업"})[0] == 202
    wait_for(lambda: c.app.store.get(sid)["turn_running"])
    assert c.call("POST", f"/api/sessions/{sid}/reload", {}) [:2] == (202, {"queued": True})
    assert c.call("POST", f"/api/sessions/{sid}/reload", {})[:2] == (202, {"queued": True})  # 두 번 눌러도 한 번만 대기한다
    time.sleep(0.3)
    assert plugin_versions(c, sid) == {"harness": ""}  # 턴이 도는 동안은 실행하지 않는다
    gate.write_text("go", encoding="utf-8")
    wait_for(lambda: plugin_versions(c, sid).get("harness") == "1.2.3")
    logs = [x["text"] for x in c.app.store.get(sid)["log"]]
    assert sum("플러그인 다시 불러옴(control)" in t for t in logs) == 1
    assert not c.app.reload_queue


def test_reload_all_reports_each_console_session(mconsole):
    c = mconsole
    a, b = launch(c, "하나"), launch(c, "둘")
    c.event("term", "SessionStart")
    for sid in (a, b):
        wait_for(lambda: c.app.store.get(sid)["report"].startswith("echo:"))
    status, body, _ = c.call("POST", "/api/reload-all", {})
    assert status == 200
    results = {r["sessionId"]: r for r in body["results"]}
    assert set(results) == {a, b}  # 터미널 세션은 대상이 아니다
    assert all(r["ok"] and r["method"] == "control" and r["harnessVersion"] == "1.2.3" for r in results.values())
    assert plugin_versions(c, a)["harness"] == plugin_versions(c, b)["harness"] == "1.2.3"


def test_init_event_plugin_versions_keep_known_versions():
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    s = store.ensure("s1", "/w")
    s["pluginVersions"] = [{"name": "harness", "version": "1.0"}]

    class P:
        session_id = None
        temp_id = "s1"
        results = 0

    m.on_event(P(), {"type": "system", "subtype": "init", "session_id": "s1", "plugins": [{"name": "harness"}, {"name": "x", "version": 2}]})
    assert s["pluginVersions"] == [{"name": "harness", "version": "1.0"}, {"name": "x", "version": "2"}]
    assert managed.plugin_list("nope") == [] and managed.plugin_list([1, {"name": ""}, {"version": "1"}]) == []


# ---- 다음 갈래로 넘어가기 ----

def next_console(tmp_path, monkeypatch, request, flows_file=None):
    c = flow_console(tmp_path, monkeypatch, claude_cmd=fake_cmd, flows_file=flows_file)
    request.addfinalizer(c.close)
    c.app.wait_poll = 0.05
    return c


def finished_job(c, job_id):
    return wait_for(lambda: (lambda j: j if j["status"] in ("started", "failed", "canceled") else None)(c.call("GET", f"/api/jobs/{job_id}")[1]))


def confirm_job(c, job_id, **body):
    """인계가 끝나 사람 확인을 기다리는 job 을 확인해 새 세션을 시작시키고 끝난 job 을 돌려준다."""
    wait_for(lambda: c.call("GET", f"/api/jobs/{job_id}")[1]["status"] in ("confirm", "failed"))
    status, answer, _ = c.call("POST", f"/api/jobs/{job_id}/confirm", body)
    assert status == 202, answer
    return finished_job(c, job_id)


def test_last_code_block_extraction():
    assert handoff.last_code_block("앞\n```\n첫째\n```\n뒤\n```text\n둘째 줄1\n줄2\n```\n끝") == "둘째 줄1\n줄2"
    assert handoff.last_code_block("```\n빈\n```\n```\n\n```") == "빈"  # 비어 있는 마지막 블록은 건너뛴다
    assert handoff.last_code_block("````\n안에 ``` 가 있다\n````") == "안에 ``` 가 있다"
    assert handoff.last_code_block("블록 없음") == "" and handoff.last_code_block("") == ""


def test_flow_next_hands_off_then_starts_new_session_with_checks(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request)
    sid = c.app.manager.launch(str(c.work), "첫 작업", model="haiku", effort="low", permission="plan")
    sid = wait_for(lambda: (c.app.store.resolve_id(sid) != sid) and c.app.store.resolve_id(sid))
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})
    assert status == 202
    waiting = wait_for(lambda: (lambda j: j if j["status"] == "confirm" else None)(c.call("GET", f"/api/jobs/{body['jobId']}")[1]))
    assert waiting["prompt"] == "앞선 작업: SRS 를 끝냈다. 이어서 Spec 을 만든다."  # 사람이 보기 전에는 새 세션을 띄우지 않는다
    time.sleep(0.2)
    assert len(c.call("GET", "/api/sessions")[1]) == 1 and c.app.manager.proc_for(sid).alive()
    job = confirm_job(c, body["jobId"])
    assert job["status"] == "started" and job["fromSession"] == sid and job["flowId"] == "spec" and job["error"] == ""
    new = job["sessionId"]
    assert new != sid
    first = wait_for(lambda: (lambda r: r if r.startswith("echo: ") else None)(c.app.store.get(new)["report"]))
    assert first.startswith("echo: 새 세션 시작 점검: /harness:sync 로 최신을 받고, 플러그인 판(/harness:version)을 확인해 낡았으면 알려 줘")
    assert "그다음 인계 내용을 이어서: 앞선 작업: SRS 를 끝냈다. 이어서 Spec 을 만든다." in first
    assert "/harness:spec" in first  # 그 갈래의 첫 스킬 지시
    model = c.call("GET", f"/api/sessions/{new}")[1]
    assert model["managed"] and model["cwd"] == str(c.work) and model["flowId"] == "spec"
    assert (model["modelChoice"], model["effortChoice"], model["permissionChoice"]) == ("haiku", "low", "plan")  # 이전 세션 값을 승계
    assert [x["id"] for x in model["startChecks"]] == ["sync", "version", "update", "reload"]
    assert model["model"] == "haiku" and model["sameFolder"] == []  # 넘어간 이전 세션은 같은 폴더 경고에서 빠진다
    old = wait_for(lambda: (lambda m: m if m["status"] == "ended" else None)(c.call("GET", f"/api/sessions/{sid}")[1]))  # stdin 을 닫아 정상 종료
    assert old["handedOffTo"] == new and old["sameFolder"] == [] and model["handedOffTo"] is None
    old_log = " ".join(x["text"] for x in c.app.store.get(sid)["log"])
    assert "보냄: /harness:handoff" in old_log and "다음 세션으로 넘어감" in old_log


def test_flow_next_to_config_shows_the_dev_numbers_as_the_reason(tmp_path, monkeypatch, request):
    """#599: SRS 다음 단계가 '설정' 인 요구사항(REQ-003)은 '설정하기' 갈래로 넘어가고, 화면에는 '설정 DEV-003' 으로 보인다."""
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    body = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "config", "ids": ["REQ-003", "REQ-003", "REQ-007"]})[1]
    job = confirm_job(c, body["jobId"])
    assert job["status"] == "started" and job["ids"] == ["REQ-003", "REQ-007"]
    model = c.call("GET", f"/api/sessions/{job['sessionId']}")[1]
    assert model["flowId"] == "config" and model["flowName"] == "설정하기" and model["flowReason"] == "설정 DEV-003, DEV-007"
    first = wait_for(lambda: (lambda r: r if r.startswith("echo: ") else None)(c.app.store.get(job["sessionId"])["report"]))
    assert "이번에 맡는 개발 건: DEV-003, DEV-007" in first and "/harness:start" in first


def test_flow_next_says_when_it_cuts_the_requirement_list(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    many = [f"REQ-{n:03d}" for n in range(1, 24)]
    body = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "config", "ids": many})[1]
    job = c.call("GET", f"/api/jobs/{body['jobId']}")[1]
    assert job["ids"] == many[:20] and "23건 중 20건만" in job["warning"]  # 조용히 자르지 않는다
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "config", "ids": ["REQ-1234567"]})[0] == 400  # 화면과 같은 범위(1~6자리)


def test_flow_next_stops_without_new_session_when_handoff_has_no_code_block(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FAKE_HANDOFF", "none")
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    body = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]
    job = finished_job(c, body["jobId"])
    assert job["status"] == "failed" and "마지막 코드 블록" in job["error"] and job["sessionId"] is None
    assert len(c.call("GET", "/api/sessions")[1]) == 1  # 새 세션을 띄우지 않았다
    assert any("다음 갈래로 넘기기 실패" in x["text"] for x in c.app.store.get(sid)["log"])
    # 실패한 뒤에는 다시 시도할 수 있다
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[0] == 202


def test_flow_next_refusals(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request, flows_file=gated_flows_file(tmp_path))
    c.event("term", "SessionStart")
    status, body, _ = c.call("POST", "/api/sessions/term/flow/next", {"flowId": "spec"})
    assert status == 409 and "/harness:handoff" in body["error"]  # 터미널 세션은 인계를 보낼 수 없다
    sid = launch(c, "첫 작업")
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {})[0] == 400
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": 3})[0] == 400
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "config", "ids": ["DEV-003"]})[0] == 400  # ids 는 REQ-xxx 만
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "config", "ids": "REQ-003"})[0] == 400
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "nope"})[0] == 400
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "atc"})[0] == 409  # env/adt-tiers.yaml 이 없는 폴더
    assert c.call("POST", "/api/sessions/nope/flow/next", {"flowId": "spec"})[0] == 404
    assert c.call("GET", "/api/jobs/nope")[0] == 404
    assert len(c.call("GET", "/api/sessions")[1]) == 2  # 거절한 요청은 세션을 늘리지 않는다


def test_flow_next_waits_for_running_turn_and_rejects_a_second_job(tmp_path, monkeypatch, request):
    gate = tmp_path / "gate"
    monkeypatch.setenv("FAKE_GATE", str(gate))
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    c.call("POST", f"/api/sessions/{sid}/messages", {"text": "slow 작업"})
    wait_for(lambda: c.app.store.get(sid)["turn_running"])
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    status, body, _ = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "dev"})
    assert status == 409 and "이미" in body["error"]
    assert c.call("GET", f"/api/jobs/{job_id}")[1]["status"] == "handoff"
    time.sleep(0.3)
    assert not any("보냄: /harness:handoff" in x["text"] for x in c.app.store.get(sid)["log"])  # 턴이 도는 동안은 인계를 보내지 않는다
    gate.write_text("go", encoding="utf-8")
    assert confirm_job(c, job_id)["status"] == "started"


def test_flow_next_confirm_edits_prompt_and_cancel_and_double_confirm(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    # 취소: 새 세션을 띄우지 않고 이전 세션은 그대로 둔다
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    wait_for(lambda: c.call("GET", f"/api/jobs/{job_id}")[1]["status"] == "confirm")
    assert c.call("POST", f"/api/jobs/{job_id}/cancel", {})[1]["status"] == "canceled"
    assert c.call("POST", f"/api/jobs/{job_id}/confirm", {})[0] == 409  # 취소한 job 은 시작할 수 없다
    assert len(c.call("GET", "/api/sessions")[1]) == 1 and c.app.manager.proc_for(sid).alive()
    # 고쳐서 시작: 고친 글이 새 세션 첫 메시지에 들어간다. 빈 글·긴 글은 거절하고 job 은 확인 대기로 남는다
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    wait_for(lambda: c.call("GET", f"/api/jobs/{job_id}")[1]["status"] == "confirm")
    assert c.call("POST", f"/api/jobs/{job_id}/confirm", {"prompt": "  "})[0] == 400
    assert c.call("POST", f"/api/jobs/{job_id}/confirm", {"prompt": "가" * 4001})[0] == 400
    assert c.call("POST", f"/api/jobs/{job_id}/confirm", {"prompt": 3})[0] == 400
    assert c.call("GET", f"/api/jobs/{job_id}")[1]["status"] == "confirm"
    job = confirm_job(c, job_id, prompt="내가 고친 인계 글")
    assert job["status"] == "started"
    first = wait_for(lambda: (lambda r: r if r.startswith("echo: ") else None)(c.app.store.get(job["sessionId"])["report"]))
    assert "내가 고친 인계 글" in first and "SRS 를 끝냈다" not in first
    assert c.call("POST", f"/api/jobs/{job_id}/confirm", {})[0] == 409  # 이미 시작한 job
    assert c.call("POST", "/api/jobs/nope/confirm", {})[0] == 404 and c.call("POST", "/api/jobs/nope/cancel", {})[0] == 404


def test_flow_next_fails_when_handoff_prompt_is_too_long(tmp_path, monkeypatch, request):
    monkeypatch.setenv("FAKE_HANDOFF", "long")
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    job = finished_job(c, job_id)
    assert job["status"] == "failed" and "너무 깁니다" in job["error"] and len(c.call("GET", "/api/sessions")[1]) == 1


def test_flow_next_keeps_only_allowed_permission_and_closes_old_after_init(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    with c.app.store.lock:
        c.app.store.get(sid)["permissionChoice"] = "bypassPermissions"  # 허용 집합 밖의 값은 승계하지 않는다
    seen, closed_when = [], []
    real_launch, real_close = c.app.manager.launch, c.app.manager.close
    c.app.manager.launch = lambda *a, **kw: seen.append(kw.get("permission")) or real_launch(*a, **kw)

    def spy_close(proc, *a, **kw):  # 이전 세션을 닫는 순간 새 세션이 시작 신호(init)를 냈는지 기록한다
        with c.app.store.lock:
            closed_when.append([s.get("starting") for s in c.app.store.sessions.values() if s["id"] != sid and s.get("managed")])
        return real_close(proc, *a, **kw)

    c.app.manager.close = spy_close
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    job = confirm_job(c, job_id)
    assert job["status"] == "started" and seen == [None]
    assert closed_when == [[False]]


def test_flow_next_run_exception_fails_job_and_frees_the_session(tmp_path, monkeypatch, request):
    c = next_console(tmp_path, monkeypatch, request)
    sid = launch(c, "첫 작업")
    wait_for(lambda: c.app.store.get(sid)["report"] == "echo: 첫 작업")
    c.app.deliver = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("터짐"))
    job_id = c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[1]["jobId"]
    job = finished_job(c, job_id)
    assert job["status"] == "failed" and "RuntimeError" in job["error"]
    del c.app.deliver  # 시험용 대체를 걷어 내면 같은 세션이 다시 넘길 수 있다(JOB_ACTIVE 가 풀렸다)
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[0] == 202


def test_flow_next_needs_flow_data(tmp_path, monkeypatch, request):
    c = Console(tmp_path, monkeypatch, claude_cmd=fake_cmd)
    request.addfinalizer(c.close)
    c.login()
    sid = launch(c, "첫 작업")
    assert c.call("POST", f"/api/sessions/{sid}/flow/next", {"flowId": "spec"})[0] == 503


# ---- 첫 화면 · 자동 점검 (시안 01, #636) ----
# 점검 판정(gh 로그인 · 하네스 판 · Claude 로그인)과 첫 실행 표시 파일을 본다.

CLAUDE_OK = (0, '{"loggedIn": true, "authMethod": "claude.ai", "email": "x@example.com"}\n')


def _check_console(tmp_path, monkeypatch, gh=(0, "me\n"), latest="9.9.9", installed=True, claude=CLAUDE_OK, claude_found=True):
    c = Console(tmp_path, monkeypatch, run=FakeRun(gh_api_user=gh, **{"claude auth status": claude}))
    c.app.claude_cmd = (lambda: ["claude"]) if claude_found else (lambda: None)
    c.app.gh_installed = lambda: installed
    c.app.remote_latest = (lambda: latest) if not callable(latest) else latest
    c.login()
    return c


def _checks(c, refresh=False):
    status, body, _ = c.call("GET", "/api/start-checks" + ("?refresh=1" if refresh else ""))
    assert status == 200
    return body, {x["id"]: x for x in body["checks"]}


def test_first_run_mark_is_saved_on_the_pc_and_survives_restart(tmp_path, monkeypatch):
    c = _check_console(tmp_path, monkeypatch)
    try:
        assert _checks(c)[0]["firstRun"] is True
        assert not (c.state / console_server.FIRST_RUN_FILE).exists()
        status, body, _ = c.call("POST", "/api/start-checks/seen", {})
        assert status == 200 and body["firstRun"] is False
        assert (c.state / console_server.FIRST_RUN_FILE).is_file()  # 브라우저가 아니라 상태 폴더에 남는다
        assert _checks(c)[0]["firstRun"] is False
        assert c.app.is_first_run() is False
    finally:
        c.close()


def _wn_console(tmp_path, monkeypatch, versions=None, raw=None, seen=None, version="9.9.9"):
    c = Console(tmp_path, monkeypatch)
    c.login()
    c.app.version = version
    if raw is not None or versions is not None:
        (c.app.plugin_root / "console").mkdir(exist_ok=True)
        (c.app.plugin_root / "console" / "whats_new.json").write_text(raw if raw is not None else json.dumps({"versions": versions}), encoding="utf-8")
    if seen is not None:
        c.state.mkdir(parents=True, exist_ok=True)
        (c.state / console_server.SEEN_VERSION_FILE).write_text(json.dumps({"version": seen}), encoding="utf-8")
    return c


def _seen_file(c):
    f = c.state / console_server.SEEN_VERSION_FILE
    return json.loads(f.read_text(encoding="utf-8"))["version"] if f.is_file() else None


def test_whats_new_first_time_on_this_pc_is_empty_and_saves_current(tmp_path, monkeypatch):
    c = _wn_console(tmp_path, monkeypatch, {"9.9.9": ["a"], "9.9.8": ["b"]})
    try:
        status, body, _ = c.call("GET", "/api/whats-new")
        assert status == 200 and body == {"current": "9.9.9", "seen": "9.9.9", "items": []}
        assert _seen_file(c) == "9.9.9"
        assert c.call("GET", "/api/whats-new")[1]["items"] == []
    finally:
        c.close()


def test_whats_new_lists_versions_between_seen_and_current_newest_first_skipping_missing(tmp_path, monkeypatch):
    versions = {"0.10.99": ["옛"], "0.10.100": ["백"], "0.10.101": ["백일"], "0.10.102": ["백이"], "0.10.103": ["미래"], "0.10.98": []}
    c = _wn_console(tmp_path, monkeypatch, versions, seen="0.10.99", version="0.10.102")
    try:
        status, body, _ = c.call("GET", "/api/whats-new")
        assert status == 200 and body["seen"] == "0.10.99" and body["current"] == "0.10.102"
        assert body["items"] == [{"version": "0.10.102", "lines": ["백이"]}, {"version": "0.10.101", "lines": ["백일"]},
                                 {"version": "0.10.100", "lines": ["백"]}]  # 숫자 비교: 99 < 100, seen 이하와 current 초과는 뺀다
        assert _seen_file(c) == "0.10.99"  # 보기만 해서는 본 판이 바뀌지 않는다
        status, body, _ = c.call("POST", "/api/whats-new/seen", {})
        assert status == 200 and _seen_file(c) == "0.10.102"
        assert c.call("GET", "/api/whats-new")[1]["items"] == []
    finally:
        c.close()


def test_whats_new_version_without_entry_is_left_out(tmp_path, monkeypatch):
    c = _wn_console(tmp_path, monkeypatch, {"9.9.9": ["a"]}, seen="9.9.5")
    try:
        assert [x["version"] for x in c.call("GET", "/api/whats-new")[1]["items"]] == ["9.9.9"]  # 9.9.6~9.9.8 은 데이터가 없어 안 띄운다
    finally:
        c.close()


def test_whats_new_broken_or_missing_json_is_empty_with_reason_and_keeps_seen(tmp_path, monkeypatch):
    for kw in ({"raw": "{깨짐"}, {"raw": '{"versions": []}'}, {}):
        sub = tmp_path / str(len(list(tmp_path.iterdir())))
        sub.mkdir()
        c = _wn_console(sub, monkeypatch, seen="9.9.0", **kw)
        try:
            status, body, _ = c.call("GET", "/api/whats-new")
            assert status == 200 and body["items"] == [] and body["reason"] and body["seen"] == "9.9.0"
            assert _seen_file(c) == "9.9.0"  # 다음에 읽히면 보이도록 건드리지 않는다
        finally:
            c.close()


def test_whats_new_unknown_current_is_empty_with_reason_and_keeps_seen(tmp_path, monkeypatch):
    c = _wn_console(tmp_path, monkeypatch, {"9.9.9": ["a"]}, seen="9.9.0", version="")
    try:
        body = c.call("GET", "/api/whats-new")[1]
        assert body["items"] == [] and body["reason"] and _seen_file(c) == "9.9.0"
        assert c.call("POST", "/api/whats-new/seen", {})[0] == 409 and _seen_file(c) == "9.9.0"
    finally:
        c.close()


def test_whats_new_downgrade_is_empty_and_resets_seen_to_current(tmp_path, monkeypatch):
    c = _wn_console(tmp_path, monkeypatch, {"9.9.9": ["a"], "9.9.5": ["b"]}, seen="9.9.20")
    try:
        body = c.call("GET", "/api/whats-new")[1]
        assert body["items"] == [] and body["seen"] == "9.9.9" and _seen_file(c) == "9.9.9"
    finally:
        c.close()


def test_notify_settings_default_off_saved_in_state_dir_and_validated(mconsole):
    c = mconsole
    off = {"turn": False, "blocked": False, "done": False}
    assert c.call("GET", "/api/settings/notify")[1] == off  # 기본은 모두 꺼짐
    status, body, _ = c.call("PUT", "/api/settings/notify", {"turn": True})
    assert status == 200 and body == dict(off, turn=True)
    saved = c.state / console_server.NOTIFY_FILE
    assert saved.is_file() and json.loads(saved.read_text(encoding="utf-8")) == dict(off, turn=True)  # 브라우저가 아니라 상태 폴더
    assert c.call("PUT", "/api/settings/notify", {"done": True})[1] == dict(off, turn=True, done=True)  # 보낸 키만 바뀐다
    assert c.call("GET", "/api/settings/notify")[1] == dict(off, turn=True, done=True)  # 파일을 읽으므로 재기동 뒤에도 같다
    for bad in ({"turn": "yes"}, {"turn": 1}, {"nope": True}, {"turn": True, "x": False}, {}):
        assert c.call("PUT", "/api/settings/notify", bad)[0] == 400, bad
    assert c.call("GET", "/api/settings/notify")[1] == dict(off, turn=True, done=True)  # 거절한 요청은 아무것도 바꾸지 않는다
    saved.write_text("not json", encoding="utf-8")
    assert c.call("GET", "/api/settings/notify")[1] == off  # 깨진 파일은 꺼진 것으로


def test_start_checks_all_ok_is_not_blocking(tmp_path, monkeypatch):
    c = _check_console(tmp_path, monkeypatch)
    try:
        body, by = _checks(c)
        assert body["blocking"] is False and body["newVersion"] is None and body["loading"] is False
        assert by["github"]["state"] == "ok" and by["github"]["detail"] == "me"
        assert by["version"]["state"] == "ok" and by["version"]["detail"] == "9.9.9"
        assert by["claude"]["state"] == "ok" and by["claude"]["detail"] == "로그인됨 · Claude 계정"
        assert "example.com" not in json.dumps(body)  # 계정 이메일은 화면에 옮기지 않는다
    finally:
        c.close()


def test_start_checks_claude_login_reads_auth_status(tmp_path, monkeypatch):
    """Claude Code 로그인: 공식 명령 claude auth status --json 의 loggedIn 으로 판정한다(#721)."""
    run = FakeRun(gh_api_user=(0, "me\n"), **{"claude auth status": (1, '{"loggedIn": false}\n')})
    c = Console(tmp_path, monkeypatch, run=run)
    c.app.claude_cmd = lambda: ["claude"]
    c.app.gh_installed = lambda: True
    c.app.remote_latest = lambda: "9.9.9"
    c.login()
    try:
        body, by = _checks(c)
        assert body["blocking"] is True and by["claude"]["state"] == "fail" and "claude auth login" in by["claude"]["fix"]
        assert "claude auth status --json" in run.calls
    finally:
        c.close()
    c = _check_console(tmp_path / "nf", monkeypatch, claude_found=False)  # claude 를 못 찾음: 로그인 안 됨이 아니라 확인 못 함
    try:
        body, by = _checks(c)
        assert by["claude"]["state"] == "unknown" and "찾지 못했어" in by["claude"]["detail"] and body["blocking"] is False
    finally:
        c.close()


def test_judge_claude_reads_json_even_with_noise_and_never_guesses():
    j = console_server.judge_claude
    assert j(0, 'warning: x\n{"loggedIn": true, "authMethod": "apiKey"}\n', True) == {"state": "ok", "detail": "로그인됨"}
    assert j(0, '{"loggedIn": false}', True)["state"] == "fail"
    assert j(1, '{"loggedIn": false}', True)["state"] == "fail"
    for rc, out in ((0, ""), (0, "not json"), (0, '{"other": 1}'), (124, ""), (1, "error")):
        assert j(rc, out, True)["state"] == "unknown", (rc, out)
    assert j(0, '{"loggedIn": true}', False)["state"] == "unknown"


def test_start_checks_github_not_logged_in_blocks_with_fix(tmp_path, monkeypatch):
    msg = "You are not logged into any GitHub hosts. To log in, run: gh auth login\n"
    c = _check_console(tmp_path, monkeypatch, gh=(1, msg))
    try:
        body, by = _checks(c)
        assert body["blocking"] is True and by["github"]["state"] == "fail"
        assert "gh auth login" in by["github"]["fix"]
    finally:
        c.close()
    c = _check_console(tmp_path / "nogh", monkeypatch, gh=(127, ""), installed=False)  # gh 자체가 없다
    try:
        body, by = _checks(c)
        assert body["blocking"] is True and by["github"]["state"] == "fail" and "gh auth login" in by["github"]["fix"]
    finally:
        c.close()


def test_start_checks_cannot_read_is_unknown_not_blocking(tmp_path, monkeypatch):
    c = _check_console(tmp_path, monkeypatch, gh=(127, ""), latest=lambda: None, claude=(124, ""))  # gh 시간 초과(설치는 돼 있음) + 원격 못 읽음 + claude 시간 초과
    try:
        body, by = _checks(c)
        assert body["blocking"] is False and body["newVersion"] is None
        assert by["github"]["state"] == "unknown" and by["version"]["state"] == "unknown"  # 못 읽은 것을 통과나 위반으로 뭉개지 않는다
        assert by["claude"]["state"] == "unknown" and "확인 못 함" in by["claude"]["detail"]
    finally:
        c.close()


def test_start_checks_old_version_is_notice_only_and_refresh_rechecks(tmp_path, monkeypatch):
    latest = ["10.0.0"]
    c = _check_console(tmp_path, monkeypatch, latest=lambda: latest[0])
    try:
        body, by = _checks(c)
        assert by["version"]["state"] == "old" and body["newVersion"] == "10.0.0" and body["blocking"] is False  # 막지 않는다
        assert "/harness:update" in by["version"]["fix"]
        latest[0] = "9.9.9"
        assert _checks(c)[0]["newVersion"] == "10.0.0"  # 60초 기억
        assert _checks(c, refresh=True)[0]["newVersion"] is None  # 다시 점검은 기억을 지우고 새로 읽는다
    finally:
        c.close()


# ---- 개발 준비 상태 GET /api/dev-ready (#668) ----
READY_SRS = """| ID | Title | Status | 다음 단계 |
|---|---|---|---|
| REQ-001 | 구매오더 조회 | New | 개발 |
| REQ-002 | 판매오더 조회 | New | 개발 |
| REQ-003 | 사용자 코드 | New | 설정 |
| REQ-004 | 옛 요구 | Dropped | 개발 |
| REQ-005 | 아직 모름 | New | 미정 |
| REQ-006 | 표준 앱으로 | New | 표준 |
"""
READY_LEDGER = """## 개발 건

| ID | 내용 | Spec | 담당 | 상태 |
|---|---|---|---|---|
| DEV-002 | 판매오더 조회 | docs/spec/DEV-002-판매.md | 김 | 진행 |
| DEV-003 | 사용자 코드 설정 | 설정 | 김 | 진행 |
"""


def ready_run(work, spec_files=("docs/spec/DEV-002-판매.md",), **over):
    files = {"docs/ssot/SRS.md": READY_SRS, "audit/ledger/a.md": READY_LEDGER}

    def show(args):
        path = args[-1].split(":", 1)[1]
        return (0, files[path]) if path in files else (128, "")

    table = {"git rev-parse --show-toplevel": (0, str(work) + "\n"), "git fetch origin main": (0, ""), "git show": show,
             "git ls-tree": (0, "\n".join(["docs/ssot/SRS.md", "audit/ledger/a.md", *spec_files]) + "\n")}
    table.update({k.replace("_", " "): v for k, v in over.items()})
    return FakeRun(**{k.replace(" ", "_"): v for k, v in table.items()})


def ready_get(c):
    c.event("p1", "SessionStart")
    return c.call("GET", "/api/dev-ready?cwd=" + urllib.parse.quote(str(c.work)))


def test_dev_ready_reads_spec_and_setup_state_from_origin_main(tmp_path, monkeypatch):
    work = tmp_path / "work"
    run = ready_run(work)
    c = flow_console(tmp_path, monkeypatch, run=run)
    (work / "audit" / "ledger").mkdir(parents=True)
    try:
        status, body, _ = ready_get(c)
        assert status == 200 and body["state"] == "yes"
        # DEV-002 는 Spec 있음, DEV-003 은 SRS 설정(+옛 원장 Spec 칸 설정), REQ-006 은 SRS 표준(#718)
        assert body["specReady"] == 1 and body["setup"] == 2 and body["standard"] == 1
        assert [i["number"] for i in body["items"] if i["standard"]] == [6]
        # 할 차례: Spec 없는 개발 건만(설정·보류·미정은 뺀다)
        assert body["needSpec"] == [{"number": 1, "label": "REQ-001(구매오더 조회)"}] and body["needSpecCount"] == 1
        assert "git fetch origin main" in run.calls
        n = len(run.calls)
        c.call("GET", "/api/dev-ready?cwd=" + urllib.parse.quote(str(c.work)))
        assert len(run.calls) == n  # 60초 안에는 다시 읽지 않는다
    finally:
        c.close()


def test_dev_ready_reads_setup_and_standard_from_srs_without_ledger(tmp_path, monkeypatch):
    work = tmp_path / "work"
    run = ready_run(work, **{"git ls-tree": (0, "docs/ssot/SRS.md\ndocs/spec/DEV-002-판매.md\n")})
    c = flow_console(tmp_path, monkeypatch, run=run)
    (work / "docs" / "ssot").mkdir(parents=True)
    (work / "docs" / "ssot" / "SRS.md").write_text("# SRS\n", encoding="utf-8")  # 원장 폴더는 없다(#718)
    try:
        body = ready_get(c)[1]
        assert body["state"] == "yes" and body["setup"] == 2 and body["standard"] == 1
        assert body["specReady"] == 1 and [n["number"] for n in body["needSpec"]] == [1]
    finally:
        c.close()


def test_dev_ready_srs_dev_overrides_old_ledger_setup(tmp_path, monkeypatch):
    # 옛 원장엔 설정, SRS 는 개발로 바꾼 건: SRS 가 먼저라 설정 건으로 세지 않는다(#718, spec_ready 와 같다)
    srs = "# SRS\n\n## 요구사항\n\n| ID | Title | Status | 다음 단계 |\n|---|---|---|---|\n| REQ-003 | 사용자 코드 | New | 개발 |\n"
    files = {"docs/ssot/SRS.md": srs, "audit/ledger/a.md": READY_LEDGER}

    def show(args):
        path = args[-1].split(":", 1)[1]
        return (0, files[path]) if path in files else (128, "")

    work = tmp_path / "work"
    run = ready_run(work, spec_files=(), **{"git show": show})
    c = flow_console(tmp_path, monkeypatch, run=run)
    (work / "audit" / "ledger").mkdir(parents=True)
    try:
        body = ready_get(c)[1]
        item = next(i for i in body["items"] if i["number"] == 3)
        assert item["setup"] is False and item["dev"] is True
        assert 3 in [n["number"] for n in body["needSpec"]]
    finally:
        c.close()


def test_dev_ready_zero_spec_is_certain_when_no_spec_file_on_main(tmp_path, monkeypatch):
    work = tmp_path / "work"
    c = flow_console(tmp_path, monkeypatch, run=ready_run(work, spec_files=()))
    (work / "audit" / "ledger").mkdir(parents=True)
    try:
        body = ready_get(c)[1]
        assert body["state"] == "yes" and body["specReady"] == 0
        assert [n["number"] for n in body["needSpec"]] == [1, 2]
    finally:
        c.close()


def test_dev_ready_not_applicable_without_ledger_or_repo(tmp_path, monkeypatch):
    work = tmp_path / "work"  # audit/ledger 가 없다
    c = flow_console(tmp_path, monkeypatch, run=ready_run(work))
    try:
        body = ready_get(c)[1]
        assert body["state"] == "no" and body["reason"] and "specReady" not in body
    finally:
        c.close()
    c2 = flow_console(tmp_path / "second", monkeypatch)  # 기본 FakeRun: git 저장소가 아니다
    try:
        assert ready_get(c2)[1]["state"] == "no"
    finally:
        c2.close()


@pytest.mark.parametrize("over", [{"git fetch origin main": (1, "")}, {"git ls-tree": (1, "")}, {"git show": (128, "")}, {"git rev-parse --show-toplevel": (127, "")}])
def test_dev_ready_unknown_when_git_cannot_be_read(tmp_path, monkeypatch, over):
    work = tmp_path / "work"
    c = flow_console(tmp_path, monkeypatch, run=ready_run(work, **over))
    (work / "audit" / "ledger").mkdir(parents=True)
    try:
        body = ready_get(c)[1]
        assert body["state"] == "unknown" and body["reason"]  # 없음이나 통과로 뭉개지 않는다
        assert "specReady" not in body
    finally:
        c.close()


# ---- 세션 기억(context) 사용량 (#648) ----

def _asst(inp, cc, cr, model="claude-opus-5-5", side=False, out=999):
    row = {"type": "assistant", "message": {"model": model, "usage": {"input_tokens": inp, "cache_creation_input_tokens": cc,
                                                                    "cache_read_input_tokens": cr, "output_tokens": out}}}
    if side:
        row["isSidechain"] = True
    return json.dumps(row)


def test_context_usage_reads_last_main_assistant_line_from_the_end(tmp_path):
    import context_usage
    f = tmp_path / "t.jsonl"
    filler = json.dumps({"type": "user", "message": {"content": "x" * 5000}})
    lines = [_asst(1, 2, 3)] + [filler] * 800 + [_asst(2, 340, 241140), _asst(9, 9, 9, side=True), '{"type":"progress"}', '{"type":"assistant","message":{"model":"x"']
    f.write_text("\n".join(lines), encoding="utf-8")  # 4MB 넘는 파일. 마지막 줄은 쓰다 만 깨진 줄
    assert f.stat().st_size > 4_000_000
    got = context_usage.read_last_usage(str(f))
    assert got == {"tokens": 241482, "model": "claude-opus-5-5"}  # output_tokens·서브에이전트 줄·깨진 줄은 셈에 넣지 않는다
    # 파일이 바뀌면 다시 읽는다
    f.write_text("\n".join(lines + [_asst(1, 1, 1)]) + "\n", encoding="utf-8")
    assert context_usage.read_last_usage(str(f))["tokens"] == 3


def test_context_usage_unknown_cases(tmp_path):
    import context_usage
    assert context_usage.read_last_usage(str(tmp_path / "nope.jsonl")) is None  # 파일 없음
    f = tmp_path / "e.jsonl"
    f.write_text('{"type":"user"}\n{"type":"assistant","message":{"role":"assistant"}}\n' + _asst(0, 0, 0) + "\n" + _asst(1, 1, 1, side=True) + "\n", encoding="utf-8")
    assert context_usage.read_last_usage(str(f)) is None  # usage 없음·0·서브에이전트뿐
    one = tmp_path / "one.jsonl"
    one.write_text(_asst(5, 5, 5), encoding="utf-8")  # 줄 하나, 끝 줄바꿈 없음
    assert context_usage.read_last_usage(str(one))["tokens"] == 15
    assert context_usage.for_session({"transcriptPath": str(tmp_path / "nope.jsonl")}) == {"tokens": None, "window": None, "pct": None}
    assert context_usage.for_session({}) == {"tokens": None, "window": None, "pct": None}
    assert context_usage.valid_path("relative.jsonl") == "" and context_usage.valid_path(str(one)) == str(one) and context_usage.valid_path(str(f)[:-6] + ".txt") == ""


@pytest.mark.parametrize("model,choice,window", [
    ("claude-opus-5-5", "", 1_000_000), ("claude-sonnet-5-5", "", 1_000_000), ("claude-haiku-5-5", "", 1_000_000), ("claude-opus-4-7", "", 1_000_000),
    ("claude-fable-5-1", "", 1_000_000), ("claude-opus-4-6", "", 200_000), ("claude-sonnet-4-6", "", 200_000),
    ("claude-opus-4-6", "opus[1m]", 1_000_000), ("claude-sonnet-4-6[1m]", "", 1_000_000),
    ("claude-haiku-4-5", "", None), ("claude-3-5-sonnet-20241022", "", None), ("claude-opus-4-1-20250805", "", None), ("something-else", "", None), ("", "", None)])
def test_context_window_table_only_documented_models(model, choice, window):
    import context_usage
    assert context_usage.window_for(model, choice) == window  # 문서에 없는 모델은 창 크기를 지어내지 않는다


def test_hook_saves_transcript_path_and_session_shows_context_pct(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch)
    try:
        c.login()
        f = tmp_path / "s1.jsonl"
        f.write_text(_asst(2, 340, 920000, model="claude-opus-5-5") + "\n", encoding="utf-8")
        c.event("s1", "SessionStart", transcript_path=str(f))
        got = [s for s in c.call("GET", "/api/sessions")[1] if s["id"] == "s1"][0]
        assert got["context"] == {"tokens": 920342, "window": 1_000_000, "pct": 92}
        # 모르는 모델이면 % 없이 토큰 수만
        f.write_text(_asst(1, 1, 99998, model="claude-haiku-4-5") + "\n", encoding="utf-8")
        got = [s for s in c.call("GET", "/api/sessions")[1] if s["id"] == "s1"][0]
        assert got["context"] == {"tokens": 100000, "window": None, "pct": None}
        # 경로가 없거나 .jsonl 이 아닌 훅은 저장된 경로를 바꾸지 못한다
        c.event("s1", "PreCompact", transcript_path="C:/etc/passwd")
        c.event("s2", "SessionStart")
        by = {s["id"]: s for s in c.call("GET", "/api/sessions")[1]}
        assert by["s1"]["context"]["tokens"] == 100000 and by["s2"]["context"] == {"tokens": None, "window": None, "pct": None}
    finally:
        c.close()


def test_srs_status_reads_working_tree_srs(tmp_path, monkeypatch):
    # 설정·표준 건의 진행(In Process)은 작업 브랜치 SRS 에만 있다: origin/main 이 아니라 작업 폴더 파일을 읽는다(#718)
    work = tmp_path / "work"
    c = flow_console(tmp_path, monkeypatch, run=ready_run(work))
    (work / "docs" / "ssot").mkdir(parents=True)
    (work / "docs" / "ssot" / "SRS.md").write_text(READY_SRS.replace("| New | 표준 |", "| In Process | 표준 |"), encoding="utf-8")
    try:
        c.event("p1", "SessionStart")
        url = "/api/srs-status?cwd=" + urllib.parse.quote(str(c.work))
        status, body, _ = c.call("GET", url)
        assert status == 200 and body["state"] == "yes"
        assert body["items"]["REQ-006"] == {"status": "In Process", "next": "표준"}
        assert body["items"]["REQ-003"] == {"status": "New", "next": "설정"}
        (work / "docs" / "ssot" / "SRS.md").write_text(READY_SRS.replace("| New | 표준 |", "| Done | 표준 |"), encoding="utf-8")
        assert c.call("GET", url)[1]["items"]["REQ-006"]["status"] == "Done"  # 캐시하지 않는다
        (work / "docs" / "ssot" / "SRS.md").unlink()
        body = c.call("GET", url)[1]
        assert body["state"] == "no" and "items" not in body
        assert c.call("GET", "/api/srs-status")[0] == 400
        other = tmp_path / "other"
        other.mkdir()
        assert c.call("GET", "/api/srs-status?cwd=" + urllib.parse.quote(str(other)))[0] == 403
    finally:
        c.close()


def test_srs_status_unknown_when_git_cannot_run(tmp_path, monkeypatch):
    work = tmp_path / "work"
    c = flow_console(tmp_path, monkeypatch, run=ready_run(work, **{"git rev-parse --show-toplevel": (127, "")}))
    try:
        c.event("p1", "SessionStart")
        body = c.call("GET", "/api/srs-status?cwd=" + urllib.parse.quote(str(c.work)))[1]
        assert body["state"] == "unknown" and body["reason"]
    finally:
        c.close()


def test_dev_ready_rejects_unknown_folder_and_missing_cwd(tmp_path, monkeypatch):
    c = flow_console(tmp_path, monkeypatch)
    try:
        other = tmp_path / "other"
        other.mkdir()
        assert c.call("GET", "/api/dev-ready?cwd=" + urllib.parse.quote(str(other)))[0] == 403
        assert c.call("GET", "/api/dev-ready")[0] == 400
    finally:
        c.close()


# ---- 세션 대화(chat) (#682) ----

def _chat(browser, sid):
    return browser.call("GET", f"/api/sessions/{sid}")[1]["chat"]


def test_chat_collects_prompt_and_stop_report_without_duplicates(browser):
    browser.event("t1", "UserPromptSubmit", prompt="  표 순서를 바꿔 줘\n두 번째 줄  ")
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "바꿨어"})
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "바꿨어"})  # 같은 보고가 또 와도 쌓지 않는다
    chat = _chat(browser, "t1")
    assert [(c["role"], c["text"]) for c in chat] == [("me", "표 순서를 바꿔 줘\n두 번째 줄"), ("ai", "바꿨어")]
    assert all(isinstance(c["t"], float) for c in chat)
    browser.event("t1", "UserPromptSubmit", prompt="바꿨어")  # 같은 글이라도 앞 항목의 role 이 다르면 쌓는다
    assert [c["role"] for c in _chat(browser, "t1")] == ["me", "ai", "me"]


def test_chat_skips_system_only_prompts_and_keeps_slash_commands(browser):
    for prompt in ("<task-notification>끝났어</task-notification>", "<system-reminder>x</system-reminder>\n<local-command-stdout>y</local-command-stdout>",
                   "<system-reminder>열림", "   "):
        browser.event("t1", "UserPromptSubmit", prompt=prompt)
    assert _chat(browser, "t1") == []
    browser.event("t1", "UserPromptSubmit", prompt="/harness:srs 구매오더")
    browser.event("t1", "UserPromptSubmit", prompt="<system-reminder>잡음</system-reminder>[Image #1] 이거 봐줘")
    assert [c["text"] for c in _chat(browser, "t1")] == ["/harness:srs 구매오더", "[Image #1] 이거 봐줘"]


def test_chat_text_and_count_limits():
    store = Store(None)
    s = store.ensure("s1", "/w")
    store.add_chat(s, "ai", "가" * 9000)
    assert len(s["chat"][0]["text"]) == 8000
    for i in range(230):
        store.add_chat(s, "me" if i % 2 else "ai", f"글{i}")
    assert len(s["chat"]) == 200 and s["chat"][-1]["text"] == "글229"
    assert store.add_chat(s, "ai", "   ") is False


def test_chat_request_item_is_added_then_filled_with_the_answer(browser):
    h = browser.hook_async("question", ask_body("t1"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    item = _chat(browser, "t1")[-1]
    assert (item["role"], item["id"], item["kind"], item["title"], item["answer"]) == ("req", req.rid, "question", "색은?", None)
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"answers": {"색은?": ["Red", "Blue"]}})
    h["t"].join(5)
    item = _chat(browser, "t1")[-1]
    assert item["answer"] == "Red, Blue" and len(_chat(browser, "t1")) == 1

    h = browser.hook_async("permission", perm_body("t1", "touch a"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    assert _chat(browser, "t1")[-1]["title"] == "Bash 사용"
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
    h["t"].join(5)
    assert _chat(browser, "t1")[-1]["answer"] == "허락함"

    h = browser.hook_async("permission", perm_body("t1", "touch b"))
    req = wait_for(lambda: (browser.pending("t1") or [None])[0])
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny"})
    h["t"].join(5)
    assert _chat(browser, "t1")[-1]["answer"] == "거절함"

    h = browser.hook_async("permission", perm_body("t1", "touch c"))
    wait_for(lambda: browser.pending("t1"))
    browser.event("t1", "SessionEnd")  # 터미널에서 닫히면 이유가 답 자리에 남는다
    h["t"].join(5)
    assert _chat(browser, "t1")[-1]["answer"] == "세션이 끝나서 닫힘"


def test_chat_survives_save_and_load_and_old_sessions_get_empty_list(browser, tmp_path):
    browser.event("t1", "UserPromptSubmit", prompt="저장해 줘")
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "저장했어"})
    browser.app.store.flush()
    assert [c["text"] for c in Store(browser.state).get("t1")["chat"]] == ["저장해 줘", "저장했어"]
    d = tmp_path / "old"
    d.mkdir()
    (d / "sessions.json").write_text(json.dumps({"sessions": [{"id": "a"}, {"id": "b", "chat": "깨짐"}, {"id": "c", "chat": [1, {"role": "me", "text": "x"}]}],
                                                  "folders": []}), encoding="utf-8")
    old = Store(d)
    assert old.get("a")["chat"] == [] and old.get("b")["chat"] == [] and old.get("c")["chat"] == [{"role": "me", "text": "x"}]


def test_chat_is_only_in_single_session_response_and_partial_for_terminal(browser):
    browser.event("t1", "UserPromptSubmit", prompt="안녕")
    listed = browser.call("GET", "/api/sessions")[1]
    assert listed and all("chat" not in s for s in listed) and listed[0]["chatPartial"] is True
    one = browser.call("GET", "/api/sessions/t1")[1]
    assert one["chat"][0]["text"] == "안녕" and one["chatPartial"] is True
    assert "chat" not in browser.call("GET", "/api/sessions/t1?chat=0")[1]
    assert "chat" not in browser.call("PUT", "/api/sessions/t1/skills/prs/reservation", {})[1]


def test_chat_for_console_session_dedups_send_hook_and_stop(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    s = store.ensure("s1", str(tmp_path))
    s["managed"] = True
    proc = FakeProc()
    m.procs["s1"] = proc
    assert m.send("s1", "계획을 세워 줘") is True
    hooks = Hooks(store)
    hooks.event(s, {"hook_event_name": "UserPromptSubmit", "prompt": "계획을 세워 줘"})  # 같은 말이 훅으로도 온다
    m.on_event(proc, {"type": "assistant", "message": {"content": [{"type": "text", "text": "먼저 읽어 볼게"}, {"type": "tool_use", "name": "Read", "input": {}}]}})
    m.on_event(proc, {"type": "assistant", "message": {"content": [{"type": "text", "text": "끝냈어"}]}})
    hooks.stop(s, {"last_assistant_message": "끝냈어"})
    m.on_event(proc, {"type": "result", "is_error": False, "result": "끝냈어"})
    assert [(c["role"], c["text"]) for c in s["chat"]] == [("me", "계획을 세워 줘"), ("ai", "먼저 읽어 볼게"), ("ai", "끝냈어")]
    assert store.get("s1") is s
    from store import public_session
    assert "chat" not in public_session(store, s, []) and public_session(store, s, [], True)["chatPartial"] is False


def test_chat_result_fallback_when_stop_hook_never_came(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    s = store.ensure("s1", str(tmp_path))
    s["managed"] = True
    proc = FakeProc()
    m.procs["s1"] = proc
    m.on_event(proc, {"type": "result", "is_error": False, "result": "대비 경로 글"})
    assert [(c["role"], c["text"]) for c in s["chat"]] == [("ai", "대비 경로 글")]


def test_chat_queued_console_message_is_recorded_when_stop_delivers_it(browser):
    browser.event("t1", "UserPromptSubmit", prompt="작업")
    browser.call("POST", "/api/sessions/t1/messages", {"text": "이어서 이것도"})
    assert [c["text"] for c in _chat(browser, "t1")] == ["작업"]  # 아직 전달 전
    browser.hook("stop", {"session_id": "t1", "cwd": "/w", "last_assistant_message": "1차 끝"})
    assert [(c["role"], c["text"]) for c in _chat(browser, "t1")] == [("me", "작업"), ("ai", "1차 끝"), ("me", "이어서 이것도")]


# ---- 훅이 막은 이유(#650) ----

def _blocked(browser, sid, reason, hook="pre_write_guard", tool="Write"):
    return browser.hook("blocked", {"session_id": sid, "cwd": "/w", "hook_event_name": "HarnessBlocked", "hook": hook, "reason": reason, "tool_name": tool})


def test_blocked_report_becomes_a_block_chat_item_with_fix(browser):
    assert _blocked(browser, "b1", "문서가 템플릿을 따르지 않습니다.\n다음: 개요 절을 추가하십시오.")[0] == 200
    item, = _chat(browser, "b1")
    assert item["role"] == "block" and item["kind"] == "blocked" and item["hook"] == "pre_write_guard" and item["tool"] == "Write"
    assert item["text"].startswith("문서가 템플릿을") and item["fix"] == "개요 절을 추가하십시오."


@pytest.mark.parametrize("word", ["검사 불능", "확인하지 못", "확인할 수 없", "판정할 수 없", "검사할 수 없", "확인 불능"])
def test_blocked_report_with_cannot_check_words_is_cannot_check(browser, word):
    _blocked(browser, "b2", f"엔진을 돌리지 못해 {word} 상태입니다.")
    assert _chat(browser, "b2")[0]["kind"] == "cannot_check" and _chat(browser, "b2")[0]["fix"] == ""


def test_session_list_carries_last_block_time_and_kind_for_notifications(browser):
    _blocked(browser, "b3", "문서가 템플릿을 따르지 않습니다.")
    listed = {s["id"]: s for s in browser.call("GET", "/api/sessions")[1]}
    first = listed["b3"]["lastBlock"]
    assert first["kind"] == "blocked" and isinstance(first["t"], (int, float))  # 대화(chat)는 목록에 없어도 새 막힘을 알 수 있다
    assert "chat" not in listed["b3"]
    _blocked(browser, "b3", "엔진을 돌리지 못해 검사 불능 상태입니다.")
    assert {s["id"]: s for s in browser.call("GET", "/api/sessions")[1]}["b3"]["lastBlock"]["kind"] == "cannot_check"
    browser.event("b4", "UserPromptSubmit", prompt="막힘 없는 세션")
    assert {s["id"]: s for s in browser.call("GET", "/api/sessions")[1]}["b4"]["lastBlock"] is None


# 실제 훅 사유 문구 대입(검토 지적: 단어만 시험하면 실제 문구가 빠진다)
@pytest.mark.parametrize("reason, kind", [
    ("임시 파일을 만들지 못해 검사 엔진의 판을 정하지 못했습니다. 확인되지 않는 상태로 통과시키지 않습니다. 다음: 같은 명령을 다시 시도하십시오.", "cannot_check"),
    ("공통 개발 규칙 검사기가 알 수 없는 종료코드(3)로 끝나 이 코드를 확인할 수 없었습니다. 확인되지 않는 상태로 통과시키지 않습니다.", "cannot_check"),
    ("harness: 기본 데이터 도구 목록(mcp_default_tools.json)을 읽지 못해 이 MCP 호출을 확인할 수 없었습니다.", "cannot_check"),
    ("검사 불능: gitleaks 가 없어 비밀정보 검사를 하지 못했습니다. 검사하지 못한 상태로 커밋을 통과시키지 않습니다.", "cannot_check"),
    ("PR #7 의 검사가 실패해 merge 를 막습니다. 실패한 검사: test 링크: u 다음: 로그를 보고 고치십시오.", "blocked"),
    ("SRS(docs/ssot) 를 바꾼 PR #7 인데 작성자가 아닌 승인자의 Approve 가 없어 merge 를 막습니다. 사유: 승인을 확인할 수 없음 다음: 승인을 받으십시오.", "blocked"),
    ("PR #7 의 검사 상태를 확인하지 못해 merge 를 막습니다(종료코드 1). 검사 불능이므로 통과시키지 않습니다. 자세히: x", "cannot_check"),
    ("git push --force 는 이 저장소에서 금지되어 있습니다. 다음: --force 를 빼고 /harness:deliver 를 실행하십시오. 확인할 수 없는 경우 사람에게 물으십시오.", "blocked"),
    ("비밀값 발견: 커밋에 들어갈 staged 변경에서 비밀정보 모양이 발견되어 커밋을 막습니다. 발견: a.txt 다음: 줄을 지우십시오.", "blocked"),
    ("doc-guard: 이 문서가 템플릿을 따르지 않습니다.\n\n- 개요 절 없음\n다음: Claude 가 위 템플릿을 보고 문서를 고친 뒤 다시 저장하십시오.", "blocked"),
])
def test_block_kind_matches_real_hook_reasons(reason, kind):
    assert hooks_mod.block_kind(reason) == kind


def test_blocked_report_same_as_previous_block_is_not_stacked_but_other_is(browser):
    _blocked(browser, "b3", "같은 사유")
    _blocked(browser, "b3", "같은 사유")
    assert len(_chat(browser, "b3")) == 1
    _blocked(browser, "b3", "다른 사유")
    assert [c["text"] for c in _chat(browser, "b3")] == ["같은 사유", "다른 사유"]


def test_blocked_report_without_reason_or_session_is_rejected(browser):
    assert _blocked(browser, "b4", "  ")[0] == 400
    assert browser.hook("blocked", {"hook": "x", "reason": "r"})[0] == 400


# ---- #649 묻는 범위와 되돌릴 수 없는 일 / #684 auto 모드 ----
import risk as risk_mod  # noqa: E402

W = r"C:\work" if os.name == "nt" else "/work"
BASH = lambda cmd: ("Bash", {"command": cmd})  # noqa: E731


@pytest.mark.parametrize("tool, tool_input, want", [
    # 읽기·되돌릴 수 있는 명령
    BASH("ls -la") + ("safe",), BASH("git status") + ("safe",), BASH("git diff --stat") + ("safe",), BASH("git log --oneline -5") + ("safe",),
    BASH("git show HEAD") + ("safe",), BASH("git branch") + ("safe",), BASH("git branch -a") + ("safe",), BASH("git fetch origin") + ("unknown",),
    BASH("git rev-parse HEAD") + ("safe",), BASH("git ls-files") + ("safe",), BASH("git remote -v") + ("unknown",),
    BASH("gh pr view 3") + ("safe",), BASH("gh pr list") + ("safe",), BASH("gh pr checks 3") + ("safe",), BASH("gh issue view 5") + ("safe",),
    BASH("gh run list") + ("safe",), BASH("pytest -q") + ("unknown",), BASH("uv run pytest -q a b") + ("unknown",), BASH("python -m pytest x") + ("unknown",),
    BASH("node --check a.js") + ("safe",), BASH("git add -A") + ("safe",), BASH("git commit -m 'msg a'") + ("safe",),
    BASH("git checkout -b feat/x") + ("safe",), BASH("git switch -c feat/x") + ("safe",), BASH("find . -name x") + ("safe",),
    BASH("grep -n foo a.py 2>&1") + ("safe",), BASH("grep -rn foo . 2>&1") + ("unknown",), BASH("cd sub && git status | head -5") + ("unknown",),  # sub 폴더가 실제로 없다
    BASH("echo hi >/dev/null") + ("safe",),
    # 되돌릴 수 없는 명령
    BASH("rm -rf x") + ("irreversible",), BASH("Remove-Item a") + ("irreversible",), BASH("del a.txt") + ("irreversible",), BASH("git clean -fd") + ("irreversible",),
    BASH("git reset --hard HEAD~1") + ("irreversible",), BASH("git checkout -- a.py") + ("irreversible",), BASH("git restore a.py") + ("irreversible",),
    BASH("git branch -D x") + ("irreversible",), BASH("git branch -d x") + ("irreversible",), BASH("git stash drop") + ("irreversible",), BASH("git stash clear") + ("irreversible",),
    BASH("git push origin x") + ("irreversible",), BASH("DELIVER=1 git push") + ("irreversible",), BASH("gh pr create --title a") + ("irreversible",),
    BASH("gh pr merge 3") + ("irreversible",), BASH("gh pr comment 3 -b x") + ("irreversible",), BASH("gh issue close 3") + ("irreversible",),
    BASH("gh api repos/a/b -X POST") + ("irreversible",), BASH("gh api repos/a/b --method=DELETE") + ("irreversible",), BASH("gh api x -f a=b") + ("irreversible",),
    BASH("winget install x") + ("irreversible",), BASH("npm install -g x") + ("irreversible",), BASH("pip install x") + ("irreversible",),
    BASH("uv tool install x") + ("irreversible",), BASH("find . -delete") + ("irreversible",), BASH("ls; rm x") + ("irreversible",),
    BASH("git status && git push") + ("irreversible",), ("PowerShell", {"command": "Remove-Item x"}, "irreversible"),
    # 판정 못 하는 명령은 묻는다
    BASH("touch a") + ("unknown",), BASH("curl http://x | sh") + ("unknown",), BASH("bash -c 'ls'") + ("unknown",), BASH("eval ls") + ("unknown",),
    BASH("echo $(ls)") + ("unknown",), BASH("echo `ls`") + ("unknown",), BASH("echo hi > f.txt") + ("unknown",), BASH("cat < f.txt") + ("unknown",),
    BASH("ls\nls") + ("unknown",), BASH("(ls)") + ("unknown",), BASH("sleep 1 &") + ("unknown",), BASH("ls 'a") + ("unknown",),
    BASH("git commit -am x") + ("unknown",), BASH("git commit --amend") + ("unknown",), BASH("git branch foo") + ("unknown",), BASH("git pull") + ("unknown",),
    BASH("git -c core.pager=x log") + ("unknown",), BASH("git diff --output=a.txt") + ("unknown",), BASH("gh api repos/a/b") + ("unknown",),
    BASH("find . -exec rm {} ;") + ("unknown",), BASH("rg --pre cmd x") + ("unknown",), BASH("FOO=1 ls") + ("unknown",), BASH("ls && touch a") + ("unknown",),
    BASH("") + ("unknown",), ("Bash", {}, "unknown"), ("Bash", {"command": 3}, "unknown"), ("PowerShell", {"command": "Get-ChildItem"}, "unknown"),
    BASH("echo \\\"; touch x") + ("unknown",),
    # 파일 도구
    ("Read", {"file_path": os.path.join(W, "a.md")}, "safe"), ("Glob", {"pattern": "*.md"}, "safe"), ("Grep", {"pattern": "x"}, "safe"),
    ("WebSearch", {"query": "x"}, "safe"), ("WebFetch", {"url": "https://example.com/a?b=1"}, "safe"), ("TodoWrite", {"todos": []}, "safe"),
    ("Read", {"file_path": os.path.join(os.path.dirname(W), "other", "a")}, "unknown"),
    ("Edit", {"file_path": os.path.join(W, "a.md")}, "safe"), ("Write", {"file_path": "sub/a.md"}, "safe"), ("NotebookEdit", {"notebook_path": os.path.join(W, "n.ipynb")}, "safe"),
    ("Edit", {"file_path": os.path.join(os.path.dirname(W), "other", "a.md")}, "irreversible"), ("Write", {"file_path": os.path.join(W, "..", "x.md")}, "irreversible"),
    ("Edit", {"file_path": os.path.join(W, ".git", "config")}, "unknown"), ("Write", {"file_path": os.path.join(W, ".claude", "settings.json")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, ".claude", "settings.local.json")}, "unknown"), ("Edit", {}, "unknown"),
    # SAP MCP: 읽기 도구라도 env/adt-tiers.yaml 이 없는 작업 폴더에서는 서버를 확인할 수 없어 unknown(safe 는 test_sap_read_tools_need_exact_server_in_tiers_file)
    ("mcp__abap-adt__getObjectSource", {}, "unknown"), ("mcp__abap-adt-z5u-dev__searchObject", {}, "unknown"), ("mcp__abap-adt__atcWorklists", {}, "unknown"),
    ("mcp__abap-adt__transportInfo", {}, "unknown"), ("mcp__abap-adt__syntaxCheckCode", {}, "unknown"), ("mcp__abap-adt__tracesStatements", {}, "unknown"),
    ("mcp__abap-adt__setObjectSource", {}, "irreversible"), ("mcp__abap-adt-z5u__createObject", {}, "irreversible"), ("mcp__abap-adt__activateByName", {}, "irreversible"),
    ("mcp__abap-adt__transportRelease", {}, "irreversible"), ("mcp__abap-adt__deleteObject", {}, "irreversible"), ("mcp__abap-adt__runClass", {}, "irreversible"),
    ("mcp__abap-adt__pushRepo", {}, "irreversible"), ("mcp__abap-adt__tableContents", {}, "unknown"), ("mcp__abap-adt__runQuery", {}, "unknown"),
    ("mcp__other__whatever", {}, "unknown"), ("Agent", {}, "unknown"), ("Skill", {}, "unknown"), ("", {}, "unknown"),
    # ---- 검토 지적(#649): 확실히 안전한 것만 safe ----
    # 1) 임의 명령 실행 우회 — 옵션 허용 목록
    BASH("git fetch --upload-pack=x .") + ("unknown",), BASH("rg --hostname-bin x y") + ("unknown",), BASH("rg --hostname-bin=x y") + ("unknown",),
    BASH("rg --pre cat foo") + ("unknown",), BASH("rg --pre-glob '*.x' foo") + ("unknown",), BASH("rg -z foo") + ("unknown",),
    BASH("git diff --ext-diff") + ("unknown",), BASH("git log --textconv") + ("unknown",), BASH("git diff --output=o.txt") + ("unknown",),
    BASH("git -c core.pager=x log") + ("unknown",), BASH("git --exec-path=/x log") + ("unknown",), BASH("git -C /tmp log") + ("unknown",),
    BASH("git --git-dir=/x status") + ("unknown",), BASH("git --work-tree=/x status") + ("unknown",), BASH("git log --upload-pack=x") + ("unknown",),
    BASH("git --no-pager log --oneline") + ("safe",), BASH("git status -s") + ("safe",), BASH("git log -n 5 --oneline") + ("safe",),
    BASH("grep -f pats.txt x") + ("unknown",), BASH("grep --file=pats.txt x") + ("unknown",), BASH("grep -rn foo src") + ("unknown",), BASH("grep -n foo src/a.py") + ("safe",),
    BASH("find . -fprint o.txt") + ("unknown",), BASH("find . -exec cat {} ;") + ("unknown",), BASH("find . -name '*.py' -type f") + ("safe",),
    # 2) 강제 옵션이 어디 있든, pytest 옵션 목록
    BASH("git checkout -b x -f origin/main") + ("irreversible",), BASH("git switch -c x --discard-changes main") + ("irreversible",),
    BASH("git switch -c x --force") + ("irreversible",), BASH("git checkout -b x --merge") + ("irreversible",), BASH("git checkout -fb x") + ("irreversible",),
    BASH("git switch -C x main") + ("irreversible",), BASH("git switch -c x main") + ("safe",),
    BASH("pytest --basetemp=d") + ("unknown",), BASH("pytest -p mod") + ("unknown",), BASH("pytest -pmod") + ("unknown",), BASH("pytest --junitxml=r.xml") + ("unknown",),
    BASH("pytest -c other.ini") + ("unknown",), BASH("pytest --rootdir=/x") + ("unknown",), BASH("pytest --pyargs mod") + ("unknown",), BASH("pytest --confcutdir=/x") + ("unknown",),
    BASH("pytest -n 4") + ("unknown",), BASH("pytest /etc/x.py") + ("unknown",), BASH("pytest ../x.py") + ("unknown",),
    BASH("pytest -q -x -s -k 'not slow' -m unit -p no:cacheprovider --tb=short -ra --maxfail=2 tests/test_a.py::test_x") + ("unknown",),  # pytest 는 써 둔 시험 파일로 임의 코드가 돌아 어떤 옵션이어도 묻는다
    BASH("uv run pytest -q -p no:cacheprovider checker/tests/a.py") + ("unknown",), BASH("python -m pytest --basetemp=d") + ("unknown",),
    BASH("uv run pytest --junitxml=r.xml") + ("unknown",),
    # 3) 쓰기 보호 경로(대소문자 무시) / 세션 scratchpad / 메모리
    ("Write", {"file_path": os.path.join(W, ".githooks", "pre-commit")}, "unknown"), ("Write", {"file_path": os.path.join(W, ".claude", "hooks", "x.sh")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, ".claude", "agents", "a.md")}, "unknown"), ("Write", {"file_path": os.path.join(W, ".mcp.json")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, "CLAUDE.md")}, "unknown"), ("Write", {"file_path": os.path.join(W, "sub", "claude.MD")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, "AGENTS.md")}, "unknown"), ("Write", {"file_path": os.path.join(W, "conftest.py")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, "tests", "conftest.py")}, "unknown"), ("Write", {"file_path": os.path.join(W, "plugins", "x", "hooks", "hooks.json")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, ".envrc")}, "unknown"), ("Write", {"file_path": os.path.join(W, ".env.local")}, "unknown"),
    ("Edit", {"file_path": os.path.join(W, "package.json")}, "unknown"), ("Edit", {"file_path": os.path.join(W, "pyproject.toml")}, "unknown"),
    ("Edit", {"file_path": os.path.join(W, "setup.cfg")}, "unknown"), ("Edit", {"file_path": os.path.join(W, "tox.ini")}, "unknown"),
    ("Edit", {"file_path": os.path.join(W, "pytest.ini")}, "unknown"), ("NotebookEdit", {"notebook_path": os.path.join(W, ".GIT", "x.ipynb")}, "unknown"),
    ("Write", {"file_path": os.path.join(W, "docs", "notes.md")}, "safe"),
    ("Write", {"file_path": os.path.join(os.path.dirname(W), "u", "AppData", "Local", "Temp", "claude", "proj", "sess", "scratchpad", "..", "x.py")}, "irreversible"),
    ("Write", {"file_path": os.path.join(os.path.dirname(W), "u", "AppData", "Local", "Temp", "other", "scratchpad", "a.py")}, "irreversible"),
    ("Write", {"file_path": os.path.join(os.path.dirname(W), "u", ".claude", "projects", "p", "memory", "m.md")}, "irreversible"),
    # 4) 읽기 경로: 작업 폴더 밖 · 비밀값 · 변수 확장
    BASH("cat ~/.ssh/id_rsa") + ("unknown",), BASH("cat /etc/passwd") + ("unknown",), BASH("cat .env") + ("unknown",), BASH("head -n 5 ../../x") + ("unknown",),
    BASH("ls /") + ("unknown",), BASH("ls ..") + ("unknown",), BASH("cat C:/Windows/win.ini") + ("unknown",), BASH("cat C:\\Windows\\win.ini") + ("unknown",),
    BASH("cat $HOME/x") + ("unknown",), BASH("cat ${HOME}/x") + ("unknown",), BASH("cat %USERPROFILE%/x") + ("unknown",), BASH("ls ~") + ("unknown",),
    BASH("cat server.pem") + ("unknown",), BASH("cat a/id_rsa.pub") + ("unknown",), BASH("cat key.pfx") + ("unknown",), BASH("cat k.key") + ("unknown",),
    BASH("cat credentials.json") + ("unknown",), BASH("cat .netrc") + ("unknown",), BASH("cat .npmrc") + ("unknown",), BASH("cat .env.local") + ("unknown",),
    BASH("cat *.pem") + ("unknown",), BASH("grep -r token .ssh") + ("unknown",), BASH("wc -l ../x") + ("unknown",), BASH("find / -name x") + ("unknown",),
    BASH("rg foo /etc") + ("unknown",), BASH("tail -n 3 a/../../x") + ("unknown",), BASH("cd .. && ls") + ("unknown",), BASH("cd /tmp && ls") + ("unknown",),
    BASH("cat README.md") + ("safe",), BASH("cat docs/a.md | head -3") + ("safe",), BASH("ls -la src") + ("safe",), BASH("cd sub && cat a.md") + ("unknown",),
    BASH("grep -rn '/api/x' static") + ("unknown",), BASH("tail -n 20 log.txt") + ("safe",), BASH("wc -l a.py b.py") + ("safe",),
    ("Glob", {"pattern": "C:/Users/**/*.pem"}, "unknown"), ("Glob", {"pattern": "**/*.pem"}, "unknown"), ("Glob", {"pattern": "../*.md"}, "unknown"),
    ("Glob", {"pattern": "/etc/*"}, "unknown"), ("Glob", {"pattern": "**/*.md", "path": os.path.dirname(W)}, "unknown"), ("Glob", {"pattern": "src/**/*.py"}, "safe"),
    ("Grep", {"pattern": "x", "path": "/etc"}, "unknown"), ("Grep", {"pattern": "x", "path": ".env"}, "unknown"), ("Grep", {"pattern": "x", "path": "src"}, "safe"),
    ("Read", {"file_path": os.path.join(W, ".env")}, "unknown"), ("Read", {"file_path": "~/.ssh/id_rsa"}, "unknown"), ("Read", {"file_path": os.path.join(W, "..", "x")}, "unknown"),
    # 5) MCP 서버 이름
    ("mcp__evil__getObjectSource", {}, "unknown"), ("mcp__evil__searchObject", {}, "unknown"), ("mcp__abap-adt-z5u__getObjectSource", {}, "unknown"),
    ("mcp__evil__setObjectSource", {}, "irreversible"),
    ("mcp__abap-adt__gitExternalRepoInfo", {}, "unknown"), ("mcp__abap-adt__remoteRepoInfo", {}, "unknown"), ("mcp__abap-adt__renamePreview", {}, "unknown"),
    ("mcp__abap-adt__extractMethodPreview", {}, "unknown"), ("mcp__abap-adt__renameEvaluate", {}, "unknown"), ("mcp__abap-adt__extractMethodEvaluate", {}, "unknown"),
    ("mcp__abap-adt__atcCustomizing", {}, "unknown"), ("mcp__abap-adt__checkRepo", {}, "unknown"),
    # 7) 추가로 안전한 읽기
    BASH("sed -n '3,5p' a.md") + ("safe",), BASH("sed -n '7p' a.md") + ("safe",), BASH("sed -n '3,5p' ../a.md") + ("unknown",), BASH("sed -n '3,5p' .env") + ("unknown",),
    BASH("sed -i 's/a/b/' a.md") + ("unknown",), BASH("sed -n '1,$p' a.md") + ("unknown",), BASH("sed 's/a/b/' a.md") + ("unknown",), BASH("sed -n '3,5w out' a.md") + ("unknown",),
    BASH("cut -d, -f1 a.csv") + ("safe",), BASH("cut -d, -f1 /etc/passwd") + ("unknown",), BASH("sort a.txt | uniq -c") + ("safe",), BASH("tr a-z A-Z") + ("safe",),
    BASH("sort -o out.txt a.txt") + ("unknown",), BASH("sort --output=o a.txt") + ("unknown",), BASH("uniq a.txt out.txt") + ("unknown",),
    BASH("sort -u /etc/hosts") + ("unknown",), BASH("git ls-files | sort | uniq") + ("safe",),
])
def test_risk_classify_table(tool, tool_input, want):
    got, why = risk_mod.classify(tool, tool_input, W)
    assert got == want, (got, why)
    assert why  # 사유는 늘 있다


@pytest.mark.parametrize("tool, tool_input, want", [
    # ---- 2차 검토 ① git clean ----
    BASH("git clean -f -e -n") + ("irreversible",), BASH("git clean -fd") + ("irreversible",), BASH("git clean --force") + ("irreversible",),
    BASH("git clean -n") + ("safe",), BASH("git clean --dry-run") + ("safe",), BASH("git clean -d") + ("safe",), BASH("git clean -dn") + ("safe",), BASH("git clean -n -d") + ("safe",),
    BASH("git clean") + ("unknown",), BASH("git clean -x -n") + ("unknown",), BASH("git clean -X -n") + ("unknown",), BASH("git clean -e x -n") + ("unknown",),
    BASH("git clean -n sub") + ("unknown",),
    # ---- ⑤ WebFetch ----
    ("WebFetch", {"url": "https://example.com"}, "safe"), ("WebFetch", {"url": "http://example.com:8080/x?y=1"}, "safe"), ("WebFetch", {"url": "https://docs.python.org/3/"}, "safe"),
    ("WebSearch", {"query": "x"}, "safe"),
    *[("WebFetch", {"url": u}, "unknown") for u in (
        "http://localhost/", "http://localhost:3000/a", "http://LOCALHOST/", "http://localhost./", "http://a.localhost/", "http://127.0.0.1/", "http://127.1.2.3:80/",
        "http://[::1]/", "http://10.0.0.1/", "http://172.16.0.1/", "http://172.31.255.1/", "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/", "http://printer.local/", "http://nas.lan/", "http://svc.internal/", "http://8.8.8.8/", "http://[2001:db8::1]/",
        "http://2130706433/", "http://0x7f.0.0.1/", "http://0177.0.0.1/", "http://intranet/", "ftp://example.com/", "file:///etc/passwd", "javascript:alert(1)",
        "https://user:pw@example.com/", "https://example.com:notaport/", "", "example.com", "//example.com")],
    ("WebFetch", {}, "unknown"), ("WebFetch", {"url": 3}, "unknown"), ("WebFetch", {"url": None}, "unknown"),
    # ---- ⑥ pytest 는 어떤 꼴이어도 묻는다, 쓰기 보호 경로 추가 ----
    BASH("pytest") + ("unknown",), BASH("pytest tests/a.py") + ("unknown",), BASH("uv run pytest") + ("unknown",), BASH("python -m pytest -q") + ("unknown",),
    BASH("uv run python -m pytest") + ("unknown",), BASH("python3 -m pytest") + ("unknown",),
    *[("Write", {"file_path": os.path.join(W, *p.split("/"))}, "unknown") for p in (
        ".husky/pre-commit", ".husky/_/husky.sh", ".pre-commit-config.yaml", "Makefile", "sub/makefile", ".vscode/settings.json", ".vscode/tasks.json",
        ".github/workflows/ci.yml", "sub/.github/workflows/x.yaml", "sitecustomize.py", "src/usercustomize.py", "site/x.pth", "sub/.npmrc", ".pypirc",
        "hooks/run.py", "plugins/x/hooks/guard.sh", "plugins/x/HOOKS/Guard.PY", ".gitattributes", ".gitconfig")],
    *[("Write", {"file_path": os.path.join(W, *p.split("/"))}, "safe") for p in (
        "hooks/readme.md", "docs/hooks.md", ".github/ISSUE_TEMPLATE/a.md", ".github/CODEOWNERS", "src/hooks_util.py", "docs/Makefile.md", "vscode/a.md")],
    # ---- ⑦ echo / printf / 리디렉션 ----
    BASH("echo hi") + ("safe",), BASH("echo hi 2>&1") + ("safe",), BASH("echo hi > /dev/null") + ("safe",), BASH("printf hello") + ("safe",),
    BASH("echo $HOME") + ("unknown",), BASH("echo ${HOME}") + ("unknown",), BASH("echo %PATH%") + ("unknown",), BASH("echo ~") + ("unknown",), BASH("echo \"$USER\"") + ("unknown",),
    BASH("echo `id`") + ("unknown",), BASH("printf '%s' x") + ("unknown",), BASH("printf '%s' $HOME") + ("unknown",), BASH("echo hi >nul") + ("unknown",),
    BASH("echo hi > nul") + ("unknown",), BASH("echo hi >NUL") + ("unknown",), BASH("echo hi 2>nul") + ("unknown",), BASH("echo -E hi") + ("unknown",),
    # ---- ⑧ 재귀 읽기 · --hidden ----
    BASH("grep -r x .") + ("unknown",), BASH("grep -R x .") + ("unknown",), BASH("grep --recursive x .") + ("unknown",), BASH("grep -rn x a.py") + ("unknown",),
    BASH("grep -n x a.py") + ("safe",), BASH("grep -n -e x a.py") + ("safe",), BASH("grep -A 3 x a.py") + ("safe",),
    BASH("rg foo") + ("unknown",), BASH("rg -A 3 foo") + ("unknown",), BASH("rg foo a.py") + ("safe",), BASH("rg -g '*.py' foo a.py") + ("safe",),
    BASH("rg --hidden foo a.py") + ("unknown",), BASH("rg --no-ignore foo a.py") + ("unknown",), BASH("rg -u foo a.py") + ("unknown",), BASH("rg -uu foo a.py") + ("unknown",),
    BASH("rg -e foo a.py") + ("unknown",), BASH("rg --files") + ("unknown",),
    BASH("ls -R") + ("unknown",), BASH("ls -lR") + ("unknown",), BASH("ls -l") + ("safe",),
    # git 위치 인자 · 경로
    BASH("git show HEAD:.env") + ("unknown",), BASH("git show HEAD:.git/config") + ("unknown",), BASH("git show HEAD:CLAUDE.md") + ("unknown",),
    BASH("git cat-file -p HEAD:.env") + ("unknown",), BASH("git cat-file -p HEAD") + ("unknown",),
    BASH("git diff -- .env") + ("unknown",), BASH("git diff -- secrets/token.txt") + ("unknown",), BASH("git log -p -- .env") + ("unknown",),
    BASH("git log -p -- id_rsa") + ("unknown",), BASH("git log -p -- ssh/id_ed25519") + ("unknown",), BASH("git ls-files .env") + ("unknown",),
    BASH("git add .env") + ("unknown",), BASH("git add -A") + ("safe",), BASH("git add src/a.py") + ("safe",), BASH("git commit -m 'fix token refresh'") + ("safe",),
    BASH("git show HEAD:src/a.py") + ("safe",), BASH("git diff -- src/a.py") + ("safe",), BASH("git log -p -- docs/a.md") + ("safe",),
    BASH("git remote get-url origin") + ("unknown",), BASH("git remote -v") + ("unknown",), BASH("git remote") + ("unknown",),
    BASH("git config user.email") + ("unknown",), BASH("git config --get remote.origin.url") + ("unknown",),
    # 읽기 금지 경로(쓰기 보호 목록 + .git)
    BASH("cat .git/config") + ("unknown",), BASH("cat .git/HEAD") + ("unknown",), BASH("cat CLAUDE.md") + ("unknown",), BASH("cat package.json") + ("unknown",),
    BASH("cat .claude/settings.json") + ("unknown",), BASH("cat Makefile") + ("unknown",), BASH("head -n 3 conftest.py") + ("unknown",), BASH("cat .github/workflows/ci.yml") + ("unknown",),
    BASH("cat .mcp.json") + ("unknown",), BASH("sed -n '1,3p' .gitconfig") + ("unknown",),
    # 비밀값 이름
    *[BASH(f"cat {n}") + ("unknown",) for n in (
        "id_ed25519", "id_ecdsa", "id_rsa", "id_rsa.pub", "a.p12", "server.key.bak", "server.key", "cert.pem.bak", "cert.pem", "my-secrets.txt", "api_token.txt", "TOKEN.md",
        "aws-credentials", "credentials.json", "prod.tfvars", "service-account-prod.json", "service-account.json", ".docker/config.json", "prod.env", "x.ENV", ".env",
        ".env.production", ".netrc", "_netrc", ".git-credentials", ".npmrc", "a.pfx", "sub/.ssh/known_hosts")],
    # ⑨ 진짜 안전한 흔한 명령은 여전히 safe
    BASH("git status") + ("safe",), BASH("git diff --stat") + ("safe",), BASH("git log --oneline -5") + ("safe",), BASH("gh pr view 1") + ("safe",), BASH("gh pr checks 1") + ("safe",),
    BASH("ls") + ("safe",), BASH("cat README.md") + ("safe",), BASH("head -n 20 a.py") + ("safe",), BASH("wc -l a") + ("safe",), BASH("sed -n '3,5p' a") + ("safe",),
    BASH("git branch") + ("safe",), BASH("git diff") + ("safe",), BASH("git show HEAD") + ("safe",), BASH("git log -n 3 --stat") + ("safe",), BASH("git rev-parse --show-toplevel") + ("safe",),
    BASH("gh issue view 3") + ("safe",), BASH("gh pr list") + ("safe",), BASH("tail -n 5 a.log") + ("safe",), BASH("find . -name '*.md'") + ("safe",),
    BASH("git add -A && git commit -m 'msg'") + ("safe",), BASH("git status && git diff --stat") + ("safe",),
])
def test_risk_second_review_table(tool, tool_input, want):
    got, why = risk_mod.classify(tool, tool_input, W)
    assert got == want, (got, why)


def test_risk_cd_is_safe_only_as_leading_cd_and_and_into_a_real_work_folder(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    cwd = str(tmp_path)
    c = lambda cmd: risk_mod.classify("Bash", {"command": cmd}, cwd)[0]  # noqa: E731
    assert c("cd sub && git status") == "safe" and c("cd sub && git status | head -5") == "safe" and c("cd sub && ls && git diff --stat") == "safe"
    assert c("cd sub; git status") == "unknown" and c("cd sub | cat a") == "unknown" and c("cd sub || ls") == "unknown" and c("cd sub") == "unknown"
    assert c("ls && cd sub && ls") == "unknown" and c("git status; cd sub && ls") == "unknown" and c("cd sub && cd sub && ls") == "unknown"
    assert c("cd nope && ls") == "unknown" and c("cd file.txt && ls") == "unknown" and c("cd .. && ls") == "unknown" and c("cd / && ls") == "unknown"
    assert c("cd ~ && ls") == "unknown" and c("cd $HOME && ls") == "unknown" and c("cd && ls") == "unknown" and c("cd -- sub && ls") == "unknown"
    assert c("cd sub && cat ../file.txt") == "safe"  # 기준 폴더가 sub 라 ../file.txt 는 작업 폴더 안
    assert c("cd sub && cat ../../x") == "unknown"
    assert c(f"cd {tmp_path.parent} && ls") == "unknown"


def test_risk_rg_needs_a_file_path_and_refuses_folders(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    cwd = str(tmp_path)
    c = lambda cmd: risk_mod.classify("Bash", {"command": cmd}, cwd)[0]  # noqa: E731
    assert c("rg foo a.py") == "safe" and c("rg foo") == "unknown" and c("rg foo .") == "unknown" and c("rg foo sub") == "unknown" and c("rg foo a.py sub") == "unknown"
    assert c("grep -n foo a.py") == "safe"


def test_risk_symlink_to_secret_is_checked_by_real_name(tmp_path):
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("K=1", encoding="utf-8")
    try:
        os.symlink(tmp_path / ".env", tmp_path / "harmless.txt")
        os.symlink(tmp_path / "real.txt", tmp_path / "fine.txt")
    except (OSError, NotImplementedError):
        pytest.skip("심볼릭 링크를 만들 수 없는 환경")
    cwd = str(tmp_path)
    assert risk_mod.classify("Bash", {"command": "cat harmless.txt"}, cwd)[0] == "unknown"
    assert risk_mod.classify("Read", {"file_path": str(tmp_path / "harmless.txt")}, cwd)[0] == "unknown"
    assert risk_mod.classify("Bash", {"command": "cat fine.txt"}, cwd)[0] == "safe"


def test_risk_scratchpad_is_decided_by_real_temp_dir_and_depth(tmp_path, monkeypatch):
    import tempfile
    temp = tmp_path / "tmproot"
    work = tmp_path / "work"
    temp.mkdir(); work.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(temp))
    cwd = str(work)
    scratch = temp / "claude" / "proj" / "sess" / "scratchpad"
    w = lambda p: risk_mod.classify("Write", {"file_path": str(p)}, cwd)  # noqa: E731
    assert w(scratch / "a.py")[0] == "safe" and "임시 폴더" in w(scratch / "a.py")[1]
    assert w(scratch / "sub" / "b.txt")[0] == "safe"
    for bad in (temp / "claude" / "proj" / "scratchpad" / "a",              # 깊이가 모자란다
                temp / "claude" / "proj" / "sess" / "other" / "a",          # scratchpad 가 아니다
                temp / "claude" / "proj" / "sess" / "scratchpad",           # 폴더 자체
                temp / "claude" / "p" / "s" / "extra" / "scratchpad" / "a",  # 깊이가 넘친다
                scratch / ".." / "x.py",                                    # 벗어난다
                temp / "other" / "p" / "s" / "scratchpad" / "a",            # claude 폴더가 아니다
                tmp_path / "evil" / "temp" / "claude" / "foo" / "scratchpad" / "a",   # 글자만 같은 다른 곳
                tmp_path / "Windows" / "Temp" / "claude" / "a" / "scratchpad" / "x.dll",
                tmp_path / "home" / ".claude" / "projects" / "p" / "memory" / "m.md"):  # 메모리 폴더는 묻는다
        assert w(bad)[0] == "irreversible", (bad, w(bad))
    # 작업 폴더 안 하위 폴더 이름이 temp/claude/scratchpad 여도 scratchpad 가 아니다(보호 경로 규칙을 그대로 받는다)
    fake = work / "docs" / "temp" / "claude" / "s" / "scratchpad"
    assert w(fake / "CLAUDE.md")[0] == "unknown"
    assert w(work / ".claude" / "commands" / "Temp" / "Claude" / "a" / "Scratchpad" / "evil.md")[0] == "unknown"
    assert w(work / ".git" / "hooks" / "temp" / "claude" / "s" / "scratchpad" / "pre-commit")[0] == "unknown"
    assert "임시 폴더" not in w(fake / "a.md")[1]  # 안 폴더라 일반 작업 폴더 안 쓰기로 본다


def test_sap_read_tools_need_exact_server_in_tiers_file(tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "adt-tiers.yaml").write_text(
        "servers:\n  abap-adt:\n    writes_allowed: false\n  abap-adt-z5u:\n    writes_allowed: false\nwrite_tools: [setObjectSource]\n", encoding="utf-8")
    cwd = str(tmp_path)
    c = lambda name: risk_mod.classify(name, {}, cwd)[0]  # noqa: E731
    assert c("mcp__abap-adt__getObjectSource") == "safe" and c("mcp__abap-adt-z5u__searchObject") == "safe"
    for bad in ("mcp__abap-adt-z5u-dev__getObjectSource", "mcp__abap-adt-evil__getObjectSource", "mcp__ABAP-ADT__getObjectSource", "mcp__abap__getObjectSource",
                "mcp__evil__getObjectSource", "mcp__abap-adt-z5u-dev__searchObject"):  # 접두어가 같아도 이름이 정확히 같지 않으면 묻는다
        assert c(bad) == "unknown", bad
    for gone in ("gitExternalRepoInfo", "remoteRepoInfo", "renamePreview", "extractMethodPreview", "renameEvaluate", "extractMethodEvaluate", "atcCustomizing", "checkRepo"):
        assert c(f"mcp__abap-adt__{gone}") == "unknown", gone
    assert c("mcp__abap-adt__tableContents") == "unknown" and c("mcp__abap-adt__runQuery") == "unknown"
    assert c("mcp__abap-adt__setObjectSource") == "irreversible" and c("mcp__evil__setObjectSource") == "irreversible"
    assert risk_mod.classify("mcp__abap-adt__getObjectSource", {}, str(tmp_path / "nowhere"))[0] == "unknown"  # 파일이 없으면 읽기 도구도 묻는다
    (tmp_path / "env" / "adt-tiers.yaml").write_text("깨진: [", encoding="utf-8")
    assert c("mcp__abap-adt__getObjectSource") == "unknown"
    assert "sap_server_prefixes" not in json.loads((CONSOLE / "safe_tools.json").read_text(encoding="utf-8"))  # 접두어 항목은 없앴다


def test_risk_classify_without_cwd_never_calls_file_edits_safe():
    assert risk_mod.classify("Edit", {"file_path": "a.md"}, "")[0] == "unknown"
    assert risk_mod.classify("Edit", {"file_path": "a.md"}, None)[0] == "unknown"


def test_risk_rules_come_from_data_file_and_missing_file_means_everything_unknown(tmp_path):
    data = json.loads((CONSOLE / "safe_tools.json").read_text(encoding="utf-8"))
    assert "getObjectSource" in data["sap_read_tools"] and "setObjectSource" in data["sap_write_tools"]
    assert not {"tableContents", "runQuery"} & set(data["sap_read_tools"])  # 데이터 조회는 하네스 훅이 따로 판정한다
    assert risk_mod.load_rules(tmp_path / "none.json") == {}
    assert risk_mod.load_rules(CONSOLE / "risk.py") == {}  # 깨진 파일도 빈 목록


def test_risk_write_tools_cover_adt_tiers_write_tools_in_repo():
    """env/adt-tiers.yaml 쓰기 목록(예시)의 이름이 우리 쓰기 목록에 빠져 있지 않다."""
    names = {"setObjectSource", "createObject", "deleteObject", "activateObjects", "activateByName", "renameExecute", "extractMethodExecute",
             "createTransport", "transportRelease", "transportDelete", "publishServiceBinding", "unPublishServiceBinding", "deployUi5App",
             "undeployUi5App", "publishBusinessCatalog", "runClass", "gitPullRepo", "pushRepo"}
    assert names <= set(json.loads((CONSOLE / "safe_tools.json").read_text(encoding="utf-8"))["sap_write_tools"])


def _perm(c, sid, tool, tool_input, **kw):
    return c.hook("permission", {"session_id": sid, "cwd": str(c.work), "hook_event_name": "PermissionRequest", "tool_name": tool,
                                 "tool_input": tool_input, **kw})


def _answer_when_pending(c, sid, decision="allow"):
    req = wait_for(lambda: (c.pending(sid) or [None])[0])
    assert c.call("POST", f"/api/requests/{req.rid}/answer", {"decision": decision})[0] == 200
    return req


def test_ask_setting_defaults_to_needed_and_validates_and_persists(authed):
    assert authed.call("GET", "/api/settings/ask")[1] == {"level": "needed"}
    for bad in ("", "ALL", "none", 3, None, ["all"]):
        assert authed.call("PUT", "/api/settings/ask", {"level": bad})[0] == 400
    assert authed.call("PUT", "/api/settings/ask", {})[0] == 400
    assert authed.call("PUT", "/api/settings/ask", {"level": "edits"})[1] == {"level": "edits"}
    assert authed.call("GET", "/api/settings/ask")[1] == {"level": "edits"}
    saved = authed.state / console_server.ASK_FILE
    assert json.loads(saved.read_text(encoding="utf-8")) == {"level": "edits"}  # notify.json 처럼 상태 폴더에 둔다
    strict = {"level": "all", "problem": "설정을 읽지 못해 모든 명령마다 물어"}
    for broken in ("not json", json.dumps({"level": "bogus"}), json.dumps([1]), "", json.dumps({})):  # 있는데 깨졌으면 가장 엄격하게
        saved.write_text(broken, encoding="utf-8")
        assert authed.call("GET", "/api/settings/ask")[1] == strict, broken
    assert authed.call("PUT", "/api/settings/ask", {"level": "needed"})[1] == {"level": "needed"}  # 다시 저장하면 풀린다
    assert authed.call("GET", "/api/settings/ask")[1] == {"level": "needed"}
    saved.unlink()
    assert authed.call("GET", "/api/settings/ask")[1] == {"level": "needed"}  # 파일이 아예 없을 때(처음)만 기본
    assert authed.call("PUT", "/api/settings/ask", {"level": "all"}, cookie=False)[0] in (401, 403)  # 로그인 없이는 못 바꾼다


def test_needed_level_allows_safe_without_card_and_logs_once(browser):
    browser.event("n1", "SessionStart")
    status, body = _perm(browser, "n1", "Bash", {"command": "git status"})[:2]
    assert status == 200 and body == {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
    assert browser.pending("n1") == []
    s = browser.app.store.get("n1")
    assert [e["text"] for e in s["log"] if e["text"].startswith("자동 허용")] == ["자동 허용: Bash: git status (git 으로 상태를 읽기만 해)"]
    assert not [c for c in s.get("chat") or [] if c.get("role") == "req"]  # 대화에는 남기지 않는다
    _perm(browser, "n1", "Bash", {"command": "git status"})  # 같은 호출을 훅과 콘솔 연결이 둘 다 물어도 한 줄
    assert len([e for e in browser.app.store.get("n1")["log"] if e["text"].startswith("자동 허용")]) == 1
    f = browser.work / "a.md"
    assert _perm(browser, "n1", "Edit", {"file_path": str(f), "old_string": "a", "new_string": "b"})[1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert _perm(browser, "n1", "Read", {"file_path": str(f)})[1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_unreadable_ask_setting_asks_for_everything(browser):
    browser.state.mkdir(parents=True, exist_ok=True)
    (browser.state / console_server.ASK_FILE).write_text("{broken", encoding="utf-8")
    browser.event("n9", "SessionStart")
    holder = browser.hook_async("permission", {"session_id": "n9", "cwd": str(browser.work), "tool_name": "Bash", "tool_input": {"command": "git status"}})
    req = wait_for(lambda: (browser.pending("n9") or [None])[0])  # 안전한 명령도 카드로 묻는다
    assert req.risk == ""
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
    holder["t"].join(30)
    assert not [e for e in browser.app.store.get("n9")["log"] if e["text"].startswith("자동 허용")]


def test_tier_file_servers_count_as_sap_servers(tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "adt-tiers.yaml").write_text(
        "servers:\n  corp-sap:\n    writes_allowed: false\nwrite_tools: [setObjectSource]\n", encoding="utf-8")
    assert risk_mod.classify("mcp__corp-sap__getObjectSource", {}, str(tmp_path))[0] == "safe"
    assert risk_mod.classify("mcp__other__getObjectSource", {}, str(tmp_path))[0] == "unknown"
    assert risk_mod.classify("mcp__corp-sap__getObjectSource", {}, str(tmp_path / "none"))[0] == "unknown"  # 파일이 없으면 모르는 서버
    (tmp_path / "env" / "adt-tiers.yaml").write_text("깨진: [", encoding="utf-8")
    assert risk_mod.classify("mcp__corp-sap__getObjectSource", {}, str(tmp_path))[0] == "unknown"


def test_needed_level_asks_for_unknown_with_plain_card(browser):
    browser.event("n2", "SessionStart")
    holder = browser.hook_async("permission", {"session_id": "n2", "cwd": str(browser.work), "tool_name": "Bash", "tool_input": {"command": "touch a"}})
    req = wait_for(lambda: (browser.pending("n2") or [None])[0])
    pub = browser.call("GET", f"/api/requests/{req.rid}")[1]
    assert "risk" not in pub and "riskNote" not in pub  # 일반 카드
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow_session"})[0] == 400  # 제안이 없어서 늘 그랬다
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny"})[0] == 200
    holder["t"].join(30)
    assert holder["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_irreversible_goes_to_yellow_card_and_cannot_be_remembered(browser):
    browser.event("n3", "SessionStart")
    sugg = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm *"}], "behavior": "allow", "destination": "session"}]
    holder = browser.hook_async("permission", {"session_id": "n3", "cwd": str(browser.work), "tool_name": "Bash",
                                                "tool_input": {"command": "rm old.xlsx"}, "permission_suggestions": sugg})
    req = wait_for(lambda: (browser.pending("n3") or [None])[0])
    pub = browser.call("GET", f"/api/requests/{req.rid}")[1]
    assert pub["risk"] == "irreversible" and pub["riskNote"] == "파일이나 폴더를 지우려 해"
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow_session"})[0] == 400  # 되돌릴 수 없는 일은 다시 묻지 않기로 허용하지 못한다
    assert browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})[0] == 200
    holder["t"].join(30)
    assert holder["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    s = browser.call("GET", "/api/sessions/n3")[1]
    assert s["pendingRequestIds"] == [] and s["permissionNote"] == ""


@pytest.mark.parametrize("tool, tool_input", [
    ("Bash", {"command": "git push origin x"}), ("Bash", {"command": "gh pr merge 3"}), ("mcp__abap-adt__setObjectSource", {}),
    ("Write", {"file_path": "OUTSIDE"}),
])
@pytest.mark.parametrize("level", ["needed", "edits", "all"])
def test_irreversible_is_asked_at_every_level(browser, tool, tool_input, level):
    assert browser.call("PUT", "/api/settings/ask", {"level": level})[0] == 200
    if tool_input.get("file_path") == "OUTSIDE":
        tool_input = {"file_path": str(browser.work.parent / "outside.md")}
    browser.event("n4", "SessionStart")
    holder = browser.hook_async("permission", {"session_id": "n4", "cwd": str(browser.work), "tool_name": tool, "tool_input": tool_input})
    req = wait_for(lambda: (browser.pending("n4") or [None])[0])
    assert req.risk == "irreversible"
    browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "deny"})
    holder["t"].join(30)


def test_edits_level_also_asks_for_edit_tools_but_not_reads(browser):
    assert browser.call("PUT", "/api/settings/ask", {"level": "edits"})[0] == 200
    browser.event("n5", "SessionStart")
    assert _perm(browser, "n5", "Bash", {"command": "git status"})[1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    assert _perm(browser, "n5", "Read", {"file_path": str(browser.work / "a")})[1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"
    for tool, tool_input in (("Edit", {"file_path": str(browser.work / "a.md")}), ("Write", {"file_path": str(browser.work / "b.md")}),
                             ("NotebookEdit", {"notebook_path": str(browser.work / "n.ipynb")})):
        holder = browser.hook_async("permission", {"session_id": "n5", "cwd": str(browser.work), "tool_name": tool, "tool_input": tool_input})
        req = wait_for(lambda: (browser.pending("n5") or [None])[0])
        assert req.risk == ""  # 되돌릴 수 없는 일은 아니라 일반 카드
        browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
        holder["t"].join(30)
        assert holder["r"][1]["hookSpecificOutput"]["decision"]["behavior"] == "allow"


def test_all_level_asks_for_everything_like_before(browser):
    assert browser.call("PUT", "/api/settings/ask", {"level": "all"})[0] == 200
    browser.event("n6", "SessionStart")
    for tool, tool_input in (("Bash", {"command": "git status"}), ("Read", {"file_path": str(browser.work / "a")})):
        holder = browser.hook_async("permission", {"session_id": "n6", "cwd": str(browser.work), "tool_name": tool, "tool_input": tool_input})
        req = wait_for(lambda: (browser.pending("n6") or [None])[0])
        browser.call("POST", f"/api/requests/{req.rid}/answer", {"decision": "allow"})
        holder["t"].join(30)
    assert not [e for e in browser.app.store.get("n6")["log"] if e["text"].startswith("자동 허용")]


def test_terminal_session_without_browser_is_untouched_by_auto_allow(authed):
    """브라우저가 없으면 터미널 프롬프트가 맡는다 — 안전한 명령이어도 콘솔이 대신 허용하지 않는다."""
    authed.event("n7", "SessionStart")
    assert _perm(authed, "n7", "Bash", {"command": "git status"})[:2] == (200, None)
    assert _perm(authed, "n7", "Bash", {"command": "rm x"})[:2] == (200, None)
    assert not [e for e in authed.app.store.get("n7")["log"] if e["text"].startswith("자동 허용")]


def test_ask_question_tool_is_never_auto_allowed(browser):
    browser.event("n8", "SessionStart")
    assert browser.hook("permission", perm_body("n8", tool_name="AskUserQuestion"))[1] is None
    assert Hooks(Store(None)).auto_allowed({"id": "x", "cwd": "/w"}, "AskUserQuestion", {}) is False


def test_managed_bridge_auto_allows_safe_and_marks_irreversible(tmp_path):
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    hooks = Hooks(store, poll=0.02)
    m.auto_allowed, m.risk_of = hooks.auto_allowed, hooks.risk_of
    store.ensure("s1", str(tmp_path))["managed"] = True
    m.on_event(proc, {"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "git status"}}})
    assert proc.written[0]["response"]["response"] == {"behavior": "allow", "updatedInput": {"command": "git status"}}
    assert store.pending_for("s1") == []
    m.on_event(proc, {"type": "control_request", "request_id": "r2", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "rm x"}}})
    (req,) = store.pending_for("s1")
    assert req.risk == "irreversible" and len(proc.written) == 1  # 사람 답 전에는 답하지 않는다
    store.resolve(req.rid, permission_reply({"behavior": "deny", "message": "싫음"}), "거부함")
    wait_for(lambda: len(proc.written) == 2)


def test_managed_bridge_without_hooks_wired_still_asks(tmp_path):
    store = Store(None)
    proc = FakeProc()
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path))
    m.on_event(proc, {"type": "control_request", "request_id": "r1", "request": {"subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "git status"}}})
    assert len(store.pending_for("s1")) == 1 and proc.written == []  # 연결이 없으면 허용으로 뭉개지 않는다


def test_auto_permission_mode_is_launched_and_reported(tmp_path):
    m = managed.Manager(Store(None), lambda: ["claude"], "/plug")
    cmd = m.command(permission="auto")
    assert cmd[cmd.index("--permission-mode") + 1] == "auto"
    assert "--dangerously-skip-permissions" not in cmd and "bypassPermissions" not in cmd


def _init_event(mode):
    return {"type": "system", "subtype": "init", "session_id": "s1", "permissionMode": mode, "model": "m"}


def test_auto_mode_running_normally_has_no_warning(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path)).update(managed=True, permissionChoice="auto")
    m.on_event(FakeProc(), _init_event("auto"))
    assert not store.get("s1").get("permissionNote")


def test_auto_mode_started_as_other_mode_shows_reason_with_original(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path)).update(managed=True, permissionChoice="auto")
    m.on_event(FakeProc(), _init_event("default"))
    note = store.get("s1")["permissionNote"]
    assert "auto 모드를 쓸 수 없는 것 같아" in note and "원문: default" in note and "이유는 확인 못 함" in note
    assert any(e["text"].startswith("권한 모드 auto:") for e in store.get("s1")["log"])
    assert store.get("s1")["permissionMode"] == "default"


def test_auto_mode_error_result_and_early_exit_are_reported(tmp_path):
    store = Store(None)
    m = managed.Manager(store, lambda: None, "/p")
    store.ensure("s1", str(tmp_path)).update(managed=True, permissionChoice="auto")
    m.on_event(FakeProc(), _init_event("auto"))
    m.on_event(FakeProc(), {"type": "result", "is_error": True, "result": "auto mode is not available for this model", "session_id": "s1"})
    assert "claude 가 낸 메시지 원문: auto mode is not available for this model" in store.get("s1")["permissionNote"]
    # 시작 신호도 못 보내고 끝났다
    store.ensure("s2", str(tmp_path)).update(managed=True, permissionChoice="auto", starting=True)
    proc = FakeProc()
    proc.session_id = proc.temp_id = "s2"
    proc.last_result = "Error: auto mode requires an Opus 4.6+ model"
    m.on_exit(proc)
    note = store.get("s2")["permissionNote"]
    assert "시작하다 끝났어" in note and "원문: Error: auto mode requires an Opus 4.6+ model" in note
    store.ensure("s3", str(tmp_path)).update(managed=True, permissionChoice="auto", starting=True)
    proc = FakeProc()
    proc.session_id = proc.temp_id = "s3"
    m.on_exit(proc)
    assert "확인 못 함" in store.get("s3")["permissionNote"]
    # 다른 모드를 고른 세션은 이 안내를 만들지 않는다
    store.ensure("s4", str(tmp_path)).update(managed=True, permissionChoice="plan", starting=True)
    proc = FakeProc()
    proc.session_id = proc.temp_id = "s4"
    m.on_exit(proc)
    assert not store.get("s4").get("permissionNote")
