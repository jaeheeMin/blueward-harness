"""Spec 의 화면 캡처 그림을 개발사양서 화면 시트에 넣고 번호별 설명을 채운다(#348).

Spec 작업본 `## 양식 항목` 의 `### <양식> · <시트>` 아래에 `#### <화면 이름> 캡처` 절을 두면, 산출(`checker.export`)이
지도 시트 항목의 `화면:` 안 `캡처:` 가 정한 영역에 PNG 그림을 넣고, 번호별 설명을 `설명` 범위의 첫 열에 한 행씩 쓴다.
영역·설명 범위는 코드가 아니라 지도(데이터)가 정한다. 못 넣으면 조용히 빼지 않고 산출을 멈춘다.

지도(시트 항목의 `화면:` 항목)
        캡처:
          영역: C7:S14      # 선택. 생략하면 그 화면의 `영역`. 그림이 이 안에 비율을 지켜 맞춰 들어간다
          설명: U7:V20      # 필수. 번호별 설명을 쓸 칸 범위. 첫 열에 한 행씩 `① 설명` 으로 쓴다(21번부터 `(21) 설명`)

작업본(md)
    #### 화면 1 캡처
    ![대체 글](docs/spec/img/DEV-001_화면1_v0.1.png)     저장소 루트 기준 상대 경로, 정확히 한 줄, PNG 만
    | 번호 | 설명 |
    |---|---|
    | 1 | 판매 조직을 고른다 |           번호는 1부터 연속 정수, 한 행 이상

멈추는 경우(거절): 그림 파일이 없다 / PNG 가 아니다 / 파일 이름의 판(`_v0.1`)이 없거나 산출 판과 다르다(캡처가 옛 판) /
같은 화면의 `그림`(셀로 그린 것)과 캡처 영역이 겹친다 / 그림을 `MIN_SCALE` 미만으로 줄여야 영역에 들어간다 /
설명이 `설명` 범위 행 수보다 많다 / 범위 안에 견본 값이 남아 있다 / 시트에 이미 drawing(그림·도형)이 있다.

크기 계산은 어림값이다 — 열 너비는 기본 글꼴 숫자 한 글자 폭을 `MDW_PX` 픽셀로 보고, PNG 는 96dpi(1픽셀=9525 EMU)로 본다.
PNG 크기는 헤더(IHDR)만 읽는다(Pillow 를 쓰지 않는다). 그림은 영역 왼쪽 위에 붙이고 늘리지 않는다.
"""
from __future__ import annotations

import posixpath
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from checker.blank_template import RangeError, _hit, parse_range
from checker.export import ExportError, SheetXml, _ATTR_RE, _BR, _clean, _inside, col2n, n2col, norm, split_ref

MIN_SCALE = 0.5  # 영역에 맞추려 원본의 이 비율(50%) 미만으로 줄여야 하면 글씨가 안 보일 수 있어 멈춘다
MDW_PX = 7  # 열 너비 1 = 기본 글꼴 숫자 한 글자 폭(11pt 기준 7px). 어림값
DEFAULT_COL_PX = 64
DEFAULT_ROW_PT = 15.0
EMU_PER_PX = 9525  # 96dpi
EMU_PER_PT = 12700
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_VERSION = re.compile(r"_[vV](\d+(?:\.\d+)*)$")  # 파일 이름(확장자 앞) 끝
_VERSION_ANYWHERE = re.compile(r"_[vV]\d")

_CT_DRAWING = "application/vnd.openxmlformats-officedocument.drawing+xml"
_REL_DRAWING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@dataclass
class Placement:
    """시트에 넣을 그림 하나."""
    label: str  # `화면 1 캡처`
    png: bytes
    alt: str
    col: int  # 영역 왼쪽 위(1부터)
    row: int
    cx: int  # EMU
    cy: int
    version: str | None  # 그림 파일 이름의 판
    path: str


# ---------------------------------------------------------------- PNG·크기

def png_size(data: bytes) -> tuple[int, int] | None:
    """PNG 헤더(IHDR)의 (너비, 높이) 픽셀. PNG 가 아니거나 헤더가 깨졌으면 None."""
    if len(data) < 33 or not data.startswith(_PNG_SIGNATURE):
        return None
    length, kind = struct.unpack(">I4s", data[8:16])
    if kind != b"IHDR" or length != 13:
        return None
    w, h = struct.unpack(">II", data[16:24])
    return (w, h) if w > 0 and h > 0 else None


