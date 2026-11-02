"""사용자 매뉴얼 화면 캡처(#533) 시험 — 브라우저 없이 도는 부분.

판정(0개·1개·여럿)·그리기 위치·화면 목록 형식·127.0.0.1 외 거부·작업본 갱신·웹소켓 클라이언트(가짜 서버)를 본다.
실제 Chrome 이 필요한 시험은 `HARNESS_CHROME_TEST=1` 일 때만 돈다(로컬 시험 절차는 docs/status/533-manual-capture.md).
"""
from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path

import pytest

from checker import cdp_client, manual_capture as mc
from checker.cdp_client import CdpError
from checker.manual_capture_js import LIB_JS
from checker.tests import test_export_pptx as tep


def R(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


# ---------------------------------------------------------------- 판정

def test_judge_zero_is_not_found():
    v = mc.judge([])
    assert v.status == "not_found" and v.rect is None


def test_judge_no_input_and_empty_reasons_differ():
    assert "입력 칸" in mc.judge([], no_input=1).reason
    assert "찾지 못했다" in mc.judge([]).reason


def V(x, y, w, h, visible=True):
    return {**R(x, y, w, h), "visible": visible}


def test_judge_single_candidate_off_screen_is_not_found():
    v = mc.judge([V(1700, 100, 80, 30, visible=False)])
    assert v.status == "not_found" and "화면 밖" in v.reason


def test_judge_visible_plus_offscreen_same_name_is_ambiguous():
    # 보이는 것이 하나뿐이어도 같은 이름이 화면 밖에 더 있으면 고르지 않는다
    v = mc.judge([V(100, 100, 80, 30), V(1700, 100, 80, 30, visible=False)])
    assert v.status == "ambiguous" and v.count == 2 and v.rect is None
    assert "화면 밖 1개" in v.reason


def test_judge_index_counts_offscreen_candidates_in_reading_order():
    cands = [V(100, 100, 80, 30), V(1700, 100, 80, 30, visible=False), V(100, 400, 80, 30)]
    assert mc.judge(cands, 1).rect["y"] == 100
    assert mc.judge(cands, 2).status == "not_found" and "화면 밖" in mc.judge(cands, 2).reason  # 2번째는 화면 밖
    assert mc.judge(cands, 3).rect["y"] == 400


def test_judge_one_is_found():
    v = mc.judge([R(10, 10, 100, 20)])
    assert v.status == "found" and v.rect == R(10, 10, 100, 20) and v.count == 1


def test_judge_two_or_more_is_ambiguous_and_picks_nothing():
    v = mc.judge([R(10, 10, 100, 20), R(10, 200, 100, 20)])
    assert v.status == "ambiguous" and v.rect is None and v.count == 2
    assert "index" in v.reason


def test_judge_index_picks_in_reading_order():
    rects = [R(300, 100, 50, 20), R(10, 100, 50, 20), R(10, 300, 50, 20)]
    assert mc.judge(rects, 1).rect == R(10, 100, 50, 20)
    assert mc.judge(rects, 2).rect == R(300, 100, 50, 20)
    assert mc.judge(rects, 3).rect == R(10, 300, 50, 20)
    assert mc.judge(rects, 4).status == "not_found"


def test_nested_duplicates_count_once():
    # 바깥 div 와 안쪽 button 이 거의 같은 영역이면 하나다
    v = mc.judge([R(10, 10, 100, 30), R(11, 11, 98, 28)])
    assert v.status == "found"


def test_distinct_overlapping_still_ambiguous():
    assert mc.judge([R(0, 0, 100, 100), R(60, 60, 100, 100)]).status == "ambiguous"


# ---------------------------------------------------------------- 그리기

def test_plan_marks_badge_sits_outside_top_left_corner():
    p = mc.plan_marks([(1, R(200, 200, 100, 40))], 1600, 900)[0]
    box, b = p.box, p.badge
    assert box == R(197, 197, 106, 46)  # 둘레 3px 여유
    assert b["cx"] < box["x"] and b["cy"] < box["y"]  # 네모 바깥 왼쪽 위
    # 배지 원이 네모 안쪽 영역(테두리 안)에 들어오지 않는다
    assert (b["cx"] + b["r"] <= box["x"] + mc.BOX_BORDER + 1) or (b["cy"] + b["r"] <= box["y"] + mc.BOX_BORDER + 1)
    assert not p.pushed and p.n == 1


def test_plan_marks_never_leaves_the_image():
    # 모서리에 붙은 요소: 왼쪽 위 자리가 그림 밖이라 다른 모서리로 옮긴다
    p = mc.plan_marks([(1, R(0, 0, 100, 40))], 1600, 900)[0]
    b = p.badge
    assert b["r"] <= b["cx"] <= 1600 - b["r"] and b["r"] <= b["cy"] <= 900 - b["r"]


def test_plan_marks_pushes_inward_when_no_corner_fits():
    # 그림 전체를 덮는 요소: 네 모서리 모두 그림 밖 → 왼쪽 위 자리를 안쪽으로 민다
    p = mc.plan_marks([(1, R(0, 0, 1600, 900))], 1600, 900)[0]
    assert p.pushed
    assert (p.badge["cx"], p.badge["cy"]) == (mc.BADGE_R, mc.BADGE_R)
    assert p.box == R(0, 0, 1600, 900)  # 네모도 그림 안으로 자른다


def test_plan_marks_keeps_numbers_and_avoids_overlapping_badges():
    # 두 요소가 붙어 있어 같은 자리가 되면 두 번째는 다른 모서리로 간다
    items = [(1, R(300, 300, 100, 30)), (3, R(300, 300, 100, 30))]
    a, b = mc.plan_marks(items, 1600, 900)
    assert (a.n, b.n) == (1, 3)  # 번호는 받은 번호 그대로(못 찾은 2 는 건너뛴다)
    d2 = (a.badge["cx"] - b.badge["cx"]) ** 2 + (a.badge["cy"] - b.badge["cy"]) ** 2
    assert d2 >= (2 * mc.BADGE_R) ** 2


# ---------------------------------------------------------------- 화면 목록 형식

GOOD = {"화면": [{
    "이름": "조회 조건", "앱": "#App-display",
    "준비": [{"입력": "플랜트", "값": "1010"}, {"누르기": "이동"}],
    "표시": [{"종류": "필터", "이름": "플랜트", "설명": "플랜트를 고른다"},
             {"종류": "열", "이름": "상태", "index": 2, "설명": "상태를 본다"}],
}]}


def test_parse_good_list():
    (s,) = mc.parse_screens(GOOD)
    assert s.name == "조회 조건" and s.app == "#App-display"
    assert [x.action for x in s.steps] == ["입력", "누르기"]
    assert s.steps[0].value == "1010"
    assert [(m.kind, m.index) for m in s.marks] == [("필터", None), ("열", 2)]


def _bad(**over):
    screen = json.loads(json.dumps(GOOD["화면"][0]))
    screen.update(over)
    return {"화면": [screen]}


@pytest.mark.parametrize("data", [
    None, {}, {"화면": []}, {"화면": "x"}, {"화면": [], "기타": 1},
    _bad(표시=[]),
    _bad(표시=[{"종류": "아이콘", "이름": "a", "설명": "b"}]),
    _bad(표시=[{"종류": "버튼", "이름": "a"}]),  # 설명 없음
    _bad(표시=[{"종류": "버튼", "이름": "a", "설명": "b", "index": 0}]),
    _bad(표시=[{"종류": "버튼", "이름": "a", "설명": "b", "색": "red"}]),
    _bad(앱="https://x.example/ui#A"),  # 전체 주소는 거부(테넌트는 env)
    _bad(준비=[{"입력": "플랜트", "값": 1010}]),  # 숫자 값
    _bad(준비=[{"입력": "플랜트"}]),
    _bad(준비=[{"입력": "플랜트", "값": "1", "누르기": "이동"}]),
    _bad(준비=[{"누르기": "이동", "값": "1"}]),
    _bad(이름="a/b"),
    _bad(이름="끝점."),
    _bad(팝업=[]),
])
def test_parse_rejects_bad_list(data):
    with pytest.raises(mc.ListError):
        mc.parse_screens(data)


def test_parse_rejects_duplicate_screen_names_and_collects_all_problems():
    data = {"화면": [GOOD["화면"][0], GOOD["화면"][0], {"이름": "x", "표시": []}]}
    with pytest.raises(mc.ListError) as e:
        mc.parse_screens(data)
    assert "겹친다" in str(e.value) and "표시" in str(e.value)  # 한 번에 다 알린다


@pytest.mark.parametrize("url,ok", [
    ("https://my1.s4hana.cloud.sap/ui", True),
    ("https://my1.s4hana.cloud.sap/ui#Shell-home", False),  # 프래그먼트
    ("https://my1.s4hana.cloud.sap/ui?sap-ui-token=abc", False),  # 쿼리(토큰)
    ("https://my1.s4hana.cloud.sap/ui?", False),
    ("http://127.0.0.1:8000/x", False),  # 시험용 옵션 없이는 http 거부
    ("file:///C:/x/page.html", False),
    ("http://example.com/ui", False),
    ("https://user:secret@example.com/ui", False),  # 비밀값
    ("https://127.0.0.1@evil.example/ui", False),
    ("ftp://example.com", False),
    ("", False),
    (None, False),
])
def test_check_base_url(url, ok):
    if ok:
        assert mc.check_base_url(url) == url
    else:
        with pytest.raises(mc.ListError):
            mc.check_base_url(url)


def test_check_base_url_local_test_option_allows_loopback_http_and_file_only():
    assert mc.check_base_url("http://127.0.0.1:8000/x", allow_local=True)
    assert mc.check_base_url("file:///C:/x/page.html", allow_local=True)
    with pytest.raises(mc.ListError):
        mc.check_base_url("http://example.com/ui", allow_local=True)
    with pytest.raises(mc.ListError):
        mc.check_base_url("file:///C:/x/page.html?a=1", allow_local=True)


def test_load_env_rejects_other_keys(tmp_path: Path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "manual-capture.yaml").write_text("테넌트: https://x.example/ui\n비밀번호: abc\n", encoding="utf-8")
    with pytest.raises(mc.ListError):
        mc.load_env(tmp_path)


def test_pick_tab():
    tabs = [{"url": "https://my1.example/ui#A", "title": "A"}, {"url": "https://accounts.example/login", "title": "L"}]
    assert mc.pick_tab(tabs, "https://my1.example/ui")["title"] == "A"
    with pytest.raises(mc.Unavailable):
        mc.pick_tab(tabs, "https://other.example/ui")
    assert mc.pick_tab(tabs[:1], "https://other.example/ui")["title"] == "A"  # 탭이 하나뿐이면 그것
    with pytest.raises(mc.Unavailable):
        mc.pick_tab([tabs[0], tabs[0]], "https://my1.example/ui")  # 둘이면 고르지 않는다
    assert mc.pick_tab(tabs, "https://x", hint="login")["title"] == "L"


# ---------------------------------------------------------------- 작업본

SPEC = """# 1.시험

버전: 0.2

## 묶은 개발 건

| DEV | 제목 |
|---|---|
| DEV-001 | 시험 |

## 양식 항목

### 사용자매뉴얼 · 표지

| 항목 | 값 |
|---|---|
| LoB | Test |

### 사용자매뉴얼 · 본문 · 조회 조건

| 항목 | 값 |
|---|---|
| 업무명 | 시험 |

#### 그림

미정

#### 번호 설명

1. 미정

### 사용자매뉴얼 · 본문 · 결과

| 항목 | 값 |
|---|---|
| 업무명 | 시험 |

### 사용자매뉴얼 · 끝

해당 없음
"""


def test_read_version():
    assert mc.read_version(SPEC) == "0.2"
    assert mc.read_version("# x\n\n## 절\n버전: 0.1\n") is None


def test_update_replaces_existing_sections_only():
    out = mc.update_workbook(SPEC, "조회 조건", "docs/manual/img/Test/조회 조건_v0.2.png", ["가", "나"])
    assert "#### 그림\n\ndocs/manual/img/Test/조회 조건_v0.2.png\n\n#### 번호 설명\n\n1. 가\n2. 나\n\n### 사용자매뉴얼 · 본문 · 결과" in out
    assert "미정" not in out
    # 다른 소절·표지·끝은 그대로
    assert out.split("### 사용자매뉴얼 · 본문 · 결과")[1] == SPEC.split("### 사용자매뉴얼 · 본문 · 결과")[1]
    assert out.startswith(SPEC.split("#### 그림")[0])


def test_update_adds_missing_sections_at_end_of_screen_section():
    out = mc.update_workbook(SPEC, "결과", "docs/manual/img/Test/결과_v0.2.png", ["하나"])
    assert "| 업무명 | 시험 |\n\n#### 그림\n\ndocs/manual/img/Test/결과_v0.2.png\n\n#### 번호 설명\n\n1. 하나\n\n### 사용자매뉴얼 · 끝" in out


def test_update_inserts_picture_before_existing_numbers():
    spec = SPEC.replace("#### 그림\n\n미정\n\n", "")
    out = mc.update_workbook(spec, "조회 조건", "p.png", ["가"])
    assert out.index("#### 그림") < out.index("#### 번호 설명")
    assert out.count("#### 그림") == 1 and out.count("#### 번호 설명") == 1


def test_update_is_idempotent():
    once = mc.update_workbook(SPEC, "결과", "a.png", ["x"])
    assert mc.update_workbook(once, "결과", "a.png", ["x"]) == once


def test_update_preserves_crlf():
    crlf = SPEC.replace("\n", "\r\n")
    out = mc.update_workbook(crlf, "결과", "a.png", ["x"])
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")


def test_update_keeps_original_line_endings_line_by_line():
    # 한 줄만 LF 인 CRLF 글: 건드리지 않은 줄의 줄바꿈은 그대로다(splitlines 로 합쳐 버리지 않는다)
    crlf = SPEC.replace("\n", "\r\n").replace("# 1.시험\r\n", "# 1.시험\n")
    out = mc.update_workbook(crlf, "결과", "a.png", ["x"])
    assert out.startswith("# 1.시험\n\r\n버전")
    assert out.split("### 사용자매뉴얼 · 끝")[1] == crlf.split("### 사용자매뉴얼 · 끝")[1]


def test_update_does_not_confuse_unusual_separators():
    # 줄 구분 문자( ·\x0c)가 든 글도 \n 기준으로만 나눈다
    spec = SPEC.replace("| 업무명 | 시험 |\n\n#### 그림", "| 업무명 | 시 험 |\n\n#### 그림")
    out = mc.update_workbook(spec, "조회 조건", "a.png", ["x"])
    assert "| 업무명 | 시 험 |" in out


def test_headings_inside_code_fences_are_ignored():
    fenced = SPEC.replace(
        "### 사용자매뉴얼 · 본문 · 결과\n",
        "### 사용자매뉴얼 · 본문 · 결과\n\n```\n### 사용자매뉴얼 · 본문 · 조회 조건\n#### 그림\n```\n")
    # 펜스 안의 가짜 소절은 소절로 세지 않는다(조회 조건 소절은 여전히 하나)
    out = mc.update_workbook(fenced, "조회 조건", "a.png", ["x"])
    assert out.count("### 사용자매뉴얼 · 본문 · 조회 조건") == 2  # 진짜 하나 + 펜스 안 글자
    # 펜스 안의 `#### 그림` 은 소제목이 아니라서 진짜 소제목만 바뀐다
    assert "```\n### 사용자매뉴얼 · 본문 · 조회 조건\n#### 그림\n```" in out
    out2 = mc.update_workbook(fenced, "결과", "b.png", ["y"])
    assert "```\n### 사용자매뉴얼 · 본문 · 조회 조건\n#### 그림\n```" in out2
    assert out2.index("b.png") > out2.index("```\n", out2.index("본문 · 결과"))  # 펜스 뒤(소절 끝)에 새 소제목이 붙는다


def test_existing_descriptions():
    assert mc.existing_descriptions(SPEC, "조회 조건") == ["미정"]
    assert mc.existing_descriptions(SPEC, "결과") is None  # 번호 설명 소제목이 없다
    assert mc.existing_descriptions(SPEC, "없는 화면") is None


def test_update_errors_on_missing_or_duplicate_section():
    with pytest.raises(mc.ListError):
        mc.update_workbook(SPEC, "없는 화면", "a.png", ["x"])
    dup = SPEC + "\n### 사용자매뉴얼 · 본문 · 결과\n\n| 항목 | 값 |\n|---|---|\n| 업무명 | 시험 |\n"
    with pytest.raises(mc.ListError):
        mc.update_workbook(dup, "결과", "a.png", ["x"])


def test_image_name_ends_with_version():
    assert mc.image_rel("Prod", "조회 조건", "0.1") == "docs/manual/img/Prod/조회 조건_v0.1.png"
    assert mc.image_rel("Prod", "조회 조건", "0.1", partial=True).endswith("_미완_v0.1.png")


# ---------------------------------------------------------------- 127.0.0.1 외 거부

@pytest.mark.parametrize("host", ["localhost", "0.0.0.0", "192.168.0.5", "10.0.0.1", "example.com", "::1", "", "127.0.0.2"])
def test_non_loopback_hosts_are_rejected(host):
    with pytest.raises(CdpError):
        cdp_client.ensure_loopback(host)
    with pytest.raises(CdpError):
        cdp_client.list_tabs(host, 9222)  # 네트워크에 나가기 전에 거부


def test_loopback_is_accepted():
    cdp_client.ensure_loopback("127.0.0.1")


def test_websocket_url_on_other_host_is_rejected():
    # /json/list 가 다른 호스트의 웹소켓 주소를 돌려줘도 붙지 않는다
    with pytest.raises(CdpError):
        cdp_client.Tab({"webSocketDebuggerUrl": "ws://192.168.0.5:9222/devtools/page/X"})
    with pytest.raises(CdpError):
        cdp_client.Tab({"webSocketDebuggerUrl": "wss://127.0.0.1:9222/devtools/page/X"})


def test_bad_port_is_rejected():
    for port in (0, 70000, -1, True):
        with pytest.raises(CdpError):
            cdp_client.list_tabs("127.0.0.1", port)


# ---------------------------------------------------------------- 웹소켓 클라이언트(가짜 서버)

def _frame(payload: bytes, opcode: int = 0x1, fin: bool = True) -> bytes:
    n = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    if n < 126:
        return head + bytes([n]) + payload
    if n < 65536:
        return head + bytes([126]) + struct.pack(">H", n) + payload
    return head + bytes([127]) + struct.pack(">Q", n) + payload


def _read_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _serve_once(server: socket.socket, big: int, seen: dict) -> None:
    conn, _ = server.accept()
    with conn:
        head = b""
        while b"\r\n\r\n" not in head:
            head += conn.recv(4096)
        seen["handshake"] = head.decode("latin-1")
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
        b1, b2 = _read_exact(conn, 2)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", _read_exact(conn, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", _read_exact(conn, 8))[0]
        mask = _read_exact(conn, 4)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(_read_exact(conn, length)))
        seen["masked"] = bool(b2 & 0x80)
        msg = json.loads(data)
        conn.sendall(_frame(b"ping!", opcode=0x9))  # ping 은 pong 으로 답하고 계속 읽어야 한다
        conn.sendall(_frame(json.dumps({"method": "Some.event", "params": {}}).encode()))  # 이벤트는 건너뛴다
        reply = json.dumps({"id": msg["id"], "result": {"echo": msg["method"], "data": "x" * big}}).encode()
        half = len(reply) // 2  # 조각난 메시지
        conn.sendall(_frame(reply[:half], fin=False) + _frame(reply[half:], opcode=0x0))
        try:
            conn.settimeout(2)
            b1, b2 = _read_exact(conn, 2)
            _read_exact(conn, 4 + (b2 & 0x7F))  # 남은 마스크·내용을 다 읽고 닫아야 연결이 재설정되지 않는다
            seen["pong"] = (b1 & 0x0F) == 0xA
        except (OSError, EOFError):
            pass


