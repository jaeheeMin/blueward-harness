"""콘솔이 띄운 `claude -p` 세션(web-console.md §6). 터미널 창 없이 stdin/stdout 만 쓴다."""
from __future__ import annotations

import json
import subprocess
import threading
import uuid
from typing import Callable

import platform_compat
from hooks_api import tool_key
from store import RequestLimit, Store, TITLE_PROMPT

FLAGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
         "--permission-prompt-tool", "stdio"]


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


def user_message(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}}, ensure_ascii=False) + "\n"


def summarize_tool(name: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "pattern", "skill", "description"):
            if isinstance(tool_input.get(key), str):
                return f"{name}: {tool_input[key][:120]}"
    return name


class Proc:
    """프로세스 하나와 읽기 스레드."""

    def __init__(self, manager: "Manager", temp_id: str, popen):
        self.manager, self.temp_id, self.p = manager, temp_id, popen
        self.session_id: str | None = None
        self.write_lock = threading.Lock()
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
        self.manager.on_exit(self)


class Manager:
    def __init__(self, store: Store, claude_cmd: Callable[[], list[str] | None], plugin_dir: str,
                 model: str = "", popen=subprocess.Popen, stderr_log=None):
        self.store = store
        self.claude_cmd = claude_cmd
        self.plugin_dir = plugin_dir
        self.model = model
        self.popen = popen
        self.procs: dict[str, Proc] = {}  # 현재 id(임시 또는 실제) -> Proc
        # 잠금 순서: 세션 잠금 -> store.lock. manager.lock 은 procs/세션 잠금 표만 지키는 잎(leaf) 잠금이라
        # 쥔 채로 store 를 부르지 않는다(교착 방지).
        self.lock = threading.Lock()
        self.session_locks: dict[str, threading.RLock] = {}
        self.stderr_log = stderr_log

    # ---- 시작 ----
    def command(self, resume: str | None = None) -> list[str] | None:
        base = self.claude_cmd()
        if not base:
            return None
        args = [*base, *FLAGS, "--plugin-dir", self.plugin_dir]
        if self.model:
            args += ["--model", self.model]
        if resume:
            args += ["--resume", resume]
        return args

    def session_lock(self, key: str):
        with self.lock:
            return self.session_locks.setdefault(key, threading.RLock())

    def launch(self, cwd: str, first_message: str | None, resume: str | None = None, title: str = "") -> str | None:
        """세션을 띄우고 첫 메시지를 보낸다. 세션 id(임시 또는 실제)를 돌려준다. 못 띄우면 None.
        같은 세션을 다시 띄우는 요청(resume)은 세션 단위로 직렬화하고, 이미 살아 있으면 새로 띄우지 않고 메시지만 보낸다."""
        if resume:
            with self.session_lock(resume):
                if self.alive(resume):
                    if first_message and not self.send(resume, first_message):
                        return None
                    return self.store.resolve_id(resume)
                return self._launch(cwd, first_message, resume, title)
        return self._launch(cwd, first_message, resume, title)

    def _launch(self, cwd: str, first_message: str | None, resume: str | None, title: str) -> str | None:
        args = self.command(resume)
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
            if title:
                self.store.set_title(s, title, TITLE_PROMPT)
        proc = Proc(self, temp, p)
        proc.session_id = resume
        with self.lock:
            self.procs[temp] = proc
        if first_message:
            self.send(temp, first_message)
        self.store.touch(s)
        return temp

    # ---- 보내기 ----
    def proc_for(self, sid: str) -> Proc | None:
        real = self.store.resolve_id(sid)  # store.lock 은 manager.lock 밖에서 잡는다
        with self.lock:
            return self.procs.get(real) or self.procs.get(sid)

    def send(self, sid: str, text: str) -> bool:
        proc = self.proc_for(sid)
        if proc is None or not proc.alive():
            return False
        with self.store.lock:
            s = self.store.get(sid)
            if s is not None:
                s.pop("interrupted", None)
                self.store.add_log(s, "보냄: " + text.split("\n", 1)[0][:200])
                if not s["title"] or s.get("title_rank", 0) < TITLE_PROMPT:
                    self.store.set_title(s, text.lstrip("/").split("\n", 1)[0], TITLE_PROMPT)
        return proc.write(user_message(text))

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

    def alive(self, sid: str) -> bool:
        proc = self.proc_for(sid)
        return bool(proc and proc.alive())

    def resume(self, sid: str, text: str) -> bool:
        """끝난 세션을 --resume 으로 다시 띄우고 메시지를 보낸다."""
        with self.store.lock:
            s = self.store.get(sid)
            cwd, real = (s["cwd"], s["id"]) if s is not None else ("", "")
        if not cwd or sid.startswith("m-"):
            return False
        return self.launch(cwd, text, resume=real) is not None

    def send_or_resume(self, sid: str, text: str) -> bool:
        """살아 있으면 보내고, 끝났으면 --resume 으로 띄운다. 같은 세션의 동시 호출이 프로세스를 둘 띄우지 않게 직렬화한다."""
        with self.store.lock:
            s = self.store.get(sid)
            real = s["id"] if s is not None else sid
        with self.session_lock(real):
            if self.alive(real):
                return self.send(real, text)
            return self.resume(real, text)

    # ---- 읽기 ----
    def log(self, proc: Proc, text: str) -> None:
        with self.store.lock:
            s = self.store.get(proc.session_id or proc.temp_id)
            if s is not None:
                self.store.add_log(s, text)

    def on_event(self, proc: Proc, e: dict) -> None:
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
            if kind == "system" and e.get("subtype") == "init":
                s["starting"] = False
                if isinstance(e.get("permissionMode"), str):
                    s["permissionMode"] = e["permissionMode"]
            elif kind == "assistant":
                for block in (e.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        s["currentAction"] = summarize_tool(str(block.get("name", "")), block.get("input"))
                    elif block.get("type") == "text" and block.get("text"):
                        self.store.add_log(s, "Claude: " + str(block["text"]).strip().split("\n", 1)[0][:200])
            elif kind == "result":
                s["currentAction"] = ""
                s["turn_running"] = False
                if isinstance(e.get("result"), str) and e["result"] and not s["report"]:
                    s["report"] = e["result"]  # Stop 훅이 못 왔을 때를 위한 대비
                if s.pop("interrupted", False):
                    self.store.add_log(s, "사용자가 작업을 중단했습니다.")
                elif e.get("is_error"):
                    detail = str(e.get("result") or e.get("subtype") or "").strip()
                    self.store.add_log(s, "오류로 끝남" + (": " + detail[:200] if detail else ""))
            elif kind == "control_request":
                control = s
        if control is not None:
            request = e.get("request") if isinstance(e.get("request"), dict) else {}
            if request.get("subtype") == "can_use_tool" and request.get("tool_name") != "AskUserQuestion":
                self._bridge_permission(proc, control, e)
            else:
                self._deny_control(proc, control, e)
        self.store.touch(control or s)

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
        try:
            r, created = self.store.add_request(s["id"], "permission", tool, tool_input, req.get("permission_suggestions"),
                                                tool_key(tool, tool_input))
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
            s.update(managed_alive=False, starting=False, turn_running=False, ended=True)
            self.store.close_session(s["id"], "세션이 끝나서 닫힘")
            self.store.add_log(s, "세션 프로세스가 끝남")
        self.store.touch(s)

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
