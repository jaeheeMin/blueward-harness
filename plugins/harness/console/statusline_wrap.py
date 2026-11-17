"""상태줄 감싸개(#1039). Claude Code 의 statusLine 명령으로 들어가 두 가지를 한다.

1. 받은 입력(stdin JSON)의 rate_limits(five_hour·seven_day 의 used_percentage·resets_at)만 이 파일 옆 statusline_limits.json 에 남긴다.
   웹 콘솔이 헤더 한도에 쓴다. 기록이 실패해도 상태줄은 그대로 그려야 하니 stderr 한 줄만 남기고 넘어간다(stdout 에는 섞지 않는다).
2. 원래 상태줄 명령(statusline_orig.json 에 기억해 둔 settings.json 의 statusLine.command 문자열 그대로)을 실행해 입력을 그대로 넘기고
   그 stdout 을 바이트 그대로 내보낸다. 종료 코드도 그대로. 원래 상태줄이 없던 PC 는 아무것도 내보내지 않는다.

콘솔이 켜기 때 이 파일을 상태 폴더로 복사하므로 플러그인 판이 바뀌어도 설정의 경로는 그대로다. 표준 라이브러리만 쓴다.
입력·출력은 모두 바이트(sys.stdin.buffer·sys.stdout.buffer)로 다룬다 — Windows 텍스트 모드의 줄바꿈·인코딩 변환을 피한다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LIMITS_FILE = "statusline_limits.json"
ORIG_FILE = "statusline_orig.json"
WINDOWS = ("five_hour", "seven_day")


def log(msg: str) -> None:
    try:  # Windows 의 stderr 텍스트 인코딩(cp1252 등)이 한글을 \\u 이스케이프로 바꾸지 않게 UTF-8 바이트로 직접 쓴다
        line = ("harness-statusline: " + msg.replace("\n", " ").replace("\r", " ")[:300] + "\n").encode("utf-8", "replace")
        sys.stderr.buffer.write(line)
        sys.stderr.buffer.flush()
    except Exception:  # noqa: BLE001 - 로그를 못 남겨도 상태줄은 그려야 한다
        pass


def limits_of(data: bytes) -> dict | None:
    """입력 JSON 에서 rate_limits 의 두 창만 뽑는다. 없거나 모양이 다르면 None."""
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    rl = doc.get("rate_limits") if isinstance(doc, dict) else None
    if not isinstance(rl, dict):
        return None
    num = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None  # noqa: E731
    out = {}
    for k in WINDOWS:
        w = rl.get(k)
        if isinstance(w, dict) and (num(w.get("used_percentage")) is not None or num(w.get("resets_at")) is not None):
            out[k] = {"used_percentage": num(w.get("used_percentage")), "resets_at": num(w.get("resets_at"))}
    return out or None


def record(state: Path, data: bytes, now: float | None = None) -> None:
    lim = limits_of(data)
    if lim is None:
        return
    tmp = state / (LIMITS_FILE + "." + str(os.getpid()) + ".tmp")
    try:
        tmp.write_text(json.dumps({"t": time.time() if now is None else now, "rate_limits": lim}), encoding="utf-8")
        os.replace(tmp, state / LIMITS_FILE)
    except OSError as e:
        log("한도를 기록하지 못했어: " + str(e))
        try:
            tmp.unlink()
        except OSError:
            pass


def original_command(state: Path) -> str | None:
    """기억해 둔 원래 statusLine 의 command 문자열. 원래 상태줄이 없었거나 읽지 못하면 None."""
    try:
        rec = json.loads((state / ORIG_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log("원래 상태줄 기록을 읽지 못했어: " + str(e))
        return None
    val = rec.get("value") if isinstance(rec, dict) else None
    cmd = val.get("command") if isinstance(val, dict) else None
    return cmd if isinstance(cmd, str) and cmd.strip() else None


def git_bash(env=os.environ, which=shutil.which, exists=os.path.exists) -> str | None:
    """Windows 에서 Claude Code 가 상태줄 명령을 돌리는 Git Bash. WSL 의 System32\\bash.exe 는 쓰지 않는다."""
    cands = []
    if env.get("CLAUDE_CODE_GIT_BASH_PATH"):
        cands.append(env["CLAUDE_CODE_GIT_BASH_PATH"])
    git = which("git")
    if git:  # <루트>\cmd\git.exe 또는 <루트>\mingw64\bin\git.exe
        p = Path(git).resolve().parent
        cands += [str(p.parent / "bin" / "bash.exe"), str(p.parent.parent / "bin" / "bash.exe")]
    if env.get("MSYSTEM") and which("bash"):  # 이미 Git Bash 안에서 불린 것
        cands.append(which("bash"))
    for pf in (env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")):
        if pf:
            cands.append(str(Path(pf) / "Git" / "bin" / "bash.exe"))
    for c in cands:
        if c and exists(c):
            return c
    return None


def shell_argv(cmd: str, os_name: str | None = None, env=os.environ) -> list[str]:
    """원래 명령 문자열을 다시 따옴표 씌우지 않고 셸에 그대로 넘기는 인자.
    Windows: Git Bash 가 있으면 bash -c, 없으면 PowerShell(Claude Code 공식 문서 statusline "Windows configuration"). 그 밖: /bin/sh -c."""
    if (os_name or os.name) != "nt":
        return ["/bin/sh", "-c", cmd]
    bash = git_bash(env)
    if bash:
        return [bash, "-c", cmd]
    return [shutil.which("powershell") or "powershell.exe", "-NoProfile", "-Command", cmd]


def run_original(cmd: str, data: bytes) -> int:
    try:
        r = subprocess.run(shell_argv(cmd), input=data, stdout=subprocess.PIPE)
    except OSError as e:
        log("원래 상태줄 명령을 실행하지 못했어: " + str(e))
        return 1
    out = sys.stdout.buffer
    out.write(r.stdout)
    out.flush()
    return r.returncode


def main(state: Path | None = None) -> int:
    state = state or Path(__file__).resolve().parent
    data = sys.stdin.buffer.read()
    record(state, data)  # 출력보다 먼저: 새 갱신이 오면 Claude Code 가 돌던 명령을 취소하기 때문이다
    cmd = original_command(state)
    if cmd is None:
        return 0
    return run_original(cmd, data)


if __name__ == "__main__":
    sys.exit(main())
