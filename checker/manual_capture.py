"""사용자 매뉴얼 화면 자동 캡처(#533).

사람이 로그인해 둔 전용 Chrome(디버깅 포트 `127.0.0.1:9222`)의 탭에 붙어, 찍을 화면 목록(`*.capture.yaml`)대로 화면마다
PNG(1600x900)를 찍고, 화면에 보이는 이름으로 요소 위치를 찾아 **빨간 네모와 번호를 그림에 직접 그린다.** 찍은 그림 경로와 번호 설명은
매뉴얼 작업본(`/harness:manual`)의 `#### 그림`·`#### 번호 설명` 에 채운다.

    python -P -m checker.manual_capture --list docs/manual/<LoB>/<번호>.<업무 제목>.capture.yaml --root <저장소 루트> [--check]

찍을 화면 목록(작업본 `docs/manual/<LoB>/<번호>.<업무 제목>.md` 옆, 같은 이름에 `.capture.yaml`)

    화면:
      - 이름: 조회 조건                      # 작업본 `### <양식> · 본문 · 조회 조건` 소절의 화면 이름과 같게
        앱: "#ProductionPlanBoard-display"   # 선택. 테넌트 주소(env/manual-capture.yaml) 뒤에 붙는 Launchpad 해시
        준비:                                # 선택. 필터 값 넣기·드롭다운 고르기·버튼 누르기·팝업 열기(여러 화면을 거치는 흐름은 범위 밖)
          - {입력: 플랜트, 값: "1010"}       # 앱이 기억한 값이 이미 같으면 넘어가고, 다른 값이면 지우고 넣는다
          - {선택: 생산방식, 값: "반복제조"}  # Select·ComboBox 에서 보이는 항목 글자가 값과 같은 것을 고른다(없으면 검사 불능)
          - {누르기: 이동}
          - {팝업: 그루핑}                   # 선택. 그 버튼을 눌러 대화상자가 정확히 하나 떠야 한다(안 뜨거나 오류·경고 창이면 검사 불능). 마지막 단계 하나만
          - {팝업: 백로그상태, 행: 3}         # 버튼 대신 그 열의 보이는 본문 3번째 행 칸(없으면 아이콘)을 더블클릭해 연다(#673). 데이터를 바꾸지 않는 칸에만 쓴다
        배율: 0.9                           # 선택(0.5~1.0). 넓은 표를 한 화면에 담으려 이 화면만 축소해 찍는다(그림은 그대로 1600x900)
        표시:                               # 필수. 번호는 이 목록 순서다
          - {종류: 필터, 이름: 플랜트, 설명: 생산 플랜트를 고른다}
          - {종류: 열, 이름: 상태, index: 2, 설명: 오더 상태를 본다}   # index 는 같은 이름이 여럿일 때 사람이 고른다(1부터, 읽는 순서)

`팝업` 이 있는 화면은 표시 요소를 **그 팝업 안에서만** 찾고, 찍기 직전에도 그 팝업 하나만 허용한다. 팝업의 확인·저장 버튼은 누르지 않는다.

넓은 표(#657): 같은 화면의 `열` 표시가 둘 이상이면 열마다 따로 넘기지 않고, 그 열들이 다 보이는 가로 스크롤 위치 하나로 한 번에 넘긴다
(열이 하나거나 표의 스크롤 요소를 못 찾으면 열마다 넘긴다). 열들의 가로 범위가 표의 보이는 폭보다 넓으면 찍지 않고 검사 불능으로 알리며
**화면을 나눌 방법**(왼쪽부터 들어가는 만큼 묶음)과 **필요 `배율`** 을 사유에 적는다. `배율` 은 찍기 전에 화면 크기를 1/배율 로 넓히고
(`setDeviceMetricsOverride` 의 width·height 를 키우고 deviceScaleFactor=배율) 다음 화면 전에 원래대로 되돌린다.

종류는 필터(라벨+입력 칸)·버튼·열(머리글부터 표 아래 끝)·그 밖(그 글자가 든 요소). 테넌트 주소는 `env/manual-capture.yaml` 의
`테넌트:`(없으면 `--base-url`). `https://호스트/경로` 만이고, 쿼리는 `?sap-client=100`(숫자 3자리)·`sap-language=KO`(영문 2자리)만 붙일 수 있다
(`https://호스트/ui?sap-client=100` + 앱 `#App-display` → `…?sap-client=100#App-display`). 그 밖의 쿼리 키·`#`·계정이 있으면 거부(시험용 http://127.0.0.1·file:// 은 `--allow-local-test` 로만).
비밀값(토큰·비밀번호)은 어디에도 두지 않는다 — 로그인은 사람이 전용 Chrome 에서 한다. 화면마다 강제로 다시 열고, 준비된 탭의 출처가 테넌트 출처와 다르면 검사 불능이다.

판정(추측해서 그리지 않는다)
- 0개: `not_found`. 2개 이상: `ambiguous` — 스크립트가 고르지 않고 목록의 `index` 로 사람이 정한다.
- 찾지 못한 요소가 하나라도 있는 화면은 `<화면 이름>_미완_v<판>.png` 로 찾은 것만 그려 따로 저장하고, 작업본은 고치지 않는다.
- 페이지가 준비되지 않거나(시간 초과) 브라우저에 붙지 못하면 검사 불능(종료 2)이다. 통과나 위반으로 뭉개지 않는다.

그리기는 페이지에 덮개(overlay)를 얹어 찍는 방식이라 Pillow 같은 이미지 라이브러리가 필요 없다. 덮개는 찍은 뒤 지운다.
종료코드: 0 모두 찍음 / 1 찾지 못한(또는 여럿인) 요소가 있다 / 2 목록·작업본을 읽지 못함·브라우저 불능.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from checker import cdp_client
from checker.cdp_client import CdpError
from checker.manual_capture_js import LIB_JS, READY_JS

WIDTH, HEIGHT = 1600, 900
RED = "#e60000"
BOX_PAD = 3  # 요소 둘레 여백(px)
BOX_BORDER = 3
BADGE_R = 13
MAX_MARKS = 99
KINDS = ("필터", "버튼", "열", "그 밖")
SCREEN_KEYS = {"이름", "앱", "준비", "표시", "배율"}
MIN_SCALE = 0.5
MARK_KEYS = {"종류", "이름", "index", "설명"}
STEP_KEYS = {"입력", "값", "누르기", "선택", "팝업", "행"}
ENV_PATH = "env/manual-capture.yaml"
LIST_SUFFIX = ".capture.yaml"
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class ListError(ValueError):
    """찍을 화면 목록·환경 파일이 틀렸다."""


# ---------------------------------------------------------------- 화면 목록

@dataclass(frozen=True)
class Mark:
    kind: str
    name: str
    text: str
    index: int | None = None


@dataclass(frozen=True)
class Step:
    action: str  # 입력 | 선택 | 누르기 | 팝업
    name: str
    value: str | None = None
    row: int | None = None  # 팝업 단계만: 이 열의 보이는 본문 N번째 행 칸을 더블클릭해 연다(없으면 버튼을 누른다)


@dataclass(frozen=True)
class Screen:
    name: str
    app: str
    steps: tuple[Step, ...]
    marks: tuple[Mark, ...]
    scale: float | None = None  # 배율(0.5~1.0). 있으면 찍기 전에 CSS 화면을 1/배율 로 넓히고 그림 크기는 그대로 둔다

    @property
    def popup(self) -> bool:
        """마지막 준비 단계가 `팝업` 이면 표시 요소는 그 팝업 안에서 찾는다."""
        return bool(self.steps) and self.steps[-1].action == "팝업"


def _text(v: object, where: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ListError(f"{where}: 비어 있지 않은 글이어야 한다(숫자는 따옴표로 감싼다): {v!r}")
    return v.strip()


def parse_screens(data: object) -> list[Screen]:
    """목록 yaml(읽은 값)을 검증해 화면 목록으로 만든다. 틀리면 ListError 에 모든 문제를 모아 알린다."""
    if not isinstance(data, dict) or set(data) != {"화면"} or not isinstance(data["화면"], list) or not data["화면"]:
        raise ListError("최상위는 `화면:` 목록 하나여야 한다(비어 있으면 안 된다)")
    problems: list[str] = []
    screens: list[Screen] = []
    seen: set[str] = set()
    for i, raw in enumerate(data["화면"], 1):
        where = f"화면 {i}"
        try:
            if not isinstance(raw, dict):
                raise ListError(f"{where}: 항목이 아니다")
            extra = set(raw) - SCREEN_KEYS
            if extra:
                raise ListError(f"{where}: 모르는 키 {sorted(extra)} (쓸 수 있는 키: {sorted(SCREEN_KEYS)})")
            name = _text(raw.get("이름"), f"{where} 이름")
            where = f"화면 {name!r}"
            if _BAD_NAME.search(name) or name in {".", ".."} or name != name.rstrip(". "):
                raise ListError(f"{where}: 그림 파일 이름이 될 수 없는 문자가 있다(\\ / : * ? \" < > | 제어 문자, 끝의 점·공백)")
            if name in seen:
                raise ListError(f"{where}: 이름이 겹친다")
            seen.add(name)
            app = raw.get("앱", "")
            if not isinstance(app, str) or (app and not app.startswith("#")):
                raise ListError(f"{where}: `앱` 은 `#` 로 시작하는 Launchpad 해시여야 한다(테넌트 주소는 {ENV_PATH}): {app!r}")
            steps = tuple(_parse_step(s, f"{where} 준비 {j}") for j, s in enumerate(raw.get("준비") or [], 1))
            pops = [j for j, s in enumerate(steps) if s.action == "팝업"]
            if pops and (len(pops) > 1 or pops[0] != len(steps) - 1):
                raise ListError(f"{where}: `팝업` 은 한 화면에 하나이고 마지막 준비 단계여야 한다")
            if not isinstance(raw.get("표시"), list) or not raw["표시"]:
                raise ListError(f"{where}: `표시` 목록이 필요하다")
            if len(raw["표시"]) > MAX_MARKS:
                raise ListError(f"{where}: 표시는 {MAX_MARKS}개까지다")
            marks = tuple(_parse_mark(m, f"{where} 표시 {j}") for j, m in enumerate(raw["표시"], 1))
            scale = raw.get("배율")
            if scale is not None:
                if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not MIN_SCALE <= scale <= 1.0:
                    raise ListError(f"{where}: `배율` 은 {MIN_SCALE}~1.0 의 숫자여야 한다(예: 0.9): {scale!r}")
                scale = float(scale)
            screens.append(Screen(name, app, steps, marks, scale))
        except ListError as e:
            problems.append(str(e))
    if problems:
        raise ListError("\n".join(problems))
    return screens


def _parse_step(raw: object, where: str) -> Step:
    if not isinstance(raw, dict) or set(raw) - STEP_KEYS:
        raise ListError(f"{where}: `{{입력: 이름, 값: 값}}`·`{{선택: 이름, 값: 항목 글자}}` `{{누르기: 이름}}`·`{{팝업: 버튼 이름}}` 이어야 한다")
    acts = [k for k in ("입력", "선택", "누르기", "팝업") if k in raw]
    if len(acts) != 1:
        raise ListError(f"{where}: `입력`·`선택`·`누르기`·`팝업` 중 하나만 쓴다")
    action = acts[0]
    if "행" in raw and action != "팝업":
        raise ListError(f"{where}: `행` 은 `팝업` 단계에서만 쓴다")
    if action in ("누르기", "팝업"):
        if "값" in raw:
            raise ListError(f"{where}: `{action}` 에는 `값` 을 쓰지 않는다")
        row = raw.get("행")
        if "행" in raw and (not isinstance(row, int) or isinstance(row, bool) or row < 1):
            raise ListError(f"{where}: `행` 은 1 이상의 정수여야 한다: {row!r}")
        return Step(action, _text(raw[action], f"{where} {action}"), None, row)
    if "값" not in raw:
        raise ListError(f"{where}: `{action}` 에는 `값` 이 필요하다")
    value = raw["값"]
    if not isinstance(value, str):
        raise ListError(f"{where}: `값` 은 따옴표로 감싼 글이어야 한다(`1010` 은 숫자가 되고 `01` 은 앞의 0 이 사라진다): {value!r}")
    if action == "선택":
        value = _text(value, f"{where} 값")
    return Step(action, _text(raw[action], f"{where} {action}"), value)


def _parse_mark(raw: object, where: str) -> Mark:
    if not isinstance(raw, dict):
        raise ListError(f"{where}: 항목이 아니다")
    extra = set(raw) - MARK_KEYS
    if extra:
        raise ListError(f"{where}: 모르는 키 {sorted(extra)}")
    kind = raw.get("종류")
    if kind not in KINDS:
        raise ListError(f"{where}: `종류` 는 {'·'.join(KINDS)} 중 하나여야 한다: {kind!r}")
    index = raw.get("index")
    if index is not None and (not isinstance(index, int) or isinstance(index, bool) or index < 1):
        raise ListError(f"{where}: `index` 는 1 이상의 정수여야 한다: {index!r}")
    text = _text(raw.get("설명"), f"{where} 설명")
    if "\n" in text:
        raise ListError(f"{where}: 설명은 한 줄이어야 한다")
    return Mark(kind, _text(raw.get("이름"), f"{where} 이름"), text, index)


def load_screens(path: Path) -> list[Screen]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ListError(f"찍을 화면 목록을 읽지 못했다({path}): {e}") from e
    return parse_screens(data)


def load_env(root: Path) -> dict:
    """`env/manual-capture.yaml` 의 `테넌트`(주소)·`포트`(선택). 파일이 없으면 빈 값."""
    p = root / ENV_PATH
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ListError(f"{ENV_PATH} 를 읽지 못했다: {e}") from e
    if not isinstance(data, dict) or set(data) - {"테넌트", "포트"}:
        raise ListError(f"{ENV_PATH} 에는 `테넌트:` 와 `포트:` 만 쓴다")
    return data


QUERY_ALLOWED = {
    "sap-client": re.compile(r"[0-9]{3}"),
    "sap-language": re.compile(r"[A-Za-z]{2}"),
}


def _check_query(query: str) -> None:
    """테넌트 주소 쿼리 검증: 허용 키(sap-client 숫자 3자리·sap-language 영문 2자리)만, 키 중복 없이."""
    seen: set[str] = set()
    for pair in query.split("&"):
        key, eq, value = pair.partition("=")
        if not eq or key not in QUERY_ALLOWED:
            raise ListError(f"테넌트 주소 쿼리는 {'·'.join(QUERY_ALLOWED)} 만 쓸 수 있다 — 토큰이 섞일 수 있어 거부한다: {pair!r}")
        if key in seen:
            raise ListError(f"테넌트 주소 쿼리에 `{key}` 가 두 번 있다")
        seen.add(key)
        if not QUERY_ALLOWED[key].fullmatch(value):
            hint = "숫자 3자리" if key == "sap-client" else "영문 2자리"
            raise ListError(f"테넌트 주소 쿼리 `{key}` 값은 {hint}여야 한다: {value!r}")


def check_base_url(url: object, allow_local: bool = False) -> str:
    """테넌트 주소 검증: `https://호스트[/경로][?sap-client=100&sap-language=KO]` 만. 쿼리는 허용 키(`QUERY_ALLOWED`)만 받고,
    그 밖의 키·값 모양·중복 키·프래그먼트(`#`)·계정·비밀번호는 거부한다(토큰이 섞일 수 있다).

    시험용 `http://127.0.0.1…`·`file://…` 은 `allow_local`(--allow-local-test)일 때만 허용한다.
    """
    if not isinstance(url, str) or not url.strip():
        raise ListError(f"테넌트 주소가 없다({ENV_PATH} 의 `테넌트:` 또는 --base-url)")
    s = url.strip()
    if "#" in s:
        raise ListError("테넌트 주소에 `#` 가 있다 — 토큰이 섞일 수 있어 거부한다(앱 해시는 화면 목록의 `앱` 에 적는다)")
    parts = urlsplit(s)
    if "?" in s:
        _check_query(parts.query)
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ListError("테넌트 주소에 계정·비밀번호를 넣지 않는다(로그인은 전용 Chrome 에서 사람이 한다)")
    if parts.scheme == "https" and parts.hostname:
        return s
    if allow_local and ((parts.scheme == "http" and parts.hostname == cdp_client.LOOPBACK) or parts.scheme == "file"):
        return s
    raise ListError(f"테넌트 주소는 https:// 여야 한다(시험용 http://127.0.0.1·file:// 은 --allow-local-test 로만): {url!r}")


# ---------------------------------------------------------------- 판정·그리기(순수 함수)

Rect = dict  # {"x","y","w","h"}


def _iou(a: Rect, b: Rect) -> float:
    ix = max(0.0, min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"]))
    inter = ix * iy
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def dedupe_rects(rects: list[Rect], threshold: float = 0.9) -> list[Rect]:
    """같은 요소를 감싼 겹친 후보(바깥 div 와 안쪽 button 등)를 하나로 줄인다."""
    out: list[Rect] = []
    for r in rects:
        if not any(_iou(r, o) >= threshold for o in out):
            out.append(r)
    return out


def reading_order(rects: list[Rect]) -> list[Rect]:
    return sorted(rects, key=lambda r: (r["y"] // 10, r["x"]))  # 페이지 스크립트의 정렬(Math.floor(y/10), x)과 같다


@dataclass
class Verdict:
    status: str  # found | not_found | ambiguous
    rect: Rect | None = None
    count: int = 0
    reason: str = ""


def judge(rects: list[Rect], index: int | None = None, *, no_input: int = 0) -> Verdict:
    """후보로 판정한다. 후보는 화면 밖·잘린 것까지 **전부**이고 각 후보의 `visible`(없으면 True)로 보이는지 안다.

    0개 not_found / 1개가 보이면 found(1개인데 안 보이면 not_found) / 2개 이상이면 보이는 것이 하나뿐이어도 ambiguous
    (화면 밖에 같은 이름이 더 있다). `index` 가 있으면 화면 밖을 포함한 전체 읽는 순서의 그 번째이고, 그것이 안 보이면 not_found.
    """
    cands = reading_order(dedupe_rects(rects))
    if not cands:
        if no_input:
            return Verdict("not_found", reason="라벨은 있으나 입력 칸을 묶지 못했다")
        return Verdict("not_found", reason="화면에서 그 이름을 찾지 못했다")
    if index is not None:
        if index > len(cands):
            return Verdict("not_found", count=len(cands), reason=f"index {index} 번째가 없다(후보 {len(cands)}개)")
        c = cands[index - 1]
        if not c.get("visible", True):
            return Verdict("not_found", count=len(cands), reason=f"index {index} 번째가 화면 밖이거나 잘려 일부만 보인다(가로 스크롤 밖 열 포함)")
        return Verdict("found", c, len(cands))
    if len(cands) > 1:
        shown = sum(1 for c in cands if c.get("visible", True))
        return Verdict("ambiguous", count=len(cands), reason=(
            f"{len(cands)}개가 같은 이름이다(화면에 보이는 것 {shown}개, 화면 밖 {len(cands) - shown}개). "
            f"목록에 index(1~{len(cands)}, 화면 밖 포함 위에서 아래·왼쪽에서 오른쪽 순)를 적는다"))
    if not cands[0].get("visible", True):
        return Verdict("not_found", count=1, reason="화면 밖이거나 잘려 일부만 보인다(가로 스크롤 밖 열 포함)")
    return Verdict("found", cands[0], 1)


@dataclass
class MarkPlan:
    n: int
    box: Rect
    badge: dict  # {"cx","cy","r"}
    pushed: bool = False  # 바깥 모서리 넷 다 그림 밖이거나 다른 배지와 겹쳐 안쪽으로 밀었다


def plan_marks(items: list[tuple[int, Rect]], width: int = WIDTH, height: int = HEIGHT,
               pad: int = BOX_PAD, r: int = BADGE_R) -> list[MarkPlan]:
    """번호와 요소 영역으로 네모(테두리)와 번호 배지 위치를 정한다.

    네모는 요소 둘레에 `pad` 만큼 여유를 두고 그림 안으로 자른다. 배지는 네모 **바깥** 모서리에 둔다(왼쪽 위 → 오른쪽 위 →
    왼쪽 아래 → 오른쪽 아래 순으로 시도, 그림 안에 다 들어가고 앞 배지와 안 겹치는 첫 자리). 어디도 안 되면 왼쪽 위 자리를
    그림 안쪽으로 민다(`pushed`). 번호는 받은 번호 그대로다.
    """
    k = r * 0.75
    plans: list[MarkPlan] = []
    for n, rect in items:
        x0 = max(0.0, rect["x"] - pad)
        y0 = max(0.0, rect["y"] - pad)
        x1 = min(float(width), rect["x"] + rect["w"] + pad)
        y1 = min(float(height), rect["y"] + rect["h"] + pad)
        corners = [(x0 - k, y0 - k), (x1 + k, y0 - k), (x0 - k, y1 + k), (x1 + k, y1 + k)]
        chosen = None
        for cx, cy in corners:
            fits = r <= cx <= width - r and r <= cy <= height - r
            free = all((cx - p.badge["cx"]) ** 2 + (cy - p.badge["cy"]) ** 2 >= (2 * r + 2) ** 2 for p in plans)
            if fits and free:
                chosen = (cx, cy, False)
                break
        if chosen is None:
            cx, cy = corners[0]
            chosen = (min(max(cx, r), width - r), min(max(cy, r), height - r), True)
        plans.append(MarkPlan(n, {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0},
                              {"cx": round(chosen[0], 1), "cy": round(chosen[1], 1), "r": r}, chosen[2]))
    return plans


# ---------------------------------------------------------------- 작업본

_HEAD3 = re.compile(r"^###\s+(.*?)\s*$")
_HEAD_ANY = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_FENCE = re.compile(r"(`{3,}|~{3,})(.*)$")
_NUM_ITEM = re.compile(r"^\s*\d+[.)]\s+(.*\S)\s*$")


def _fence_mask(lines: list[str]) -> list[bool]:
    """줄마다 코드펜스(``` 또는 ~~~) 안인지(여는·닫는 줄 포함). 그 안의 `#` 줄은 제목이 아니다."""
    mask: list[bool] = []
    opened: tuple[str, int] | None = None
    for line in lines:
        s = line.rstrip("\r")
        m = _FENCE.match(s.lstrip(" ")) if len(s) - len(s.lstrip(" ")) <= 3 else None
        if opened is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                opened = (m.group(1)[0], len(m.group(1)))
                mask.append(True)
            else:
                mask.append(False)
        else:
            mask.append(True)
            if m and m.group(1)[0] == opened[0] and len(m.group(1)) >= opened[1] and not m.group(2).strip():
                opened = None
    return mask


def _heading(lines: list[str], mask: list[bool], i: int) -> tuple[int, str] | None:
    """코드펜스 밖의 제목 줄이면 (수준, 글)."""
    if mask[i]:
        return None
    m = _HEAD_ANY.match(lines[i].rstrip("\r"))
    return (len(m.group(1)), m.group(2)) if m else None


def read_version(text: str) -> str | None:
    """작업본 머리(첫 `##` 앞)의 `버전: 0.1`."""
    for line in text.splitlines():
        if line.startswith("## "):
            return None
        m = re.match(r"^버전:\s*(\d+\.\d+)\s*$", line)
        if m:
            return m.group(1)
    return None


def screen_sections(lines: list[str], name: str) -> list[tuple[int, int]]:
    """`### <양식> · <쪽> · <화면 이름>` 소절들의 (제목 줄, 끝 줄(미포함)). 화면 이름이 같은 소절을 모두."""
    found = []
    mask = _fence_mask(lines)
    for i in range(len(lines)):
        h = _heading(lines, mask, i)
        if h and h[0] == 3:
            parts = [p.strip() for p in h[1].split("·")]
            if len(parts) >= 3 and parts[-1] == name:
                end = len(lines)
                for j in range(i + 1, len(lines)):
                    nxt = _heading(lines, mask, j)
                    if nxt and nxt[0] <= 3:
                        end = j
                        break
                found.append((i, end))
    return found


def existing_descriptions(text: str, name: str) -> list[str] | None:
    """작업본 화면 소절의 지금 `#### 번호 설명` 항목 글들. 소절이나 소제목이 없으면 None."""
    lines = text.split("\n")
    secs = screen_sections(lines, name)
    if len(secs) != 1:
        return None
    mask = _fence_mask(lines)
    start, end = secs[0]
    items: list[str] | None = None
    for k in range(start + 1, end):
        h = _heading(lines, mask, k)
        if h and h[0] == 4:
            if items is not None:
                break
            items = [] if h[1] == "번호 설명" else None
        elif items is not None and not mask[k]:
            m = _NUM_ITEM.match(lines[k].rstrip("\r"))
            if m:
                items.append(m.group(1))
    return items


def update_workbook(text: str, name: str, png_rel: str, descriptions: list[str]) -> str:
    """작업본의 `<화면 이름>` 소절에서 `#### 그림`·`#### 번호 설명` 본문을 바꾼다(없으면 소절 끝에 더한다). 다른 곳은 건드리지 않는다.

    소절이 없거나 둘 이상이면 ListError.
    """
    lines = text.split("\n")  # 줄 끝의 \r 은 줄에 남겨 원래 줄바꿈을 그대로 둔다(새 줄은 글 전체의 우세한 줄바꿈을 따른다)
    cr = "\r" if text.count("\r\n") * 2 > text.count("\n") else ""

    def mk(s: str) -> str:
        return s + cr

    mask = _fence_mask(lines)
    secs = screen_sections(lines, name)
    if not secs:
        raise ListError(f"작업본에 화면 {name!r} 의 `### … · {name}` 소절이 없다(소절 이름을 목록의 화면 이름과 같게 먼저 만든다)")
    if len(secs) > 1:
        raise ListError(f"작업본에 화면 {name!r} 소절이 {len(secs)}개다(하나여야 한다)")
    start, end = secs[0]
    # 소절 본문을 앞부분(첫 `####` 전)과 `####` 조각들로 나눈다(코드펜스 안의 `####` 는 제목이 아니다).
    pre: list[str] = []
    parts: list[tuple[str, list[str]]] = []
    for k in range(start + 1, end):
        h = _heading(lines, mask, k)
        if h and h[0] == 4:
            parts.append((h[1], []))
        elif parts:
            parts[-1][1].append(lines[k])
        else:
            pre.append(lines[k])
    new = {"그림": [mk(""), mk(png_rel), mk("")],
           "번호 설명": [mk(""), *[mk(f"{i}. {d}") for i, d in enumerate(descriptions, 1)], mk("")]}
    names = [t for t, _ in parts]
    if names.count("그림") > 1 or names.count("번호 설명") > 1:
        raise ListError(f"작업본 화면 {name!r} 소절에 `#### 그림` 또는 `#### 번호 설명` 이 둘 이상이다")
    for key in ("그림", "번호 설명"):
        if key in names:
            parts[names.index(key)] = (key, new[key])
        elif key == "그림" and "번호 설명" in names:
            parts.insert(names.index("번호 설명"), (key, new[key]))
        else:
            while pre and not pre[-1].strip() and not parts:
                pre.pop()
            parts.append((key, new[key]))
        names = [t for t, _ in parts]
    out = lines[:start + 1] + pre
    for title, content in parts:
        if out and out[-1].strip():
            out.append(mk(""))
        out.append(mk(f"#### {title}"))
        out.extend(content if content and not content[0].strip() else [mk(""), *content])
    while out and not out[-1].strip():
        out.pop()
    if end < len(lines):
        out.append(mk(""))
        out.extend(lines[end:])
    elif text.endswith("\n"):
        out.append("")
    return "\n".join(out)


def image_rel(lob: str, screen: str, version: str, partial: bool = False) -> str:
    return f"docs/manual/img/{lob}/{screen}{'_미완' if partial else ''}_v{version}.png"


# ---------------------------------------------------------------- 브라우저 쪽

class Unavailable(RuntimeError):
    """검사 불능(브라우저·페이지가 준비되지 않았다)."""


def split_columns(cols: list[dict], view: float) -> list[list[str]]:
    """열(`name`·`left`·`width`, 표 안 좌표)을 왼쪽부터 보이는 폭 `view` 에 들어가는 만큼 묶는다. 한 열이 혼자 넘쳐도 그 열 하나로 한 묶음."""
    groups: list[list[str]] = []
    start = None
    for c in sorted(cols, key=lambda c: c["left"]):
        if start is None or c["left"] + c["width"] - start > view:
            groups.append([])
            start = c["left"]
        groups[-1].append(c["name"])
    return groups


def wide_reason(screen: Screen, res: dict) -> str:
    """열들이 한 화면에 안 들어갈 때의 사유: 나눌 방법과 `배율` 제안."""
    cols, span, view = res.get("cols") or [], res.get("span") or 0, res.get("view") or 0
    parts = [f"열 {len(cols)}개가 한 화면에 안 들어간다(필요 폭 {span}px, 보이는 폭 {view}px)."]
    groups = split_columns(cols, view)
    parts.append("나누기 제안: " + ", ".join(f"{i}화면 [{', '.join(g)}]" for i, g in enumerate(groups, 1))
                 + " (`열` 이 아닌 표시(버튼·필터)는 첫 묶음 화면에 둔다).")
    if span and view:
        need = int(view / span * 20) / 20  # 5% 단위로 내림
        if need >= MIN_SCALE:
            parts.append(f"또는 화면에 `배율: {need:g}` 을 적는다(필요 배율 약 {view / span:.2f}).")
        else:
            parts.append(f"배율로는 부족하다(필요 배율 약 {view / span:.2f}, 최소 {MIN_SCALE:g}).")
    return " ".join(parts)


def pick_tab(tabs: list[dict], base_url: str, hint: str | None = None) -> dict:
    """붙을 탭을 고른다. `hint`(주소·제목에 든 글)가 있으면 그것으로, 없으면 테넌트 주소가 같은 탭, 탭이 하나뿐이면 그것."""
    if hint:
        hits = [t for t in tabs if hint in (t.get("url") or "") or hint in (t.get("title") or "")]
    else:
        hits = [t for t in tabs if same_site(t.get("url") or "", base_url)]
        if not hits and len(tabs) == 1:
            hits = tabs
    if len(hits) == 1:
        return hits[0]
    listing = "; ".join(f"{t.get('title')!r} {t.get('url')}" for t in tabs) or "(열린 탭 없음)"
    raise Unavailable(("탭을 하나로 정하지 못했다" if hits else "맞는 탭이 없다") + f" — 전용 Chrome 의 탭: {listing}. 테넌트 탭 하나만 두거나 --tab 으로 고른다")


def compose_url(base: str, app: str) -> str:
    return base + app


def same_site(url: str, base: str) -> bool:
    """`url` 의 출처(스킴+호스트·포트)가 테넌트 주소와 같은가. file:// 은 파일 경로가 테넌트 파일 아래여야 한다."""
    u, b = urlsplit(url), urlsplit(base)
    if (u.scheme, u.netloc.lower()) != (b.scheme, b.netloc.lower()):
        return False
    return b.scheme != "file" or unquote(url).startswith(unquote(base).split("#")[0].split("?")[0])


class Capturer:
    def __init__(self, tab: cdp_client.Tab, base_url: str, ui5: str, timeout: float) -> None:
        self.tab, self.base, self.ui5, self.timeout = tab, base_url, ui5, timeout
        self.scoped = False  # 팝업 단계 뒤 찾는 범위가 팝업 안으로 좁혀져 있다

    def wait_ready(self, what: str) -> None:
        """준비될 때까지 기다린다(두 번 연속 준비 상태여야 한다). 시간 초과면 Unavailable."""
        end = time.monotonic() + self.timeout
        streak = 0
        state = None
        while time.monotonic() < end:
            try:  # `__mc_stale` 은 navigate 가 옛 문서에 달아 둔 표지다 — 아직 있으면 새 문서로 바뀌기 전이다
                state = self.tab.evaluate(f"(window.__mc_stale === true) ? 'stale' : {READY_JS}")
            except CdpError:
                state = False
            ok = state is True or (state == "no-ui5" and self.ui5 == "skip")
            streak = streak + 1 if ok else 0
            if streak >= 2:
                self.check_site()
                return
            time.sleep(0.4)
        url = ""
        try:
            url = self.tab.evaluate("location.href") or ""
        except CdpError:
            pass
        hint = ""
        if url and not same_site(url, self.base):
            hint = " — 주소가 테넌트가 아니다. 로그인 화면일 수 있다(전용 Chrome 에서 로그인한 뒤 다시)"
        elif state == "no-ui5":
            hint = " — UI5 가 없는 페이지다(UI5 가 아닌 페이지면 --ui5 skip)"
        raise Unavailable(f"{what}: {self.timeout:g}초 안에 페이지가 준비되지 않았다(현재 {url!r}){hint}")

    def check_site(self) -> None:
        """준비된 페이지의 출처가 테넌트 출처와 같아야 한다. 다르면(로그인 화면·다른 사이트) 검사 불능이다."""
        url = self.tab.evaluate("location.href") or ""
        if not same_site(url, self.base):
            raise Unavailable(f"현재 주소 {url!r} 의 출처가 테넌트 {self.base!r} 와 다르다(로그인 화면이거나 다른 사이트다. 전용 Chrome 에서 테넌트에 로그인한 뒤 다시)")

    def prepare(self) -> None:
        try:  # 최소화된 창은 bringToFront 로 안 살아난다 — 창 상태를 normal 로 돌린다
            win = self.tab.call("Browser.getWindowForTarget")
            self.tab.call("Browser.setWindowBounds", windowId=win["windowId"], bounds={"windowState": "normal"})
        except (CdpError, KeyError, TypeError):
            pass  # 못 해도 아래 보임 확인이 판정한다
        self.tab.call("Page.bringToFront")
        self.set_viewport(None)
        self.ensure_visible("시작")

    def window_hint(self) -> str:
        """브라우저 응답 시간 초과 같은 CDP 오류 뒤에 붙일 원인 안내. 창이 가려지거나 최소화되면 Chrome 이 화면을 그리지 않아
        응답이 멈춘다(#654 실제 테넌트 100). 창 상태·보임을 다시 읽어 알 수 있으면 그대로, 못 읽으면 가능성으로 말한다."""
        state = win = None
        try:
            state = self.tab.evaluate("document.visibilityState")
        except CdpError:
            pass
        try:
            w = self.tab.call("Browser.getWindowForTarget")
            win = self.tab.call("Browser.getWindowBounds", windowId=w["windowId"]).get("bounds", {}).get("windowState")
        except (CdpError, KeyError, TypeError):
            pass
        if state == "hidden" or win == "minimized":
            return f" — 전용 Chrome 창이 가려져 있거나 최소화돼 있다(visibilityState={state!r}, 창={win!r}). 창을 앞으로 꺼내 화면에 띄워 둔 채 다시 돈다"
        if state is None and win is None:
            return " — 창 상태를 읽지 못했다. 전용 Chrome 창이 다른 창에 가려지거나 최소화되면 이렇게 나온다. 창을 앞으로 꺼내 두고 다시 돈다"
        return ""

    def set_viewport(self, scale: float | None) -> tuple[int, int]:
        """화면 크기를 정한다. 배율이 있으면 CSS 픽셀을 1/배율 만큼 넓히고 deviceScaleFactor=배율 로 그림은 WIDTH x HEIGHT 를 유지한다.
        돌려주는 값은 CSS 픽셀 크기(innerWidth·innerHeight 와 같아야 한다).
        실제 테넌트 확인 필요(#657): deviceScaleFactor<1 의 스크린샷이 정확히 1600x900 인지, 반올림으로 1px 어긋나지 않는지."""
        s = scale or 1.0
        w, h = round(WIDTH / s), round(HEIGHT / s)
        self.tab.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=s, mobile=False)
        return w, h

    def ensure_visible(self, what: str) -> None:
        """창이 가려지거나 최소화되면 Chrome 이 화면을 그리지 않는다(#533 실제 테넌트 시험). 보이지 않으면 검사 불능이다."""
        end = time.monotonic() + 3
        while True:
            try:
                state = self.tab.evaluate("document.visibilityState")
            except CdpError:
                state = None
            if state == "visible":
                return
            if time.monotonic() >= end:
                raise Unavailable(f"{what}: 전용 Chrome 창이 보이지 않는다(visibilityState={state!r}). 창을 최소화하거나 다른 창으로 가리지 말고 화면에 띄워 둔 채 다시 돈다")
            self.tab.call("Page.bringToFront")
            time.sleep(0.5)

    def finish(self) -> None:
        try:
            self.tab.evaluate("window.__mc && window.__mc.clearOverlay()")
            self.tab.call("Emulation.clearDeviceMetricsOverride")
        except CdpError:
            pass

    def navigate(self, app: str) -> None:
        """화면마다 **강제로 다시 연다**(같은 주소여도). 앞 화면의 필터 값·열린 상태가 남지 않게 하고, 해시 이동만으로는 앱이 다시 로드되지 않는 문제를 피한다."""
        url = compose_url(self.base, app)
        self.scoped = False
        cur =self.tab.evaluate("location.href") or ""
        self.tab.evaluate("window.__mc_stale = true")  # 새 문서가 열렸는지 알아보는 표지(새 문서에는 없다)
        if unquote(cur) != unquote(url):
            res = self.tab.call("Page.navigate", url=url)
            if res.get("errorText"):
                raise Unavailable(f"화면 열기 {url}: {res['errorText']}")
        if unquote(cur).split("#")[0] == unquote(url).split("#")[0]:  # 문서가 같으면(해시만 다르거나 같다) navigate 로는 안 다시 열린다
            self.tab.call("Page.reload", ignoreCache=False)
        time.sleep(0.5)
        self.wait_ready(f"화면 열기 {url}")
        self.tab.evaluate(LIB_JS)

    def find(self, kind: str, name: str) -> dict:
        res = self.tab.evaluate(f"window.__mc.find({json.dumps(kind)}, {json.dumps(name)})")
        if not isinstance(res, dict) or not isinstance(res.get("items"), list):
            raise Unavailable(f"요소 찾기 응답이 이상하다({kind} {name!r}): {res!r}")
        return res

    def locate(self, mark: Mark) -> Verdict:
        res = self.find(mark.kind, mark.name)
        return judge(res["items"], mark.index, no_input=int(res.get("noInput") or 0))

    def click(self, rect: Rect) -> None:
        x, y = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.tab.call("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=1)

    def double_click(self, rect: Rect) -> None:
        x, y = rect["x"] + rect["w"] / 2, rect["y"] + rect["h"] / 2
        self.tab.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y, button="left", clickCount=1)
        for n in (1, 2):
            for t in ("mousePressed", "mouseReleased"):
                self.tab.call("Input.dispatchMouseEvent", type=t, x=x, y=y, button="left", clickCount=n)

    def cell_target(self, s: Step) -> dict:
        """`행` 이 있는 팝업 단계: 그 열의 보이는 본문 N번째 칸을 찾는다(열이 유일해야 한다). 못 찾으면 검사 불능."""
        what = f"준비 단계 팝업 {s.name!r} 행 {s.row}"
        n = len(self.find("열", s.name)["items"])
        if n != 1:
            raise Unavailable(f"{what}: 열 머리글 {s.name!r} 이 {n}개라 하나로 정하지 못했다")
        self.tab.evaluate(f"window.__mc.scrollColumn({json.dumps(s.name)}, null)")  # 가로 화면 밖이면 먼저 보이게 한다
        time.sleep(0.3)
        r = self.tab.evaluate(f"window.__mc.cellOf({json.dumps(s.name)}, {s.row})")
        if not isinstance(r, dict) or not r.get("ok"):
            r = r if isinstance(r, dict) else {}
            if r.get("noGrid"):
                why = "열 머리글에 aria-colindex 가 없거나 표를 찾지 못해 본문 칸을 셀 수 없다"
            elif "rows" in r:
                why = f"그 열에 보이는 본문 행이 {r['rows']}개뿐이라 {s.row}번째 칸이 없다(세로로 안 보이는 행은 세지 않는다)"
            else:
                why = "열 머리글이 하나로 정해지지 않았다"
            raise Unavailable(f"{what}: {why}")
        return r

    def fill_needed(self, s: Step) -> bool:
        """입력 칸에 값을 넣어야 하는가. 앱이 기억한 필터 값(토큰)이 이미 같으면 False(또 넣으면 오류 창이 뜬다), 다른 값이 있으면 지우고 True."""
        name, want = json.dumps(s.name), (s.value or "").strip()
        cur = self.tab.evaluate(f"window.__mc.readInput({name})")
        if not isinstance(cur, dict) or not cur.get("ok"):
            raise Unavailable(f"준비 단계 입력 {s.name!r}: 입력 칸의 지금 값을 읽지 못했다(MultiInput·Input 이 아니거나 하나로 정하지 못했다): {cur!r}")
        tokens = [str(t).strip() for t in cur.get("tokens") or []]
        value = str(cur.get("value") or "").strip()
        keys = [str(k).strip() for k in cur.get("keys") or []]
        # 토큰 글자는 "AutoOne 1공장 (4310)" 처럼 이름이 붙기도 한다(#656 실제 테넌트 100). 키나 끝의 "(값)" 도 같은 값으로 본다.
        same = want in tokens or f"={want}" in tokens or want in keys or any(t.endswith(f"({want})") for t in tokens)
        if same or (not tokens and value in (want, f"={want}")):
            return False
        if tokens or value:
            done = self.tab.evaluate(f"window.__mc.clearInput({name})")
            if not isinstance(done, dict) or not done.get("ok"):
                raise Unavailable(f"준비 단계 입력 {s.name!r}: 들어 있는 다른 값 {tokens or value!r} 을 지우지 못했다: {done!r}")
            left = self.tab.evaluate(f"window.__mc.readInput({name})")
            if not isinstance(left, dict) or left.get("tokens") or str(left.get("value") or "").strip():
                raise Unavailable(f"준비 단계 입력 {s.name!r}: 들어 있는 다른 값 {tokens or value!r} 을 지운 뒤에도 남아 있다: {left!r}")
        return True

    def run_steps(self, screen: Screen) -> None:
        empty_cell = False
        for s in screen.steps:
            if s.action == "팝업" and s.row:
                cell = self.cell_target(s)
                if self.tab.evaluate("window.__mc.dialogs()") or []:
                    raise Unavailable(f"준비 단계 팝업 {s.name!r}: 더블클릭 전에 이미 대화상자가 떠 있어 새 팝업을 가를 수 없다")
                empty_cell = not cell.get("text") and not cell.get("icon")
                self.double_click(cell["rect"])
            elif s.action in ("누르기", "팝업"):
                v = self.locate(Mark("버튼", s.name, ""))
                if v.status != "found":
                    raise Unavailable(f"준비 단계 {s.action} {s.name!r}: {v.status} — {v.reason}")
                if s.action == "팝업" and (self.tab.evaluate("window.__mc.dialogs()") or []):
                    raise Unavailable(f"준비 단계 팝업 {s.name!r}: 누르기 전에 이미 대화상자가 떠 있어 새 팝업을 가를 수 없다")
                self.click(v.rect)
            elif s.action == "선택":
                v = self.locate(Mark("필터", s.name, ""))
                if v.status != "found":
                    raise Unavailable(f"준비 단계 선택 {s.name!r}: {v.status} — {v.reason}")
                r = self.tab.evaluate(f"window.__mc.selectOption({json.dumps(s.name)}, {json.dumps(s.value)})")
                if not isinstance(r, dict) or not r.get("ok"):
                    r = r if isinstance(r, dict) else {}
                    if r.get("notSelect"):
                        why = "드롭다운(Select·ComboBox)이 아니거나 UI5 컨트롤을 찾지 못했다"
                    elif "items" in r:
                        why = f"보이는 항목 중 {s.value!r} 와 같은 글자가 {r.get('count', 0)}개다. 보이는 항목: {r['items']!r}"
                    else:
                        why = "드롭다운을 하나로 정하지 못했다"
                    raise Unavailable(f"준비 단계 선택 {s.name!r}: {why}")
            else:
                v = self.locate(Mark("필터", s.name, ""))
                if v.status != "found":
                    raise Unavailable(f"준비 단계 입력 {s.name!r}: {v.status} — {v.reason}")
                if self.fill_needed(s):
                    f = self.tab.evaluate(f"window.__mc.focusInput({json.dumps(s.name)})")
                    if not f or not f.get("ok"):
                        raise Unavailable(f"준비 단계 입력 {s.name!r}: 입력 칸에 포커스를 주지 못했다")
                    self.tab.call("Input.insertText", text=s.value or "")
                    for t in ("keyDown", "keyUp"):  # Tab 으로 값을 확정한다
                        self.tab.call("Input.dispatchKeyEvent", type=t, key="Tab", code="Tab", windowsVirtualKeyCode=9)
            time.sleep(0.3)
            self.wait_ready(f"준비 단계 {s.action} {s.name!r}")
            if s.action == "팝업":  # 팝업은 마지막 단계다. 확인·저장은 누르지 않는다
                self.open_popup(s, empty_cell)
                continue
            shown = self.tab.evaluate("window.__mc.dialogs()") or []
            if shown:  # 오류·경고 창이 떴다 — 그 화면은 의도한 상태가 아니다(통과로 찍지 않는다)
                raise Unavailable(f"준비 단계 {s.action} {s.name!r} 뒤에 대화상자가 떴다: {shown[0]!r}. 준비 단계(값·이미 들어 있는 기본값)를 확인한다")

    def set_scope(self, what: str) -> None:
        r = self.tab.evaluate("window.__mc.setScope()")
        if not isinstance(r, dict) or not r.get("ok"):
            raise Unavailable(f"{what}: 팝업 안으로 찾는 범위를 좁히지 못했다(대화상자 {r.get('count') if isinstance(r, dict) else r!r}개)")
        self.scoped = True

    def popup_info(self, what: str) -> dict:
        """떠 있는 대화상자가 정확히 하나이고 오류·경고 창이 아닐 때만 그 하나를 돌려준다. 아니면 검사 불능."""
        info = self.tab.evaluate("window.__mc.dialogInfo()") or []
        if not info:
            raise Unavailable(f"{what}: 팝업이 뜨지 않았다")
        if len(info) > 1:
            raise Unavailable(f"{what}: 대화상자가 {len(info)}개 떠 있어 팝업 하나로 정하지 못했다: {[i.get('text') for i in info]!r}")
        if info[0].get("alert"):
            raise Unavailable(f"{what}: 오류·경고 창이 떴다: {info[0].get('text')!r}. 준비 단계(값·기본값)를 확인한다")
        return info[0]

    def open_popup(self, s: Step, empty_cell: bool = False) -> None:
        what = f"준비 단계 팝업 {s.name!r}"
        # 팝업은 서버 호출 뒤 늦게 뜨기도 한다(#653 실제 테넌트 100 그루핑). 뜰 때까지 기다린 뒤 판정한다.
        end = time.monotonic() + self.timeout
        while time.monotonic() < end and not (self.tab.evaluate("window.__mc.dialogInfo()") or []):
            time.sleep(0.5)
        time.sleep(0.5)  # 뜬 뒤 그리기·애니메이션
        self.wait_ready(what)
        try:
            self.popup_info(what)
        except Unavailable as e:
            if s.row and "팝업이 뜨지 않았다" in str(e):
                # 칸이 비어 있지 않아도(예: 백로그 없음을 뜻하는 동그라미 아이콘) 그 행은 팝업을 안 열 수 있다(#673 실제 테넌트 100).
                why = "그 행 칸이 비어 있다" if empty_cell else f"{s.row}번째 행 칸을 더블클릭했지만 그 행은 팝업을 열지 않는다"
                raise Unavailable(f"{e} — {why}(백로그 없는 행일 수 있다), 팝업이 열리는 다른 `행` 을 고른다") from e
            raise
        self.set_scope(what)

    def wait_content(self, screen: Screen, what: str) -> None:
        """찾을 이름 중 하나라도 화면에 나타나고 문서가 멈출 때까지 기다린다. 시간 초과면 Unavailable.

        Launchpad 는 UI5 코어가 준비된 뒤에도 앱을 그리는 데 시간이 걸린다(#533 실제 테넌트 시험에서 빈 화면이 찍혔다).
        하나도 안 나타나면 "못 찾음" 이 아니라 화면이 그려지지 않은 것이라 검사 불능이다.
        """
        # 입력·선택은 필터 라벨. 팝업 뒤에는 팝업 안에서 표시 이름이 그려지길 기다린다(준비 단계 대상은 팝업 밖에 있다)
        names = [] if self.scoped else [("열" if s.row else "버튼" if s.action in ("누르기", "팝업") else "필터", s.name) for s in screen.steps]
        names += [(m.kind, m.name) for m in screen.marks]
        end = time.monotonic() + self.timeout
        last, stable = None, 0
        while time.monotonic() < end:
            try:
                if not self.tab.evaluate("!!window.__mc"):
                    self.tab.evaluate(LIB_JS)
                    if self.scoped:
                        self.tab.evaluate("window.__mc.setScope()")
                hit = any(len(self.find(k, n)["items"]) > 0 for k, n in names)
                nodes = self.tab.evaluate("document.getElementsByTagName('*').length")
            except (CdpError, Unavailable):
                hit, nodes = False, None
            stable = stable + 1 if hit and nodes == last else 0
            last = nodes
            if stable >= 2:
                return
            time.sleep(0.5)
        raise Unavailable(f"{what}: {self.timeout:g}초 안에 찾을 이름이 하나도 그려지지 않았다(화면이 덜 그려졌거나 이름이 모두 틀렸다)")

    def capture(self, screen: Screen) -> tuple[bytes, list[dict], list[dict]]:
        """화면 하나를 찍는다. (PNG, 그린 것, 못 찾은 것). `배율` 이 있으면 이 화면만 그 배율로 찍고 원래 크기로 되돌린다."""
        if not screen.scale:
            return self._capture(screen, WIDTH, HEIGHT)
        size = self.set_viewport(screen.scale)
        try:
            return self._capture(screen, *size)
        finally:
            self.set_viewport(None)

    def scroll_columns(self, screen: Screen) -> None:
        """`열` 표시들을 가로 스크롤 안에서 보이게 한다. 둘 이상이면 한 번에 넘기고, 한 화면에 안 들어가면 검사 불능(나누기·배율 제안)."""
        cols = [m for m in screen.marks if m.kind == "열"]
        if len(cols) >= 2:
            res = self.tab.evaluate(f"window.__mc.scrollColumns({json.dumps([{'name': m.name, 'index': m.index} for m in cols], ensure_ascii=False)})")
            if isinstance(res, dict) and res.get("ok"):
                if not res.get("fits"):
                    raise Unavailable(f"화면 {screen.name!r}: {wide_reason(screen, res)}")
                return
        for m in cols:  # 열이 하나이거나 표의 가로 스크롤 요소를 못 찾으면 열마다 넘긴다
            self.tab.evaluate(f"window.__mc.scrollColumn({json.dumps(m.name)}, {json.dumps(m.index)})")

    def _capture(self, screen: Screen, cw: int, ch: int) -> tuple[bytes, list[dict], list[dict]]:
        self.navigate(screen.app)
        self.ensure_visible(f"화면 {screen.name!r}")
        try:
            self.wait_content(screen, f"화면 {screen.name!r} 그리기")
        except Unavailable as first:
            # 앱 첫 로드(캐시 없음)는 시간 안에 못 그리기도 한다 — 같은 명령을 다시 돌리면 됐다(#655 실제 테넌트 100).
            # 한 번만 다시 열어 기다린다. 또 안 되면 원인 안내를 붙여 검사 불능.
            self.navigate(screen.app)
            self.ensure_visible(f"화면 {screen.name!r} 다시 열기")
            try:
                self.wait_content(screen, f"화면 {screen.name!r} 다시 열어 그리기")
            except Unavailable as e:
                raise Unavailable(f"{e} — 한 번 다시 열어도 같았다(처음: {first}). 첫 로드가 느린 앱이면 --timeout 을 늘려 다시 돈다") from e
        self.run_steps(screen)
        if screen.steps:
            self.wait_content(screen, f"화면 {screen.name!r} 준비 뒤 그리기")
        if screen.popup:  # 그 팝업 하나만 허용한다(그 밖의 대화상자가 더 있으면 검사 불능)
            self.popup_info(f"화면 {screen.name!r} 찍기 직전")
            self.set_scope(f"화면 {screen.name!r} 찍기 직전")
        shown = [] if screen.popup else self.tab.evaluate("window.__mc.dialogs()") or []
        if shown:  # 찍기 직전에도 본다 — 대화상자는 준비 단계 뒤 늦게 뜰 수 있다
            raise Unavailable(f"화면 {screen.name!r}: 대화상자가 떠 있다: {shown[0]!r}. 이 상태로는 찍지 않는다(준비 단계·기본값 확인)")
        self.scroll_columns(screen)  # 가로 스크롤 밖 열은 먼저 보이게 한다
        time.sleep(0.2)
        size = self.tab.evaluate("window.__mc.size()")
        if (size["w"], size["h"]) != (cw, ch):
            raise Unavailable(f"창 크기를 {cw}x{ch} 로 고정하지 못했다(현재 {size['w']}x{size['h']})")
        drawn, missing, items = [], [], []
        for n, m in enumerate(screen.marks, 1):
            v = self.locate(m)
            if v.status == "found":
                items.append((n, v.rect))
                drawn.append({"번호": n, "종류": m.kind, "이름": m.name, "설명": m.text})
            else:
                missing.append({"번호": n, "종류": m.kind, "이름": m.name, "상태": v.status, "사유": v.reason, "후보": v.count})
        k = WIDTH / cw  # 배율. 덮개는 CSS 픽셀로 그리므로 그림에서 같은 굵기·크기가 되게 1/배율 만큼 키운다
        plan = plan_marks(items, cw, ch, pad=round(BOX_PAD / k), r=round(BADGE_R / k))
        self.tab.evaluate(f"window.__mc.drawOverlay({json.dumps([p.__dict__ for p in plan])}, {json.dumps(RED)}, {round(BOX_BORDER / k)})")
        time.sleep(0.15)
        try:
            png = self.tab.screenshot_png()
        finally:
            self.tab.evaluate("window.__mc.clearOverlay()")
        return png, drawn, missing


