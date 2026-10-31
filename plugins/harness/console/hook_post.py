"""콘솔 서버로 훅 입력을 넘기는 command 훅(web-console.md §5).

사용: hook_post.py <경로> [제한 초]   예: hook_post.py event 3
stdin 의 훅 입력을 `http://127.0.0.1:<포트>/hooks/<경로>` 로 POST 하고, 200 응답 본문을 그대로 stdout 에 낸다.

상태만 모으는 이벤트는 hooks.json 에서 `async: true` 로 돌아 stdout 이 쓰이지 않는다. 그래서 뜬 시각을 `X-Hook-Ts`
헤더로 함께 보내 서버가 늦게 도착한 이벤트를 가려낸다.

서버가 없거나 느리거나 오류를 돌려줘도 아무것도 출력하지 않고 exit 0 으로 끝난다. HTTP 훅은 서버가 꺼져 있으면
대화형 화면에 훅 오류 줄이 남지만, 이 스크립트는 조용히 지나간다. 승인·질문 훅이 오래 기다리는 동안
Claude Code 가 이 프로세스를 끝내면 소켓이 닫혀 서버가 "터미널에서 답했다" 는 것을 알아챈다.
"""
from __future__ import annotations

import http.client
import os
import re
import sys
import threading
import time


def main(argv: list[str]) -> int:
    started = time.time()  # 비동기 훅은 도착 순서가 뒤바뀔 수 있다. 서버가 순서를 가리도록 훅이 뜬 시각을 함께 보낸다.
    if not argv or not re.fullmatch(r"[a-z]+", argv[0]):
        return 0
    try:
        limit = float(argv[1]) if len(argv) > 1 else 3.0
    except ValueError:
        limit = 3.0
    timer = threading.Timer(limit, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    try:
        body = sys.stdin.buffer.read(1 << 22)
        try:
            port = int(os.environ.get("HARNESS_CONSOLE_PORT", "") or 4873)
        except ValueError:
            port = 4873
        if not body.strip():
            return 0
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=limit)
        try:
            conn.request("POST", "/hooks/" + argv[0], body=body, headers={"Content-Type": "application/json", "X-Hook-Ts": f"{started:.6f}"})
            resp = conn.getresponse()
            data = resp.read()
        finally:
            conn.close()
        if resp.status == 200 and data.strip():
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
