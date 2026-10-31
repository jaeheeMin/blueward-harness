"""세션과 요청 상태. 세션은 sessions.json 에 원자적으로 저장하고, 대기 중인 요청은 저장하지 않는다(web-console.md §3)."""
from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import platform_compat

LOG_LIMIT = 200
REQUEST_KEEP = 200
SAVE_INTERVAL = 2.0
MAX_SESSIONS = 500
MAX_PENDING_REQUESTS = 100
MAX_SKILL_STATES = 100
MAX_SUBAGENTS = 200
MAX_PENDING_STOP = 20
MAX_CHANGED_FILES = 500
MAX_PR_LINKS = 50
SUBSCRIBER_MAXSIZE = 1000
TERMINAL_IDLE_SECONDS = 600.0  # 터미널 세션은 이만큼 신호가 없으면 쉬는 상태로 본다(Esc 로 끊으면 Stop 이 오지 않는다)
REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.05

# 제목 우선순위: SessionStart 의 session_title > 첫 요청 글 > 폴더 이름
TITLE_FOLDER, TITLE_PROMPT, TITLE_SESSION = 1, 2, 3


class RequestLimit(Exception):
    """대기 중인 요청이 너무 많다. 호출한 쪽은 요청을 조용히 허용하지 말고 터미널로 넘기거나 거부해야 한다."""


class Subscriber(queue.Queue):
    """SSE 구독자 한 명의 큐. 가득 차면 closed 로 표시하고, 연결 쪽이 끊어서 브라우저가 다시 붙게 한다."""

    def __init__(self):
        super().__init__(maxsize=SUBSCRIBER_MAXSIZE)
        self.closed = False


def describe_suggestions(suggestions) -> list[str]:
    """permission_suggestions 를 사람이 읽는 문장으로 바꾼다. 화면은 이 문장을 '허용하고 다시 묻지 않기' 위에 보여 준다."""
    out: list[str] = []
    for sug in suggestions or []:
        if not isinstance(sug, dict):
            out.append("알 수 없는 제안")
            continue
        kind = sug.get("type")
        dest = {"session": "이 세션", "localSettings": "이 폴더의 로컬 설정", "projectSettings": "프로젝트 설정",
                "userSettings": "사용자 설정"}.get(sug.get("destination"), str(sug.get("destination") or "이 세션"))
        if kind in ("addRules", "replaceRules", "removeRules"):
            verb = {"addRules": "추가", "replaceRules": "교체", "removeRules": "제거"}[kind]
            behavior = {"allow": "허용", "deny": "거부", "ask": "묻기"}.get(sug.get("behavior"), str(sug.get("behavior") or ""))
            rules = [r for r in sug.get("rules") or [] if isinstance(r, dict)]
            if not rules:
                out.append(f"{dest}: 규칙 {verb}({behavior})")
            for r in rules:
                content = r.get("ruleContent")
                name = str(r.get("toolName", "?"))
                out.append(f"{dest}: {behavior} 규칙 {verb} - {name}({content})" if content else f"{dest}: {behavior} 규칙 {verb} - {name} 전체")
        elif kind == "setMode":
            out.append(f"{dest}: 권한 모드를 {sug.get('mode')} 로 변경")
        elif kind in ("addDirectories", "removeDirectories"):
            verb = "추가" if kind == "addDirectories" else "제거"
            out.append(f"{dest}: 접근 폴더 {verb} - " + ", ".join(str(d) for d in sug.get("directories") or []))
        else:
            out.append(f"{dest}: {kind}")
    return out


class Request:
    """승인 또는 질문 하나. 훅 연결이 이 객체의 event 를 기다린다."""

    def __init__(self, rid, session_id, kind, tool_name, tool_input, suggestions, key, created):
        self.rid = rid
        self.session_id = session_id
        self.kind = kind  # "permission" | "question"
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.suggestions = suggestions if isinstance(suggestions, list) else []
        self.key = key
        self.created = created
        self.status = "pending"  # pending | answered | closed
        self.outcome = ""  # 화면에 보여 줄 처리 결과
        self.response = None  # 훅에 돌려줄 값(answered 일 때)
        self.answered_at = None
        self.waiters = 0
        self.event = threading.Event()

    def public(self) -> dict:
        data = {
            "id": self.rid,
            "sessionId": self.session_id,
            "kind": self.kind,
            "toolName": self.tool_name,
            "toolInput": self.tool_input,
            "hasSuggestions": bool(self.suggestions),
            "suggestionText": describe_suggestions(self.suggestions),
            "status": self.status,
            "outcome": self.outcome,
            "createdAt": self.created,
            "answeredAt": self.answered_at,
        }
        if self.kind == "question" and isinstance(self.tool_input, dict):
            data["questions"] = self.tool_input.get("questions", [])
        return data


