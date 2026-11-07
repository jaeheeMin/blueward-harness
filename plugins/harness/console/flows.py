"""갈래(flow) 데이터 읽기·검사와 세션의 갈래 진행 상태(web-console.md §갈래). 갈래와 단계는 플러그인의 workflow.json 이 정한다.
이 모듈은 파일·네트워크를 직접 부르지 않는다. 읽기(git·gh)는 호출한 쪽이 fetch 로 넘겨 주고, 조건은 cond 로 넘겨 준다.
데이터 검사(validate)만 근거(basis) 문장을 확인하려고 플러그인 안의 스킬·규칙 파일을 읽는다."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Callable

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PLUGIN_ROOT / "workflow.json"
STEP_KINDS = {"skill", "human", "work", "wait"}
TOOL_KINDS = {"skill", "console"}
CONDITION_TYPES = {"file", "approver", "paths"}
BASIS_READ_LIMIT = 2 << 20
PENDING, ACTIVE, DONE, SKIPPED = "pending", "active", "done", "skipped"
EVIDENCE_TOKENS = {"skill_done", "has_changes", "on_work_branch", "pr_exists", "pr_merged", "manual"}
MAX_REASON = 500
NEXT_HINT = "새 세션으로 시작하십시오."
SRS_READ_LIMIT = 4 << 20

Cond = Callable[[str], "bool | None"]  # 조건 이름 -> 참/거짓/None(판정 불능)
Fetch = Callable[[str], "dict | None"]  # "changes" | "pr" -> 증거


def load(path: Path = DATA_FILE) -> tuple[dict | None, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"갈래 데이터를 읽지 못했습니다({Path(path).name}): {e}"
    return (data, "") if isinstance(data, dict) else (None, "갈래 데이터가 객체가 아닙니다.")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def basis_errors(where: str, basis, root: Path, cache: dict[str, str | None]) -> list[str]:
    """basis: [{"file": 플러그인 기준 경로, "quote": 그 파일에 실제로 있는 문장}]. 비었거나, 파일이 없거나, 문장이 파일에 없으면 오류.
    줄바꿈·공백 차이는 무시한다(문서가 줄을 접어 쓰므로)."""
    if not isinstance(basis, list) or not basis:
        return [f"{where}: basis(근거 스킬·규칙 문장)가 비어 있습니다. 근거 문장을 못 찾으면 이 항목을 넣지 않습니다."]
    errors: list[str] = []
    for item in basis:
        if not isinstance(item, dict) or not isinstance(item.get("file"), str) or not isinstance(item.get("quote"), str) \
                or not item["file"].strip() or not _squash(item["quote"]):
            errors.append(f"{where}: basis 항목은 file 과 quote 문자열을 가져야 합니다.")
            continue
        rel = item["file"]
        if rel not in cache:
            try:
                path = (root / rel).resolve()
                if not path.is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size > BASIS_READ_LIMIT:
                    raise OSError("플러그인 안의 파일이 아니거나 없거나 너무 큽니다.")
                cache[rel] = _squash(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError):
                cache[rel] = None
        if cache[rel] is None:
            errors.append(f"{where}: basis 파일 {rel!r} 을 읽을 수 없습니다.")
        elif _squash(item["quote"]) not in cache[rel]:
            errors.append(f"{where}: basis 문장이 {rel} 에 없습니다: {item['quote'][:40]!r}")
    return errors


def validate(data: dict, skill_names: set[str], root: Path | None = None) -> list[str]:
    """데이터의 모든 스킬이 실제로 있고, 가리키는 갈래·조건·증거가 정의돼 있고, 갈래·단계·다음 갈래·도구·조건마다 근거 문장이
    실제 파일에 있는지 본다. root 는 basis 파일의 기준 폴더(기본: 플러그인 폴더). 문제 목록(비면 유효)."""
    errors: list[str] = []
    root = root or PLUGIN_ROOT
    cache: dict[str, str | None] = {}

    def basis_ok(where: str, owner) -> None:
        errors.extend(basis_errors(where, owner.get("basis") if isinstance(owner, dict) else None, root, cache))

    conditions = data.get("conditions") if isinstance(data.get("conditions"), dict) else {}
    for name, cond in conditions.items():
        if not isinstance(cond, dict) or cond.get("type") not in CONDITION_TYPES:
            errors.append(f"조건 {name}: 종류가 {sorted(CONDITION_TYPES)} 중 하나여야 합니다.")
            continue
        basis_ok(f"조건 {name}", cond)
        if cond.get("type") == "approver" and cond.get("whenNoFile", "admin") != "admin":
            errors.append(f"조건 {name}: whenNoFile 은 \"admin\" 만 쓸 수 있습니다(엔진과 같은 판정).")
        elif cond.get("type") == "paths":
            paths = cond.get("paths")
            if not isinstance(paths, list) or not paths or any(not isinstance(p, str) or not p or p.startswith("/") or ".." in p.split("/") for p in paths):
                errors.append(f"조건 {name}: paths 는 저장소 안 상대 경로 문자열 목록이어야 합니다.")
            depth = cond.get("searchDepth", 0)
            if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 5:
                errors.append(f"조건 {name}: searchDepth 는 0~5 정수여야 합니다.")
            exempt = cond.get("exemptFile")
            if exempt is not None and (not isinstance(exempt, str) or not exempt or exempt.startswith("/") or ".." in exempt.split("/")):
                errors.append(f"조건 {name}: exemptFile 은 저장소 안 상대 경로 문자열이어야 합니다.")
    flows = data.get("flows")
    if not isinstance(flows, list) or not flows:
        return errors + ["flows 가 비어 있습니다."]
    ids = [f.get("id") for f in flows if isinstance(f, dict)]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and i for i in ids):
        errors.append("갈래 id 가 비었거나 겹칩니다.")

    def skill_ok(where: str, skill) -> None:
        if skill not in skill_names:
            errors.append(f"{where}: 스킬 {skill!r} 이 skills/ 에 없습니다.")

    def flow_ok(where: str, target) -> None:
        if target is not None and target not in ids:
            errors.append(f"{where}: 갈래 {target!r} 이 없습니다.")

    for f in flows:
        if not isinstance(f, dict):
            errors.append("갈래가 객체가 아닙니다.")
            continue
        fid = f.get("id")
        basis_ok(f"갈래 {fid}", f)
        if f.get("requires") is not None and f["requires"] not in conditions:
            errors.append(f"{fid}: requires {f['requires']!r} 조건이 없습니다.")
        steps = f.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"{fid}: steps 가 비어 있습니다.")
            continue
        step_ids = [s.get("id") for s in steps if isinstance(s, dict)]
        if len(set(step_ids)) != len(step_ids):
            errors.append(f"{fid}: 단계 id 가 겹칩니다.")
        for s in steps:
            where = f"{fid}/{s.get('id') if isinstance(s, dict) else '?'}"
            if not isinstance(s, dict) or s.get("kind") not in STEP_KINDS:
                errors.append(f"{where}: kind 가 {sorted(STEP_KINDS)} 중 하나여야 합니다.")
                continue
            basis_ok(where, s)
            if s["kind"] == "skill":
                skill_ok(where, s.get("skill"))
            if s.get("helperSkill") is not None:
                skill_ok(where + " helperSkill", s["helperSkill"])
            done = s.get("done")
            if not isinstance(done, list) or not done or any(t not in EVIDENCE_TOKENS for t in done):
                errors.append(f"{where}: done {done!r} 은 {sorted(EVIDENCE_TOKENS)} 안의 값을 하나 이상 가진 목록이어야 합니다.")
            elif "skill_done" in done and s["kind"] != "skill":
                errors.append(f"{where}: skill_done 은 스킬 단계에만 쓸 수 있습니다.")
            if s.get("onlyIf") is not None and s["onlyIf"] not in conditions:
                errors.append(f"{where}: onlyIf {s['onlyIf']!r} 조건이 없습니다.")
        rule = f.get("next")
        if isinstance(rule, dict):
            if "srsColumn" in rule:
                col = rule["srsColumn"]
                if not isinstance(col, dict) or not isinstance(col.get("branches"), dict) or not col.get("file") or not col.get("column"):
                    errors.append(f"{fid}: next.srsColumn 형식이 맞지 않습니다.")
                else:
                    basis_ok(f"{fid}: next.srsColumn", col)
                    for value, branch in col["branches"].items():
                        flow_ok(f"{fid}: next.srsColumn.{value}", branch.get("flow") if isinstance(branch, dict) else None)
                        basis_ok(f"{fid}: next.srsColumn.{value}", branch)
                        skip = branch.get("skipStatuses") if isinstance(branch, dict) else None
                        if skip is not None and (not isinstance(skip, list) or any(not isinstance(x, str) for x in skip)):
                            errors.append(f"{fid}: next.srsColumn.{value}: skipStatuses 는 문자열 목록이어야 합니다.")
            else:
                flow_ok(f"{fid}: next", rule.get("flow"))
                basis_ok(f"{fid}: next", rule)
    for t in data.get("tools") or []:
        where = f"도구 {t.get('id') if isinstance(t, dict) else '?'}"
        if not isinstance(t, dict) or t.get("kind") not in TOOL_KINDS:
            errors.append(f"{where}: kind 가 {sorted(TOOL_KINDS)} 중 하나여야 합니다.")
            continue
        basis_ok(where, t)
        if t["kind"] == "skill":
            skill_ok(where, t.get("skill"))
        if t.get("requires") is not None and t["requires"] not in conditions:
            errors.append(f"{where}: requires {t['requires']!r} 조건이 없습니다.")
    return errors


def missing_skills(data: dict, skill_names) -> list[str]:
    """skills/ 에 있는데 workflow.json 의 단계(skill·helperSkill)에도 도구(tools)에도 없는 스킬. PR 검사가 비어 있어야 통과시킨다."""
    used = flow_skills(data) | tool_skills(data)
    return sorted(s for s in skill_names if s not in used)


def flow_def(data: dict, fid) -> dict | None:
    return next((f for f in data.get("flows", []) if f.get("id") == fid), None)


def tool_skills(data: dict) -> set[str]:
    return {t["skill"] for t in data.get("tools", []) if t.get("kind") == "skill"}


def flow_skills(data: dict) -> set[str]:
    out = set()
    for f in data.get("flows", []):
        for s in f.get("steps", []):
            out.update(x for x in (s.get("skill"), s.get("helperSkill")) if x)
    return out


# ---- 세션의 갈래 상태 ----

def new_state(flow: dict, reason: str, now: float, cond: Cond) -> dict:
    steps = [{"id": s["id"], "name": s.get("name", s["id"]), "kind": s["kind"], "skill": s.get("skill"),
              "helperSkill": s.get("helperSkill"), "hint": s.get("hint", ""), "onlyIf": s.get("onlyIf"), "done": list(s["done"]),
              "state": PENDING, "reason": "", "skillDone": False, "confirmed": False} for s in flow["steps"]]
    state = {"id": flow["id"], "name": flow.get("name", flow["id"]), "reason": str(reason or "")[:MAX_REASON], "assignedAt": now,
             "stepIndex": 0, "steps": steps, "finished": False, "unknown": [], "next": None, "prNumber": None, "pr": None}
    settle(state, cond, now)
    return state


def current(state: dict | None) -> dict | None:
    if not state or state.get("finished"):
        return None
    idx = state["stepIndex"]
    return state["steps"][idx] if 0 <= idx < len(state["steps"]) else None


def settle(state: dict, cond: Cond, now: float) -> bool:
    """끝났거나 건너뛴 단계를 넘기고, 조건이 안 맞는 단계(onlyIf)는 건너뛰고, 사람·작업·대기 단계는 진행 중으로 바꾼다.
    지금 단계의 조건을 판정하지 못했으면(None) 건너뛰지도 끝내지도 않고 True 를 돌려준다(unknown 에 사유를 적는다)."""
    steps = state["steps"]
    undecided = False
    while state["stepIndex"] < len(steps):
        st = steps[state["stepIndex"]]
        if st["state"] in (DONE, SKIPPED):
            state["stepIndex"] += 1
            continue
        if st.get("onlyIf"):
            value = cond(st["onlyIf"])
            if value is False:
                st["state"], st["reason"] = SKIPPED, f"조건에 맞지 않아 건너뜀: {st['onlyIf']}"
                state["stepIndex"] += 1
                continue
            if value is None:
                undecided = True
                msg = f"조건 {st['onlyIf']} 을 확인하지 못했습니다."
                if msg not in state["unknown"]:
                    state["unknown"].append(msg)
        if st["kind"] != "skill" and st["state"] == PENDING:
            st["state"] = ACTIVE
        break
    state["finished"] = state["stepIndex"] >= len(steps)
    if state["finished"] and not state.get("finishedAt"):
        state["finishedAt"] = now
    return undecided


def skill_started(s: dict, skill: str) -> None:
    """Skill 이벤트: 지금 단계의 스킬이 시작되면 진행 중으로 바꾼다. 순서 밖 스킬은 기록하지 않는다(막는 건 API 의 일이다)."""
    st = current(s.get("flowState"))
    if st and st["kind"] == "skill" and st["skill"] == skill and st["state"] == PENDING:
        st["state"] = ACTIVE


def turn_ended(s: dict, asking: bool = False) -> None:
    """Stop: 진행 중인 스킬 단계는 그 스킬이 끝난 것으로 적는다(done 판정은 evaluate 가 한다).
    사용자에게 묻는 질문이 답을 기다리는 중(asking)의 Stop 은 스킬이 끝난 것이 아니다."""
    st = current(s.get("flowState"))
    if st and st["kind"] == "skill" and st["state"] == ACTIVE and not asking:
        st["skillDone"] = True


def _token(state: dict, st: dict, token: str, fetch: Fetch):
    if token == "skill_done":
        return st["skillDone"]
    if token == "manual":
        return st["confirmed"]
    if token in ("has_changes", "on_work_branch"):
        ev = fetch("changes" if token == "has_changes" else "branch")
        return None if ev is None or ev.get("state") != "ok" else bool(ev.get("value"))
    ev = fetch("pr")
    if ev is None or ev.get("state") != "ok":
        reason = (ev or {}).get("reason") or "PR 상태를 확인하지 못했습니다."
        if reason not in state["unknown"]:
            state["unknown"].append(reason)
        return None
    pr = ev.get("pr")
    state["pr"] = pr
    if pr and pr.get("number"):
        state["prNumber"] = pr["number"]
    if token == "pr_exists":
        return pr is not None
    return bool(pr and pr.get("state") == "MERGED")


def evaluate(state: dict, fetch: Fetch, cond: Cond, now: float) -> bool:
    """지금 단계의 완료 근거가 모두 맞으면 끝으로 바꾸고 다음 단계로 간다. 근거를 확인 못 하면 그대로 두고 unknown 에 사유를 적는다.
    fetch 는 같은 호출 안에서 증거를 한 번만 읽도록 호출한 쪽이 기억해 둔다."""
    changed = False
    state["unknown"] = []
    while True:
        undecided = settle(state, cond, now)
        st = current(state)
        if st is None or undecided:
            break  # 조건을 확인하지 못한 단계는 끝내지도 건너뛰지도 않는다
        values = [_token(state, st, t, fetch) for t in st["done"]]
        if not all(v is True for v in values):
            break
        st["state"], st["doneAt"] = DONE, now
        changed = True
    return changed


def confirm(s: dict) -> str:
    """사람이 '끝났다' 고 누른다. 지금 단계에 manual 이 없으면 사유 문장을 돌려준다."""
    st = current(s.get("flowState"))
    if st is None:
        return "진행 중인 단계가 없습니다."
    if "manual" not in st["done"]:
        return f"이 단계({st['name']})는 사람이 끝냈다고 누르는 단계가 아닙니다."
    st["confirmed"] = True
    return ""


def skip(s: dict, reason, now: float, cond: Cond) -> str:
    """지금 단계를 이유와 함께 건너뛴다. 이유가 비면 사유 문장을 돌려준다."""
    if not isinstance(reason, str) or not reason.strip():
        return "건너뛰는 이유를 적어야 합니다."
    st = current(s.get("flowState"))
    if st is None:
        return "진행 중인 단계가 없습니다."
    st["state"], st["reason"], st["skippedAt"] = SKIPPED, reason.strip()[:MAX_REASON], now
    settle(s["flowState"], cond, now)
    return ""


def allowed_skills(s: dict) -> set[str] | None:
    """지금 실행해도 되는 갈래 스킬. 갈래가 없으면 None(제한 없음). 도구 스킬은 따로 항상 허용한다."""
    state = s.get("flowState")
    if not state:
        return None
    st = current(state)
    if st is None:
        return set()
    return {x for x in (st["skill"] if st["kind"] == "skill" else None, st.get("helperSkill")) if x}


def public_fields(s: dict, data: dict | None = None) -> dict:
    """화면용 갈래 상태. `data`(현재 갈래 정의)를 주면 같은 갈래·단계 id 의 이름·설명을 현재 값으로 내보낸다
    (개편 전에 저장된 세션의 옛 이름이 남지 않게). 정의에서 못 찾으면 저장된 값 그대로다. 저장 상태는 바꾸지 않는다."""
    state = s.get("flowState")
    if not state:
        return {"flowId": None, "flowName": "", "flowReason": "", "stepIndex": 0, "flowSteps": [], "flowFinished": False,
                "flowUnknown": [], "flowPr": None, "nextFlow": None}
    keep = ("id", "name", "kind", "skill", "helperSkill", "hint", "short", "onlyIf", "state", "reason")
    flow = flow_def(data, state["id"]) if data else None
    current_steps = {x.get("id"): x for x in (flow or {}).get("steps", []) if isinstance(x, dict)}

    def view(st: dict) -> dict:
        out = {k: st.get(k) for k in keep}
        cur = current_steps.get(st.get("id"))
        if cur:
            out["name"] = cur.get("name", st.get("id"))
            out["hint"] = cur.get("hint", "")
            out["short"] = cur.get("short")
        return out

    flow_name = flow.get("name", state["id"]) if flow else state["name"]
    return {"flowId": state["id"], "flowName": flow_name, "flowReason": state["reason"], "stepIndex": state["stepIndex"],
            "flowSteps": [view(st) for st in state["steps"]], "flowFinished": bool(state["finished"]),
            "flowUnknown": list(state["unknown"]), "flowPr": state.get("pr"), "nextFlow": state.get("next")}


# ---- 다음 갈래 ----

def _option(data: dict, rule: dict) -> dict:
    target = flow_def(data, rule.get("flow")) if rule.get("flow") else None
    return {"flow": rule.get("flow"), "name": target["name"] if target else rule.get("label", ""), "label": rule.get("label", ""),
            "disabled": bool(rule.get("disabled"))}


def read_column(text: str, column: str, id_column: str, status_column: str, skip_statuses: list[str]) -> list[tuple[str, str, str]]:
    """마크다운 표에서 (ID, column 값, 상태) 목록을 읽는다. column 이 든 표만 본다. skip_statuses 상태의 줄은 뺀다
    (갈래마다 빼는 상태가 다르므로 호출한 쪽이 비워 두고 직접 거를 수 있다)."""
    rows: list[tuple[str, str, str]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = cells if column in cells else None
            continue
        if len(cells) < len(header):
            continue
        row = dict(zip(header, cells))
        if status_column in row and row[status_column] in skip_statuses:
            continue
        rows.append((row.get(id_column, ""), row.get(column, ""), row.get(status_column, "")))
    return rows


def compute_next(data: dict, flow: dict, root: str) -> dict | None:
    """갈래가 끝났을 때 다음에 갈 곳. {"options":[{flow,name,label,disabled,...}], "hint", "unknown"?}. 읽지 못하면 unknown 사유를 넣는다."""
    rule = flow.get("next")
    if not isinstance(rule, dict):
        return None
    if "srsColumn" not in rule:
        return {"options": [_option(data, rule)], "hint": NEXT_HINT}
    col = rule["srsColumn"]
    path = os.path.join(root, *col["file"].split("/")) if root else ""
    try:
        if not path or os.path.getsize(path) > SRS_READ_LIMIT:
            raise OSError("파일이 없거나 너무 큽니다.")
        with open(path, encoding="utf-8") as fh:
            rows = read_column(fh.read(), col["column"], col.get("idColumn", "ID"), col.get("statusColumn", "Status"),
                               col.get("skipStatuses", []))
    except (OSError, UnicodeDecodeError) as e:
        return {"options": [], "hint": NEXT_HINT, "unknown": f"{col['file']} 을 읽지 못해 다음 갈래를 정할 수 없습니다: {e}"}
    if not rows:
        return {"options": [], "hint": NEXT_HINT, "unknown": f"{col['file']} 에서 '{col['column']}' 값이 든 요구사항을 찾지 못했습니다."}
    options = []
    for value, branch in col["branches"].items():
        skip = set(branch.get("skipStatuses") or [])  # 갈래마다 근거가 있는 상태만 뺀다(없으면 아무것도 빼지 않는다)
        ids = [i for i, v, st in rows if v == value and st not in skip]
        if ids:
            options.append(dict(_option(data, branch), value=value, count=len(ids), ids=ids))
    known = set(col["branches"])
    other = [i for i, v, _st in rows if v not in known]
    if other:
        options.append({"flow": None, "name": "", "label": "정해진 값이 아닌 다음 단계(SRS 를 고쳐야 합니다)", "disabled": True,
                        "value": "", "count": len(other), "ids": other})
    return {"options": options, "hint": NEXT_HINT}
