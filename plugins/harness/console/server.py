"""HTTP 서버, 라우팅, 인증, SSE(web-console.md §3, §4, §8)."""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import analysis
import gitstate
import platform_compat
from hooks_api import Hooks, permission_reply, question_reply
from managed import Manager
from store import MAX_PENDING_STOP, Store, public_session, can_send

APP_NAME = "harness-console"
COOKIE = "harness_console"
COOKIE_MAX_AGE = 30 * 24 * 3600
REQUEST_TIMEOUT = 30.0  # 요청을 읽는 동안의 소켓 timeout. 본문을 다 읽은 훅 연결은 timeout 을 풀고 오래 기다린다
TOKEN_TTL = 60.0
API_BODY_LIMIT = 1 << 20
HOOK_BODY_LIMIT = 32 << 20
HEARTBEAT = 10.0
HIDDEN_SKILLS = {"update", "scaffold", "open"}
# Windows 레지스트리의 MIME 설정에 영향받지 않게 직접 매핑한다(CSP 가 script 를 막는 일 방지).
STATIC_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
                ".svg": "image/svg+xml", ".json": "application/json", ".map": "application/json"}
SPA_PATHS = re.compile(r"^/(s/[^/]+|r/[^/]+|new|settings)?$")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def plugin_info(plugin_root: Path) -> tuple[str, str]:
    try:
        meta = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return str(meta.get("name", "harness")), str(meta.get("version", ""))
    except (OSError, ValueError):
        return "harness", ""


def load_skills(plugin_root: Path) -> list[str]:
    """skills/*/SKILL.md 의 frontmatter name 에서 읽는다. update, scaffold, open 은 버튼으로 내지 않는다."""
    names = []
    for f in sorted((plugin_root / "skills").glob("*/SKILL.md")):
        name = f.parent.name
        try:
            head = f.read_text(encoding="utf-8").split("---", 2)
            for line in head[1].splitlines() if len(head) > 2 else []:
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
        except OSError:
            pass
        if name not in HIDDEN_SKILLS:
            names.append(name)
    return names