class Store:
    def __init__(self, state_dir: Path | None, clock: Callable[[], float] = time.time):
        self.dir = Path(state_dir) if state_dir else None
        self.clock = clock
        self.lock = threading.RLock()
        self.sessions: dict[str, dict] = {}
        self.aliases: dict[str, str] = {}
        self.requests: dict[str, Request] = {}
        self.folders: list[str] = []
        self.subscribers: list[Subscriber] = []
        self._dirty = False
        self._last_save = 0.0
        self._seq = 0  # 저장 요청 순번. 늦게 만든 스냅샷이 먼저 쓰이는 일이 없게 한다
        self._written_seq = 0
        self._io_lock = threading.Lock()
        self.sleep = time.sleep
        self.load()

    # ---- 저장 ----
    def _file(self, name: str) -> Path | None:
        return self.dir / name if self.dir else None

    def load(self) -> None:
        f = self._file("sessions.json")
        if not f or not f.exists():
            return
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for s in data.get("sessions", []):
            if isinstance(s, dict) and isinstance(s.get("id"), str):
                s["turn_running"] = False
                s["managed_alive"] = False
                self.sessions[s["id"]] = s
        self.folders = [p for p in data.get("folders", []) if isinstance(p, str)]

    def save(self, force: bool = False) -> None:
        """직렬화는 잠금 안에서 끝내고(다른 스레드가 세션을 바꾸는 중에 읽지 않는다), 파일 쓰기는 잠금 밖에서 한다.
        저장이 실패해도 예외를 밖으로 내지 않는다. 훅 처리가 저장 때문에 깨지면 안 된다."""
        if not self.dir:
            return
        try:
            with self.lock:
                now = self.clock()
                if not force and now - self._last_save < SAVE_INTERVAL:
                    self._dirty = True
                    return
                self._dirty = False
                self._last_save = now
                text = json.dumps({"sessions": [{k: v for k, v in s.items() if k != "managed_alive"} for s in self.sessions.values()],
                                   "folders": self.folders}, ensure_ascii=False, default=str)
                self._seq += 1
                seq = self._seq
            self._write(text, seq)
        except Exception:
            pass

    def _write(self, text: str, seq: int) -> None:
        with self._io_lock:
            if seq < self._written_seq:
                return  # 더 새로운 스냅샷이 이미 쓰였다
            tmp = None
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="sessions.", suffix=".tmp")
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(text)
                for attempt in range(REPLACE_RETRIES):
                    try:
                        os.replace(tmp, self.dir / "sessions.json")
                        tmp = None
                        self._written_seq = seq
                        return
                    except PermissionError:  # Windows 에서 다른 프로세스가 파일을 잠시 잡고 있을 수 있다
                        if attempt == REPLACE_RETRIES - 1:
                            raise
                        self.sleep(REPLACE_RETRY_DELAY)
            except Exception:
                pass
            finally:
                if tmp:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

    def flush(self) -> None:
        self.save(force=True)

    # ---- 구독(SSE) ----
    def subscribe(self) -> Subscriber:
        q = Subscriber()
        with self.lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def browser_connected(self) -> bool:
        with self.lock:
            return bool(self.subscribers)

    def publish(self, kind: str, payload: dict) -> None:
        with self.lock:
            targets = list(self.subscribers)
        for q in targets:
            try:
                q.put_nowait((kind, payload))
            except queue.Full:
                q.closed = True  # 따라오지 못하는 구독자는 끊어서 다시 붙게 한다
                self.unsubscribe(q)

    # ---- 세션 ----
    def resolve_id(self, sid: str) -> str:
        with self.lock:
            return self.aliases.get(sid, sid)

    def get(self, sid: str) -> dict | None:
        with self.lock:
            return self.sessions.get(self.resolve_id(sid))

    def ensure(self, sid: str, cwd: str = "") -> dict:
        """처음 보는 session_id 는 자동 등록한다."""
        with self.lock:
            sid = self.resolve_id(sid)
            s = self.sessions.get(sid)
            if s is None:
                now = self.clock()
                self._make_room()
                s = {
                    "id": sid, "title": "", "title_rank": 0, "cwd": cwd, "repo": "", "branch": "", "managed": False,
                    "permissionMode": "", "currentSkill": "", "currentAction": "", "startedAt": now, "updatedAt": now,
                    "log": [], "report": "", "changedFiles": [], "prLinks": [], "subagents": [], "skillStates": {},
                    "pending_stop": [], "turn_running": False, "ended": False, "managed_alive": False,
                    "turn": {"skill": None, "unknown": False},
                }
                self.sessions[sid] = s
                if cwd:
                    self.set_title(s, os.path.basename(cwd.rstrip("/\\")) or cwd, TITLE_FOLDER)
                    self.add_folder(cwd)
            elif cwd and not s["cwd"]:
                s["cwd"] = cwd
                self.set_title(s, os.path.basename(cwd.rstrip("/\\")) or cwd, TITLE_FOLDER)
                self.add_folder(cwd)
            return s

    def _make_room(self) -> None:
        """세션이 상한을 넘으면 오래된 끝난 세션부터, 그다음 쉬는 세션 순으로 지운다. 대기 요청이 있거나 도는 세션은 지우지 않는다."""
        over = len(self.sessions) - MAX_SESSIONS + 1
        if over <= 0:
            return
        busy = {r.session_id for r in self.requests.values() if r.status == "pending"}

        def removable(s):
            return s["id"] not in busy and not s.get("managed_alive") and not s.get("starting")

        pool = sorted((s for s in self.sessions.values() if removable(s)),
                      key=lambda s: (0 if s.get("ended") else 1 if not s.get("turn_running") else 2, s["updatedAt"]))
        for s in pool[:over]:
            self.sessions.pop(s["id"], None)
            self.publish("removed", {"kind": "session", "id": s["id"]})

    def set_title(self, s: dict, title: str, rank: int) -> None:
        title = " ".join(str(title).split())[:60]
        if title and rank >= s.get("title_rank", 0):
            s["title"], s["title_rank"] = title, rank

    def add_log(self, s: dict, text: str) -> None:
        with self.lock:
            s["log"].append({"time": self.clock(), "text": str(text)[:500]})
            del s["log"][:-LOG_LIMIT]

    def touch(self, s: dict, publish: bool = True) -> None:
        with self.lock:
            s["updatedAt"] = self.clock()
        self.save()
        if publish:
            self.publish("session", {"id": s["id"]})

    def rekey(self, old: str, new: str) -> dict | None:
        """콘솔이 띄운 세션의 임시 id 를 실제 session_id 로 바꾼다. 훅이 먼저 실제 id 로 등록했으면 합친다."""
        with self.lock:
            if old == new:
                return self.sessions.get(new)
            s = self.sessions.pop(old, None)
            if s is None:
                return self.sessions.get(new)
            existing = self.sessions.get(new)
            if existing:
                existing["managed"] = True
                existing["cwd"] = existing["cwd"] or s["cwd"]
                existing["startedAt"] = min(existing["startedAt"], s["startedAt"])
                if s["title_rank"] > existing["title_rank"]:
                    existing["title"], existing["title_rank"] = s["title"], s["title_rank"]
                existing["log"] = (s["log"] + existing["log"])[-LOG_LIMIT:]
                target = existing
            else:
                s["id"] = new
                self.sessions[new] = s
                target = s
            self.aliases[old] = new
            for r in self.requests.values():
                if r.session_id == old:
                    r.session_id = new
        self.publish("removed", {"kind": "session", "id": old})
        self.publish("session", {"id": new})
        return target

    # ---- 폴더 ----
    def add_folder(self, path: str) -> None:
        with self.lock:
            self.folders[:] = [f for f in self.folders if not platform_compat.same_path(f, path)]
            self.folders.insert(0, path)
            del self.folders[20:]

    # ---- 요청 ----
    def add_request(self, sid, kind, tool_name, tool_input, suggestions, key) -> tuple[Request, bool]:
        """같은 세션·도구·입력의 동시 호출은 요청 하나로 합친다. (요청, 새로 만들었는지) 를 돌려준다."""
        with self.lock:
            sid = self.resolve_id(sid)
            for r in self.requests.values():
                # 제안(permission_suggestions)이 다르면 합치지 않는다. 합치면 먼저 온 위조 요청의 제안이
                # 진짜 요청의 '다시 묻지 않기' 답으로 적용된다.
                if (r.status == "pending" and r.session_id == sid and r.kind == kind and r.key == key
                        and r.suggestions == (suggestions if isinstance(suggestions, list) else [])):
                    return r, False
            if sum(1 for r in self.requests.values() if r.status == "pending") >= MAX_PENDING_REQUESTS:
                raise RequestLimit("대기 중인 요청이 너무 많습니다.")
            r = Request(uuid.uuid4().hex[:12], sid, kind, tool_name, tool_input, suggestions, key, self.clock())
            self.requests[r.rid] = r
            self._prune_requests()
        self.publish("request", {"id": r.rid, "sessionId": sid})
        self.publish("session", {"id": sid})
        return r, True

    def _prune_requests(self) -> None:
        done = [r for r in self.requests.values() if r.status != "pending"]
        for r in sorted(done, key=lambda x: x.created)[:-REQUEST_KEEP]:
            self.requests.pop(r.rid, None)
            self.publish("removed", {"kind": "request", "id": r.rid})

    def resolve(self, rid: str, response, outcome: str) -> bool:
        """답변을 확정한다. 이미 닫혔으면 False(먼저 처리한 쪽이 이긴다)."""
        with self.lock:
            r = self.requests.get(rid)
            if r is None or r.status != "pending":
                return False
            r.status, r.response, r.outcome, r.answered_at = "answered", response, outcome, self.clock()
            r.event.set()
        self.publish("request", {"id": rid, "sessionId": r.session_id})
        self.publish("session", {"id": r.session_id})
        return True

    def close(self, rid: str, outcome: str) -> bool:
        with self.lock:
            r = self.requests.get(rid)
            if r is None or r.status != "pending":
                return False
            r.status, r.outcome, r.answered_at = "closed", outcome, self.clock()
            r.event.set()
        self.publish("request", {"id": rid, "sessionId": r.session_id})
        self.publish("session", {"id": r.session_id})
        return True

    def pending_for(self, sid: str) -> list[Request]:
        with self.lock:
            sid = self.resolve_id(sid)
            return sorted((r for r in self.requests.values() if r.session_id == sid and r.status == "pending"),
                          key=lambda r: r.created)

    def close_session(self, sid: str, outcome: str, before: float | None = None) -> int:
        """before 가 있으면 그 시각까지 만들어진 요청만 닫는다(늦게 도착한 이벤트가 새 요청을 닫지 않게)."""
        n = 0
        for r in self.pending_for(sid):
            if before is None or r.created <= before:
                n += self.close(r.rid, outcome)
        return n

    def get_request(self, rid: str) -> Request | None:
        with self.lock:
            return self.requests.get(rid)