@pytest.mark.parametrize("big", [10, 70000])
def test_websocket_client_roundtrip_with_fake_server(big):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    seen: dict = {}
    t = threading.Thread(target=_serve_once, args=(server, big, seen), daemon=True)
    t.start()
    port = server.getsockname()[1]
    tab = cdp_client.Tab({"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/X"}, timeout=5)
    try:
        res = tab.call("Test.method", a=1)
    finally:
        tab.close()
        t.join(3)
        server.close()
    assert res["echo"] == "Test.method" and len(res["data"]) == big
    assert seen["masked"] and "Host: 127.0.0.1" in seen["handshake"]
    assert seen.get("pong") is True


# ---------------------------------------------------------------- 실행(--check, 브라우저 없이)

def _repo(tmp_path: Path, *, with_section: bool = True) -> Path:
    spec_dir = tmp_path / "docs" / "manual" / "Test"
    spec_dir.mkdir(parents=True)
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "manual-capture.yaml").write_text("테넌트: https://my1.example/ui\n", encoding="utf-8")
    body = SPEC if with_section else SPEC.replace("본문 · 조회 조건", "본문 · 다른")
    (spec_dir / "1.시험.md").write_bytes(body.encode("utf-8"))  # 줄바꿈을 그대로(Windows 의 \n → \r\n 변환을 피한다)
    (spec_dir / "1.시험.capture.yaml").write_text(
        "화면:\n  - 이름: 조회 조건\n    앱: \"#A-display\"\n    표시:\n      - {종류: 필터, 이름: 플랜트, 설명: 고른다}\n", encoding="utf-8")
    return tmp_path