class App:
    def __init__(self, port: int, state_dir: Path | None, plugin_root: Path, clock=time.time,
                 browser_open=webbrowser.open, claude_cmd=None, git_inspect=gitstate.inspect,
                 model: str = "", poll: float = 0.5, question_wait: float = 300.0, sync_spawn: bool = False,
                 popen=subprocess.Popen, request_timeout: float = REQUEST_TIMEOUT):
        self.port = port
        self.request_timeout = request_timeout
        self.clock = clock
        self.plugin_root = Path(plugin_root)
        self.plugin_name, self.version = plugin_info(self.plugin_root)
        self.skills = load_skills(self.plugin_root)
        self.browser_open = browser_open
        self.git_inspect = git_inspect
        self.sync_spawn = sync_spawn
        self.static_dir = Path(__file__).resolve().parent / "static"
        self.store = Store(state_dir, clock)
        claude_cmd = claude_cmd or platform_compat.find_claude
        self.manager = Manager(self.store, claude_cmd, str(self.plugin_root), model=model, popen=popen)
        self.analyses = analysis.Analyses(claude_cmd, model=model, spawn=self.spawn)
        self.hooks = Hooks(self.store, clock, poll, question_wait, refresh_git=self.refresh_git)
        self.tokens: dict[str, float] = {}
        self.cookies: dict[str, float] = {}  # 쿠키 값 -> 만료 시각(서버 쪽에서도 COOKIE_MAX_AGE 를 지킨다)
        self.lock = threading.Lock()
        self.set_port(port)

    def set_port(self, port: int) -> None:
        """시험이 임시 포트(0)로 서버를 연 뒤 실제 포트를 알려 줄 때 쓴다."""
        self.port = port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.origins = {f"http://{h}" for h in self.hosts}

    def spawn(self, fn) -> None:
        if self.sync_spawn:
            fn()
        else:
            threading.Thread(target=fn, daemon=True).start()

    # ---- 인증 ----
    def open_browser(self) -> dict:
        token = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            self.tokens = {t: exp for t, exp in self.tokens.items() if exp > now}
            self.tokens[token] = now + TOKEN_TTL
        # 토큰은 서버 프로세스가 브라우저에 직접 넘기고, 응답 본문과 stdout 에는 넣지 않는다.
        if not platform_compat.open_in_browser(f"http://127.0.0.1:{self.port}/auth?t={token}", self.browser_open):
            with self.lock:
                self.tokens.pop(token, None)
            raise HttpError(503, "브라우저를 열지 못했습니다.")
        return {"ok": True}

    def consume_token(self, token: str) -> str | None:
        """일회용 토큰을 소비하고 쿠키 값을 돌려준다. 없거나 만료됐으면 None."""
        with self.lock:
            exp = self.tokens.pop(token, None)
            if exp is None or exp <= self.clock():
                return None
            value = secrets.token_urlsafe(32)
            self.cookies = {c: e for c, e in self.cookies.items() if e > self.clock()}
            self.cookies[value] = self.clock() + COOKIE_MAX_AGE
            return value

    def cookie_ok(self, header: str | None) -> bool:
        if not header:
            return False
        jar = SimpleCookie()
        try:
            jar.load(header)
        except Exception:
            return False
        morsel = jar.get(COOKIE)
        with self.lock:
            exp = self.cookies.get(morsel.value) if morsel else None
            return bool(exp and exp > self.clock())

    # ---- 세션 보조 ----
    def refresh_git(self, sid: str) -> None:
        s = self.store.get(sid)
        if s is None or not s["cwd"]:
            return

        def work():
            info = self.git_inspect(s["cwd"])
            with self.store.lock:
                s["repo"], s["branch"] = info["repo"], info["branch"]
                s["turn"] = {"skill": info["skill"], "unknown": info["unknown"]}
                if info["isRepo"]:
                    s["changedFiles"] = info["changedFiles"]
            self.store.touch(s)

        self.spawn(work)

    def model_of(self, s: dict) -> dict:
        """잠금 순서: manager.lock(잎) 은 store.lock 을 쥔 채 잡지 않는다. 그래서 살아 있는지부터 묻고 나서 store.lock 을 잡는다."""
        alive = self.manager.alive(s["id"]) if s["managed"] else False
        with self.store.lock:
            s["managed_alive"] = alive
            return public_session(self.store, s, self.skills)

    def known_roots(self) -> list[str]:
        with self.store.lock:
            paths = list(self.store.folders) + [s["cwd"] for s in self.store.sessions.values() if s["cwd"]]
        return [os.path.realpath(p) for p in paths if os.path.isdir(p)]

    def shutdown(self) -> None:
        self.manager.shutdown()
        self.store.flush()

    # ---- API ----
    def api(self, method: str, path: str, query: dict, body: dict):
        for m, pattern, fn in ROUTES:
            if m != method:
                continue
            match = pattern.fullmatch(path)
            if match:
                return fn(self, match.groups(), query, body)
        raise HttpError(404, "없는 경로입니다.")

    def get_session(self, sid: str) -> dict:
        s = self.store.get(sid)
        if s is None:
            raise HttpError(404, "없는 세션입니다.")
        return s

    def a_sessions(self, g, q, b):
        with self.store.lock:
            items = sorted(self.store.sessions.values(), key=lambda s: -s["updatedAt"])
        return 200, [self.model_of(s) for s in items]

    def a_session(self, g, q, b):
        return 200, self.model_of(self.get_session(g[0]))

    def a_message(self, g, q, b):
        s = self.get_session(g[0])
        text = b.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "text 가 비어 있습니다.")
        return self.deliver(s, text.strip(), {"kind": "message", "text": text.strip()})

    def a_run(self, g, q, b):
        s = self.get_session(g[0])
        skill = g[1]
        if skill not in self.skills:
            raise HttpError(404, "없는 스킬입니다.")
        args = b.get("args") if isinstance(b.get("args"), str) else ""
        text = f"/{self.plugin_name}:{skill}" + (f" {args.strip()}" if args.strip() else "")
        return self.deliver(s, text, {"kind": "skill", "skill": skill, "args": args.strip()})

    def deliver(self, s: dict, text: str, queued: dict):
        """콘솔이 띄운 세션은 stdin 으로 바로, 실행 중인 터미널 세션은 턴 끝에 Stop 훅으로 보낸다. 쉬는 터미널은 불가."""
        if s["managed"]:
            if not self.manager.send_or_resume(s["id"], text):
                raise HttpError(502, "세션에 보내지 못했습니다.")
            with self.store.lock:
                s["turn_running"] = True
            self.store.touch(s)
            return 202, {"queued": False, "sent": True}
        with self.store.lock:
            ok, why = can_send(s, self.store)
            if not ok:
                raise HttpError(409, why)
            if len(s["pending_stop"]) >= MAX_PENDING_STOP:
                raise HttpError(429, "예약된 요청이 너무 많습니다. 세션이 처리한 뒤에 다시 보내십시오.")
            s["pending_stop"].append(queued)
        self.store.touch(s)
        return 202, {"queued": True, "sent": False}

    def a_reserve(self, g, q, b):
        s = self.get_session(g[0])
        if g[1] not in self.skills:
            raise HttpError(404, "없는 스킬입니다.")
        with self.store.lock:
            ok, why = can_send(s, self.store)
            if not ok:
                raise HttpError(409, why)
            if not any(i.get("skill") == g[1] for i in s["pending_stop"]):
                if len(s["pending_stop"]) >= MAX_PENDING_STOP:
                    raise HttpError(429, "예약된 요청이 너무 많습니다.")
                s["pending_stop"].append({"kind": "skill", "skill": g[1], "args": ""})
        self.store.touch(s)
        return 200, self.model_of(s)

    def a_unreserve(self, g, q, b):
        s = self.get_session(g[0])
        with self.store.lock:
            s["pending_stop"][:] = [i for i in s["pending_stop"] if not (i.get("kind") == "skill" and i.get("skill") == g[1])]
        self.store.touch(s)
        return 200, self.model_of(s)

    def a_interrupt(self, g, q, b):
        s = self.get_session(g[0])
        if not s["managed"]:
            raise HttpError(409, "콘솔이 띄운 세션만 중단할 수 있습니다.")
        if not self.manager.interrupt(s["id"]):
            raise HttpError(409, "실행 중인 프로세스가 없습니다.")
        return 200, {"ok": True}

    def a_request(self, g, q, b):
        r = self.store.get_request(g[0])
        if r is None:
            raise HttpError(404, "없는 요청입니다.")
        data = r.public()
        s = self.store.get(r.session_id)
        data["sessionTitle"] = s["title"] if s else ""
        data["suggestions"] = r.suggestions
        return 200, data

    def a_answer(self, g, q, b):
        r = self.store.get_request(g[0])
        if r is None:
            raise HttpError(404, "없는 요청입니다.")
        if r.kind == "permission":
            decision = b.get("decision")
            if decision == "allow":
                reply, outcome = {"behavior": "allow"}, "허용함"
            elif decision == "allow_session":
                if not r.suggestions:
                    raise HttpError(400, "이 요청에는 '다시 묻지 않기' 제안이 없습니다.")
                reply, outcome = {"behavior": "allow", "updatedPermissions": r.suggestions}, "허용하고 이 세션에서 다시 묻지 않음"
            elif decision == "deny":
                reason = b.get("reason") if isinstance(b.get("reason"), str) and b["reason"].strip() else "콘솔에서 거부했습니다."
                reply, outcome = {"behavior": "deny", "message": reason}, "거부함"
            else:
                raise HttpError(400, "decision 은 allow, allow_session, deny 중 하나여야 합니다.")
            response = permission_reply(reply)
        else:
            response = question_reply(r.tool_input["questions"], self.check_answers(r, b.get("answers")))
            outcome = "답변함"
        if not self.store.resolve(r.rid, response, outcome):
            raise HttpError(409, f"이미 처리된 요청입니다: {r.outcome}")
        return 200, r.public()

    @staticmethod
    def check_answers(r, answers) -> dict:
        questions = [q.get("question") for q in r.tool_input.get("questions", []) if isinstance(q, dict)]
        if not isinstance(answers, dict):
            raise HttpError(400, "answers 가 객체가 아닙니다.")
        result = {}
        for q in questions:
            value = answers.get(q)
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                value = ", ".join(value)
            if not isinstance(value, str) or not value.strip():
                raise HttpError(400, f"답이 없는 질문이 있습니다: {q}")
            result[q] = value
        return result

    # 새 작업
    def a_new(self, g, q, b):
        text, cwd = b.get("text"), b.get("cwd")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "요청 글이 비어 있습니다.")
        folder = self.folder_info(cwd)
        if not folder["ok"]:
            raise HttpError(400, folder["error"])
        self.store.add_folder(folder["path"])
        return 202, {"id": self.analyses.start(text.strip(), folder["path"])}

    def get_job(self, jid):
        job = self.analyses.get(jid)
        if job is None:
            raise HttpError(404, "없는 분석입니다.")
        return job

    def a_new_get(self, g, q, b):
        j = self.get_job(g[0])
        return 200, {k: j[k] for k in ("id", "status", "text", "cwd", "result", "error")}

    def preview_text(self, job, picked, extra, note) -> str:
        if not isinstance(picked, list) or not all(isinstance(p, str) for p in picked):
            raise HttpError(400, "picked 형식이 맞지 않습니다.")
        clean = []
        for p in picked:
            rel, why = analysis.mention_path(job["cwd"], p)
            if why:
                raise HttpError(400, f"이 경로는 쓸 수 없습니다({why}): {p[:100]!r}")
            clean.append(rel)
        picked = clean
        if not isinstance(extra, dict):
            extra = {}
        is_git = self.git_inspect(job["cwd"])["isRepo"]
        return analysis.first_message(job["text"], picked, extra, note if isinstance(note, str) else "", is_git)

    def a_preview(self, g, q, b):
        job = self.get_job(g[0])
        try:
            extra = json.loads(q.get("extraAnswers", ["{}"])[0])
        except ValueError:
            raise HttpError(400, "extraAnswers 가 JSON 이 아닙니다.")
        return 200, {"message": self.preview_text(job, q.get("picked", []), extra, q.get("note", [""])[0])}

    def a_start(self, g, q, b):
        job = self.get_job(g[0])
        message = self.preview_text(job, b.get("picked") or [], b.get("extraAnswers") or {}, b.get("note") or "")
        with job["start_lock"]:  # 시작 버튼을 두 번 눌러도 세션은 하나만 뜬다
            sid = job.get("session_id")
            if sid is None:
                sid = self.manager.launch(job["cwd"], message, title=job["text"].split("\n", 1)[0])
                if sid is None:
                    raise HttpError(502, "claude 세션을 띄우지 못했습니다. " + platform_compat.CLAUDE_MISSING)
                job["session_id"] = sid
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and self.store.resolve_id(sid) == sid and sid.startswith("m-"):
            time.sleep(0.05)
        real = self.store.resolve_id(sid)
        self.refresh_git(real)
        return 202, {"id": real}

    # 폴더
    def folder_info(self, path) -> dict:
        path = platform_compat.clean_user_path(path) if isinstance(path, str) else ""
        if not path:
            return {"ok": False, "error": "경로가 비어 있습니다."}
        p = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(p):
            return {"ok": False, "error": "폴더가 아니거나 없습니다."}
        return {"ok": True, "path": p, "name": os.path.basename(p) or p, "isGit": self.git_inspect(p)["isRepo"]}

    def a_recent(self, g, q, b):
        with self.store.lock:
            paths = [p for p in self.store.folders if os.path.isdir(p)]
        return 200, [{"path": p, "name": os.path.basename(p) or p} for p in paths]

    def a_validate(self, g, q, b):
        info = self.folder_info(b.get("path"))
        if info["ok"]:
            self.store.add_folder(info["path"])
        return 200, info

    def a_fs(self, g, q, b):
        raw_root = platform_compat.clean_user_path(q.get("root", [""])[0])
        root = os.path.realpath(os.path.expanduser(raw_root))
        if not raw_root or not any(platform_compat.same_path(root, r) for r in self.known_roots()):
            raise HttpError(403, "고른 작업 폴더가 아닙니다.")
        rel = q.get("dir", [""])[0]
        target = os.path.join(root, rel)
        if not platform_compat.is_within(target, root) or not os.path.isdir(target):
            raise HttpError(403, "작업 폴더 밖이거나 폴더가 아닙니다.")
        entries = []
        try:
            names = sorted(os.listdir(target))
        except OSError:
            raise HttpError(403, "폴더를 읽을 수 없습니다.")
        for name in names[:2000]:
            full = os.path.join(target, name)
            if name == ".git" or not platform_compat.is_within(full, root):
                continue  # 링크가 작업 폴더 밖을 가리키면 보여 주지 않는다
            try:
                is_dir = os.path.isdir(full)
                size = 0 if is_dir else os.path.getsize(full)
            except OSError:
                continue
            entries.append({"name": name, "kind": "dir" if is_dir else "file", "size": size})
        entries.sort(key=lambda e: (e["kind"] != "dir", e["name"].lower()))
        return 200, {"root": root, "dir": rel.strip("/\\"), "entries": entries}


