"""산출 xlsx 에 셀 서식(채우기·테두리·글꼴·정렬)과 병합을 쓰는 기반(#335, PR C1).

개발사양서의 화면 시트에 필터 바·액션·결과 테이블 모양을 그리려면 셀에 서식을 입히고 칸을 병합해야 한다. 색·테두리·
글꼴은 코드가 아니라 데이터라서 지도(`templates/forms/<양식>.yaml`)가 정한다. 이 모듈은 그 정의(한국어 키 dict)를
검증하고 `styles.xml`·시트 XML 에 반영하는 도구만 준다. 지도 문법을 export 흐름에 잇는 것은 PR C2 다.

스타일 정의(dict)의 키. 적은 것만 덮어쓰고 안 적은 부분은 셀의 기존 서식(템플릿의 글꼴·숫자 형식 등)을 따른다.
    채우기: "DDEBF7" | "없음"          배경색(RRGGBB). 없음은 채우기 제거.
    테두리: 얇게 | 중간 | 굵게 | 없음   네 변 모두. 범위에 쓰면 범위의 모든 칸에 그린다(바깥선만이 아니다).
    테두리_색: "000000"               테두리 색(RRGGBB). 안 적으면 자동. `테두리` 가 선 종류일 때만 쓴다.
    굵게: true | false
    글꼴_크기: 9                      pt (0 초과 409 이하 숫자)
    글꼴_색: "000000"                 RRGGBB
    가로: 왼쪽 | 가운데 | 오른쪽
    세로: 위 | 가운데 | 아래
    줄바꿈: true | false
모르는 키·잘못된 값은 조용히 무시하지 않고 `validate_style` 이 사유로 돌려준다. 쓰는 쪽(`StylesXml.derive`)은 정의가
틀리면 ExportError 로 멈춘다(검사 불능을 통과로 뭉개지 않는다).

쓰기는 openpyxl 을 쓰지 않는다. `styles.xml` 의 fonts·fills·borders·cellXfs 에 항목만 덧붙이고(같은 것은 재사용),
dxfs·cellStyleXfs·numFmts 등 나머지는 바이트 그대로 둔다.
"""
from __future__ import annotations

import re
import unicodedata

from checker.blank_template import _col_style, parse_range
from checker.export import ExportError, SheetXml, col2n, n2col

MAX_STYLED_CELLS = 100_000

_HEX = re.compile(r"^[0-9A-Fa-f]{6}$")
_BORDER_STYLES = {"얇게": "thin", "중간": "medium", "굵게": "thick", "없음": None}
_HORIZONTAL = {"왼쪽": "left", "가운데": "center", "오른쪽": "right"}
_VERTICAL = {"위": "top", "가운데": "center", "아래": "bottom"}
STYLE_KEYS = ("채우기", "테두리", "테두리_색", "굵게", "글꼴_크기", "글꼴_색", "가로", "세로", "줄바꿈")