def _run(capsys, *argv):
    code = mc.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_check_ok(tmp_path, capsys):
    root = _repo(tmp_path)
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--check")
    assert code == 0 and out["status"] == "ok" and out["screens"][0]["표시"] == 1


def test_check_missing_section_in_spec_is_error(tmp_path, capsys):
    root = _repo(tmp_path, with_section=False)
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--check")
    assert code == 2 and "소절이 없다" in out["problems"][0]


def test_check_rejects_non_loopback_host_without_touching_network(tmp_path, capsys):
    root = _repo(tmp_path)
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--host", "192.168.0.5")
    assert code == 2 and "127.0.0.1" in out["problems"][0]


def test_check_without_tenant_is_error(tmp_path, capsys):
    root = _repo(tmp_path)
    (root / "env" / "manual-capture.yaml").unlink()
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--check")
    assert code == 2 and "테넌트" in out["problems"][0]


def test_unreachable_browser_is_unavailable_not_pass(tmp_path, capsys):
    root = _repo(tmp_path)
    with socket.socket() as s:  # 비어 있는 포트를 얻는다
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--port", str(port))
    assert code == 2 and out["status"] == "error" and "검사 불능" in out["problems"][0]
    assert not (root / "docs" / "manual" / "img").exists()  # 아무것도 쓰지 않았다