S = r"([^/]+)"
ROUTES = [
    ("GET", re.compile(r"/api/sessions"), App.a_sessions),
    ("GET", re.compile(rf"/api/sessions/{S}"), App.a_session),
    ("POST", re.compile(rf"/api/sessions/{S}/messages"), App.a_message),
    ("POST", re.compile(rf"/api/sessions/{S}/skills/{S}/run"), App.a_run),
    ("PUT", re.compile(rf"/api/sessions/{S}/skills/{S}/reservation"), App.a_reserve),
    ("DELETE", re.compile(rf"/api/sessions/{S}/skills/{S}/reservation"), App.a_unreserve),
    ("POST", re.compile(rf"/api/sessions/{S}/interrupt"), App.a_interrupt),
    ("GET", re.compile(rf"/api/requests/{S}"), App.a_request),
    ("POST", re.compile(rf"/api/requests/{S}/answer"), App.a_answer),
    ("POST", re.compile(r"/api/new"), App.a_new),
    ("GET", re.compile(rf"/api/new/{S}"), App.a_new_get),
    ("POST", re.compile(rf"/api/new/{S}/start"), App.a_start),
    ("GET", re.compile(rf"/api/new/{S}/preview"), App.a_preview),
    ("GET", re.compile(r"/api/folders/recent"), App.a_recent),
    ("POST", re.compile(r"/api/folders/validate"), App.a_validate),
    ("GET", re.compile(r"/api/fs"), App.a_fs),
]


