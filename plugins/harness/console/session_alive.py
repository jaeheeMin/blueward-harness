"""터미널 세션의 claude 프로세스가 아직 살아 있는지 본다(#867, web-console.md §9).

같은 세션을 두 프로세스가 동시에 --resume 하면 오류 없이 대화가 두 갈래로 조용히 갈라진다(실측: docs/status/867-console-resume-terminal.md).
그래서 콘솔이 터미널 세션을 이어받기 전에 그 터미널의 claude 가 끝났는지 확인한다.

근거는 claude 가 남기는 `<설정 폴더>/sessions/<pid>.json`(pid·sessionId·procStart) 하나다. 시작하면 생기고, 정상 종료하면 지워지고,
강제로 끄면 파일만 남는다(그래서 pid 가 실제로 살아 있는지도 본다). 설정 폴더는 훅이 알려 준 transcript_path(<설정 폴더>/projects/…)에서 찾는다.

결과는 셋이다. 어느 쪽도 아닌 것을 통과나 위반으로 뭉개지 않는다.
- alive: 그 세션을 쥔 claude 프로세스가 살아 있다.
- ended: 설정 폴더의 sessions 를 읽었고 그 세션을 쥔 살아 있는 프로세스가 없다.
- unknown: sessions 폴더가 없거나(옛 claude) 읽을 수 없는 파일이 있어 판단하지 못했다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, Mapping

ALIVE, ENDED, UNKNOWN = "alive", "ended", "unknown"
PROC_START_TOLERANCE = 10_000_000  # procStart 는 Windows FILETIME(100ns). 1초 안이면 같은 프로세스로 본다
ERROR_ACCESS_DENIED = 5


def config_dir(transcript_path: str = "", env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """transcript_path 가 <설정 폴더>/projects/… 모양이면 그 설정 폴더. 아니면 CLAUDE_CONFIG_DIR 또는 ~/.claude."""
    if transcript_path:
        p = Path(transcript_path)
        for parent in p.parents:
            if parent.name == "projects":
                return parent.parent
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return Path(base) if base else (home or Path.home()) / ".claude"


def process_alive(pid: int, proc_start: int | None = None, os_name: str | None = None) -> bool:
    """pid 가 살아 있는지. procStart 를 알고 Windows 에서 만든 시각을 읽을 수 있으면 같은 프로세스인지도 본다(pid 재사용 방지).
    확인할 수 없으면 살아 있는 쪽으로 답한다(틀리면 안전한 쪽: 갈라서 이어 가기를 권한다)."""
    if (os_name or ("windows" if sys.platform.startswith("win") else "posix")) == "windows":
        return _windows_alive(pid, proc_start)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _windows_alive(pid: int, proc_start: int | None) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # 접근 거부면 있는 프로세스, 그 밖(없는 pid)이면 없다
    try:
        created, exited, kernel_t, user_t = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_t), ctypes.byref(user_t)):
            return True
        code = wintypes.DWORD()
        if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != 259:  # STILL_ACTIVE
            return False
        if proc_start is None:
            return True
        made = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return abs(made - proc_start) <= PROC_START_TOLERANCE
    finally:
        kernel.CloseHandle(handle)


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def check(session_id: str, transcript_path: str = "", env: Mapping[str, str] | None = None, home: Path | None = None,
          alive: Callable[[int, int | None], bool] = process_alive) -> tuple[str, str]:
    """(상태, 쉬운 설명). 상태는 ALIVE·ENDED·UNKNOWN."""
    folder = config_dir(transcript_path, env, home) / "sessions"
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        files = []
    if not folder.is_dir():
        return UNKNOWN, "이 컴퓨터의 Claude Code 가 세션 목록(sessions 폴더)을 남기지 않아서 터미널이 열려 있는지 확인하지 못했어."
    unreadable = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable += 1
            continue
        if not isinstance(data, dict) or data.get("sessionId") != session_id:
            continue
        pid = _int(data.get("pid"))
        if pid is not None and alive(pid, _int(data.get("procStart"))):
            return ALIVE, "이 세션을 쥔 터미널(claude)이 아직 열려 있어."
    if unreadable:
        return UNKNOWN, f"세션 목록 파일 {unreadable}개를 읽지 못해서 터미널이 닫혔는지 확인하지 못했어."
    return ENDED, "이 세션을 쥔 터미널(claude)이 없어. 닫힌 것으로 확인했어."
