"""HTTP 서버, 라우팅, 인증, SSE, 갈래·인계(web-console.md §3, §4, §7a-7c, §8)."""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import analysis
import devready
import docfiles
import flows
import gitstate
import handoff
import platform_compat
import trouble
from hooks_api import ASK_DEFAULT, ASK_LEVELS, Hooks, permission_reply, question_reply
from managed import (EFFORT_OPTIONS, EFFORT_VALUES, MODEL_NAME, MODEL_OPTIONS, PERMISSION_OPTIONS,  # noqa: F401
                     PERMISSION_VALUES, Manager)
from standards_scan import customer_forms, has_standard_folder  # noqa: F401
from store import (CHECK_SKIPPED, MAX_PENDING_STOP, START_CHECK_IDS, Store, can_send, display_title, mark_check, public_session,
                   remember_touched, set_baseline)

APP_NAME = "harness-console"
COOKIE = "harness_console"
COOKIE_MAX_AGE = 30 * 24 * 3600
REQUEST_TIMEOUT = 30.0  # 요청을 읽는 동안의 소켓 timeout. 본문을 다 읽은 훅 연결은 timeout 을 풀고 오래 기다린다
GAP_NOTICE_SECONDS = 1800.0  # git 상태를 못 읽은 일을 만든 문서 목록에서 알리는 시간(그 뒤엔 사라진다)
TOKEN_TTL = 60.0
API_BODY_LIMIT = 1 << 20
HOOK_BODY_LIMIT = 32 << 20
DRAIN_LIMIT = 1 << 20   # 오류 응답 전에 버려 읽는 본문의 상한
DRAIN_SECONDS = 1.0     # 버려 읽는 데 쓰는 총 시간
HEARTBEAT = 10.0
CACHE_SECONDS = 60.0  # 승인자 판정과 승인 대기 PR 목록은 gh 를 자주 부르지 않게 이만큼 기억한다
MAX_ADVANCE_ROUNDS = 4  # 갈래 진행 판정에서 증거를 읽고 다시 판정하는 최대 횟수(증거 종류가 둘뿐이라 넉넉하다)
COND_YES, COND_NO, COND_UNKNOWN = "yes", "no", "unknown"
LOADING_REASON = "GitHub 에서 읽는 중입니다."
HIDDEN_SKILLS = {"update", "scaffold", "open"}
# 모델 이름 형식·에포트·권한 모드 허용 값은 managed.py 에 있다(띄울 때도 한 번 더 검사한다).
# @ 파일 찾기 한도와 건너뛰는 큰 폴더
FILE_RESULT_LIMIT = 50
FILE_SCAN_LIMIT = 20000
FILE_QUERY_MAX = 200
# 플러그인 다시 불러오기·다음 갈래 넘기기의 기다림(초). 폴링 간격은 App.wait_poll 이다.
RELOAD_QUEUE_WAIT = 600.0   # 턴이 끝나기를 기다렸다가 다시 불러온다
RELOAD_ALL_WORKERS = 8
HANDOFF_IDLE_WAIT = 600.0   # 인계를 보내기 전에 지금 턴이 끝나기를 기다리는 시간
HANDOFF_WAIT = 600.0        # 인계 턴이 끝나기를 기다리는 시간(최대 10분)
NEW_SESSION_ID_WAIT = 8.0   # 새 세션이 실제 id 를 얻을 때까지
NEW_SESSION_INIT_WAIT = 60.0  # 새 세션이 init 이벤트를 낼 때까지(이 뒤에야 이전 세션을 닫는다)
MAX_NEXT_PROMPT = 4000      # 새 세션 첫 메시지로 보낼 인계 프롬프트의 최대 글자 수
MAX_NEXT_IDS = 20           # 다음 갈래로 넘길 요구사항 번호(REQ-xxx) 수
REQ_ID = re.compile(r"REQ-\d{1,6}")
SYSTEM_TYPE = re.compile(r"^system_type\s*:\s*([^#\r\n]*)", re.MULTILINE)


def read_system_type(root: str) -> str:
    """env/adt-tiers.yaml 의 최상위 system_type 값. 파일이나 키가 없거나 읽지 못하면 빈 문자열(지어내지 않는다)."""
    try:
        path = os.path.join(root, "env", "adt-tiers.yaml")
        if os.path.getsize(path) > 1 << 20:
            return ""
        with open(path, encoding="utf-8") as fh:
            m = SYSTEM_TYPE.search(fh.read())
    except (OSError, UnicodeDecodeError):
        return ""
    return m.group(1).strip().strip("'\"")[:60] if m else ""


MAX_JOBS = 50
JOB_ACTIVE = ("handoff", "starting")
WAIT_POLL = 0.2
HANDOFF_GUIDE = ("터미널 세션에는 콘솔이 /harness:handoff 를 보낼 수 없습니다. 터미널에서 /harness:handoff 를 실행해 인계 프롬프트를 받고, "
                 "콘솔의 새 작업으로 시작하십시오.")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache"}
# Windows 레지스트리의 MIME 설정에 영향받지 않게 직접 매핑한다(CSP 가 script 를 막는 일 방지).
STATIC_TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
                ".svg": "image/svg+xml", ".json": "application/json", ".map": "application/json", ".woff2": "font/woff2"}
FIRST_RUN_FILE = "first-run.json"  # 이 PC 에서 첫 화면(시작하기)을 이미 본 표시. 상태 폴더 아래, 브라우저와 무관
SEEN_VERSION_FILE = "seen-version.json"  # 바뀐 점 안내를 마지막으로 본 판. 상태 폴더 아래, 브라우저와 무관
WHATS_NEW_FILE = "whats_new.json"  # 판별 바뀐 점(플러그인 console 폴더). 판을 올리는 PR 이 줄을 더한다
LAST_FOLDER_FILE ="last-folder.json"  # 새 작업에서 마지막으로 시작한 작업 폴더. 상태 폴더 아래, 브라우저와 무관
NOTIFY_FILE = "notify.json"  # 브라우저 알림 설정(내 차례·막힘·끝남). 상태 폴더 아래, 브라우저와 무관
NOTIFY_KEYS = ("turn", "blocked", "done")
ASK_UNREADABLE = "설정을 읽지 못해 모든 명령마다 물어"
ASK_FILE = "ask.json"  # 설정 "AI가 묻는 범위"(꼭 필요할 때만 · 문서를 바꿀 때마다 · 모든 명령마다). 상태 폴더 아래, 브라우저와 무관
FOLDER_INTRO_FILE = "folder-intro.json"  # 준비 안 된 폴더의 "프로젝트 준비" 안내를 이미 보여 준 폴더들. 상태 폴더 아래, 브라우저와 무관
FOLDER_INTRO_MAX = 200  # 넘치면 오래된 것부터 잊는다
CHECK_RUN_TIMEOUT = 15.0         # 시작 점검의 gh 호출 제한 시간(초)
GH_LOGIN_FAIL = ("gh auth login", "not logged in", "authentication", "bad credentials", "401", "no oauth token")


def judge_github(rc: int, out: str, installed: bool) -> dict:
    """`gh api user` 결과로 GitHub 연결을 판정한다. ok / fail(막는 문제) / unknown(확인 못 함).
    gh 가 없거나 로그인이 안 된 것만 fail 이고, 시간 초과·네트워크 오류는 원인을 몰라 unknown 이다."""
    text = (out or "").strip()
    if rc == 0 and text:
        return {"state": "ok", "detail": text.splitlines()[0][:80]}
    if not installed:
        return {"state": "fail", "detail": "gh 가 없어", "fix": "gh(GitHub CLI)를 설치한 뒤 터미널에서 gh auth login 을 해 줘."}
    if rc != 0 and any(k in text.lower() for k in GH_LOGIN_FAIL):
        return {"state": "fail", "detail": "로그인이 안 돼 있어", "fix": "터미널에서 gh auth login 을 하고 다시 점검해 줘."}
    return {"state": "unknown", "detail": "확인 못 함 · 시간 안에 읽지 못했어"}


def judge_claude(rc: int, out: str, found: bool) -> dict:
    """`claude auth status --json`(Claude Code CLI 의 공식 로그인 상태 명령) 결과로 로그인을 판정한다.
    loggedIn true = ok, false = fail(막는 문제, claude auth login 안내). 명령을 못 찾았거나 JSON 을 못 읽으면 unknown —
    못 읽은 것을 로그인 안 됨으로 뭉개지 않는다. 이메일 같은 계정 정보는 화면에 옮기지 않는다."""
    if not found:
        return {"state": "unknown", "detail": "확인 못 함 · claude 명령을 찾지 못했어"}
    text = out or ""
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if 0 <= start < end else None  # 로그인 안 됨이면 종료코드가 0 이 아닐 수 있어 종료코드로 거르지 않는다
    except ValueError:
        data = None
    logged = data.get("loggedIn") if isinstance(data, dict) else None
    if logged is True:
        how = {"claude.ai": "Claude 계정"}.get(data.get("authMethod"), "")
        return {"state": "ok", "detail": "로그인됨" + (" · " + how if how else "")}
    if logged is False:
        return {"state": "fail", "detail": "로그인이 안 돼 있어", "fix": "터미널에서 claude auth login 을 하고 다시 점검해 줘."}
    return {"state": "unknown", "detail": "확인 못 함 · 로그인 상태를 읽지 못했어"}


def parse_version(text) -> tuple[int, ...] | None:
    return tuple(int(p) for p in text.split(".")) if isinstance(text, str) and re.fullmatch(r"[0-9]+(\.[0-9]+)*", text) else None


def judge_version(loaded: str, latest: str | None) -> dict:
    """실린 판과 원격 최신 판 비교. old 는 막지 않는 문제, 원격을 못 읽으면 unknown(문제로 치지 않는다)."""
    mine, newest = parse_version(loaded), parse_version(latest)
    if mine is None:
        return {"state": "unknown", "detail": "확인 못 함 · 실린 판을 읽지 못했어"}
    if newest is None:
        return {"state": "unknown", "detail": loaded + " · 최신 판은 확인 못 함"}
    if mine < newest:
        return {"state": "old", "detail": f"{loaded} → 새 판 {latest}", "latest": latest,
                "fix": "터미널에서 /harness:update 를 하면 돼."}
    return {"state": "ok", "detail": loaded}


SPA_PATHS = re.compile(r"^/(s/[^/]+|r/[^/]+|new|settings|docs|troubles(/new|/[^/]+/[^/]+/\d+)?)?$")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


class Raw:
    """JSON 이 아닌 본문으로 답하는 API 의 반환값(이미지 원본)."""

    def __init__(self, body: bytes, ctype: str, headers: dict | None = None):
        self.body, self.ctype, self.headers = body, ctype, headers or {}


def plugin_info(plugin_root: Path) -> tuple[str, str]:
    try:
        meta = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        return str(meta.get("name", "harness")), str(meta.get("version", ""))
    except (OSError, ValueError):
        return "harness", ""


def load_skill_info(plugin_root: Path) -> list[dict]:
    """skills/*/SKILL.md 의 frontmatter name·description 에서 읽는다. update, scaffold, open 은 버튼으로 내지 않는다."""
    items = []
    for f in sorted((plugin_root / "skills").glob("*/SKILL.md")):
        name, description = f.parent.name, ""
        try:
            head = f.read_text(encoding="utf-8").split("---", 2)
            for line in head[1].splitlines() if len(head) > 2 else []:
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip("\"'")
        except OSError as e:
            print(f"스킬 파일을 읽지 못했습니다({f.name}): {e}", file=sys.stderr)
        if name not in HIDDEN_SKILLS:
            items.append({"name": name, "description": description})
    return items


def load_skills(plugin_root: Path) -> list[str]:
    return [i["name"] for i in load_skill_info(plugin_root)]