class Handler(BaseHTTPRequestHandler):
    server_version = "HarnessConsole"
    app: App  # make_server 가 서브클래스에 붙인다

    def log_message(self, *args) -> None:
        pass

    def setup(self) -> None:
        self.timeout = self.app.request_timeout  # 요청을 느리게 보내며 스레드를 붙드는 연결을 끊는다
        super().setup()

    # ---- 응답 ----
    def send(self, status: int, body: bytes = b"", ctype: str = "application/json; charset=utf-8", headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, data) -> None:
        body = b"" if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send(status, body)

    def read_json(self, limit: int) -> dict:
        header = (self.headers.get("Content-Length") or "0").strip()
        if not header.isascii() or not header.isdigit():  # 음수·숫자 아님·부호가 붙은 값은 거부한다
            raise HttpError(400, "Content-Length 가 올바르지 않습니다.")
        length = int(header)
        if length > limit:
            raise HttpError(413, "요청 본문이 너무 큽니다.")
        try:
            raw = self.rfile.read(length) if length else b""
        except TimeoutError:
            raise HttpError(408, "요청을 제때 다 받지 못했습니다.")
        if len(raw) < length:
            raise HttpError(400, "요청 본문이 모자랍니다.")
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "JSON 이 아닙니다.")
        if not isinstance(data, dict):
            raise HttpError(400, "JSON 객체가 아닙니다.")
        return data

    # ---- 라우팅 ----
    def do_GET(self): self.route()
    def do_POST(self): self.route()
    def do_PUT(self): self.route()
    def do_DELETE(self): self.route()

    def route(self) -> None:
        try:
            self.dispatch()
        except HttpError as e:
            self.send_json(e.status, {"error": e.message})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            pass
        except Exception as e:  # 한 요청의 오류로 서버가 죽지 않게 한다
            try:
                self.send_json(500, {"error": f"서버 오류: {type(e).__name__}"})
            except OSError:
                pass

    def dispatch(self) -> None:
        app = self.app
        if self.headers.get("Host") not in app.hosts:  # DNS 리바인딩 차단
            raise HttpError(403, "허용되지 않은 Host 입니다.")
        url = urlsplit(self.path)
        path, query, method = url.path, parse_qs(url.query), self.command
        origin = self.headers.get("Origin")

        if path.startswith("/hooks/") or path in ("/api/open", "/api/shutdown"):
            # 쿠키 없이 받는 경로. 브라우저가 부른 것(Origin 이 있음)은 거부한다. 요청을 만들 수만 있고 답할 수 없다.
            if method != "POST":
                raise HttpError(405, "POST 만 받습니다.")
            if origin is not None:
                raise HttpError(403, "브라우저에서 부를 수 없는 경로입니다.")
            if path == "/api/open":
                self.read_json(API_BODY_LIMIT)
                return self.send_json(200, app.open_browser())
            if path == "/api/shutdown":
                self.read_json(API_BODY_LIMIT)
                self.send_json(200, {"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()  # 응답 뒤 정상 종료 절차(finally)를 탄다
                return None
            body = self.read_json(HOOK_BODY_LIMIT)
            self.connection.settimeout(None)  # 읽기가 끝났으니 승인 훅의 긴 대기를 소켓 timeout 이 끊지 않게 한다
            undo: list = []
            try:
                hook_ts = float(self.headers.get("X-Hook-Ts", ""))
            except ValueError:
                hook_ts = None
            status, data = app.hooks.handle(path[len("/hooks/"):], body, lambda: not platform_compat.socket_closed(self.connection), undo, hook_ts)
            try:
                self.send_json(status, data)
            except OSError:
                for fn in undo:  # 응답이 닿지 못했으면 Stop 의 예약 항목 같은 것을 되돌린다
                    fn()
                raise
            return

        if path == "/api/health" and method == "GET":
            return self.send_json(200, {"app": APP_NAME, "version": app.version})
        if path == "/auth" and method == "GET":
            return self.auth(query)

        if path.startswith("/api/"):
            if not app.cookie_ok(self.headers.get("Cookie")):
                raise HttpError(401, "인증이 필요합니다. /harness:open 으로 다시 여십시오.")
            if origin is not None and origin not in app.origins:
                raise HttpError(403, "다른 출처의 요청입니다.")
            if method != "GET" and not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                raise HttpError(415, "Content-Type 은 application/json 이어야 합니다.")
            if path == "/api/events" and method == "GET":
                return self.events()
            body = self.read_json(API_BODY_LIMIT) if method != "GET" else {}
            status, data = app.api(method, path, query, body)
            return self.send_json(status, data)

        if method != "GET":
            raise HttpError(405, "허용되지 않은 메서드입니다.")
        self.static(path)

    def auth(self, query) -> None:
        value = self.app.consume_token((query.get("t") or [""])[0])
        if value is None:
            return self.send(403, "링크가 만료됐거나 이미 썼습니다. /harness:open 을 다시 실행하십시오.".encode("utf-8"),
                             "text/plain; charset=utf-8")
        self.send(302, b"", headers={"Location": "/", "Set-Cookie": f"{COOKIE}={value}; HttpOnly; SameSite=Strict; Path=/; Max-Age={COOKIE_MAX_AGE}"})

    def static(self, path: str) -> None:
        app = self.app
        name = None
        if SPA_PATHS.match(path):
            name = "index.html"
        else:
            rest = path[len("/static"):] if path.startswith("/static/") else path
            if re.fullmatch(r"/[\w.-]+", rest):
                name = rest[1:]
        f = app.static_dir / name if name else None
        if not f or not f.is_file() or not platform_compat.is_within(f, app.static_dir):
            raise HttpError(404, "없는 페이지입니다.")
        ctype = STATIC_TYPES.get(f.suffix.lower()) or mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send(200, f.read_bytes(), ctype, {"Content-Security-Policy": CSP})

    def events(self) -> None:
        app = self.app
        q = app.store.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while not q.closed:  # 큐가 가득 차 끊긴 구독자는 연결을 닫아 브라우저가 다시 붙게 한다
                try:
                    kind, payload = q.get(timeout=HEARTBEAT)
                except queue.Empty:
                    if platform_compat.socket_closed(self.connection):
                        return
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                data = self.event_data(kind, payload)
                if data is not None:
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
        except (OSError, ValueError):
            pass
        finally:
            app.store.unsubscribe(q)

    def event_data(self, kind: str, payload: dict):
        app = self.app
        if kind == "session":
            s = app.store.get(payload["id"])
            return app.model_of(s) if s else None
        if kind == "request":
            r = app.store.get_request(payload["id"])
            return r.public() if r else None
        return payload


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = platform_compat.current_os() != "windows"  # Windows 의 SO_REUSEADDR 은 같은 포트를 두 번 열게 한다


def make_server(app: App, port: int | None = None) -> Server:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return Server(("127.0.0.1", app.port if port is None else port), handler)


def pid_file(state: Path) -> Path:
    return state / "server.pid"


def write_error_file(state: Path, reason: str) -> None:
    """서버가 못 뜬 이유를 한 줄로 남긴다(open.py 가 보여 준다). 토큰이나 경로 같은 민감 정보는 넣지 않는다."""
    try:
        state.mkdir(parents=True, exist_ok=True)
        (state / "server.err").write_text(" ".join(reason.split())[:300] + "\n", encoding="utf-8")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    port = platform_compat.port_from_env()
    state = platform_compat.state_dir()
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent)
    app = App(port, state, plugin_root, model=os.environ.get("HARNESS_CONSOLE_MODEL", ""))
    try:
        server = make_server(app)
    except OSError as e:
        reason = f"포트 {port} 를 열지 못했습니다: {type(e).__name__} {getattr(e, 'winerror', None) or e.errno or ''} {e.strerror or ''}".strip()
        print(reason, file=sys.stderr)
        write_error_file(state, reason)
        return 1
    state.mkdir(parents=True, exist_ok=True)
    pf = pid_file(state)
    pf.write_text(f"{os.getpid()}\n{port}\n", encoding="utf-8")

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        app.shutdown()
        try:
            pf.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
