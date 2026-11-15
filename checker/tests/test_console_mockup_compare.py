"""시안 치수 검사의 '나중 시안에서 기대값 가져오기'(#993). 브라우저 없이 순수 함수만 본다."""
from checker.tests.console_mockup.compare import borrow_later_mockup, screen_diffs
from checker.tests.console_mockup.screen_config import SCREEN_CONFIG


def _el(**kw):
    base = {"x": 268, "y": 165.5, "w": 277, "h": 79, "tcy": 187, "fs": 14, "bg": "rgb(14, 26, 25)", "color": "rgb(255, 255, 255)",
            "nat": None, "pad": [14, 16, 14, 16], "rad": [20, 20, 20, 20], "n": 4}
    base.update(kw)
    return base


HEADER = {"x": 0, "y": 0, "w": 1440, "h": 63, "tcy": 30, "fs": 14, "bg": "rgba(0, 0, 0, 0)", "color": "rgb(255, 255, 255)",
          "nat": None, "pad": [0, 0, 0, 0], "rad": [0, 0, 0, 0], "n": 1}
OLD = {"header": HEADER, "tile": _el(), "light": _el(y=352, h=300, tcy=380, w=1144)}
LATER = {"header": HEADER, "tile": _el(w=219.2, h=111.5, n=5), "light": _el(y=388.5, h=300, tcy=410, w=1144)}
SCREENS = {"G-11": {"widths": {"1440": OLD}}, "G-24": {"widths": {"1440": LATER}}}
OV = {"tile": {"from": "G-24"}, "light": {"below": {"screen": "G-24", "element": "tile"}}}
# 콘솔은 나중 시안(다섯 칸)대로 그려져 있다: 칸이 높아진 만큼 아래 판이 내려가 있다.
CONSOLE = {"header": HEADER, "tile": _el(w=219.2, h=111.5, n=5), "light": _el(y=384.5, h=300, tcy=412.5, w=1144)}


def test_without_borrowing_the_five_tile_home_fails_the_old_mockup():
    fails = screen_diffs(OLD, CONSOLE, {})
    assert {(d["element"], d["prop"]) for d in fails} >= {("tile", "w"), ("tile", "h"), ("light", "y")}


def test_borrowing_takes_tile_from_later_mockup_and_moves_the_panel_below_by_the_growth():
    exp = borrow_later_mockup(OLD, SCREENS, "1440", OV)
    assert exp["tile"] == LATER["tile"]
    assert exp["light"]["y"] == 352 + (111.5 - 79) and exp["light"]["tcy"] == 380 + (111.5 - 79)
    assert exp["light"]["w"] == OLD["light"]["w"]  # 위치만 내린다(크기는 앞 시안 그대로)
    assert OLD["tile"]["h"] == 79 and OLD["light"]["y"] == 352  # 원본 기준은 바꾸지 않는다
    assert screen_diffs(exp, CONSOLE, OV) == []


def test_borrowing_still_fails_when_console_differs_from_the_later_mockup():
    exp = borrow_later_mockup(OLD, SCREENS, "1440", OV)
    wrong = dict(CONSOLE, tile=_el(w=219.2, h=130, n=5))
    assert ("tile", "h") in {(d["element"], d["prop"]) for d in screen_diffs(exp, wrong, OV)}


def test_no_override_keeps_expected_as_is():
    assert borrow_later_mockup(OLD, SCREENS, "1440", {"ask": {"console": ".call"}, "nav": None}) == OLD


def test_g11_config_borrows_home_tiles_from_g24_and_checks_the_team_tile():
    cfg = SCREEN_CONFIG["G-11"]
    assert cfg["elements"]["tile"] == {"from": "G-24"}
    assert cfg["elements"]["light"] == {"below": {"screen": "G-24", "element": "tile"}}
    assert any(e["text"] == "아직 안 풀린 문제" for e in cfg["expect"])
