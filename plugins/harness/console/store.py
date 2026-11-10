"""세션과 요청 상태. 세션은 sessions.json 에 원자적으로 저장하고, 대기 중인 요청은 저장하지 않는다(web-console.md §3)."""
from __future__ import annotations

import json
import os
import queue
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import context_usage
import flows
import platform_compat
from docfiles import SKIP_DIRS

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
CHAT_LIMIT = 200  # 세션마다 남기는 대화 항목 수
CHAT_TEXT_LIMIT = 8000  # 항목 하나의 글자 수
SUBSCRIBER_MAXSIZE = 1000
TERMINAL_IDLE_SECONDS = 600.0  # 터미널 세션은 이만큼 신호가 없으면 쉬는 상태로 본다(Esc 로 끊으면 Stop 이 오지 않는다)
REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.05
# 새 세션 점검 항목(sync, version, update, reload). 상태: pending(대기) / done(했음) / skipped(건너뜀)
START_CHECK_IDS = ("sync", "version", "update", "reload")
CHECK_PENDING, CHECK_DONE, CHECK_SKIPPED = "pending", "done", "skipped"

# 제목 우선순위: SessionStart 의 session_title > 첫 요청 글 > 폴더 이름
TITLE_FOLDER, TITLE_PROMPT, TITLE_SESSION = 1, 2, 3

_DROP_TAGS = "system-reminder|task-notification|local-command-stdout|local-command-caveat"
_DROP_BLOCK = re.compile(rf"<({_DROP_TAGS})\b[^>]*>.*?</\1\s*>", re.S)
_DROP_OPEN = re.compile(rf"<({_DROP_TAGS})\b[^>]*>.*\Z", re.S)
_COMMAND_TAG = re.compile(r"<command-[a-z-]+>")
# 옛 판이 60자로 잘라 저장한 이름은 여는 태그의 > 가 없다 — 줄 끝까지를 태그로 본다
_CROSS_SESSION = re.compile(r"<cross-session-message\b[^>\n]*(?:>|$)|</cross-session-message\s*>", re.M)
_PLACEHOLDER = re.compile(r"\[Image #\d+\]|\[Image: source: [^\]]*\]|\[Pasted text #\d+[^\]]*\]")
_BRANCH = re.compile(r"^[A-Za-z]+/(\d+)-(.+)$")


def prompt_title(text: str) -> str:
    """프롬프트 전체 글에서 세션 이름이 될 한 줄을 고른다. 사람이 쓴 글이 아니거나 슬래시 명령이면 빈 문자열."""
    text = str(text or "")
    text = _DROP_BLOCK.sub("", text)
    text = _DROP_OPEN.sub("", text)
    if _COMMAND_TAG.search(text):
        return ""
    cross = bool(_CROSS_SESSION.search(text))
    text = _CROSS_SESSION.sub("", text)
    text = _PLACEHOLDER.sub("", text)
    for line in text.split("\n"):
        line = line.strip()
        if line:
            if line.startswith("/"):
                return ""
            return ("다른 세션: " if cross else "") + line
    return ""


def chat_clean(text: str) -> str:
    """대화에 남길 내 말. 시스템 블록(task-notification, system-reminder, local-command-*)을 걷어 내고, 남는 글이 없으면 빈 문자열."""
    text = _DROP_OPEN.sub("", _DROP_BLOCK.sub("", str(text or "")))
    return text.strip()


def request_title(kind: str, tool_name, tool_input) -> str:
    """대화에 남길 요청 제목. 질문이면 첫 질문 글, 승인이면 도구 이름."""
    if kind == "question" and isinstance(tool_input, dict):
        for q in tool_input.get("questions") or []:
            if isinstance(q, dict) and str(q.get("question") or q.get("header") or "").strip():
                return " ".join(str(q.get("question") or q.get("header")).split())[:200]
        return "질문"
    return str(tool_name or "도구")[:100] + " 사용"