# ---------------------------------------------------------------- 웹소켓 오류·주소 거부

def test_websocket_url_with_userinfo_trick_is_rejected():
    # `127.0.0.1@evil` 은 호스트가 evil 이다
    for url in ("ws://127.0.0.1@evil:80/", "ws://127.0.0.1:9222@evil.example/devtools/page/X", "ws://user:pw@127.0.0.1:9222/x"):
        with pytest.raises(CdpError):
            cdp_client.Tab({"webSocketDebuggerUrl": url})
    with pytest.raises(CdpError):
        cdp_client.Tab({"webSocketDebuggerUrl": "ws://127.0.0.1:notaport/x"})


def _server(handler):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve():
        try:
            conn, _ = server.accept()
            handler(conn)
        except OSError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return server, t, server.getsockname()[1]


def _connect_spy(monkeypatch):
    made = []
    real = socket.create_connection

    def spy(*a, **k):
        s = real(*a, **k)
        made.append(s)
        return s

    monkeypatch.setattr(cdp_client.socket, "create_connection", spy)
    return made


def _reset(conn):
    conn.recv(4096)
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # 닫으면 RST
    conn.close()


def _close_silently(conn):
    conn.recv(4096)
    conn.close()


def _hang(conn):
    conn.recv(4096)
    threading.Event().wait(1.5)
    conn.close()


