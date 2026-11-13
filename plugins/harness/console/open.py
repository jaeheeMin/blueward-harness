"""`/harness:open` 이 실행한다. 서버가 꺼져 있으면 띄우고 브라우저를 열게 한다(web-console.md §3).

결과는 한 줄만 낸다. 인증 토큰은 서버가 브라우저에 직접 넘기므로 여기에는 나오지 않는다.
"""
from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):  # Windows 콘솔 기본 코드페이지(cp949 등)에서 한글이 깨지거나 예외가 나지 않게
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import platform_compat
import shortcut

APP_NAME = "harness-console"


def request(port: int, method: str, path: str, body: dict | None = None, timeout: float = 3.0):
    """(상태, JSON 또는 None). 연결하지 못하면 (None, None)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            return resp.status, json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            return resp.status, None
    except OSError:
        return None, None
    finally:
        conn.close()


def probe(port: int) -> str:
    """"ours" 우리 서버 / "free" 아무도 안 씀 / "other" 다른 프로그램이 이 포트를 씀."""
    status, data = request(port, "GET", "/api/health")
    if status is None:
        return "free"
    return "ours" if isinstance(data, dict) and data.get("app") == APP_NAME else "other"


def server_popen_args(port: int, os_name: str | None = None, breakaway: bool = True,
                      exists=os.path.exists) -> tuple[list[str], dict]:
    """서버를 띄우는 Popen 의 (명령, 키워드 인자). creationflags 는 하나로 합쳐 한 번만 넣는다.
    Windows 는 콘솔 창이 없는 pythonw.exe 로 띄운다(없으면 sys.executable + CREATE_NO_WINDOW)."""
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
    server = Path(__file__).resolve().parent / "server.py"
    python, windowless = sys.executable, True
    if (os_name or platform_compat.current_os()) == "windows":
        python, windowless = platform_compat.windows_server_python(exists)
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                  **platform_compat.popen_detached_kwargs(os_name, windowless, breakaway))
    return [python, str(server)], kwargs


def launch_server(port: int, os_name: str | None = None, popen=subprocess.Popen, exists=os.path.exists):
    """서버를 띄운다. 부모 Job 이 breakaway 를 막아 OSError 가 나면 그 플래그를 빼고 한 번 더 시도한다."""
    args, kwargs = server_popen_args(port, os_name, True, exists)
    if "creationflags" not in kwargs:
        return popen(args, **kwargs)
    try:
        return popen(args, **kwargs)
    except OSError:
        args, kwargs = server_popen_args(port, os_name, False, exists)
        return popen(args, **kwargs)


STOP_PORT_WAIT = 10.0   # --stop 이 포트가 풀리기를 기다리는 최대 시간(초)
START_PORT_WAIT = 3.0   # 시작할 때 포트가 사용 중이면 풀리기를 기다리는 시간(초)
STOP_REAP_WAIT = 5.0    # 끈 뒤 이 프로세스가 띄운 서버 프로세스가 끝나기를 기다리는 최대 시간(초, #836)
FAIL_REAP_WAIT = 2.0    # 띄우기에 실패했을 때 그 서버 프로세스가 끝나기를 기다리는 최대 시간(초, #836)


def port_bindable(port: int) -> bool:
    """서버가 열 때와 같은 방식으로 이 포트를 열 수 있는가."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if platform_compat.current_os() != "windows":  # server.py 의 Server.allow_reuse_address 와 같다
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def wait_port_released(port: int, seconds: float) -> bool:
    """우리 서버가 응답하지 않고 포트도 열 수 있게 될 때까지 기다린다. 시간 안에 풀리면 True."""
    end = time.monotonic() + seconds
    while True:
        if probe(port) == "free" and port_bindable(port):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.1)


def err_path() -> Path:
    return platform_compat.state_dir() / "server.err"


def read_server_error() -> str:
    try:
        return " ".join(err_path().read_text(encoding="utf-8", errors="replace").split())[:300]
    except OSError:
        return ""


# 이 프로세스가 띄운 서버의 Popen. 떼어 띄운 서버는 기다리지 않지만, 핸들을 바로 버리면 살아 있는 프로세스의 Popen 이
# 정리되며 ResourceWarning 이 난다(#836). 들고 있다가 같은 프로세스에서 서버를 끄면 stop_server 가 거둔다.
# Windows venv 의 pythonw.exe 는 실제 서버를 자식으로 띄우는 런처라 Popen pid 와 server.pid 가 다를 수 있어 pid 로 짝짓지 않는다.
_launched: list = []