def request_answer(r) -> str:
    """처리된 요청의 답 요약. 응답 구조를 알 수 없으면 outcome 만 쓴다(답을 지어내지 않는다)."""
    if r.status != "answered":
        return r.outcome or "닫힘"
    out = r.response.get("hookSpecificOutput") if isinstance(r.response, dict) else None
    out = out if isinstance(out, dict) else {}
    if r.kind == "question":
        answers = (out.get("updatedInput") or {}).get("answers") if isinstance(out.get("updatedInput"), dict) else None
        if isinstance(answers, dict):
            values = [" ".join(str(v).split()) for v in answers.values() if isinstance(v, str) and v.strip()]
            if values:
                return " / ".join(values)[:400]
        return r.outcome or "답변함"
    decision = out.get("decision") if isinstance(out.get("decision"), dict) else {}
    if decision.get("behavior") == "allow":
        return "허락함(이 세션에서 다시 묻지 않기)" if decision.get("updatedPermissions") else "허락함"
    if decision.get("behavior") == "deny":
        return "거절함"
    return r.outcome or "처리함"


# 스킬 이름의 쉬운 말. static/app.js 의 SKILL_LABELS 와 같게 둔다.
SKILL_TITLES = {
    "start": "작업 시작", "sync": "최신 받기", "deliver": "제출하기", "wrapup": "이슈로 남기기", "srs": "요구사항 문서",
    "spec": "개발 Spec", "scaffold": "구조 만들기", "atc": "ATC 고치기", "prs": "내 PR", "approvals": "승인 대기",
    "version": "버전 보기", "update": "업데이트", "open": "콘솔 열기",
}