class App:
    def __init__(self, port: int, state_dir: Path | None, plugin_root: Path, clock=time.time,
                 browser_open=webbrowser.open, claude_cmd=None, git_inspect=gitstate.inspect,
                 model: str = "", poll: float = 0.5, question_wait: float = 300.0, sync_spawn: bool = False,
                 popen=subprocess.Popen, request_timeout: float = REQUEST_TIMEOUT, folder_picker=platform_compat.pick_folder,
                 effort: str = "", flows_path=None, run=None, opener=None, wait_poll: float = WAIT_POLL):
        self.port = port
        self.default_model = model
        self.default_effort = effort if effort in EFFORT_VALUES else ""
        self.folder_picker = folder_picker
        self.pick_lock = threading.Lock()  # 폴더 선택 창은 한 번에 하나만 연다
        self.request_timeout = request_timeout
        self.clock = clock
        self.plugin_root = Path(plugin_root)
        self.plugin_name, self.version = plugin_info(self.plugin_root)
        self.skill_info = load_skill_info(self.plugin_root)
        self.skills = [i["name"] for i in self.skill_info]
        self.run = run or gitstate.gh_runner()  # gh·git 조회(갈래 진행·승인자 판정). 시험이 바꿔 끼운다
        self.slow_run = run or (lambda args, cwd: gitstate.run_command(args, cwd, gitstate.SLOW_GIT_TIMEOUT, merge_stderr=True))
        self.opener = opener or platform_compat.open_path  # 파일 열기·위치 보기. 시험이 바꿔 끼운다
        self.check_run = run or (lambda args, cwd: gitstate.run_command(args, cwd, CHECK_RUN_TIMEOUT, merge_stderr=True))  # 시작 점검용(오류 글까지 본다)
        self.gh_installed = lambda: shutil.which("gh") is not None
        self.remote_latest = self.read_remote_latest  # 원격 최신 판. 시험이 바꿔 끼운다
        self.last_folder_mem = None  # 상태 폴더가 없는 실행(시험)에서만 쓴다
        self.notify_mem = None  # 알림 설정도 같다
        self.ask_mem = None  # 묻는 범위 설정도 같다
        self.seen_version: str | None = None  # 상태 폴더가 없는 실행(시험)에서만 메모리에 둔다
        self.first_run_seen = False# 상태 폴더가 없는 실행(시험)에서만 메모리에 둔다
        self.folder_intro_mem: list = []  # 상태 폴더가 없는 실행(시험)에서만 쓴다
        self.intro_lock = threading.Lock()
        self.wait_poll = wait_poll
        self.jobs: dict[str, dict] = {}  # 다음 갈래 넘기기 작업(메모리에만 둔다)
        self.reload_queue: set[str] = set()  # 턴이 끝나기를 기다리는 다시 불러오기
        self.cache: dict = {}
        self.last: dict = {}      # 마지막으로 읽은 값(못 읽은 것 포함). 새로 읽는 동안 이전 값으로 보여 준다
        self.inflight: dict = {}  # 지금 계산 중인 key -> Event
        self.flow_data, self.flow_error = self.load_flows(flows_path)
        self.browser_open = browser_open
        self.git_inspect = git_inspect
        self.sync_spawn = sync_spawn
        self.static_dir = Path(__file__).resolve().parent / "static"
        self.store = Store(state_dir, clock)
        self.store.flow_data = self.flow_data
        claude_cmd = claude_cmd or platform_compat.find_claude
        self.claude_cmd = claude_cmd  # 시작 점검의 로그인 확인(claude auth status)도 세션을 띄우는 것과 같은 claude 를 쓴다
        self.manager = Manager(self.store, claude_cmd, str(self.plugin_root), model=model, popen=popen, effort=self.default_effort)
        self.analyses = analysis.Analyses(claude_cmd, model=model, spawn=self.spawn, effort=self.default_effort,
                                          flows=self.flow_catalog())
        self.hooks = Hooks(self.store, clock, poll, question_wait, refresh_git=self.refresh_git, ask_level=self.read_ask)
        self.manager.auto_allowed = self.hooks.auto_allowed  # 콘솔 세션의 can_use_tool 요청도 같은 판정을 쓴다
        self.manager.risk_of = self.hooks.risk_of
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
            try:
                seen, why = gitstate.status_paths(self.run, s["cwd"])  # 커밋 전에 만든 파일을 쌓아 둔다(만든 문서 목록용)
            except Exception as e:
                seen, why = [], f"git 상태를 읽다 오류가 났습니다({type(e).__name__})."
            with self.store.lock:
                if why:  # 못 읽은 동안 커밋된 파일은 목록에서 빠질 수 있다. 빈 목록을 '바뀐 것 없음' 으로 읽지 않게 시각과 함께 표시를 남긴다
                    s["touchedGap"] = {"reason": why, "at": self.store.clock()}
                else:
                    set_baseline(s, seen)  # 처음 본 때 이미 바뀌어 있던 파일은 이 세션 것으로 치지 않는다
                    remember_touched(s, seen, from_status=True)
                s["repo"], s["branch"] = info["repo"], info["branch"]
                s["turn"] = {"skill": info["skill"], "unknown": info["unknown"]}
                if info["isRepo"]:
                    s["changedFiles"] = info["changedFiles"]
            self.advance_flow(s, info)
            self.store.touch(s)

        self.spawn(work)

    # ---- 갈래(플러그인의 workflow.json) ----
    def load_flows(self, path) -> tuple[dict | None, str]:
        """데이터를 읽고 모든 스킬이 skills/ 에 있는지, 단계마다 근거 문장이 실제 파일에 있는지 본다.
        틀리면 갈래 기능을 끄고 사유를 남긴다(콘솔 전체는 계속 뜬다)."""
        data, error = flows.load(path or flows.DATA_FILE)
        if data is not None:
            names = {f.parent.name for f in (self.plugin_root / "skills").glob("*/SKILL.md")}
            problems = flows.validate(data, names)  # 근거 문장은 이 콘솔이 들어 있는 플러그인의 파일에서 찾는다
            if problems:
                data, error = None, "갈래 데이터가 맞지 않습니다: " + "; ".join(problems[:5])
        if error:
            print(error, file=sys.stderr)
        return data, error

    def flow_catalog(self) -> dict:
        return {f["id"]: {"name": f.get("name", f["id"]), "description": f.get("description", "")}
                for f in (self.flow_data or {}).get("flows", [])}

    def require_flows(self) -> dict:
        if self.flow_data is None:
            raise HttpError(503, self.flow_error or "갈래 데이터를 쓸 수 없습니다.")
        return self.flow_data

    def runnable_skills(self) -> set[str]:
        """버튼에 안 내는 스킬(scaffold, update)도 갈래·도구 데이터에 있으면 실행할 수 있다."""
        extra = (flows.flow_skills(self.flow_data) | flows.tool_skills(self.flow_data)) if self.flow_data else set()
        return set(self.skills) | extra

    def cached(self, key, fn, wait: bool = True):
        """fn(gh·git 호출) 결과를 CACHE_SECONDS 기억한다. 같은 key 는 동시에 한 번만 계산한다(single-flight).
        wait=False(요청 스레드)면 계산이 끝나기를 기다리지 않는다: 계산은 백그라운드에서 하고, 지금은 이전 값(loading 표시)
        또는 읽는 중 값을 즉시 돌려준다. 잠금은 맵을 만질 때만 쥐고 fn 은 잠금 밖에서 부른다."""
        now = self.clock()
        with self.lock:
            hit = self.cache.get(key)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1]
            done = self.inflight.get(key)
            owner = done is None
            if owner:
                done = self.inflight[key] = threading.Event()

        def compute():
            try:
                value = fn()
                with self.lock:
                    self.last[key] = value
                    if value.get("state") != COND_UNKNOWN:  # 못 읽은 결과는 기억하지 않는다(화면에 보여 주려고 last 에만 둔다)
                        self.cache[key] = (now, value)
            finally:
                with self.lock:
                    self.inflight.pop(key, None)
                done.set()

        if wait:
            if owner:
                compute()
            else:
                done.wait()
        elif owner:
            self.spawn(compute)
        with self.lock:
            value = self.last.get(key)
            running = key in self.inflight
        if value is None:
            return {"state": COND_UNKNOWN, "reason": LOADING_REASON, "login": "", "items": [], "loading": True}
        return dict(value, loading=True) if running else value

    def cond_state(self, name: str, cwd: str, wait: bool = True) -> dict:
        """조건 하나의 판정. {"state": yes/no/unknown, "reason", "label"}. 못 읽으면 unknown 이고 없음(no)으로 두지 않는다.
        wait=False 는 gh 결과를 기다리지 않는다(읽는 중이면 unknown + loading)."""
        spec = self.require_flows()["conditions"][name]
        label = spec.get("label", name)
        if spec["type"] == "paths":
            root, failed = gitstate.repo_root_checked(self.run, cwd)
            if failed:
                return {"state": COND_UNKNOWN, "label": label, "reason": "git 을 실행하지 못해 " + ", ".join(spec["paths"]) + " 가 있는지 확인하지 못했습니다."}
            root = root or cwd
            names = ", ".join(spec["paths"])
            exempt = spec.get("exemptFile")  # 플러그인 저장소처럼 Project Repository 가 아닌 곳은 준비 여부를 따지지 않는다(session-start-sync.sh 와 같다)
            if (exempt and os.path.isfile(os.path.join(root, *exempt.split("/")))) or os.environ.get("HARNESS_NO_SCAFFOLD_HINT") == "1":
                ready, why_ready = True, f"Project Repository 가 아니라서({exempt} 가 있거나 HARNESS_NO_SCAFFOLD_HINT=1) {names} 를 따지지 않습니다."
            else:
                ready = has_standard_folder(root, spec["paths"], int(spec.get("searchDepth", 0)))
                why_ready = "" if ready else f"{names} 를 함께 가진 폴더가 없습니다."
            holds = (not ready) if spec.get("negate") else ready  # negate: 준비가 안 됐을 때 참
            return {"state": COND_YES if holds else COND_NO, "label": label, "reason": "" if holds else (why_ready or f"{names} 를 함께 가진 폴더가 있습니다.")}
        if spec["type"] == "file":
            root, failed = gitstate.repo_root_checked(self.run, cwd)
            if failed:  # git 을 실행하지 못했다 = 파일이 없다는 뜻이 아니다
                return {"state": COND_UNKNOWN, "label": label, "reason": f"git 을 실행하지 못해 {spec['path']} 이 있는지 확인하지 못했습니다."}
            root = root or cwd
            found = os.path.isfile(os.path.join(root, *spec["path"].split("/")))
            return {"state": COND_YES if found else COND_NO, "label": label, "reason": "" if found else f"{spec['path']} 이 없습니다."}
        key = ("approver", os.path.normcase(os.path.realpath(cwd)))
        got = self.cached(key, lambda: gitstate.approver_state(self.run, cwd, spec["file"], spec.get("whenNoFile", gitstate.WHEN_NO_FILE_ADMIN)), wait)
        out = {"state": got["state"], "label": label, "reason": got["reason"]}
        if got.get("loading"):
            out["loading"] = True
        return out

    def cond_fn(self, cwd: str, wait: bool = True):
        return lambda name: {COND_YES: True, COND_NO: False}.get(self.cond_state(name, cwd, wait)["state"])

    def cond_snapshot(self, cwd: str, state: dict | None = None, flow: dict | None = None):
        """갈래 상태·정의가 쓰는 조건(onlyIf)을 지금 읽어 둔 값으로 답하는 함수. git·gh 는 여기서만 부르므로 store.lock 밖에서 만든다.
        읽어 둔 적 없는 이름은 None(판정 불능)이다."""
        steps = (state or {}).get("steps") or (flow or {}).get("steps") or []
        values = {name: self.cond_fn(cwd)(name) for name in {st["onlyIf"] for st in steps if st.get("onlyIf")}}
        return lambda name: values.get(name)

    def advance_flow(self, s: dict, info: dict | None = None) -> None:
        """갈래의 지금 단계가 끝났는지 git·gh 증거로 판정한다. gh 는 잠금 밖에서 부르고(느리다), 증거를 읽을 때마다 다시 판정한다."""
        state = s.get("flowState")
        if not state or state["finished"] or not s["cwd"] or self.flow_data is None:
            return
        cwd, memo = s["cwd"], {}
        cond = self.cond_snapshot(cwd, state)
        for _ in range(MAX_ADVANCE_ROUNDS):
            missing: set[str] = set()

            def fetch(kind):
                if kind in memo:
                    return memo[kind]
                missing.add(kind)
                return None

            with self.store.lock:
                flows.evaluate(state, fetch, cond, self.clock())
            if not missing:
                break
            for kind in missing:
                memo[kind] = self.read_evidence(s, kind, info)
        if state["finished"] and state.get("next") is None:
            flow = flows.flow_def(self.flow_data, state["id"])
            state["next"] = flows.compute_next(self.flow_data, flow, gitstate.repo_root(self.run, cwd) or cwd) if flow else None

    def read_evidence(self, s: dict, kind: str, info: dict | None) -> dict:
        state = s["flowState"]
        if kind == "changes":
            got = info if info is not None else self.git_inspect(s["cwd"])
            if not got["isRepo"]:
                return {"state": "unknown", "reason": "git 저장소가 아니어서 변경을 확인하지 못했습니다."}
            return {"state": "ok", "value": bool(got["changedFiles"] or got.get("ahead"))}
        if kind == "branch":
            got = info if info is not None else self.git_inspect(s["cwd"])
            if not got["isRepo"]:
                return {"state": "unknown", "reason": "git 저장소가 아니어서 브랜치를 확인하지 못했습니다."}
            return {"state": "ok", "value": not got.get("onBase", False)}
        branch = (info or {}).get("branch") or s["branch"]
        return gitstate.pr_status(self.run, s["cwd"], branch, state.get("prNumber"))

    def assign_flow(self, s: dict, fid, reason: str) -> None:
        data = self.require_flows()
        flow = flows.flow_def(data, fid)
        if flow is None:
            raise HttpError(400, "없는 갈래입니다.")
        if flow.get("requires") and self.cond_fn(s["cwd"])(flow["requires"]) is False:
            raise HttpError(409, f"이 폴더에서는 쓸 수 없는 갈래입니다: {data['conditions'][flow['requires']].get('label', flow['requires'])}")
        cond = self.cond_snapshot(s["cwd"], flow=flow)  # git·gh 는 잠금 밖에서 읽는다
        with self.store.lock:
            s["flowState"] = flows.new_state(flow, reason, self.clock(), cond)
            self.store.add_log(s, f"갈래 지정: {flow['name']}")
        self.store.touch(s)
        self.refresh_git(s["id"])

    def check_flow_order(self, s: dict, skill: str) -> None:
        """갈래가 있는 세션은 지금 단계의 스킬(과 도구)만 실행할 수 있다. 도구는 언제나 허용한다."""
        if self.flow_data is not None and skill in flows.tool_skills(self.flow_data):
            return
        allowed = flows.allowed_skills(s)
        if allowed is None or skill in allowed:
            return
        cur = flows.current(s.get("flowState"))
        where = f"지금 단계는 '{cur['name']}' 입니다." if cur else "이 갈래는 이미 끝났습니다."
        raise HttpError(409, f"갈래 순서에 맞지 않는 스킬입니다. {where} 단계를 건너뛰려면 이유를 적어 건너뛰기를 하십시오.")

    def known_root(self, raw) -> str:
        cwd = platform_compat.clean_user_path(raw) if isinstance(raw, str) else ""
        root = os.path.realpath(os.path.expanduser(cwd)) if cwd else ""
        if not root or not any(platform_compat.same_path(root, r) for r in self.known_roots()):
            raise HttpError(403, "고른 작업 폴더가 아닙니다.")
        return root

    def available_flows(self, cwd: str) -> dict:
        """이 폴더에서 쓸 수 있는 갈래(조건이 없음으로 판정된 것만 뺀다. 판정 불능이면 둔다)."""
        data = self.flow_data
        if data is None:
            return {}
        cond = self.cond_fn(cwd, wait=False)  # 요청 스레드는 gh 를 기다리지 않는다(읽는 중이면 판정 불능이라 둔다)
        out = {fid: f for fid, f in self.flow_catalog().items()
               if not (flows.flow_def(data, fid).get("requires") and cond(flows.flow_def(data, fid)["requires"]) is False)}
        tools = ", ".join(f"/{self.plugin_name}:{t['skill']}" for t in data.get("tools", []) if t.get("kind") == "skill" and not t.get("hidden"))
        out[analysis.NO_FLOW] = {"name": analysis.NO_FLOW_NAME,
                                 "description": f"갈래(순서) 없이 도구 스킬만 쓰는 일. 도구: {tools}. 개발·문서 작업이 아니면 이쪽이다."}
        return out

    def tool_skill_of(self, text: str) -> str:
        """글 맨 앞에 사용자가 직접 적은 스킬이 workflow.json 의 도구 스킬이면 그 이름(`scaffold`), 아니면 빈 문자열."""
        prefix, _, name = analysis.direct_skill(text).rpartition(":")
        data = self.flow_data
        return name if data is not None and prefix in ("", self.plugin_name) and name in flows.tool_skills(data) else ""

    def analysis_context(self, cwd: str) -> str:
        """분석 프롬프트에 넣을 이 폴더의 사실: 프로젝트 준비 상태(scaffold 스킬 설명), 대상 시스템(Public Cloud, ABAP Cloud)."""
        lines = ["이 작업의 대상은 SAP S/4HANA Public Cloud 이고 ABAP Cloud(RAP, CDS, 릴리스된 API)를 전제로 한다. "
                 "ALV 리포트·클래식 dynpro·SAP GUI 전용 방식처럼 Public Cloud 에서 쓸 수 없는 방식은 보기나 질문으로 내놓지 않는다."]
        system_type = read_system_type(cwd)
        if system_type:
            lines.append(f"저장소 env/adt-tiers.yaml 의 system_type 은 {system_type!r} 이다. 이 값을 대상 시스템으로 본다.")
        if self.flow_data is not None and "project-ready" in self.flow_data.get("conditions", {}):
            state = self.cond_state("project-ready", cwd, wait=False)["state"]
            if state == COND_NO:
                lines.append("이 폴더는 프로젝트 준비가 안 됐다(templates/ 와 rules/ 를 함께 가진 폴더가 없다). 개발·문서 작업 요청이면 "
                             "understood 의 첫 문장으로 \"먼저 관리자가 프로젝트 구조 만들기(/harness:scaffold)를 해야 한다\"고 안내하고, "
                             "갈래 분류보다 이 안내를 앞세운다. scaffold 스킬은 새 고객사 Project Repository 를 처음 만들었을 때 표준 구조를 만든다.")
            elif state == COND_UNKNOWN:
                lines.append("이 폴더의 프로젝트 준비 여부(templates/ 와 rules/)는 확인하지 못했다. 준비가 됐다고도 안 됐다고도 단정하지 않는다.")
        return "\n".join(lines)

    def model_of(self, s: dict, chat: bool = False) -> dict:
        """잠금 순서: manager.lock(잎) 은 store.lock 을 쥔 채 잡지 않는다. 그래서 살아 있는지부터 묻고 나서 store.lock 을 잡는다."""
        alive = self.manager.alive(s["id"]) if s["managed"] else False
        with self.store.lock:
            s["managed_alive"] = alive
            return public_session(self.store, s, self.skills, chat)

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
        return 200, self.model_of(self.get_session(g[0]), chat=q.get("chat", ["1"])[0] != "0")  # 열어 보지 않는 세션은 ?chat=0 으로 대화를 뺀다

    def a_message(self, g, q, b):
        s = self.get_session(g[0])
        text = b.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "text 가 비어 있습니다.")
        return self.deliver(s, text.strip(), {"kind": "message", "text": text.strip()})

    def a_run(self, g, q, b):
        s = self.get_session(g[0])
        skill = g[1]
        if skill not in self.runnable_skills():
            raise HttpError(404, "없는 스킬입니다.")
        self.check_flow_order(s, skill)
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
                s["reportFresh"] = False
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
        if g[1] not in self.runnable_skills():
            raise HttpError(404, "없는 스킬입니다.")
        self.check_flow_order(s, g[1])
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

    def a_permission(self, g, q, b):
        s = self.get_session(g[0])
        mode = b.get("mode")
        if not isinstance(mode, str) or mode not in PERMISSION_VALUES:
            raise HttpError(400, "고를 수 없는 권한 모드입니다.")
        if not s["managed"]:
            raise HttpError(409, "콘솔이 띄운 세션만 권한 모드를 바꿀 수 있습니다.")
        result = self.manager.set_permission(s["id"], mode)
        if not result["ok"]:
            raise HttpError(502, "권한 모드를 바꾸지 못했습니다: " + str(result.get("error", "")))
        return 200, dict(result, session=self.model_of(s))

    def a_request(self, g, q, b):
        r = self.store.get_request(g[0])
        if r is None:
            raise HttpError(404, "없는 요청입니다.")
        data = r.public()
        s = self.store.get(r.session_id)
        data["sessionTitle"] = display_title(s) if s else ""
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
                if r.risk == "irreversible":
                    raise HttpError(400, "되돌릴 수 없는 일은 '다시 묻지 않기'로 허용할 수 없습니다. 이번만 허락하세요.")
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

    # 모델
    def model_options(self) -> list[dict]:
        options = [{"value": v, "label": label} for v, label in MODEL_OPTIONS]
        if self.default_model and all(o["value"] != self.default_model for o in options):
            options.append({"value": self.default_model, "label": self.default_model})  # 서버를 켠 쪽이 정한 값도 고를 수 있게
        return options

    def a_models(self, g, q, b):
        return 200, {"options": self.model_options(), "default": self.default_model,
                     "effortOptions": [{"value": v, "label": label} for v, label in EFFORT_OPTIONS],
                     "defaultEffort": self.default_effort, "customPattern": MODEL_NAME.pattern,
                     "permissionOptions": [{"value": v, "label": label} for v, label in PERMISSION_OPTIONS]}

    # 갈래
    def flow_exposure(self, requires, state_of) -> dict:
        if not requires:
            return {"visible": True, "state": COND_YES, "reason": ""}
        got = state_of(requires)
        return {"visible": got["state"] != COND_NO, "state": got["state"], "reason": got["reason"]}  # 판정 불능은 숨기지 않는다

    def a_flows(self, g, q, b):
        """갈래·단계·도구 데이터. cwd(아는 작업 폴더)를 주면 그 폴더·이 사용자 기준의 노출 여부(exposure)를 더한다."""
        data = self.require_flows()
        cwd = self.known_root(q["cwd"][0]) if q.get("cwd") else None
        states: dict[str, dict] = {}

        def state_of(name):  # 이 요청 안에서 조건마다 한 번만 읽고, gh 결과는 기다리지 않는다
            if name not in states:
                states[name] = self.cond_state(name, cwd, wait=False)
            return states[name]

        out_flows = []
        for f in data["flows"]:
            item = {k: f.get(k) for k in ("id", "name", "description", "requires", "next")}
            item["steps"] = [dict(st, **({"exposure": self.flow_exposure(st["onlyIf"], state_of)} if cwd and st.get("onlyIf") else {}))
                             for st in f["steps"]]
            if cwd:
                item["exposure"] = self.flow_exposure(f.get("requires"), state_of)
            out_flows.append(item)
        tools = [dict(t, **({"exposure": self.flow_exposure(t.get("requires"), state_of)} if cwd else {})) for t in data["tools"]]
        result = {"version": data.get("version"), "flows": out_flows, "tools": tools, "evidence": data.get("evidence", {})}
        if cwd:
            result["conditions"] = {name: state_of(name) for name in data["conditions"]}
            result["loading"] = any(c.get("loading") for c in result["conditions"].values())
            ready = result["conditions"].get("project-ready", {}).get("state")
            result["formsMissing"] = self.forms_missing(cwd)["state"] if ready == COND_YES else COND_NO
        return 200, result

    def a_approvals(self, g, q, b):
        """내 승인을 기다리는 열린 PR. gh 로 읽고 60초 기억한다. state: yes(승인자) / no(승인자 아님) / unknown(판정 불능)."""
        if not q.get("cwd"):
            raise HttpError(400, "cwd 가 필요합니다.")
        cwd = self.known_root(q["cwd"][0])
        spec = (self.flow_data or {}).get("conditions", {}).get("approver", {})
        file_rel, when_no_file = spec.get("file", ".github/ssot-approvers"), spec.get("whenNoFile", gitstate.WHEN_NO_FILE_ADMIN)
        got = self.cached(("approvals", os.path.normcase(cwd)), lambda: gitstate.approval_prs(self.run, cwd, file_rel, when_no_file), wait=False)
        return 200, got  # 읽는 중이면 loading: true 와 이전 값(없으면 state unknown)을 바로 준다

    def a_dev_ready(self, g, q, b):
        """이 폴더의 개발 건별 Spec 유무(#668). git 으로 읽고 60초 기억하며 요청 스레드는 기다리지 않는다(읽는 중이면 loading: true).
        state: yes(읽음) / no(원장 없는 저장소 등 해당 없음) / unknown(읽지 못함)."""
        if not q.get("cwd"):
            raise HttpError(400, "cwd 가 필요합니다.")
        cwd = self.known_root(q["cwd"][0])
        return 200, self.cached(("dev-ready", os.path.normcase(cwd)), lambda: devready.read(self.run, self.slow_run, cwd), wait=False)

    def a_srs_status(self, g, q, b):
        """세션 작업 폴더 SRS 의 요구사항별 Status(#718). 설정·표준 건 세션 화면의 "SRS 상태" 칸이 쓴다.
        state: yes(읽음) / no(SRS 없음) / unknown(읽지 못함)."""
        if not q.get("cwd"):
            raise HttpError(400, "cwd 가 필요합니다.")
        return 200, devready.srs_status(self.run, self.known_root(q["cwd"][0]))

    # ---- 시작 점검(첫 화면) ----
    def first_run_file(self) -> Path | None:
        return self.store.dir / FIRST_RUN_FILE if self.store.dir else None

    def is_first_run(self) -> bool:
        """이 PC 에서 시작하기를 아직 안 눌렀나. 표시 파일이 있으면 아니다(읽을 수 없어도 있는 것으로 본다)."""
        f = self.first_run_file()
        if f is None:
            return not self.first_run_seen
        return not f.exists()

    def mark_first_run(self) -> None:
        f = self.first_run_file()
        if f is None:
            self.first_run_seen = True
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seenAt": self.clock()}), encoding="utf-8")
        os.replace(tmp, f)

    def read_remote_latest(self) -> str | None:
        """원격 v* 태그 중 가장 큰 판(installed_version.py --remote 와 같은 update_notice 를 쓴다). 못 읽으면 None."""
        hooks = str(self.plugin_root / "hooks")
        try:
            if hooks not in sys.path:
                sys.path.insert(0, hooks)
            import update_notice  # noqa: PLC0415 - 훅 모듈
            return update_notice.latest_version(update_notice.ls_remote_tags())
        except Exception:  # noqa: BLE001 - 어떤 이유로든 못 읽으면 "확인 못 함"
            return None

    def run_start_checks(self) -> dict:
        home = str(Path.home())
        rc, out = self.check_run(["gh", "api", "user", "--jq", ".login"], home)
        gh = dict(judge_github(rc, out, self.gh_installed()), id="github", name="GitHub 연결")
        ver = judge_version(self.version, self.remote_latest())
        ver = dict(ver, id="version", name="하네스 최신 판" if ver["state"] == "ok" else "하네스 판")  # 시안 G-01: 최신이면 "하네스 최신 판"
        try:
            base = self.claude_cmd()
        except Exception:  # noqa: BLE001 - 못 찾으면 확인 못 함
            base = None
        rc2, out2 = self.check_run(list(base) + ["auth", "status", "--json"], home) if base else (127, "")
        claude = dict(judge_claude(rc2, out2, bool(base)), id="claude", name="Claude Code 로그인")
        checks = [gh, ver, claude]
        return {"state": "ok", "checks": checks, "blocking": any(c["state"] == "fail" for c in checks),
                "newVersion": ver.get("latest") if ver["state"] == "old" else None}

    def a_start_checks(self, g, q, b):
        """첫 화면과 맨 위 알림에 쓰는 점검 결과. 점검은 백그라운드에서 하고(60초 기억), 읽는 중이면 loading: true.
        ?refresh=1 은 기억을 지우고 다시 점검한다(다시 점검 버튼)."""
        key = ("start-checks",)
        if q.get("refresh"):
            with self.lock:
                self.cache.pop(key, None)
                self.last.pop(key, None)
        got = self.cached(key, self.run_start_checks, wait=False)
        out = {"firstRun": self.is_first_run(), "loading": bool(got.get("loading")), "checks": got.get("checks", []),
               "blocking": bool(got.get("blocking")), "newVersion": got.get("newVersion")}
        return 200, out

    def a_start_seen(self, g, q, b):
        try:
            self.mark_first_run()
        except OSError as e:
            raise HttpError(500, f"첫 화면 표시를 남기지 못했습니다: {e}")
        return 200, {"firstRun": False}

    # ---- 플러그인이 바뀐 뒤 바뀐 점 안내(#647) ----
    def read_seen_version(self) -> str | None:
        """지난번 본 판. 파일이 없거나 읽을 수 없으면 None(이 PC 에서 처음으로 본다)."""
        f = self.store.dir / SEEN_VERSION_FILE if self.store.dir else None
        if f is None:
            return self.seen_version
        try:
            v = json.loads(f.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError):
            return None
        return v if isinstance(v, str) and v else None

    def save_seen_version(self, version: str) -> None:
        f = self.store.dir / SEEN_VERSION_FILE if self.store.dir else None
        if f is None:
            self.seen_version = version
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": version, "seenAt": self.clock()}), encoding="utf-8")
        os.replace(tmp, f)

    def a_whats_new(self, g, q, b):
        """콘솔이 실린 판(current)과 지난번 본 판(seen) 사이 판들의 바뀐 점. 새 판부터."""
        current = self.version
        seen = self.read_seen_version()
        cur_key = parse_version(current)
        if cur_key is None:
            return 200, {"current": current, "seen": seen, "items": [], "reason": "콘솔이 실린 판을 몰라서 바뀐 점을 못 보여 줘"}
        if seen is None or parse_version(seen) is None:  # 이 PC 에서 처음 — 첫 화면이 따로 있으니 옛 변경을 쏟지 않는다
            try:
                self.save_seen_version(current)
            except OSError as e:
                return 200, {"current": current, "seen": None, "items": [], "reason": f"본 판을 남기지 못했어: {e}"}
            return 200, {"current": current, "seen": current, "items": []}
        seen_key = parse_version(seen)
        if seen_key > cur_key:  # 판을 내렸다
            try:
                self.save_seen_version(current)
            except OSError as e:
                return 200, {"current": current, "seen": seen, "items": [], "reason": f"본 판을 남기지 못했어: {e}"}
            return 200, {"current": current, "seen": current, "items": []}
        try:
            data = json.loads((self.plugin_root / "console" / WHATS_NEW_FILE).read_text(encoding="utf-8"))
            versions = data["versions"]
            if not isinstance(versions, dict):
                raise ValueError("versions 가 목록이 아니야")
        except (OSError, ValueError, KeyError, TypeError) as e:
            return 200, {"current": current, "seen": seen, "items": [], "reason": f"바뀐 점 목록을 못 읽었어: {e}"}
        found = []
        for ver, lines in versions.items():
            k = parse_version(ver)
            if k is None or not (seen_key < k <= cur_key) or not isinstance(lines, list):
                continue
            lines = [x for x in lines if isinstance(x, str) and x.strip()]
            if lines:
                found.append((k, {"version": ver, "lines": lines}))
        found.sort(key=lambda t: t[0], reverse=True)
        return 200, {"current": current, "seen": seen, "items": [x for _, x in found]}

    def a_whats_new_seen(self, g, q, b):
        if parse_version(self.version) is None:
            raise HttpError(409, "콘솔이 실린 판을 몰라서 본 판을 남길 수 없어.")
        try:
            self.save_seen_version(self.version)
        except OSError as e:
            raise HttpError(500, f"본 판을 남기지 못했습니다: {e}")
        return 200, {"seen": self.version}

    def a_flow_set(self, g, q, b):
        s = self.get_session(g[0])
        if "flowId" not in b:
            raise HttpError(400, "flowId 가 필요합니다(비우려면 null).")
        if b["flowId"] is None:
            with self.store.lock:
                s["flowState"] = None
                self.store.add_log(s, "갈래 해제")
            self.store.touch(s)
            return 200, self.model_of(s)
        if not isinstance(b["flowId"], str):
            raise HttpError(400, "flowId 가 문자열이 아닙니다.")
        reason = b.get("reason") if isinstance(b.get("reason"), str) and b["reason"].strip() else "사용자가 고름"
        self.assign_flow(s, b["flowId"], reason)
        return 200, self.model_of(s)

    def flow_session(self, g) -> dict:
        s = self.get_session(g[0])
        if not s.get("flowState"):
            raise HttpError(409, "갈래가 지정되지 않은 세션입니다.")
        return s

    def a_flow_skip(self, g, q, b):
        s = self.flow_session(g)
        cond = self.cond_snapshot(s["cwd"], s["flowState"])  # git·gh 는 잠금 밖에서 읽는다
        with self.store.lock:
            cur = flows.current(s["flowState"])
            name = cur["name"] if cur else ""
            why = flows.skip(s, b.get("reason"), self.clock(), cond)
            if why:
                raise HttpError(400 if cur else 409, why)
            self.store.add_log(s, f"단계 건너뜀: {name} - {b['reason'].strip()[:200]}")
        self.advance_flow(s)
        self.store.touch(s)
        return 200, self.model_of(s)

    def a_flow_done(self, g, q, b):
        """사람이 '끝났다' 고 누른다. manual 이 든 단계만 되고, 같은 단계의 다른 근거(변경 등)가 안 맞으면 409."""
        s = self.flow_session(g)
        with self.store.lock:
            cur = flows.current(s["flowState"])
            name = cur["name"] if cur else ""
            why = flows.confirm(s)
            if why:
                raise HttpError(409, why)
        self.advance_flow(s)
        if flows.current(s["flowState"]) is cur:
            with self.store.lock:
                cur["confirmed"] = False  # 다른 근거가 아직 안 맞으면 누른 것을 무르고 알린다
            raise HttpError(409, " ".join(s["flowState"]["unknown"]) or "이 단계의 다른 완료 근거(변경 등)가 아직 맞지 않습니다.")
        with self.store.lock:
            self.store.add_log(s, f"단계 끝냄(사람 확인): {name}")
        self.store.touch(s)
        return 200, self.model_of(s)

    def a_flow_refresh(self, g, q, b):
        """병합처럼 세션 밖에서 일어난 일을 지금 다시 읽어 판정한다."""
        s = self.flow_session(g)
        self.advance_flow(s)
        self.store.touch(s)
        return 200, self.model_of(s)

    # ---- 플러그인 다시 불러오기 ----
    def busy(self, s: dict) -> bool:
        with self.store.lock:
            return bool(s["turn_running"] or s.get("starting"))

    def wait_until(self, cond, timeout: float) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(self.wait_poll)
        return cond()

    def reload_body(self, got: dict) -> dict:
        plugins = got["plugins"]
        body = {"ok": True, "method": got["method"], "plugins": plugins, "errorCount": got["errorCount"],
                "harnessVersion": next((p["version"] for p in plugins if p["name"] == self.plugin_name), "")}
        if got.get("message"):
            body["message"] = got["message"]
        return body

    def reload_session(self, s: dict) -> tuple[int, dict]:
        """콘솔이 띄운 세션의 플러그인을 다시 불러온다. 턴 도중이면 끝나기를 기다렸다가 하고 바로 202 {queued:true} 로 답한다."""
        sid = s["id"]
        if self.busy(s):
            with self.lock:
                already = sid in self.reload_queue
                self.reload_queue.add(sid)
            if not already:
                threading.Thread(target=self.queued_reload, args=(sid,), daemon=True).start()
            return 202, {"queued": True}
        got = self.manager.reload_plugins(sid)
        if not got["ok"]:
            raise HttpError(502, "플러그인을 다시 불러오지 못했습니다: " + got["error"])
        return 200, self.reload_body(got)

    def queued_reload(self, sid: str) -> None:
        try:
            s = self.store.get(sid)
            if s is None or not self.wait_until(lambda: not self.busy(s), RELOAD_QUEUE_WAIT):
                self.manager._warn(sid, "플러그인 다시 불러오기: 턴이 끝나지 않아 실행하지 못했습니다.")
                return
            got = self.manager.reload_plugins(sid)  # 성공하면 Manager 가 로그와 점검 표시를 남긴다
            if not got["ok"]:
                self.manager._warn(sid, "플러그인 다시 불러오기 실패: " + got["error"])
        finally:
            with self.lock:
                self.reload_queue.discard(sid)

    def console_session(self, sid: str) -> dict:
        s = self.get_session(sid)
        if not s["managed"]:
            raise HttpError(409, "콘솔이 띄운 세션만 플러그인을 다시 불러올 수 있습니다. 터미널 세션은 터미널에서 /reload-plugins 를 실행하십시오.")
        if not self.manager.alive(s["id"]):
            raise HttpError(409, "끝난 세션입니다. 이어서 띄우면 최신 플러그인으로 시작합니다.")
        return s

    def a_reload(self, g, q, b):
        return self.reload_session(self.console_session(g[0]))

    def a_reload_all(self, g, q, b):
        with self.store.lock:
            targets = [s for s in self.store.sessions.values() if s["managed"]]
        targets = [s for s in targets if self.manager.alive(s["id"])]

        def one(s: dict) -> dict:
            item = {"sessionId": s["id"], "title": display_title(s)}
            try:
                _, data = self.reload_session(s)
            except HttpError as e:
                return dict(item, ok=False, error=e.message)
            return dict(item, **data)

        with ThreadPoolExecutor(max_workers=RELOAD_ALL_WORKERS) as pool:
            return 200, {"results": list(pool.map(one, targets))}

    def a_check_skip(self, g, q, b):
        s = self.get_session(g[0])
        if g[1] not in START_CHECK_IDS:
            raise HttpError(404, "없는 점검 항목입니다.")
        with self.store.lock:
            mark_check(s, g[1], CHECK_SKIPPED)
        self.store.touch(s)
        return 200, self.model_of(s)

    # ---- 만든 문서 보기 ----
    def file_session_cwd(self, sid: str) -> tuple[dict, str]:
        s = self.get_session(sid)
        cwd = s["cwd"]
        if not cwd or not os.path.isdir(cwd):
            raise HttpError(409, "세션의 작업 폴더가 없습니다.")
        return s, cwd

    def file_target(self, sid: str, raw) -> tuple[str, str, str]:
        _, cwd = self.file_session_cwd(sid)
        try:
            real, rel = docfiles.resolve(cwd, raw)
        except docfiles.PathRefused as e:
            raise HttpError(e.status, e.message)
        return cwd, real, rel

    def annotate_upload(self, cwd: str, root: str, listed: list[dict], why: str) -> None:
        """파일마다 upload 를 더한다(칩의 근거, #652). git 상태를 못 읽었으면(why) 커밋 여부도 모르므로 모두 unknown 이다."""
        if why:
            for f in listed:
                f["upload"] = {"state": "unknown", "prs": [], "reason": why}
            return
        key = ("open-pr-files", os.path.normcase(root))  # gh 는 느리니 저장소당 CACHE_SECONDS 기억한다(못 읽은 결과는 기억하지 않는다)
        states = gitstate.upload_states(self.run, cwd, [(f["path"], bool(f.get("changed"))) for f in listed],
                                        lambda: self.cached(key, lambda: gitstate.open_pr_files(self.run, cwd)))
        for f in listed:
            f["upload"] = states.get(f["path"]) or {"state": "unknown", "prs": [], "reason": "올렸는지 판정하지 못했습니다."}

    def a_session_files(self, g, q, b):
        s, cwd = self.file_session_cwd(g[0])
        root, failed = gitstate.repo_root_checked(self.run, cwd)
        not_repo = not root and not failed  # 저장소가 아니면 git status 가 비어도 '바뀐 것 없음' 이 아니다
        paths, why = ([], "") if not_repo else gitstate.status_paths(self.run, cwd)
        now = self.store.clock()
        with self.store.lock:
            if why:
                s["touchedGap"] = {"reason": why, "at": now}
            elif not not_repo:
                remember_touched(s, paths, from_status=True)  # 커밋하면 git status 에서 사라지므로 이 세션이 만든 파일은 따로 쌓아 둔다
            touched = list(s.get("touchedFiles") or [])
            truncated, gap = bool(s.get("touchedTruncated")), s.get("touchedGap")
        listed = docfiles.collect(cwd, touched, None if (why or not_repo) else paths)
        out = {"files": listed}
        self.annotate_upload(cwd, root, listed, why or ("git 저장소가 아니라 올렸는지 알 수 없어요." if not_repo else ""))
        if truncated:
            out["truncated"] = True  # 쌓아 두는 상한에 닿아 더 있는 문서가 빠졌다
        if why:  # git 을 못 읽었다 = 바뀐 문서가 없다는 뜻이 아니다. 훅이 모은 목록만으로 보여 주고 화면이 알리게 한다
            out.update(unknown=True, reason=why)
        elif not_repo:
            out.update(unknown=True, reason="git 저장소가 아니라 커밋 여부를 알 수 없어요.")
        elif isinstance(gap, dict) and now - gap.get("at", 0) <= GAP_NOTICE_SECONDS:  # 지금은 읽었다. 못 읽은 동안 커밋된 문서가 빠졌을 수 있다는 안내만 하고(note) 파일별 칩은 덮지 않는다. 영구 경고는 피하려 일정 시간만 알린다
            out["note"] = f"{time.strftime('%H:%M', time.localtime(gap['at']))} 에 git 상태를 읽지 못해 그 사이 커밋된 문서가 빠졌을 수 있어요."
        return 200, out

    def a_file_preview(self, g, q, b):
        _, real, rel = self.file_target(g[0], q.get("path", [""])[0])
        try:
            return 200, docfiles.preview(real, rel, f"/api/sessions/{quote(g[0], safe='')}/files/raw?path={quote(rel, safe='/')}")
        except docfiles.PreviewError as e:
            raise HttpError(422, str(e))
        except OSError as e:
            raise HttpError(500, f"파일을 읽지 못했습니다: {type(e).__name__}")

    def a_file_raw(self, g, q, b):
        _, real, rel = self.file_target(g[0], q.get("path", [""])[0])
        ext = docfiles.ext_of(real)
        if docfiles.kind_of(real) != "image" or ext not in docfiles.IMAGE_MIME:
            raise HttpError(403, "이미지 파일만 내려줍니다.")
        try:
            if os.path.getsize(real) > docfiles.MAX_RAW_BYTES:
                raise HttpError(413, "이미지가 너무 큽니다.")
            with open(real, "rb") as fh:
                body = fh.read()
        except OSError as e:
            raise HttpError(500, f"파일을 읽지 못했습니다: {type(e).__name__}")
        # SVG 안의 스크립트가 이 출처에서 돌지 못하게 한다
        return 200, Raw(body, docfiles.IMAGE_MIME[ext], {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})

    def a_file_open(self, g, q, b):
        mode = b.get("mode")
        if mode not in ("open", "reveal"):
            raise HttpError(400, "mode 는 open 또는 reveal 이어야 합니다.")
        _, real, rel = self.file_target(g[0], b.get("path"))
        if mode == "open" and not {docfiles.ext_of(real), docfiles.ext_of(rel)} <= docfiles.OPEN_EXTS:
            raise HttpError(403, "이 형식은 열 수 없습니다. 실행 파일이나 스크립트일 수 있어 위치 보기만 됩니다.")
        error = self.opener(real, mode)
        if error:
            raise HttpError(502, error)
        with self.store.lock:
            self.store.add_log(self.get_session(g[0]), ("파일 열기: " if mode == "open" else "파일 위치 보기: ") + rel)
        return 200, {"ok": True}

    # ---- 작업용 폴더(worktree) ----
    def a_worktree(self, g, q, b):
        root = self.known_root(b.get("cwd"))
        top = gitstate.repo_root(self.run, root)
        if not top:
            raise HttpError(400, "git 저장소가 아닌 폴더입니다.")
        if not platform_compat.same_path(os.path.realpath(top), root):
            raise HttpError(400, "저장소의 맨 위 폴더에서만 작업용 폴더를 만들 수 있습니다.")
        for _ in range(5):
            path = gitstate.worktree_path(root, uuid.uuid4().hex[:6])
            if not os.path.exists(path):
                break
        else:
            raise HttpError(502, "작업용 폴더 이름을 정하지 못했습니다.")
        error = gitstate.add_worktree(self.run, self.slow_run, root, path)
        if error:
            raise HttpError(502, error)
        self.store.add_folder(path)
        return 200, {"path": path}

    # ---- 다음 갈래로 넘어가기(자동 인계 + 새 세션) ----
    def a_flow_next(self, g, q, b):
        s = self.get_session(g[0])
        fid = b.get("flowId")
        if not isinstance(fid, str):
            raise HttpError(400, "flowId 가 필요합니다.")
        data = self.require_flows()
        flow = flows.flow_def(data, fid)
        if flow is None:
            raise HttpError(400, "없는 갈래입니다.")
        raw_ids = b.get("ids")
        if raw_ids is not None and (not isinstance(raw_ids, list) or any(not isinstance(i, str) or not REQ_ID.fullmatch(i) for i in raw_ids)):
            raise HttpError(400, "ids 는 REQ-xxx 번호 목록이어야 합니다.")
        unique = list(dict.fromkeys(raw_ids or []))
        ids = unique[:MAX_NEXT_IDS]
        cut_note = f"요구사항 {len(unique)}건 중 {MAX_NEXT_IDS}건만 넘겼습니다. 나머지는 이 세션이 끝난 뒤 다시 고르세요." if len(unique) > MAX_NEXT_IDS else ""
        if not s["managed"]:
            raise HttpError(409, HANDOFF_GUIDE)
        if not s["cwd"] or not os.path.isdir(s["cwd"]):
            raise HttpError(409, "세션의 작업 폴더가 없습니다.")
        if flow.get("requires") and self.cond_fn(s["cwd"])(flow["requires"]) is False:
            raise HttpError(409, f"이 폴더에서는 쓸 수 없는 갈래입니다: {data['conditions'][flow['requires']].get('label', flow['requires'])}")
        with self.lock:
            if any(j["fromSession"] == s["id"] and j["status"] in JOB_ACTIVE for j in self.jobs.values()):
                raise HttpError(409, "이 세션은 이미 다음 갈래로 넘기는 중입니다.")
            for j in self.jobs.values():  # 확인을 기다리다 잊힌 이전 요청은 새 요청이 대신한다
                if j["fromSession"] == s["id"] and j["status"] == "confirm":
                    j.update(status="canceled", prompt="")
            job = {"id": uuid.uuid4().hex[:12], "kind": "flowNext", "status": "handoff", "fromSession": s["id"], "flowId": fid, "ids": ids,
                   "sessionId": None, "error": "", "warning": cut_note}
            self.jobs[job["id"]] = job
            for old in [j["id"] for j in self.jobs.values() if j["status"] not in JOB_ACTIVE + ("confirm",)][:-MAX_JOBS]:
                self.jobs.pop(old, None)
        threading.Thread(target=self.run_next, args=(job, s["id"], flow), daemon=True).start()
        return 202, {"jobId": job["id"]}

    def a_job(self, g, q, b):
        with self.lock:
            job = self.jobs.get(g[0])
            if job is None:
                raise HttpError(404, "없는 작업입니다.")
            return 200, dict(job)

    def next_failed(self, job: dict, sid: str, why: str) -> None:
        job.update(status="failed", error=why)
        s = self.store.get(sid)
        if s is not None:
            with self.store.lock:
                self.store.add_log(s, "다음 갈래로 넘기기 실패: " + why)
            self.store.touch(s)

    def run_next(self, job: dict, sid: str, flow: dict) -> None:
        """예외가 나도 job 을 failed 로 바꾸고 JOB_ACTIVE 에서 풀어 준다(그렇지 않으면 그 세션은 영영 '넘기는 중' 으로 남는다)."""
        try:
            self.run_handoff(job, sid, flow)
        except Exception as e:  # noqa: BLE001 - 어떤 예외든 job 을 끝낸다
            print(f"[console] 다음 갈래 인계 중 예외: {type(e).__name__}: {e}", file=sys.stderr)
            self.next_failed(job, sid, f"예기치 못한 오류로 멈췄습니다({type(e).__name__}).")

    def run_handoff(self, job: dict, sid: str, flow: dict) -> None:
        """이 세션에 /harness:handoff 를 보내 끝나기를 기다리고 마지막 코드 블록을 뽑아, 사람이 확인할 수 있게 job 을 confirm 으로 둔다.
        인계를 못 받으면 사유와 함께 멈춘다. 새 세션은 사람이 확인(confirm)해야 띄운다."""
        s = self.store.get(sid)
        if s is None or not self.wait_until(lambda: not self.busy(s), HANDOFF_IDLE_WAIT):
            return self.next_failed(job, sid, "진행 중인 턴이 끝나지 않아 인계를 보내지 못했습니다.")
        marker = self.manager.result_marker(sid)
        try:
            self.deliver(s, f"/{self.plugin_name}:{handoff.HANDOFF_SKILL}", {"kind": "skill", "skill": handoff.HANDOFF_SKILL, "args": ""})
        except HttpError as e:
            return self.next_failed(job, sid, "인계를 보내지 못했습니다: " + e.message)
        result = [False, "", False, ""]

        def finished() -> bool:
            result[:] = self.manager.result_after(sid, marker)
            return result[0] or bool(result[3])

        if not self.wait_until(finished, HANDOFF_WAIT):
            return self.next_failed(job, sid, "인계가 10분 안에 끝나지 않아 새 세션을 띄우지 않았습니다.")
        done, text, is_error, why = result
        if not done:
            return self.next_failed(job, sid, "인계 도중 " + why)
        if is_error:
            return self.next_failed(job, sid, "인계가 오류로 끝났습니다: " + text.strip()[:200])
        prompt = handoff.last_code_block(text)
        if not prompt:
            return self.next_failed(job, sid, "인계 결과에서 새 세션용 프롬프트(마지막 코드 블록)를 찾지 못해 새 세션을 띄우지 않았습니다.")
        if len(prompt) > MAX_NEXT_PROMPT:
            return self.next_failed(job, sid, f"인계 프롬프트가 너무 깁니다({len(prompt)}자, 최대 {MAX_NEXT_PROMPT}자). 새 세션을 띄우지 않았습니다.")
        with self.lock:
            job.update(status="confirm", prompt=prompt)  # 사람이 보고 [이대로 시작] [고쳐서 시작] [취소] 를 고른다

    def a_job_confirm(self, g, q, b):
        """확인 대기 중인 job 의 새 세션을 띄운다. 본문의 prompt(고친 글)를 쓰고, 없으면 인계가 만든 글을 그대로 쓴다."""
        with self.lock:
            job = self.jobs.get(g[0])
            if job is None:
                raise HttpError(404, "없는 작업입니다.")
            if job["status"] != "confirm":
                raise HttpError(409, "확인을 기다리는 작업이 아닙니다.")
            prompt = b.get("prompt", job.get("prompt"))
            if not isinstance(prompt, str) or not prompt.strip():
                raise HttpError(400, "새 세션에 보낼 글이 비어 있습니다.")
            if len(prompt) > MAX_NEXT_PROMPT:
                raise HttpError(400, f"글이 너무 깁니다(최대 {MAX_NEXT_PROMPT}자).")
            job["status"] = "starting"  # 두 번 눌러도 새 세션이 둘 뜨지 않게 이 잠금 안에서 바꾼다
            flow = flows.flow_def(self.flow_data or {}, job["flowId"])
        if flow is None:
            self.next_failed(job, job["fromSession"], "갈래 데이터가 바뀌어 새 세션을 띄우지 못했습니다.")
            raise HttpError(409, job["error"])
        threading.Thread(target=self.start_next, args=(job, flow, prompt), daemon=True).start()
        return 202, {"jobId": job["id"]}

    def a_job_cancel(self, g, q, b):
        with self.lock:
            job = self.jobs.get(g[0])
            if job is None:
                raise HttpError(404, "없는 작업입니다.")
            if job["status"] != "confirm":
                raise HttpError(409, "확인을 기다리는 작업이 아닙니다.")
            job.update(status="canceled", prompt="")
        s = self.store.get(job["fromSession"])
        if s is not None:
            with self.store.lock:
                self.store.add_log(s, "다음 갈래로 넘기기 취소")
            self.store.touch(s)
        return 200, dict(job)

    def start_next(self, job: dict, flow: dict, prompt: str) -> None:
        try:
            self.launch_next(job, flow, prompt)
        except Exception as e:  # noqa: BLE001
            print(f"[console] 새 세션 시작 중 예외: {type(e).__name__}: {e}", file=sys.stderr)
            self.next_failed(job, job["fromSession"], f"예기치 못한 오류로 멈췄습니다({type(e).__name__}).")

    def launch_next(self, job: dict, flow: dict, prompt: str) -> None:
        """같은 폴더에서 새 콘솔 세션을 그 갈래로 띄운다. 이전 세션은 새 세션이 시작 신호(init)를 낸 것을 확인한 뒤에만 닫는다."""
        s = self.store.get(job["fromSession"])
        if s is None:
            return self.next_failed(job, job["fromSession"], "이전 세션이 없어졌습니다.")
        with self.store.lock:
            choices = {k: s.get(k) if isinstance(s.get(k), str) else None for k in ("modelChoice", "effortChoice", "permissionChoice")}
        if choices["permissionChoice"] not in PERMISSION_VALUES:  # 허용 집합(""·acceptEdits·plan) 밖의 모드는 승계하지 않는다
            choices["permissionChoice"] = None
        devs = [("DEV-" + i[4:]) for i in job.get("ids") or []]  # REQ-003 은 DEV-003 이다(srs 스킬 "번호")
        message = handoff.new_session_message(prompt, flow, self.plugin_name, devs)
        new = self.manager.launch(s["cwd"], message, title=f"{flow.get('name', flow['id'])} (이어서)", model=choices["modelChoice"],
                                  effort=choices["effortChoice"], permission=choices["permissionChoice"])
        if new is None:
            return self.next_failed(job, s["id"], "새 claude 세션을 띄우지 못했습니다. " + platform_compat.CLAUDE_MISSING)
        end = time.monotonic() + NEW_SESSION_ID_WAIT
        while time.monotonic() < end and self.store.resolve_id(new) == new and new.startswith("m-"):
            time.sleep(0.05)
        real = self.store.resolve_id(new)
        started = self.wait_until(lambda: self.new_session_started(real), NEW_SESSION_INIT_WAIT)
        if not started:
            job["sessionId"] = real
            return self.next_failed(job, s["id"], "새 세션이 시작 신호를 보내지 않아 이전 세션을 닫지 않았습니다. 새 세션 상태를 확인해 주세요.")
        try:
            reason = f"{flow['reasonPrefix']} {', '.join(devs)}" if flow.get("reasonPrefix") and devs else "이전 세션에서 이어서 시작"
            self.assign_flow(self.get_session(real), flow["id"], reason)
        except HttpError as e:
            job["warning"] = " ".join(x for x in (job.get("warning"), "새 세션은 떴지만 갈래를 지정하지 못했습니다: " + e.message) if x)
        self.mark_handed_off(s, real)
        with self.lock:
            job.update(status="started", sessionId=real)
        proc = self.manager.proc_for(s["id"])  # 새 세션이 떴으니 이전 세션은 정상 종료(stdin 닫기)한다
        if proc is not None and proc.alive():
            self.manager.close(proc)

    def new_session_started(self, sid: str) -> bool:
        """새 세션 프로세스가 init 이벤트를 냈는가(managed 의 init 처리가 starting 을 내린다)."""
        with self.store.lock:
            n = self.store.get(sid)
            return bool(n is not None and n.get("managed") and not n.get("starting"))

    def mark_handed_off(self, old: dict, new_id: str) -> None:
        """이전 세션에 넘어간 곳을 적는다. 같은 폴더 경고(sameFolder)에서는 넘어간 세션이 빠진다."""
        with self.store.lock:
            old["handedOffTo"] = new_id
            self.store.add_log(old, "다음 세션으로 넘어감")
        self.store.touch(old)
        self.store.publish("session", {"id": new_id})  # 새 세션 화면이 sameFolder 를 다시 받는다

    def a_skills(self, g, q, b):
        return 200, {"plugin": self.plugin_name, "skills": self.skill_info}

    def a_files(self, g, q, b):
        """@ 멘션용 파일 찾기. 서버가 아는 작업 폴더 안만 보고, 큰 폴더는 건너뛰며, 결과·탐색 수에 상한이 있다."""
        raw_root = platform_compat.clean_user_path(q.get("root", [""])[0])
        root = os.path.realpath(os.path.expanduser(raw_root))
        if not raw_root or not any(platform_compat.same_path(root, r) for r in self.known_roots()):
            raise HttpError(403, "고른 작업 폴더가 아닙니다.")
        needle = q.get("q", [""])[0][:FILE_QUERY_MAX].replace("\\", "/").lower()
        results, scanned, truncated = [], 0, False
        for cur, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(files):
                scanned += 1
                if scanned > FILE_SCAN_LIMIT:
                    truncated = True
                    break
                full = os.path.join(cur, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                if needle not in rel.lower() or not platform_compat.is_within(full, root):
                    continue  # 링크가 작업 폴더 밖을 가리키면 내지 않는다
                results.append(rel)
                if len(results) >= FILE_RESULT_LIMIT:
                    truncated = True
                    break
            if truncated:
                break
        return 200, {"root": root, "files": results, "truncated": truncated}

    def requested_permission(self, b: dict) -> str | None:
        """요청에 permission 이 없으면 None(세션에 기억된 값 또는 기본). 있으면 허용 3종 안의 값만 받는다."""
        if "permission" not in b or b["permission"] is None:
            return None
        value = b["permission"]
        if not isinstance(value, str) or value not in PERMISSION_VALUES:
            raise HttpError(400, "고를 수 없는 권한 모드입니다.")
        return value

    def requested_model(self, b: dict) -> str | None:
        """요청에 model 이 없으면 None(서버 기본값). 있으면 허용 별칭이거나 안전한 정식 이름만 받는다."""
        if "model" not in b or b["model"] is None:
            return None
        value = b["model"]
        if not isinstance(value, str) or not (value in {o["value"] for o in self.model_options()} or MODEL_NAME.fullmatch(value)):
            raise HttpError(400, "고를 수 없는 모델입니다.")
        return value

    def requested_effort(self, b: dict) -> str | None:
        """요청에 effort 가 없으면 None(서버 기본값). 있으면 허용 목록 안의 값만 받는다."""
        if "effort" not in b or b["effort"] is None:
            return None
        value = b["effort"]
        if not isinstance(value, str) or value not in EFFORT_VALUES:
            raise HttpError(400, "고를 수 없는 에포트입니다.")
        return value

    # 새 작업
    def a_new(self, g, q, b):
        text, cwd = b.get("text"), b.get("cwd")
        if not isinstance(text, str) or not text.strip():
            raise HttpError(400, "요청 글이 비어 있습니다.")
        model = self.requested_model(b)
        effort = self.requested_effort(b)
        folder = self.folder_info(cwd)
        if not folder["ok"]:
            raise HttpError(400, folder["error"])
        self.store.add_folder(folder["path"])
        return 202, {"id": self.analyses.start(text.strip(), folder["path"], model, effort, self.available_flows(folder["path"]),
                                               self.analysis_context(folder["path"]))}

    def get_job(self, jid):
        job = self.analyses.get(jid)
        if job is None:
            raise HttpError(404, "없는 분석입니다.")
        return job

    def a_new_get(self, g, q, b):
        j = self.get_job(g[0])
        out = {k: j[k] for k in ("id", "status", "text", "cwd", "result", "error")}
        tool = self.tool_skill_of(j["text"])
        if tool and out["result"]:  # 요청이 도구 스킬로 시작하면 분석이 어느 갈래로 봤든 갈래 없이 도구만 쓰는 일이다
            out["result"] = dict(out["result"], flow={"id": analysis.NO_FLOW, "name": analysis.NO_FLOW_NAME, "confident": True, "alternativeId": None,
                                                     "alternativeName": "", "reason": f"요청이 도구 스킬(/{self.plugin_name}:{tool})로 시작해요."})
        return 200, out

    def chosen_flow(self, job, b: dict) -> tuple[str | None, str]:
        """시작 때 쓸 갈래와 이유. 요청이 고른 갈래가 먼저고, 없으면 분석이 확신한 분류를 쓴다. 갈래 없이 도구만 쓰는 일(none)이면 (None, "")."""
        fid = b.get("flow")
        found = (job.get("result") or {}).get("flow") or {}
        if fid is not None:
            if fid == analysis.NO_FLOW:
                return None, ""
            if not isinstance(fid, str) or flows.flow_def(self.require_flows(), fid) is None:
                raise HttpError(400, "없는 갈래입니다.")
            return fid, str(b.get("flowReason") or (found.get("reason") if found.get("id") == fid else "") or "사용자가 고름")[:flows.MAX_REASON]
        if self.tool_skill_of(job["text"]):
            return None, ""
        if found and found.get("confident") and found["id"] != analysis.NO_FLOW:
            return found["id"], found.get("reason", "")
        return None, ""

    def preview_text(self, job, picked, extra, note, flow_id=None) -> str:
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
        first = None
        if flow_id and flow_id != analysis.NO_FLOW and self.flow_data is not None:
            flow = flows.flow_def(self.flow_data, flow_id)
            step = flow["steps"][0] if flow else None
            first = step["skill"] if step and step["kind"] == "skill" else None
        tool_only = flow_id == analysis.NO_FLOW
        return analysis.first_message(job["text"], picked, extra, note if isinstance(note, str) else "", is_git, first, tool_only)

    def a_preview(self, g, q, b):
        job = self.get_job(g[0])
        try:
            extra = json.loads(q.get("extraAnswers", ["{}"])[0])
        except ValueError:
            raise HttpError(400, "extraAnswers 가 JSON 이 아닙니다.")
        flow_id = q.get("flow", [""])[0] or None
        if flow_id and flow_id != analysis.NO_FLOW and (self.flow_data is None or flows.flow_def(self.flow_data, flow_id) is None):
            raise HttpError(400, "없는 갈래입니다.")
        return 200, {"message": self.preview_text(job, q.get("picked", []), extra, q.get("note", [""])[0], flow_id)}

    def a_start(self, g, q, b):
        job = self.get_job(g[0])
        model = self.requested_model(b)
        if model is None:
            model = job.get("model")  # 분석 때 고른 모델을 그대로 쓴다
        effort = self.requested_effort(b)
        if effort is None:
            effort = job.get("effort")
        permission = self.requested_permission(b)
        flow_id, flow_reason = self.chosen_flow(job, b)
        found = (job.get("result") or {}).get("flow") or {}
        tool_only = not flow_id and (b.get("flow") == analysis.NO_FLOW or (b.get("flow") is None and (
            bool(self.tool_skill_of(job["text"])) or (found.get("id") == analysis.NO_FLOW and bool(found.get("confident"))))))
        message = self.preview_text(job, b.get("picked") or [], b.get("extraAnswers") or {}, b.get("note") or "", analysis.NO_FLOW if tool_only else flow_id)
        with job["start_lock"]:  # 시작 버튼을 두 번 눌러도 세션은 하나만 뜬다
            sid = job.get("session_id")
            if sid is None:
                sid = self.manager.launch(job["cwd"], message, title=job["text"].split("\n", 1)[0], model=model, effort=effort, permission=permission)
                if sid is None:
                    raise HttpError(502, "claude 세션을 띄우지 못했습니다. " + platform_compat.CLAUDE_MISSING)
                job["session_id"] = sid
                self.save_last_folder(job["cwd"])
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and self.store.resolve_id(sid) == sid and sid.startswith("m-"):
            time.sleep(0.05)
        real = self.store.resolve_id(sid)
        if flow_id:
            self.assign_flow(self.get_session(real), flow_id, flow_reason)  # 안에서 refresh_git 도 한다
        else:
            self.refresh_git(real)
        return 202, {"id": real, "flowId": flow_id}

    # 폴더
    def folder_info(self, path) -> dict:
        path = platform_compat.clean_user_path(path) if isinstance(path, str) else ""
        if not path:
            return {"ok": False, "error": "경로가 비어 있습니다."}
        p = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(p):
            return {"ok": False, "error": "폴더가 아니거나 없습니다."}
        return {"ok": True, "path": p, "name": os.path.basename(p) or p, "isGit": self.git_inspect(p)["isRepo"]}

    def last_folder_file(self) -> Path | None:
        return self.store.dir / LAST_FOLDER_FILE if self.store.dir else None

    def save_last_folder(self, path: str) -> None:
        """새 작업을 시작한 폴더를 기억한다. 상태 폴더가 없는 실행(시험)에서는 메모리에만 둔다."""
        f = self.last_folder_file()
        if f is None:
            self.last_folder_mem = path
            return
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"path": path, "at": self.clock()}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, f)
        except OSError:
            pass  # 기억을 못 해도 작업 시작은 막지 않는다

    def a_last_folder(self, g, q, b):
        f = self.last_folder_file()
        path = self.last_folder_mem
        if f is not None:
            try:
                path = json.loads(f.read_text(encoding="utf-8")).get("path")
            except (OSError, ValueError, AttributeError):
                path = None
        if isinstance(path, str) and path and os.path.isdir(path):  # 지금 없는 폴더는 없는 것으로 본다
            return 200, {"path": path, "name": os.path.basename(path) or path}
        return 200, {"path": None, "name": ""}

    def a_last_folder_set(self, g, q, b):
        """첫 실행 "프로젝트 고르기"(시안 G-02)에서 고른 폴더를 마지막 폴더로 기억한다. 실제 폴더가 아니면 거부."""
        info = self.folder_info(b.get("path") if isinstance(b, dict) else None)
        if not info["ok"]:
            raise HttpError(400, info["error"])
        self.store.add_folder(info["path"])
        self.save_last_folder(info["path"])
        return 200, {"path": info["path"], "name": info["name"]}

    # 알림 설정(시안 19). 상태 폴더 아래 notify.json — 브라우저 저장소가 아니라 이 PC 의 콘솔 설정이다.
    def read_notify(self) -> dict:
        f = self.store.dir / NOTIFY_FILE if self.store.dir else None
        saved = self.notify_mem
        if f is not None:
            try:
                saved = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = None
        saved = saved if isinstance(saved, dict) else {}
        return {k: saved.get(k) is True for k in NOTIFY_KEYS}  # 파일이 깨졌거나 값이 이상하면 꺼진 것으로 본다

    def a_notify_get(self, g, q, b):
        return 200, self.read_notify()

    def a_notify_put(self, g, q, b):
        if not isinstance(b, dict) or not b:
            raise HttpError(400, "바꿀 알림 설정이 없습니다.")
        bad = [k for k, v in b.items() if k not in NOTIFY_KEYS or not isinstance(v, bool)]
        if bad:
            raise HttpError(400, f"알림 설정은 turn · blocked · done 의 true/false 만 받습니다: {', '.join(map(str, bad))}")
        now = dict(self.read_notify(), **b)
        f = self.store.dir / NOTIFY_FILE if self.store.dir else None
        if f is None:
            self.notify_mem = now
            return 200, now
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(now), encoding="utf-8")
            os.replace(tmp, f)
        except OSError as e:
            raise HttpError(500, f"알림 설정을 저장하지 못했습니다: {e}")
        return 200, now

    # 묻는 범위(시안 19). notify.json 과 같은 방식으로 상태 폴더 아래 ask.json.
    # 파일이 아예 없을 때(처음)만 기본(꼭 필요할 때만)이다. 있는데 못 읽거나 깨졌거나 값이 이상하면 가장 엄격한 all 로 본다.
    def ask_state(self) -> tuple[str, str]:
        f = self.store.dir / ASK_FILE if self.store.dir else None
        if f is None:
            saved = self.ask_mem
            if saved is None:
                return ASK_DEFAULT, ""
        else:
            try:
                saved = json.loads(f.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return ASK_DEFAULT, ""
            except (OSError, ValueError):
                return "all", ASK_UNREADABLE
        level = saved.get("level") if isinstance(saved, dict) else None
        return (level, "") if level in ASK_LEVELS else ("all", ASK_UNREADABLE)

    def read_ask(self) -> str:
        return self.ask_state()[0]

    def a_ask_get(self, g, q, b):
        level, problem = self.ask_state()
        return 200, dict({"level": level}, **({"problem": problem} if problem else {}))

    def a_ask_put(self, g, q, b):
        level = b.get("level") if isinstance(b, dict) else None
        if level not in ASK_LEVELS:
            raise HttpError(400, f"묻는 범위는 {' · '.join(ASK_LEVELS)} 중 하나여야 합니다.")
        now = {"level": level}
        f = self.store.dir / ASK_FILE if self.store.dir else None
        if f is None:
            self.ask_mem = now
            return 200, now
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(now), encoding="utf-8")
            os.replace(tmp, f)
        except OSError as e:
            raise HttpError(500, f"묻는 범위를 저장하지 못했습니다: {e}")
        return 200, now

    def folder_ready(self, path: str, wait: bool = False, fresh: bool = False) -> dict:
        """폴더 하나의 프로젝트 준비 판정. {"state": yes/no/unknown, "checking": bool}. 갈래 데이터가 없으면 확인 못 함이다.
        fresh 는 기억을 건너뛰고 지금 읽는다(첫 열기 안내처럼 틀리면 안 될 때). 아니면 cached 로 60초 기억하고, 계산 중이면 checking."""
        data = self.flow_data
        if data is None or "project-ready" not in data.get("conditions", {}):
            return {"state": COND_UNKNOWN, "checking": False}
        if fresh:
            return {"state": self.cond_state("project-ready", path, wait=False)["state"], "checking": False}
        got = self.cached(("project-ready", os.path.normcase(os.path.realpath(path))), lambda: self.cond_state("project-ready", path, wait=False), wait=wait)
        return {"state": got["state"], "checking": bool(got.get("loading"))}

    def forms_missing(self, path: str) -> dict:
        """준비된 폴더에 고객 양식 원본(templates/ 의 사무 문서)이 없는가. {"state": yes(없다)/no(있다·따질 일 아님)/unknown(못 읽음)}.
        준비 안 된 폴더, 플러그인 저장소처럼 준비 여부를 따지지 않는 곳, 준비 여부를 모르는 곳은 따질 일이 아니라 no 다(안내하지 않는다)."""
        data = self.flow_data
        spec = (data or {}).get("conditions", {}).get("project-ready")
        if spec is None or spec.get("type") != "paths":
            return {"state": COND_UNKNOWN}
        root, failed = gitstate.repo_root_checked(self.run, path)
        if failed:
            return {"state": COND_UNKNOWN}
        root = root or path
        exempt = spec.get("exemptFile")
        if (exempt and os.path.isfile(os.path.join(root, *exempt.split("/")))) or os.environ.get("HARNESS_NO_SCAFFOLD_HINT") == "1":
            return {"state": COND_NO}
        try:
            found = customer_forms(root, int(spec.get("searchDepth", 0)))
        except OSError:
            return {"state": COND_UNKNOWN}
        return {"state": COND_UNKNOWN if found is None else (COND_NO if found else COND_YES)}

    def folder_forms(self, path: str, wait: bool = False) -> dict:
        """forms_missing 을 폴더 준비 판정과 같이 60초 기억한다."""
        key = ("customer-forms", os.path.normcase(os.path.realpath(path)))
        return self.cached(key, lambda: self.forms_missing(path), wait=wait)

    def folder_sessions(self, path: str) -> int:
        """그 폴더 또는 하위 폴더를 cwd 로 가진 세션 수(끝난 세션 포함, 세션 목록과 같은 기준)."""
        with self.store.lock:
            cwds = [s["cwd"] for s in self.store.sessions.values() if s["cwd"]]
        return sum(1 for c in cwds if platform_compat.is_within(c, path))

    def a_recent(self, g, q, b):
        """최근 폴더와 폴더별 준비 판정(ready: yes/no/unknown, checking: 읽는 중이면 true)·세션 수. 판정은 기다리지 않는다."""
        with self.store.lock:
            paths = [p for p in self.store.folders if os.path.isdir(p)]
        out = []
        for p in paths:
            r = self.folder_ready(p)
            # 양식 안내는 준비됨일 때만 따진다. 준비 판정이 아직 읽는 중이면 양식도 읽지 않는다(둘 다 기다리지 않는다).
            forms = self.folder_forms(p)["state"] if r["state"] == COND_YES and not r["checking"] else COND_NO
            out.append({"path": p, "name": os.path.basename(p) or p, "ready": r["state"], "checking": r["checking"], "sessions": self.folder_sessions(p),
                        "formsMissing": forms})
        return 200, out

    # ---- 폴더별 첫 열기 안내(시안 03) ----
    def intro_file(self) -> Path | None:
        return self.store.dir / FOLDER_INTRO_FILE if self.store.dir else None

    def intro_list(self) -> list:
        f = self.intro_file()
        if f is None:
            return list(self.folder_intro_mem)
        try:
            rows = json.loads(f.read_text(encoding="utf-8")).get("folders", [])
        except (OSError, ValueError, AttributeError):
            return []
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("path"), str)] if isinstance(rows, list) else []

    def intro_key(self, path: str) -> str:
        return os.path.normcase(os.path.realpath(path))

    def intro_seen(self, path: str) -> bool:
        key = self.intro_key(path)
        return any(r["path"] == key for r in self.intro_list())

    def mark_intro_seen(self, path: str) -> None:
        key = self.intro_key(path)
        with self.intro_lock:
            rows = [r for r in self.intro_list() if r["path"] != key] + [{"path": key, "at": self.clock()}]
            rows = rows[-FOLDER_INTRO_MAX:]
            f = self.intro_file()
            if f is None:
                self.folder_intro_mem = rows
                return
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps({"folders": rows}, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, f)

    def a_folder_intro(self, g, q, b):
        """고른 폴더가 준비 안 됐고(no) 이 안내를 본 적이 없으면 show: true. 확인 못 함(unknown)이면 안내하지 않는다."""
        if not q.get("path"):
            raise HttpError(400, "path 가 필요합니다.")
        root = self.known_root(q["path"][0])
        state = self.folder_ready(root, fresh=True)["state"]
        return 200, {"ready": state, "seen": self.intro_seen(root), "show": state == COND_NO and not self.intro_seen(root)}

    def a_folder_intro_seen(self, g, q, b):
        root = self.known_root(b.get("path"))
        try:
            self.mark_intro_seen(root)
        except OSError as e:
            raise HttpError(500, f"안내 표시를 남기지 못했습니다: {e}")
        return 200, {"seen": True}

    def a_pick(self, g, q, b):
        """서버를 돌리는 컴퓨터에 OS 폴더 선택 창을 띄운다. 쿠키로 인증한 로컬 사용자만 부를 수 있다."""
        if not self.pick_lock.acquire(blocking=False):
            raise HttpError(409, "폴더 선택 창이 이미 열려 있습니다. 열린 창에서 고르거나 닫아 주세요.")
        start = b.get("path")
        start = start if isinstance(start, str) and 0 < len(start) <= 1024 and os.path.isdir(start) else None
        try:
            try:
                path = self.folder_picker(start=start) if start else self.folder_picker()
            except platform_compat.PickUnavailable as e:
                raise HttpError(503, str(e))
        finally:
            self.pick_lock.release()
        if path is None:
            return 200, {"cancelled": True}
        return 200, {"path": path}

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