# ---------------------------------------------------------------- 실행

def _spec_for(list_path: Path) -> Path:
    if not list_path.name.endswith(LIST_SUFFIX):
        raise ListError(f"목록 파일 이름은 `<번호>.<업무 제목>{LIST_SUFFIX}` 여야 한다: {list_path.name}")
    return list_path.with_name(list_path.name[: -len(LIST_SUFFIX)] + ".md")


def _write_png(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".png.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _read_spec(path: Path) -> str:
    """작업본을 줄바꿈 변환 없이 읽는다(\\r\\n 을 그대로 둔다)."""
    if not path.is_file():
        raise ListError(f"작업본이 없다: {path} (먼저 `/harness:manual` 로 작업본을 만든다)")
    return path.read_bytes().decode("utf-8")


def _write_spec(path: Path, text: str) -> None:
    """임시 파일에 쓰고 교체한다(쓰다 끊겨도 작업본이 반쪽이 되지 않는다)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)


def _port(value: object) -> int:
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ListError(f"디버깅 포트가 숫자가 아니다: {value!r}") from e
    if isinstance(value, bool) or not 1 <= port <= 65535:
        raise ListError(f"디버깅 포트가 올바르지 않다: {value!r}")
    return port


@dataclass
class Report:
    screens: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def status(self) -> str:
        if self.problems or any(s["상태"] == "검사 불능" for s in self.screens):
            return "unavailable"
        return "incomplete" if any(s["상태"] == "미완" for s in self.screens) else "ok"


def run(args: argparse.Namespace) -> tuple[Report, int]:
    root = Path(args.root).resolve()
    list_path = Path(args.list)
    if not list_path.is_absolute():
        list_path = root / list_path
    report = Report()
    try:
        screens = load_screens(list_path)
        spec_path = Path(args.spec) if args.spec else _spec_for(list_path)
        if not spec_path.is_absolute():
            spec_path = root / spec_path
        spec_text = _read_spec(spec_path)
        version = read_version(spec_text)
        if not version:
            raise ListError("작업본 머리에 `버전: 0.1` 줄이 없다(그림 파일 이름의 판을 정할 수 없다)")
        lob = spec_path.parent.name
        env = load_env(root)
        base = check_base_url(args.base_url or env.get("테넌트"), allow_local=args.allow_local_test)
        port = _port(args.port or env.get("포트") or cdp_client.DEFAULT_PORT)
        cdp_client.ensure_loopback(args.host)
        wanted = [s for s in screens if not args.screen or s.name in args.screen]
        if args.screen and {s.name for s in wanted} != set(args.screen):
            raise ListError(f"목록에 없는 화면: {sorted(set(args.screen) - {s.name for s in wanted})}")
        lines = spec_text.split("\n")
        for s in wanted:
            n = len(screen_sections(lines, s.name))
            if n != 1:
                report.problems.append(f"작업본에 화면 {s.name!r} 소절이 {'없다' if n == 0 else f'{n}개다(하나여야 한다)'}")
    except (ListError, CdpError, OSError, UnicodeDecodeError) as e:
        report.problems.append(str(e))
        return report, 2
    if report.problems:
        return report, 2
    if args.check:
        report.screens = [{"이름": s.name, "상태": "목록 정상", "표시": len(s.marks), "준비": len(s.steps)} for s in wanted]
        return report, 0

    try:
        tabs = cdp_client.list_tabs(args.host, port)
        tab = cdp_client.Tab(pick_tab(tabs, base, args.tab), timeout=args.timeout)
    except (CdpError, Unavailable) as e:
        report.problems.append(f"검사 불능: {e}")
        return report, 2
    cap = Capturer(tab, base, args.ui5, args.timeout)
    try:
        cap.prepare()
        for s in wanted:
            try:
                png, drawn, missing = cap.capture(s)
            except (Unavailable, CdpError) as e:
                why = str(e)
                if isinstance(e, CdpError):
                    why += cap.window_hint()
                report.screens.append({"이름": s.name, "상태": "검사 불능", "사유": why})
                continue
            complete = not missing
            rel = image_rel(lob, s.name, version, partial=not complete)
            _write_png(root / rel, png)
            row = {"이름": s.name, "상태": "완료" if complete else "미완", "그림": rel, "그린 것": drawn, "못 찾은 것": missing}
            if complete and not args.no_spec_update:
                try:  # 화면마다 갱신 직전에 다시 읽는다(캡처 중 사람이 작업본을 고쳤을 수 있다)
                    current = _read_spec(spec_path)
                    descriptions = [m.text for m in s.marks]
                    before = existing_descriptions(current, s.name)
                    if before and before != descriptions and any(b.strip() and b.strip() != "미정" for b in before):
                        row["replaced_descriptions"] = {"before": before, "after": descriptions}
                    _write_spec(spec_path, update_workbook(current, s.name, rel, descriptions))
                    row["작업본 갱신"] = True
                except (ListError, OSError, UnicodeDecodeError) as e:
                    row = {"이름": s.name, "상태": "검사 불능", "사유": f"그림은 {rel} 에 저장했으나 작업본을 고치지 못했다: {e}"}
            report.screens.append(row)
    except (CdpError, Unavailable, OSError) as e:
        report.problems.append(f"검사 불능: {e}")
    finally:
        cap.finish()
        tab.close()
    code = {"ok": 0, "incomplete": 1, "unavailable": 2}[report.status()]
    return report, code


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="python -m checker.manual_capture", description="사용자 매뉴얼 화면을 찍고 빨간 네모·번호를 그린다.")
    p.add_argument("--list", required=True, metavar="<번호>.<업무 제목>.capture.yaml", help="찍을 화면 목록(Project Repository 안)")
    p.add_argument("--root", default=".", help="Project Repository 루트")
    p.add_argument("--spec", help="작업본 경로(기본: 목록 이름에서 `.capture.yaml` 을 `.md` 로)")
    p.add_argument("--screen", action="append", help="이 화면만(여러 번 쓸 수 있다)")
    p.add_argument("--base-url", help=f"테넌트 주소(기본: {ENV_PATH} 의 `테넌트:`)")
    p.add_argument("--host", default=cdp_client.LOOPBACK, help=f"디버깅 주소. {cdp_client.LOOPBACK} 만 허용한다")
    p.add_argument("--port", type=int, help=f"디버깅 포트(기본 {ENV_PATH} 의 `포트:`, 없으면 {cdp_client.DEFAULT_PORT})")
    p.add_argument("--tab", help="붙을 탭의 주소·제목에 든 글(기본: 테넌트 주소의 탭)")
    p.add_argument("--ui5", choices=("require", "skip"), default="require", help="require: UI5 가 준비돼야 찍는다(기본). skip: UI5 가 없는 페이지를 허용(시험용)")
    p.add_argument("--timeout", type=float, default=30.0, help="페이지 준비를 기다리는 초(초과하면 검사 불능)")
    p.add_argument("--check", action="store_true", help="브라우저에 붙지 않고 목록·작업본·주소만 검사한다")
    p.add_argument("--allow-local-test", action="store_true", help="시험용으로 http://127.0.0.1·file:// 테넌트 주소를 허용한다(실제 테넌트에는 쓰지 않는다)")
    p.add_argument("--no-spec-update", action="store_true", help="그림만 저장하고 작업본은 고치지 않는다")
    args = p.parse_args(argv)
    report, code = run(args)
    out = {"status": report.status(), "screens": report.screens}
    if report.problems:
        out["problems"] = report.problems
        if not report.screens:
            out["status"] = "error"
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
