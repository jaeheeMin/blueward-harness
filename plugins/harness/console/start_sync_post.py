"""SessionStart 훅(hooks/session-start-sync.sh)이 한 최신 내용 받기의 결과를 콘솔 서버에 알린다(#1059).

사용: start_sync_post.py <결과 코드>   stdin 은 SessionStart 훅 입력(session_id·cwd 를 거기서 가져온다).
`http://127.0.0.1:<포트>/hooks/event` 로 {"hook_event_name": "HarnessStartSync", "state": ok|fail|unknown, "reason": 한 줄} 을 POST 한다.
결과 코드는 영문으로만 받고(Windows 셸 인자의 한글 인코딩을 피한다) 사유 글은 여기서 붙인다.

세션 시작을 막지 않는다: 자체 제한 3초, 콘솔이 없거나 어떤 오류가 나도 아무것도 출력하지 않고 항상 exit 0 이다.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import threading

LIMIT = 3.0
CONNECT_LIMIT = 0.5

# 코드 -> (상태, 화면에 보일 사유). ok 받음·이미 최신 / fail 다시 필요 / unknown 판정 못 함(확인 못 함)
RESULTS = {
    "latest": ("ok", "이미 최신이에요"),
    "synced": ("ok", "받아서 최신으로 맞췄어요"),
    "conflict": ("fail", "충돌해서 되돌렸어요. 다시 받아야 해요"),
    "failed": ("fail", "받다가 실패했어요. 다시 받아야 해요"),
    "fetch_failed": ("fail", "원격을 가져오지 못했어요. 네트워크·로그인을 확인해야 해요"),
    "main_ahead": ("fail", "로컬 main 이 원격보다 앞서 있어서 맞추지 않았어요"),
    "gone": ("unknown", "원격 브랜치가 지워진 작업이라 받지 않았어요"),
    "dirty": ("unknown", "커밋 안 된 변경이 있어서 받지 않았어요"),
    "in_progress": ("unknown", "리베이스·병합이 진행 중이라 받지 않았어요"),
    "no_remote": ("unknown", "원격 저장소가 없어서 확인 못 했어요"),
    "no_main": ("unknown", "비교할 원격 main 이 없어서 확인 못 했어요"),
    "not_repo": ("unknown", "git 저장소가 아니라서 확인 못 했어요"),
}


def post(body: bytes, port: int) -> None:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=CONNECT_LIMIT)
    try:
        conn.connect()  # Windows 는 닫힌 포트 거부에 약 2초 걸려서 연결 단계에만 짧은 제한을 둔다
        conn.sock.settimeout(LIMIT)
        conn.request("POST", "/hooks/event", body=body, headers={"Content-Type": "application/json"})
        conn.getresponse().read()
    finally:
        conn.close()


def build(raw: bytes, code: str) -> bytes | None:
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict) or not isinstance(data.get("session_id"), str) or not data["session_id"]:
        return None
    state, reason = RESULTS.get(code, ("unknown", "결과를 판정하지 못했어요"))
    body = {"hook_event_name": "HarnessStartSync", "session_id": data["session_id"], "cwd": data.get("cwd") if isinstance(data.get("cwd"), str) else "",
            "state": state, "reason": reason}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def main(argv: list[str]) -> int:
    timer = threading.Timer(LIMIT + 1.0, lambda: os._exit(0))
    timer.daemon = True
    timer.start()
    try:
        raw = sys.stdin.buffer.read(1 << 20)
        body = build(raw, argv[0] if argv else "")
        if body is not None:
            try:
                port = int(os.environ.get("HARNESS_CONSOLE_PORT", "") or 4873)
            except ValueError:
                port = 4873
            post(body, port)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
