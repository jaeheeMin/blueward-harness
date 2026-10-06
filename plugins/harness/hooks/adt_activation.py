"""080 에 쓴 ABAP 오브젝트의 활성화 성공 확인 — 기록과 관문의 공용 로직(#190).

`mcp_activation_tracker.py`(PostToolUse)가 ADT MCP 호출 결과를 기록 파일에 남기고,
`activation_gate.py`(와 `pre_write_guard.py`, `pre-bash-git-guard.sh`)가 그 기록을 읽어
활성화되지 않은 오브젝트가 있으면 푸시·`src/` 쓰기를 막는다. 경로·키 계산·읽기·쓰기를
이 모듈 한 곳에 둔다. stdlib 만 쓴다(훅은 `uv run --no-project` 로 돈다).

**기록 파일.** `$(git rev-parse --absolute-git-dir)/harness-adt-activation.json`. worktree 마다
따로이고 세션을 넘어 남는다 — 이전 세션에서 쓰고 활성화하지 않은 것도 막아야 하기 때문이다.

    {"version": 1, "entries": {"<서버>|<TYPE:NAME>": {server, type, name, status, tool,
                                                      at, messages, session_id}}}

status: `written`(썼고 활성화 확인 전) / `active` / `failed`(활성화가 실패로 돌아옴) /
`unknown`(활성화 응답을 해석하지 못해 확인 불능). `active` 가 아니면 모두 관문에 걸린다
— 확인하지 못한 것을 통과로 뭉개지 않는다(CLAUDE.md 원칙 7).

**오브젝트 키.** `TYPE:NAME`(대문자). 같은 이름의 DDLS 와 BDEF 가 따로 추적되도록
TYPE 을 넣는다. URL 은 `adt_object_types.json` 표로 TYPE 을 찾고, 표에 없으면
`URL:<루트 URL>` 이다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

RECORD_NAME = "harness-adt-activation.json"
ERROR_NAME = "harness-adt-activation.error"  # 기록에 실패했다는 표식(내용: 시각·도구·사유)
LOCK_STALE_SECONDS = 30
LOCK_WAIT_SECONDS = 10
_TYPES_PATH = Path(__file__).with_name("adt_object_types.json")
_ADT_PREFIX = ["sap", "bc", "adt"]
_STOP_SEGMENTS = ("source", "includes")

ACTIVE = "active"
PENDING_STATUSES = ("written", "failed", "unknown")

NEXT_FIX = (
    "다음: 위 오브젝트의 오류 메시지를 읽고 소스를 고친 뒤 activateObjects 또는 activateByName 으로 "
    "다시 활성화하십시오. 다른 도구(Eclipse 등)로 이미 활성화했다면 inactiveObjects 를 호출해 "
    "기록을 맞추십시오. 오브젝트를 버릴 거면 deleteObject 로 지우십시오. ADT 호출이 401·세션 만료로 "
    "실패하면 그 서버에 다시 로그인(env/adt-tiers.yaml 의 login_skill)한 뒤 진행하십시오."
)


class ActivationError(Exception):
    """기록 파일이나 git 정보를 읽지 못했다(검사 불능)."""


# --- 경로 ----------------------------------------------------------------------

def git_dir(cwd: str | os.PathLike) -> Path | None:
    """cwd 가 속한 worktree 의 git 디렉터리. git 저장소가 아니면 None."""
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"], cwd=str(cwd),
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        return None
    return Path(out)


def record_path(cwd: str | os.PathLike) -> Path | None:
    gd = git_dir(cwd)
    return None if gd is None else gd / RECORD_NAME


# --- 기록 읽기·쓰기 ------------------------------------------------------------

def load(path: Path) -> dict:
    """기록을 읽는다. 파일이 없으면 빈 기록, 깨졌으면 ActivationError."""
    if not path.exists():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ActivationError(f"{path} 를 읽지 못했다: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        raise ActivationError(f"{path} 의 모양이 예상과 다르다")
    for key, entry in data["entries"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("status"), str):
            raise ActivationError(f"{path} 의 항목 {key} 모양이 예상과 다르다")
    return data


def save(path: Path, data: dict) -> None:
    """임시 파일에 쓰고 바꿔치기해 기록이 반쯤 쓰인 채 남지 않게 한다."""
    fd, tmp = tempfile.mkstemp(prefix=RECORD_NAME + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        # Windows 에서 다른 프로세스가 읽는 중이면 PermissionError 가 날 수 있어 다시 시도한다.
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def error_path(cwd: str | os.PathLike) -> Path | None:
    gd = git_dir(cwd)
    return None if gd is None else gd / ERROR_NAME


def mark_error(cwd: str | os.PathLike, tool: str, reason: str) -> Path | None:
    """기록에 실패했다는 표식을 남긴다(관문이 이 표식이 있으면 검사 불능으로 막는다)."""
    path = error_path(cwd)
    if path is None:
        return None
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(f"{_now()}\t{tool}\t{reason}\n")
    except OSError:
        return None
    return path


def update(path: Path, mutate) -> dict:
    """잠금을 잡고 읽기-수정-쓰기를 한다. `mutate(data)` 가 data 를 제자리에서 고친다.

    `<기록>.lock` 을 `O_CREAT|O_EXCL` 로 만들어 잠금으로 쓴다(stdlib, 크로스플랫폼). 짧게
    재시도하고, 30초 넘은 잠금은 죽은 프로세스가 남긴 것으로 보고 깨뜨린 뒤 진행한다. 잠금을
    못 잡으면 ActivationError.
    """
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise ActivationError(f"기록 잠금 {lock} 을 {LOCK_WAIT_SECONDS}초 안에 잡지 못했다")
            time.sleep(0.05)
        except OSError as exc:
            raise ActivationError(f"기록 잠금 {lock} 을 만들지 못했다: {exc}") from exc
    try:
        data = load(path)
        mutate(data)
        save(path, data)
        return data
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


# --- 오브젝트 키 ---------------------------------------------------------------
#
# 대상(target) 은 {type, name, key, root} 이다. key 는 `TYPE:NAME`, root 는 정규화한 루트 URL
# (URL 이 없으면 None). 두 대상은 key 가 같거나, 둘 다 root 가 있고 root 가 같으면 같은
# 오브젝트다 — 표에 없는 URL 로 기록된 항목(type URL)도 root 로 맞는다.

def _collections() -> list[tuple[list[str], str]]:
    table = json.loads(_TYPES_PATH.read_text(encoding="utf-8"))["collections"]
    items = [(coll.split("/"), typ) for coll, typ in table.items()]
    return sorted(items, key=lambda it: -len(it[0]))


def key_from_url(url: str) -> dict | None:
    """URL -> 대상. 표에 없으면 type 은 'URL', name 은 루트 URL. ADT URL 이 아니면 None.

    `#type=...` 같은 조각과 `/source/`·`/includes/` 이하는 무시하므로 메서드 하위 URL 도
    부모 오브젝트의 루트로 모인다.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    path = urlsplit(url.strip()).path.lower()
    segs = [s for s in path.split("/") if s]
    n = len(_ADT_PREFIX)
    if segs[:n] != _ADT_PREFIX:
        return None
    rest = segs[n:]
    for coll, typ in _collections():
        if rest[: len(coll)] == coll and len(rest) > len(coll):
            name = unquote(rest[len(coll)]).upper()
            if name:
                root = "/" + "/".join(segs[: n + len(coll) + 1])
                return {"type": typ, "name": name, "key": f"{typ}:{name}", "root": root}
    root_segs = []
    for seg in segs:
        if seg in _STOP_SEGMENTS:
            break
        root_segs.append(seg)
    root = "/" + "/".join(root_segs)
    return {"type": "URL", "name": root, "key": f"URL:{root}", "root": root}


