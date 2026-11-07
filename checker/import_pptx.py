"""사람이 양식 pptx 에 직접 써서 올린 매뉴얼을 작업본(md)과 그림으로 읽어 들인다(#742).

`checker.export_pptx` 의 거꾸로다. 지도(`templates/forms/<양식>.yaml`)의 `찾기` 는 **견본 쪽의 예시 글자** 앞부분이라 사람이 데이터로
바꾼 pptx 에는 쓸 수 없다. 대신 견본 쪽에서 `_Locator` 로 칸 도형의 **위치**를 얻고, 올린 pptx 에서 같은 위치(허용 오차 안)의
도형 글을 읽는다. 이 모듈에는 특정 양식의 글자·슬라이드 번호·좌표가 없다 — 쪽·항목 이름은 지도에서 읽는다.

- 쪽 분류: 올린 쪽마다 견본 쪽들의 칸 위치와 맞는 정도로 정한다. 칸이 없는 견본(끝 쪽)은 어느 칸 쪽과도 맞지 않는 남은 쪽이다.
  정할 수 없거나 지도 순서와 다르면 읽지 못함이다.
- 번호 설명: 번호 도형(`번호.글자` 모양의 숫자 글, `왼쪽_이상` 오른쪽, 쪽 번호 필드 `a:fld` 제외)마다 오른쪽·같은 높이의 가장 가까운
  글상자를 짝으로 잡는다(견본 간격에 기대지 않는다). 위에서 아래로 읽는다. `쪽당_최대` 로 넘어간 쪽은 화면 제목이 같으면 한 화면으로 합친다.
- 지도가 안 가리킨 글은 산출 때 지워지는 쪽이 있다. 견본에 있던 글이 아닌데 올린 쪽에 남은 글은 `unmapped`(옮기지 못한 글)로 알린다.
- 표는 지도가 읽지 않는다. 견본 표와 다른 표가 있으면 `unmapped` 로 알린다.

종료코드와 stdout(JSON 한 줄)
    0  `ok`          지도의 모든 칸을 읽었고 옮기지 못한 글이 없다. 작업본·그림을 썼다(--check 면 쓰지 않고 `planned` 만).
    1  `incomplete`  작업본을 썼지만 못 찾은 칸(`missing`, 작업본에는 `미정`)이나 옮기지 못한 글(`unmapped`)이 있다.
    2  `error`       지도·양식·올린 pptx 를 못 읽음, 쪽을 분류하지 못함, 파일 이름에서 값을 못 읽음, 같은 작업본·그림이 이미 있음.
                     아무것도 쓰지 않는다. 검사 불능이지 통과도 위반도 아니다.

`## 묶은 개발 건` 같은 pptx 에 정보가 없는 필수 절은 템플릿 틀대로 두고 값은 `미정` 으로 쓴다(`--dev DEV-001,DEV-002` 를 주면 DEV 칸을 그 번호로 채운다). 쓴 작업본에는 문서 검사
(`rules/` 의 규칙, 훅과 같은 검사 함수)를 돌려 `doc_guard` 로 싣는다. 못 돌리면 `unavailable`(검사 불능)이다.

    python -P -m checker.import_pptx --pptx <올린 pptx> --root <저장소> [--form <양식 이름>] [--check]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pptx import Presentation
from pptx.oxml.ns import qn

from checker import export, export_pptx
from checker.export import ExportError, norm

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_ERROR = 2

TOL = 120000  # 칸 도형 위치 허용 오차(EMU, 약 3mm). 이 안에서 옮긴 도형은 같은 칸으로 읽는다
EXACT = 20000  # 쪽 분류에서 위치가 사실상 같다고 보는 오차(EMU). 칸 위치가 서로 가까운 견본 쪽끼리 가를 때 쓴다
MIN_SCORE = 0.5  # 쪽 분류: 지도 칸의 이만큼 이상이 맞아야 그 쪽으로 본다
VERSION_RE = r"\d+\.\d+"
_BAD_IMG_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------- 도형 읽기

def _raw(shape) -> str:
    """도형 글. 문단은 줄바꿈으로, 줄바꿈(a:br)도 줄바꿈으로 읽고 앞뒤 공백만 뗀다."""
    lines = [p.text.replace("\v", "\n") for p in shape.text_frame.paragraphs]
    return "\n".join(l.rstrip() for l in "\n".join(lines).split("\n")).strip()


def _group_text(shape) -> str:
    return norm(" ".join(t.text or "" for t in shape._element.iter(qn("a:t"))))


def _is_group(shape) -> bool:
    return shape._element.tag == qn("p:grpSp")


def _text_shapes(slide) -> list:
    """칸 후보: 자리가 있는 글상자(빈 것 포함). 쪽 번호 필드 도형은 뺀다."""
    return [s for s in slide.shapes
            if export_pptx._is_text(s) and s.left is not None and s.top is not None and not export_pptx._has_fld(s)]


def _table_sig(shape) -> tuple[str, ...]:
    return tuple(norm(t.text or "") for t in shape._element.iter(qn("a:t")))


def _assign(marks: list, shapes: list, tol: int) -> dict[int, int]:
    """표시(견본 위치)마다 허용 오차 안에서 가장 가까운 도형을 하나씩 짝짓는다. 한 도형은 한 표시에만 쓴다."""
    pairs = []
    for i, m in enumerate(marks):
        for j, s in enumerate(shapes):
            dl, dt = abs(s.left - m.left), abs(s.top - m.top)
            if dl <= tol and dt <= tol:
                pairs.append((dl + dt, i, j))
    pairs.sort()
    out: dict[int, int] = {}
    used: set[int] = set()
    for _, i, j in pairs:
        if i in out or j in used:
            continue
        out[i] = j
        used.add(j)
    return out


# ---------------------------------------------------------------- 견본 쪽의 위치 정보

@dataclass
class _Mark:
    kind: str  # field | seq | list | listnum
    item: str
    frame: str | None
    left: int
    top: int
    sample: str


@dataclass
class _Geo:
    pmap: dict
    name: str
    marks: list[_Mark] = field(default_factory=list)
    badge: object = None
    left_min: int = 0
    pic_box: tuple[int, int, int, int] | None = None
    statics: list[tuple[str, int, int]] = field(default_factory=list)  # 견본에 있던 글(글, 왼쪽, 위)
    pic_hashes: set[str] = field(default_factory=set)
    tables: set[tuple[str, ...]] = field(default_factory=set)

    @property
    def repeat(self) -> bool:
        return bool(self.pmap.get("반복"))

    @property
    def field_items(self) -> list[str]:
        return [norm(f["항목"]) for f in self.pmap.get("칸") or []]


def _geometry(prs, fmap: dict, form: str) -> list[_Geo]:
    slides = list(prs.slides)
    geos: list[_Geo] = []
    for p in fmap["쪽"]:
        name = norm(p["이름"])
        n = p["견본"]
        if not 1 <= n <= len(slides):
            raise ExportError(f"견본 {n} 이 양식의 슬라이드 수({len(slides)}) 밖이다", form=form, sheet=name, item="견본")
        slide = slides[n - 1]
        loc = export_pptx._Locator(slide, p, prs.slide_height)
        if loc.problems:
            item, reason = loc.problems[0]
            raise ExportError(f"양식 지도가 양식 pptx 와 맞지 않아 위치를 얻지 못했다: {reason}", form=form, sheet=name, item=item)
        g = _Geo(p, name)
        for f, s in loc.fields:
            g.marks.append(_Mark("field", norm(f["항목"]), f.get("틀"), s.left, s.top, norm(s.text_frame.text)))
        if loc.seq is not None:
            g.marks.append(_Mark("seq", "순번", None, loc.seq.left, loc.seq.top, norm(loc.seq.text_frame.text)))
        if loc.list_text is not None:
            g.marks.append(_Mark("list", "목록.글", None, loc.list_text.left, loc.list_text.top, ""))
            g.marks.append(_Mark("listnum", "목록.번호", None, loc.list_num.left, loc.list_num.top, ""))
        if loc.badge is not None:
            g.badge = loc.badge
            g.left_min = int((p["번호_설명"]["번호"]).get("왼쪽_이상", 0))
        if loc.pic is not None:
            g.pic_box = (loc.pic.left, loc.pic.top, loc.pic.width, loc.pic.height)
        for s in slide.shapes:
            if export_pptx._is_pic(s):
                g.pic_hashes.add(s.image.sha1)
            elif export_pptx._is_table(s):
                g.tables.add(_table_sig(s))
            elif _is_group(s):
                t = _group_text(s)
                if t and s.left is not None:
                    g.statics.append((t, s.left, s.top))
            elif export_pptx._is_text(s) and s.left is not None:
                t = norm(s.text_frame.text)
                if t:
                    g.statics.append((t, s.left, s.top))
        geos.append(g)
    return geos


# ---------------------------------------------------------------- 쪽 분류

def _bare_evidence(shapes: list, geo: _Geo) -> bool:
    """올린 쪽의 글이 모두 칸 없는 견본 쪽의 고정 글(같은 글·같은 자리)이고 하나 이상이면 True."""
    texts = [(norm(s.text_frame.text), s.left, s.top) for s in shapes if norm(s.text_frame.text)]
    return bool(texts) and all(
        any(t == st and abs(l - sl) <= TOL and abs(tp - sp) <= TOL for st, sl, sp in geo.statics) for t, l, tp in texts)


def _classify(slides: list, shapes_by_slide: list[list], geos: list[_Geo], form: str) -> list[int]:
    """올린 쪽마다 지도 쪽 번호를 낸다. 정할 수 없으면 ExportError."""
    """1) 지도 칸의 절반을 넘게 맞는 견본 쪽이 하나로 가려지면 확실한 쪽이다. 2) 나머지(칸이 일부 지워졌거나 칸 없는 끝 쪽)는 앞뒤 확실한 쪽의
    지도 순서 사이에 들어가는 견본 쪽 중에서, 절반 이상 맞는 쪽 → 칸 없는 쪽 순으로 하나로 정한다. 하나로 못 정하면 ExportError."""
    marked = [i for i, g in enumerate(geos) if g.marks]
    scores: list[dict[int, tuple[float, int, int]]] = []  # 쪽마다 {지도 쪽: (맞는 비율, 거의 정확히 맞는 칸 수, 오차 안에 맞는 칸 수)}
    conf: dict[int, int] = {}  # 올린 쪽 번호(1부터) → 지도 쪽 번호
    for k, shapes in enumerate(shapes_by_slide, 1):
        sc: dict[int, tuple[float, int, int]] = {}
        for i in marked:
            m = geos[i].marks
            got = _assign(m, shapes, TOL)
            exact = sum(1 for a, b in got.items() if abs(shapes[b].left - m[a].left) <= EXACT and abs(shapes[b].top - m[a].top) <= EXACT)
            sc[i] = (len(got) / len(m), exact, len(got))
        scores.append(sc)
        ranked = sorted(sc.items(), key=lambda x: x[1][1:], reverse=True)  # 정확히 맞는 칸이 많은 쪽, 같으면 오차 안에 맞는 칸이 많은 쪽
        if ranked and sc[ranked[0][0]][0] > MIN_SCORE:
            if len(ranked) > 1 and ranked[1][1][1:] == ranked[0][1][1:] and ranked[1][1][0] > MIN_SCORE:
                a, b = geos[ranked[0][0]].name, geos[ranked[1][0]].name
                raise ExportError(f"올린 pptx 의 {k}번째 쪽이 {a!r} 인지 {b!r} 인지 정할 수 없다(두 견본 쪽의 칸 위치가 같게 맞는다)", form=form)
            conf[k] = ranked[0][0]
    used_once = {p for p in conf.values() if not geos[p].repeat}
    result: dict[int, int] = dict(conf)
    for k in range(1, len(shapes_by_slide) + 1):
        if k in conf:
            continue
        prev = max((p for j, p in conf.items() if j < k), default=-1)
        nxt = min((p for j, p in conf.items() if j > k), default=len(geos))
        cands = [i for i, g in enumerate(geos)
                 if (i > prev or (i == prev and g.repeat)) and (i < nxt or (i == nxt and g.repeat))
                 and (g.repeat or i not in used_once)]
        weak = sorted(((scores[k - 1][i][1:], i) for i in cands if i in scores[k - 1] and scores[k - 1][i][0] >= MIN_SCORE), reverse=True)
        bare = [i for i in cands if not geos[i].marks]
        if weak and (len(weak) == 1 or weak[0][0] != weak[1][0]):
            pick = weak[0][1]
        elif not weak and len(bare) == 1 and (not any(geos[i].marks for i in cands) or _bare_evidence(shapes_by_slide[k - 1], geos[bare[0]])):
            # 칸이 있는 쪽(예: 칸을 다 지운 본문 쪽)도 후보면, 이 쪽의 글이 칸 없는 견본의 고정 글과 같다는 증거가 있을 때만 칸 없는 쪽으로 정한다
            pick = bare[0]
        else:
            names = ", ".join(repr(geos[i].name) for i in ([w[1] for w in weak] or cands)) or "없음"
            raise ExportError(f"올린 pptx 의 {k}번째 쪽이 어느 견본 쪽과 맞는지 정할 수 없다(후보: {names}). "
                              "지도의 칸 위치와 맞지 않는 쪽이거나, 앞뒤 쪽의 순서상 들어갈 칸 없는 견본 쪽이 하나로 정해지지 않는다", form=form)
        result[k] = pick
        if not geos[pick].repeat:
            used_once.add(pick)
    order = [result[k] for k in sorted(result)]
    if order != sorted(order):
        names = " → ".join(geos[r].name for r in order)
        raise ExportError(f"올린 pptx 의 쪽 순서가 지도 순서와 다르다(읽은 순서: {names})", form=form)
    return order


# ---------------------------------------------------------------- 쪽 읽기

@dataclass
class _Read:
    slide_no: int
    values: dict[str, str | None] = field(default_factory=dict)
    why: dict[str, str] = field(default_factory=dict)  # 값이 None 인 이유
    seq: str = ""
    toc: list[str] = field(default_factory=list)
    notes: list[tuple[str, str | None]] = field(default_factory=list)
    pic: tuple[bytes, str, int, int] | None = None  # 바이트, 확장자, 가로, 세로
    pic_why: str = ""
    unmapped: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)


def _unframe(text: str, frame: str | None) -> str:
    if not frame:
        return text
    pre, _, post = str(frame).partition("{값}")
    if pre and text.startswith(pre):
        text = text[len(pre):]
    if post and text.endswith(post):
        text = text[: -len(post)]
    return text.strip()


def _same_as_static(geo: _Geo, text: str, left: int, top: int) -> bool:
    t = norm(text)
    return any(t == st and abs(left - sl) <= TOL and abs(top - sp) <= TOL for st, sl, sp in geo.statics)


def _overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0


def _read_slide(slide, k: int, geo: _Geo) -> _Read:
    r = _Read(k)
    shapes = _text_shapes(slide)
    got = _assign(geo.marks, shapes, TOL)
    claimed: set[int] = set()
    for i, m in enumerate(geo.marks):
        s = shapes[got[i]] if i in got else None
        if s is not None:
            claimed.add(id(s._element))
        if m.kind == "field":
            if s is None:
                r.values[m.item] = None
                r.why[m.item] = f"견본의 칸 위치(왼쪽 {m.left}, 위 {m.top} EMU, 오차 {TOL}) 안에 도형이 없다 — 지웠거나 크게 옮겼다"
                continue
            text = _raw(s)
            if not text:
                r.values[m.item] = None
                r.why[m.item] = "칸 도형은 있으나 글이 비어 있다"
            elif norm(text) == m.sample:
                r.values[m.item] = None
                r.why[m.item] = "견본의 예시 글이 그대로 남아 있다(아직 안 썼다)"
            else:
                v = _unframe(text, m.frame)
                if m.frame and v == text and str(m.frame).replace("{값}", ""):
                    r.warnings.append({"type": "frame-differs", "item": m.item,
                                       "reason": f"{m.item} 칸 글이 지도의 틀({m.frame})로 시작·끝나지 않아 글 전체를 값으로 읽었다"})
                r.values[m.item] = v
        elif m.kind == "seq" and s is not None:
            r.seq = norm(s.text_frame.text)
        elif m.kind == "list" and s is not None:
            r.toc = [l.strip() for l in _raw(s).split("\n") if l.strip()]

    # 번호 설명: 번호 도형마다 오른쪽·같은 높이의 가까운 글상자를 짝으로
    others = [s for s in shapes if id(s._element) not in claimed]
    if geo.badge is not None:
        badges = sorted((s for s in others if re.fullmatch(r"\d+", norm(s.text_frame.text)) and s.left >= geo.left_min),
                        key=lambda s: (s.top, s.left))
        badge_ids = {id(s._element) for s in badges}
        notes = [s for s in others if id(s._element) not in badge_ids and norm(s.text_frame.text)
                 and not _same_as_static(geo, _raw(s), s.left, s.top)]  # 양식에 원래 있는 고정 글은 설명 후보가 아니다
        used: set[int] = set()
        pairs = []
        for b in badges:
            cands = [n for n in notes if id(n._element) not in used and n.left >= b.left + b.width // 2
                     and n.top <= b.top + b.height and n.top + n.height >= b.top]
            n = min(cands, key=lambda n: (abs(n.top - b.top), abs(n.left - (b.left + b.width))), default=None)
            if n is not None:
                used.add(id(n._element))
            pairs.append((b, n))
            claimed.add(id(b._element))
            if n is not None:
                claimed.add(id(n._element))
        for b, n in pairs:
            text = None
            if n is not None:
                lines = [l.rstrip() for l in _raw(n).split("\n") if l.strip()]
                text = "\n".join(lines).strip() or None
            r.notes.append((norm(b.text_frame.text), text))

    # 그림 자리: 견본 그림 자리와 가장 많이 겹치는 그림. 견본의 예시 그림 그대로면 아직 안 바꾼 것
    pics = [s for s in slide.shapes if export_pptx._is_pic(s)]
    claimed_pics: set[int] = set()
    if geo.pic_box is not None:
        cands = sorted(((_overlap(geo.pic_box, (s.left, s.top, s.width, s.height)), s) for s in pics if s.left is not None),
                       key=lambda x: -x[0])
        if not cands or cands[0][0] <= 0:
            r.pic_why = "견본의 그림 자리와 겹치는 그림이 없다"
        else:
            s = cands[0][1]
            claimed_pics.add(id(s._element))
            if s.image.sha1 in geo.pic_hashes:
                r.pic_why = "견본의 예시 그림이 그대로 남아 있다(아직 안 바꿨다)"
            else:
                im = s.image
                try:
                    ext = im.ext
                except Exception:  # 이미지로 읽히지 않는 바이트는 확장자를 못 알아낸다 — 쓰기 전 검사가 막는다
                    ext = "img"
                r.pic = (im.blob, ext, 0, 0)  # 이미지로 읽히는지는 쓰기 전에 따로 본다

    # 옮기지 못한 글: 견본에 있던 글이 아닌 남은 글·표·묶음·그림
    for s in slide.shapes:
        el = s._element
        if export_pptx._is_text(s) and s.left is not None and not export_pptx._has_fld(s):
            if id(el) in claimed:
                continue
            text = _raw(s)
            if text and not _same_as_static(geo, text, s.left, s.top):
                r.unmapped.append({"slide": k, "kind": "글", "text": text,
                                   "reason": "지도가 읽는 칸·번호 설명 어디에도 속하지 않는 글이라 작업본에 옮기지 못했다"})
        elif _is_group(s):
            t = _group_text(s)
            if t and not (s.left is not None and _same_as_static(geo, t, s.left, s.top)):
                r.unmapped.append({"slide": k, "kind": "묶음 도형", "text": t, "reason": "묶음 도형 안의 글은 지도가 읽지 않는다"})
        elif export_pptx._is_table(s):
            if _table_sig(s) not in geo.tables:
                r.unmapped.append({"slide": k, "kind": "표", "text": " | ".join(t for t in _table_sig(s) if t),
                                   "reason": "표는 지도가 읽지 않는다(견본의 표와 다르다)"})
        elif export_pptx._is_pic(s):
            if id(el) in claimed_pics:
                continue
            try:
                same = s.image.sha1 in geo.pic_hashes
            except Exception:
                same = False
            if not same:
                r.unmapped.append({"slide": k, "kind": "그림", "text": f"{s.name} ({s.width}x{s.height} EMU)",
                                   "reason": "그림 자리 밖의 그림은 지도가 읽지 않는다"})
    return r


# ---------------------------------------------------------------- 파일 이름 거꾸로 읽기

def _read_filename(fmap: dict, name: str, form: str) -> dict[str, str]:
    """`산출.파일명` 틀(`사용자매뉴얼_{LoB}_{제목}_v{버전}.pptx`)을 거꾸로 써서 올린 파일 이름에서 자리 값을 읽는다."""
    tpl = str(fmap["산출"]["파일명"])
    slots = fmap["산출"].get("자리") or {}
    parts = re.split(r"\{([^{}]+)\}", tpl)
    lits = [unicodedata.normalize("NFC", p).casefold() for p in parts[0::2]]
    names, is_ver = [], []
    for part in parts[1::2]:
        slot = norm(part)
        spec = slots.get(slot)
        if isinstance(spec, dict) and "표" in spec:
            raise ExportError(f"파일명 자리 {{{slot}}} 는 표에서 오는 값이라 파일 이름에서 읽을 수 없다", form=form, item=slot)
        names.append(slot)
        is_ver.append(isinstance(spec, dict) and norm(spec.get("메타", "")) == "버전")
    text = unicodedata.normalize("NFC", name)
    low = text.casefold()
    if len(low) != len(text):  # 대소문자 접기로 길이가 달라지는 글자가 있으면 위치를 맞출 수 없다
        raise ExportError(f"올린 파일 이름 {name!r} 에 대소문자 접기로 길이가 달라지는 글자가 있어 읽을 수 없다", form=form, item="파일명")
    splits: list[dict[str, str]] = []

    def walk(pos: int, k: int, acc: list[str]) -> None:
        """리터럴 k 를 pos 에서 맞춘 뒤 자리 k 의 가능한 모든 길이를 시도한다. 맞는 분할은 전부 모은다."""
        if not low.startswith(lits[k], pos):
            return
        pos += len(lits[k])
        if k == len(names):
            if pos == len(low):
                vals: dict[str, str] = {}
                for slot, v in zip(names, acc):
                    if vals.setdefault(slot, v) != v:
                        return  # 같은 자리가 두 번 나오는데 값이 다르다
                if vals not in splits:
                    splits.append(vals)
            return
        for end in range(pos + 1, len(text) + 1):
            v = text[pos:end]
            if is_ver[k] and not re.fullmatch(VERSION_RE, v):
                continue
            walk(end, k + 1, acc + [v])

    walk(0, 0, [])
    if not splits:
        raise ExportError(f"올린 파일 이름 {name!r} 이 지도의 파일명 틀 {tpl!r} 과 맞지 않아 자리 값(LoB·제목·판 등)을 읽지 못했다", form=form, item="파일명")
    if len(splits) > 1:
        shown = " / ".join(", ".join(f"{k}={v!r}" for k, v in s.items()) for s in splits[:3])
        raise ExportError(f"올린 파일 이름 {name!r} 에서 자리 값을 나누는 방법이 {len(splits)}가지라 하나로 정할 수 없다({shown}). 자리 값에 틀의 구분 글자(예: `_`)가 들어 있는지 확인한다",
                          form=form, item="파일명")
    return splits[0]


def _doc_name_slot(out_cfg: dict, form: str) -> str:
    """작업본 파일 이름(`<값>.md`)이 되는 파일명 자리. 지도 `산출.작업본_자리` 가 있으면 그것, 없으면 파일명 자리 중 폴더에도 안 쓰이고 `메타` 도 아닌 자리가 하나일 때 그것이다."""
    slots = out_cfg.get("자리") or {}
    names = list(dict.fromkeys(norm(m) for m in re.findall(r"\{([^{}]+)\}", str(out_cfg["파일명"]))))
    explicit = out_cfg.get("작업본_자리")
    if explicit is not None:
        e = norm(explicit)
        if e not in names:
            raise ExportError(f"지도 `산출.작업본_자리` {e!r} 가 `산출.파일명` 의 자리({', '.join(names)})에 없다", form=form, item="산출.작업본_자리")
        return e
    in_folder = {norm(m) for m in re.findall(r"\{([^{}]+)\}", str(out_cfg["폴더"]))}
    cands = [n for n in names if n not in in_folder and not (isinstance(slots.get(n), dict) and "메타" in slots[n])]
    if len(cands) != 1:
        raise ExportError(
            f"지도에서 작업본 파일 이름이 되는 자리를 정할 수 없다 — `산출.파일명` 의 자리 중 폴더에 안 쓰이고 `메타` 도 아닌 자리가 {len(cands)}개"
            f"({', '.join(cands) or '없음'})다. `산출.작업본_자리: <자리 이름>` 을 지도에 적는다(form-map.md)", form=form, item="산출.작업본_자리")
    return cands[0]


def _safe_img_name(title: str) -> str:
    s = _BAD_IMG_CHARS.sub("_", title).strip()
    s = re.sub(r"[. ]+$", lambda m: "_" * len(m.group(0)), s)
    return s if s and set(s) - {".", "_"} else "화면"


# ---------------------------------------------------------------- 작업본 쓰기

def _cell(v: str) -> str:
    return v.replace("|", "\\|")


def _guard(root: Path, rel: str, content: str) -> dict:
    """쓴 작업본에 문서 검사(훅 pre_write_guard 와 같은 `checker.cli` 검사 함수, `root/rules`)를 돌린다. 못 돌리면 unavailable."""
    from checker import cli
    from checker.model import ConfigError

    rules = root / "rules"
    if not rules.is_dir():
        return {"status": "unavailable", "reason": "rules/ 폴더가 없어 문서 검사를 하지 못했다(검사 불능, 통과 아님)", "violations": []}
    try:
        with tempfile.TemporaryDirectory(prefix="doc-guard-") as tmp:
            staged = Path(tmp) / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text(content, encoding="utf-8", newline="\n")
            report = cli._check_with_rules(rules, Path(tmp), [staged])
    except ConfigError as e:
        return {"status": "unavailable", "reason": f"규칙 설정 오류로 문서 검사를 하지 못했다(검사 불능, 통과 아님): {e}", "violations": []}
    except Exception as e:  # 검사를 못 한 것이지 통과도 위반도 아니다
        return {"status": "unavailable", "reason": f"문서 검사를 하지 못했다(검사 불능, 통과 아님): {type(e).__name__}: {e}", "violations": []}
    f = report["files"][0]
    status = {"pass": "pass", "violation": "violation", "out_of_scope": "out_of_scope"}.get(f["status"], f["status"])
    out = {"status": status, "type": f.get("type"), "violations": f["violations"]}
    if status == "out_of_scope":
        out["reason"] = "이 작업본은 어떤 규칙의 관할에도 들지 않아 검사되지 않았다(통과가 아니다)"
    return out


def _find_maps(root: Path, form: str | None) -> tuple[str, dict, Path]:
    if form:
        name = export.resolve_form(root, form)
        fmap, path = export.load_map(root, name)
        if not export_pptx.is_pptx_map(fmap):
            raise ExportError(f"양식 지도 {name} 의 템플릿이 .pptx 가 아니다", form=name)
        return name, fmap, path
    folder = root / "templates" / "forms"
    cands: list[str] = []
    bad: list[str] = []
    for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
            bad.append(f"{f.name}({type(e).__name__})")
            continue
        if isinstance(data, dict) and str(data.get("템플릿", "")).lower().endswith(".pptx"):
            cands.append(f.stem)
    note = f" 읽지 못한 지도: {', '.join(bad)}." if bad else ""
    if not cands:
        raise ExportError("templates/forms/ 에 템플릿이 .pptx 인 양식 지도가 없다." + note)
    if len(cands) > 1:
        raise ExportError(f"pptx 지도가 여럿이다({', '.join(cands)}) — --form <양식 이름> 으로 고른다." + note)
    if bad:
        raise ExportError(f"pptx 지도 {cands[0]} 말고 읽지 못한 지도가 있어 어느 것인지 확실하지 않다:{note[1:]} 고치거나 --form 으로 고른다.")
    fmap, path = export.load_map(root, cands[0])
    return cands[0], fmap, path


DEV_RE = re.compile(r"DEV-\d{3,}")  # rules/manual.yaml 의 묶은 개발 건 DEV 칸 패턴과 같다


def parse_devs(arg: str | None) -> list[str]:
    """`--dev DEV-001,DEV-002` → 목록. 형식이 틀리거나 비었거나 겹치면 ExportError(종료 2)."""
    if arg is None:
        return []
    devs = [d.strip() for d in arg.split(",")]
    bad = [d for d in devs if not DEV_RE.fullmatch(d)]
    if bad or not devs:
        raise ExportError(f"--dev 번호 형식이 `DEV-숫자3자리이상` 이 아니다: {', '.join(repr(b) for b in bad) or '(비었다)'}", item="--dev")
    if len(set(devs)) != len(devs):
        raise ExportError("--dev 에 같은 번호가 두 번 있다", item="--dev")
    return devs


def run(pptx: Path, root: Path, only_form: str | None, check_only: bool, devs: list[str] | None = None) -> tuple[int, dict]:
    form, fmap, map_path = _find_maps(root, only_form)
    tpl = export._inside(root, map_path.parent / str(fmap["템플릿"]), "템플릿", form)
    try:
        tprs = Presentation(str(tpl))
    except Exception as e:
        raise ExportError(f"양식 pptx {tpl} 를 읽지 못했다: {type(e).__name__}: {e}", form=form) from None
    try:
        uprs = Presentation(str(pptx))
    except Exception as e:
        raise ExportError(f"올린 pptx {pptx} 를 읽지 못했다: {type(e).__name__}: {e}", form=form) from None
    if (uprs.slide_width, uprs.slide_height) != (tprs.slide_width, tprs.slide_height):
        raise ExportError(
            f"올린 pptx 의 쪽 크기({uprs.slide_width}x{uprs.slide_height})가 양식({tprs.slide_width}x{tprs.slide_height})과 다르다 — 다른 양식의 파일이다",
            form=form)
    slides = list(uprs.slides)
    if not slides:
        raise ExportError("올린 pptx 에 쪽이 없다", form=form)

    slot_vals = _read_filename(fmap, pptx.name, form)
    out_cfg = fmap["산출"]
    slots_cfg = out_cfg.get("자리") or {}
    ver_slot = next((n for n in slot_vals if isinstance(slots_cfg.get(n), dict) and norm(slots_cfg[n].get("메타", "")) == "버전"), None)
    if ver_slot is None:
        raise ExportError("지도의 파일명에 `{메타: 버전}` 자리가 없어 올린 파일의 판을 읽을 수 없다", form=form, item="버전")
    name_slot = _doc_name_slot(out_cfg, form)
    version, title = slot_vals[ver_slot], slot_vals[name_slot]
    for slot, v in slot_vals.items():  # 파일 이름에서 읽은 값은 폴더·파일 이름 조각으로 다시 쓰이므로 export 와 같은 검사를 한다
        why = export._bad_folder_piece(v)
        if why:
            raise ExportError(f"올린 파일 이름에서 읽은 {{{slot}}} 값 {v!r} 을 폴더·파일 이름으로 쓸 수 없다: {why}", form=form, item=slot)

    # 작업본·그림 위치
    folder_tpl = str(out_cfg["폴더"])
    if "\\" in folder_tpl:
        raise ExportError(f"`산출.폴더` {folder_tpl!r} 에 역슬래시가 있다 — 폴더 구분은 `/` 로 쓴다", form=form, item="산출.폴더")
    t_parts, f_parts = folder_tpl.split("/"), []
    for tp in t_parts:
        def fill(m: re.Match) -> str:
            slot = norm(m.group(1))
            if slot not in slot_vals:
                raise ExportError(f"`산출.폴더` 의 {{{slot}}} 를 올린 파일 이름에서 읽을 수 없다(파일명 틀에 없는 자리)", form=form, item="산출.폴더")
            return slot_vals[slot]

        piece = re.sub(r"\{([^{}]+)\}", fill, tp)
        if "{" in tp:
            why = export._bad_folder_piece(piece)
            if why:
                raise ExportError(f"작업본 폴더 조각 {piece!r} 을 쓸 수 없다: {why}", form=form, item="산출.폴더")
        f_parts.append(piece)
    folder = "/".join(f_parts)
    spec_rel = f"{folder}/{title}.md"
    # 그림 위치는 캡처 도구(`manual_capture.image_rel`)와 같은 규칙이다: 작업본 폴더 이름을 LoB 자리로 쓴다(캡처가 spec_path.parent.name 을 쓴다)
    from checker.manual_capture import image_rel

    lob_dir = f_parts[-1]
    spec_path = export._inside(root, root / spec_rel, "작업본", form)
    export._inside(root, root / Path(image_rel(lob_dir, "x", version)).parent, "그림 폴더", form)
    if spec_path.exists():
        raise ExportError(f"같은 작업본 {spec_rel} 가 이미 있다 — 덮어쓰지 않는다. 지우거나 옮긴 뒤 다시 읽는다", form=form, item="작업본")

    geos = _geometry(tprs, fmap, form)
    shapes_by = [_text_shapes(s) for s in slides]
    assigned = _classify(slides, shapes_by, geos, form)
    reads = [_read_slide(s, k, geos[assigned[k - 1]]) for k, s in enumerate(slides, 1)]

    # 화면(반복 쪽)별로 합치고 쪽마다 모은다
    title_item = next((norm(g.pmap["목록"]["제목"]) for g in geos if g.pmap.get("목록")), None)
    if title_item is None:
        rep = next((g for g in geos if g.repeat and g.field_items), None)
        title_item = "화면 제목" if rep and "화면 제목" in rep.field_items else (rep.field_items[0] if rep else None)

    missing: list[dict] = []
    unmapped: list[dict] = []
    warnings: list[dict] = []
    per_page: dict[int, list[dict]] = {i: [] for i in range(len(geos))}  # 지도 쪽 번호 → 화면(또는 쪽) 목록

    def add_missing(sheet: str, item: str, reason: str) -> None:
        missing.append({"form": form, "sheet": sheet, "item": item, "reason": reason})

    for gi, rd in zip(assigned, reads):
        g = geos[gi]
        warnings += [{"form": form, "sheet": g.name, **w} for w in rd.warnings]
        unmapped += [{"form": form, "sheet": g.name, **u} for u in rd.unmapped]
        scr = per_page[gi]
        title_v = rd.values.get(title_item) if g.repeat and title_item else None
        if scr and not g.repeat:
            unmapped += [{"form": form, "sheet": g.name, "slide": rd.slide_no, "kind": "쪽",
                          "text": " / ".join(v for v in rd.values.values() if v) or "(글 없음)",
                          "reason": f"쪽 {g.name!r} 이 올린 pptx 에 둘 이상이다 — 첫 쪽만 읽었다"}]
            continue
        if scr and g.repeat and scr[-1]["slides"][-1] == rd.slide_no - 1:
            last = scr[-1]
            if title_v and title_v == last["title"]:
                last["slides"].append(rd.slide_no)  # 쪽당_최대로 넘어간 쪽 — 한 화면으로 합친다
                for it, v in rd.values.items():
                    cur = last["values"].get(it)
                    if cur is None and v is not None:
                        last["values"][it] = v
                        last["why"].pop(it, None)
                    elif v is not None and cur != v:
                        unmapped.append({"form": form, "sheet": f"{g.name} · {last['title']}", "slide": rd.slide_no, "kind": "글", "text": v,
                                         "reason": f"이어진 쪽의 {it} 이 첫 쪽과 다르다 — 첫 쪽 값만 읽었다"})
                last["notes"] += rd.notes
                if last["pic"] is None and rd.pic is not None:
                    last["pic"], last["pic_why"] = rd.pic, ""
                continue
            if rd.seq and rd.seq == last["seq"] and rd.seq not in {m.sample for m in g.marks if m.kind == "seq"}:
                warnings.append({"form": form, "sheet": g.name, "type": "seq-same-title-differs", "item": "순번",
                                 "reason": f"{rd.slide_no}번째 쪽은 앞 쪽과 순번({rd.seq})이 같지만 화면 제목이 달라 다른 화면으로 읽었다"})
        scr.append({"slides": [rd.slide_no], "title": title_v, "name": g.name, "values": dict(rd.values), "why": dict(rd.why),
                    "seq": rd.seq, "toc": rd.toc, "notes": list(rd.notes), "pic": rd.pic, "pic_why": rd.pic_why})

    # 올린 pptx 에 없는 쪽
    for gi, g in enumerate(geos):
        if not per_page[gi] and g.marks:
            add_missing(g.name, "쪽", f"올린 pptx 에서 {g.name!r} 쪽을 찾지 못했다")
            if not g.repeat:
                per_page[gi].append({"slides": [], "title": None, "name": g.name, "values": {it: None for it in g.field_items},
                                     "why": {it: "쪽이 없다" for it in g.field_items}, "notes": [], "pic": None, "pic_why": "쪽이 없다",
                                     "seq": "", "toc": []})

    # 화면 이름은 첫 화면 제목 값(없으면 순번). 같은 이름이 떨어져 둘이면 소절이 겹치므로 읽지 못함
    titles_in_order: list[str] = []
    for gi, g in enumerate(geos):
        if not g.repeat:
            continue
        seen: dict[str, int] = {}
        for n, sc in enumerate(per_page[gi], 1):
            sc["name"] = sc["title"] or f"화면 {n}"
            if sc["name"] in seen:
                raise ExportError(f"쪽 {g.name!r} 에 화면 이름 {sc['name']!r} 이 떨어져 두 번 나온다 — 소절 이름이 겹쳐 읽지 못한다(올린 {sc['slides'][0]}번째 쪽)",
                                  form=form, sheet=g.name)
            seen[sc["name"]] = n
            titles_in_order.append(sc["title"] or "")
    for gi, g in enumerate(geos):
        for sc in per_page[gi]:
            if sc["toc"] and g.marks and any(m.kind == "list" for m in g.marks):
                want = [t for t in titles_in_order if t]
                if sc["toc"] != want:
                    warnings.append({"form": form, "sheet": g.name, "type": "toc-differs", "item": "목록",
                                     "reason": f"올린 목차의 목록({sc['toc']})이 본문 화면 제목({want})과 다르다 — 목차 목록은 산출 때 본문 제목으로 다시 만든다"})

    writes: list[tuple[Path, bytes]] = []
    lines = [f"# {title}", "", f"버전: {version}", ""]
    for slot, spec in slots_cfg.items():
        if isinstance(spec, dict) and "메타" in spec and norm(spec["메타"]) != "버전" and norm(slot) in slot_vals:
            lines.insert(3, f"{norm(spec['메타'])}: {slot_vals[norm(slot)]}")
    lines += ["## 묶은 개발 건", "", "| DEV | 제목 |", "|---|---|"]
    # --dev 가 있으면 DEV 칸만 채운다(제목 칸은 규칙이 패턴 검사하지 않아 비워 둔다 — 모르는 제목을 지어내지 않는다). 없으면 `미정`
    lines += [f"| {d} |  |" for d in devs] if devs else ["| 미정 | 미정 |"]
    lines += ["", "## 양식 항목", ""]
    img_seen: set[str] = set()
    for gi, g in enumerate(geos):
        pmap = g.pmap
        if g.repeat and not per_page[gi]:
            continue  # 소절을 쓸 화면이 없다(missing 에 올렸다)
        screens = per_page[gi] or [None]
        for sc in screens:
            label = g.name + (f" · {sc['name']}" if g.repeat and sc else "")
            head = f"### {form} · {label}"
            body: list[str] = []
            if sc is None:
                lines += [head, "", "해당 없음", ""]
                continue
            multi: list[tuple[str, str]] = []
            rows: list[tuple[str, str]] = []
            for it in g.field_items:
                v = sc["values"].get(it)
                if v is None:
                    add_missing(label, it, sc["why"].get(it, "읽지 못했다"))
                    rows.append((it, export.UNDECIDED))
                elif "\n" in v:
                    multi.append((it, v))
                else:
                    rows.append((it, v))
            if rows:
                body += ["| 항목 | 값 |", "|---|---|"] + [f"| {it} | {_cell(v)} |" for it, v in rows] + [""]
            for it, v in multi:
                body += [f"#### {it}", "", v, ""]
            if pmap.get("그림"):
                pic_line = export.UNDECIDED
                if sc["pic"] is None:
                    add_missing(label, "그림", sc["pic_why"] or "그림을 읽지 못했다")
                else:
                    data, ext, iw, ih = sc["pic"]
                    ext = re.sub(r"[^a-z0-9]", "", (ext or "png").lower()) or "png"
                    ext = "jpg" if ext == "jpeg" else ext
                    try:  # 산출이 읽지 못하는 그림이면 파일을 쓰지 않고 `미정` 으로 둔다(쓰면 산출이 그림 파일을 읽지 못해 거부한다)
                        import io

                        from PIL import Image

                        with Image.open(io.BytesIO(data)) as im:
                            im.load()
                    except Exception as e:
                        add_missing(label, "그림", f"그림({ext})을 이미지로 읽지 못해 파일을 쓰지 않았다: {type(e).__name__}")
                        data = None
                    if data is not None:
                        fname = f"{_safe_img_name(sc['name'])}_v{version}.{ext}"
                        if fname in img_seen:
                            raise ExportError(f"그림 파일 이름 {fname!r} 이 겹친다(화면 이름이 같은 파일 이름이 된다)", form=form, sheet=label)
                        img_seen.add(fname)
                        rel = image_rel(lob_dir, fname[: -len(f"_v{version}.{ext}")], version)[: -len(".png")] + f".{ext}"
                        if (root / rel).exists():
                            raise ExportError(f"같은 이름의 그림 {rel} 가 이미 있다 — 덮어쓰지 않는다", form=form, sheet=label, item="그림")
                        writes.append((export._inside(root, root / rel, "그림", form), data))
                        pic_line = rel
                        if ext != "png":
                            warnings.append({"form": form, "sheet": label, "type": "image-not-png", "item": "그림",
                                             "reason": f"그림이 PNG 가 아니다({ext}). 산출은 이미지 라이브러리(PIL)가 읽는 형식이면 받지만 매뉴얼 스킬은 PNG 를 권한다"})
                body += ["#### 그림", "", pic_line, ""]
            if pmap.get("번호_설명"):
                if not sc["notes"]:
                    add_missing(label, "번호 설명", "번호 도형을 하나도 찾지 못했다")
                    body += ["#### 번호 설명", "", export.UNDECIDED, ""]
                else:
                    nums = [n for n, _ in sc["notes"]]
                    if len(set(nums)) != len(nums):
                        warnings.append({"form": form, "sheet": label, "type": "number-repeated", "item": "번호 설명",
                                         "reason": "번호가 겹친다: " + ", ".join(sorted({n for n in nums if nums.count(n) > 1}))})
                    body += ["#### 번호 설명", ""]
                    for n, t in sc["notes"]:
                        if t is None:
                            add_missing(label, f"번호 설명 {n}", "번호 도형 오른쪽에서 같은 높이의 글상자를 찾지 못했다")
                            t = export.UNDECIDED
                        body.append(f"{n}. " + t.replace("\n", "\n   "))
                    body.append("")
            if not body:
                body = ["해당 없음", ""]
            lines += [head, ""] + body
    while lines and lines[-1] == "":
        lines.pop()
    text = "\n".join(lines) + "\n"

    # 쓴 작업본을 export 가 읽을 수 있는지 먼저 본다(읽지 못하면 아무것도 쓰지 않는다)
    try:
        sections = export.parse_spec(text)[form]
        export_pptx.normalize_sections(fmap, sections, form)
    except ExportError as e:
        raise ExportError(f"읽어 들인 작업본이 지도와 맞지 않는다(import 의 오류): {e.reason}", form=form) from None

    writes.insert(0, (spec_path, text.encode("utf-8")))
    planned = [p.relative_to(root.resolve()).as_posix() for p, _ in writes]
    guard = _guard(root, spec_rel, text)
    code = EXIT_INCOMPLETE if (missing or unmapped) else EXIT_OK
    if not check_only:
        written = export._commit(writes, root.resolve())
    else:
        written = []
    page_log = [{"slide": rd.slide_no, "page": geos[gi].name} for gi, rd in zip(assigned, reads)]
    nxt = ["다음:"]
    if missing:
        nxt.append(f"못 찾은 칸 {len(missing)}개는 작업본에 `미정` 으로 썼다 — 올린 pptx 에서 그 칸을 다시 확인하거나 작업본에 직접 채운다.")
    if unmapped:
        nxt.append(f"옮기지 못한 글 {len(unmapped)}개는 버리지 않았다 — 어디(어느 칸·번호 설명)에 넣을지 정해 작업본에 반영한다.")
    if devs:
        nxt.append(f"`## 묶은 개발 건` 표에 {', '.join(devs)} 를 썼다(제목 칸은 비웠다 — 알면 채운다).")
    else:
        nxt.append("`## 묶은 개발 건` 표는 pptx 에 정보가 없어 `미정` 으로 썼다 — 이 매뉴얼이 다루는 DEV 번호를 채워야 문서 검사를 통과한다(`--dev` 로 줄 수 있다).")
    if guard["status"] == "unavailable":
        nxt.append("문서 검사는 하지 못했다(검사 불능, 통과 아님).")
    nxt.append(f"종료코드 0 이어도 `doc_guard.status` 가 `pass` 가 아니면(지금 `{guard['status']}`) 문서 검사를 통과한 것이 아니다.")
    if check_only:
        nxt.append("--check 라서 아무것도 쓰지 않았다. --check 없이 다시 실행하면 쓴다.")
    report = {
        "status": "ok" if code == EXIT_OK else "incomplete",
        "dry_run": check_only,
        "form": form,
        "spec": spec_rel,
        "version": version,
        "files": written,
        "planned": planned,
        "pages": page_log,
        "missing": missing,
        "unmapped": unmapped,
        "problems": [],
        "warnings": warnings,
        "doc_guard": guard,
        "next": " ".join(nxt),
    }
    return code, report


# ---------------------------------------------------------------- 진입점

def _error_report(reason: str, form: str = "", sheet: str = "", item: str = "") -> dict:
    return {
        "status": "error",
        "files": [],
        "missing": [],
        "unmapped": [],
        "problems": [{"form": form, "sheet": sheet, "item": item, "reason": reason}],
        "warnings": [],
        "next": "다음: 읽지 못한 원인을 고친 뒤 다시 시도한다. 아무것도 쓰지 않았다 — 통과도 위반도 아니라 검사 불능이다.",
    }


def main(argv: list[str] | None = None) -> int:
    export._force_utf8()
    parser = argparse.ArgumentParser(prog="python -m checker.import_pptx",
                                     description="사람이 양식 pptx 에 써서 올린 매뉴얼을 작업본(md)과 그림으로 읽어 들인다.")
    parser.add_argument("--pptx", type=Path, required=True, help="올린 매뉴얼 pptx(파일 이름은 지도의 `산출.파일명` 틀대로)")
    parser.add_argument("--root", type=Path, required=True, help="Project Repository 루트")
    parser.add_argument("--form", help="양식 이름 또는 지도 파일 경로. pptx 지도가 여럿이면 필수")
    parser.add_argument("--check", action="store_true", help="아무것도 쓰지 않고 읽은 결과·계획만 낸다")
    parser.add_argument("--dev", help="이 매뉴얼이 다루는 DEV 번호(쉼표로 여럿: DEV-001,DEV-002). 주면 `## 묶은 개발 건` 표를 채운다. 생략하면 `미정`")
    args = parser.parse_args(argv)
    try:
        devs = parse_devs(args.dev)
        root = args.root.resolve()
        if not root.is_dir():
            raise ExportError(f"--root {args.root} 가 폴더가 아니다")
        if not args.pptx.is_file():
            raise ExportError(f"--pptx {args.pptx} 파일이 없다")
        code, report = run(args.pptx, root, args.form, args.check, devs)
    except ExportError as e:
        code, report = EXIT_ERROR, _error_report(e.reason, e.form, e.sheet, e.item)
    except Exception as e:  # 예상하지 못한 오류도 검사 불능(2)이다
        code, report = EXIT_ERROR, _error_report(f"예상하지 못한 오류({type(e).__name__}): {e}")
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