@pytest.mark.parametrize("handler,needle", [(_reset, ""), (_close_silently, "끊겼"), (_hang, "붙지 못했다")])
def test_handshake_failures_become_cdp_error_and_close_the_socket(monkeypatch, handler, needle):
    made = _connect_spy(monkeypatch)
    server, t, port = _server(handler)
    try:
        with pytest.raises(CdpError) as e:
            cdp_client.Tab({"webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/X"}, timeout=0.4)
    finally:
        server.close()
        t.join(3)
    assert needle in str(e.value)
    assert made and all(s.fileno() == -1 for s in made)  # 실패하면 소켓을 닫는다


def test_http_listing_errors_become_cdp_error(monkeypatch):
    # 응답이 HTTP 가 아닌 포트(BadStatusLine 등)도 검사 불능으로 감싼다
    def junk(conn):
        conn.recv(4096)
        conn.sendall(b"\x00\x01 not http\r\n\r\n")
        conn.close()

    server, t, port = _server(junk)
    try:
        with pytest.raises(CdpError):
            cdp_client.list_tabs("127.0.0.1", port, timeout=2)
    finally:
        server.close()
        t.join(3)


def test_non_integer_port_in_env_is_error_not_traceback(tmp_path, capsys):
    root = _repo(tmp_path)
    (root / "env" / "manual-capture.yaml").write_text("테넌트: https://my1.example/ui\n포트: abc\n", encoding="utf-8")
    code, out = _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--check")
    assert code == 2 and "포트" in out["problems"][0]