def key_from_type_name(obj_type: str, name: str) -> dict | None:
    if not isinstance(obj_type, str) or not isinstance(name, str):
        return None
    typ = obj_type.split("/")[0].strip().upper()[:4]
    nm = name.strip().upper()
    if not typ or not nm:
        return None
    return {"type": typ, "name": nm, "key": f"{typ}:{nm}", "root": None}


def target_from_object(uri, obj_type, name) -> dict | None:
    """uri 를 먼저 본다 — 메서드 하위 항목(`CLAS/OM/public`, 이름에 공백·`~`)도 uri 루트로 부모가 된다.
    uri 로 TYPE 을 못 찾으면(표에 없음) 이름과 TYPE 으로 맞춰 본다."""
    by_url = key_from_url(uri)
    if by_url is not None and by_url["type"] != "URL":
        return by_url
    by_name = key_from_type_name(obj_type, name)
    if by_name is not None and by_url is not None:
        by_name["root"] = by_url["root"]  # 이름으로도 루트 URL 로도 맞게 둘 다 담는다
    return by_name or by_url


def _json_value(value):
    """문자열로 온 JSON 을 풀어 준다(이미 객체면 그대로)."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def targets_for(tool: str, tool_input: dict) -> list[dict]:
    """도구 입력에서 대상 오브젝트들을 뽑는다. 못 뽑으면 빈 목록."""
    out: list[dict | None] = []
    if tool == "setObjectSource":
        out.append(key_from_url(tool_input.get("objectSourceUrl", "")))
    elif tool in ("deleteObject", "activateByName"):
        # activateByName 도 URL 로만 맞춘다(objectUrl 은 필수). 이름만으로 맞추면 같은 이름의
        # CDS 와 BDEF 가 함께 active 가 된다.
        out.append(key_from_url(tool_input.get("objectUrl", "")))
    elif tool == "createObject":
        objtype = tool_input.get("objtype", "")
        name = tool_input.get("name", "")
        if isinstance(objtype, str) and objtype.upper().startswith("FUGR") and tool_input.get("parentName"):
            name = tool_input["parentName"]  # 펑션 모듈·인클루드는 펑션 그룹으로 추적한다
        out.append(key_from_type_name(objtype, name))
    elif tool == "activateObjects":
        items = _json_value(tool_input.get("objects"))
        if isinstance(items, dict):
            items = [items]
        for item in items if isinstance(items, list) else []:
            item = _json_value(item)
            if isinstance(item, dict):
                out.append(target_from_object(
                    item.get("adtcore:uri", ""), item.get("adtcore:type", ""), item.get("adtcore:name", "")))
    return [t for t in out if t]


def _objects_in_inactive(parsed) -> list[dict]:
    """InactiveObjectRecord 배열(또는 {inactive: [...]})에서 오브젝트 대상들을 뽑는다."""
    if isinstance(parsed, dict):
        parsed = parsed.get("inactive")
    out = []
    for rec in parsed if isinstance(parsed, list) else []:
        obj = rec.get("object") if isinstance(rec, dict) else None
        if not isinstance(obj, dict):
            continue
        t = target_from_object(obj.get("adtcore:uri", ""), obj.get("adtcore:type", ""), obj.get("adtcore:name", ""))
        if t:
            out.append(t)
    return out


# --- 응답 해석 -----------------------------------------------------------------

def response_text(resp) -> str:
    """tool_response 가 문자열·블록 배열·{"content": [...]} 어느 모양이든 텍스트를 이어 붙인다."""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "".join(response_text(r) for r in resp)
    if isinstance(resp, dict):
        if "content" in resp:
            return response_text(resp["content"])
        if isinstance(resp.get("text"), str):
            return resp["text"]
        return json.dumps(resp, ensure_ascii=False)
    return str(resp)


def _parse_json(text: str):
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _message_line(m: dict):
    """실제 줄은 href 의 `#start=<줄>,<열>` 에 있다(`line` 은 1 로 오는 일이 있다). 없으면 line."""
    href = m.get("href")
    if isinstance(href, str):
        found = re.search(r"#start=(\d+)", href)
        if found:
            return found.group(1)
    line = m.get("line")
    return None if line in (None, "", 0, "0") else line


def _short_messages(parsed: dict, limit: int = 3) -> list[str]:
    msgs = parsed.get("messages")
    if not isinstance(msgs, list):
        return []
    items = [m for m in msgs if isinstance(m, dict) and isinstance(m.get("shortText"), str)]
    errors = [m for m in items if str(m.get("type", "")).upper() in ("E", "A", "X")]
    out = []
    for m in (errors or items)[:limit]:
        text = m["shortText"].strip()
        line = _message_line(m)
        out.append(f"{text} (줄 {line})" if line is not None else text)
    return out


# --- 기록 갱신 -----------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _same(entry: dict, server: str, t: dict) -> bool:
    if entry.get("server") != server:
        return False
    key = entry.get("key") or f"{entry.get('type')}:{entry.get('name')}"
    if key == t["key"]:
        return True
    return bool(entry.get("root") and t.get("root") and entry["root"] == t["root"])


def _find(entries: dict, server: str, t: dict) -> list[str]:
    return [k for k, e in entries.items() if _same(e, server, t)]


def _set(entry: dict, status: str, tool: str, session_id: str, messages: list[str]) -> None:
    entry.update(status=status, tool=tool, at=_now(), messages=messages, session_id=session_id)


def apply_event(data: dict, server: str, tool: str, tool_input: dict, tool_response,
                session_id: str = "") -> None:
    """PostToolUse 한 건을 기록에 반영한다(data 를 제자리에서 고친다)."""
    entries = data["entries"]
    targets = targets_for(tool, tool_input if isinstance(tool_input, dict) else {})

    if tool in ("setObjectSource", "createObject"):
        if isinstance(tool_response, dict) and tool_response.get("isError"):
            return
        for t in targets:
            found = _find(entries, server, t)
            if found:
                e = entries[found[0]]
                if t.get("root"):
                    e["root"] = t["root"]
            else:
                e = entries.setdefault(f"{server}|{t['key']}", {
                    "server": server, "type": t["type"], "name": t["name"], "key": t["key"], "root": t["root"]})
            _set(e, "written", tool, session_id, [])
        return

    if tool == "deleteObject":
        for t in targets:
            for k in _find(entries, server, t):
                del entries[k]
        return

    if tool in ("activateObjects", "activateByName"):
        parsed = _parse_json(response_text(tool_response))
        hit_keys: list[str] = []
        for t in targets:
            hit_keys += [k for k in _find(entries, server, t) if k not in hit_keys]
        if not isinstance(parsed, dict) or not isinstance(parsed.get("success"), bool):
            for k in hit_keys:
                _set(entries[k], "unknown", tool, session_id, ["활성화 응답을 해석하지 못했다"])
            return
        if parsed["success"]:
            for k in hit_keys:
                _set(entries[k], ACTIVE, tool, session_id, [])
            return
        msgs = _short_messages(parsed)
        failed = list(hit_keys)
        for t in _objects_in_inactive(parsed):
            failed += [k for k in _find(entries, server, t) if k not in failed]
        for k in failed:
            _set(entries[k], "failed", tool, session_id, msgs)
        return

    if tool == "inactiveObjects":
        parsed = _parse_json(response_text(tool_response))
        if not isinstance(parsed, (list, dict)):
            return
        if isinstance(parsed, dict) and not isinstance(parsed.get("inactive"), list):
            return
        # 기록 밖의 항목(다른 사용자의 비활성 오브젝트)은 아래에서 아예 보지 않는다.
        still = _objects_in_inactive(parsed)
        for e in entries.values():
            if e.get("server") != server or e.get("status") == ACTIVE:
                continue
            if any(_same(e, server, t) for t in still):
                continue
            _set(e, ACTIVE, tool, session_id, [])


# --- 관문 ----------------------------------------------------------------------

def pending_entries(data: dict) -> list[dict]:
    return [e for e in data["entries"].values() if e.get("status") != ACTIVE]


def describe(entries: list[dict]) -> str:
    lines = []
    for e in entries:
        lines.append(f"  - [{e.get('server')}] {e.get('type')}:{e.get('name')} — {e.get('status')}")
        for m in e.get("messages") or []:
            lines.append(f"      {m}")
    return "\n".join(lines)


def gate(cwd: str | os.PathLike) -> tuple[bool, str]:
    """(통과 여부, 거절 메시지). 검사 불능은 통과가 아니라 (False, 검사 불능 메시지)."""
    gd = git_dir(cwd)
    if gd is None:
        return True, ""
    marker, path = gd / ERROR_NAME, gd / RECORD_NAME
    if marker.exists():
        try:
            detail = marker.read_text(encoding="utf-8").strip()[-600:]
        except (OSError, UnicodeDecodeError):
            detail = "(표식 내용을 읽지 못함)"
        return False, (
            "활성화 기록을 남기지 못한 적이 있어 ABAP 오브젝트의 활성화 성공을 확인할 수 없습니다(검사 불능).\n"
            f"표식: {marker}\n{detail}\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: inactiveObjects 로 서버의 비활성 오브젝트를 확인해 남은 것이 없음을 본 뒤, 사람이 "
            f"표식 파일 {marker} 를 지우십시오. 남은 것이 있으면 activateObjects 또는 activateByName 으로 "
            "활성화한 뒤 다시 확인하십시오."
        )
    if not path.exists():
        return True, ""
    try:
        data = load(path)
    except ActivationError as exc:
        return False, (
            "활성화 기록을 읽지 못해 ABAP 오브젝트의 활성화 성공을 확인할 수 없습니다(검사 불능).\n"
            f"사유: {exc}\n확인되지 않는 상태로 통과시키지 않습니다.\n\n"
            "다음: 사람이 할 일 — 기록 파일을 확인하십시오. 오브젝트가 모두 활성화된 것이 확실하면 "
            "파일을 지우고 inactiveObjects 로 다시 확인한 뒤 같은 작업을 시도하십시오."
        )
    pend = pending_entries(data)
    if not pend:
        return True, ""
    return False, (
        "활성화가 확인되지 않은 ABAP 오브젝트가 있어 막습니다.\n\n"
        + describe(pend) + "\n\n" + NEXT_FIX
    )