def file_version(name: str) -> str | None:
    """파일 이름 끝(확장자 앞)의 판 번호(`_v0.1` → `0.1`, 앞 `v` 는 뗀다). 끝에 없으면 None."""
    m = _VERSION.search(Path(name).stem)
    return m.group(1) if m else None


def circled(n: int) -> str:
    """번호 표기: 1~20 은 원문자 ①~⑳, 그 위는 `(21)`."""
    return chr(0x2460 + n - 1) if 1 <= n <= 20 else f"({n})"


def _sheet_format(xml: str) -> tuple[int, float]:
    """(기본 열 너비 px, 기본 행 높이 pt)."""
    m = re.search(r"<sheetFormatPr\b[^>]*>", xml)
    a = dict(_ATTR_RE.findall(m.group(0))) if m else {}
    col_px, row_pt = DEFAULT_COL_PX, DEFAULT_ROW_PT
    try:
        if a.get("defaultColWidth"):
            col_px = int(float(a["defaultColWidth"]) * MDW_PX + 0.5)
    except ValueError:
        pass
    try:
        if a.get("defaultRowHeight"):
            row_pt = float(a["defaultRowHeight"])
    except ValueError:
        pass
    return col_px, row_pt


def box_emu(ed: SheetXml, rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """영역의 (너비, 높이) EMU. 열 너비(`<cols>`·기본 너비)와 행 높이(`ht`·기본 높이), 숨긴 열·행은 0 으로 센다."""
    xml = ed.pre + ed.post
    default_col, default_row = _sheet_format(xml)
    widths: dict[int, int] = {}
    for m in re.finditer(r"<col\b[^>]*>", xml):
        a = dict(_ATTR_RE.findall(m.group(0)))
        try:
            lo, hi = int(a["min"]), int(a["max"])
            px = 0 if a.get("hidden") in ("1", "true") else int(float(a["width"]) * MDW_PX + 0.5)
        except (KeyError, ValueError):
            continue
        for c in range(max(lo, rect[0]), min(hi, rect[2]) + 1):
            widths[c] = px
    c0, r0, c1, r1 = rect
    w_px = sum(widths.get(c, default_col) for c in range(c0, c1 + 1))
    h_pt = 0.0
    for r in range(r0, r1 + 1):
        row = ed.rows.get(r)
        attrs = dict(row.attrs) if row else {}
        if attrs.get("hidden") in ("1", "true"):
            continue
        try:
            h_pt += float(attrs["ht"]) if "ht" in attrs else default_row
        except ValueError:
            h_pt += default_row
    return w_px * EMU_PER_PX, int(h_pt * EMU_PER_PT)


# ---------------------------------------------------------------- 검사·배치

def has_drawing(sheet_xml: str, sheet_rels: str | None) -> bool:
    """시트에 이미 drawing(그림·도형·차트)이 걸려 있는가."""
    if re.search(r"<drawing\b", sheet_xml):
        return True
    return bool(sheet_rels and re.search(r'Type="[^"]*/drawing"', sheet_rels))


def _merge_traps(ed: SheetXml, refs: list[str]) -> list[str]:
    """병합의 왼쪽 위가 아닌 칸(쓰면 엑셀에서 안 보이는 칸)."""
    traps = []
    for m in re.finditer(r'<mergeCell\b[^>]*\bref="([A-Z]+\d+):([A-Z]+\d+)"', ed.post):
        (a, ar), (b, br) = split_ref(m.group(1)), split_ref(m.group(2))
        for ref in refs:
            c, r = split_ref(ref)
            if col2n(a) <= col2n(c) <= col2n(b) and ar <= r <= br and (c, r) != (a, ar):
                traps.append(ref)
    return traps


def plan(
    item: dict, body: list[str], sname: str, ed: SheetXml, root: Path, form: str, problem, put,
    picture_drawn: bool, existing_drawing: bool = False,
) -> Placement | None:
    """한 화면의 캡처 절을 검사하고 설명 칸을 쓴다. 넣을 그림을 낸다. 막히면 problem 으로 알리고 None(설명도 쓰지 않는다).

    `picture_drawn` 은 같은 화면의 `#### … 그림` 절이 있어 셀로 그렸다는 뜻이다. `existing_drawing` 은 시트에 이미 drawing 이 있다는 뜻이다.
    표 구조·경로 모양은 `screen_draw.capture_offenders` 가 먼저 거절했으므로 여기서는 값 문제만 본다.
    """
    from checker import screen_draw

    label = screen_draw.capture_name(item)
    cap = item["캡처"]
    ok = True

    def stop(reason: str) -> None:
        nonlocal ok
        ok = False
        problem(sname, label, reason)

    imgs, _, _, _ = screen_draw.parse_capture(body, label)
    path = imgs[0][2]
    alt = imgs[0][1].strip() or item["이름"]
    rows = screen_draw.capture_rows(body, label)
    try:
        area = parse_range(cap["영역"])
        desc = parse_range(cap["설명"])
        pic_area = parse_range(item["영역"])
    except RangeError as e:  # 지도 검증이 먼저 걸러 오지만 단독 호출에도 조용히 넘기지 않는다
        raise ExportError(f"{label}: 지도 범위 오류: {e.reason}", form=form, sheet=sname, item=label) from None

    if existing_drawing:
        stop(f"시트 {sname} 에 이미 그림·도형(drawing)이 있어 캡처 그림을 넣지 않는다 — 그림이 있는 시트에는 아직 덧붙이지 않는다. 템플릿의 그림을 지운 빈 양식을 쓴다")
    if picture_drawn and _hit(pic_area, area):
        stop(
            f"{item['이름']} 에 `그림`(셀로 그린 화면)과 `캡처` 가 둘 다 있고 두 영역이 겹친다(그림 {item['영역']}, 캡처 {cap['영역']}) — "
            f"둘 중 하나만 쓰거나 지도에서 캡처 `영역` 을 그림 영역과 겹치지 않게 따로 잡는다"
        )

    # 그림 파일
    png, size = None, None
    try:
        file = _inside(root, root / path, "캡처 그림", form)
    except ExportError as e:
        stop(f"그림 경로 {path!r} 가 저장소({root}) 밖을 가리킨다: {e.reason}")
        file = None
    if file is not None:
        if not file.is_file():
            stop(f"그림 파일 {path} 가 없다 — 화면을 캡처해 저장소 루트 기준 이 경로에 PNG 로 저장한다")
        else:
            try:
                png = file.read_bytes()
            except OSError as e:
                stop(f"그림 파일 {path} 를 읽지 못했다: {e}")
            else:
                size = png_size(png)
                if size is None:
                    stop(f"그림 파일 {path} 가 PNG 가 아니거나 PNG 헤더(IHDR)를 읽지 못했다 — 화면을 PNG 로 다시 저장한다")
    version = file_version(path)
    if version is None and _VERSION_ANYWHERE.search(Path(path).stem):
        stop(f"그림 파일 이름 {Path(path).name!r} 의 판 번호는 파일 이름 끝(확장자 바로 앞)에 `_v<판>` 으로 둔다 — 이름 중간의 `_v…` 는 판으로 보지 않는다")
    elif version is None:
        stop(f"그림 파일 이름 {Path(path).name!r} 에 판 번호(`_v0.1`)가 없다 — 캡처가 어느 판인지 알 수 없어 넣지 않는다. 파일 이름 끝을 `_v<판>` 으로 한다")

    # 크기
    cx = cy = 0
    if size is not None:
        bw, bh = box_emu(ed, area)
        iw, ih = size[0] * EMU_PER_PX, size[1] * EMU_PER_PX
        if bw <= 0 or bh <= 0:
            stop(f"캡처 영역 {cap['영역']} 의 크기가 0 이다(숨긴 열·행뿐이다)")
        else:
            scale = min(1.0, bw / iw, bh / ih)
            if scale < MIN_SCALE:
                stop(
                    f"그림 {path}({size[0]}x{size[1]}px)을 영역 {cap['영역']}(약 {bw // EMU_PER_PX}x{bh // EMU_PER_PX}px)에 맞추려면 "
                    f"원본의 {scale * 100:.0f}% 로 줄여야 한다(기준 {MIN_SCALE * 100:.0f}% 미만이면 글씨가 안 보일 수 있다) — "
                    "지도에서 캡처 영역을 넓히거나, 캡처를 잘라서(필요한 부분만) 다시 찍는다"
                )
            else:
                cx, cy = int(iw * scale), int(ih * scale)

    # 영역·설명 범위의 견본
    c0, r0, c1, r1 = area
    under = [r for r in ed.valued_refs() if c0 <= col2n(split_ref(r)[0]) <= c1 and r0 <= split_ref(r)[1] <= r1]
    if under:
        stop(f"캡처 영역 {cap['영역']} 안에 이미 값이 있다({', '.join(under[:5])}{' …' if len(under) > 5 else ''}) — 그림이 덮는다. 지도 `비우기` 로 지운 빈 양식을 템플릿으로 쓴다")
    d0, dr0, d1, dr1 = desc
    left = [r for r in ed.valued_refs() if d0 <= col2n(split_ref(r)[0]) <= d1 and dr0 <= split_ref(r)[1] <= dr1]
    if left:
        stop(f"설명 범위 {cap['설명']} 안에 이미 값이 있다({', '.join(left[:5])}{' …' if len(left) > 5 else ''}) — 견본이 남은 자리에는 쓰지 않는다. 지도 `비우기` 에 이 범위를 넣거나 빈 양식을 템플릿으로 쓴다")
    room = dr1 - dr0 + 1
    if len(rows) > room:
        stop(f"설명이 {len(rows)}행이라 설명 범위 {cap['설명']}({room}행)를 넘는다 — 지도에서 설명 범위를 늘리거나 설명을 줄인다(자르지 않는다)")
    refs = [f"{n2col(d0)}{dr0 + k}" for k in range(min(len(rows), room))]
    traps = _merge_traps(ed, refs)
    if traps:
        stop(f"설명 칸 {', '.join(traps[:5])} 이 병합 셀의 왼쪽 위가 아니라 값을 써도 보이지 않는다 — 지도의 설명 범위를 병합의 왼쪽 위 열에서 시작하게 잡는다")
    texts = []
    for k, (_, desc_text) in enumerate(rows, start=1):
        text = _clean(_BR.sub("\n", desc_text))
        if not text:
            stop(f"{k}번 설명이 비어 있거나 미정이다 — 설명을 적거나 행을 지운다")
        texts.append(f"{circled(k)} {text}")
    if not ok or png is None:
        return None
    for ref, text in zip(refs, texts):
        put(label, ref, text, as_text=True)
    return Placement(label, png, alt, c0, r0, cx, cy, version, path)


# ---------------------------------------------------------------- 조립

def _next_number(names, pattern: str) -> int:
    nums = [int(m.group(1)) for n in names if (m := re.match(pattern, n))]
    return max(nums, default=0) + 1


def _drawing_xml(items: list[Placement]) -> str:
    anchors = []
    for i, p in enumerate(items):
        name = escape(p.label, {'"': "&quot;"})
        alt = escape(p.alt, {'"': "&quot;"})
        anchors.append(
            "<xdr:oneCellAnchor>"
            f"<xdr:from><xdr:col>{p.col - 1}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{p.row - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f'<xdr:ext cx="{p.cx}" cy="{p.cy}"/>'
            f'<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="{i + 2}" name="{name}" descr="{alt}"/>'
            '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
            f'<xdr:blipFill><a:blip xmlns:r="{_NS_R}" r:embed="rId{i + 1}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
            f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{p.cx}" cy="{p.cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + "".join(anchors) + "</xdr:wsDr>"
    )


_AFTER_DRAWING = frozenset(
    ("legacyDrawing", "legacyDrawingHF", "drawingHF", "picture", "oleObjects", "controls", "webPublishItems", "tableParts", "extLst")
)
_TAG = re.compile(r"<!--.*?-->|<\?.*?\?>|<!\[CDATA\[.*?\]\]>|<(/?)([A-Za-z_][\w.:-]*)(?:[^>\"']|\"[^\"]*\"|'[^']*')*?(/?)>", re.S)


def _top_level_pos(xml: str, start: int) -> int | None:
    """`start` 부터 `<worksheet>` 의 직접 자식(깊이 1) 중 `<drawing>` 뒤에 와야 하는 첫 요소의 위치. 중첩 요소 안의 같은 이름(cfRule 안 extLst 등)은 건너뛴다."""
    depth = 1  # <worksheet> 안
    for m in _TAG.finditer(xml, start):
        close, name, selfclose = m.group(1), m.group(2), m.group(3)
        if name is None:
            continue
        if close:
            depth -= 1
            if depth < 1:
                return None
            continue
        if depth == 1 and name.rpartition(":")[2] in _AFTER_DRAWING:
            return m.start()
        if not selfclose:
            depth += 1
    return None


def _with_drawing(xml: str, rid: str) -> str:
    """시트 XML 에 `<drawing r:id=…/>` 를 OOXML 순서(pageSetup·headerFooter 등 뒤, legacyDrawing 앞)에 넣는다."""
    root = re.search(r"<worksheet\b[^>]*>", xml)
    if not root:
        raise ExportError("시트 XML 의 루트가 `<worksheet>` 가 아니라(이름공간 접두어) 캡처 그림을 넣지 못한다")
    tag = root.group(0)
    if "xmlns:r=" not in tag:
        xml = xml[: root.start()] + tag[:-1] + f' xmlns:r="{_NS_R}">' + xml[root.end():]
    if "</sheetData>" in xml:
        end = xml.index("</sheetData>") + len("</sheetData>")
    else:  # `<sheetData/>`
        end = xml.index("<sheetData")
        end = xml.index(">", end) + 1
    pos = _top_level_pos(xml, end)
    if pos is None:
        pos = xml.rindex("</worksheet>")
    return xml[:pos] + f'<drawing r:id="{rid}"/>' + xml[pos:]


def assemble(
    raw: dict[str, bytes], paths: dict[str, str], rendered: dict[str, str], placements: dict[str, list[Placement]]
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """그림 파트들을 만든다. `rendered`(시트 경로 → 시트 XML)는 `<drawing>` 이 들어간 것으로 바뀐다.

    (바뀐 기존 파트 {이름: 바이트}, 새 파트 {이름: 바이트}) 를 낸다. 기존 파트: `[Content_Types].xml`, 시트 rels. 번호는 기존 이름과 겹치지 않게 잡는다.
    """
    ct_name = "[Content_Types].xml"
    if ct_name not in raw:
        raise ExportError("템플릿에 [Content_Types].xml 이 없어 그림 파트를 등록하지 못한다")
    ct_bytes = raw[ct_name]
    ct = ct_bytes.decode("utf-8-sig")
    names = set(raw)
    changed: dict[str, bytes] = {}
    new: dict[str, bytes] = {}
    overrides = ""
    for sname, items in placements.items():
        sheet_path = paths[sname]
        dn = _next_number(names, r"^xl/drawings/drawing(\d+)\.xml$")
        drawing = f"xl/drawings/drawing{dn}.xml"
        names.add(drawing)
        rels = []
        for i, p in enumerate(items):
            inum = _next_number(names, r"^xl/media/image(\d+)\.")
            image = f"xl/media/image{inum}.png"
            names.add(image)
            new[image] = p.png
            rels.append(f'<Relationship Id="rId{i + 1}" Type="{_REL_IMAGE}" Target="../media/image{inum}.png"/>')
        new[drawing] = _drawing_xml(items).encode("utf-8")
        new[f"xl/drawings/_rels/drawing{dn}.xml.rels"] = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>"
        ).encode("utf-8")
        overrides += f'<Override PartName="/{drawing}" ContentType="{_CT_DRAWING}"/>'

        d, _, base = sheet_path.rpartition("/")
        rels_path = f"{d}/_rels/{base}.rels"
        target = posixpath.relpath(drawing, d)
        if rels_path in raw:
            text = raw[rels_path].decode("utf-8-sig")
            used = {m.group(2) for m in re.finditer(r"""\bId\s*=\s*(["'])(.*?)\1""", text)}
            rid = "rId" + str(_next_number(used, r"^rId(\d+)$"))
            rel = f'<Relationship Id="{rid}" Type="{_REL_DRAWING}" Target="{target}"/>'
            if "</Relationships>" not in text:
                raise ExportError(f"시트 관계 파일 {rels_path} 의 모양을 몰라 그림 관계를 덧붙이지 못한다")
            bom = b"\xef\xbb\xbf" if raw[rels_path].startswith(b"\xef\xbb\xbf") else b""
            changed[rels_path] = bom + text.replace("</Relationships>", rel + "</Relationships>", 1).encode("utf-8")
        else:
            rid = "rId1"
            new[rels_path] = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="{rid}" Type="{_REL_DRAWING}" Target="{target}"/></Relationships>'
            ).encode("utf-8")
        rendered[sheet_path] = _with_drawing(rendered[sheet_path], rid)

    add = ""
    if not re.search(r"""<Default\b[^>]*\bExtension\s*=\s*(["'])png\1""", ct, re.I):
        add += '<Default Extension="png" ContentType="image/png"/>'
    if "</Types>" not in ct:
        raise ExportError("[Content_Types].xml 의 모양을 몰라 그림 파트를 등록하지 못한다")
    # Default 는 Override 보다 앞에 둔다(관례). 기존 첫 Default·Override 앞이 아니라 끝에 덧붙여도 유효하다.
    bom = b"\xef\xbb\xbf" if ct_bytes.startswith(b"\xef\xbb\xbf") else b""
    changed[ct_name] = bom + ct.replace("</Types>", add + overrides + "</Types>", 1).encode("utf-8")
    return changed, new
