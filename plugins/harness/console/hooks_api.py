"""`/hooks/*` 판단 로직(web-console.md §5). 응답을 오래 붙드는 훅 연결은 요청 객체의 event 를 기다린다."""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from store import (MAX_CHANGED_FILES, MAX_PENDING_STOP, MAX_PR_LINKS, MAX_SKILL_STATES, MAX_SUBAGENTS, RequestLimit, Store,
                   TITLE_PROMPT, TITLE_SESSION)

QUESTION_WAIT = 300.0
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

Reply = tuple[int, "dict | None"]  # (HTTP 상태, 본문). 본문 None 은 빈 2xx


def permission_reply(response: dict) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": response}}


def question_reply(questions, answers: dict) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "updatedInput": {"questions": questions, "answers": answers}}}


def stop_block(reason: str) -> dict:
    return {"decision": "block", "reason": reason}


def tool_key(tool_name, tool_input) -> str:
    return tool_name + "\0" + json.dumps(tool_input, sort_keys=True, ensure_ascii=False, default=str)


class Hooks:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time, poll: float = 0.5,
                 question_wait: float = QUESTION_WAIT, refresh_git: Callable[[str], None] | None = None):
        self.store = store
        self.clock = clock
        self.poll = poll
        self.question_wait = question_wait
        self.refresh_git = refresh_git or (lambda sid: None)

    # ---- 진입 ----
    def handle(self, name: str, body: dict, alive: Callable[[], bool] = lambda: True, undo: list | None = None,
               ts: float | None = None) -> Reply:
        """undo 에 함수를 넣어 두면 호출한 쪽이 응답 전송에 실패했을 때 그 함수들을 불러 상태를 되돌린다(Stop 의 예약 항목).

        ts 는 hook_post.py 가 훅이 뜬 때 찍은 시각이다. 상태를 모으기만 하는 이벤트는 비동기로 돌아 Stop 보다 늦게 도착할 수 있어서,
        이 시각으로 "이미 끝난 턴의 늦은 이벤트" 를 가려낸다. 없으면(옛 호출자) 도착 순서를 그대로 믿는다."""
        if not isinstance(ts, (int, float)) or isinstance(ts, bool) or ts != ts or ts in (float("inf"), float("-inf")):
            ts = None
        sid = body.get("session_id")
        if not isinstance(sid, str) or not sid:
            return 400, {"error": "session_id 가 없습니다."}
        cwd = body.get("cwd") if isinstance(body.get("cwd"), str) else ""
        if name not in ("permission", "question", "stop", "event"):
            return 404, {"error": "알 수 없는 훅 경로입니다."}
        waits = name in ("permission", "question")
        with self.store.lock:  # 세션 데이터를 바꾸는 동안 저장·화면 변환이 중간 상태를 읽지 않게 한다
            s = self.store.ensure(sid, cwd)
            s["lastSignalAt"] = self.clock()
            mode = body.get("permission_mode")
            if isinstance(mode, str):
                s["permissionMode"] = mode
            if not waits:
                return self.stop(s, body, undo, ts) if name == "stop" else self.event(s, body, ts)
        return self.permission(s, body, alive) if name == "permission" else self.question(s, body, alive)

    # ---- 기다리기 ----
    def wait(self, req, alive: Callable[[], bool], deadline: float | None = None) -> None:
        """답이 오거나, 닫히거나, 연결이 끊기거나, 마감이 되면 돌아온다. 같은 요청에 붙은 연결이 모두 끊겨야 요청을 닫는다."""
        with self.store.lock:
            req.waiters += 1
        try:
            while True:
                if req.event.wait(self.poll):
                    return
                if not alive():
                    with self.store.lock:
                        others = req.waiters - 1
                    if others <= 0:
                        self.store.close(req.rid, "연결이 끊겨 닫힘(터미널에서 거부하거나 취소함)")
                    return
                if deadline is not None and self.clock() >= deadline:
                    self.store.close(req.rid, "터미널로 넘어감")
                    return
        finally:
            with self.store.lock:
                req.waiters -= 1

    def _terminal_without_browser(self, s: dict) -> bool:
        return not s["managed"] and not self.store.browser_connected()

    # ---- 승인 ----
    def permission(self, s: dict, body: dict, alive) -> Reply:
        tool = body.get("tool_name") if isinstance(body.get("tool_name"), str) else ""
        if tool == "AskUserQuestion":
            return 200, None  # 질문은 PreToolUse 훅이 맡는다
        if self._terminal_without_browser(s):
            return 200, None  # 터미널 프롬프트가 처리한다
        tool_input = body.get("tool_input")
        try:
            req, created = self.store.add_request(
                s["id"], "permission", tool, tool_input, body.get("permission_suggestions"), tool_key(tool, tool_input))
        except RequestLimit:
            self.store.add_log(s, f"대기 요청이 너무 많아 터미널로 넘김: {tool}")
            return 200, None  # 조용히 허용하지 않는다. 빈 응답은 터미널 승인 창으로 넘어간다
        if created:
            self.store.add_log(s, f"승인 요청: {tool}")
            self.store.touch(s)
        self.wait(req, alive)
        if req.status == "answered":
            return 200, req.response
        return 200, None

    # ---- 질문 ----
    def question(self, s: dict, body: dict, alive) -> Reply:
        if body.get("tool_name") != "AskUserQuestion":
            return 200, None  # 거르지 않으면 다른 도구가 깨진다
        tool_input = body.get("tool_input")
        if not isinstance(tool_input, dict) or not isinstance(tool_input.get("questions"), list):
            return 200, None
        if self._terminal_without_browser(s):
            return 200, None  # 터미널 질문창으로 넘어간다
        try:
            req, created = self.store.add_request(s["id"], "question", "AskUserQuestion", tool_input, None,
                                                  tool_key("AskUserQuestion", tool_input))
        except RequestLimit:
            self.store.add_log(s, "대기 요청이 너무 많아 질문을 터미널로 넘김")
            return 200, None
        if created:
            self.store.add_log(s, "질문이 도착함")
            self.store.touch(s)
        deadline = None if s["managed"] else self.clock() + self.question_wait
        self.wait(req, alive, deadline)
        if req.status == "answered":
            return 200, req.response
        return 200, None

    # ---- 턴 끝 ----
    def stop(self, s: dict, body: dict, undo: list | None = None, ts: float | None = None) -> Reply:
        if ts is not None:
            s["boundaryTs"] = max(ts, s.get("boundaryTs", 0.0))  # 이보다 먼저 뜬 상태 이벤트는 이 턴의 것이다
        text = body.get("last_assistant_message")
        if isinstance(text, str) and text.strip():
            s["report"] = text
        s["turn_running"] = False
        s["currentAction"] = ""
        if not s["managed"]:
            self.store.close_session(s["id"], "터미널에서 처리됨")
        for name, state in list(s["skillStates"].items()):
            if state == "active":
                s["skillStates"][name] = "done"
        s["currentSkill"] = ""
        self.refresh_git(s["id"])
        queue_ = s["pending_stop"]
        if queue_:
            item = queue_.pop(0)  # 꺼낼 때 지워서 무한 반복을 막는다. 응답 전송이 실패하면 undo 로 되돌린다.
            s["turn_running"] = True
            if undo is not None:
                undo.append(lambda: self._restore_stop(s, item))
            self.store.touch(s)
            self.store.flush()
            if item.get("kind") == "skill":
                return 200, stop_block(f"사용자가 콘솔에서 예약한 스킬을 이어서 실행하십시오: Skill 도구로 `{item['skill']}` 을 실행합니다. "
                                       + (f"인자: {item['args']}" if item.get("args") else ""))
            return 200, stop_block("사용자가 콘솔에서 보낸 요청입니다. 이어서 처리하십시오:\n" + str(item.get("text", "")))
        self.store.touch(s)
        self.store.flush()
        return 200, None

    def _restore_stop(self, s: dict, item: dict) -> None:
        """Stop 응답이 Claude Code 에 닿지 못했다. 예약 항목을 맨 앞에 되돌리고 쉬는 상태로 둔다."""
        with self.store.lock:
            if len(s["pending_stop"]) < MAX_PENDING_STOP:
                s["pending_stop"].insert(0, item)
            s["turn_running"] = False
            self.store.add_log(s, "예약 전송에 실패해 되돌림")
        self.store.touch(s)

    # ---- 그 밖의 이벤트 ----
    def event(self, s: dict, body: dict, ts: float | None = None) -> Reply:
        name = body.get("hook_event_name")
        store = self.store
        # 끝난 턴(Stop·SessionEnd)보다 먼저 떴는데 늦게 도착한 이벤트. 쉬는 세션을 다시 도는 것으로 되돌리면 안 된다.
        late = ts is not None and ts < s.get("boundaryTs", 0.0)
        if name == "SessionStart":
            s["ended"] = False
            title = body.get("session_title")
            if isinstance(title, str) and title.strip():
                store.set_title(s, title, TITLE_SESSION)
            self.refresh_git(s["id"])
            store.add_log(s, "세션 시작")
        elif name == "UserPromptSubmit":
            if not late:
                s["turn_running"], s["ended"] = True, False
            prompt = body.get("prompt") if isinstance(body.get("prompt"), str) else ""
            if not s["managed"]:
                store.close_session(s["id"], "터미널에서 처리됨", before=ts)  # 늦게 온 프롬프트가 그 뒤의 새 요청을 닫지 않게 한다
            if prompt and not prompt.lstrip().startswith("/") and s.get("title_rank", 0) < TITLE_PROMPT:
                store.set_title(s, prompt.split("\n", 1)[0], TITLE_PROMPT)
            store.add_log(s, "요청: " + prompt.split("\n", 1)[0][:200])
        elif name == "UserPromptExpansion":
            if not late:
                self._skill_started(s, body.get("command_name"))
        elif name == "PreToolUse":
            tool = str(body.get("tool_name", ""))
            tool_input = body.get("tool_input")
            if not late:
                s["turn_running"], s["ended"] = True, False
                if ts is None or ts >= s.get("actionTs", 0.0):  # 도구를 잇달아 부르면 먼저 뜬 이벤트가 늦게 올 수 있다
                    s["currentAction"] = _action(tool, tool_input)
                    if ts is not None:
                        s["actionTs"] = ts
                if tool == "Skill" and isinstance(tool_input, dict):
                    self._skill_started(s, tool_input.get("skill"))
        elif name == "PostToolUse":
            self._post_tool_use(s, body, ts)
        elif name == "SubagentStart":
            if not any(a.get("id") == body.get("agent_id") and body.get("agent_id") is not None for a in s["subagents"]):
                s["subagents"].append({"id": body.get("agent_id"), "type": body.get("agent_type"), "state": "running"})
                del s["subagents"][:-MAX_SUBAGENTS]
            store.add_log(s, "서브에이전트 시작" + (f": {body['agent_type']}" if body.get("agent_type") else ""))
        elif name == "SubagentStop":
            found = False
            for a in s["subagents"]:
                if a.get("id") == body.get("agent_id"):
                    a["state"], found = "done", True
            if not found and body.get("agent_id") is not None:  # 끝 이벤트가 시작보다 먼저 왔다. 나중에 올 시작이 다시 running 으로 만들지 못하게 남긴다.
                s["subagents"].append({"id": body.get("agent_id"), "type": body.get("agent_type"), "state": "done"})
                del s["subagents"][:-MAX_SUBAGENTS]
            store.add_log(s, "서브에이전트 끝" + (f": {body['agent_type']}" if body.get("agent_type") else ""))
        elif name == "Notification":
            store.add_log(s, "알림: " + str(body.get("message", ""))[:200])
        elif name == "PreCompact":
            store.add_log(s, "대화 압축")
        elif name == "SessionEnd":
            if ts is not None:
                s["boundaryTs"] = max(ts, s.get("boundaryTs", 0.0))
            s["ended"], s["turn_running"], s["currentAction"] = True, False, ""
            store.close_session(s["id"], "세션이 끝나서 닫힘")
            store.add_log(s, "세션 끝")
            store.flush()
        store.touch(s)
        return 200, None

    def _skill_started(self, s: dict, command) -> None:
        if not isinstance(command, str) or not command:
            return
        skill = command.split(":", 1)[-1].lstrip("/")
        for name, state in list(s["skillStates"].items()):
            if state == "active":
                s["skillStates"][name] = "done"
        if skill not in s["skillStates"] and len(s["skillStates"]) >= MAX_SKILL_STATES:
            for old in [n for n, v in s["skillStates"].items() if v != "active"][:len(s["skillStates"]) - MAX_SKILL_STATES + 1]:
                del s["skillStates"][old]
        s["skillStates"][skill] = "active"
        s["currentSkill"] = skill
        self.store.add_log(s, f"스킬 시작: {skill}")

    def _post_tool_use(self, s: dict, body: dict, ts: float | None = None) -> None:
        tool = str(body.get("tool_name", ""))
        tool_input = body.get("tool_input")
        key = tool_key(tool, tool_input)
        for r in self.store.pending_for(s["id"]):
            # 늦게 온 PostToolUse 가 그 뒤에 같은 도구·입력으로 새로 생긴 요청을 닫으면 안 된다
            if r.kind == "permission" and r.tool_name == tool and r.key == key and (ts is None or r.created <= ts):
                self.store.close(r.rid, "터미널에서 처리됨")  # 훅 연결은 끊기지 않으므로 여기서 닫는다
        if tool in EDIT_TOOLS and isinstance(tool_input, dict):
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if isinstance(path, str) and path not in s["changedFiles"] and len(s["changedFiles"]) < MAX_CHANGED_FILES:
                s["changedFiles"].append(path)
        response = body.get("tool_response")
        text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str)
        for url in PR_URL.findall(text or ""):
            if url not in s["prLinks"] and len(s["prLinks"]) < MAX_PR_LINKS:
                s["prLinks"].append(url)


def _action(tool: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "pattern", "skill", "description"):
            if isinstance(tool_input.get(key), str):
                return f"{tool}: {tool_input[key][:120]}"
    return tool