# ---------------------------------------------------------------- 가짜 CDP 로 캡처 경로 전체

BASE = "https://my1.example/ui"

TWO_SCREENS = """화면:
  - 이름: 조회 조건
    앱: "#A-display"
    표시:
      - {종류: 필터, 이름: 플랜트, 설명: 플랜트를 고른다}
      - {종류: 버튼, 이름: 이동, 설명: 조회한다}
"""

FOUND = {"items": [{"x": 100, "y": 200, "w": 200, "h": 50, "visible": True}], "noInput": 0}
NONE = {"items": [], "noInput": 0}


class FakeTab:
    """`cdp_client.Tab` 대역. 페이지 스크립트 결과를 `finds` 로 정해 준다."""

    def __init__(self, finds, href=BASE, redirect=None, ready=True):
        self.finds, self.href, self.redirect, self.ready = finds, href, redirect, ready
        self.stale = False
        self.calls: list[tuple] = []
        self.evals: list[str] = []
        self.on_screenshot = None
        self.closed = False

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "Page.navigate":
            self.href = self.redirect or params["url"]
            self.stale = False
        elif method == "Page.reload":
            self.stale = False
        return {}

    def evaluate(self, expr):
        self.evals.append(expr)
        if expr.startswith("(window.__mc_stale"):
            if self.stale:
                return "stale"
            return True if self.ready else False
        if expr == "window.__mc_stale = true":
            self.stale = True
            return True
        if expr == "location.href":
            return self.href
        if expr == LIB_JS:
            return True
        if expr.startswith("window.__mc.find("):
            kind, name = json.loads("[" + expr[len("window.__mc.find("):-1] + "]")
            return self.finds.get((kind, name), NONE)
        if expr == "window.__mc.size()":
            return {"w": 1600, "h": 900}
        if expr.startswith("window.__mc.focusInput("):
            return {"ok": True}
        return 1 if "scrollColumn" in expr else None

    def screenshot_png(self):
        if self.on_screenshot:
            self.on_screenshot()
        return tep._png((20, 40, 60), (1600, 900))

    def close(self):
        self.closed = True


@pytest.fixture
def fake(monkeypatch):
    holder = {}
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    monkeypatch.setattr(cdp_client, "list_tabs", lambda host, port, timeout=5.0: [
        {"type": "page", "url": BASE, "title": "T", "webSocketDebuggerUrl": "ws://127.0.0.1:1/x"}])
    monkeypatch.setattr(cdp_client, "Tab", lambda info, timeout=30.0: holder["tab"])
    return holder


def _capture(capsys, root, *extra):
    return _run(capsys, "--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--timeout", "2", *extra)


def _spec(root):
    return (root / "docs" / "manual" / "Test" / "1.시험.md").read_bytes().decode("utf-8")


def test_run_all_found_updates_workbook_and_exits_0(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): {"items": [
        {"x": 400, "y": 200, "w": 80, "h": 40, "visible": True}], "noInput": 0}})
    code, out = _capture(capsys, root)
    assert code == 0 and out["status"] == "ok", out
    row = out["screens"][0]
    assert row["상태"] == "완료" and row["작업본 갱신"] is True and not row.get("못 찾은 것")
    assert (root / "docs/manual/img/Test/조회 조건_v0.2.png").is_file()
    spec = _spec(root)
    assert "docs/manual/img/Test/조회 조건_v0.2.png" in spec and "1. 플랜트를 고른다\n2. 조회한다" in spec
    assert not list((root / "docs/manual/Test").glob("*.tmp"))  # 임시 파일이 남지 않는다
    assert fake["tab"].closed
    overlay = [e for e in fake["tab"].evals if e.startswith("window.__mc.drawOverlay(")]
    assert len(overlay) == 1 and '"n": 1' in overlay[0] and '"n": 2' in overlay[0]


