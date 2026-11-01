"""SessionStart command 훅. 콘솔 서버에 세션 시작을 알린다(web-console.md §5).

세션을 절대 막지 않는다: 자체 제한 1초, 어떤 오류든 삼키고 항상 exit 0 으로 끝낸다.
"""
from __future__ import annotations

import http.client
import os
import sys
import threading

LIMIT = 1.0
CONNECT_LIMIT = 0.5


def post(body: bytes, port: int) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=CONNECT_LIMIT)
    try:
        conn.connect()  # Windows 는 닫힌 포트 거부에 약 2초 걸려서 연결 단계에만 짧은 제한을 둔다
        conn.sock.settimeout(0.8)
        conn.request("POST", "/hooks/event", body=body, headers={"Content-Type": "application/json"})
        conn.getresponse().read()
    finally:
        conn.close()


def main() -> int:
    timer = threading.Timer(LIMIT, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    try:
        body = sys.stdin.buffer.read(1 << 20)
        try:
            port = int(os.environ.get("HARNESS_CONSOLE_PORT", "") or 4873)
        except ValueError:
            port = 4873
        if body.strip():
            post(body, port)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