def display_title(s: dict) -> str:
    """화면에 보일 이름. 요청 글 이름이 아직 없으면 브랜치·스킬·폴더 순으로 대신한다(저장값은 바꾸지 않는다)."""
    if s.get("title_rank", 0) >= TITLE_PROMPT and s.get("title"):
        return s["title"]
    m = _BRANCH.match(str(s.get("branch") or ""))
    if m:
        return f"#{m.group(1)} " + " ".join(m.group(2).replace("-", " ").split())
    turn = s.get("turn") if isinstance(s.get("turn"), dict) else {}
    skill = str(s.get("currentSkill") or turn.get("skill") or "")
    cwd = str(s.get("cwd") or "")
    folder = re.split(r"[\\/]", cwd.rstrip("/\\"))[-1] or cwd  # Windows 경로를 Linux 에서 읽어도 폴더 이름만
    tail = f" · {folder}" if folder else ""
    if skill:
        name = skill.split(":", 1)[-1]
        return SKILL_TITLES.get(name, name) + tail  # 같은 스킬 세션이 여럿이어도 폴더로 가려 본다
    return "이름 없는 세션" + tail


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
        self.risk = ""  # "irreversible" 이면 되돌릴 수 없는 일이라 노랑 카드로 묻는다(#649)
        self.risk_note = ""  # 무엇을 하려는지 쉬운 말
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
        if self.risk:
            data["risk"], data["riskNote"] = self.risk, self.risk_note
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
        self.flow_data: dict | None = None  # 서버가 읽어 둔 갈래 정의. 화면에는 현재 이름·설명으로 내보낸다
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
                if not isinstance(s.get("chat"), list):
                    s["chat"] = []
                else:
                    s["chat"] = [c for c in s["chat"] if isinstance(c, dict)][-CHAT_LIMIT:]
                if s.get("title_rank") == TITLE_PROMPT:  # 옛 버전이 저장한 "[Image #17]" 같은 이름을 정리한다
                    # 비어도 rank 는 그대로 둔다 — 첫 요청은 이미 지나갔으니 대화 중간 말("응 계속 해")이 이름이
                    # 되지 않고 display_title 의 브랜치·스킬·폴더 이름으로 보이게 한다
                    s["title"] = " ".join(prompt_title(str(s.get("title") or "")).split())[:60]
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
                    "permissionMode": "", "model": "", "currentSkill": "", "currentAction": "", "startedAt": now, "updatedAt": now,
                    "log": [], "chat": [], "report": "", "changedFiles": [], "touchedFiles": [], "prLinks": [], "subagents": [], "skillStates": {},
                    "pending_stop": [], "turn_running": False, "ended": False, "managed_alive": False,
                    "turn": {"skill": None, "unknown": False}, "flowState": None,
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

    def add_chat(self, s: dict, role: str, text: str = "", **extra) -> bool:
        """대화 목록(s["chat"], 오래된 것부터)에 항목을 더한다. 바로 앞 항목이 같은 role·같은 글이면 더하지 않는다
        (훅과 콘솔 전송, 콘솔 마지막 블록과 Stop 보고가 같은 글을 두 번 알린다). 더했으면 True."""
        text = str(text or "").strip()[:CHAT_TEXT_LIMIT]
        if role != "req" and not text:
            return False
        with self.lock:
            chat = s.get("chat")
            if not isinstance(chat, list):
                chat = s["chat"] = []
            if role != "req" and not extra.get("attachments") and chat and chat[-1].get("role") == role and chat[-1].get("text") == text:
                return False
            item = {"t": self.clock(), "role": role}
            if role != "req":
                item["text"] = text
            item.update(extra)
            chat.append(item)
            del chat[:-CHAT_LIMIT]
        return True

    def _chat_answer(self, r: "Request") -> None:
        """처리된 요청의 답을 같은 id 의 대화 항목에 채운다(store.lock 안에서 부른다)."""
        s = self.sessions.get(r.session_id)
        for item in reversed((s.get("chat") if s else None) or []):
            if isinstance(item, dict) and item.get("role") == "req" and item.get("id") == r.rid:
                item["answer"] = request_answer(r)
                return

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
                existing["chat"] = (list(s.get("chat") or []) + list(existing.get("chat") or []))[-CHAT_LIMIT:]
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

    def touch_peers(self, s: dict) -> None:
        """같은 폴더의 다른 세션 화면이 sameFolder 를 다시 받게 알린다(저장하지는 않는다)."""
        with self.lock:
            ids = same_folder_ids(self, s)
        for sid in ids:
            self.publish("session", {"id": sid})

    # ---- 폴더 ----
    def add_folder(self, path: str) -> None:
        with self.lock:
            self.folders[:] = [f for f in self.folders if not platform_compat.same_path(f, path)]
            self.folders.insert(0, path)
            del self.folders[20:]

    # ---- 요청 ----
    def add_request(self, sid, kind, tool_name, tool_input, suggestions, key, risk: str = "", risk_note: str = "") -> tuple[Request, bool]:
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
                raise RequestLimit("대기 중인 요청이 너무 많아.")
            r = Request(uuid.uuid4().hex[:12], sid, kind, tool_name, tool_input, suggestions, key, self.clock())
            r.risk, r.risk_note = risk, risk_note
            self.requests[r.rid] = r
            s = self.sessions.get(sid)
            if s is not None:
                self.add_chat(s, "req", id=r.rid, kind=kind, title=request_title(kind, tool_name, tool_input), answer=None)
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
            self._chat_answer(r)
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
            self._chat_answer(r)
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


def new_start_checks() -> list[dict]:
    return [{"id": cid, "state": CHECK_PENDING} for cid in START_CHECK_IDS]


def mark_check(s: dict, cid: str, state: str = CHECK_DONE) -> bool:
    """새 세션 점검 한 항목을 대기에서 바꾼다. 이미 했거나 건너뛴 항목, 없는 항목은 그대로 둔다. 바뀌었으면 True."""
    for item in s.get("startChecks") or []:
        if item["id"] == cid and item["state"] == CHECK_PENDING:
            item["state"] = state
            return True
    return False


REPORT_TAIL_TRIM = " \t*_`~\"'”’)」』>]"