_ATTR = re.compile(r"""([\w:]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
MAX_CELL_XFS = 64000  # 엑셀 cellXfs 한도


def _attrs(text: str, what: str) -> list[tuple[str, str]]:
    """속성 문자열을 읽는다(큰따옴표·작은따옴표). 못 읽는 조각이 남으면 말없이 버리지 않고 ExportError."""
    found = [(m.group(1), m.group(2) if m.group(2) is not None else m.group(3)) for m in _ATTR.finditer(text)]
    if _ATTR.sub("", text).strip().rstrip("/").strip():
        raise ExportError(f"{what} 의 속성을 모두 읽지 못했다: {text.strip()[:80]}")
    return found


def _q(value: str) -> str:
    return value.replace('"', "&quot;")
# CT_Font 자식 순서(엑셀은 이 순서를 요구한다).
_FONT_ORDER = ("b", "i", "strike", "condense", "extend", "outline", "shadow", "u", "vertAlign", "sz", "color", "name", "family", "charset", "scheme")


def _key(k) -> str:
    return unicodedata.normalize("NFC", str(k)).strip()


def validate_style(defn) -> list[str]:
    """스타일 정의의 문제를 사유 목록으로 낸다. 빈 목록이면 쓸 수 있는 정의다."""
    if not isinstance(defn, dict):
        return [f"스타일 정의는 키: 값 목록이어야 한다(받은 값 {defn!r})"]
    out: list[str] = []
    d: dict = {}
    for k, v in defn.items():
        kk = _key(k)
        if kk not in STYLE_KEYS:
            out.append(f"스타일 키 {kk!r} 는 모른다 — 가능한 키: {', '.join(STYLE_KEYS)}")
        elif kk in d:
            out.append(f"스타일 키 {kk!r} 가 두 번 적혔다")
        else:
            d[kk] = v
    if not d and not out:
        return ["스타일 정의가 비어 있다 — 적용할 키가 하나도 없다"]

    def hexcolor(key: str) -> None:
        v = d[key]
        if not (isinstance(v, str) and _HEX.match(v.strip())):
            out.append(f"{key} {v!r} 는 RRGGBB 6자리 16진수 문자열이어야 한다(예: DDEBF7. 숫자만이면 따옴표로 감싼다)")

    def choice(key: str, allowed) -> None:
        v = d[key]
        if not (isinstance(v, str) and _key(v) in allowed):
            out.append(f"{key} {v!r} 는 {' | '.join(allowed)} 중 하나여야 한다")

    if "채우기" in d:
        v = d["채우기"]
        if not (isinstance(v, str) and (_key(v) == "없음" or _HEX.match(v.strip()))):
            out.append(f"채우기 {v!r} 는 RRGGBB 6자리 16진수 문자열 또는 없음이어야 한다(숫자만이면 따옴표로 감싼다)")
    if "테두리" in d:
        choice("테두리", _BORDER_STYLES)
    if "테두리_색" in d:
        hexcolor("테두리_색")
        b = d.get("테두리")
        if "테두리" not in d or (isinstance(b, str) and _BORDER_STYLES.get(_key(b), "x") is None):
            out.append("테두리_색은 테두리가 얇게·중간·굵게일 때만 쓸 수 있다")
    for key in ("굵게", "줄바꿈"):
        if key in d and not isinstance(d[key], bool):
            out.append(f"{key} {d[key]!r} 는 true 또는 false 여야 한다")
    if "글꼴_크기" in d:
        v = d["글꼴_크기"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 409:
            out.append(f"글꼴_크기 {v!r} 는 0 보다 크고 409 이하인 숫자여야 한다")
    if "글꼴_색" in d:
        hexcolor("글꼴_색")
    if "가로" in d:
        choice("가로", _HORIZONTAL)
    if "세로" in d:
        choice("세로", _VERTICAL)
    return out


def _normalized(defn: dict) -> dict:
    strings = ("채우기", "테두리", "테두리_색", "글꼴_색", "가로", "세로")
    return {_key(k): (_key(v) if isinstance(v, str) and _key(k) in strings else v) for k, v in defn.items()}


# ---------------------------------------------------------------- styles.xml

class _Section:
    """styles.xml 의 `<fonts>`·`<fills>`·`<borders>`·`<cellXfs>` 하나. 항목을 덧붙이면 다시 쓸 때 count 를 고친다."""

    def __init__(self, xml: str, tag: str, item: str):
        m = re.search(rf"<{tag}\b([^>]*?)(?:/>|>(.*?)</{tag}>)", xml, re.S)
        if not m:
            raise ExportError(f"styles.xml 에 <{tag}> 가 없다")
        self.tag, self.span, self.attrs = tag, m.span(), m.group(1)
        self.items = re.findall(rf"<{item}\b[^>]*?/>|<{item}\b[^>]*?>.*?</{item}>", m.group(2) or "", re.S)
        self.original = len(self.items)

    def find_or_add(self, item: str) -> int:
        if item in self.items:
            return self.items.index(item)
        self.items.append(item)
        return len(self.items) - 1

    def render(self) -> str:
        attrs = self.attrs
        if re.search(r"\bcount=", attrs):
            attrs = re.sub(r"""\bcount=(["'])\d+\1""", f'count="{len(self.items)}"', attrs, count=1)
        else:
            attrs = f' count="{len(self.items)}"' + attrs
        return f"<{self.tag}{attrs}>{''.join(self.items)}</{self.tag}>"


def _xf_parts(xf: str) -> tuple[list[tuple[str, str]], str]:
    m = re.match(r"<xf\b([^>]*?)(/?)>", xf)
    attrs = _attrs(m.group(1), "cellXfs 의 xf")
    inner = "" if m.group(2) else xf[m.end(): xf.rindex("</xf>")]
    return attrs, inner


def _set_attr(attrs: list[tuple[str, str]], key: str, value: str) -> list[tuple[str, str]]:
    if any(k == key for k, _ in attrs):
        return [(k, value if k == key else v) for k, v in attrs]
    return attrs + [(key, value)]


class StylesXml:
    """`xl/styles.xml` 에 서식 항목을 덧붙이는 편집기. 안 건드린 부분은 바이트 그대로다."""

    def __init__(self, xml: str):
        self.xml = xml
        self.fonts = _Section(xml, "fonts", "font")
        self.fills = _Section(xml, "fills", "fill")
        self.borders = _Section(xml, "borders", "border")
        self.xfs = _Section(xml, "cellXfs", "xf")
        self._cache: dict[tuple[int, str], int] = {}

    @property
    def dirty(self) -> bool:
        return any(len(s.items) != s.original for s in (self.fonts, self.fills, self.borders, self.xfs))

    def snapshot(self) -> tuple[int, ...]:
        return tuple(len(s.items) for s in (self.fonts, self.fills, self.borders, self.xfs))

    def rollback(self, snap: tuple[int, ...]) -> None:
        """snapshot 뒤에 덧붙인 항목을 되돌린다(실패한 일괄 적용이 styles.xml 을 어지럽히지 않게)."""
        for sec, n in zip((self.fonts, self.fills, self.borders, self.xfs), snap):
            del sec.items[n:]
        self._cache.clear()

    def xf_count(self) -> int:
        return len(self.xfs.items)

    def derive(self, base: int | str | None, defn: dict) -> int:
        """`base` xf(셀이 이미 가진 서식. 없으면 0)에서 정의에 적힌 부분만 덮어쓴 xf 의 번호를 낸다. 같은 xf 가 있으면 재사용한다."""
        problems = validate_style(defn)
        if problems:
            raise ExportError("스타일 정의가 틀렸다: " + "; ".join(problems))
        d = _normalized(defn)
        try:
            bi = int(base) if base not in (None, "") else 0
        except ValueError:
            raise ExportError(f"서식 번호 {base!r} 가 숫자가 아니다") from None
        if not 0 <= bi < len(self.xfs.items):
            raise ExportError(f"서식 번호 {bi} 가 cellXfs(0~{len(self.xfs.items) - 1}) 밖이다")
        memo = (bi, repr(sorted(d.items(), key=lambda kv: kv[0])))
        if memo in self._cache:
            return self._cache[memo]
        attrs, inner = _xf_parts(self.xfs.items[bi])

        if "채우기" in d:
            if d["채우기"] == "없음":
                fill = '<fill><patternFill patternType="none"/></fill>'
            else:
                rgb = "FF" + d["채우기"].upper()
                fill = f'<fill><patternFill patternType="solid"><fgColor rgb="{rgb}"/><bgColor indexed="64"/></patternFill></fill>'
            attrs = _set_attr(attrs, "fillId", str(self.fills.find_or_add(fill)))
            attrs = _set_attr(attrs, "applyFill", "1")
        if "테두리" in d:
            style = _BORDER_STYLES[d["테두리"]]
            if style is None:
                border = "<border><left/><right/><top/><bottom/><diagonal/></border>"
            else:
                color = f'<color rgb="FF{d["테두리_색"].upper()}"/>' if "테두리_색" in d else '<color indexed="64"/>'
                side = lambda n: f'<{n} style="{style}">{color}</{n}>'  # noqa: E731
                border = f"<border>{side('left')}{side('right')}{side('top')}{side('bottom')}<diagonal/></border>"
            attrs = _set_attr(attrs, "borderId", str(self.borders.find_or_add(border)))
            attrs = _set_attr(attrs, "applyBorder", "1")
        if any(k in d for k in ("굵게", "글꼴_크기", "글꼴_색")):
            font_id = int(dict(attrs).get("fontId", "0") or 0)
            if not 0 <= font_id < len(self.fonts.items):
                raise ExportError(f"글꼴 번호 {font_id} 가 fonts 밖이다")
            font = self._font_with(self.fonts.items[font_id], d)
            attrs = _set_attr(attrs, "fontId", str(self.fonts.find_or_add(font)))
            attrs = _set_attr(attrs, "applyFont", "1")
        if any(k in d for k in ("가로", "세로", "줄바꿈")):
            am = re.search(r"<alignment\b([^>]*?)(?:/>|>\s*</alignment>)", inner)
            if am is None and "<alignment" in inner:
                raise ExportError("xf 의 alignment 를 읽지 못해 덮어쓸 수 없다")
            if am is not None and inner.count("<alignment") != 1:
                raise ExportError("xf 에 alignment 가 둘 이상이라 덮어쓸 수 없다")
            al = _attrs(am.group(1), "xf 의 alignment") if am else []
            if "가로" in d:
                al = _set_attr(al, "horizontal", _HORIZONTAL[d["가로"]])
            if "세로" in d:
                al = _set_attr(al, "vertical", _VERTICAL[d["세로"]])
            if "줄바꿈" in d:
                al = [(k, v) for k, v in al if k != "wrapText"] + ([("wrapText", "1")] if d["줄바꿈"] else [])
            tag = "<alignment" + "".join(f' {k}="{_q(v)}"' for k, v in al) + "/>" if al else ""
            inner = tag + (inner[: am.start()] + inner[am.end():] if am else inner)
            attrs = _set_attr(attrs, "applyAlignment", "1")

        xf = "<xf" + "".join(f' {k}="{_q(v)}"' for k, v in attrs) + (f">{inner}</xf>" if inner else "/>")
        if xf not in self.xfs.items and len(self.xfs.items) >= MAX_CELL_XFS:
            raise ExportError(f"cellXfs 가 엑셀 한도 {MAX_CELL_XFS}개에 닿아 서식을 더 만들 수 없다")
        number = self.xfs.find_or_add(xf)
        self._cache[memo] = number
        return number

    @staticmethod
    def _font_with(font: str, d: dict) -> str:
        m = re.match(r"<font\b[^>]*?(/?)>", font)
        inner = "" if m.group(1) else font[m.end(): font.rindex("</font>")]
        children = re.findall(r"<(\w+)\b[^>]*?/>", inner)
        if re.sub(r"<(\w+)\b[^>]*?/>", "", inner).strip():
            raise ExportError(f"지원하지 않는 글꼴 정의라 덮어쓸 수 없다: {font[:80]}")
        parts = {t: e for t, e in zip(children, re.findall(r"<\w+\b[^>]*?/>", inner))}
        if "굵게" in d:
            if d["굵게"]:
                parts["b"] = "<b/>"
            else:
                parts.pop("b", None)
        if "글꼴_크기" in d:
            size = d["글꼴_크기"]
            parts["sz"] = f'<sz val="{int(size) if float(size).is_integer() else size}"/>'
        if "글꼴_색" in d:
            parts["color"] = f'<color rgb="FF{d["글꼴_색"].upper()}"/>'
        return "<font>" + "".join(parts[t] for t in _FONT_ORDER if t in parts) + "".join(
            e for t, e in parts.items() if t not in _FONT_ORDER) + "</font>"

    def render(self) -> str:
        out = self.xml
        for sec in sorted((s for s in (self.fonts, self.fills, self.borders, self.xfs) if len(s.items) != s.original),
                          key=lambda s: -s.span[0]):
            out = out[: sec.span[0]] + sec.render() + out[sec.span[1]:]
        return out


# ---------------------------------------------------------------- 시트 XML

def _base_style(ed: SheetXml, ref: str) -> str | None:
    """덮어쓸 바탕 서식. 셀 요소가 이미 있으면 그 s(없으면 엑셀 규칙대로 0). 셀을 새로 만들 때만 행 → 열 기본 서식(행이 우선)."""
    cell = ed.cell(ref)
    if cell is not None:
        return cell.style or "0"
    col, num = ref_split(ref)
    row = ed.rows.get(num)
    if row is not None:
        a = dict(row.attrs)
        if a.get("customFormat") in ("1", "true") and a.get("s"):
            return a["s"]
    return _col_style(ed.pre, col2n(col))


def ref_split(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return m.group(1), int(m.group(2))


def style_range(ed: SheetXml, styles: StylesXml, first: str, last: str | None, defn: dict, sname: str = "") -> int:
    """범위의 모든 칸(없는 행·셀은 만든다)에 정의를 적용한다. 칸마다 기존 서식 위에 덮어쓴다. 바꾼 칸 수를 낸다.

    테두리는 범위의 모든 칸에 네 변을 그린다(바깥선만 그리는 모드는 없다).
    """
    try:
        c1, r1, c2, r2 = parse_range(f"{first}:{last}" if last else first)
    except ExportError as exc:
        raise ExportError(exc.reason, sheet=sname) from None
    problems = validate_style(defn)
    if problems:
        raise ExportError("스타일 정의가 틀렸다: " + "; ".join(problems), sheet=sname)
    if (c2 - c1 + 1) * (r2 - r1 + 1) > MAX_STYLED_CELLS:
        raise ExportError(f"서식을 입힐 범위가 {MAX_STYLED_CELLS}칸을 넘는다", sheet=sname)
    plan: list[tuple[str, str]] = []
    snap = styles.snapshot()
    try:
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                ref = f"{n2col(c)}{r}"
                plan.append((ref, str(styles.derive(_base_style(ed, ref), defn))))
    except ExportError as exc:
        styles.rollback(snap)
        raise ExportError(exc.reason, sheet=sname) from None
    except (ValueError, AttributeError, KeyError, IndexError) as exc:  # styles.xml 모양이 예상 밖(fontId="abc", 닫히지 않은 font 등)
        styles.rollback(snap)
        raise ExportError(f"styles.xml 을 읽지 못해 서식을 만들 수 없다: {type(exc).__name__} {exc}", sheet=sname) from None
    for ref, new in plan:  # 모든 칸의 서식이 정해진 뒤에만 시트를 바꾼다
        ed.set_style(ref, new)
    return len(plan)


_MERGES = re.compile(r"<mergeCells\b([^>]*?)(?:/>|>(.*?)</mergeCells>)", re.S)
_MERGE_EL = re.compile(r"<mergeCell\b[^>]*?/>")
_AFTER_MERGE = re.compile(
    r"<(?:phoneticPr|conditionalFormatting|dataValidations|hyperlinks|printOptions|pageMargins|pageSetup|headerFooter|rowBreaks|"
    r"colBreaks|customProperties|cellWatches|ignoredErrors|smartTags|drawing|legacyDrawing|legacyDrawingHF|drawingHF|picture|"
    r"oleObjects|controls|webPublishItems|tableParts|extLst)\b"
)


def _merge_block(ed: SheetXml, sname: str = "") -> tuple[re.Match | None, list[str]]:
    """(mergeCells 블록, 기존 병합 요소들). 블록이 있는데 읽지 못하면 검사 불능이라 ExportError."""
    m = _MERGES.search(ed.post)
    if m is None:
        if re.search(r"<mergeCells\b", ed.post):
            raise ExportError("시트의 mergeCells 를 읽지 못해 병합 겹침을 검사할 수 없다", sheet=sname)
        return None, []
    inner = m.group(2) or ""
    if _MERGE_EL.sub("", inner).strip():
        raise ExportError("시트의 mergeCells 안에 읽지 못하는 내용이 있어 병합 겹침을 검사할 수 없다", sheet=sname)
    return m, _MERGE_EL.findall(inner)


def merges_of(ed: SheetXml, sname: str = "") -> list[str]:
    out = []
    for el in _merge_block(ed, sname)[1]:
        ref = dict(_attrs(el[len("<mergeCell"):-2], "mergeCell")).get("ref")
        if not ref:
            raise ExportError("ref 가 없는 mergeCell 이 있어 병합 겹침을 검사할 수 없다", sheet=sname)
        out.append(ref)
    return out


def merge_range(ed: SheetXml, first: str, last: str, sname: str = "") -> str:
    """범위를 병합한다. 기존 병합과 한 칸이라도 겹치면 쓰지 않고 ExportError 로 멈춘다. 병합 위치(`B2:D3`)를 낸다.

    병합의 왼쪽 위가 아닌 칸에 값이 있으면 엑셀이 버리는 값이라 멈춘다.
    """
    try:
        rect = parse_range(f"{first}:{last}")
    except ExportError as exc:
        raise ExportError(exc.reason, sheet=sname) from None
    c1, r1, c2, r2 = rect
    ref = f"{n2col(c1)}{r1}:{n2col(c2)}{r2}"
    if rect[0] == rect[2] and rect[1] == rect[3]:
        raise ExportError(f"병합 {ref} 는 한 칸이라 병합할 수 없다", sheet=sname)
    for other in merges_of(ed, sname):
        try:
            o = parse_range(other)
        except ExportError:
            raise ExportError(f"기존 병합 {other!r} 를 읽지 못해 겹침을 검사할 수 없다", sheet=sname) from None
        if c1 <= o[2] and o[0] <= c2 and r1 <= o[3] and o[1] <= r2:
            raise ExportError(f"시트 {sname!r} 의 병합 {ref} 가 기존 병합 {other} 와 겹친다", sheet=sname)
    for n in ed.rows_with_content(r1, r2):
        for cell in ed.rows[n].cells:
            if c1 <= cell.col <= c2 and cell.ref != f"{n2col(c1)}{r1}" and cell.has_content():
                raise ExportError(f"시트 {sname!r} 의 병합 {ref} 안 {cell.ref} 에 값이 있다 — 병합하면 엑셀이 버리는 값이다", sheet=sname)
    el = f'<mergeCell ref="{ref}"/>'
    m, existing = _merge_block(ed, sname)
    if m:
        items = existing + [el]
        attrs = re.sub(r"""\s*\bcount=(["'])\d+\1""", "", m.group(1)).rstrip("/").rstrip()
        ed.post = ed.post[: m.start()] + f'<mergeCells count="{len(items)}"{attrs}>{"".join(items)}</mergeCells>' + ed.post[m.end():]
    else:
        block = f'<mergeCells count="1">{el}</mergeCells>'
        nxt = _AFTER_MERGE.search(ed.post)
        at = nxt.start() if nxt else ed.post.rindex("</worksheet>")
        ed.post = ed.post[:at] + block + ed.post[at:]
    ed.dirty = True
    return ref
