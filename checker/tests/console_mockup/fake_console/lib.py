"""시안 대조용 시험 콘솔 도우미(기본 포트 4881, CONSOLE_CHECK_PORT 로 바꿈). 저장소 파일은 읽기만 하고, 가짜 저장소·상태는 임시 폴더에 만든다."""
from __future__ import annotations

import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
# 콘솔 코드를 읽어 올 저장소. 기본은 이 파일이 든 저장소이고, 다른 작업 폴더의 콘솔을 보려면 CONSOLE_CHECK_REPO.
REPO = Path(os.environ.get("CONSOLE_CHECK_REPO") or HERE.parents[3])
PLUGIN = REPO / "plugins" / "harness"
CONSOLE = PLUGIN / "console"
PORT = int(os.environ.get("CONSOLE_CHECK_PORT", "4881"))
BASE = f"http://127.0.0.1:{PORT}"
RUN = Path(os.environ.get("CONSOLE_CHECK_RUN") or Path(tempfile.gettempdir()) / f"console-mockup-check-{PORT}")
STATE = RUN / "state"
WORK = RUN / "work"
GH_STATE = RUN / "gh_state.json"
ANALYSIS = RUN / "analysis.json"
AUTH_URL = RUN / "auth_url.txt"
PIDFILE = RUN / "serve.pid"
LOG = RUN / "serve.log"
RUN.mkdir(parents=True, exist_ok=True)
LOGIN = "jaeheemin"


# ---------------------------------------------------------------- 폴더·git
def _rm_ro(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, onerror=_rm_ro)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-c", "user.name=tester", "-c", "user.email=t@example.com", "-c", "core.autocrlf=false", *args],
                          cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패: {done.stderr.strip()}")
    return done.stdout


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


SRS_HEAD = "# SRS(요구사항정의서)\n\n| ID | Title | Status | 다음 단계 |\n|---|---|---|---|\n"