def report_asks(report: str) -> bool:
    """마지막 결과 보고가 질문으로 끝났는가(추정). 끝 줄의 끝 글자가 물음표이면 그렇다고 본다. 도구 질문창(AskUserQuestion)이 아니라
    글로 물은 경우를 잡으려는 것이라 틀릴 수 있고, 화면은 이를 추정으로 보여 준다."""
    lines = [ln.strip() for ln in str(report or "").splitlines() if ln.strip()]
    if not lines:
        return False
    return lines[-1].rstrip(REPORT_TAIL_TRIM).endswith(("?", "？"))


def _skipped(s: dict, p: str) -> bool:
    """건너뛰는 폴더(.git, node_modules 등) 안의 경로인가."""
    try:
        rel = os.path.relpath(p, s["cwd"]) if s.get("cwd") and os.path.isabs(p) else p
    except ValueError:
        return False
    return any(part in SKIP_DIRS for part in rel.replace("\\", "/").split("/")[:-1])


def _key(p: str) -> str:
    """경로 비교용 키. 구분자(\\ /)와 대소문자(Windows)를 같게 본다."""
    return os.path.normcase(os.path.normpath(p))


def _after_start(s: dict, p: str) -> bool:
    """세션이 시작된 뒤에 마지막으로 바뀐 파일인가(세션 시작 시각을 모르거나 파일을 못 읽으면 아니라고 본다)."""
    started = s.get("startedAt")
    if not isinstance(started, (int, float)):
        return False
    try:
        return os.stat(p).st_mtime >= started
    except OSError:
        return False


def set_baseline(s: dict, paths) -> None:
    """세션을 처음 본 때 이미 바뀌어 있던 파일을 기준선으로 한 번만 적는다. 이 파일들은 git status 만으로는 이 세션 것으로 치지 않는다.
    기준선이 늦게 잡혀도(첫 refresh_git 이 첫 턴 끝에 오면) 세션 시작 뒤에 바뀐 파일은 기준선에 넣지 않는다 — 그 턴에 만든 파일이 빠지지 않게."""
    if "baselineFiles" not in s:
        s["baselineFiles"] = [_key(p) for p in paths if isinstance(p, str) and p and not _after_start(s, p)]


def remember_touched(s: dict, paths, from_status: bool = False) -> None:
    """이 세션이 만들거나 바꾼 파일 경로를 쌓는다. changedFiles(지금 git 상태)와 달리 커밋해도 지우지 않는다(만든 문서 목록용).
    from_status 이면 git status 에서 온 경로라 기준선(세션 시작 전부터 바뀌어 있던 파일)은 뺀다. 훅의 Edit·Write 경로는 이 세션 것이 확실해 그대로 쌓는다.
    작업 폴더 밖 경로(작업 폴더가 저장소 하위일 때 git status 에 같이 나온다)는 쌓지 않고, 구분자·대소문자만 다른 경로는 같은 것으로 본다.
    상한에 닿으면 touchedTruncated 를 켜서 화면이 목록이 잘렸다고 알리게 한다."""
    touched = s.setdefault("touchedFiles", [])
    base = set(s.get("baselineFiles") or []) if from_status else set()
    seen = {_key(t) for t in touched}
    for p in paths:
        if not isinstance(p, str) or not p:
            continue
        k = _key(p)
        if k in seen or k in base or _skipped(s, p):
            continue
        if s.get("cwd") and os.path.isabs(p) and not platform_compat.is_within(p, s["cwd"]):
            continue
        if len(touched) >= MAX_CHANGED_FILES:
            s["touchedTruncated"] = True
            break
        touched.append(p)
        seen.add(k)


def same_folder_ids(store: "Store", s: dict) -> list[str]:
    """같은 폴더(정규화해 비교)에서 살아 있는 다른 세션 id. 끝난 세션과 프로세스가 죽은 콘솔 세션은 뺀다."""
    if not s["cwd"] or s.get("handedOffTo"):  # 넘어간 세션 자신도 경고를 받지 않는다
        return []
    with store.lock:
        return [o["id"] for o in store.sessions.values()
                if o is not s and o["cwd"] and not o["ended"] and not o.get("handedOffTo") and (o.get("managed_alive") or not o["managed"])
                and platform_compat.same_path(o["cwd"], s["cwd"])]


