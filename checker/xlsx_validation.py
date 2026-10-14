"""xlsx 시트의 데이터 유효성(드롭다운 목록)에서 허용 값을 읽는다(#228).

표준 `<dataValidation>` 과 확장 `<x14:dataValidation>`(extLst) 둘 다 본다. 목록은 세 모양이다.

- 직접 적은 목록 `"a,b,c"`
- 범위 `'Values Drop Down'!$A$4:$A$9` (다른 시트여도 된다)
- 정의 이름 `Priorities` (통합문서 `definedName` 을 따라가 범위로 푼다)

범위 안 셀 값은 sharedStrings·inlineStr·수식 결과(`t="str"`)·숫자를 문자열로 읽는다. 빈 칸은 무시한다.
읽을 수 없는 수식(INDIRECT, 이름 없는 함수, 열 전체 참조 …)은 `allowed=None` 으로 두고 사유를 남긴다 —
허용 값을 모르는 것이지 "아무 값이나 된다" 도 "다 틀렸다" 도 아니다.

XML 은 정규식으로만 다룬다(`xml.etree` 는 이름공간 접두어를 바꾼다). 이 모듈은 읽기만 한다.
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

_ATTR_RE = re.compile(r'([\w:]+)="([^"]*)"')
_CELL_RE = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_VALIDATION_RE = re.compile(r"<((?:\w+:)?)dataValidation\b([^>]*)>(.*?)</\1dataValidation>", re.S)
_REF_RE = re.compile(
    r"^(?:(?:'((?:[^']|'')+)'|([^'!]+))!)?\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?$"
)


def _col2n(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _split(ref: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\$?([A-Z]+)\$?(\d+)", ref.strip())
    return (_col2n(m.group(1)), int(m.group(2))) if m else None


def xml_text(s: str) -> str:
    """XML 본문의 엔티티와 `_x000D_` 같은 이스케이프를 푼다."""
    s = html.unescape(s)
    return re.sub(r"_x([0-9A-Fa-f]{4})_", lambda m: chr(int(m.group(1), 16)), s)


def _text_of(fragment: str) -> str:
    """`<si>`·`<is>` 조각의 글자를 모은다(윗주 rPh 는 뺀다)."""
    fragment = re.sub(r"<(?:\w+:)?rPh\b.*?</(?:\w+:)?rPh>", "", fragment, flags=re.S)
    return "".join(xml_text(t) for t in re.findall(r"<t\b[^>]*>(.*?)</t>", fragment, re.S))


@dataclass
class Validation:
    ranges: list[tuple[int, int, int, int]]  # (열1, 행1, 열2, 행2)
    formula: str
    allowed: list[str] | None  # None 이면 읽지 못함, [] 면 목록 범위가 실제로 비어 있음
    why: str = ""  # 읽지 못한(또는 비어 있는) 사유
    enforced: bool = True  # False 면 엑셀이 목록 밖 값을 그냥 받는다(오류 메시지 꺼짐, 정보·경고 스타일)

    @property
    def empty(self) -> bool:
        return self.allowed == []

    def covers(self, col: int, row: int) -> bool:
        return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in self.ranges)

    def cells_text(self) -> str:
        def n2col(n: int) -> str:
            out = ""
            while n:
                n, r = divmod(n - 1, 26)
                out = chr(65 + r) + out
            return out

        return " ".join(
            f"{n2col(c1)}{r1}" if (c1, r1) == (c2, r2) else f"{n2col(c1)}{r1}:{n2col(c2)}{r2}"
            for c1, r1, c2, r2 in self.ranges
        )


class ListReader:
    """통합문서 하나에서 시트별 드롭다운 허용 값을 읽는다."""

    def __init__(self, raw: dict[str, bytes], paths: dict[str, str], wb_xml: str):
        self.raw, self.paths = raw, paths  # paths 키는 export._sheet_paths 가 NFC 로 정규화한 시트 이름
        self._sst: list[str] | None = None
        self.sheet_order = [
            xml_text(dict(_ATTR_RE.findall(m.group(0))).get("name", ""))
            for m in re.finditer(r"<sheet\b[^>]*>", wb_xml)
        ]
        self.names: dict[tuple[str, int | None], str] = {}
        for m in re.finditer(r"<definedName\b([^>]*)>(.*?)</definedName>", wb_xml, re.S):
            a = dict(_ATTR_RE.findall(m.group(1)))
            local = a.get("localSheetId")
            self.names[(xml_text(a.get("name", "")).lower(), int(local) if local else None)] = xml_text(m.group(2))

    # -- 셀 값
    def _shared(self) -> list[str]:
        if self._sst is None:
            data = self.raw.get("xl/sharedStrings.xml")
            text = data.decode("utf-8-sig") if data else ""
            self._sst = [
                _text_of(m.group(1) or "")
                for m in re.finditer(r"<si\b[^>]*?(?:/>|>(.*?)</si>)", text, re.S)
            ]
        return self._sst

    def _range_values(self, sheet: str, c1: int, r1: int, c2: int, r2: int) -> list[str]:
        path = self.paths.get(unicodedata.normalize("NFC", sheet))
        if path is None or path not in self.raw:
            raise KeyError(f"시트 {sheet!r} 을 찾지 못했다")
        xml = self.raw[path].decode("utf-8-sig")
        found: list[tuple[int, int, str]] = []
        for m in _CELL_RE.finditer(xml):
            attrs = dict(_ATTR_RE.findall(m.group(1)))
            pos = _split(attrs.get("r", ""))
            if pos is None or not (c1 <= pos[0] <= c2 and r1 <= pos[1] <= r2):
                continue
            inner = m.group(2) or ""
            t = attrs.get("t", "")
            v = re.search(r"<v>(.*?)</v>", inner, re.S)
            if t == "inlineStr":
                val = _text_of(inner)
            elif v is None:
                continue
            elif t == "s":
                idx = int(v.group(1))
                sst = self._shared()
                val = sst[idx] if idx < len(sst) else ""
            elif t == "str":
                val = xml_text(v.group(1))
            elif t == "b":
                val = "TRUE" if v.group(1).strip() == "1" else "FALSE"
            elif t == "e":
                continue
            else:
                val = v.group(1).strip()
                try:
                    f = float(val)
                    val = str(int(f)) if f == int(f) and abs(f) < 1e15 else val
                except ValueError:
                    pass
            val = val.strip()
            if val:
                found.append((pos[1], pos[0], val))
        return [v for _, _, v in sorted(found)]

    # -- 수식 풀기
    def _resolve(self, formula: str, sheet: str) -> tuple[list[str] | None, str]:
        f = xml_text(formula).strip()
        f = f[1:].strip() if f.startswith("=") else f
        if len(f) >= 2 and f.startswith('"') and f.endswith('"'):
            items = [x.strip() for x in f[1:-1].split(",")]
            return list(dict.fromkeys(x for x in items if x)), ""
        ref_text = f
        if re.fullmatch(r"[A-Za-z_\\][\w.]*", f):
            idx = self.sheet_order.index(sheet) if sheet in self.sheet_order else None
            hit = self.names.get((f.lower(), idx))
            if hit is None:
                hit = self.names.get((f.lower(), None))
            if hit is not None:
                ref_text = hit.strip()
                ref_text = ref_text[1:].strip() if ref_text.startswith("=") else ref_text
            elif not _REF_RE.match(f):
                return None, f"정의 이름 {f} 를 통합문서에서 찾지 못했다"
        m = _REF_RE.match(ref_text)
        if not m:
            return None, f"목록 수식 {ref_text!r} 은 셀 범위가 아니라 읽지 못한다"
        target = (m.group(1).replace("''", "'") if m.group(1) else m.group(2)) or sheet
        c1, r1 = _col2n(m.group(3)), int(m.group(4))
        c2, r2 = (_col2n(m.group(5)), int(m.group(6))) if m.group(5) else (c1, r1)
        try:
            vals = self._range_values(target, min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2))
        except (KeyError, UnicodeDecodeError, ValueError) as e:
            return None, f"목록 범위 {ref_text} 를 읽지 못했다: {e}"
        return list(dict.fromkeys(vals)), ""

    # -- 시트의 유효성
    def validations(self, sheet: str) -> list[Validation]:
        path = self.paths.get(unicodedata.normalize("NFC", sheet))
        if path is None or path not in self.raw:
            return []
        xml = self.raw[path].decode("utf-8-sig")
        out: list[Validation] = []
        for m in _VALIDATION_RE.finditer(xml):
            attrs = dict(_ATTR_RE.findall(m.group(2)))
            if attrs.get("type") != "list":
                continue
            body = m.group(3)
            fm = re.search(r"<(?:\w+:)?formula1>(.*?)</(?:\w+:)?formula1>", body, re.S)
            if not fm:
                continue
            formula = re.sub(r"<[^>]+>", "", fm.group(1))
            sq = attrs.get("sqref")
            if sq is None:
                sm = re.search(r"<(?:\w+:)?sqref>(.*?)</(?:\w+:)?sqref>", body, re.S)
                sq = sm.group(1) if sm else ""
            ranges = []
            for part in xml_text(sq).split():
                a, _, b = part.partition(":")
                p1, p2 = _split(a), _split(b or a)
                if p1 and p2:
                    ranges.append((min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])))
            if not ranges:
                continue
            allowed, why = self._resolve(formula, sheet)
            if allowed is not None and not allowed:
                why = f"목록 {xml_text(formula).strip()} 에 값이 하나도 없다"
            # 오류 메시지가 꺼져 있거나 정보·경고 스타일이면 엑셀이 목록 밖 값을 받는다.
            enforced = attrs.get("showErrorMessage", "0") in ("1", "true") and attrs.get("errorStyle", "stop") == "stop"
            out.append(Validation(ranges, xml_text(formula).strip(), allowed, why, enforced))
        return out


def find(validations: list[Validation], col: int, row: int) -> Validation | None:
    return next((v for v in validations if v.covers(col, row)), None)