def test_run_missing_element_exits_1_and_leaves_workbook_alone(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    before = _spec(root)
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND})  # 이동 버튼은 못 찾음
    code, out = _capture(capsys, root)
    assert code == 1 and out["status"] == "incomplete"
    row = out["screens"][0]
    assert row["상태"] == "미완" and row["못 찾은 것"][0]["번호"] == 2 and row["못 찾은 것"][0]["상태"] == "not_found"
    assert (root / "docs/manual/img/Test/조회 조건_미완_v0.2.png").is_file()
    assert not (root / "docs/manual/img/Test/조회 조건_v0.2.png").exists()
    assert _spec(root) == before


def test_run_not_ready_is_unavailable_exit_2(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    before = _spec(root)
    fake["tab"] = FakeTab({}, ready=False)
    code, out = _capture(capsys, root, "--timeout", "0.05")
    assert code == 2 and out["status"] == "unavailable"
    assert out["screens"][0]["상태"] == "검사 불능" and "준비되지 않았다" in out["screens"][0]["사유"]
    assert _spec(root) == before and not (root / "docs/manual/img").exists()


def test_run_checks_origin_even_when_ready(tmp_path, capsys, fake):
    # 로그인 화면(다른 출처)이 준비 상태로 보여도 테넌트가 아니면 찍지 않는다
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND}, redirect="https://accounts.example/login")
    code, out = _capture(capsys, root)
    assert code == 2 and "출처" in out["screens"][0]["사유"]
    assert not (root / "docs/manual/img").exists()


def test_run_reopens_every_screen_even_on_same_url(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS.replace('    앱: "#A-display"\n', ""), encoding="utf-8")
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND}, href=BASE)
    code, out = _capture(capsys, root)
    methods = [m for m, _ in fake["tab"].calls]
    assert code == 0 and "Page.reload" in methods and "Page.navigate" not in methods  # 같은 주소 → 다시 로드


def test_run_hash_only_change_navigates_then_reloads_other_document_only_navigates(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    t = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND}, href=BASE)
    fake["tab"] = t
    _capture(capsys, root)
    assert [m for m, _ in t.calls if m in ("Page.navigate", "Page.reload")] == ["Page.navigate", "Page.reload"]
    # 다른 문서(주소 경로가 다름)면 navigate 만으로 새로 열린다
    root2 = _repo(tmp_path / "b")
    (root2 / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    t2 = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND}, href="https://my1.example/other")
    fake["tab"] = t2
    _capture(capsys, root2)
    assert [m for m, _ in t2.calls if m in ("Page.navigate", "Page.reload")] == ["Page.navigate"]


def test_run_ambiguity_with_offscreen_duplicate_and_scroll_uses_same_index(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(
        "화면:\n  - 이름: 조회 조건\n    표시:\n"
        "      - {종류: 열, 이름: 비고, 설명: 하나}\n"
        "      - {종류: 열, 이름: 비고, index: 2, 설명: 둘}\n", encoding="utf-8")
    two = {"items": [{"x": 100, "y": 200, "w": 90, "h": 120, "visible": True},
                     {"x": 1700, "y": 200, "w": 90, "h": 120, "visible": False}], "noInput": 0}
    t = FakeTab({("열", "비고"): two})
    fake["tab"] = t
    code, out = _capture(capsys, root)
    miss = {m["번호"]: m for m in out["screens"][0]["못 찾은 것"]}
    assert code == 1
    assert miss[1]["상태"] == "ambiguous"  # 보이는 것 하나 + 화면 밖 하나
    assert miss[2]["상태"] == "not_found" and "화면 밖" in miss[2]["사유"]  # index 2 는 화면 밖
    scrolls = [e for e in t.evals if e.startswith("window.__mc.scrollColumn(")]
    args = [json.loads("[" + e[len("window.__mc.scrollColumn("):-1] + "]") for e in scrolls]
    assert args == [["비고", None], ["비고", 2]]  # find 와 같은 index 기준


def test_run_reports_replaced_descriptions_and_rereads_the_workbook(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    spec_path = root / "docs/manual/Test/1.시험.md"
    spec_path.write_bytes(_spec(root).replace("1. 미정", "1. 옛 설명 하나\n2. 옛 설명 둘").encode("utf-8"))
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    t = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND})

    def user_edits_meanwhile():  # 캡처 도중 사람이 작업본 끝에 글을 더했다
        spec_path.write_bytes(spec_path.read_bytes() + "\n<!-- 사람이 더한 글 -->\n".encode("utf-8"))

    t.on_screenshot = user_edits_meanwhile
    fake["tab"] = t
    code, out = _capture(capsys, root)
    row = out["screens"][0]
    assert code == 0
    assert row["replaced_descriptions"] == {"before": ["옛 설명 하나", "옛 설명 둘"], "after": ["플랜트를 고른다", "조회한다"]}
    assert "<!-- 사람이 더한 글 -->" in _spec(root)  # 갱신 직전에 다시 읽었으므로 사람의 변경이 남는다


def test_run_placeholder_descriptions_are_not_reported_as_replaced(tmp_path, capsys, fake):
    root = _repo(tmp_path)  # 번호 설명 "1. 미정"
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND})
    _, out = _capture(capsys, root)
    assert "replaced_descriptions" not in out["screens"][0]