CANNOT_SEND_IDLE = "쉬는 터미널 세션에는 바깥에서 새 턴을 시작할 수 없습니다. 터미널에서 직접 이어 가십시오."
CANNOT_SEND_ENDED = "끝난 터미널 세션입니다."


def turn_running(store: "Store", s: dict) -> bool:
    """터미널 세션은 마지막 신호 뒤 TERMINAL_IDLE_SECONDS 가 지나면 쉬는 것으로 본다(Esc 로 끊으면 Stop 이 오지 않는다).
    승인 대기가 있거나 콘솔이 띄운 세션이면 신호가 없어도 도는 것으로 둔다."""
    if not s["turn_running"]:
        return False
    if s["managed"] or any(r.session_id == s["id"] and r.status == "pending" for r in store.requests.values()):
        return True
    last = s.get("lastSignalAt", s["updatedAt"])
    return store.clock() - last <= TERMINAL_IDLE_SECONDS


def can_send(s: dict, store: "Store | None" = None) -> tuple[bool, str]:
    if s["managed"]:
        return True, ""
    if s["ended"]:
        return False, CANNOT_SEND_ENDED
    if (turn_running(store, s) if store is not None else s["turn_running"]):
        return True, ""
    return False, CANNOT_SEND_IDLE


def public_session(store: Store, s: dict, skills: list[str]) -> dict:
    """화면에 내려보내는 세션 모델(web-console.md §8)."""
    with store.lock:
        pending = [r.rid for r in store.pending_for(s["id"])]
        running = turn_running(store, s)
        ok, why = can_send(s, store)
        reserved = {i["skill"] for i in s["pending_stop"] if i.get("kind") == "skill"}
        flow = []
        for name in skills:
            item = {"skill": name, "state": s["skillStates"].get(name, "idle"), "reserved": name in reserved}
            if not ok:
                item["disabledReason"] = why
            flow.append(item)
        if s["ended"] and not s["managed"]:
            status = "ended"
        elif pending:
            status = "waiting"
        elif running:
            status = "running"
        elif s.get("starting"):
            status = "starting"
        elif s["ended"]:
            status = "ended"
        else:
            status = "idle"
        turn_skill = s["turn"].get("skill")
        if pending or (turn_skill and not running and not s["ended"]):
            group = "todo"
        elif running:
            group = "running"
        else:
            group = "idle"
        return {
            "id": s["id"], "title": s["title"], "cwd": s["cwd"], "repo": s["repo"], "branch": s["branch"],
            "managed": s["managed"], "status": status, "group": group, "permissionMode": s["permissionMode"],
            "currentSkill": s["currentSkill"], "currentAction": s["currentAction"],
            "startedAt": s["startedAt"], "updatedAt": s["updatedAt"], "log": list(s["log"]), "report": s["report"],
            "changedFiles": list(s["changedFiles"]), "prLinks": list(s["prLinks"]), "subagents": list(s["subagents"]),
            "flow": flow, "turnSkill": turn_skill, "turnUnknown": bool(s["turn"].get("unknown")),
            "pendingRequestIds": pending, "canSend": ok, "cannotSendReason": why,
            "bypassPermissions": s["permissionMode"] == "bypassPermissions",
        }
