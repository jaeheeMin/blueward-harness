"""설정 "한도 표시" 켜기·끄기(#1039). 사용자 settings.json 의 statusLine 을 하네스 감싸개(statusline_wrap.py)로 바꾸고 되돌린다.

- 어느 settings.json 인가: CLAUDE_CONFIG_DIR 이 있으면 그 아래, 없으면 ~/.claude(콘솔 서버가 보는 환경 기준).
- 켜기는 원래 statusLine 값(객체 통째, 없으면 없음)을 상태 폴더 statusline_orig.json 에 기억하고, command 만 감싸개로 바꾼다.
  원래 객체의 다른 키(padding·refreshInterval 등)는 그대로 둔다. 이미 감싸개면 아무것도 바꾸지 않는다(멱등).
- 끄기는 기억한 값으로 되돌린다(없었으면 키를 지운다). 사이에 사용자가 statusLine 을 직접 바꿨으면 건드리지 않는다.
- settings.json 은 키 순서·값을 그대로 두고 들여쓰기·줄바꿈 모양을 따라 쓴다. 읽을 수 없거나 JSON 이 아니면 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

WRAP_NAME = "statusline_wrap.py"
ORIG_FILE = "statusline_orig.json"
LIMITS_FILE = "statusline_limits.json"
LAUNCHER = "uv run --no-project python"  # 하네스 훅과 같은 실행 방식(hooks.json)
UNSAFE = '"$`'  # 큰따옴표 안에서 Git Bash·PowerShell 이 다르게 읽는 글자. 상태 폴더 경로에 있으면 켜지 않는다


class LimitsError(Exception):
    """사람에게 그대로 보여 줄 수 있는 실패 이유."""


def settings_path(env=None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else (home or Path.home()) / ".claude") / "settings.json"


def wrapper_command(state: Path) -> str:
    p = (state / WRAP_NAME).as_posix()  # Git Bash 는 따옴표 밖 역슬래시를 먹으니 슬래시로 쓴다(공식 문서 Windows configuration)
    bad = [c for c in UNSAFE if c in p]
    if bad:
        raise LimitsError("상태 폴더 경로에 " + " ".join(bad) + " 가 있어서 상태줄 명령에 안전하게 쓸 수 없어: " + p)
    return f'{LAUNCHER} "{p}"'


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_settings(path: Path) -> tuple[dict, dict]:
    """(내용, 쓸 때 따를 모양). 파일이 없으면 빈 내용."""
    fmt = {"bom": False, "nl": "\n", "indent": "  ", "tail": True}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {}, fmt
    except OSError as e:
        raise LimitsError(f"{path} 를 읽지 못했어: {e}")
    fmt["bom"] = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw[3:].decode("utf-8") if fmt["bom"] else raw.decode("utf-8")
    except UnicodeDecodeError:
        raise LimitsError(f"{path} 가 UTF-8 이 아니어서 건드리지 않았어.")
    if not text.strip():
        return {}, fmt
    try:
        data = json.loads(text)
    except ValueError as e:
        raise LimitsError(f"{path} 가 올바른 JSON 이 아니어서 건드리지 않았어({e}).")
    if not isinstance(data, dict):
        raise LimitsError(f"{path} 의 맨 위가 객체가 아니어서 건드리지 않았어.")
    fmt["nl"] = "\r\n" if "\r\n" in text else "\n"
    m = re.search(r"\n([ \t]+)\S", text)
    if m:
        fmt["indent"] = m.group(1)
    fmt["tail"] = text.endswith("\n")
    return data, fmt


def _settings_bytes(data: dict, fmt: dict) -> bytes:
    text = json.dumps(data, ensure_ascii=False, indent=fmt["indent"])
    if fmt["tail"]:
        text += "\n"
    if fmt["nl"] == "\r\n":
        text = text.replace("\n", "\r\n")
    return (b"\xef\xbb\xbf" if fmt["bom"] else b"") + text.encode("utf-8")


def _write_bytes(path: Path, raw: bytes) -> None:
    try:
        _atomic_write(path, raw)
    except OSError as e:
        raise LimitsError(f"{path} 를 쓰지 못했어: {e}")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(state: Path) -> dict | None:
    try:
        rec = json.loads((state / ORIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and "present" in rec else None


def _command_of(cur) -> str:
    return cur.get("command") if isinstance(cur, dict) and isinstance(cur.get("command"), str) else ""


def received_at(state: Path) -> float | None:
    try:
        t = json.loads((state / LIMITS_FILE).read_text(encoding="utf-8")).get("t")
    except (OSError, ValueError, AttributeError):
        return None
    return t if isinstance(t, (int, float)) and not isinstance(t, bool) else None


def status(state: Path, env=None, home: Path | None = None) -> dict:
    """화면에 보일 현재 상태와, 켜면 무엇이 바뀌는지."""
    sp = settings_path(env, home)
    out = {"settingsPath": str(sp), "enabled": False, "canEnable": True, "problem": "", "current": None, "currentCommand": "",
           "newCommand": "", "originalKept": False, "receivedAt": received_at(state)}
    try:
        out["newCommand"] = cmd = wrapper_command(state)
        data, _ = _read_settings(sp)
    except LimitsError as e:
        out.update(canEnable=False, problem=str(e))
        return out
    cur = data.get("statusLine")
    out["current"], out["currentCommand"] = cur, _command_of(cur)
    out["enabled"] = out["currentCommand"] == cmd
    rec = _record(state)
    out["originalKept"] = rec is not None
    if out["enabled"] and rec is None:
        out.update(canEnable=False, problem="이미 감싸개로 바뀌어 있는데 원래 값을 기억한 파일이 없어서 끄기로 되돌릴 수 없어. settings.json 의 statusLine 을 직접 고쳐 줘.")
    elif cur is not None and not out["enabled"] and not (isinstance(cur, dict) and out["currentCommand"].strip()):
        out.update(canEnable=False, problem="지금 statusLine 이 command 형식이 아니라서 감싸지 않았어.")
    return out


def enable(state: Path, console_dir: Path, env=None, home: Path | None = None) -> dict:
    sp = settings_path(env, home)
    cmd = wrapper_command(state)
    data, fmt = _read_settings(sp)
    cur = data.get("statusLine")
    if _command_of(cur) == cmd:  # 멱등: 이미 켜져 있으면 감싸개 파일만 새 판으로 맞춘다
        refresh_script(state, console_dir)
        return status(state, env, home)
    if cur is not None and not (isinstance(cur, dict) and _command_of(cur).strip()):
        raise LimitsError("지금 statusLine 이 command 형식이 아니라서 감싸지 않았어.")
    state.mkdir(parents=True, exist_ok=True)
    data["statusLine"] = dict(cur, command=cmd) if cur is not None else {"type": "command", "command": cmd}
    new_raw = _settings_bytes(data, fmt)
    try:
        before = sp.read_bytes() if sp.exists() else None
    except OSError as e:
        raise LimitsError(f"{sp} 를 읽지 못했어: {e}")
    try:
        shutil.copyfile(console_dir / WRAP_NAME, state / (WRAP_NAME + ".tmp"))
        os.replace(state / (WRAP_NAME + ".tmp"), state / WRAP_NAME)
        # before/afterSha: 끌 때 파일이 우리가 쓴 그대로면 켜기 전 바이트를 그대로 되돌린다(들여쓰기·줄 모양까지)
        _atomic_write(state / ORIG_FILE, json.dumps({
            "version": 1, "settingsPath": str(sp), "present": cur is not None, "value": cur, "command": cmd, "enabledAt": time.time(),
            "before": None if before is None else base64.b64encode(before).decode("ascii"), "afterSha": _sha(new_raw)}, ensure_ascii=False).encode("utf-8"))
    except OSError as e:
        raise LimitsError(f"감싸개를 상태 폴더에 두지 못했어: {e}")
    try:
        _write_bytes(sp, new_raw)
    except LimitsError:
        try:
            (state / ORIG_FILE).unlink()
        except OSError:
            pass
        raise
    return status(state, env, home)


def disable(state: Path, env=None, home: Path | None = None) -> dict:
    sp = settings_path(env, home)
    cmd = wrapper_command(state)
    rec = _record(state)
    data, fmt = _read_settings(sp)
    cur = data.get("statusLine")
    if _command_of(cur) != cmd:  # 감싸개가 아니다: 사용자가 직접 바꿨거나 이미 꺼져 있다. 남의 값을 덮어쓰지 않는다
        try:
            (state / ORIG_FILE).unlink()
        except OSError:
            pass
        return dict(status(state, env, home), note="statusLine 이 이미 감싸개가 아니라서 settings.json 은 건드리지 않았어.")
    if rec is None:
        raise LimitsError("원래 statusLine 값을 기억한 파일이 없어서 되돌릴 수 없어. settings.json 의 statusLine 을 직접 고쳐 줘.")
    try:
        ours = sp.read_bytes()
    except OSError as e:
        raise LimitsError(f"{sp} 를 읽지 못했어: {e}")
    if rec.get("afterSha") == _sha(ours) and isinstance(rec.get("before"), str):  # 켠 뒤 아무도 안 고쳤다: 켜기 전 바이트 그대로
        _write_bytes(sp, base64.b64decode(rec["before"]))
    elif rec.get("afterSha") == _sha(ours) and rec.get("before") is None:  # 설정 파일 자체가 없었다
        try:
            sp.unlink()
        except OSError as e:
            raise LimitsError(f"{sp} 를 지우지 못했어: {e}")
    else:  # 그 사이 다른 설정이 바뀌었다: statusLine 만 되돌리고 나머지는 지금 값 그대로
        if rec["present"]:
            data["statusLine"] = rec.get("value")
        else:
            data.pop("statusLine", None)
        _write_bytes(sp, _settings_bytes(data, fmt))
    try:
        (state / ORIG_FILE).unlink()
    except OSError:
        pass
    return status(state, env, home)


def refresh_script(state: Path, console_dir: Path) -> None:
    """켜져 있을 때 상태 폴더의 감싸개 복사본을 지금 플러그인 판으로 맞춘다. 실패해도 이전 복사본이 그대로 돈다."""
    src, dst = console_dir / WRAP_NAME, state / WRAP_NAME
    try:
        if dst.exists() and dst.read_bytes() != src.read_bytes():  # 켠 적 없으면(복사본 없음) 만들지 않는다
            shutil.copyfile(src, state / (WRAP_NAME + ".tmp"))
            os.replace(state / (WRAP_NAME + ".tmp"), dst)
    except OSError:
        pass
