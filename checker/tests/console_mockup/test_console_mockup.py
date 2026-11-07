"""웹 콘솔 시안 대조 검사의 시험(#764).

- 브라우저 없이 도는 것: 비교 함수, 기준 파일 모양, main 에서 잰 G-09 값으로 차이를 잡아내는지.
- 브라우저가 필요한 것(선택 실행): CONSOLE_MOCKUP_CHECK=1 이고 Chrome·Edge·Chromium 이 있을 때만 돈다. 없으면 건너뛰고 이유를 보인다.
  콘솔이 시안과 다르면 실패하는 것이 정상 동작이라 기본 시험에는 넣지 않는다(화면 코드를 고치는 PR 이 직접 돌려 통과를 확인한다).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from checker.tests.console_mockup import compare
from checker.tests.console_mockup.cdp import find_browser
from checker.tests.console_mockup.elements import ELEMENTS
from checker.tests.console_mockup.measure_lib import WIDTHS

HERE = Path(__file__).resolve().parent
BASELINE = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))


def _m(x=0, y=0, w=100, h=50, fs=14, pad=(0, 0, 0, 0), rad=(0, 0, 0, 0)):
    return {"x": x, "y": y, "w": w, "h": h, "fs": fs, "pad": list(pad), "rad": list(rad), "n": 1}


def test_baseline_covers_all_mockups_in_both_widths():
    assert sorted(BASELINE["screens"]) == [f"G-{i:02d}" for i in range(1, 25)]
    for gid, entry in BASELINE["screens"].items():
        assert sorted(entry["widths"]) == sorted(str(w) for w in WIDTHS), gid
        for w, meas in entry["widths"].items():
            assert meas["_layout"]["clientW"] == int(w), (gid, w)
            assert meas["_layout"]["scrollW"] <= int(w), f"시안 {gid} 자체가 가로 스크롤({w}px)"
            assert set(meas) - {"_layout"} <= set(ELEMENTS), (gid, set(meas) - set(ELEMENTS))


def test_within_tolerance_passes_and_outside_fails():
    base = {"header": _m(w=1440), "_layout": {"clientW": 1440, "scrollW": 1440, "docH": 900}}
    ok = {"header": _m(w=1441.5), "_layout": base["_layout"]}
    bad = {"header": _m(w=1447), "_layout": base["_layout"]}
    only = {"header": ELEMENTS["header"]}
    assert compare.screen_diffs(base, ok) == []
    diffs = compare.screen_diffs(base, bad)
    assert [(d["element"], d["prop"]) for d in diffs] == [("header", "w")]
    assert diffs[0]["expected"] == 1440 and diffs[0]["actual"] == 1447 and only


def test_per_element_tolerance_override():
    base = {"header": _m(w=1440), "_layout": {"clientW": 1440, "scrollW": 1440, "docH": 900}}
    bad = {"header": _m(w=1447), "_layout": base["_layout"]}
    assert compare.screen_diffs(base, bad, {"header": {"tol": {"w": 10}}}) == []


def test_missing_element_is_reported_but_hidden_in_mockup_is_not():
    lay = {"clientW": 1440, "scrollW": 1440, "docH": 900}
    assert compare.screen_diffs({"tile": _m(), "_layout": lay}, {"tile": None, "_layout": lay})[0]["prop"] == "존재"
    assert compare.screen_diffs({"tile": None, "_layout": lay}, {"tile": _m(), "_layout": lay}) == []
    assert compare.screen_diffs({"tile": _m(), "_layout": lay}, {"tile": None, "_layout": lay}, {"tile": None}) == []  # 화면에서 건너뜀


def test_horizontal_scroll_fails():
    lay = {"clientW": 1440, "scrollW": 1500, "docH": 900}
    diffs = compare.screen_diffs({"_layout": {"clientW": 1440, "scrollW": 1440, "docH": 900}}, {"_layout": lay})
    assert [d["prop"] for d in diffs] == ["scroll"]


def test_vertical_position_ignores_announcement_bar():
    """맨 위 띠(.ann)가 있고 없고로 모든 y 가 밀려도 같은 배치로 본다."""
    exp = {"header": _m(y=0, h=63), "h1": _m(y=84), "_layout": {"clientW": 1440, "scrollW": 1440, "docH": 900}}
    act = {"ann": _m(y=0, h=36), "header": _m(y=36, h=63), "h1": _m(y=120), "_layout": exp["_layout"]}
    assert [d for d in compare.screen_diffs(exp, act) if d["prop"] == "y"] == []


def test_radius_and_padding_lists_compare_worst_corner():
    lay = {"clientW": 1440, "scrollW": 1440, "docH": 900}
    exp = {"tile": _m(pad=(14, 16, 14, 16), rad=(20, 20, 20, 20)), "_layout": lay}
    act = {"tile": _m(pad=(14, 16, 14, 24), rad=(20, 20, 20, 20)), "_layout": lay}
    d = compare.screen_diffs(exp, act)
    assert [(x["prop"], x["delta"]) for x in d] == [("pad", 8)]


@pytest.mark.parametrize("width", WIDTHS)
def test_g09_difference_on_main_before_762_763_is_caught(width):
    """#762·#763 을 고치기 전 main 에서 잰 G-09 값(fixtures)으로: 오른쪽 칸 폭, 대화 판 폭, 할 일 카드 높이를 잡아낸다."""
    got = json.loads((HERE / "fixtures" / "g09_before_762_763.json").read_text(encoding="utf-8"))[str(width)]
    diffs = compare.screen_diffs(BASELINE["screens"]["G-09"]["widths"][str(width)], got)
    found = {(d["element"], d["prop"]) for d in diffs}
    assert {("right", "w"), ("light", "w"), ("ask", "h"), ("paper", "w")} <= found
    right = next(d for d in diffs if (d["element"], d["prop"]) == ("right", "w"))
    assert round(right["expected"]) == 300 and round(right["actual"]) == 320
    ask = next(d for d in diffs if (d["element"], d["prop"]) == ("ask", "h"))
    assert round(ask["expected"]) == 158 and 230 <= ask["actual"] <= 231
    assert "G-09" in compare.fmt("G-09", width, right) and "right" in compare.fmt("G-09", width, right)


