"""Chrome 디버깅 포트(CDP, Chrome DevTools Protocol)에 붙는 최소 클라이언트(#533).

사용자 매뉴얼 화면 캡처(`checker.manual_capture`)가 쓴다. 웹소켓 라이브러리를 더하지 않으려고 표준 라이브러리(`socket`)로
RFC 6455 의 필요한 부분(텍스트 프레임 보내기·받기, ping 에 pong, 조각난 메시지)만 구현했다.

보안: **`127.0.0.1` 에만 붙는다.** 호스트를 `localhost`·사설 주소·다른 PC 로 지정하면 연결하기 전에 거부한다
(`/json/list` 가 돌려준 `webSocketDebuggerUrl` 의 호스트도 다시 확인한다). 로그인 쿠키가 든 브라우저를 원격에서 조종하게
두지 않기 위해서다. 프록시 환경 변수도 쓰지 않는다.

못 붙거나 응답이 없으면 `CdpError`(검사 불능)다. 통과나 위반으로 뭉개지 않는다.
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 9222


class CdpError(RuntimeError):
    """브라우저에 붙지 못했거나 명령이 실패했다(검사 불능)."""


def ensure_loopback(host: str) -> None:
    """`127.0.0.1` 이 아니면 거부한다. `localhost` 도 거부한다(이름 풀이에 기대지 않는다)."""
    if host != LOOPBACK:
        raise CdpError(f"원격 디버깅 주소는 {LOOPBACK} 만 허용한다(받은 값: {host!r}). 로그인 쿠키가 든 브라우저를 다른 호스트에서 조종하게 두지 않는다")


def _check_port(port: int) -> None:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise CdpError(f"디버깅 포트가 올바르지 않다: {port!r}")


def list_tabs(host: str, port: int, timeout: float = 5.0) -> list[dict]:
    """`http://127.0.0.1:<포트>/json/list` 의 page 탭 목록."""
    ensure_loopback(host)
    _check_port(port)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://{LOOPBACK}:{port}/json/list", timeout=timeout) as resp:
            tabs = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        raise CdpError(f"{LOOPBACK}:{port} 의 Chrome 디버깅 포트에 붙지 못했다(전용 Chrome 이 떠 있는지 확인): {e}") from e
    if not isinstance(tabs, list):
        raise CdpError("탭 목록 응답이 목록이 아니다")
    return [t for t in tabs if isinstance(t, dict) and t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


class _WebSocket:
    def __init__(self, url: str, timeout: float) -> None:
        self.sock: socket.socket | None = None
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "ws":
            raise CdpError(f"웹소켓 주소가 ws:// 가 아니다: {url!r}")
        if parts.username is not None or parts.password is not None:
            raise CdpError(f"웹소켓 주소에 계정 부분(`@`)이 있어 거부한다: {url!r}")
        ensure_loopback(parts.hostname or "")
        try:
            port = parts.port or 80
        except ValueError as e:
            raise CdpError(f"웹소켓 주소의 포트가 올바르지 않다: {url!r}") from e
        _check_port(port)
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        try:
            self.sock = socket.create_connection((LOOPBACK, port), timeout=timeout)
            self.sock.settimeout(timeout)
            self._handshake(path, port)
        except CdpError:
            self.close()
            raise
        except (OSError, ValueError) as e:  # TimeoutError·ConnectionResetError 포함
            self.close()
            raise CdpError(f"웹소켓에 붙지 못했다: {e}") from e

    def _handshake(self, path: str, port: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f"GET {path} HTTP/1.1\r\nHost: {LOOPBACK}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(request.encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CdpError("웹소켓 핸드셰이크 중 연결이 끊겼다")
            head += chunk
            if len(head) > 65536:
                raise CdpError("웹소켓 핸드셰이크 응답이 너무 길다")
        header, _, rest = head.partition(b"\r\n\r\n")
        status_line = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise CdpError(f"웹소켓 핸드셰이크가 거절됐다: {status_line.decode('latin-1')}")
        self._buf = rest

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            try:
                chunk = self.sock.recv(max(65536, n - len(self._buf)))
            except TimeoutError as e:
                raise CdpError("브라우저 응답을 기다리다 시간이 지났다") from e
            except OSError as e:
                raise CdpError(f"웹소켓 읽기 실패: {e}") from e
            if not chunk:
                raise CdpError("브라우저와 연결이 끊겼다")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send(self, text: str, opcode: int = 0x1) -> None:
        data = text.encode("utf-8") if isinstance(text, str) else text
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self._sendall(head + mask + _xor_mask(data, mask))

    def recv(self) -> str:
        message = b""
        while True:
            b1, b2 = self._read(2)
            fin, opcode, length = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(length)
            if mask:
                payload = _xor_mask(payload, mask)
            if opcode == 0x8:
                raise CdpError("브라우저가 연결을 닫았다")
            if opcode == 0x9:
                self._pong(payload)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if fin:
                return message.decode("utf-8")

    def _pong(self, payload: bytes) -> None:
        mask = os.urandom(4)
        self._sendall(bytes([0x8A, 0x80 | len(payload)]) + mask + _xor_mask(payload, mask))

    def _sendall(self, data: bytes) -> None:
        try:
            self.sock.sendall(data)
        except OSError as e:
            raise CdpError(f"웹소켓 쓰기 실패: {e}") from e

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def _xor_mask(data: bytes, mask: bytes) -> bytes:
    # 큰 페이로드(스크린샷 등)는 정수 XOR 로 한 번에 처리한다.
    n = len(data)
    if n == 0:
        return b""
    key = (mask * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


class Tab:
    """탭 하나에 붙은 CDP 세션."""

    def __init__(self, info: dict, timeout: float = 30.0) -> None:
        self.info = info
        self._ws = _WebSocket(info["webSocketDebuggerUrl"], timeout)
        self._id = 0

    def call(self, method: str, **params) -> dict:
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") != mid:
                continue  # 이벤트·다른 응답은 버린다
            if "error" in msg:
                raise CdpError(f"{method} 실패: {msg['error'].get('message', msg['error'])}")
            return msg.get("result", {})

    def evaluate(self, expression: str):
        """페이지에서 식을 실행하고 값을 JSON 으로 받는다. 페이지 예외는 CdpError."""
        res = self.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            raise CdpError(f"페이지 스크립트 오류: {d.get('exception', {}).get('description') or d.get('text')}")
        return res.get("result", {}).get("value")

    def wait_until(self, expression: str, timeout: float, interval: float = 0.25) -> bool:
        """식이 참이 될 때까지 기다린다. 시간 초과면 False(호출한 쪽이 검사 불능으로 알린다)."""
        end = time.monotonic() + timeout
        while True:
            try:
                if self.evaluate(expression):
                    return True
            except CdpError:
                pass  # 이동 중이라 문맥이 바뀌었을 수 있다
            if time.monotonic() >= end:
                return False
            time.sleep(interval)

    def screenshot_png(self) -> bytes:
        res = self.call("Page.captureScreenshot", format="png", fromSurface=True)
        try:
            return base64.b64decode(res["data"])
        except (KeyError, ValueError) as e:
            raise CdpError("스크린샷 응답을 읽지 못했다") from e

    def close(self) -> None:
        self._ws.close()
