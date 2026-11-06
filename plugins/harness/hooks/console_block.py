"""막는 훅이 막을 때 그 사유를 웹 콘솔에 알린다(#650).

PreToolUse 가 막은 호출에는 다른 훅 이벤트가 뜨지 않고 한 훅이 다른 훅의 결과를 볼 수 없다. 그래서 막는 훅이
직접 `http://127.0.0.1:<포트>/hooks/blocked` 로 보낸다(콘솔 주소는 console/hook_post.py 와 같다).

보고는 부가 기능이다. 콘솔이 꺼져 있거나 느리거나 오류를 내도 호출한 훅의 종료코드·stdout·stderr 는 달라지지 않는다.
이 모듈은 어떤 예외도 밖으로 내지 않고, stdout·stderr 에 아무것도 쓰지 않는다(훅 stderr 는 Claude 에게 사유로 간다).

사용(bash 훅): `printf '%s' "$input" | HARNESS_BLOCK_REASON="$reason" python console_block.py <훅 이름>`
사용(python 훅): `console_block.report(payload, "pre_write_guard", reason)`
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading

CONNECT_LIMIT = 0.5  # Windows 는 닫힌 포트 거부에 약 2초 걸려서 연결 단계에만 짧은 제한을 둔다
TOTAL_LIMIT = 1.0
REASON_LIMIT = 6000


def _send(body: bytes) -> None:
    try:
        port = int(os.environ.get("HARNESS_CONSOLE_PORT", "") or 4873)
    except ValueError:
        port = 4873
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=CONNECT_LIMIT)
    try:
        conn.connect()
        conn.sock.settimeout(TOTAL_LIMIT)
        conn.request("POST", "/hooks/blocked", body=body, headers={"Content-Type": "application/json"})
        conn.getresponse().read()
    finally:
        conn.close()


def report(payload, hook: str, reason: str) -> None:
    """막은 사유를 콘솔로 보낸다. 실패하면 조용히 돌아온다. 전체가 TOTAL_LIMIT 안에 끝나도록 별도 스레드에서 보낸다."""
    try:
        if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str) or not payload.get("session_id"):
            return
        body = {"hook_event_name": "HarnessBlocked", "hook": str(hook)[:80], "reason": str(reason)[:REASON_LIMIT]}
        for key in ("session_id", "tool_use_id", "tool_name", "cwd"):
            if isinstance(payload.get(key), str):
                body[key] = payload[key]
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        worker = threading.Thread(target=lambda: _quiet(raw), daemon=True)
        worker.start()
        worker.join(CONNECT_LIMIT + TOTAL_LIMIT)
    except Exception:  # noqa: BLE001 - 보고 실패가 막는 동작을 바꾸면 안 된다
        pass


def _quiet(raw: bytes) -> None:
    try:
        _send(raw)
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str]) -> int:
    try:
        if len(argv) < 2:
            return 0
        raw = sys.stdin.buffer.read(1 << 22)
        payload = json.loads(raw.decode("utf-8", "replace") or "{}")
        reason = os.environ.get("HARNESS_BLOCK_REASON", "")
        if reason:
            report(payload, argv[1], reason)
    except Exception:  # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except BaseException:  # noqa: BLE001
        code = 0
    sys.exit(code)