def test_color_must_match_exactly_unless_skipped():
    lay = {"clientW": 1440, "scrollW": 1440, "docH": 900}
    exp = {"light": dict(_m(), bg="rgb(237, 247, 245)", color="rgb(19, 35, 34)"), "_layout": lay}
    act = {"light": dict(_m(), bg="rgb(237, 247, 246)", color="rgb(19, 35, 34)"), "_layout": lay}
    d = compare.screen_diffs(exp, act)
    assert [(x["element"], x["prop"]) for x in d] == [("light", "bg")]
    assert "시안 rgb(237, 247, 245) / 실제 rgb(237, 247, 246)" in compare.fmt("G-09", 1440, d[0])
    assert compare.screen_diffs(exp, act, {"light": {"skip": ("bg",)}}) == []
    # 글자색 예외는 값 쌍이 같을 때만, 배경색에는 적용되지 않는다
    t = {"light": dict(_m(), bg="a", color="rgb(243, 250, 248)"), "_layout": lay}
    e = {"light": dict(_m(), bg="a", color="rgb(255, 255, 255)"), "_layout": lay}
    pair = {("rgb(255, 255, 255)", "rgb(243, 250, 248)"): "이유"}
    assert compare.screen_diffs(e, t, None, pair) == []
    assert compare.screen_diffs(e, t, None, {("x", "y"): "이유"})[0]["prop"] == "color"
    t["light"]["bg"] = "b"
    assert [d["prop"] for d in compare.screen_diffs(e, t, None, pair)] == ["bg"]


def test_logo_must_load_and_match_size():
    lay = {"clientW": 1440, "scrollW": 1440, "docH": 900}
    exp = {"logo": dict(_m(x=28, y=22, w=110, h=18), nat=860), "_layout": lay}
    broken = {"logo": dict(_m(x=28, y=22, w=0.1, h=18), nat=0), "_layout": lay}
    props = {x["prop"] for x in compare.screen_diffs(exp, broken)}
    assert {"nat", "w"} <= props
    assert compare.screen_diffs(exp, {"logo": dict(_m(x=28, y=22, w=110, h=18), nat=860), "_layout": lay}) == []


def test_background_must_cover_window_height():
    exp = {"_layout": {"clientW": 1440, "scrollW": 1440, "docH": 1000}}
    short = {"_layout": {"clientW": 1440, "scrollW": 1440, "docH": 700, "innerH": 900, "bg": {"canvas": False, "appBottom": 700, "covers": False}}}
    ok = {"_layout": {"clientW": 1440, "scrollW": 1440, "docH": 900, "innerH": 900, "bg": {"canvas": False, "appBottom": 900, "covers": True}}}
    assert [d["prop"] for d in compare.screen_diffs(exp, short)] == ["bgcover"]
    assert compare.screen_diffs(exp, ok) == []