def tb(fn):
    """문제·해결 기록 API(trouble.py)의 오류를 HttpError 로 바꾼다."""
    def call(app, g, q, b):
        try:
            return fn(app, g, q, b)
        except trouble.HttpError as e:
            raise HttpError(e.status, e.message)
    return call


S = r"([^/]+)"
ROUTES = [
    ("GET", re.compile(r"/api/trouble"), tb(trouble.a_list)),
    ("GET", re.compile(r"/api/trouble/item"), tb(trouble.a_item)),
    ("GET", re.compile(r"/api/trouble/pr"), tb(trouble.a_pr)),
    ("GET", re.compile(r"/api/trouble/similar"), tb(trouble.a_similar)),
    ("GET", re.compile(r"/api/trouble/draft"), tb(trouble.a_draft_get)),
    ("POST", re.compile(r"/api/trouble/check"), tb(trouble.a_check)),
    ("POST", re.compile(r"/api/trouble"), tb(trouble.a_create)),
    ("POST", re.compile(r"/api/trouble/comment"), tb(trouble.a_comment)),
    ("POST", re.compile(r"/api/trouble/resolve"), tb(trouble.a_resolve)),
    ("POST", re.compile(r"/api/trouble/draft"), tb(trouble.a_draft_put)),
    ("POST", re.compile(r"/api/trouble/ai-draft"), tb(trouble.a_ai_draft)),
    ("GET", re.compile(r"/api/sessions"), App.a_sessions),
    ("GET", re.compile(rf"/api/sessions/{S}"), App.a_session),
    ("POST", re.compile(rf"/api/sessions/{S}/messages"), App.a_message),
    ("POST", re.compile(rf"/api/sessions/{S}/skills/{S}/run"), App.a_run),
    ("PUT", re.compile(rf"/api/sessions/{S}/skills/{S}/reservation"), App.a_reserve),
    ("DELETE", re.compile(rf"/api/sessions/{S}/skills/{S}/reservation"), App.a_unreserve),
    ("POST", re.compile(rf"/api/sessions/{S}/interrupt"), App.a_interrupt),
    ("PUT", re.compile(rf"/api/sessions/{S}/permission"), App.a_permission),
    ("PUT", re.compile(rf"/api/sessions/{S}/flow"), App.a_flow_set),
    ("POST", re.compile(rf"/api/sessions/{S}/flow/skip"), App.a_flow_skip),
    ("POST", re.compile(rf"/api/sessions/{S}/flow/done"), App.a_flow_done),
    ("POST", re.compile(rf"/api/sessions/{S}/flow/refresh"), App.a_flow_refresh),
    ("POST", re.compile(rf"/api/sessions/{S}/flow/next"), App.a_flow_next),
    ("POST", re.compile(r"/api/jobs/([^/]+)/confirm"), App.a_job_confirm),
    ("POST", re.compile(r"/api/jobs/([^/]+)/cancel"), App.a_job_cancel),
    ("GET", re.compile(rf"/api/jobs/{S}"), App.a_job),
    ("POST", re.compile(rf"/api/sessions/{S}/reload"), App.a_reload),
    ("POST", re.compile(r"/api/reload-all"), App.a_reload_all),
    ("POST", re.compile(rf"/api/sessions/{S}/checks/{S}/skip"), App.a_check_skip),
    ("GET", re.compile(rf"/api/sessions/{S}/files"), App.a_session_files),
    ("GET", re.compile(rf"/api/sessions/{S}/files/preview"), App.a_file_preview),
    ("GET", re.compile(rf"/api/sessions/{S}/files/raw"), App.a_file_raw),
    ("POST", re.compile(rf"/api/sessions/{S}/files/open"), App.a_file_open),
    ("POST", re.compile(r"/api/folders/worktree"), App.a_worktree),
    ("GET", re.compile(r"/api/flows"), App.a_flows),
    ("GET", re.compile(r"/api/approvals"), App.a_approvals),
    ("GET", re.compile(r"/api/dev-ready"), App.a_dev_ready),
    ("GET", re.compile(r"/api/srs-status"), App.a_srs_status),
    ("GET", re.compile(r"/api/start-checks"), App.a_start_checks),
    ("POST", re.compile(r"/api/start-checks/seen"), App.a_start_seen),
    ("GET", re.compile(r"/api/whats-new"), App.a_whats_new),
    ("POST", re.compile(r"/api/whats-new/seen"), App.a_whats_new_seen),
    ("GET", re.compile(rf"/api/requests/{S}"), App.a_request),
    ("POST", re.compile(rf"/api/requests/{S}/answer"), App.a_answer),
    ("POST", re.compile(r"/api/new"), App.a_new),
    ("GET", re.compile(rf"/api/new/{S}"), App.a_new_get),
    ("POST", re.compile(rf"/api/new/{S}/start"), App.a_start),
    ("GET", re.compile(rf"/api/new/{S}/preview"), App.a_preview),
    ("GET", re.compile(r"/api/folders/recent"), App.a_recent),
    ("GET", re.compile(r"/api/folders/last"), App.a_last_folder),
    ("POST", re.compile(r"/api/folders/last"), App.a_last_folder_set),
    ("GET", re.compile(r"/api/settings/notify"), App.a_notify_get),
    ("PUT", re.compile(r"/api/settings/notify"), App.a_notify_put),
    ("GET", re.compile(r"/api/settings/ask"), App.a_ask_get),
    ("PUT", re.compile(r"/api/settings/ask"), App.a_ask_put),
    ("GET", re.compile(r"/api/folders/intro"), App.a_folder_intro),
    ("POST", re.compile(r"/api/folders/intro/seen"), App.a_folder_intro_seen),
    ("POST", re.compile(r"/api/folders/validate"), App.a_validate),
    ("POST", re.compile(r"/api/folders/pick"), App.a_pick),
    ("GET", re.compile(r"/api/models"), App.a_models),
    ("GET", re.compile(r"/api/fs"), App.a_fs),
    ("GET", re.compile(r"/api/skills"), App.a_skills),
    ("GET", re.compile(r"/api/files"), App.a_files),
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

    def drain_body(self) -> None:
        """오류 응답 전에 안 읽은 요청 본문을 비운다. 남기면 Windows 가 연결을 RST 로 닫아 클라이언트가 응답을 못 받는다."""
        if getattr(self, "body_touched", False):
            return
        self.body_touched = True
        try:
            header = (self.headers.get("Content-Length") or "0").strip()
            if not header.isascii() or not header.isdigit():
                return
            remaining = min(int(header), DRAIN_LIMIT)
            deadline = time.monotonic() + DRAIN_SECONDS
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    return
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, 65536)) if hasattr(self.rfile, "read1") else self.rfile.read(min(remaining, 65536))
                if not chunk:
                    return
                remaining -= len(chunk)
        except Exception:  # 비우지 못해도 응답은 그대로 보낸다
            return

    def read_json(self, limit: int) -> dict:
        self.body_touched = True
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
        self.body_touched = False  # 요청마다 초기화한다(핸들러 하나가 연결 하나를 다루지만 keep-alive 로 바뀌어도 안전하게)
        try:
            self.dispatch()
        except HttpError as e:
            self.drain_body()
            self.send_json(e.status, {"error": e.message})
        except (BrokenPipeError, ConnectionError, TimeoutError):
            pass
        except Exception as e:  # 한 요청의 오류로 서버가 죽지 않게 한다
            try:
                self.drain_body()
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
            if isinstance(data, Raw):
                return self.send(status, data.body, data.ctype, data.headers)
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
            if re.fullmatch(r"/(fonts/)?[\w.-]+", rest):  # fonts/ 한 단계만 연다
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
    app = App(port, state, plugin_root, model=os.environ.get("HARNESS_CONSOLE_MODEL", ""),
              effort=os.environ.get("HARNESS_CONSOLE_EFFORT", ""))
    try:
        server = make_server(app)
    except OSError as e:
        reason = f"포트 {port} 를 열지 못했습니다: {type(e).__name__} {getattr(e, 'winerror', None) or e.errno or ''} {e.strerror or ''}".strip()
        if sys.stderr is not None:  # pythonw.exe 로 뜨면 stderr 가 없다
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