def test_run_keeps_crlf_workbook(tmp_path, capsys, fake):
    root = _repo(tmp_path)
    p = root / "docs/manual/Test/1.시험.md"
    p.write_bytes(_spec(root).replace("\n", "\r\n").encode("utf-8"))
    (root / "docs/manual/Test/1.시험.capture.yaml").write_text(TWO_SCREENS, encoding="utf-8")
    fake["tab"] = FakeTab({("필터", "플랜트"): FOUND, ("버튼", "이동"): FOUND})
    code, _ = _capture(capsys, root)
    raw = p.read_bytes().decode("utf-8")
    assert code == 0 and "\n" not in raw.replace("\r\n", "") and "1. 플랜트를 고른다" in raw


def test_locate_judges_with_find_result_through_capturer():
    t = FakeTab({("버튼", "이동"): {"items": [{"x": 1, "y": 1, "w": 5, "h": 5, "visible": True},
                                              {"x": 900, "y": 1, "w": 5, "h": 5, "visible": False}], "noInput": 0}})
    cap = mc.Capturer(t, BASE, "require", 1)
    assert cap.locate(mc.Mark("버튼", "이동", "")).status == "ambiguous"
    assert cap.locate(mc.Mark("버튼", "이동", "", 1)).status == "found"
    t.finds = {("버튼", "이동"): "이상한 응답"}
    with pytest.raises(mc.Unavailable):
        cap.locate(mc.Mark("버튼", "이동", ""))


# ---------------------------------------------------------------- 작업본 → 고객 양식 pptx 산출까지

def test_updated_workbook_exports_to_pptx(tmp_path, capsys, fake):
    from pptx import Presentation

    root = tmp_path
    (root / "templates" / "forms").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / "templates" / "forms" / "시험매뉴얼.yaml").write_text(tep.MAP, encoding="utf-8")
    (root / "rules" / "test.yaml").write_text(tep.RULES, encoding="utf-8")
    tep._make_template(root / "templates" / "시험.pptx")
    (root / "docs" / "img").mkdir(parents=True)
    (root / "docs" / "img" / "b.png").write_bytes(tep._png((150, 0, 150), (100, 200)))
    (root / "env").mkdir()
    (root / "env" / "manual-capture.yaml").write_text(f"테넌트: {BASE}\n", encoding="utf-8")
    folder = root / "docs" / "manual" / "Test"
    folder.mkdir(parents=True)
    # 첫째 화면의 그림·번호 설명은 아직 모른다(미정). 둘째 화면은 이미 그림이 있다.
    spec = tep.SPEC.replace("docs/img/a.png", "미정").replace("1. 하나\n2. 둘\n\n###", "1. 미정\n\n###", 1)
    (folder / "1.시험.md").write_bytes(spec.encode("utf-8"))
    (folder / "1.시험.capture.yaml").write_text(
        "화면:\n  - 이름: 첫째 화면\n    표시:\n"
        "      - {종류: 버튼, 이름: 이동, 설명: 캡처가 채운 첫째 설명}\n"
        "      - {종류: 버튼, 이름: 저장, 설명: 캡처가 채운 둘째 설명}\n", encoding="utf-8")
    fake["tab"] = FakeTab({("버튼", "이동"): FOUND, ("버튼", "저장"): FOUND})

    code = mc.main(["--list", "docs/manual/Test/1.시험.capture.yaml", "--root", str(root), "--timeout", "2"])
    assert code == 0, capsys.readouterr().out
    capsys.readouterr()
    png = root / "docs/manual/img/Test/첫째 화면_v0.1.png"
    assert png.is_file()

    from checker import export  # 갱신된 작업본을 pptx 산출이 읽는다(그림 경로·번호 설명 문법이 맞다)

    code = export.main(["--spec", str(folder / "1.시험.md"), "--root", str(root)])
    out = json.loads(capsys.readouterr().out)
    assert code == 3 and out["status"] == "warning", out  # 3 = 산출됨 + 화면 확인 필요(검사 불능) 경고
    prs = Presentation(str(root / out["files"][0]))
    texts = [s.text_frame.text for sl in prs.slides for s in sl.shapes if s.has_text_frame]
    assert any("캡처가 채운 첫째 설명" in t for t in texts) and any("캡처가 채운 둘째 설명" in t for t in texts)
    assert sum(1 for sl in prs.slides for s in sl.shapes if s.shape_type == 13) >= 2  # 두 화면의 그림이 들어갔다


# ---------------------------------------------------------------- 실제 Chrome(건너뜀)

@pytest.mark.skipif(os.environ.get("HARNESS_CHROME_TEST") != "1", reason="실제 Chrome 이 필요하다(HARNESS_CHROME_TEST=1 로 켠다)")
def test_real_chrome_capture_placeholder():
    # 로컬 HTML 로 끝까지 도는 절차는 docs/status/533-manual-capture.md 에 있다. 자동 시험은 Chrome 을 띄우지 않는다.
    assert cdp_client.list_tabs("127.0.0.1", mc.cdp_client.DEFAULT_PORT)
