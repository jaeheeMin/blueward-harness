"""콘솔이 띄운 `claude -p` 세션(web-console.md §6). 터미널 창 없이 stdin/stdout 만 쓴다."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from typing import Callable

import attachments as attachments_mod
import platform_compat
from hooks_api import tool_key
from store import CHECK_DONE, RequestLimit, Store, TITLE_PROMPT, chat_clean, mark_check, new_start_checks, prompt_title

FLAGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
         "--permission-prompt-tool", "stdio"]
# 별칭 말고 정식 이름을 직접 적을 때 받는 모양. 인자로만 넘기고 셸을 거치지 않으며, 맨 앞이 영문·숫자라 옵션으로 읽히지 않는다.
MODEL_NAME = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]{0,62}(\[1m\])?$")
# 화면에서 고를 수 있는 모델(claude --model 별칭). 빈 값은 Claude Code 설정을 따른다는 뜻이다.
MODEL_OPTIONS = [("", "기본값(Claude Code 설정을 따름)"), ("fable", "Fable"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku")]
MODEL_ALIASES = {v for v, _ in MODEL_OPTIONS if v}
# claude --effort 가 받는 단계. 빈 값은 플래그를 붙이지 않는다는 뜻이다. (값, 쉬운 이름)
EFFORT_OPTIONS = [("", "기본값"), ("low", "낮음"), ("medium", "보통"), ("high", "높음"), ("xhigh", "아주 높음"), ("max", "최대")]
EFFORT_VALUES = {v for v, _ in EFFORT_OPTIONS}
# claude --permission-mode 로 고를 수 있는 값. bypassPermissions·dontAsk 는 화면에도 서버에도 두지 않는다. 빈 값은 플래그를 붙이지 않는다.
# auto 는 AI 가 위험한 행동을 알아서 막는 모드다(#684, https://code.claude.com/docs/en/permission-modes). 못 쓰는 환경이면 AUTO_UNAVAILABLE 로 알린다.
PERMISSION_OPTIONS = [("", "기본(그때그때 확인)"), ("acceptEdits", "파일 고치기는 자동 허용"), ("plan", "계획만 세우기"),
                      ("auto", "알아서 하되 위험한 건 AI가 막기")]
PERMISSION_VALUES = {v for v, _ in PERMISSION_OPTIONS}
PERMISSION_LABELS = dict(PERMISSION_OPTIONS)
# 살아 있는 세션에 set_permission_mode 를 보내고 control_response 를 기다리는 시간(초). 빈 값(기본)은 claude 쪽 이름 default 로 보낸다.
MODE_REPLY_WAIT = 8.0
AUTO_MODE = "auto"
AUTO_UNAVAILABLE = ("auto 모드를 쓸 수 없는 것 같아. 관리자가 꺼 뒀거나, 이 모델·Claude Code 판이 지원하지 않을 수 있어. "
                    "그래서 다른 모드로 시작됐어. 이유는 확인 못 함")
DEFAULT_MODE_NAME = "default"
# 플러그인 다시 불러오기: control_request(reload_plugins) 가 안 되면 user 메시지 /reload-plugins 로 대신한다(모델 비용 없는 합성 응답).
RELOAD_SUBTYPE = "reload_plugins"
RELOAD_COMMAND = "/reload-plugins"
RELOAD_REPLY_WAIT = 20.0
RELOAD_MESSAGE_WAIT = 60.0
RELOAD_POLL = 0.05
RELOADED = re.compile(r"Reloaded:\s*\d+\s+plugins?", re.IGNORECASE)
RELOAD_ERRORS = re.compile(r"(\d+)\s+errors?", re.IGNORECASE)


def classify_api_error(error, status) -> str:
    """claude 가 알려 준 API 오류 이름·상태 번호를 화면 종류로 나눈다(#865). 모르는 모양은 other 로 두고 성공으로 치지 않는다.
    auth(로그인) · limit(사용 한도) · model(없는 모델) · other(그 밖의 API 오류)."""
    name = str(error or "")
    code = status if isinstance(status, int) and not isinstance(status, bool) else None
    if name == "authentication_failed" or code == 401:
        return "auth"
    if name == "rate_limit" or code == 429:
        return "limit"
    if name == "model_not_found" or code == 404:
        return "model"
    return "other"


def issue_text(value) -> str:
    return value.strip()[:600] if isinstance(value, str) else ""


def parse_line(line: str):
    """stdout 한 줄을 JSON 객체로 읽는다. 깨진 줄은 None 이라서 건너뛴다."""
    line = line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def user_message(text: str, attachments: list[dict] | None = None) -> str:
    """첨부가 있으면 content 를 [image|document 블록…, text 블록] 배열로 보낸다(attachments.content_blocks)."""
    content = attachments_mod.content_blocks(text, attachments) if attachments else text
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False) + "\n"


def summarize_tool(name: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "pattern", "skill", "description"):
            if isinstance(tool_input.get(key), str):
                return f"{name}: {tool_input[key][:120]}"
    return name


def plugin_list(raw) -> list[dict]:
    """claude 가 알려 준 플러그인 목록을 [{name, version}] 으로 줄인다. 모양이 다르면 빈 목록."""
    if not isinstance(raw, list):
        return []
    return [{"name": p["name"], "version": str(p["version"]) if p.get("version") is not None else ""}
            for p in raw if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"]]


class Proc:
    """프로세스 하나와 읽기 스레드."""

    def __init__(self, manager: "Manager", temp_id: str, popen):
        self.manager, self.temp_id, self.p = manager, temp_id, popen
        self.session_id: str | None = None
        self.write_lock = threading.Lock()
        self.reload_lock = threading.Lock()
        self.results = 0  # 받은 result 이벤트 수. 보낸 메시지의 턴이 끝났는지 이 수가 늘었는지로 안다
        self.last_result = ""
        self.last_error = False
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def alive(self) -> bool:
        return self.p.poll() is None

    def write(self, text: str) -> bool:
        with self.write_lock:
            try:
                self.p.stdin.write(text)
                self.p.stdin.flush()
                return True
            except (OSError, ValueError):
                return False

    def _read(self) -> None:
        try:
            for line in self.p.stdout:
                event = parse_line(line)
                if event is not None:
                    try:
                        self.manager.on_event(self, event)
                    except Exception as e:  # 한 줄 때문에 읽기를 멈추지 않는다
                        self.manager.log(self, f"이벤트 처리 오류: {e}")
        except (OSError, ValueError):
            pass
        # 읽기가 끝났으면(EOF) 자식 파이프를 닫는다. 안 닫으면 오래 켜 둔 콘솔에 파일 핸들이 쌓인다(#823).
        # stdin 은 write() 와 겹치지 않게 같은 잠금 안에서 닫는다(닫힌 뒤 write() 는 False).
        with self.write_lock:
            for pipe in (self.p.stdout, self.p.stdin):
                close = getattr(pipe, "close", None)  # 시험의 가짜 프로세스는 stdout 이 줄 목록이라 close 가 없다
                try:
                    if close is not None:
                        close()
                except (OSError, ValueError) as e:
                    self.manager.log(self, f"파이프 닫기 실패: {e}")
        self.manager.on_exit(self)


class Manager:
    def __init__(self, store: Store, claude_cmd: Callable[[], list[str] | None], plugin_dir: str,
                 model: str = "", popen=subprocess.Popen, stderr_log=None, effort: str = ""):
        self.store = store
        self.claude_cmd = claude_cmd
        self.plugin_dir = plugin_dir
        self.model = model
        self.effort = effort
        self.popen = popen
        self.procs: dict[str, Proc] = {}  # 현재 id(임시 또는 실제) -> Proc
        # 잠금 순서: 세션 잠금 -> store.lock. manager.lock 은 procs/세션 잠금 표만 지키는 잎(leaf) 잠금이라
        # 쥔 채로 store 를 부르지 않는다(교착 방지).
        self.lock = threading.Lock()
        self.session_locks: dict[str, threading.RLock] = {}
        self.stderr_log = stderr_log
        self.mode_waits: dict[str, dict] = {}  # request_id -> {"event", "response"}. manager.lock 으로 지킨다
        # 서버가 끼워 준다(hooks_api.Hooks). 없으면 묻지 않고 허용하는 일이 없고 위험 표시도 없다.
        self.auto_allowed: Callable[[dict, str, object], bool] | None = None
        self.risk_of: Callable[[dict, str, object], tuple[str, str]] | None = None

    # ---- 시작 ----
    def command(self, resume: str | None = None, model: str | None = None, effort: str | None = None,
                permission: str | None = None) -> list[str] | None:
        """model·effort 가 None 이면 서버 기본값, 빈 문자열이면 --model·--effort 를 붙이지 않는다.
        permission 은 None 이거나 빈 문자열이면 --permission-mode 를 붙이지 않는다(기본값은 서버 쪽에 없다)."""
        base = self.claude_cmd()
        if not base:
            return None
        args = [*base, *FLAGS, "--plugin-dir", self.plugin_dir]
        chosen = self.model if model is None else model
        # 저장된 값이 상태 파일에서 어긋났을 수 있어 여기서 한 번 더 검사하고, 어긋나면 그 플래그만 뺀다.
        if chosen and chosen != self.model and chosen not in MODEL_ALIASES and not MODEL_NAME.fullmatch(chosen):
            self._warn(resume, f"모델 값이 허용 형식이 아니라 --model 을 뺐다: {chosen[:60]!r}")
            chosen = ""
        if chosen:
            args += ["--model", chosen]
        level = self.effort if effort is None else effort
        if level and level not in EFFORT_VALUES:
            self._warn(resume, f"에포트 값이 허용 단계가 아니라 --effort 를 뺐다: {level[:60]!r}")
            level = ""
        if level:
            args += ["--effort", level]
        if permission and permission not in PERMISSION_VALUES:
            self._warn(resume, f"권한 모드 값이 허용 집합이 아니라 --permission-mode 를 뺐다: {permission[:60]!r}")
            permission = ""
        if permission:
            args += ["--permission-mode", permission]
        if resume:
            args += ["--resume", resume]
        return args

    def _warn(self, sid: str | None, text: str) -> None:
        """세션 기록에 남긴다. 세션이 아직 없으면 표준 오류로 낸다."""
        with self.store.lock:
            s = self.store.get(sid) if sid else None
            if s is not None:
                self.store.add_log(s, text)
                return
        print("[console] " + text, file=sys.stderr)

    def session_lock(self, key: str):
        with self.lock:
            return self.session_locks.setdefault(key, threading.RLock())

    def remembered_model(self, sid: str) -> str | None:
        """세션에 기억된 모델 별칭. 기억이 없는 옛 세션이면 None(서버 기본값을 따른다)."""
        with self.store.lock:
            s = self.store.get(sid)
            value = s.get("modelChoice") if s is not None else None
        return value if isinstance(value, str) else None

    def remembered_effort(self, sid: str) -> str | None:
        """세션에 기억된 에포트. 기억이 없는 옛 세션이면 None(서버 기본값을 따른다)."""
        with self.store.lock:
            s = self.store.get(sid)
            value = s.get("effortChoice") if s is not None else None
        return value if isinstance(value, str) else None

    def remembered_permission(self, sid: str) -> str | None:
        """세션에 기억된 권한 모드. 기억이 없는 옛 세션이면 None(아무것도 안 붙인다)."""
        with self.store.lock:
            s = self.store.get(sid)
            value = s.get("permissionChoice") if s is not None else None
        return value if isinstance(value, str) else None

    def launch(self, cwd: str, first_message: str | None, resume: str | None = None, title: str = "",
               model: str | None = None, effort: str | None = None, permission: str | None = None,
               attachments: list[dict] | None = None) -> str | None:
        """세션을 띄우고 첫 메시지를 보낸다. 세션 id(임시 또는 실제)를 돌려준다. 못 띄우면 None.
        model 은 --model 별칭이다. 이어서 띄울 때(resume) 안 주면 그 세션에 기억된 모델을 쓴다.
        같은 세션을 다시 띄우는 요청(resume)은 세션 단위로 직렬화하고, 이미 살아 있으면 새로 띄우지 않고 메시지만 보낸다."""
        if resume:
            with self.session_lock(resume):
                if self.alive(resume):
                    if (first_message or attachments) and not self.send(resume, first_message or "", attachments):
                        return None
                    return self.store.resolve_id(resume)
                return self._launch(cwd, first_message, resume, title, model, effort, permission, attachments)
        return self._launch(cwd, first_message, resume, title, model, effort, permission, attachments)

    def _launch(self, cwd: str, first_message: str | None, resume: str | None, title: str, model: str | None,
                effort: str | None = None, permission: str | None = None, attachments: list[dict] | None = None) -> str | None:
        if model is None and resume:
            model = self.remembered_model(resume)
        if effort is None and resume:
            effort = self.remembered_effort(resume)
        if permission is None and resume:
            permission = self.remembered_permission(resume)
        args = self.command(resume, model, effort, permission)
        if args is None:
            return None
        try:
            p = self.popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr_log or subprocess.DEVNULL,
                           cwd=cwd, text=True, encoding="utf-8", errors="replace", bufsize=1,
                           **platform_compat.hidden_window_kwargs())
        except OSError:
            return None
        temp = resume or ("m-" + uuid.uuid4().hex[:10])
        with self.store.lock:
            s = self.store.ensure(temp, cwd)
            s.update(managed=True, starting=True, ended=False, managed_alive=True)
            s["modelChoice"] = self.model if model is None else model
            s["effortChoice"] = self.effort if effort is None else effort
            s["permissionChoice"] = permission or ""
            if not resume:
                s["startChecks"] = new_start_checks()  # 새 세션 점검 체크리스트(이어서 띄운 세션에는 새로 만들지 않는다)
            title = prompt_title(title) if title else ""
            if title:
                self.store.set_title(s, title, TITLE_PROMPT)
        proc = Proc(self, temp, p)
        proc.session_id = resume
        with self.lock:
            self.procs[temp] = proc
        if first_message or attachments:
            self.send(temp, first_message or "", attachments)
        self.store.touch(s)
        self.store.touch_peers(s)
        return temp

    # ---- 보내기 ----
    def proc_for(self, sid: str) -> Proc | None:
        real = self.store.resolve_id(sid)  # store.lock 은 manager.lock 밖에서 잡는다
        with self.lock:
            return self.procs.get(real) or self.procs.get(sid)

    def send(self, sid: str, text: str, attachments: list[dict] | None = None) -> bool:
        proc = self.proc_for(sid)
        if proc is None or not proc.alive():
            return False
        with self.store.lock:
            s = self.store.get(sid)
            if s is not None:
                s.pop("interrupted", None)
                s.pop("apiIssue", None)  # 새로 시키면 앞의 오류 안내는 닫고, 또 나면 다시 띄운다
                names = ", ".join(a["name"] for a in attachments or [])
                self.store.add_log(s, "보냄: " + (text.split("\n", 1)[0][:200] or "(글 없음)") + (f" + 첨부 {len(attachments)}개({names[:100]})" if attachments else ""))
                if attachments:  # 기록에는 이름·형식·크기만 남기고 base64 원본은 넣지 않는다
                    self.store.add_chat(s, "me", chat_clean(text) or "(첨부만 보냄)", attachments=attachments_mod.meta(attachments))
                else:
                    self.store.add_chat(s, "me", chat_clean(text))
                if s.get("title_rank", 0) < TITLE_PROMPT:
                    title = prompt_title(text)
                    if title:
                        self.store.set_title(s, title, TITLE_PROMPT)
        return proc.write(user_message(text, attachments))

    def interrupt(self, sid: str) -> bool:
        proc = self.proc_for(sid)
        if proc is None or not proc.alive():
            return False
        req = {"type": "control_request", "request_id": uuid.uuid4().hex[:8], "request": {"subtype": "interrupt"}}
        with self.store.lock:
            s = self.store.get(sid)
            if s is not None:
                s["interrupted"] = True
        return proc.write(json.dumps(req) + "\n")

    def set_permission(self, sid: str, mode: str) -> dict:
        """세션 도중 권한 모드를 바꾼다. mode 는 PERMISSION_VALUES 안의 값이어야 한다(호출한 쪽이 400 으로 거른다).
        살아 있으면 control_request(set_permission_mode) 를 보내 응답을 기다리고, 끝난 세션이면 다음 resume 때 쓸 값만 갱신한다.
        돌려주는 dict: ok, live, previous, mode / 실패면 ok=False 와 error."""
        proc = self.proc_for(sid)
        real = self.store.resolve_id(sid)
        previous = self.remembered_permission(real) or ""
        live = bool(proc and proc.alive())
        if live:
            request_id = uuid.uuid4().hex[:8]
            wait = {"event": threading.Event(), "response": None}
            with self.lock:
                self.mode_waits[request_id] = wait
            req = {"type": "control_request", "request_id": request_id,
                   "request": {"subtype": "set_permission_mode", "mode": mode or DEFAULT_MODE_NAME}}
            try:
                if not proc.write(json.dumps(req) + "\n"):
                    return {"ok": False, "live": True, "error": "실행 중인 프로세스에 보내지 못했어."}
                if not wait["event"].wait(MODE_REPLY_WAIT):
                    return {"ok": False, "live": True, "error": "세션이 권한 모드 변경에 답하지 않았어."}
            finally:
                with self.lock:
                    self.mode_waits.pop(request_id, None)
            response = wait["response"] or {}
            if response.get("subtype") != "success":
                detail = str(response.get("error") or "알 수 없는 오류")[:200]
                if mode == AUTO_MODE:
                    detail = f"{AUTO_UNAVAILABLE.split('. ', 1)[0]}. 원문: {detail}"
                self._warn(real, f"권한 모드를 바꾸지 못함: {detail}")
                return {"ok": False, "live": True, "error": detail}
        with self.store.lock:
            s = self.store.get(real)
            if s is None:
                return {"ok": False, "live": live, "error": "없는 세션이야."}
            s["permissionChoice"] = mode
            s["permissionNote"] = ""
            if live:
                s["permissionMode"] = mode or DEFAULT_MODE_NAME
            if mode != previous:
                self.store.add_log(s, f"권한 모드: {PERMISSION_LABELS.get(previous, previous)} → {PERMISSION_LABELS.get(mode, mode)}"
                                   + ("" if live else " (다음에 이어서 띄울 때 적용)"))
        self.store.touch(s)
        return {"ok": True, "live": live, "previous": previous, "mode": mode}

    def alive(self, sid: str) -> bool:
        proc = self.proc_for(sid)
        return bool(proc and proc.alive())

    def result_marker(self, sid: str):
        """(프로세스, 지금까지 받은 result 수). 이 뒤에 보낸 메시지의 턴이 끝났는지 result_after 로 본다."""
        proc = self.proc_for(sid)
        return proc, (proc.results if proc is not None else 0)

    def result_after(self, sid: str, marker) -> tuple[bool, str, bool, str]:
        """(끝났는가, 결과 글, 오류인가, 못 기다리는 사유). 사유가 있으면 더 기다려도 소용없다(프로세스가 끝남).
        프로세스가 새로 떴으면(이어서 띄움) 그 프로세스의 첫 result 부터 센다."""
        proc0, before = marker
        proc = self.proc_for(sid)
        if proc is None:
            return False, "", False, "세션 프로세스가 없어."
        base = before if proc is proc0 else 0
        if proc.results > base:
            return True, proc.last_result, proc.last_error, ""
        if not proc.alive():
            return False, "", False, "세션 프로세스가 끝났어."
        return False, "", False, ""

    # ---- 플러그인 다시 불러오기 ----
    def control_call(self, proc: Proc, request: dict, wait_seconds: float) -> dict:
        """control_request 를 보내고 control_response 를 기다린다. {"ok", "response"(성공 때 본문 dict), "error"}."""
        request_id = uuid.uuid4().hex[:8]
        wait = {"event": threading.Event(), "response": None}
        with self.lock:
            self.mode_waits[request_id] = wait
        try:
            if not proc.write(json.dumps({"type": "control_request", "request_id": request_id, "request": request}) + "\n"):
                return {"ok": False, "error": "실행 중인 프로세스에 보내지 못했어."}
            if not wait["event"].wait(wait_seconds):
                return {"ok": False, "error": "세션이 답하지 않았어."}
        finally:
            with self.lock:
                self.mode_waits.pop(request_id, None)
        response = wait["response"] or {}
        if response.get("subtype") != "success":
            return {"ok": False, "error": str(response.get("error") or "알 수 없는 오류")[:200]}
        inner = response.get("response")
        return {"ok": True, "response": inner if isinstance(inner, dict) else {}}

    def reload_plugins(self, sid: str) -> dict:
        """세션이 이미 띄운 플러그인을 디스크의 최신 판으로 다시 불러온다. 턴 도중이면 부르지 않는다(호출한 쪽이 끝날 때까지 기다린다).
        {"ok", "method"("control"|"message"), "plugins"[{name,version}], "errorCount", "message"?} 또는 {"ok": False, "error", "dead"?}."""
        proc = self.proc_for(sid)
        real = self.store.resolve_id(sid)
        if proc is None or not proc.alive():
            return {"ok": False, "dead": True, "error": "세션 프로세스가 끝났어."}
        with proc.reload_lock:
            got = self.control_call(proc, {"subtype": RELOAD_SUBTYPE}, RELOAD_REPLY_WAIT)
            if got["ok"]:
                count = got["response"].get("error_count")
                result = {"ok": True, "method": "control", "plugins": plugin_list(got["response"].get("plugins")),
                          "errorCount": count if isinstance(count, int) and not isinstance(count, bool) else 0}
            else:
                fallback = self._reload_by_message(proc, real)
                if not fallback["ok"]:
                    error = f"control_request: {got['error']}; {RELOAD_COMMAND}: {fallback['error']}"
                    self._warn(real, "플러그인 다시 불러오기 실패: " + error)
                    return {"ok": False, "error": error}
                result = fallback
        self._record_reload(real, result)
        return result

    def _reload_by_message(self, proc: Proc, real: str) -> dict:
        before = proc.results
        with self.store.lock:
            s = self.store.get(real)
            if s is not None:
                s["turn_running"] = True
        if not self.send(real, RELOAD_COMMAND):
            return {"ok": False, "error": "메시지를 보내지 못했어."}
        deadline = time.monotonic() + RELOAD_MESSAGE_WAIT
        while proc.results <= before:
            if not proc.alive():
                return {"ok": False, "error": "세션 프로세스가 끝났어."}
            if time.monotonic() > deadline:
                return {"ok": False, "error": "답이 오지 않았어."}
            time.sleep(RELOAD_POLL)
        text = proc.last_result
        if proc.last_error or not RELOADED.search(text):
            return {"ok": False, "error": ("이 판은 지원하지 않는 듯해: " + text.strip()[:100]) if text.strip() else "빈 응답이야."}
        errors = RELOAD_ERRORS.search(text)
        with self.store.lock:
            s = self.store.get(real)
            known = [dict(p) for p in (s.get("pluginVersions") or [])] if s is not None else []
        return {"ok": True, "method": "message", "plugins": known, "errorCount": int(errors.group(1)) if errors else 0,
                "message": text.strip()[:200]}

    def _record_reload(self, real: str, result: dict) -> None:
        with self.store.lock:
            s = self.store.get(real)
            if s is None:
                return
            if result["plugins"]:
                s["pluginVersions"] = [dict(p) for p in result["plugins"]]
            mark_check(s, "reload", CHECK_DONE)
            self.store.add_log(s, f"플러그인 다시 불러옴({result['method']}): {len(result['plugins'])}개, 오류 {result['errorCount']}개")
        self.store.touch(s)

    def resume(self, sid: str, text: str, attachments: list[dict] | None = None) -> bool:
        """끝난 세션을 --resume 으로 다시 띄우고 메시지를 보낸다."""
        with self.store.lock:
            s = self.store.get(sid)
            cwd, real = (s["cwd"], s["id"]) if s is not None else ("", "")
        if not cwd or sid.startswith("m-"):
            return False
        return self.launch(cwd, text, resume=real, attachments=attachments) is not None

    def send_or_resume(self, sid: str, text: str, attachments: list[dict] | None = None) -> bool:
        """살아 있으면 보내고, 끝났으면 --resume 으로 띄운다. 같은 세션의 동시 호출이 프로세스를 둘 띄우지 않게 직렬화한다."""
        with self.store.lock:
            s = self.store.get(sid)
            real = s["id"] if s is not None else sid
        with self.session_lock(real):
            if self.alive(real):
                return self.send(real, text, attachments)
            return self.resume(real, text, attachments)

    # ---- 읽기 ----
    def log(self, proc: Proc, text: str) -> None:
        with self.store.lock:
            s = self.store.get(proc.session_id or proc.temp_id)
            if s is not None:
                self.store.add_log(s, text)

    def on_event(self, proc: Proc, e: dict) -> None:
        if e.get("type") == "result":
            proc.last_result = e["result"] if isinstance(e.get("result"), str) else ""
            proc.last_error = bool(e.get("is_error"))
            proc.results += 1
        if e.get("type") == "control_response":
            response = e.get("response") if isinstance(e.get("response"), dict) else {}
            with self.lock:
                wait = self.mode_waits.get(response.get("request_id"))
            if wait is not None:
                wait["response"] = response
                wait["event"].set()
        sid = e.get("session_id")
        if isinstance(sid, str) and sid and proc.session_id != sid:
            proc.session_id = sid
            with self.manager_lock():
                self.procs[sid] = proc
            if proc.temp_id != sid:
                self.store.rekey(proc.temp_id, sid)
        control = None
        with self.store.lock:  # 세션 데이터 변경은 store.lock 안에서 한다. 자식 프로세스에 쓰는 일은 잠금 밖에서 한다.
            s = self.store.get(proc.session_id or proc.temp_id)
            if s is None:
                return
            s.update(managed=True, managed_alive=True)
            s["lastSignalAt"] = self.store.clock()
            kind = e.get("type")
            if kind == "system" and e.get("subtype") == "status" and isinstance(e.get("permissionMode"), str):
                s["permissionMode"] = e["permissionMode"]  # 도중에 바꾼 모드가 실제로 반영됐다는 알림
                if s.get("permissionChoice") == "plan" and e["permissionMode"] != "plan":  # 계획을 승인해 모드가 기본으로 돌아왔다(#861). 고른 값도 맞춰야 이어 띄울 때 다시 계획 모드로 가지 않는다
                    s["permissionChoice"] = ""
                    self.store.add_log(s, "계획 승인: 권한 모드가 계획만 세우기에서 " + ("기본" if e["permissionMode"] == DEFAULT_MODE_NAME else e["permissionMode"][:40]) + "(으)로 바뀜")
            if kind == "system" and e.get("subtype") == "init":
                s["starting"] = False
                s.pop("apiIssue", None)
                if isinstance(e.get("permissionMode"), str):
                    s["permissionMode"] = e["permissionMode"]
                    if s.get("permissionChoice") == AUTO_MODE:  # auto 로 시작해 달라고 했는데 다른 모드로 떴으면 쓸 수 없는 환경이다
                        if e["permissionMode"] != AUTO_MODE:
                            self._auto_note(s, f"{AUTO_UNAVAILABLE} (claude 가 알려 준 모드 원문: {e['permissionMode'][:40]})")
                        else:
                            s["permissionNote"] = ""
                if isinstance(e.get("model"), str) and e["model"]:
                    s["model"] = e["model"]
                plugins = plugin_list(e.get("plugins"))
                if plugins:  # init 에 판이 안 실려 있으면 알던 판을 지키고, 실려 있으면 새로 적는다
                    old = {p["name"]: p["version"] for p in s.get("pluginVersions") or []}
                    s["pluginVersions"] = [dict(p, version=p["version"] or old.get(p["name"], "")) for p in plugins]
            elif kind == "system" and e.get("subtype") == "api_retry":
                num = lambda v: v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None  # noqa: E731
                s["apiIssue"] = {"kind": "retry", "t": self.store.clock(), "attempt": num(e.get("attempt")), "max": num(e.get("max_retries")),
                                 "delayMs": num(e.get("retry_delay_ms")), "status": num(e.get("error_status")), "error": issue_text(e.get("error"))}
            elif kind == "rate_limit_event":
                info = e.get("rate_limit_info") if isinstance(e.get("rate_limit_info"), dict) else {}
                status = str(info.get("status") or "")
                if status in ("", "allowed"):
                    s.pop("rateLimit", None)
                else:  # allowed_warning(곧 한도) · rejected(한도 참) · 모르는 값도 그대로 실어 화면이 "알 수 없음" 으로 보이게 한다
                    reset, used = info.get("resetsAt"), info.get("utilization")
                    s["rateLimit"] = {"status": status[:40], "type": str(info.get("rateLimitType") or "")[:40], "t": self.store.clock(),
                                      "resetsAt": reset if isinstance(reset, (int, float)) and not isinstance(reset, bool) else None,
                                      "utilization": used if isinstance(used, (int, float)) and not isinstance(used, bool) else None}
            elif kind == "assistant" and (e.get("error") or e.get("is_api_error_message")):
                # claude 가 API 오류를 assistant 글처럼 내보낸 것. 대화의 AI 말로 쓰지 않고 오류 카드로만 알린다(#865)
                texts = [str(b.get("text", "")) for b in (e.get("message") or {}).get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
                status = e.get("api_error_status")
                s["apiIssue"] = {"kind": classify_api_error(e.get("error"), status), "t": self.store.clock(),
                                 "status": status if isinstance(status, int) and not isinstance(status, bool) else None,
                                 "error": issue_text(e.get("error")), "raw": issue_text("\n".join(texts))}
            elif kind == "assistant":
                if (s.get("apiIssue") or {}).get("kind") == "retry":
                    s.pop("apiIssue", None)  # 다시 시도가 통해 답이 왔다
                for block in (e.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        s["currentAction"] = summarize_tool(str(block.get("name", "")), block.get("input"))
                    elif block.get("type") == "text" and block.get("text"):
                        self.store.add_log(s, "Claude Code: " +str(block["text"]).strip().split("\n", 1)[0][:200])
                        self.store.add_chat(s, "ai", str(block["text"]))
            elif kind == "result":
                s["currentAction"] = ""
                s["turn_running"] = False
                failed = bool(e.get("is_error"))  # 오류 result 도 subtype 은 success 라서 is_error 로 가린다(#865)
                if not failed:
                    s.pop("apiIssue", None)  # 이번 턴이 정상으로 끝나면 앞의 오류·재시도 안내는 닫는다
                if isinstance(e.get("result"), str) and e["result"] and not s.get("reportFresh") and not failed:
                    s["report"] = e["result"]  # Stop 훅이 이번 턴에 못 왔을 때를 위한 대비(턴마다 reportFresh 를 비우므로 이후 턴도 반영된다)
                    s["reportFresh"] = True
                    self.store.add_chat(s, "ai", e["result"])
                if s.pop("interrupted", False):
                    self.store.add_log(s, "사용자가 작업을 중단했어.")
                elif failed:
                    detail = str(e.get("result") or e.get("subtype") or "").strip()
                    self.store.add_log(s, "오류로 끝남" + (": " + detail[:200] if detail else ""))
                    if s.get("permissionChoice") == AUTO_MODE and "auto" in detail.lower():
                        self._auto_note(s, f"{AUTO_UNAVAILABLE} (claude 가 낸 메시지 원문: {detail[:300]})")
                    else:
                        s["apiIssue"] = self._failed_issue(s, e)
            elif kind == "control_request":
                control = s
        if control is not None:
            request = e.get("request") if isinstance(e.get("request"), dict) else {}
            if request.get("subtype") == "can_use_tool" and request.get("tool_name") != "AskUserQuestion":
                self._bridge_permission(proc, control, e)
            else:
                self._deny_control(proc, control, e)
        self.store.touch(control or s)

    def _failed_issue(self, s: dict, e: dict) -> dict:
        """is_error result 를 오류 카드 모델로 만든다. assistant 오류 이벤트·재시도로 이미 알던 것을 이어받는다.
        API 오류라는 표시(terminal_reason·상태 번호·앞선 오류 이벤트·재시도)가 없는 모양은 unknown 으로 두고 성공으로 치지 않는다. store.lock 안에서 부른다."""
        prev = s.get("apiIssue") if isinstance(s.get("apiIssue"), dict) else {}
        status = e.get("api_error_status") if isinstance(e.get("api_error_status"), int) and not isinstance(e.get("api_error_status"), bool) else prev.get("status")
        raw = issue_text(e.get("result")) or prev.get("raw", "")
        base = {"t": self.store.clock(), "status": status, "raw": raw}
        if prev.get("kind") in ("auth", "limit", "model", "other"):
            return dict(prev, **base, kind=classify_api_error(prev.get("error"), status) if prev.get("error") or status else prev["kind"])
        if prev.get("kind") == "retry":  # 다시 시도를 다 쓰고 끝났다
            return dict(base, kind=classify_api_error(prev.get("error"), status), error=prev.get("error", ""), attempt=prev.get("attempt"), max=prev.get("max"))
        if e.get("terminal_reason") == "api_error" or status is not None:
            return dict(base, kind=classify_api_error("", status), error="")
        return dict(base, kind="unknown", error=issue_text(e.get("subtype")), reason=issue_text(e.get("terminal_reason")))

    def _auto_note(self, s: dict, text: str) -> None:
        """auto 모드를 못 쓴 사정을 세션 기록과 화면(permissionNote)에 쉬운 말로 남긴다. store.lock 안에서 부른다."""
        s["permissionNote"] = text
        self.store.add_log(s, "권한 모드 auto: " + text)

    def _deny_control(self, proc: Proc, s: dict, e: dict) -> None:
        """can_use_tool 이 아니거나 우리가 다루지 못하는 요청은 거부로 답하고 로그에 남긴다."""
        req = e.get("request") if isinstance(e.get("request"), dict) else {}
        with self.store.lock:
            self.store.add_log(s, f"처리할 수 없는 권한 요청을 거부함: {req.get('tool_name', '?')}")
        self._control_reply(proc, e, {"behavior": "deny", "message": "콘솔이 처리하지 못하는 요청이라 거부했습니다."})

    def _control_reply(self, proc: Proc, e: dict, response: dict) -> None:
        reply = {"type": "control_response", "response": {"subtype": "success", "request_id": e.get("request_id"), "response": response}}
        proc.write(json.dumps(reply, ensure_ascii=False) + "\n")

    def _bridge_permission(self, proc: Proc, s: dict, e: dict) -> None:
        """[실제 시험] 훅이 답을 기다리는 동안에도 claude 는 같은 승인을 control_request 로 동시에 보낸다.
        바로 거부하면 사용자가 허용해도 도구가 막히므로, 훅과 같은 요청으로 합쳐 같은 답을 돌려준다."""
        req = e["request"]
        tool, tool_input = str(req.get("tool_name", "")), req.get("input")
        if self.auto_allowed is not None and self.auto_allowed(s, tool, tool_input):  # 묻지 않고 허용할 일(#649). 훅 쪽과 같은 판정
            self._control_reply(proc, e, {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}})
            return
        risk, note = "", ""
        if self.risk_of is not None:
            risk, note = self.risk_of(s, tool, tool_input)
        try:
            r, created = self.store.add_request(s["id"], "permission", tool, tool_input, req.get("permission_suggestions"),
                                                tool_key(tool, tool_input), risk=risk, risk_note=note)
        except RequestLimit:  # 조용히 허용하지 않고 거부한다
            with self.store.lock:
                self.store.add_log(s, f"대기 요청이 너무 많아 거부함: {tool}")
            self._control_reply(proc, e, {"behavior": "deny", "message": "대기 중인 승인 요청이 너무 많아 거부했습니다."})
            return
        if created:
            with self.store.lock:
                self.store.add_log(s, f"승인 요청: {tool}")

        def answer() -> None:
            while not r.event.wait(1.0):
                if not proc.alive():
                    return
            decision = {}
            if r.status == "answered" and isinstance(r.response, dict):
                decision = r.response.get("hookSpecificOutput", {}).get("decision", {})
            if decision.get("behavior") == "allow":
                response = {"behavior": "allow", "updatedInput": tool_input if isinstance(tool_input, dict) else {}}
                if decision.get("updatedPermissions"):
                    response["updatedPermissions"] = decision["updatedPermissions"]
            else:
                response = {"behavior": "deny", "message": decision.get("message") or "요청이 닫혀 거부했습니다."}
            self._control_reply(proc, e, response)

        threading.Thread(target=answer, daemon=True).start()

    def manager_lock(self):
        return self.lock

    def on_exit(self, proc: Proc) -> None:
        with self.store.lock:
            s = self.store.get(proc.session_id or proc.temp_id)
            if s is None:
                return
            if s.get("starting") and s.get("permissionChoice") == AUTO_MODE:  # 시작 신호(init)도 못 보내고 끝났다
                raw = proc.last_result.strip()[:300]
                self._auto_note(s, f"auto 모드로 시작하다 끝났어. {AUTO_UNAVAILABLE.split('. ', 1)[0]}. "
                                   + (f"claude 가 낸 메시지 원문: {raw}" if raw else "claude 가 남긴 메시지가 없어서 이유는 확인 못 함"))
            s.update(managed_alive=False, starting=False, turn_running=False, ended=True)
            self.store.close_session(s["id"], "세션이 끝나서 닫힘")
            self.store.add_log(s, "세션 프로세스가 끝남")
        self.store.touch(s)
        self.store.touch_peers(s)

    # ---- 종료 ----
    def close(self, proc: Proc, wait: float = 5.0) -> None:
        try:
            proc.p.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            proc.p.wait(wait)
        except subprocess.TimeoutExpired:
            platform_compat.terminate(proc.p)
            try:
                proc.p.wait(wait)
            except subprocess.TimeoutExpired:
                proc.p.kill()

    def shutdown(self) -> None:
        with self.lock:
            procs = {id(p): p for p in self.procs.values()}.values()
        for proc in list(procs):
            if proc.alive():
                self.close(proc)