CANNOT_SEND_IDLE = "쉬는 터미널 세션이라 여기서는 새로 시킬 수 없어. 터미널에서 이어서 말해 줘."
CANNOT_SEND_ENDED = "끝난 터미널 세션이야."


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


def last_block_of(chat: list) -> dict | None:
    """마지막 훅 막힘. open 은 그 뒤에 내 말·AI 말이 아직 없다는 뜻(있으면 이미 이어 간 것이라 풀린 걸로 본다 — 확인 못 함은 풀렸는지 알 수 없어도 이어 갔으면 닫는다)."""
    items = [c for c in chat if isinstance(c, dict)]
    for i in range(len(items) - 1, -1, -1):
        c = items[i]
        if c.get("role") == "block":
            return {"t": c.get("t"), "kind": c.get("kind") or "blocked",
                    "open": not any(x.get("role") in ("me", "ai") for x in items[i + 1:])}
    return None


def public_session(store: Store, s: dict, skills: list[str], include_chat: bool = False) -> dict:
    """화면에 내려보내는 세션 모델(web-console.md §8). 대화(chat)는 크기 때문에 include_chat 일 때만(단일 세션 응답) 싣는다."""
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
        asks = bool(not pending and not running and not s["ended"] and not s.get("starting")
                    and s.get("reportFresh") and report_asks(s["report"]))  # 이번 턴에 받은 보고일 때만
        phase = flows.phase_of(s) if not (pending or asks or running or s.get("starting") or s["ended"]) else ""
        if pending or asks or (turn_skill and not running and not s["ended"] and not phase):
            group = "todo"
        elif running:
            group = "running"
        else:
            group = "idle"
        extra = {"chat": [dict(c) for c in s.get("chat") or [] if isinstance(c, dict)]} if include_chat else {}
        last_block = last_block_of(s.get("chat") or [])  # 목록 갱신만으로 새 막힘을 알아채게(알림용) · open 은 홈·목록 표시용
        return dict(flows.public_fields(s, store.flow_data), **extra, **{
            "chatPartial": not s["managed"],  # 터미널 세션은 내 말과 AI 마지막 답만 안다
            "id": s["id"], "title": display_title(s), "cwd": s["cwd"], "repo": s["repo"], "branch": s["branch"],
            "managed": s["managed"], "canAttach": bool(s["managed"]), "status": status, "group": group, "permissionMode": s["permissionMode"],
            "model": s.get("model", ""), "modelChoice": s.get("modelChoice", ""),
            "effortChoice": s.get("effortChoice", ""), "permissionChoice": s.get("permissionChoice", ""),
            "permissionNote": s.get("permissionNote", ""),
            "currentSkill": s["currentSkill"], "currentAction": s["currentAction"],
            "startedAt": s["startedAt"], "updatedAt": s["updatedAt"], "log": list(s["log"]), "report": s["report"],
            "changedFiles": list(s["changedFiles"]), "prLinks": list(s["prLinks"]), "subagents": list(s["subagents"]),
            "flow": flow, "turnSkill": turn_skill, "turnUnknown": bool(s["turn"].get("unknown")),
            "askedInText": asks, "lastBlock": last_block, "phase": phase,
            "pendingRequestIds": pending, "canSend": ok, "cannotSendReason": why,
            "bypassPermissions": s["permissionMode"] == "bypassPermissions",
            "pluginVersions": [dict(p) for p in s.get("pluginVersions") or []],
            "sameFolder": same_folder_ids(store, s), "handedOffTo": s.get("handedOffTo") or None,
            "startChecks": [dict(c) for c in s.get("startChecks") or []],
            "context": context_usage.for_session(s),
        })
