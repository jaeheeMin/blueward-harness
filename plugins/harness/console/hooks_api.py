"""`/hooks/*` 판단 로직(web-console.md §5). 응답을 오래 붙드는 훅 연결은 요청 객체의 event 를 기다린다."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Callable

import context_usage
import flows
import session_alive
from risk import IRREVERSIBLE, SAFE, classify, plan_dir_of
from store import (CHECK_DONE, MAX_CHANGED_FILES, MAX_PENDING_STOP, MAX_PR_LINKS, MAX_SKILL_STATES, MAX_SUBAGENTS, RequestLimit, Store,
                   TITLE_PROMPT, TITLE_SESSION, chat_clean, mark_check, prompt_title, remember_touched)

QUESTION_WAIT = 300.0
PR_URL = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
# 설정 "AI가 묻는 범위"(#649): needed 꼭 필요할 때만(기본) / edits 문서를 바꿀 때마다 / all 모든 명령마다
ASK_LEVELS = ("needed", "edits", "all")
ASK_DEFAULT = "needed"
AGENT_TOOLS = {"Agent", "Task"}  # 서브에이전트를 띄우는 도구(버전에 따라 이름이 다르다)
MAX_PENDING_AGENTS = 50  # 아직 SubagentStart 와 짝을 못 지은 Agent 호출
MAX_AGENT_TEXT = 200  # description·type 글자 상한
MAX_AGENT_PROMPT = 120  # 프롬프트는 첫 줄만, 이만큼까지

# 막힌 게 아니라 검사를 못 한 사유. 실제 훅 사유 문구로 맞췄다(checker/tests/test_web_console.py 의 대입 시험).
CANNOT_CHECK_WORDS = ("검사 불능", "확인 불능", "확인하지 못", "확인할 수 없", "판정할 수 없", "검사할 수 없", "검사하지 못",
                      "확인되지 않는 상태", "판을 정하지 못", "해석하지 못", "판정하지 못", "판단할 수 없", "알 수 없",
                      "읽지 못", "실행하지 못")
CANNOT_CHECK_CUT = ("다음:", "사유:", "자세히:")  # 이 뒤는 고치는 법·도구 출력이라 판정에 쓰지 않는다


def block_kind(reason: str) -> str:
    """막은 사유가 검사를 못 해서인지(cannot_check) 진짜 위반인지(blocked) 가른다."""
    head = reason
    for cut in CANNOT_CHECK_CUT:
        head = head.split(cut, 1)[0]
    return "cannot_check" if any(w in head for w in CANNOT_CHECK_WORDS) else "blocked"

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
                 question_wait: float = QUESTION_WAIT, refresh_git: Callable[[str], None] | None = None,
                 ask_level: Callable[[], str] | None = None):
        self.store = store
        self.ask_level = ask_level or (lambda: ASK_DEFAULT)
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
        if name not in ("permission", "question", "stop", "event", "blocked"):
            return 404, {"error": "알 수 없는 훅 경로입니다."}
        waits = name in ("permission", "question")
        with self.store.lock:  # 세션 데이터를 바꾸는 동안 저장·화면 변환이 중간 상태를 읽지 않게 한다
            s = self.store.ensure(sid, cwd)
            s["lastSignalAt"] = self.clock()
            mode = body.get("permission_mode")
            if isinstance(mode, str):
                s["permissionMode"] = mode
            model = body.get("model")  # 훅 입력에 있을 때만 쓴다(없으면 표시하지 않는다)
            if isinstance(model, str) and model:
                s["model"] = model
            tpath = context_usage.valid_path(body.get("transcript_path"))  # 기억 사용량을 읽을 대화 기록 위치(#648)
            if tpath:
                s["transcriptPath"] = tpath
            if name == "blocked":
                return self.blocked(s, body)
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

    def _terminal_without_browser(self, s: dict, tool: str = "", tool_input=None) -> bool:
        if s["managed"] or self.store.browser_connected():
            return False
        # 콘솔이 다시 연결됐을 때 화면이 알릴 수 있게 기록을 남긴다(app.js HANDOFF_MARK). 같은 호출이 거듭 오면 한 번만.
        key = tool_key(tool, tool_input)
        with self.store.lock:
            if s.get("lastTermKey") != key:
                s["lastTermKey"] = key
                self.store.add_log(s, f"콘솔이 연결돼 있지 않아 터미널로 넘김: {tool or '질문'}")
                self.store.touch(s)
        return True

    def decide(self, s: dict, tool: str, tool_input) -> tuple[str, str, str]:
        """(allow | ask, risk, 사유). 묻지 않고 허용할 일이면 allow. 되돌릴 수 없는 일이면 risk 가 irreversible.
        판정 못 한 것(unknown)과 모든 명령마다(all)는 ask 다. 하네스 훅이 막는 일은 이 판정과 상관없이 훅이 막는다."""
        level = self.ask_level()
        if level not in ASK_LEVELS:
            level = "all"  # 모르는 값이면 가장 엄격하게
        # 계획 모드면 그 세션의 설정 폴더 plans/ 의 계획 파일 쓰기를 묻지 않는다(#878). 설정 폴더는 대화 기록 경로로, 없으면 CLAUDE_CONFIG_DIR·~/.claude
        plan_dir = plan_dir_of(session_alive.config_dir(str(s.get("transcriptPath") or ""))) if s.get("permissionMode") == "plan" else ""
        roots = (os.environ.get("CLAUDE_CONFIG_DIR") or "", str(Path.home() / ".claude")) if plan_dir else ()  # plans 링크로 받아 줄 실제 설정 폴더(#911)
        verdict, why = classify(tool, tool_input, s.get("cwd") or "", plan_dir=plan_dir, config_roots=roots)
        if verdict == IRREVERSIBLE:
            return "ask", IRREVERSIBLE, why
        if verdict == SAFE and level != "all" and not (level == "edits" and tool in EDIT_TOOLS):
            return "allow", "", why
        return "ask", "", why

    def risk_of(self, s: dict, tool: str, tool_input) -> tuple[str, str]:
        """카드에 붙일 (risk, 쉬운 말 사유). 되돌릴 수 없는 일이 아니면 ("", "")."""
        _, risk, why = self.decide(s, tool, tool_input)
        return (risk, why) if risk else ("", "")

    def auto_allowed(self, s: dict, tool: str, tool_input) -> bool:
        """콘솔이 카드를 띄울 경로에서만 부른다. 허용이면 세션 기록에 한 줄 남긴다(같은 호출을 훅과 콘솔 연결이 둘 다 물을 수 있어 한 번만)."""
        if tool == "AskUserQuestion":
            return False
        action, _, why = self.decide(s, tool, tool_input)
        if action != "allow":
            return False
        key = tool_key(tool, tool_input)
        with self.store.lock:
            if s.get("lastAutoKey") != key:
                s["lastAutoKey"] = key
                self.store.add_log(s, f"자동 허용: {_action(tool, tool_input)[:160]} ({why})")
                self.store.touch(s)
        return True

    # ---- 승인 ----
    def permission(self, s: dict, body: dict, alive) -> Reply:
        tool = body.get("tool_name") if isinstance(body.get("tool_name"), str) else ""
        if tool == "AskUserQuestion":
            return 200, None  # 질문은 PreToolUse 훅이 맡는다
        if self._terminal_without_browser(s, tool, body.get("tool_input")):
            return 200, None  # 터미널 프롬프트가 처리한다
        tool_input = body.get("tool_input")
        if self.auto_allowed(s, tool, tool_input):
            return 200, permission_reply({"behavior": "allow"})  # 사람 카드 없이 바로 허용
        risk, why = self.risk_of(s, tool, tool_input)
        try:
            req, created = self.store.add_request(
                s["id"], "permission", tool, tool_input, body.get("permission_suggestions"), tool_key(tool, tool_input),
                risk=risk, risk_note=why, source="hook")
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
        if self._terminal_without_browser(s, "AskUserQuestion", tool_input):
            return 200, None  # 터미널 질문창으로 넘어간다
        # 마감은 질문이 도착한 시점 기준이다. 요청을 화면에 등록한 뒤에 재면 그 사이 흐른 시간만큼 늦어진다(#610).
        deadline = None if s["managed"] else self.clock() + self.question_wait
        try:
            req, created = self.store.add_request(s["id"], "question", "AskUserQuestion", tool_input, None,
                                                  tool_key("AskUserQuestion", tool_input))
        except RequestLimit:
            self.store.add_log(s, "대기 요청이 너무 많아 질문을 터미널로 넘김")
            return 200, None
        if created:
            self.store.add_log(s, "질문이 도착함")
            self.store.touch(s)
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
            s["reportFresh"] = True  # 이번 턴에 받은 보고(askedInText 는 이것만 본다)
            self.store.add_chat(s, "ai", text)
        s["turn_running"] = False
        s["currentAction"] = ""
        asking = any(r.kind == "question" for r in self.store.pending_for(s["id"]))  # 질문 대기 중의 Stop 은 스킬 끝이 아니다(아래에서 닫기 전에 본다)
        if not s["managed"]:
            self.store.close_session(s["id"], "터미널에서 처리됨")
        for name, state in list(s["skillStates"].items()):
            if state == "active":
                s["skillStates"][name] = "done"
        s["currentSkill"] = ""
        flows.turn_ended(s, asking=asking)
        self.refresh_git(s["id"])
        queue_ = s["pending_stop"]
        if queue_:
            item = queue_.pop(0)  # 꺼낼 때 지워서 무한 반복을 막는다. 응답 전송이 실패하면 undo 로 되돌린다.
            s["turn_running"] = True
            if undo is not None:
                undo.append(lambda: self._restore_stop(s, item))
            self.store.add_chat(s, "me", f"/{item['skill']}" + (f" {item['args']}" if item.get("args") else "")
                                if item.get("kind") == "skill" else str(item.get("text", "")))  # 훅 프롬프트로는 오지 않는 콘솔 예약 말
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

    # ---- 막는 훅의 보고(#650) ----
    def blocked(self, s: dict, body: dict) -> Reply:
        """막는 훅(hooks/console_block.py)이 막을 때 직접 보낸 사유를 대화에 쌓는다. 막힌 호출에는 다른 훅 이벤트가 뜨지 않는다."""
        reason = body.get("reason") if isinstance(body.get("reason"), str) else ""
        hook = body.get("hook") if isinstance(body.get("hook"), str) else ""
        tool = body.get("tool_name") if isinstance(body.get("tool_name"), str) else ""
        reason = reason.strip()
        if not reason:
            return 400, {"error": "reason 이 없습니다."}
        kind = block_kind(reason)
        fix = ""
        if "다음:" in reason:
            fix = reason.split("다음:", 1)[1].strip()
        if self.store.add_chat(s, "block", reason, hook=hook[:80], kind=kind, fix=fix[:2000], tool=tool[:120]):
            self.store.add_log(s, ("검사 못 해 멈춤: " if kind == "cannot_check" else "하네스 훅이 막음: ") + reason.split("\n", 1)[0][:200])
            self.store.touch(s)
        return 200, None

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
            store.touch_peers(s)
        elif name == "UserPromptSubmit":
            if not late:
                s["turn_running"], s["ended"] = True, False
                s["reportFresh"] = False  # 새 턴이 시작됐다. 이전 보고는 화면에 남아도 질문 판정에는 쓰지 않는다
            prompt = body.get("prompt") if isinstance(body.get("prompt"), str) else ""
            if not s["managed"]:
                store.close_session(s["id"], "터미널에서 처리됨", before=ts)  # 늦게 온 프롬프트가 그 뒤의 새 요청을 닫지 않게 한다
            if prompt and s.get("title_rank", 0) < TITLE_PROMPT:
                title = prompt_title(prompt)
                if title:
                    store.set_title(s, title, TITLE_PROMPT)
            store.add_log(s, "요청: " + prompt.split("\n", 1)[0][:200])
            store.add_chat(s, "me", chat_clean(prompt))
        elif name == "UserPromptExpansion":
            if not late:
                self._skill_started(s, body.get("command_name"))
        elif name == "PreToolUse":
            tool = str(body.get("tool_name", ""))
            tool_input = body.get("tool_input")
            agent_id = body.get("agent_id")
            if tool in AGENT_TOOLS and agent_id is None:
                self._agent_called(s, body, tool_input)
            if agent_id is not None:  # 서브에이전트 안에서 난 호출. 메인 세션의 현재 동작을 덮어쓰지 않고 그 서브에이전트 항목에 적는다.
                self._subagent_tool(s, agent_id, _action(tool, tool_input))
            if not late:
                s["turn_running"], s["ended"] = True, False
                if agent_id is None and (ts is None or ts >= s.get("actionTs", 0.0)):  # 도구를 잇달아 부르면 먼저 뜬 이벤트가 늦게 올 수 있다
                    s["currentAction"] = _action(tool, tool_input)
                    if ts is not None:
                        s["actionTs"] = ts
                if tool == "Skill" and isinstance(tool_input, dict) and agent_id is None:
                    self._skill_started(s, tool_input.get("skill"))
        elif name == "PostToolUse":
            self._post_tool_use(s, body, ts)
        elif name == "SubagentStart":
            aid = body.get("agent_id")
            if not any(a.get("id") == aid and aid is not None for a in s["subagents"]):
                entry = {"id": aid, "type": _clip(body.get("agent_type"), MAX_AGENT_TEXT), "state": "running",
                         "startedAt": self.clock(), "tools": 0, "currentAction": ""}
                entry.update(self._take_pending_agent(s, body))
                s["subagents"].append(entry)
                del s["subagents"][:-MAX_SUBAGENTS]
            store.add_log(s, "서브에이전트 시작" + (f": {body['agent_type']}" if body.get("agent_type") else ""))
        elif name == "SubagentStop":
            found = False
            for a in s["subagents"]:
                if a.get("id") == body.get("agent_id"):
                    self._subagent_done(a)
                    found = True
            if not found and body.get("agent_id") is not None:  # 끝 이벤트가 시작보다 먼저 왔다. 나중에 올 시작이 다시 running 으로 만들지 못하게 남긴다.
                entry = {"id": body.get("agent_id"), "type": _clip(body.get("agent_type"), MAX_AGENT_TEXT), "state": "running", "tools": 0}
                self._subagent_done(entry)
                s["subagents"].append(entry)
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
            store.touch_peers(s)
            store.flush()
        store.touch(s)
        return 200, None

    def _agent_called(self, s: dict, body: dict, tool_input) -> None:
        """Agent·Task 호출의 맡은 일을 적어 둔다. 곧 오는 SubagentStart 와 짝을 맞춘다."""
        if not isinstance(tool_input, dict):
            return
        pending = s.setdefault("pendingAgents", [])
        use_id = body.get("tool_use_id") if isinstance(body.get("tool_use_id"), str) else ""
        if use_id and any(p.get("toolUseId") == use_id for p in pending):
            return
        prompt = tool_input.get("prompt") if isinstance(tool_input.get("prompt"), str) else ""
        pending.append({"toolUseId": use_id, "type": _clip(tool_input.get("subagent_type"), MAX_AGENT_TEXT),
                        "description": _clip(tool_input.get("description"), MAX_AGENT_TEXT),
                        "prompt": _clip(prompt.strip().split("\n", 1)[0], MAX_AGENT_PROMPT),
                        "background": tool_input.get("run_in_background") is True})
        del pending[:-MAX_PENDING_AGENTS]

    def _take_pending_agent(self, s: dict, body: dict) -> dict:
        """SubagentStart 와 짝이 되는 대기 항목을 꺼낸다. tool_use_id 가 같은 것, 없으면 같은 종류 중 가장 오래된 것."""
        pending = s.get("pendingAgents") or []
        use_id = body.get("tool_use_id") if isinstance(body.get("tool_use_id"), str) else ""
        kind = _clip(body.get("agent_type"), MAX_AGENT_TEXT)
        hit = next((p for p in pending if use_id and p.get("toolUseId") == use_id), None)
        if hit is None:
            hit = next((p for p in pending if p.get("type") == kind or not p.get("type")), None)
        if hit is None:
            return {}
        pending.remove(hit)
        return {"description": hit["description"], "prompt": hit["prompt"], "background": hit["background"]}

    def _subagent_tool(self, s: dict, agent_id, action: str) -> None:
        for a in s["subagents"]:
            if a.get("id") == agent_id and a.get("state") == "running":
                a["currentAction"] = _clip(action, MAX_AGENT_TEXT)
                a["tools"] = a.get("tools", 0) + 1

    def _subagent_done(self, a: dict) -> None:
        now = self.clock()
        a["state"], a["currentAction"], a["endedAt"] = "done", "", now
        if isinstance(a.get("startedAt"), (int, float)):
            a["durationSec"] = max(0.0, now - a["startedAt"])

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
        flows.skill_started(s, skill)
        mark_check(s, skill, CHECK_DONE)  # 새 세션 점검(sync, version, update)이면 했음으로
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
            remember_touched(s, [path])
        response = body.get("tool_response")
        text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str)
        for url in PR_URL.findall(text or ""):
            if url not in s["prLinks"] and len(s["prLinks"]) < MAX_PR_LINKS:
                s["prLinks"].append(url)


def _clip(value, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _action(tool: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "pattern", "skill", "description"):
            if isinstance(tool_input.get(key), str):
                return f"{tool}: {tool_input[key][:120]}"
    return tool
