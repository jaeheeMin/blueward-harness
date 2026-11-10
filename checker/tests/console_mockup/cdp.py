"""헤드리스 Chromium 계열 브라우저(Chrome·Edge·Chromium)를 DevTools 프로토콜로 움직이는 최소 클라이언트.

새 의존성(playwright 등)을 더하지 않으려고 표준 라이브러리만 쓴다. 브라우저는 이미 깔린 것을 찾아 쓰며,
없으면 find_browser() 가 None 을 돌려준다(호출하는 쪽이 "검사 불능" 으로 건너뛴다).
찾는 순서: 환경변수 CONSOLE_CHECK_BROWSER → PATH(chrome·chromium·microsoft-edge 등) → 흔한 설치 위치(Windows·macOS).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def find_browser() -> str | None:
    env = os.environ.get("CONSOLE_CHECK_BROWSER")
    if env:
        return env if Path(env).exists() else None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "microsoft-edge", "microsoft-edge-stable", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    pf = [os.environ.get(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    cands = []
    for base in filter(None, pf):
        cands += [Path(base) / "Google/Chrome/Application/chrome.exe", Path(base) / "Microsoft/Edge/Application/msedge.exe",
                  Path(base) / "Chromium/Application/chrome.exe"]
    cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
              Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
              Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


class WebSocket:
    """클라이언트 쪽 최소 WebSocket(텍스트 프레임만). DevTools 연결 하나에 필요한 만큼만 만든다."""

    def __init__(self, url: str, timeout: float = 60.0):
        assert url.startswith("ws://"), url
        hostport, _, path = url[5:].partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 핸드셰이크 중 연결이 끊김")
            buf += chunk
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("WebSocket 연결 거절: " + head.decode("latin1", "replace")[:200])

    def _read(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("WebSocket 연결이 끊김")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode("utf-8")
        n = len(data)
        head = bytearray([0x81])
        if n < 126:
            head.append(0x80 | n)
        elif n < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", n)
        mask = os.urandom(4)
        head += mask
        self.sock.sendall(bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        msg = b""
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)  # 서버→클라이언트 프레임은 마스크가 없다
            if op == 8:
                raise ConnectionError("브라우저가 연결을 닫음")
            if op == 9:  # ping -> pong
                self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op in (0, 1, 2):
                msg += payload
                if b0 & 0x80:
                    return msg.decode("utf-8")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    """headless 브라우저 하나와 탭 하나. with 로 쓰면 끝날 때 프로세스와 임시 프로필을 지운다."""

    def __init__(self, exe: str):
        self.exe = exe
        self.profile = Path(tempfile.mkdtemp(prefix="console-check-"))
        self.proc = None
        self.ws: WebSocket | None = None
        self._id = 0

    def __enter__(self) -> "Browser":
        try:
            return self._start()
        except BaseException:  # 중간에 실패하면 브라우저 프로세스와 임시 프로필을 남기지 않고 다시 던진다
            self.__exit__(None, None, None)
            raise

    def _start(self) -> "Browser":
        args = [self.exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--remote-debugging-port=0",
                f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--disable-background-networking", "--force-device-scale-factor=1", "--lang=ko-KR", "about:blank"]
        if sys.platform.startswith("linux"):
            args.insert(1, "--no-sandbox")  # 컨테이너·CI 에서 root 로 돌 때 필요하다
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = self.profile / "DevToolsActivePort"
        end = time.time() + 30
        # Chrome 156(Windows)은 실행한 프로세스가 브라우저를 넘겨 띄우고 곧바로 끝난다. 그래서 먼저 끝난 것만으로는 실패로 보지 않고
        # 이 프로필의 디버그 포트 파일이 생길 때까지 기다린다. 끝내 안 생기면 그때 실패다.
        while time.time() < end and not port_file.exists():
            time.sleep(0.1)
        if not port_file.exists():
            early = self.proc.poll() is not None
            raise RuntimeError(("브라우저가 바로 종료됨: " + self.exe) if early else "브라우저 디버그 포트를 못 받음")
        port = port_file.read_text().split()[0]
        self.port = port
        pages = []
        while time.time() < end and not pages:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                pages = [t for t in json.load(r) if t.get("type") == "page"]
            time.sleep(0.1) if not pages else None
        self.ws = WebSocket(pages[0]["webSocketDebuggerUrl"])
        self.call("Page.enable")
        self.call("Runtime.enable")
        return self

    def __exit__(self, *exc) -> None:
        if self.ws:
            self.ws.close()
        if getattr(self, "port", None):  # 띄운 프로세스가 이미 끝났어도(Chrome 156) 브라우저 자체를 닫는다
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=5) as r:
                    bws = WebSocket(json.load(r)["webSocketDebuggerUrl"], timeout=5)
                try:
                    bws.send(json.dumps({"id": 1, "method": "Browser.close", "params": {}}))
                    bws.recv()
                except (OSError, ConnectionError, ValueError):
                    pass  # 닫히면서 연결이 끊기는 것도 정상이다
                bws.close()
            except (OSError, ValueError, KeyError):
                pass
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for _ in range(10):  # 프로세스가 프로필 파일을 놓을 때까지(Windows)
            try:
                shutil.rmtree(self.profile)
                break
            except OSError:
                time.sleep(0.3)

    def call(self, method: str, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def evaluate(self, expr: str):
        res = self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            raise RuntimeError("페이지 스크립트 오류: " + json.dumps(res["exceptionDetails"], ensure_ascii=False)[:400])
        return res["result"].get("value")

    def set_viewport(self, width: int, height: int = 900) -> None:
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    def set_cookie(self, name: str, value: str, url: str) -> None:
        self.call("Network.setCookie", name=name, value=value, url=url)

    def goto(self, url: str, timeout: float = 30.0) -> None:
        self.call("Page.navigate", url=url)
        end = time.time() + timeout
        while time.time() < end:
            if self.evaluate("document.readyState") == "complete":
                return
            time.sleep(0.1)
        raise TimeoutError("페이지가 안 열림: " + url)

    def screenshot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)["data"]
        path.write_bytes(base64.b64decode(data))
