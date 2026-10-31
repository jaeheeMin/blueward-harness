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
import subprocess
import sys
import time
from pathlib import Path

import platform_compat

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


def server_popen_args(port: int, os_name: str | None = None) -> tuple[list[str], dict]:
    """서버를 띄우는 Popen 의 (명령, 키워드 인자). creationflags 는 하나로 합쳐 한 번만 넣는다."""
    env = dict(os.environ, HARNESS_CONSOLE_PORT=str(port))
    server = Path(__file__).resolve().parent / "server.py"
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                  **platform_compat.popen_detached_kwargs(os_name))
    return [sys.executable, str(server)], kwargs


def err_path() -> Path:
    return platform_compat.state_dir() / "server.err"


def read_server_error() -> str:
    try:
        return " ".join(err_path().read_text(encoding="utf-8", errors="replace").split())[:300]
    except OSError:
        return ""


def start_server(port: int) -> None:
    try:
        err_path().unlink()  # 이전 실행의 실패 이유가 남아 있지 않게 한다
    except OSError:
        pass
    args, kwargs = server_popen_args(port)
    subprocess.Popen(args, **kwargs)


def ensure_server(port: int, wait: float = 8.0) -> str | None:
    """서버가 떠 있게 한다. 실패하면 이유를, 성공하면 None 을 돌려준다."""
    state = probe(port)
    if state == "ours":
        return None
    if state == "other":
        return f"포트 {port} 를 다른 프로그램이 쓰고 있어 웹 콘솔을 띄울 수 없습니다."
    start_server(port)
    end = time.monotonic() + wait
    while time.monotonic() < end:
        time.sleep(0.2)
        state = probe(port)
        if state == "ours":
            return None
        if state == "other":
            return f"포트 {port} 를 다른 프로그램이 쓰고 있어 웹 콘솔을 띄울 수 없습니다."
        why = read_server_error()
        if why:  # 서버가 스스로 못 뜬 이유를 남겼다 -> 더 기다리지 않는다
            return f"웹 콘솔 서버가 뜨지 못했습니다. 원인: {why}"
    why = read_server_error()
    return "웹 콘솔 서버가 시간 안에 뜨지 않았습니다." + (f" 원인: {why}" if why else "")


def stop_server(port: int) -> str:
    pid_path = platform_compat.state_dir() / "server.pid"
    try:
        pid = int(pid_path.read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return "실행 중인 웹 콘솔 서버를 찾지 못했습니다." if probe(port) != "ours" else "서버 기록을 찾지 못해 끄지 못했습니다."
    if probe(port) != "ours":
        return "실행 중인 웹 콘솔 서버가 없습니다."  # 옛 기록이 다른 프로세스를 가리킬 수 있으므로 건드리지 않는다
    status, _ = request(port, "POST", "/api/shutdown", {})  # 정상 종료 절차를 먼저 요청한다
    if status != 200:
        platform_compat.terminate_pid(pid)  # 위에서 /api/health 로 우리 서버임을 확인했다
    for _ in range(50):
        if probe(port) == "free":
            return "웹 콘솔 서버를 껐습니다."
        time.sleep(0.1)
    return "웹 콘솔 서버가 아직 꺼지지 않았습니다."


def main(argv: list[str]) -> int:
    port = platform_compat.port_from_env()
    if "--stop" in argv:
        print(stop_server(port))
        return 0
    why = ensure_server(port)
    if why:
        print(why)
        return 1
    status, data = request(port, "POST", "/api/open", {})
    if status != 200:
        print("웹 콘솔 서버는 떠 있지만 브라우저를 열지 못했습니다. 이 명령을 다시 실행해 보십시오.")
        return 1
    print("웹 콘솔을 브라우저로 열었습니다: http://127.0.0.1:%d" % port)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
