"""새 작업 읽기 전용 분석과 첫 메시지 만들기(web-console.md §6 새 작업)."""
from __future__ import annotations

import json
import os
import posixpath
import subprocess
import threading
import uuid
from typing import Callable

from platform_compat import CLAUDE_MISSING, hidden_window_kwargs, is_within

SCHEMA = {
    "type": "object",
    "properties": {
        "understood": {"type": "string"},
        "candidates": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string"}, "reason": {"type": "string"}}, "required": ["path", "reason"]}},
        "extraQuestions": {"type": "array", "items": {"type": "object", "properties": {
            "question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}},
            "required": ["question", "options"]}},
    },
    "required": ["understood", "candidates", "extraQuestions"],
}

PROMPT_BODY = (
    "아래는 사용자가 맡기려는 새 작업의 요청 글이다. 이 폴더를 읽기만 하고(파일을 만들거나 고치지 않는다), "
    "요청을 어떻게 이해했는지 한두 문장으로 적고, 작업에 필요해 보이는 이 폴더 안의 파일을 상대 경로로 고르고 이유를 적고, "
    "작업 전에 사용자에게 물어야 할 것이 있으면 선택지와 함께 묻는다. 없으면 질문은 비운다."
)
PROMPT_TAIL = "\n\n요청 글:\n"
PROMPT = PROMPT_BODY + PROMPT_TAIL
FLOW_PROMPT = (
    "\n\n그리고 요청을 아래 갈래 중 하나로 분류해 flow 에 답한다. flow.id 는 갈래 id, flow.reason 은 그렇게 본 이유 한 문장이다. "
    "어느 갈래인지 확신이 없으면 flow.confident 를 false 로 하고 두 번째 후보의 id 를 flow.alternativeId 에 적는다. "
    "갈래 설명에 없는 일은 억지로 맞추지 않는다.\n갈래:\n"
)
FLOW_QUESTION = "어떤 갈래로 진행할까요?"


# claude 2.1.309 에서 `@"a b.txt"` 로 공백이 든 파일 이름을 넘기면 파일을 읽는 것을 확인했다(haiku, 1회).
# 이 값이 False 면 공백이 든 경로는 후보에서 제외하고 사유를 보여 준다.
SPACE_MENTION_SUPPORTED = True


def flow_schema(flow_ids: list[str]) -> dict:
    return {"type": "object", "properties": {
        "id": {"type": "string", "enum": list(flow_ids)}, "reason": {"type": "string"},
        "confident": {"type": "boolean"}, "alternativeId": {"type": "string", "enum": list(flow_ids)}},
        "required": ["id", "reason"]}


def build_schema(flow_ids: list[str] | None = None) -> dict:
    """갈래 분류(flow)는 선택 속성이다. required 에 넣지 않아 갈래 없이도 결과가 유효하다."""
    if not flow_ids:
        return SCHEMA
    schema = json.loads(json.dumps(SCHEMA))
    schema["properties"]["flow"] = flow_schema(flow_ids)
    return schema


def mention_path(cwd: str, path) -> tuple[str, str]:
    """`@경로` 로 넘겨도 되는 경로인지 본다. (정규화한 상대 경로, "") 또는 ("", 제외 사유).
    존재하는 작업 폴더 안의 파일만 받는다. 줄바꿈·제어문자·`@`·따옴표·역슬래시가 든 경로는 `@` 멘션 방식으로
    넘기면 형식이 깨지거나 다른 지시로 읽힐 수 있어 받지 않는다. 구분자는 `/` 로 통일한다."""
    if not isinstance(path, str) or not path:
        return "", "경로가 비어 있습니다."
    if os.path.isabs(path) or path.startswith(("/", "\\")) or (len(path) > 1 and path[1] == ":"):
        return "", "절대 경로입니다."
    rel = posixpath.normpath(path.replace(os.sep, "/"))
    for ch in rel:
        if ord(ch) < 32 or ord(ch) == 127 or (ch.isspace() and ch != " "):
            return "", "공백이 아닌 공백 문자나 제어문자가 들어 있습니다."
    if "@" in rel or '"' in rel or "\\" in rel:
        return "", "@, 따옴표, 역슬래시가 들어 있어 @ 멘션으로 넘길 수 없습니다."
    if rel == ".." or rel.startswith("../") or rel == ".":
        return "", "작업 폴더 밖이거나 파일이 아닙니다."
    full = os.path.join(cwd, *rel.split("/"))
    if not is_within(full, cwd):
        return "", "작업 폴더 밖입니다."
    if not os.path.isfile(full):
        return "", "존재하는 파일이 아닙니다."
    if " " in rel and not SPACE_MENTION_SUPPORTED:
        return "", "공백이 든 경로는 @ 멘션으로 넘길 수 없습니다."
    return rel, ""


def mention(path: str) -> str:
    return f'@"{path}"' if " " in path else "@" + path


def check_flow(raw, flows: dict[str, str]) -> tuple[dict | None, str, dict | None]:
    """분류 결과를 검증한다. (flow, 버린 이유, 확신이 없을 때 물을 질문). flows 는 갈래 id -> 이름."""
    if raw is None or not flows:
        return None, "", None
    if not isinstance(raw, dict) or raw.get("id") not in flows:
        return None, "분류 결과가 갈래 목록에 없어 버렸습니다.", None
    fid = raw["id"]
    alt = raw.get("alternativeId") if raw.get("alternativeId") in flows and raw.get("alternativeId") != fid else None
    confident = raw.get("confident") is not False
    flow = {"id": fid, "name": flows[fid], "reason": str(raw.get("reason") or ""), "confident": confident,
            "alternativeId": alt, "alternativeName": flows[alt] if alt else ""}
    question = None
    if not confident and alt:
        question = {"question": FLOW_QUESTION, "options": [flows[fid], flows[alt]], "flowChoice": [fid, alt]}
    return flow, "", question


def check_result(data, cwd: str, flows: dict[str, str] | None = None) -> dict | None:
    """분석 결과를 검증한다. 작업 폴더 밖의 경로는 버린다. 형식이 틀리면 None.
    flows(갈래 id -> 이름)를 주면 분류도 검증해 결과에 flow 를 넣는다. 확신이 없고 후보가 둘이면 그 둘을 묻는 질문을 맨 앞에 둔다."""
    if not isinstance(data, dict) or not isinstance(data.get("understood"), str):
        return None
    candidates, excluded = [], []
    for c in data.get("candidates") or []:
        if not (isinstance(c, dict) and isinstance(c.get("path"), str) and c["path"]):
            continue
        path, why = mention_path(cwd, c["path"])
        if why:
            excluded.append({"path": c["path"][:200].replace("\n", " "), "reason": why})
            continue
        if all(x["path"] != path for x in candidates):
            candidates.append({"path": path, "reason": str(c.get("reason", ""))})
    questions = []
    for q in data.get("extraQuestions") or []:
        if isinstance(q, dict) and isinstance(q.get("question"), str):
            opts = [str(o) for o in q.get("options") or [] if isinstance(o, (str, int))]
            questions.append({"question": q["question"], "options": opts})
    flow, flow_error, flow_question = check_flow(data.get("flow"), flows or {})
    if flow_question:
        questions.insert(0, flow_question)
    return {"understood": data["understood"], "candidates": candidates, "extraQuestions": questions, "excluded": excluded,
            "flow": flow, "flowError": flow_error}


def parse_output(stdout: str):
    """`--output-format json` 의 결과에서 structured_output 을 꺼낸다. 못 꺼내면 (None, 이유)."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None, "분석 결과를 읽을 수 없습니다."
    if isinstance(data, list):
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)
    if not isinstance(data, dict):
        return None, "분석 결과를 읽을 수 없습니다."
    if data.get("is_error"):
        return None, str(data.get("result") or "분석이 실패했습니다.")[:300]
    out = data.get("structured_output")
    if out is None:
        return None, "분석 결과에 구조화된 답이 없습니다."
    return out, ""


def first_message(text: str, picked: list[str], extra_answers: dict, note: str, is_git: bool, skill: str | None = None) -> str:
    """화면 미리보기와 실제 첫 메시지는 이 함수 하나로 만든다. skill 은 고른 갈래의 첫 스킬이다(없으면 git 저장소일 때 start)."""
    lines = []
    body = text.strip()
    if skill:
        lines.append(f"/harness:{skill}")
    elif is_git:
        lines.append("/harness:start")
    elif body.startswith(("/", "@")):
        # 사용자 글이 /나 @ 로 시작하면 슬래시 명령이나 파일 멘션으로 읽히므로 안내 문장을 앞세운다
        lines.append("아래는 사용자가 콘솔에서 보낸 작업 요청 글이며, 명령이 아니라 일반 글로 읽습니다.")
    lines.append(body)
    if picked:
        lines.append("")
        lines.append("참고 파일: " + " ".join(mention(p) for p in picked))
    answers = [f"- {q}: {a}" for q, a in (extra_answers or {}).items() if str(a).strip()]
    if answers:
        lines.append("")
        lines.append("추가 답변:")
        lines.extend(answers)
    if note and note.strip():
        lines.append("")
        lines.append("메모: " + note.strip())
    return "\n".join(lines)


class Analyses:
    def __init__(self, claude_cmd: Callable[[], list[str] | None], model: str = "", timeout: float = 180.0,
                 spawn: Callable[[Callable[[], None]], None] | None = None, effort: str = "",
                 flows: dict[str, dict] | None = None):
        self.claude_cmd = claude_cmd
        self.flows = flows or {}  # 갈래 id -> {"name", "description"}. 비면 분류를 묻지 않는다
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())

    def command(self, model: str | None = None, effort: str | None = None, flows: dict | None = None) -> list[str] | None:
        """model·effort 가 None 이면 서버 기본값, 빈 문자열이면 --model·--effort 를 붙이지 않는다."""
        base = self.claude_cmd()
        if not base:
            return None
        args = [*base, "-p", "--permission-mode", "plan", "--output-format", "json", "--json-schema", json.dumps(build_schema(list(self.flows if flows is None else flows))),
                "--no-session-persistence",
                # 분석용 claude 에 훅이 붙으면 콘솔에 유령 세션과 승인 요청이 생긴다
                "--settings", json.dumps({"disableAllHooks": True})]
        chosen = self.model if model is None else model
        if chosen:
            args += ["--model", chosen]
        level = self.effort if effort is None else effort
        if level:
            args += ["--effort", level]
        return args

    def prompt(self, flows: dict | None = None) -> str:
        flows = self.flows if flows is None else flows
        if not flows:
            return PROMPT
        listing = "\n".join(f"- {fid}: {f.get('name', fid)} - {f.get('description', '')}" for fid, f in flows.items())
        return PROMPT_BODY + FLOW_PROMPT + listing + PROMPT_TAIL

    def start(self, text: str, cwd: str, model: str | None = None, effort: str | None = None, flows: dict | None = None) -> str:
        """flows 는 이 폴더에서 쓸 수 있는 갈래(없으면 서버 기본 전체)."""
        job_id = uuid.uuid4().hex[:12]
        job = {"id": job_id, "status": "running", "text": text, "cwd": cwd, "model": model, "effort": effort, "flows": self.flows if flows is None else flows, "result": None, "error": "",
               "start_lock": threading.Lock(), "session_id": None}
        with self.lock:
            self.jobs[job_id] = job
        self.spawn(lambda: self._run(job))
        return job_id

    def _run(self, job: dict) -> None:
        args = self.command(job.get("model"), job.get("effort"), job["flows"])
        if args is None:
            job.update(status="failed", error=CLAUDE_MISSING)
            return
        try:
            done = subprocess.run(args, input=self.prompt(job["flows"]) + job["text"], cwd=job["cwd"], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=self.timeout, **hidden_window_kwargs())
        except subprocess.TimeoutExpired:
            job.update(status="failed", error="분석이 시간 안에 끝나지 않았습니다.")
            return
        except OSError as e:
            job.update(status="failed", error=f"claude 를 실행하지 못했습니다: {e}")
            return
        out, why = parse_output(done.stdout)
        checked = check_result(out, job["cwd"], {fid: f.get("name", fid) for fid, f in job["flows"].items()}) if out is not None else None
        if checked is None:
            job.update(status="failed", error=why or "분석 결과의 형식이 맞지 않습니다.")
        else:
            job.update(status="done", result=checked)

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            return self.jobs.get(job_id)