def make_xlsx(path: Path, sheet: str, header: list[str], rows: list[list[str]]) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(header)
    for r in rows:
        ws.append(r)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def make_project(name: str, branch: str | None = None, forms: bool = True, push: bool = True) -> Path:
    """가짜 Project Repository. templates/·rules/·docs/ssot/SRS.md·.github/ssot-approvers 가 커밋돼 있고,
    origin(로컬 bare)이 있다. branch 를 주면 그 브랜치를 만들어 체크아웃한다(원격에도 올림)."""
    root = WORK / name
    origin = WORK / f"_origin_{name}.git"
    rmtree(root)
    rmtree(origin)
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    write(root / "rules" / "rules.yaml", "rules: []\n")
    write(root / "templates" / "README.md", "# 양식\n")
    if forms:
        make_xlsx(root / "templates" / "BW_Backlog List.xlsx", "Backlog", ["ID", "Title", "Status"], [])
    write(root / "docs" / "ssot" / "SRS.md", SRS_HEAD)
    write(root / ".github" / "ssot-approvers", f"{LOGIN}\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    if push:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
        git(root, "remote", "add", "origin", str(origin).replace("\\", "/"))
        git(root, "push", "-q", "-u", "origin", "main")
        git(root, "remote", "set-head", "origin", "main")
    if branch and branch != "main":
        git(root, "checkout", "-q", "-b", branch)
        if push:
            git(root, "push", "-q", "-u", "origin", branch)
    if push:  # 승인자 판정이 'GitHub 원격' 을 요구한다. 올린 뒤에 주소만 GitHub 모양으로 바꾼다(origin/* 기록은 남는다, fetch 는 안 됨)
        git(root, "remote", "set-url", "origin", "https://github.com/example/proj.git")
    return root


def add_req_row(root: Path, row: str = "| REQ-001 | 구매오더 조회 앱 | Open | 개발 |") -> None:
    p = root / "docs" / "ssot" / "SRS.md"
    p.write_text(p.read_text(encoding="utf-8") + row + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- gh 흉내(serve.py 가 읽는다)
def set_gh(prs: list[dict], login: str = LOGIN) -> None:
    GH_STATE.write_text(json.dumps({"login": login, "prs": prs}, ensure_ascii=False, indent=1), encoding="utf-8")


def pr(number: int, branch: str, state: str = "OPEN", title: str = "t", author: str = LOGIN, files: list[str] | None = None,
       checks: str = "pass") -> dict:
    rollup = {"pass": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
              "pending": [{"status": "IN_PROGRESS", "conclusion": ""}],
              "fail": [{"status": "COMPLETED", "conclusion": "FAILURE"}], "none": []}[checks]
    return {"number": number, "state": state, "url": f"https://github.com/example/proj/pull/{number}", "title": title,
            "headRefName": branch, "mergedAt": "2026-11-07T01:00:00Z" if state == "MERGED" else None,
            "statusCheckRollup": rollup, "files": [{"path": f} for f in (files or [])], "author": {"login": author},
            "isDraft": False, "headRefOid": f"oid{number}", "latestReviews": []}


# ---------------------------------------------------------------- 서버 수명
def health() -> bool:
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=2)
        c.request("GET", "/api/health")
        ok = c.getresponse().status == 200
        c.close()
        return ok
    except OSError:
        return False


class ConsoleUnavailable(RuntimeError):
    """시험 콘솔을 띄우거나 끌 수 없다(포트 사용 중, 서버 안 뜸 등). 검사 불능이다 - 통과도 위반도 아니다."""


PROTECTED_PORTS = (4873, 4874)  # 사용자·시험 콘솔 포트: 이 도구는 건드리지 않는다
TOKEN_FILE = RUN / "serve.token"


def _guard_port() -> None:
    if PORT in PROTECTED_PORTS:
        raise ConsoleUnavailable(f"포트 {PORT} 는 사용자·시험 콘솔이 쓰는 포트라 이 검사가 쓰지 않는다. CONSOLE_CHECK_PORT 로 다른 포트를 줘.")


def _cmdline(pid: int) -> str | None:
    """프로세스 명령줄. 알아내지 못하면 None."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout
        elif Path(f"/proc/{pid}/cmdline").exists():
            return Path(f"/proc/{pid}/cmdline").read_bytes().replace(bytes([0]), b" ").decode("utf-8", "replace")
        else:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=10).stdout
        return out.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _our_pid() -> int | None:
    """pid 파일의 프로세스가 이 도구가 띄운 서버(명령줄에 띄울 때 넘긴 토큰이 있음)일 때만 pid 를 돌려준다. 아니면 None."""
    try:
        pid = int(PIDFILE.read_text().split()[0])
        token = TOKEN_FILE.read_text().strip()
    except (OSError, ValueError, IndexError):
        return None
    cmd = _cmdline(pid)
    return pid if cmd and token and token in cmd and "serve.py" in cmd else None


def stop_server() -> None:
    """우리가 띄운 서버만 끈다. 포트를 쓰는 게 우리 서버가 아니면(pid 가 없거나 명령줄이 안 맞으면) 건드리지 않고 ConsoleUnavailable."""
    _guard_port()
    if not health():
        PIDFILE.unlink(missing_ok=True)
        return
    pid = _our_pid()
    if pid is None:
        raise ConsoleUnavailable(f"포트 {PORT} 를 우리가 띄운 서버가 아닌 프로세스가 쓰고 있다 - 건드리지 않고 멈춘다.")
    try:
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=5)
        c.request("POST", "/api/shutdown", body=b"{}", headers={"Content-Type": "application/json"})
        c.getresponse().read()
        c.close()
    except OSError:
        pass
    for _ in range(40):
        if not health():
            break
        time.sleep(0.25)
    if health():  # 마지막 수단: 방금 확인한 우리 pid 만 끈다
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            os.kill(pid, 15)
        time.sleep(1)
    PIDFILE.unlink(missing_ok=True)


def start_server(first_run_done: bool = True) -> None:
    """깨끗한 상태 폴더로 서버를 새로 띄운다. 이미 이 포트에 우리 서버면 먼저 끈다."""
    stop_server()
    if health():
        raise ConsoleUnavailable(f"포트 {PORT} 를 다른 프로세스가 쓰고 있다 - 건드리지 않고 멈춘다.")
    rmtree(STATE)
    STATE.mkdir(parents=True)
    if first_run_done:
        (STATE / "first-run.json").write_text("{}", encoding="utf-8")
    AUTH_URL.unlink(missing_ok=True)
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(PORT), CLAUDE_PLUGIN_DATA=str(STATE), PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8")
    env.pop("HARNESS_NO_SCAFFOLD_HINT", None)
    env.update(CONSOLE_CHECK_RUN=str(RUN), CONSOLE_CHECK_REPO=str(REPO))
    detach = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    log = open(LOG, "wb")
    token = os.urandom(8).hex()  # 띄운 서버의 명령줄에 넣어 두고, 끌 때 같은 토큰이 명령줄에 있는지로 우리 서버임을 확인한다
    TOKEN_FILE.write_text(token, encoding="utf-8")
    subprocess.Popen([sys.executable, "-B", str(HERE / "serve.py"), f"--run-token={token}"], env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     close_fds=True, **detach)
    for _ in range(80):
        if health():
            return
        time.sleep(0.25)
    raise ConsoleUnavailable("서버가 뜨지 않았다: " + LOG.read_text(encoding="utf-8", errors="replace")[-800:])


# ---------------------------------------------------------------- API 호출
class Api:
    def __init__(self):
        self.cookie = ""

    def call(self, method: str, path: str, body=None, cookie: bool = True, headers: dict | None = None, timeout: float = 60):
        h = {"Host": f"127.0.0.1:{PORT}"}
        if cookie and self.cookie:
            h["Cookie"] = f"harness_console={self.cookie}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("Content-Length", str(len(data or b"")))
        c.endheaders(data or b"")
        r = c.getresponse()
        raw = r.read()
        c.close()
        text = raw.decode("utf-8", "replace")
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            parsed = text
        return r.status, parsed, r

    def login(self) -> "Api":
        for _ in range(20):
            AUTH_URL.unlink(missing_ok=True)
            st, _, _ = self.call("POST", "/api/open", {}, cookie=False)
            if st == 200 and AUTH_URL.exists():
                break
            time.sleep(0.2)
        token = AUTH_URL.read_text(encoding="utf-8").split("t=")[1].strip()
        st, _, r = self.call("GET", f"/auth?t={token}", cookie=False)
        assert st == 302, f"/auth 실패 {st}"
        self.cookie = r.getheader("Set-Cookie").split(";")[0].split("=", 1)[1]
        return self

    def get(self, path):
        st, d, _ = self.call("GET", path)
        return st, d

    def post(self, path, body=None):
        st, d, _ = self.call("POST", path, body if body is not None else {})
        return st, d

    def put(self, path, body):
        st, d, _ = self.call("PUT", path, body)
        return st, d

    def hook(self, name: str, body: dict, ts=None):
        st, d, _ = self.call("POST", f"/hooks/{name}", body, cookie=False,
                             headers={"X-Hook-Ts": repr(ts)} if ts is not None else None)
        return st, d

    def hook_async(self, name: str, body: dict) -> dict:
        holder: dict = {}

        def run():
            holder["r"] = self.hook(name, body)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        holder["t"] = t
        return holder

    def event(self, sid: str, cwd: str, name: str, **kw):
        return self.hook("event", dict({"session_id": sid, "cwd": cwd, "hook_event_name": name}, **kw))

    def stop(self, sid: str, cwd: str, text: str):
        return self.hook("stop", {"session_id": sid, "cwd": cwd, "hook_event_name": "Stop", "last_assistant_message": text})


def new_auth_url() -> str:
    """브라우저용 일회용 로그인 주소. 열면 쿠키가 생긴다(5분 안에 쓸 것)."""
    AUTH_URL.unlink(missing_ok=True)
    st, _, _ = Api().call("POST", "/api/open", {}, cookie=False)
    assert st == 200
    for _ in range(20):
        if AUTH_URL.exists():
            return AUTH_URL.read_text(encoding="utf-8").strip()
        time.sleep(0.1)
    raise ConsoleUnavailable("로그인 주소를 못 받았다")


def transcript(sid: str, tokens: int = 120_000, model: str = "claude-opus-4-7") -> str:
    """기억 % 계산용 대화 기록 jsonl. 마지막 assistant 줄의 usage 만 읽는다."""
    p = STATE / f"transcript-{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = {"type": "assistant", "message": {"model": model, "role": "assistant", "content": [{"type": "text", "text": "ok"}],
                                              "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000,
                                                        "cache_read_input_tokens": tokens - 1010, "output_tokens": 50}}}
    p.write_text(json.dumps(line) + "\n", encoding="utf-8")
    return str(p)


def wait_for(fn, timeout: float = 20, step: float = 0.2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(step)
    return fn()


# ---------------------------------------------------------------- 갈래 세션(훅 세션)
def hook_flow_session(api: Api, sid: str, cwd: Path, prompt: str, flow: str, skill: str, write_file: str | None,
                      report: str, tokens: int = 120_000, stop: bool = True, extra_files: list[str] | None = None) -> dict:
    """UserPromptSubmit -> 갈래 지정 -> Skill -> (파일 쓰기) -> Stop -> 갈래 새로 읽기. 세션 JSON 을 돌려준다."""
    c = str(cwd)
    tp = transcript(sid, tokens)
    api.event(sid, c, "SessionStart", model="claude-opus-4-7", transcript_path=tp)
    api.event(sid, c, "UserPromptSubmit", prompt=prompt, model="claude-opus-4-7", transcript_path=tp)
    st, d = api.put(f"/api/sessions/{sid}/flow", {"flowId": flow, "reason": "시안 대조용으로 지정"})
    assert st == 200, f"갈래 지정 실패 {st} {d}"
    api.event(sid, c, "PreToolUse", tool_name="Skill", tool_input={"skill": f"harness:{skill}"})
    for wf in ([write_file] if write_file else []) + list(extra_files or []):  # 세션이 쓴 파일마다 Write 한 쌍(산출물 목록에 오른다)
        fp = str(cwd / wf)
        api.event(sid, c, "PreToolUse", tool_name="Write", tool_input={"file_path": fp, "content": "x"})
        api.event(sid, c, "PostToolUse", tool_name="Write", tool_input={"file_path": fp, "content": "x"}, tool_response="ok")
    if stop:
        api.stop(sid, c, report)
    wait_for(lambda: api.get(f"/api/sessions/{sid}")[1].get("branch"), 15)  # git 정보는 백그라운드로 읽힌다: 브랜치가 채워진 뒤에 판정해야 PR 을 찾는다
    time.sleep(0.5)
    api.post(f"/api/sessions/{sid}/flow/refresh")
    time.sleep(0.5)
    return api.get(f"/api/sessions/{sid}")[1]


def show(title: str, value) -> None:
    print(f"[{title}] " + (json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value))
