"""OS 차이를 한 곳에 모은다(web-console.md §1).

분기가 있는 함수는 `os_name` 을 인자로 받는다. 시험이 Windows 값을 넣어 분기 로직만 확인할 수 있게 하려는 것이다.
이 파일의 Windows 분기는 Windows 에서 실행해 보지 않았다.
"""
from __future__ import annotations

import ntpath
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_PORT = 4873


def current_os() -> str:
    return "windows" if sys.platform.startswith("win") else "posix"


def port_from_env(env: Mapping[str, str] | None = None) -> int:
    """기본은 4873. 시험이 임시 포트를 쓰도록 HARNESS_CONSOLE_PORT 로 바꿀 수 있다."""
    raw = (env if env is not None else os.environ).get("HARNESS_CONSOLE_PORT", "")
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 0 < port < 65536 else DEFAULT_PORT


def state_dir(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """CLAUDE_PLUGIN_DATA -> <CLAUDE_CONFIG_DIR 또는 ~/.claude>/harness-console."""
    env = os.environ if env is None else env
    data = env.get("CLAUDE_PLUGIN_DATA")
    if data:
        return Path(data)
    base = env.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else (home or Path.home()) / ".claude"
    return root / "harness-console"


def detach_kwargs(os_name: str | None = None) -> dict:
    """띄운 서버가 부모(Claude 세션의 Bash)가 끝나도 살아 있게 하는 Popen 인자."""
    if (os_name or current_os()) == "windows":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        return {"creationflags": flags}
    return {"start_new_session": True}


def hidden_window_kwargs(os_name: str | None = None) -> dict:
    """Windows 에서 자식 프로세스의 콘솔 창이 뜨지 않게 한다. POSIX 는 필요 없다."""
    if (os_name or current_os()) == "windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


CLAUDE_MISSING = ("claude 실행 파일을 찾을 수 없습니다. Claude Code 를 설치했는지 확인하고, 새 터미널에서 `claude --version` 이 "
                  "되는지 보십시오. npm 으로 설치했다면 `claude.exe` 가 있는 공식 설치본으로 다시 설치하는 것을 권합니다.")


def _windows_cmd_target(path: str, which, exists) -> list[str] | None:
    """npm 이 만든 claude.cmd 옆의 node_modules 에서 .cmd 없이 직접 실행할 대상을 찾는다.
    네이티브 exe -> node + cli.js 순서. cmd /c 는 공백·한글 경로와 JSON 인자에서 깨지므로 쓰지 않는다."""
    base = ntpath.join(ntpath.dirname(path), "node_modules", "@anthropic-ai", "claude-code")
    for rel in (("bin", "claude.exe"), ("claude.exe",)):
        exe = ntpath.join(base, *rel)
        if exists(exe):
            return [exe]
    cli = ntpath.join(base, "cli.js")
    if exists(cli):
        node = which("node") or ntpath.join(ntpath.dirname(path), "node.exe")
        if which("node") or exists(node):
            return [node, cli]
    return None


def find_claude(os_name: str | None = None, which: Callable[[str], str | None] = shutil.which,
                exists: Callable[[str], bool] = os.path.exists) -> list[str] | None:
    """claude 실행 명령의 앞부분. 못 찾으면 None(호출한 쪽이 CLAUDE_MISSING 을 보여 준다).
    Windows 는 claude.exe 를 먼저 찾고, .cmd/.bat 이면 옆 node_modules 의 exe 또는 cli.js 를 직접 실행한다.
    cmd /c 로 감싸지 않는다. 뒤에 붙는 인자는 이 모듈이 정한 고정 값뿐이고 사용자 입력은 stdin 으로만 넘긴다."""
    if (os_name or current_os()) != "windows":
        path = which("claude")
        return [path] if path else None
    exe = which("claude.exe")
    if exe:
        return [exe]
    path = which("claude")
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat", ".ps1")):
        return _windows_cmd_target(path, which, exists)
    return [path]


def terminate(proc, os_name: str | None = None, runner=subprocess.run) -> None:
    """프로세스를 끝내 달라고 요청한다. POSIX 는 SIGTERM, Windows 는 taskkill /T /F 로 자식까지 끈다."""
    try:
        if (os_name or current_os()) == "windows":
            pid = getattr(proc, "pid", None)
            if pid is None or not kill_tree(pid, "windows", runner):
                proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def kill_tree(pid: int, os_name: str | None = None, runner=subprocess.run) -> bool:
    """Windows: taskkill /PID <pid> /T /F (창 없이). 성공 여부."""
    try:
        done = runner(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=10,
                      **hidden_window_kwargs(os_name or "windows"))
        return getattr(done, "returncode", 1) == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def terminate_pid(pid: int, os_name: str | None = None, runner=subprocess.run) -> bool:
    if (os_name or current_os()) == "windows":
        return kill_tree(pid, "windows", runner)
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


def popen_detached_kwargs(os_name: str | None = None) -> dict:
    """서버를 띄우는 Popen 인자. 분리 플래그에 창 숨김을 하나의 creationflags 로 합친다(키워드 중복 방지)."""
    kw = detach_kwargs(os_name)
    if "creationflags" in kw:
        kw["creationflags"] |= hidden_window_kwargs(os_name).get("creationflags", 0)
    return kw


def open_in_browser(url: str, opener: Callable[[str], bool] = webbrowser.open) -> bool:
    """기본 브라우저로 연다. 서버 프로세스가 직접 호출한다. 열 수 없으면 False."""
    try:
        return bool(opener(url))
    except Exception:
        return False


def same_path(a: str | os.PathLike, b: str | os.PathLike, os_name: str | None = None) -> bool:
    if (os_name or current_os()) == "windows":  # 경로 구분자와 대소문자를 구별하지 않는다
        return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def clean_user_path(raw: str) -> str:
    """탐색기 '경로로 복사' 의 "C:\\Work\\proj" 처럼 앞뒤 공백과 따옴표가 붙은 입력을 정리한다."""
    return raw.strip().strip("\"'").strip()


def is_within(path: str | os.PathLike, root: str | os.PathLike, os_name: str | None = None) -> bool:
    """realpath 로 풀어서 path 가 root 안(같은 곳 포함)인지 본다. 심볼릭 링크 탈출을 막는다."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
    except (OSError, ValueError):
        return False
    if (os_name or current_os()) == "windows":
        p, r = os.path.normcase(p), os.path.normcase(r)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # Windows 에서 드라이브가 다르면
        return False


def socket_closed(sock: socket.socket) -> bool:
    """상대가 연결을 끊었는지 본다. 읽을 게 있으면 건드리지 않고 엿보기만 한다."""
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True