def test_baseline_has_real_logo_and_colors():
    g = BASELINE["screens"]["G-09"]["widths"]["1440"]
    assert g["logo"]["nat"] == 860 and g["logo"]["w"] > 100  # 시안의 진짜 로고(860x141)가 떠서 잰 값
    assert g["page"]["bg"] == "rgb(19, 35, 34)" and g["pillNow"]["bg"] == "rgb(61, 220, 145)"


def test_unmeasured_console_value_is_reported_not_skipped():
    lay = {"clientW": 1440, "scrollW": 1440, "docH": 900}
    exp = {"eyebrow": dict(_m(), tcy=74.5), "_layout": lay}
    act = {"eyebrow": dict(_m(), tcy=None), "_layout": lay}
    d = compare.screen_diffs(exp, act)
    assert [(x["prop"], x.get("kind")) for x in d] == [("tcy", "unmeasured")]
    assert "측정 못 함" in compare.fmt("G-04", 1440, d[0])
    assert compare.screen_diffs({"eyebrow": dict(_m(), tcy=None), "_layout": lay}, act) == []  # 시안에 값이 없으면 견줄 기준이 없다


# ---- 검사 불능 경로(종료 코드 2)와 안전장치
class _FakeHealth:
    """/api/health 에 200 을 주는 남의 서버 흉내."""

    def __enter__(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *a):
                pass

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self.srv.server_address[1]

    def __exit__(self, *a):
        self.srv.shutdown()


@pytest.fixture
def lib(monkeypatch, tmp_path):
    from checker.tests.console_mockup.fake_console import lib as l

    monkeypatch.setattr(l, "PIDFILE", tmp_path / "serve.pid")
    monkeypatch.setattr(l, "TOKEN_FILE", tmp_path / "serve.token")
    return l


def test_port_in_use_by_foreign_process_is_unavailable_exit_2(lib, monkeypatch, capsys):
    from checker.tests.console_mockup import check_console

    class FakeBrowser:
        def __init__(self, exe):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with _FakeHealth() as port:
        monkeypatch.setattr(lib, "PORT", port)
        monkeypatch.setattr(check_console, "find_browser", lambda: "fake-browser")
        monkeypatch.setattr(check_console, "Browser", FakeBrowser)
        with pytest.raises(lib.ConsoleUnavailable):
            lib.start_server()
        assert check_console.run(["G-09"]) == 2
    assert "검사 불능" in capsys.readouterr().out


def test_protected_ports_are_refused(lib, monkeypatch):
    for port in (4873, 4874):
        monkeypatch.setattr(lib, "PORT", port)
        with pytest.raises(lib.ConsoleUnavailable):
            lib.stop_server()
        with pytest.raises(lib.ConsoleUnavailable):
            lib.start_server()


def test_stop_server_never_kills_a_pid_that_is_not_ours(lib, monkeypatch):
    import os

    with _FakeHealth() as port:
        monkeypatch.setattr(lib, "PORT", port)
        lib.PIDFILE.write_text(f"{os.getpid()}\n{port}\n")  # 이 시험 프로세스의 pid: 명령줄에 우리 토큰이 없다
        lib.TOKEN_FILE.write_text("not-in-any-cmdline")
        with pytest.raises(lib.ConsoleUnavailable):
            lib.stop_server()
    assert lib._our_pid() is None


def test_browser_start_failure_cleans_up_profile():
    import sys

    from checker.tests.console_mockup.cdp import Browser

    br = Browser(sys.executable)  # 브라우저 옵션을 못 알아듣고 바로 종료하는 실행 파일
    with pytest.raises(RuntimeError):
        br.__enter__()
    assert not br.profile.exists()


def test_extract_baseline_without_browser_exits_2(monkeypatch, tmp_path, capsys):
    from checker.tests.console_mockup import extract_baseline

    (tmp_path / "G-01.dc.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(extract_baseline, "find_browser", lambda: None)
    assert extract_baseline.main([str(tmp_path)]) == 2
    assert "검사 불능" in capsys.readouterr().out


# ---- 선택 실행: 진짜 브라우저로 콘솔을 띄워 대조(콘솔이 시안과 다르면 실패)
@pytest.mark.skipif(os.environ.get("CONSOLE_MOCKUP_CHECK") != "1", reason="선택 실행: CONSOLE_MOCKUP_CHECK=1 로 켠다(화면 코드를 고친 PR 이 직접 돌린다)")
@pytest.mark.skipif(find_browser() is None, reason="헤드리스 브라우저(Chrome·Edge·Chromium)를 못 찾음 - CONSOLE_CHECK_BROWSER 로 알려 준다")
def test_console_matches_mockups(capsys):
    from checker.tests.console_mockup import check_console

    code = check_console.run(None)
    out = capsys.readouterr().out
    assert code == 0, out
