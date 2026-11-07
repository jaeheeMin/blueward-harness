"""브라우저에서 요소를 재는 공통 함수와 시안 보는 임시 서버."""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import threading
import time
from pathlib import Path

from .elements import ELEMENTS

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
STATIC = REPO / "plugins" / "harness" / "console" / "static"
MEASURE_JS = (HERE / "measure.js").read_text(encoding="utf-8")
WIDTHS = (1440, 1280)


def selectors(side: str, overrides: dict | None = None) -> dict[str, str]:
    """side 는 'mock' 또는 'console'. 화면별 overrides 로 선택자를 바꾸거나(None 이면) 뺀다."""
    out = {}
    for key, spec in ELEMENTS.items():
        ov = (overrides or {}).get(key, {})
        if ov is None:
            continue
        sel = ov.get(side) or ov.get("sel") or spec.get(side) or spec["mock"]
        out[key] = sel
    return out


def measure(br, sels: dict[str, str], settle: float = 10.0) -> dict:
    """두 번 연속 같은 값이 나올 때까지(그림이 안정될 때까지) 잰다."""
    expr = f"({MEASURE_JS})({json.dumps(sels)})"
    prev, end = None, time.time() + settle
    while True:
        cur = br.evaluate(expr)
        if cur == prev or time.time() > end:
            return cur
        prev = cur
        time.sleep(0.4)


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def guess_type(self, path):
        # 시안의 /_blob/<해시> 파일은 확장자가 없다. 앞부분으로 종류를 알아낸다.
        try:
            head = open(path, "rb").read(8)
        except OSError:
            return "application/octet-stream"
        return {bytes([0x89]) + b"PNG": "image/png", b"wOF2": "font/woff2"}.get(head[:4], super().guess_type(path))

    def translate_path(self, path):
        # /__static/ 아래는 콘솔 static 폴더(글꼴·로고). 시안과 같은 출처라 글꼴이 막히지 않는다.
        if path.startswith("/__static/"):
            return super().translate_path("/" + path[len("/__static/"):]).replace(str(Path(self.directory)), str(STATIC), 1)
        return super().translate_path(path)


def serve_dir(directory: Path) -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = functools.partial(_Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def sha(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:12]