def start_server(port: int) -> None:
    try:
        err_path().unlink()  # 이전 실행의 실패 이유가 남아 있지 않게 한다
    except OSError:
        pass
    _launched.append(launch_server(port))


def reap_launched(timeout: float) -> None:
    """이 프로세스가 띄운 서버 중 끝난 것을 거둔다(wait). 시간 안에 안 끝난 것은 그대로 둔다."""
    end = time.monotonic() + timeout
    for proc in list(_launched):
        try:
            proc.wait(max(0.0, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            continue
        _launched.remove(proc)


def ensure_server(port: int, wait: float = 20.0) -> str | None:
    """서버가 떠 있게 한다. 실패하면 이유를, 성공하면 None 을 돌려준다."""
    state = probe(port)
    if state == "ours":
        return None
    if state == "other":
        return f"포트 {port} 를 다른 프로그램이 쓰고 있어 웹 콘솔을 띄울 수 없어."
    wait_port_released(port, START_PORT_WAIT)  # 방금 끈 서버의 포트가 풀리기를 잠깐 기다린다. 끝내 안 풀려도 띄워 원인을 남기게 한다
    state = probe(port)
    if state == "ours":
        return None
    start_server(port)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        time.sleep(0.2)
        state = probe(port)
        if state == "ours":
            return None
        if state == "other":
            reap_launched(FAIL_REAP_WAIT)  # 띄운 서버는 포트를 못 열고 끝난다 -> 거둔다(#836)
            return f"포트 {port} 를 다른 프로그램이 쓰고 있어 웹 콘솔을 띄울 수 없어."
        why = read_server_error()
        if why:  # 서버가 스스로 못 뜬 이유를 남겼다 -> 더 기다리지 않는다
            reap_launched(FAIL_REAP_WAIT)
            return f"웹 콘솔 서버가 뜨지 못했어. 원인: {why}"
    why = read_server_error()
    reap_launched(FAIL_REAP_WAIT)  # 아직 안 끝났으면 그대로 둔다(끝까지 기다리지 않는다)
    return "웹 콘솔 서버가 시간 안에 뜨지 않았어." + (f" 원인: {why}" if why else "")


def stop_server(port: int) -> str:
    pid_path = platform_compat.state_dir() / "server.pid"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return "실행 중인 웹 콘솔 서버를 찾지 못했어." if probe(port) != "ours" else "서버 기록을 찾지 못해 끄지 못했어."
    if probe(port) != "ours":
        return "실행 중인 웹 콘솔 서버가 없어."  # 옛 기록이 다른 프로세스를 가리킬 수 있으므로 건드리지 않는다
    status, _ = request(port, "POST", "/api/shutdown", {})  # 정상 종료 절차를 먼저 요청한다
    if status != 200:
        platform_compat.terminate_pid(pid)  # 위에서 /api/health 로 우리 서버임을 확인했다
    if wait_port_released(port, STOP_PORT_WAIT):  # 서버가 응답을 멈춘 뒤에도 소켓이 잠시 남는다 -> 바로 다시 띄우면 열지 못한다
        reap_launched(STOP_REAP_WAIT)  # 이 프로세스가 띄운 서버였다면 끝난 프로세스를 거둔다(#836)
        return "웹 콘솔 서버를 껐어."
    return "웹 콘솔 서버가 아직 꺼지지 않았어."


def main(argv: list[str]) -> int:
    port = platform_compat.port_from_env()
    if "--stop" in argv:
        print(stop_server(port))
        return 0
    why = ensure_server(port)
    if why:
        print(why)
        return 1
    status, data = request(port, "POST", "/api/open", {}, timeout=30)  # 바쁜 PC 에서 브라우저가 뜨는 동안 끊기지 않게
    if status != 200:
        print("웹 콘솔 서버는 떠 있지만 브라우저를 열지 못했어. 이 명령을 다시 실행해 봐.")
        return 1
    line = "웹 콘솔을 브라우저로 열었어: http://127.0.0.1:%d" % port
    result = shortcut.Result("none") if "--from-shortcut" in argv else shortcut.ensure_shortcut(force="--make-shortcut" in argv)
    if result.status in ("made", "fixed"):
        line += " " + result.text
    print(line)
    if result.status == "failed":
        print(result.text)  # 콘솔은 이미 열렸다. 바로가기를 못 만든 것만 한 줄 더 알린다
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
