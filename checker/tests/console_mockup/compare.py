"""시안 기준(baseline)과 콘솔에서 잰 값을 견줘 차이 목록을 만든다. 브라우저 없이 부르는 순수 함수."""
from __future__ import annotations

from .elements import DEFAULT_TOL, ELEMENTS

SIDE_LABEL = {"x": "가로 위치", "y": "세로 위치", "w": "너비", "h": "높이", "fs": "글자 크기", "pad": "안쪽 여백(위 오른 아래 왼)", "rad": "모서리(4곳)", "bg": "배경색", "color": "글자색", "nat": "이미지 로드", "tcy": "글자 줄 세로 가운데"}


def _tol(key: str, prop: str, override: dict | None) -> float:
    base = dict(DEFAULT_TOL)
    base.update(ELEMENTS.get(key, {}).get("tol", {}))
    base.update((override or {}).get("tol", {}))
    return base[prop]


def element_diffs(key: str, expected: dict | None, actual: dict | None, override: dict | None = None, color_exceptions: dict | None = None) -> list[dict]:
    """요소 하나의 차이 목록. 시안에 없거나 안 보이면(expected 가 None) 견주지 않는다."""
    if expected is None:
        return []
    if actual is None:
        return [{"element": key, "prop": "존재", "expected": "있음", "actual": "없음(또는 안 보임)", "tol": None, "label": "요소"}]
    props = (override or {}).get("props") or ELEMENTS[key]["props"]
    out = []
    for p in props:
        if p in (override or {}).get("skip", ()) or p not in expected or p not in actual:
            continue
        if p in ("bg", "color"):  # 색은 정확히 같아야 한다
            if expected[p] != actual[p] and (p != "color" or (expected[p], actual[p]) not in (color_exceptions or {})):
                out.append({"element": key, "prop": p, "expected": expected[p], "actual": actual[p], "tol": 0, "delta": None, "label": SIDE_LABEL[p]})
            continue
        if p == "nat":  # 이미지가 실제로 떴는지(시안에서 떴으면 콘솔도 떠야 한다)
            if (expected[p] or 0) > 0 and not (actual[p] or 0) > 0:
                out.append({"element": key, "prop": p, "expected": f"naturalWidth {expected[p]}", "actual": "0(안 뜸)", "tol": 0, "delta": None, "label": SIDE_LABEL[p]})
            continue
        tol = _tol(key, p, override)
        e, a = expected[p], actual[p]
        if e is None:  # 시안에 값이 없는 항목은 견줄 기준이 없다
            continue
        if a is None:  # 시안엔 있는데 콘솔 값을 못 쟀다: 조용히 넘기지 않는다(통과도 위반도 아님)
            out.append({"element": key, "prop": p, "expected": e, "actual": None, "tol": None, "delta": None, "label": SIDE_LABEL[p],
                        "kind": "unmeasured"})
            continue
        if isinstance(e, list):
            delta = max(abs(x - y) for x, y in zip(e, a))
            bad = delta > tol
        else:
            delta = a - e
            bad = abs(delta) > tol
        if bad:
            out.append({"element": key, "prop": p, "expected": e, "actual": a, "tol": tol, "delta": delta, "label": SIDE_LABEL[p]})
    return out


def rel_y(meas: dict) -> dict:
    """세로 위치를 헤더 아래끝 기준으로 바꾼다. 맨 위 알림 띠(.ann)가 있고 없고는 상태에 따라 달라서 요소 위치를 밀기 때문이다."""
    hdr = meas.get("header")
    base = hdr["y"] + hdr["h"] if hdr else 0
    return {k: (dict(v, y=round(v["y"] - base, 1), tcy=None if v.get("tcy") is None else round(v["tcy"] - base, 1)) if isinstance(v, dict) and "y" in v and k not in ("ann", "header") else v) for k, v in meas.items()}


def screen_diffs(expected: dict, actual: dict, overrides: dict | None = None, color_exceptions: dict | None = None) -> list[dict]:
    """한 화면·한 너비의 차이 목록(요소 차이 + 가로 스크롤). 세로 위치는 헤더 아래끝 기준으로 견준다."""
    out = []
    lay = actual.get("_layout") or {}
    expected, actual = rel_y(expected), rel_y(actual)
    for key in ELEMENTS:
        ov = (overrides or {}).get(key, {})
        if ov is None or key not in actual:  # 화면에서 건너뛰기로 한 요소
            continue
        out += element_diffs(key, expected.get(key), actual.get(key), ov, color_exceptions)
    bg = lay.get("bg")
    if bg is not None and not bg["covers"]:  # 시안은 .app min-height 1000 이라 기준 없이 콘솔 쪽만 판정
        out.append({"element": "페이지", "prop": "bgcover", "expected": f"창 높이 {lay['innerH']} 끝까지", "actual": f"배경이 {bg['appBottom']}까지",
                    "tol": 0, "label": "배경 덮기"})
    if lay.get("scrollW", 0) > lay.get("clientW", 0):
        out.append({"element": "페이지", "prop": "scroll", "expected": f"가로 {lay['clientW']} 안", "actual": f"가로 {lay['scrollW']}",
                    "tol": 0, "label": "가로 스크롤"})
    return out


def fmt(screen: str, width: int, d: dict) -> str:
    where = f"{screen} {width}px {d['element']}"
    if d.get("kind") == "unmeasured":
        return f"{where}.{d['prop']} ({d['label']}): 시안 {d['expected']} / 콘솔 값을 못 쟀다(측정 못 함 - 검사 불능)"
    if d["prop"] in ("존재", "scroll", "bgcover", "nat"):
        return f"{where}: {d['label']} - 시안 {d['expected']} / 실제 {d['actual']}"
    sign = f", 차 {d['delta']:+.1f}" if isinstance(d["delta"], (int, float)) and not isinstance(d["expected"], list) else ""
    if d["prop"] in ("bg", "color"):
        return f"{where}.{d['prop']} ({d['label']}): 시안 {d['expected']} / 실제 {d['actual']}"
    return f"{where}.{d['prop']} ({d['label']}): 시안 {d['expected']} / 실제 {d['actual']}{sign} (허용 ±{d['tol']})"
