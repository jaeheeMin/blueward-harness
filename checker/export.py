"""작업본(md)의 `## 양식 항목` 을 고객사 양식 xlsx 로 산출한다(#192).

`/harness:spec` 이 만든 작업본과 양식 지도(`templates/forms/<양식>.yaml`, 형식 정본은
`plugins/harness/skills/spec/form-map.md`)를 읽어 지도의 `템플릿` xlsx 복사본에 값을 채운다.

쓰기는 openpyxl 을 쓰지 않는다. load→save 는 도형·그림·인쇄 설정·calcChain 을 잃는다. 대신
zip 수준에서 바뀐 시트의 XML 만 고치고 나머지 항목은 같은 순서로 그대로 복사한다. XML 은
정규식·문자열로만 다룬다(`xml.etree` 는 이름공간 접두어를 바꾼다).

종료코드
    0  산출함.
    1  거부. 작업본이 덜 채워졌거나(필수 `미정`, `최대_행` 초과, 짝 행 수 불일치 …) 파일을
       쓸 수 없다(이미 있음, 금지 문자, 파일명 패턴). 아무 파일도 쓰지 않는다.
    2  읽지 못함. 작업본·지도·템플릿을 못 읽거나 작업본이 지도에 없는 것을 가리킨다.
       검사 불능이지 통과도 위반도 아니다.
    3  산출했으나 경고가 있다(#228). 표 값이 템플릿 드롭다운 목록 밖이다. 파일은 썼고 stdout 의
       `status` 는 `warning`, `warnings` 에서 `type: dropdown` 이 목록 밖 값이다(행·열·값·허용 값).
       허용 값을 읽지 못해 검사하지 못한 칸은 `type: dropdown-unchecked` 경고로만 알리고 종료코드는 0 이다.

원본이 SRS 인 지도(표에 `원본: SRS`)는 `## 양식 항목` 이 아니라 SRS.md 의 `## 요구사항` 표와
`### REQ-xxx` 상세 절을 읽는다(`--form <지도>` 와 `--spec <SRS.md>`). `--check` 는 파일을 쓰지 않고
같은 보고만 낸다. `--list-values` 는 지도 템플릿의 드롭다운 허용 값을 열별로 JSON 으로 낸다.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import io
import json
import os
import posixpath
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, unescape

import yaml

from checker.xlsx_validation import ListReader
from checker.xlsx_validation import find as find_validation

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_ERROR = 2
EXIT_WARNING = 3

FORBIDDEN_NAME_CHARS = '\\/:*?"<>|'
UNDECIDED = "미정"
NOT_APPLICABLE = "해당 없음"

_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INT = re.compile(r"^(0|-?[1-9]\d{0,14})$")
_CTRL = re.compile("[" + chr(0) + "-" + chr(8) + chr(0xB) + chr(0xC) + chr(0xE) + "-" + chr(0x1F) + chr(0xFFFE) + chr(0xFFFF) + chr(0xD800) + "-" + chr(0xDFFF) + "]")  # XML 1.0 에 못 넣는 문자
MAX_CELL_CHARS = 32767


class ExportError(Exception):
    """읽지 못함(종료코드 2)."""

    too_long = False

    def __init__(self, reason: str, form: str = "", sheet: str = "", item: str = ""):
        super().__init__(reason)
        self.reason, self.form, self.sheet, self.item = reason, form, sheet, item


class CellTooLong(ExportError):
    """셀 하나에 못 담는 길이. 거부(종료코드 1)로 바꿔 알린다."""

    too_long = True


def norm(text: str) -> str:
    """form-map.md 의 정규화: 앞뒤 공백 제거, 줄바꿈·연속 공백은 공백 하나로."""
    return re.sub(r"\s+", " ", str(text)).strip()


# ---------------------------------------------------------------- 열 문자

def col2n(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def n2col(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def split_ref(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not m:
        raise ExportError(f"셀 위치 {ref!r} 의 모양이 틀렸다")
    return m.group(1), int(m.group(2))


# ---------------------------------------------------------------- 시트 XML

_ROW_RE = re.compile(r"<row\b([^>]*?)(?:/>|>(.*?)</row>)", re.S)
_CELL_RE = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_ATTR_RE = re.compile(r'([\w:]+)="([^"]*)"')


@dataclass
class _Cell:
    ref: str
    attrs: list[tuple[str, str]]
    inner: str
    raw: str | None = None  # 손대지 않았으면 원문 그대로 낸다

    @property
    def col(self) -> int:
        return col2n(split_ref(self.ref)[0])

    @property
    def style(self) -> str | None:
        return dict(self.attrs).get("s")

    def has_content(self) -> bool:
        return any(tag in self.inner for tag in ("<v>", "<v ", "<is>", "<is ", "<f"))

    def render(self) -> str:
        if self.raw is not None:
            return self.raw
        attrs = "".join(f' {k}="{v}"' for k, v in self.attrs)
        return f"<c{attrs}>{self.inner}</c>" if self.inner else f"<c{attrs}/>"


@dataclass
class _Row:
    num: int
    attrs: list[tuple[str, str]]  # r, spans 를 뺀 나머지
    cells: list[_Cell]
    raw: str | None = None

    def render(self) -> str:
        if self.raw is not None:
            return self.raw
        attrs = "".join(f' {k}="{v}"' for k, v in self.attrs)
        head = f'<row r="{self.num}"{attrs}'
        body = "".join(c.render() for c in self.cells)
        return f"{head}>{body}</row>" if body else f"{head}/>"


class SheetXml:
    """시트 XML 에서 셀 몇 개만 바꾸는 얇은 편집기."""

    def __init__(self, xml: str, date_styles: set[str], base1904: bool):
        self.date_styles = date_styles
        self.base = dt.date(1904, 1, 1) if base1904 else dt.date(1899, 12, 30)
        m = re.search(r"<sheetData\b[^>]*?(?:/>|>(.*?)</sheetData>)", xml, re.S)
        if not m:
            raise ExportError("시트 XML 에 sheetData 가 없다")
        self.pre, self.post = xml[: m.start()], xml[m.end():]
        self.rows: dict[int, _Row] = {}
        self.dirty = False
        self.filter_change: tuple[str, str] | None = None
        self._max_row = 0
        self._max_col = 0
        for rm in _ROW_RE.finditer(m.group(1) or ""):
            attrs = dict(_ATTR_RE.findall(rm.group(1)))
            num = int(attrs["r"])
            keep = [(k, v) for k, v in _ATTR_RE.findall(rm.group(1)) if k not in ("r", "spans")]
            cells = []
            for cm in _CELL_RE.finditer(rm.group(2) or ""):
                ca = _ATTR_RE.findall(cm.group(1))
                cells.append(_Cell(dict(ca)["r"], ca, cm.group(2) or "", cm.group(0)))
            self.rows[num] = _Row(num, keep, cells, rm.group(0))

    # -- 조회
    def cell(self, ref: str) -> _Cell | None:
        col, row = split_ref(ref)
        r = self.rows.get(row)
        if not r:
            return None
        for c in r.cells:
            if c.ref == ref:
                return c
        return None

    def has_value(self, ref: str) -> bool:
        c = self.cell(ref)
        return bool(c and c.has_content())

    def rows_with_content(self, first: int, last: int) -> list[int]:
        return [n for n in sorted(self.rows) if first <= n <= last]

    # -- 편집
    def _row(self, num: int, clone_from: int | None = None) -> _Row:
        if num in self.rows:
            return self.rows[num]
        attrs: list[tuple[str, str]] = []
        if clone_from is not None and clone_from in self.rows:
            attrs = list(self.rows[clone_from].attrs)
        row = _Row(num, attrs, [], None)
        self.rows[num] = row
        return row

    def _touch(self, row: _Row, ref: str) -> None:
        row.raw = None
        self.dirty = True
        col, n = split_ref(ref)
        self._max_row = max(self._max_row, n)
        self._max_col = max(self._max_col, col2n(col))

    def _coerce(self, text: str, style: str | None) -> tuple[str, str]:
        """(속성 t 값, 본문)을 낸다. 날짜·정수는 숫자로, 나머지는 inlineStr."""
        if _DATE.match(text) and style in self.date_styles:
            try:
                d = dt.date.fromisoformat(text)
            except ValueError:
                d = None
            if d:
                return "", f"<v>{(d - self.base).days}</v>"
        if _INT.match(text):
            return "", f"<v>{text}</v>"
        safe = escape(text.replace("\r\n", "\n").replace("\r", "\n"))
        sp = ' xml:space="preserve"' if (safe != safe.strip() or "\n" in safe) else ""
        return "inlineStr", f"<is><t{sp}>{safe}</t></is>"

    def set(self, ref: str, text: str, style: str | None = None, clone_row: int | None = None) -> int:
        """셀에 쓴다. XML 에 못 넣는 문자는 지우고 지운 개수를 돌려준다."""
        cleaned = _CTRL.sub("", text)
        removed = len(text) - len(cleaned)
        text = cleaned
        if len(text) > MAX_CELL_CHARS:
            raise CellTooLong(f"{ref} 에 쓸 값이 {len(text)}자라 셀 한도 {MAX_CELL_CHARS}자를 넘는다")
        col, num = split_ref(ref)
        row = self._row(num, clone_row)
        cell = self.cell(ref)
        if cell is None:
            attrs = [("r", ref)]
            if style is not None:
                attrs.append(("s", style))
            cell = _Cell(ref, attrs, "")
            pos = len(row.cells)
            for i, c in enumerate(row.cells):
                if c.col > col2n(col):
                    pos = i
                    break
            row.cells.insert(pos, cell)
        elif "<f" in cell.inner:
            raise ExportError(
                f"{ref} 는 수식 셀이라 덮어쓸 수 없다. 지도에 `자동: true` 가 빠졌는지 확인한다"
            )
        elif style is not None:
            cell.attrs = [(k, v) for k, v in cell.attrs if k != "s"] + [("s", style)]
        t, body = self._coerce(text, cell.style)
        cell.attrs = [(k, v) for k, v in cell.attrs if k != "t"]
        if t:
            cell.attrs.append(("t", t))
        cell.inner = body
        cell.raw = None
        self._touch(row, ref)
        return removed

    def valued_refs(self) -> list[str]:
        """값(또는 수식)이 있는 셀의 위치를 행·열 순서로 낸다."""
        return [c.ref for n in sorted(self.rows) for c in self.rows[n].cells if c.has_content()]

    def clear(self, ref: str) -> None:
        """값만 비운다. 내용이 없는 셀은 건드리지 않고, 수식 셀도 건드리지 않는다."""
        cell = self.cell(ref)
        if cell is None or not cell.has_content() or "<f" in cell.inner:
            return
        cell.attrs = [(k, v) for k, v in cell.attrs if k != "t"]
        cell.inner = ""
        cell.raw = None
        self._touch(self.rows[split_ref(ref)[1]], ref)

    def clear_range(self, first_ref: str, last_ref: str, keep: str | None = None) -> None:
        c1, r1 = split_ref(first_ref)
        c2, r2 = split_ref(last_ref)
        for n in self.rows_with_content(r1, r2):
            for c in list(self.rows[n].cells):
                if col2n(c1) <= c.col <= col2n(c2) and c.ref != keep:
                    self.clear(c.ref)

    def blank(self, ref: str, style: str | None, clone_row: int | None) -> None:
        """새 행의 빈 칸에 서식만 복제한다."""
        if style is None or self.cell(ref) is not None:
            return
        col, num = split_ref(ref)
        row = self._row(num, clone_row)
        pos = next((i for i, c in enumerate(row.cells) if c.col > col2n(col)), len(row.cells))
        row.cells.insert(pos, _Cell(ref, [("r", ref), ("s", style)], ""))
        self._touch(row, ref)

    def style_of(self, ref: str) -> str | None:
        c = self.cell(ref)
        return c.style if c else None

    def unhide(self, num: int) -> None:
        """쓰는 행에 숨김 속성이 있으면 지운다(양식에서 숨겨진 행에 쓰면 산출물에서 안 보인다)."""
        row = self.rows.get(num)
        if row and any(k == "hidden" and v in ("1", "true") for k, v in row.attrs):
            row.attrs = [(k, v) for k, v in row.attrs if k != "hidden"]
            row.raw = None
            self.dirty = True

    def autofit(self, num: int) -> None:
        """값을 쓴 행의 고정 줄 높이(ht·customHeight)를 지워 엑셀이 내용에 맞춰 높이를 잡게 한다."""
        row = self.rows.get(num)
        if row and any(k in ("ht", "customHeight") for k, _ in row.attrs):
            row.attrs = [(k, v) for k, v in row.attrs if k not in ("ht", "customHeight")]
            row.raw = None
            self.dirty = True

    def render(self) -> str:
        pre = self.pre
        post = self.post
        self.filter_change = None
        if self._max_row:
            # 자동 필터 범위는 쓴 행이 그 끝을 넘을 때만 늘린다(없으면 건드리지 않는다).
            def grow(m: re.Match) -> str:
                c1, r1, c2, r2 = m.group(2), int(m.group(3)), m.group(4), int(m.group(5))
                if self._max_row <= r2:
                    return m.group(0)
                self.filter_change = (f"{c1}{r1}:{c2}{r2}", f"{c1}{r1}:{c2}{self._max_row}")
                return f'{m.group(1)}{c1}{r1}:{c2}{self._max_row}"'
            post = re.sub(r'(<autoFilter\b[^>]*?\bref=")([A-Z]+)(\d+):([A-Z]+)(\d+)"', grow, post, count=1)
        if self._max_row:
            def fix(m: re.Match) -> str:
                a, b = m.group(1).split(":") if ":" in m.group(1) else (m.group(1), m.group(1))
                c1, r1 = split_ref(a)
                c2, r2 = split_ref(b)
                c2 = n2col(max(col2n(c2), self._max_col))
                r2 = max(r2, self._max_row)
                return f'<dimension ref="{c1}{r1}:{c2}{r2}"/>'
            pre = re.sub(r'<dimension ref="([^"]+)"\s*/>', fix, pre, count=1)
        body = "".join(self.rows[n].render() for n in sorted(self.rows))
        return f"{pre}<sheetData>{body}</sheetData>{post}"


# ---------------------------------------------------------------- xlsx(zip) 읽기

def _sheet_paths(zf: zipfile.ZipFile) -> dict[str, str]:
    wb = zf.read("xl/workbook.xml").decode("utf-8")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets: dict[str, str] = {}
    for m in re.finditer(r"<Relationship\b[^>]*>", rels):
        a = dict(_ATTR_RE.findall(m.group(0)))
        t = a.get("Target", "")
        targets[a.get("Id", "")] = t[1:] if t.startswith("/") else "xl/" + t
    out: dict[str, str] = {}
    for m in re.finditer(r"<sheet\b[^>]*>", wb):
        a = dict(_ATTR_RE.findall(m.group(0)))
        rid = a.get("r:id")
        if rid in targets:
            out[unescape(a["name"], {"&quot;": '"', "&apos;": "'"})] = targets[rid]
    return out


_BUILTIN_DATE_IDS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _date_styles(zf: zipfile.ZipFile) -> set[str]:
    """날짜 서식인 셀 스타일(`s` 값) 집합. 날짜 서식이 아닌 칸에는 날짜를 숫자로 쓰지 않는다."""
    if "xl/styles.xml" not in zf.namelist():
        return set()
    xml = zf.read("xl/styles.xml").decode("utf-8")
    custom: set[int] = set()
    for m in re.finditer(r"<numFmt\b[^>]*>", xml):
        a = dict(_ATTR_RE.findall(m.group(0)))
        code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", unescape(a.get("formatCode", "")))
        if re.search(r"[dmyhsDMYHS]", code) and "General" not in code:
            custom.add(int(a["numFmtId"]))
    cx = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", xml, re.S)
    out: set[str] = set()
    if cx:
        for i, m in enumerate(re.finditer(r"<xf\b([^>]*?)(?:/>|>.*?</xf>)", cx.group(1), re.S)):
            nid = int(dict(_ATTR_RE.findall(m.group(1))).get("numFmtId", "0"))
            if nid in _BUILTIN_DATE_IDS or nid in custom:
                out.add(str(i))
    return out


def _extend_filter_database(workbook_xml: str, sheet: str, old_ref: str, new_ref: str) -> str:
    """자동 필터 범위를 늘렸으면 그 시트의 숨은 이름 `_xlnm._FilterDatabase` 의 범위도 같이 늘린다."""
    def absolute(ref: str) -> str:
        a, b = ref.split(":")
        return "$" + re.sub(r"(\d+)$", r"$\1", a) + ":$" + re.sub(r"(\d+)$", r"$\1", b)

    old_abs, new_abs = absolute(old_ref), absolute(new_ref)

    def fix(m: re.Match) -> str:
        sheet_part, _, rng = m.group(2).rpartition("!")
        name = unescape(sheet_part.strip("'").replace("''", "'"), {"&quot;": '"', "&apos;": "'"})
        if name == sheet and rng == old_abs:
            return f"{m.group(1)}{sheet_part}!{new_abs}{m.group(3)}"
        return m.group(0)

    return re.sub(
        r'(<definedName\b[^>]*name="_xlnm\._FilterDatabase"[^>]*>)([^<]*)(</definedName>)', fix, workbook_xml
    )


def _with_full_calc(workbook_xml: str) -> str:
    """수식이 있는 통합문서는 열 때 전체 재계산하게 한다(겉표지 파일명 수식 등)."""
    m = re.search(r"<calcPr\b[^>]*?/>", workbook_xml)
    if m:
        tag = m.group(0)
        if "fullCalcOnLoad" in tag:
            new = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
        else:
            new = tag[:-2].rstrip() + ' fullCalcOnLoad="1"/>'
        return workbook_xml[: m.start()] + new + workbook_xml[m.end():]
    # 스키마 순서: ... sheets, functionGroups, externalReferences, definedNames, calcPr, oleSize ...
    ends = []
    for tag in ("definedNames", "externalReferences", "functionGroups", "sheets"):
        m2 = re.search(rf"</{tag}>|<{tag}\b[^>]*?/>", workbook_xml)
        if m2:
            ends.append(m2.end())
    if not ends:
        raise ExportError("workbook.xml 에 sheets 가 없다")
    p = max(ends)
    return workbook_xml[:p] + '<calcPr fullCalcOnLoad="1"/>' + workbook_xml[p:]


# ---------------------------------------------------------------- 작업본(md) 읽기

@dataclass
class Section:
    na: bool = False
    fields: dict[str, str] = field(default_factory=dict)
    tables: dict[str, tuple[list[str], list[list[str]]]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    issues: list[tuple[str, str]] = field(default_factory=list)  # 작업본 형식 문제(거부)


def _split_row(line: str) -> list[str]:
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _is_sep(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _parse_table(
    lines: list[str], where: str
) -> tuple[list[str], list[list[str]], list[tuple[int, int]]] | None:
    """줄들에서 md 표 하나를 찾아 (머리글, 행들, 셀 수가 틀린 행들) 로 낸다.

    구분선은 머리글 바로 다음 줄만 구분선으로 본다. 표가 끊긴 뒤 같은 소절에서 표 행이 다시
    나오거나 머리글 다음 줄이 구분선이 아니면 작업본 형식 오류라 ExportError(읽지 못함)다.
    셀 수가 틀린 행은 (1부터 센 행 번호, 실제 셀 수) 로 따로 알리고 행은 머리글 길이에 맞춰 채운다.
    """
    i = 0
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        i += 1
    if i >= len(lines):
        return None
    header = [norm(c) for c in _split_row(lines[i])]
    if i + 1 >= len(lines) or not _is_sep(_split_row(lines[i + 1])):
        raise ExportError(f"{where}: 표 머리글 바로 다음 줄이 구분선(|---|)이 아니다")
    rows: list[list[str]] = []
    bad: list[tuple[int, int]] = []
    j = i + 2
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        cells = _split_row(lines[j])
        if len(cells) != len(header):
            bad.append((len(rows) + 1, len(cells)))
        rows.append((cells + [""] * len(header))[: len(header)])
        j += 1
    if any(l.lstrip().startswith("|") for l in lines[j:]):
        raise ExportError(f"{where}: 표가 끊긴 뒤 다시 표 행이 나온다(소절 안에 표는 하나여야 한다)")
    return header, rows, bad


def _clean(value: str | None) -> str:
    v = (value or "").strip()
    return "" if v == UNDECIDED else v


def parse_spec(text: str) -> dict[str, dict[str, tuple[Section, dict[str, list[str]]]]]:
    """`## 양식 항목` → {양식: {시트: (Section, {#### 이름: 본문 줄들})}}. 본문은 지도로 해석한다."""
    lines = re.split(r"\r\n|\n|\r", text)  # splitlines 는 \x0b·\x1c 등에서도 줄을 나눈다
    start = next((i for i, l in enumerate(lines) if re.match(r"^##\s+양식 항목\s*$", l)), None)
    if start is None:
        raise ExportError("작업본에 `## 양식 항목` 절이 없다")
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^##\s", lines[i])), len(lines)
    )
    forms: dict[str, dict[str, tuple[Section, dict[str, list[str]]]]] = {}
    cur: tuple[str, str] | None = None
    buf: list[str] = []

    def flush() -> None:
        if cur is None:
            return
        form, sheet = cur
        pre: list[str] = []
        subs: dict[str, list[str]] = {}
        name = None
        for l in buf:
            hm = re.match(r"^####\s+(.+?)\s*$", l)
            if hm:
                name = norm(hm.group(1))
                if name in subs:
                    raise ExportError(f"{form} · {sheet}: `#### {name}` 이 두 번 나온다", form=form, sheet=sheet, item=name)
                subs[name] = []
            elif name is None:
                pre.append(l)
            else:
                subs[name].append(l)
        sec = Section()
        parsed = _parse_table(pre, f"{form} · {sheet}")
        if parsed:
            if parsed[0] != ["항목", "값"]:
                raise ExportError(
                    f"{form} · {sheet}: 칸 표의 머리글이 `| 항목 | 값 |` 이 아니다({' | '.join(parsed[0])})",
                    form=form, sheet=sheet,
                )
            for n, cnt in parsed[2]:
                sec.issues.append(("칸 표", f"{n}번째 행의 셀 수({cnt})가 머리글(2)과 다르다"))
            for row in parsed[1]:
                if row[0].strip():
                    sec.fields[norm(row[0])] = row[1].strip()
        elif not subs and any(l.strip() == NOT_APPLICABLE for l in pre):
            sec.na = True
        elif not subs and not any(l.strip() and not l.startswith("양식 지도:") for l in pre):
            sec.na = True
        if sheet in forms.setdefault(form, {}):
            raise ExportError(f"`### {form} · {sheet}` 소절이 두 번 나온다", form=form, sheet=sheet)
        forms[form][sheet] = (sec, subs)

    for l in lines[start + 1: end]:
        hm = re.match(r"^###\s+(.+?)\s*$", l)
        if hm:
            flush()
            buf = []
            parts = hm.group(1).split("·")
            if len(parts) < 2:
                raise ExportError(f"소절 제목 {hm.group(1)!r} 이 `<양식> · <시트>` 모양이 아니다")
            cur = (norm(parts[0]), norm("·".join(parts[1:])))
        else:
            buf.append(l)
    flush()
    if not forms:
        raise ExportError("`## 양식 항목` 에 `### <양식> · <시트>` 소절이 없다")
    return forms


# ---------------------------------------------------------------- SRS(md) 읽기

_REQ_ID = re.compile(r"^REQ-(\d+)$")
_META_LINE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?([^:：*|#]{1,30}?)(?:\*\*)?\s*[:：]\s*(?:\*\*)?(.*?)(?:\*\*)?\s*$")


@dataclass
class SrsDoc:
    header: list[str]  # 요구사항 표 머리글(정규화)
    rows: list[list[str]]
    bad: list[tuple[int, int]]  # 셀 수가 틀린 행 (행 번호, 셀 수)
    details: dict[str, dict[str, str]]  # REQ-xxx → {소제목(정규화): 본문}
    meta: dict[str, str]  # 문서 머리의 `이름: 값` 줄 (예: 버전)


def parse_srs(text: str) -> SrsDoc:
    """SRS.md → `## 요구사항` 표(1건 1줄)와 `### REQ-xxx` 상세 절의 `#### <열 이름>` 본문.

    문서 머리(첫 `##` 앞)의 `이름: 값` 줄은 meta 로 모은다(파일명의 버전 자리가 쓴다).
    """
    lines = re.split(r"\r\n|\n|\r", text)
    fenced: list[bool] = []  # 코드 펜스(```) 안의 줄은 제목·표로 보지 않는다
    inside = False
    for l in lines:
        if l.lstrip().startswith("```"):
            fenced.append(True)  # 펜스 줄 자신도 제목이 아니다
            inside = not inside
        else:
            fenced.append(inside)
    first_h2 = next((i for i, l in enumerate(lines) if re.match(r"^##\s", l) and not fenced[i]), len(lines))
    meta: dict[str, str] = {}
    for l in lines[:first_h2]:
        if l.lstrip().startswith("#"):
            continue
        m = _META_LINE.match(l)
        if m and m.group(2):
            meta.setdefault(norm(m.group(1)), m.group(2).strip())
    start = next((i for i, l in enumerate(lines) if re.match(r"^##\s+요구사항\s*$", l) and not fenced[i]), None)
    if start is None:
        raise ExportError("SRS 에 `## 요구사항` 절이 없다")
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^##\s", lines[i]) and not fenced[i]), len(lines))
    body = lines[start + 1: end]
    body_fenced = fenced[start + 1: end]
    first_h3 = next((i for i, l in enumerate(body) if re.match(r"^###\s", l) and not body_fenced[i]), len(body))
    parsed = _parse_table(body[:first_h3], "SRS · 요구사항")
    if not parsed:
        raise ExportError("SRS 의 `## 요구사항` 절에 표가 없다")
    header, rows, bad = parsed

    details: dict[str, dict[str, str]] = {}
    cur: str | None = None
    field_name: str | None = None
    buf: list[str] = []

    def flush_field() -> None:
        nonlocal field_name, buf
        if cur is not None and field_name is not None:
            while buf and not buf[0].strip():
                buf.pop(0)
            while buf and not buf[-1].strip():
                buf.pop()
            details[cur][field_name] = "\n".join(x.rstrip() for x in buf)
        field_name, buf = None, []

    for k, l in enumerate(body[first_h3:], start=first_h3):
        in_fence = body_fenced[k]
        h3 = None if in_fence else re.match(r"^###\s+(.+?)\s*$", l)
        if h3:
            flush_field()
            m = re.match(r"^(REQ-\d+)\b", h3.group(1))
            cur = m.group(1) if m else None
            if cur is not None:
                if cur in details:
                    raise ExportError(f"SRS 에 `### {cur}` 상세 절이 두 번 나온다", item=cur)
                details[cur] = {}
            continue
        h4 = None if in_fence else re.match(r"^####\s+(.+?)\s*$", l)
        if h4 and cur is not None:
            flush_field()
            field_name = norm(h4.group(1))
            if field_name in details[cur]:
                raise ExportError(f"{cur} 상세 절에 `#### {field_name}` 이 두 번 나온다", item=cur)
            details[cur][field_name] = ""
            continue
        if field_name is not None:
            buf.append(l)
    flush_field()
    return SrsDoc(header, rows, bad, details, meta)


# ---------------------------------------------------------------- 지도

def _check_form_name(form: str) -> None:
    """양식 이름은 지도 파일 이름이 되므로 경로 구분자·상위 경로를 막는다."""
    if not form or any(c in form for c in "/\\:") or ".." in form:
        raise ExportError(f"양식 이름 {form!r} 이 올바르지 않다(경로 구분자나 `..` 를 쓸 수 없다)", form=form)


def _inside(root: Path, path: Path, what: str, form: str = "") -> Path:
    """resolve 한 경로가 root 안이 아니면 읽지 못함으로 거절한다(절대경로·`..` 탈출 모두)."""
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        raise ExportError(f"{what} {path} 이 Project Repository({root}) 밖을 가리킨다", form=form) from None
    return resolved


def resolve_form(root: Path, form: str) -> str:
    """`--form` 값을 지도 이름(파일 이름 stem)으로 바꾼다. 이름 또는 지도 파일 경로를 받는다.

    경로는 --root 기준 상대 또는 절대이고 `.yaml`/`.yml` 확장자가 있어야 한다. 경로는 root 의
    `templates/forms/` 바로 아래의 실제 파일만 허용한다.
    """
    if not form:
        raise ExportError("--form 이 비어 있다")
    is_path = any(c in form for c in "/\\") or form.lower().endswith((".yaml", ".yml"))
    if not is_path:
        return form
    p = Path(form)
    if not p.is_absolute():
        # 구분자 없는 `Backlog.yaml` 은 templates/forms 아래 파일 이름으로 본다.
        p = root / (Path("templates") / "forms" / form if not any(c in form for c in "/\\") else p)
    resolved = p.resolve()
    forms_dir = (root / "templates" / "forms").resolve()
    if resolved.parent != forms_dir:
        raise ExportError(f"--form {form} 이 양식 지도 폴더({forms_dir}) 안의 파일이 아니다", form=form)
    if resolved.suffix.lower() not in (".yaml", ".yml") or not resolved.is_file():
        raise ExportError(f"--form {form} 에 해당하는 양식 지도 파일(.yaml)이 없다", form=form)
    name = resolved.stem
    if resolved.suffix != ".yaml":
        raise ExportError(f"양식 지도는 `.yaml` 확장자여야 한다: {resolved.name}", form=form)
    return name


def _in_origin_main(root: Path, rel: str) -> tuple[bool | None, str]:
    """root 기준 상대 경로 rel 이 origin/main 트리에 있는지. 판단 불능이면 (None, 사유). fetch 는 하지 않는다."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-c", "core.quotepath=false", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    try:
        head = git("rev-parse", "--verify", "--quiet", "origin/main^{commit}")
        if head.returncode != 0:
            return None, "git 저장소가 아니거나 origin/main 을 읽지 못했다(fetch 가 필요할 수 있다)"
        ls = git("ls-tree", "-r", "--name-only", "origin/main", "--", rel)
    except FileNotFoundError:
        return None, "git 을 실행하지 못했다(git 이 없다)"
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"git 실행이 실패했다: {e}"
    if ls.returncode != 0:
        return None, f"origin/main 트리를 읽지 못했다: {(ls.stderr or '').strip()}"
    return bool(ls.stdout.strip()), ""


def load_map(root: Path, form: str) -> tuple[dict, Path]:
    _check_form_name(form)
    path = _inside(root, root / "templates" / "forms" / f"{form}.yaml", "양식 지도", form)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise ExportError(f"양식 지도 {path} 를 읽지 못했다: {e}", form=form) from None
    if not isinstance(data, dict) or not data.get("템플릿") or not isinstance(data.get("시트"), list):
        raise ExportError(f"양식 지도 {path} 에 `템플릿`·`시트` 가 없다", form=form)
    out = data.get("산출")
    if not isinstance(out, dict) or not out.get("폴더") or not out.get("파일명"):
        raise ExportError(f"양식 지도 {path} 에 `산출.폴더`·`산출.파일명` 이 없다", form=form)
    for s in data["시트"]:
        if not isinstance(s, dict) or "이름" not in s:
            raise ExportError(f"양식 지도 {path} 의 시트에 `이름` 이 없다", form=form)
    return data, path


def _filename_pattern(fmap: dict, map_path: Path, root: Path, form: str) -> str | None:
    rel = fmap.get("검사_규칙")
    if not rel:
        return None
    rules_path = _inside(root, map_path.parent / str(rel), "검사 규칙", form)
    try:
        rules = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as e:
        raise ExportError(f"검사 규칙 {rules_path} 를 읽지 못했다: {e}", form=form) from None
    for rule in (rules or {}).get("규칙", []) or []:
        if isinstance(rule, dict) and rule.get("종류") == "filename":
            pattern = rule.get("패턴") or rule.get("pattern")  # 엔진(checker/rules/filename.py)과 같다
            if pattern:
                try:
                    re.compile(str(pattern))
                except re.error as e:
                    raise ExportError(f"검사 규칙 {rules_path} 의 filename 패턴이 정규식이 아니다: {e}", form=form) from None
                return str(pattern)
    return None


def _cell_range(loc: str) -> tuple[str, str]:
    a, _, b = str(loc).partition(":")
    return a, (b or a)


def _drawing_count(raw: dict[str, bytes], sheet_path: str) -> int:
    """시트에 딸린 drawing 의 그림·도형 개수."""
    d, _, base = sheet_path.rpartition("/")
    rels = raw.get(f"{d}/_rels/{base}.rels")
    if not rels:
        return 0
    total = 0
    for m in re.finditer(r"<Relationship\b[^>]*>", rels.decode("utf-8", "replace")):
        a = dict(_ATTR_RE.findall(m.group(0)))
        if not a.get("Type", "").endswith("/drawing"):
            continue
        t = a.get("Target", "")
        target = posixpath.normpath(t[1:] if t.startswith("/") else posixpath.join(d, t))
        data = raw.get(target)
        if data:
            total += len(re.findall(rb"<(?:\w+:)?(?:sp|pic|graphicFrame|cxnSp)[\s>/]", data))
    return total


# ---------------------------------------------------------------- 산출 한 양식

def _read_template(root: Path, map_path: Path, fmap: dict, form: str):
    """지도의 템플릿 xlsx 를 읽는다. (zip 항목들, 항목별 바이트, 시트 경로, 날짜 서식, workbook.xml)."""
    tpl = _inside(root, map_path.parent / str(fmap["템플릿"]), "템플릿", form)
    try:
        with zipfile.ZipFile(tpl) as zf:
            infos = zf.infolist()
            raw = {i.filename: zf.read(i.filename) for i in infos}
            paths = _sheet_paths(zf)
            date_styles = _date_styles(zf)
        wb_xml = raw["xl/workbook.xml"].decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
        raise ExportError(f"템플릿 {tpl} 를 읽지 못했다: {e}", form=form) from None
    return infos, raw, paths, date_styles, wb_xml


def is_srs_map(fmap: dict) -> bool:
    """표 하나라도 `원본: SRS` 면 SRS.md 의 요구사항 표를 원본으로 하는 지도다."""
    return any(
        isinstance(t, dict) and norm(str(t.get("원본", ""))).upper() == "SRS"
        for s in fmap["시트"] if isinstance(s, dict)
        for t in (s.get("표") or [])
    )


def build_form(
    form: str, spec_sections: dict, root: Path, srs: SrsDoc | None = None, replaced: list | None = None
) -> tuple[list[tuple[Path, bytes]], list[dict], list[dict]]:
    """한 양식을 산출한다. (쓸 파일, 거부 사유들, 경고들) 을 낸다. 못 읽으면 ExportError.

    `srs` 가 있으면 지도의 `원본: SRS` 표를 SRS.md 요구사항 표·상세 절로 채운다(작업본 `## 양식 항목` 은 쓰지 않는다).
    """
    fmap, map_path = load_map(root, form)
    if is_srs_map(fmap) != (srs is not None):
        raise ExportError(
            "이 지도는 원본이 SRS 다 — SRS.md 를 `--spec` 으로 주고 `--form` 으로 이 지도를 고른다"
            if is_srs_map(fmap) else "이 지도는 원본이 SRS 가 아니다 — 작업본의 `## 양식 항목` 으로 산출한다",
            form=form,
        )
    problems: list[dict] = []
    warnings: list[dict] = []

    def problem(sheet: str, item: str, reason: str) -> None:
        problems.append({"form": form, "sheet": sheet, "item": item, "reason": reason})

    def warn(sheet: str, item: str, reason: str) -> None:
        warnings.append({"form": form, "sheet": sheet, "item": item, "reason": reason})

    map_sheets = {norm(s["이름"]): s for s in fmap["시트"]}
    if srs is not None:
        for s in fmap["시트"]:
            if s.get("칸") or s.get("서술") or any(
                norm(str(t.get("원본", ""))).upper() != "SRS" for t in (s.get("표") or [])
            ):
                raise ExportError(
                    f"원본이 SRS 인 지도에는 시트 {s['이름']!r} 의 칸·서술·원본 없는 표를 둘 수 없다(`원본: SRS` 표만 쓴다)",
                    form=form, sheet=norm(s["이름"]),
                )
    for sheet in spec_sections:
        if sheet not in map_sheets:
            raise ExportError(f"작업본의 시트 {sheet!r} 이 양식 지도에 없다", form=form, sheet=sheet)

    infos, raw, paths, date_styles, wb_xml = _read_template(root, map_path, fmap, form)
    base1904 = bool(re.search(r'date1904="(1|true)"', wb_xml))

    editors: dict[str, SheetXml] = {}
    md_values: dict[str, dict] = {}  # 파일명 자리가 쓸 작업본 값

    def editor(sheet: str) -> SheetXml:
        if sheet not in editors:
            if sheet not in paths:
                raise ExportError(f"템플릿에서 시트 {sheet!r} 의 XML 을 찾지 못했다", form=form, sheet=sheet)
            try:
                editors[sheet] = SheetXml(raw[paths[sheet]].decode("utf-8-sig"), date_styles, base1904)
            except KeyError:
                raise ExportError(f"템플릿에서 시트 {sheet!r} 의 XML 을 찾지 못했다", form=form, sheet=sheet) from None
        return editors[sheet]

    def make_put(sname: str, ed: SheetXml):
        def put(item: str, ref: str, text: str, **kw) -> None:
            try:
                removed = ed.set(ref, text, **kw)
            except CellTooLong as e:
                problem(sname, item, e.reason)
                return
            except ExportError as e:
                raise ExportError(e.reason, form=form, sheet=sname, item=item) from None
            if removed:
                warn(sname, item, f"{ref} 에 쓸 값에서 XML 에 넣을 수 없는 제어 문자 {removed}개를 지웠다")
        return put

    reader = ListReader(raw, paths, wb_xml)
    validations: dict[str, list] = {}
    unchecked_seen: set[tuple[str, str]] = set()

    def make_check(sname: str):
        """표에 쓴 값이 템플릿 드롭다운 목록 안인지 본다. (칸 검사, 행 검사) 를 돌려준다.

        warnings 의 type: dropdown(목록 밖 값) / dropdown-unchecked(허용 값을 읽지 못해 검사 못 함) /
        dropdown-empty(목록 범위가 실제로 비어 있어 검사할 값이 없음) / dropdown-missing(그 줄엔 드롭다운이 없음).
        """
        def unchecked(kind: str, header: str, formula: str, reason: str) -> None:
            if (sname, kind, formula) in unchecked_seen:
                return
            unchecked_seen.add((sname, kind, formula))
            warnings.append({"form": form, "sheet": sname, "item": header, "type": kind, "reason": reason})

        def load() -> bool:
            try:
                if sname not in validations:
                    validations[sname] = reader.validations(sname)
            except Exception as e:  # 유효성 XML 이 예상과 다르면 검사 불능으로 알린다
                validations[sname] = []
                unchecked("dropdown-unchecked", "", "", f"시트 {sname} 의 데이터 유효성을 읽지 못해 목록 검사를 못 했다({type(e).__name__}: {e})")
                return False
            return True

        def check(tname: str, label: str, header: str, ref: str, val: str) -> None:
            if not load():
                return
            col, row = split_ref(ref)
            v = find_validation(validations[sname], col2n(col), row)
            if v is None or not v.enforced:
                return  # 드롭다운이 없거나, 엑셀이 목록 밖 값을 받는 설정(오류 메시지 꺼짐·정보·경고 스타일)
            if v.allowed is None:
                unchecked("dropdown-unchecked", header, v.formula,
                          f"{header} 열의 드롭다운 목록({v.formula})을 읽지 못해 목록 검사를 못 했다: {v.why}")
                return
            if v.empty:
                unchecked("dropdown-empty", header, v.formula,
                          f"{header} 열의 드롭다운 목록({v.formula})에 값이 없어 검사할 허용 값이 없다")
                return
            if val.strip() in v.allowed:
                return
            shown = ", ".join(v.allowed[:30]) + (f" … (전체 {len(v.allowed)}개)" if len(v.allowed) > 30 else "")
            hint = ""
            same = [a for a in v.allowed if a.lower() == val.strip().lower()]
            if same:
                hint = f" 대소문자만 다르다({same[0]!r})."
            warnings.append({
                "form": form, "sheet": sname, "item": label, "type": "dropdown",
                "row": row, "column": header, "cell": ref, "value": val, "allowed": list(v.allowed),
                "reason": f"{label} 의 {header} 칸({ref}) 값 {val!r} 이 드롭다운 허용 값 밖이다.{hint} 허용 값: {shown}",
            })

        def row_check(tname: str, label: str, rn: int, letters: list[str]) -> None:
            """이 줄이 드롭다운 범위 밖이면(같은 열의 다른 줄엔 드롭다운이 있는데) 한 줄로 알린다."""
            if not load():
                return
            vs = validations[sname]
            missing = [
                c for c in letters
                if any(c1 <= col2n(c) <= c2 for v in vs for c1, _, c2, _ in v.ranges)
                and find_validation(vs, col2n(c), rn) is None
            ]
            if missing:
                warnings.append({
                    "form": form, "sheet": sname, "item": label, "type": "dropdown-missing", "row": rn,
                    "reason": f"{label}: {rn}행 — 이 줄엔 드롭다운이 없다(열 {', '.join(missing)}). 이 줄의 값은 목록 검사를 못 한다",
                })
        return check, row_check

    for sname, smap in map_sheets.items():
        if srs is not None:
            srs_tabs = [t for t in smap.get("표") or [] if norm(str(t.get("원본", ""))).upper() == "SRS"]
            if not srs_tabs:
                continue  # SRS 원본 지도는 SRS 표가 있는 시트만 건드린다(드롭다운 목록 시트 등은 그대로)
            ed = editor(sname)
            put = make_put(sname, ed)
            for t in srs_tabs:
                tname = norm(t["이름"])
                rows = _srs_table_rows(form, sname, tname, t, srs, problem)
                chk, rchk = make_check(sname)
                _write_table(form, sname, tname, t, {tname: t}, {}, ed, md_values, problem, [], put,
                             srs_rows=rows, check=chk, row_check=rchk)
            continue
        na = sname not in spec_sections or spec_sections[sname][0].na
        sec, subs = spec_sections.get(sname, (Section(na=True), {}))
        ed = editor(sname)
        put = make_put(sname, ed)
        fields = {norm(f["항목"]): f for f in smap.get("칸", []) or []}
        tables = {norm(t["이름"]): t for t in smap.get("표", []) or []}
        texts = {norm(n["이름"]): n for n in smap.get("서술", []) or []}

        for item, reason in sec.issues:
            problem(sname, item, reason)

        # 작업본이 가리키는 것이 지도에 있는지부터 본다(없으면 읽지 못함).
        for name in sec.fields:
            if name not in fields:
                raise ExportError(f"작업본의 칸 {name!r} 이 양식 지도에 없다", form=form, sheet=sname, item=name)
        for name in subs:
            if name not in tables and name not in texts:
                raise ExportError(f"작업본의 `#### {name}` 이 양식 지도의 표·서술에 없다", form=form, sheet=sname, item=name)

        # 칸
        for name, f in fields.items():
            if f.get("자동"):
                continue
            val = _clean(sec.fields.get(name))
            if not val:
                if f.get("필수"):
                    problem(sname, name, "필수 칸이 미정이거나 비어 있다")
                elif f.get("예시") is not None:
                    ed.clear(str(f["위치"]))
                continue
            text = _BR.sub("\n", val)
            if f.get("형식"):
                text = str(f["형식"]).replace("{값}", text)
            put(name, str(f["위치"]), text)

        # 표
        sheet_tops = [(split_ref(_cell_range(f["위치"])[0])[1], f["항목"]) for f in fields.values()]
        sheet_tops += [(split_ref(_cell_range(n["위치"])[0])[1], n["이름"]) for n in texts.values()]
        for tname, t in tables.items():
            chk, rchk = make_check(sname)
            _write_table(form, sname, tname, t, tables, subs, ed, md_values, problem, sheet_tops, put,
                         check=chk, row_check=rchk)

        # 서술: 한 셀이면 줄바꿈 포함 한 셀, 범위면 줄마다 범위 첫 열의 한 행씩
        for name, n in texts.items():
            body = list(subs.get(name, []))
            lines = [x.rstrip() for l in body for x in _BR.split(l) if x.strip()]
            if lines in ([UNDECIDED], [NOT_APPLICABLE]):
                lines = []
            first, last = _cell_range(n["위치"])
            if not lines:
                if n.get("필수"):
                    problem(sname, name, "필수 서술이 미정이거나 비어 있다")
                ed.clear_range(first, last)
                continue
            c1, r1 = split_ref(first)
            _, r2 = split_ref(last)
            if first == last:
                ed.clear_range(first, last, keep=first)
                text = "\n".join(l.rstrip() for l in _BR.sub("\n", "\n".join(body)).splitlines()).strip()
                put(name, first, text)
            elif len(lines) > r2 - r1 + 1:
                problem(sname, name, f"서술이 {len(lines)}줄이라 범위 {n['위치']}({r2 - r1 + 1}행)를 넘는다")
            else:
                ed.clear_range(first, last)
                for i, line in enumerate(lines):
                    put(name, f"{c1}{r1 + i}", line)

        # 해당 없음·작업본에 없는 시트에 지도 밖 템플릿 샘플이 남으면 알린다(지우지 않는다).
        if na:
            pics = _drawing_count(raw, paths[sname])
            left = ed.valued_refs()
            if pics or left:
                parts = []
                if pics:
                    parts.append(f"그림·도형 {pics}개")
                if left:
                    parts.append(f"값이 있는 셀 {len(left)}개: {', '.join(left[:5])}{' …' if len(left) > 5 else ''}")
                warn(sname, "", f"템플릿 샘플({', '.join(parts)})이 남아 있다 — 엑셀에서 확인해 지우십시오")

    # 파일명
    out_name = _file_name(form, fmap, map_sheets, spec_sections, md_values, problem, srs.meta if srs else None)
    out_path = None
    if out_name:
        bad = [c for c in FORBIDDEN_NAME_CHARS if c in out_name]
        pattern = _filename_pattern(fmap, map_path, root, form)
        folder = _inside(root, root / str(fmap["산출"]["폴더"]), "산출.폴더", form)
        if bad:
            problem("", "파일명", f"파일 이름 {out_name!r} 에 쓸 수 없는 문자 {' '.join(bad)} 가 있다")
        elif pattern and not re.search(pattern, out_name):
            problem("", "파일명", f"파일 이름 {out_name!r} 이 검사 규칙의 파일명 패턴 {pattern} 과 맞지 않는다")
        else:
            out_path = folder / out_name
            if out_path.exists():
                rel = out_path.relative_to(root.resolve()).as_posix()
                in_main, why = _in_origin_main(root, rel)
                if in_main is False:
                    # 이 브랜치에서 만든 판(main 에 아직 없다) — 같은 버전으로 다시 산출한다.
                    if replaced is not None:
                        replaced.append({"file": rel, "reason": f"{rel} 는 origin/main 에 없는 판(이 브랜치에서 만든 판)이라 같은 버전으로 덮어쓴다"})
                elif in_main:
                    problem("", "파일명", f"{rel} 가 이미 있고 main 에 이미 있는 판이다. 이전 판은 덮어쓰지 않는다 — 버전을 올려 새 판으로 산출한다")
                    out_path = None
                else:
                    problem("", "파일명", f"{rel} 가 이미 있는데 main 에 있는 판인지 판단하지 못해 덮어쓰지 않는다(검사 불능, 통과 아님): {why}")
                    out_path = None

    unique: list[dict] = []
    for p in problems:
        if p not in unique:
            unique.append(p)
    if unique or out_path is None:
        return [], unique, warnings

    # 쓸 바이트를 만든다. 바뀐 시트와 workbook.xml 말고는 그대로 복사한다.
    changed = {paths[s]: ed for s, ed in editors.items() if ed.dirty}
    has_formula = any(
        re.search(rb"<f[\s>/]", data) for name, data in raw.items() if name.startswith("xl/worksheets/sheet")
    )
    rendered = {path: ed.render() for path, ed in changed.items()}
    new_wb = wb_xml
    if has_formula:
        new_wb = _with_full_calc(new_wb)
    for s_name, ed in editors.items():
        if ed.dirty and ed.filter_change:
            new_wb = _extend_filter_database(new_wb, s_name, *ed.filter_change)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zo:
        for info in infos:
            data = raw[info.filename]
            if info.filename in changed:
                bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
                data = bom + rendered[info.filename].encode("utf-8")
            elif info.filename == "xl/workbook.xml" and new_wb != wb_xml:
                data = new_wb.encode("utf-8")
            zo.writestr(copy.copy(info), data)
    return [(out_path, buf.getvalue())], [], warnings


def _write_table(
    form, sname, tname, t, tables, subs, ed, md_values, problem, sheet_tops, put,
    srs_rows: tuple[list[dict[str, str]], list[str]] | None = None, check=None, row_check=None,
) -> None:
    """표를 쓴다. `srs_rows` 가 있으면 (행들, 행 이름들)을 그대로 쓰고 작업본 표는 읽지 않는다."""
    cols = {norm(k): str(v) for k, v in (t.get("열") or {}).items()}
    start = int(t["시작_행"])
    max_rows = int(t["최대_행"]) if t.get("최대_행") is not None else None
    partner = norm(t["짝"]) if t.get("짝") else None
    if partner and partner not in tables:
        raise ExportError(f"표 {tname!r} 의 짝 {partner!r} 이 지도에 없다", form=form, sheet=sname, item=tname)

    labels: list[str] | None = None
    if srs_rows is not None:
        md_rows, labels = srs_rows
    else:
        md_rows = _md_table_rows(form, sname, tname, cols, subs, problem)
        if partner is None:
            md_rows = [r for r in md_rows if any(v for v in r.values())]
        else:
            pr = _md_table_rows(form, sname, partner, {norm(k): v for k, v in (tables[partner].get("열") or {}).items()}, subs)
            if len(pr) != len(md_rows) and tname < partner:
                problem(sname, tname, f"짝 표 {partner!r} 와 행 수가 다르다({len(md_rows)}행 대 {len(pr)}행)")
    md_values.setdefault("tables", {})[tname] = [r for r in md_rows if any(v for v in r.values())]
    if t.get("필수") and not md_values["tables"][tname]:
        problem(sname, tname, "필수 표가 미정이거나 비어 있다")

    # 행 펼치기
    out_rows: list[dict[str, str]] = []
    out_labels: list[str] = []
    split_rows = t.get("여러_줄") == "행"
    for k, r in enumerate(md_rows):
        label = labels[k] if labels else ""
        if split_rows:
            lines = {c: _BR.split(v) if v else [""] for c, v in r.items()}
            h = max(len(v) for v in lines.values()) if lines else 1
            for i in range(h):
                out_rows.append({c: (v[i].strip() if i < len(v) else "") for c, v in lines.items()})
                out_labels.append(label)
        else:
            out_rows.append({c: _BR.sub("\n", v) for c, v in r.items()})
            out_labels.append(label)
    header_of = {}
    for name, letter in cols.items():
        header_of.setdefault(letter, name)
    if max_rows is not None and len(out_rows) > max_rows:
        problem(sname, tname, f"행이 최대 {max_rows}행을 넘었다({len(out_rows)}행)")
        return

    # 템플릿의 데이터 영역
    letters = list(cols.values())
    if max_rows is not None:
        tmpl_last = start + max_rows - 1
    else:
        tmpl_last = start - 1
        while any(ed.has_value(f"{c}{tmpl_last + 1}") for c in letters):
            tmpl_last += 1

    last_row = start + len(out_rows) - 1
    if max_rows is None and last_row > tmpl_last:
        below = [n for top, n in sheet_tops if top > start]
        below += [
            f"표 {norm(o['이름'])}" for o in tables.values()
            if o is not t and int(o["시작_행"]) > start
        ]
        if below:
            problem(sname, tname, f"행이 템플릿 데이터 행보다 늘어나는데 아래에 다른 항목({below[0]})이 있어 행을 더할 수 없다")
            return

    clone = tmpl_last if tmpl_last >= start else None
    # 이름(열 머리글) → md 열 문자
    for i, row in enumerate(out_rows):
        rn = start + i
        new_row = max_rows is None and rn > tmpl_last
        for c in letters:
            ref = f"{c}{rn}"
            val = row.get(c, "")
            if val:
                style = ed.style_of(f"{c}{clone}") if (new_row and clone) else None
                put(tname, ref, val, style=style, clone_row=clone if new_row else None)
                if check:
                    check(tname, out_labels[i] or f"{rn}행", header_of.get(c, c), ref, val)
            elif not new_row:
                ed.clear(ref)
            elif clone:
                ed.blank(ref, ed.style_of(f"{c}{clone}"), clone)
        ed.unhide(rn)
        if any(row.get(c) for c in letters):
            if srs_rows is not None:
                ed.autofit(rn)  # 여러 줄 칸이 템플릿의 고정 줄 높이에 잘리지 않게
            if row_check:
                row_check(tname, out_labels[i] or f"{rn}행", rn, [c for c in letters if row.get(c)])
    for rn in range(start + len(out_rows), tmpl_last + 1):
        for c in letters:
            ed.clear(f"{c}{rn}")


def _md_table_rows(form, sname, tname, cols_by_name, subs, problem=None) -> list[dict[str, str]]:
    """작업본의 `#### <표>` 표를 {열 문자: 값} 행들로 바꾼다. 열 이름이 지도에 없으면 읽지 못함."""
    body = subs.get(tname)
    if not body:
        return []
    parsed = _parse_table(body, f"{form} · {sname} · {tname}")
    if not parsed:
        return []
    header, rows, bad = parsed
    if problem:
        for n, cnt in bad:
            problem(sname, tname, f"{n}번째 행의 셀 수({cnt})가 머리글({len(header)})과 다르다")
    # cols_by_name: {정규화한 머리글: 열 문자}
    letters = []
    for h in header:
        if h not in cols_by_name:
            raise ExportError(f"작업본 표 {tname!r} 의 열 {h!r} 이 양식 지도에 없다", form=form, sheet=sname, item=tname)
        letters.append(cols_by_name[h])
    return [{L: _clean(v) for L, v in zip(letters, r)} for r in rows]


def _srs_table_rows(form, sname, tname, t, srs: SrsDoc, problem) -> tuple[list[dict[str, str]], list[str]]:
    """SRS 요구사항 표 + 상세 절 → ({열 문자: 값} 행들, 행 이름(REQ-xxx)들).

    md 표 열은 지도 `열` 이름이거나 `ID`(→ `번호_열` 에 REQ 번호의 숫자) 거나 지도 `md_전용` 에 적힌 열이다.
    상세 절 `#### <열 이름>` 은 지도 `열` 의 해당 칸 값이 된다. 그 밖의 이름은 읽지 못함(오타를 조용히 버리지 않는다).
    """
    cols = {norm(k): str(v) for k, v in (t.get("열") or {}).items()}
    md_only = {norm(x) for x in (t.get("md_전용") or [])}
    id_name = norm(t["번호_열"]) if t.get("번호_열") else None
    if id_name and id_name not in cols:
        raise ExportError(f"표 {tname!r} 의 번호_열 {id_name!r} 이 지도 열에 없다", form=form, sheet=sname, item=tname)
    if "ID" not in srs.header:
        raise ExportError("SRS 요구사항 표에 `ID` 열이 없다", form=form, sheet=sname, item=tname)
    if len(set(srs.header)) != len(srs.header):
        raise ExportError("SRS 요구사항 표에 같은 이름의 열이 둘 이상 있다", form=form, sheet=sname, item=tname)
    letters: list[str | None] = []
    for h in srs.header:
        if h == "ID" or h in md_only:
            letters.append(None)
        elif h in cols:
            letters.append(cols[h])
        else:
            raise ExportError(
                f"SRS 요구사항 표의 열 {h!r} 이 양식 지도의 열에도 `md_전용` 에도 없다",
                form=form, sheet=sname, item=h,
            )
    for n, cnt in srs.bad:
        problem(sname, tname, f"요구사항 표 {n}번째 행의 셀 수({cnt})가 머리글({len(srs.header)})과 다르다")

    all_ids = {r[srs.header.index("ID")].strip() for r in srs.rows}
    for rid, fields in srs.details.items():
        if rid not in all_ids:
            raise ExportError(f"`### {rid}` 상세 절에 해당하는 요구사항 표 행이 없다", form=form, sheet=sname, item=rid)
        for fname in fields:
            if fname not in md_only and (fname not in cols or fname == id_name):
                raise ExportError(
                    f"{rid} 상세 절의 `#### {fname}` 이 양식 지도의 열에 없다", form=form, sheet=sname, item=rid
                )

    rows: list[dict[str, str]] = []
    labels: list[str] = []
    seen: set[str] = set()
    id_at = srs.header.index("ID")
    for r in srs.rows:
        rid = r[id_at].strip()
        m = _REQ_ID.match(rid)
        if not m:
            problem(sname, rid or "(빈 ID)", f"요구사항 표의 ID {rid!r} 가 `REQ-숫자` 모양이 아니다")
            continue
        if rid in seen:
            problem(sname, rid, "요구사항 표에 같은 ID 가 두 줄 이상 있다")
            continue
        seen.add(rid)
        row: dict[str, str] = {}
        if id_name:
            row[cols[id_name]] = str(int(m.group(1)))
        for letter, v in zip(letters, r):
            if letter:
                row[letter] = _clean(v)
        for fname, body in srs.details.get(rid, {}).items():
            body = _clean(body)
            if fname in md_only or not body:
                continue
            if row.get(cols[fname]):
                problem(sname, rid, f"{fname} 이 표 칸과 상세 절 양쪽에 적혀 있다 — 한쪽만 둔다")
            else:
                row[cols[fname]] = body
        rows.append(row)
        labels.append(rid)
    if not rows and not srs.bad:
        problem(sname, tname, "요구사항 표에 산출할 요구사항 줄이 없다")
    return rows, labels


def _file_name(form, fmap, map_sheets, spec_sections, md_values, problem, meta=None) -> str | None:
    out = fmap["산출"]
    slots = out.get("자리") or {}
    ok = True

    def value_of(name: str) -> str | None:
        spec = slots.get(name)
        if spec is None:
            # 같은 이름의 칸
            for sname, sm in map_sheets.items():
                for f in sm.get("칸", []) or []:
                    if norm(f["항목"]) == name:
                        return _field_value(spec_sections, sname, name)
            raise ExportError(f"파일명의 {{{name}}} 가 어디서 오는지 알 수 없다(`자리` 도 같은 이름의 칸도 없다)", form=form, item=name)
        if not isinstance(spec, dict):
            raise ExportError(f"`자리.{name}` 의 모양이 틀렸다", form=form, item=name)
        if "칸" in spec:
            want = norm(spec["칸"])
            for sname, sm in map_sheets.items():
                if any(norm(f["항목"]) == want for f in sm.get("칸", []) or []):
                    v = _field_value(spec_sections, sname, want)
                    break
            else:
                raise ExportError(f"`자리.{name}` 의 칸 {want!r} 이 지도에 없다", form=form, item=name)
        elif "메타" in spec:
            # SRS 문서 머리의 `이름: 값` 줄(예: `버전: 0.1`)
            key = norm(spec["메타"])
            v = (meta or {}).get(key, "")
            if key == "버전":
                v = re.sub(r"^[vV](?=\d)", "", v)
        elif "표" in spec:
            tname, col = norm(spec["표"]), norm(spec.get("열", ""))
            tmap = next((t for sm in map_sheets.values() for t in sm.get("표", []) or [] if norm(t["이름"]) == tname), None)
            if tmap is None:
                raise ExportError(f"`자리.{name}` 의 표 {tname!r} 이 지도에 없다", form=form, item=name)
            letter = {norm(k): str(x) for k, x in (tmap.get("열") or {}).items()}.get(col)
            if letter is None:
                raise ExportError(f"`자리.{name}` 의 열 {col!r} 이 표 {tname!r} 에 없다", form=form, item=name)
            vals = [r.get(letter, "") for r in md_values.get("tables", {}).get(tname, [])]
            vals = [x for x in vals if x]
            if not vals:
                v = ""
            else:
                v = vals[0] if spec.get("행") == "처음" else vals[-1]
        else:
            raise ExportError(f"`자리.{name}` 에 `칸`·`표`·`메타` 가 없다", form=form, item=name)
        if v and spec.get("떼기") and v.startswith(str(spec["떼기"])):
            v = v[len(str(spec["떼기"])):]
        return v.strip()

    def sub(m: re.Match) -> str:
        nonlocal ok
        name = norm(m.group(1))
        v = value_of(name)
        if not v:
            problem("", f"파일명 {{{name}}}", f"파일 이름에 들어갈 {name} 값이 없다(미정이거나 비어 있다)")
            ok = False
            return ""
        return v

    name = re.sub(r"\{([^{}]+)\}", sub, str(out["파일명"]))
    return name if ok else None


def _field_value(spec_sections, sname, name) -> str:
    sec = spec_sections.get(sname, (Section(), {}))[0]
    return _clean(sec.fields.get(name))


# ---------------------------------------------------------------- 진입점

def _commit(writes: list[tuple[Path, bytes]], root: Path, replace: frozenset[Path] = frozenset()) -> list[str]:
    """산출물을 원자적으로 쓴다.

    모두 같은 폴더의 임시 파일로 먼저 쓰고, 전부 성공하면 최종 이름으로 rename 한다. 최종 이름이
    그 사이 생겼거나 하나라도 실패하면 이번 실행이 만든 임시·최종 파일(과 새로 만든 폴더)을 모두
    지우고 ExportError 를 낸다.
    """
    temps: list[Path] = []
    finals: list[Path] = []
    backups: list[tuple[Path, Path]] = []
    made_dirs: list[Path] = []
    try:
        for i, (path, data) in enumerate(writes):
            missing = []
            d = path.parent
            while not d.exists():
                missing.append(d)
                d = d.parent
            path.parent.mkdir(parents=True, exist_ok=True)
            made_dirs += missing  # 깊은 폴더가 먼저 오도록 아래에서 뒤집어 지운다
            tmp = path.parent / f".{path.name}.{os.getpid()}.{i}.tmp"
            temps.append(tmp)
            with open(tmp, "xb") as fh:
                fh.write(data)
        for (path, _), tmp in zip(writes, temps):
            if path.exists():
                if path not in replace:
                    raise ExportError(f"{path} 가 이미 있다. 이전 판은 덮어쓰지 않는다")
                backup = path.parent / f".{path.name}.{os.getpid()}.bak"
                os.replace(path, backup)
                backups.append((path, backup))
            os.rename(tmp, path)
            finals.append(path)
    except BaseException as e:
        for f in temps + finals:
            try:
                f.unlink()
            except OSError:
                pass
        for path, backup in backups:
            try:
                os.replace(backup, path)
            except OSError:
                pass
        for d in sorted(set(made_dirs), key=lambda x: len(x.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        if isinstance(e, ExportError):
            raise
        if isinstance(e, Exception):
            raise ExportError(f"산출물을 쓰지 못했다: {e}") from None
        raise
    for _, backup in backups:
        try:
            backup.unlink()
        except OSError:
            pass
    return [p.relative_to(root).as_posix() for p, _ in writes]


def _srs_map_names(root: Path) -> list[str]:
    """templates/forms 에서 `원본: SRS` 표가 있는 지도 이름들(읽지 못한 지도는 건너뛴다)."""
    out: list[str] = []
    folder = root / "templates" / "forms"
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("시트"), list) and is_srs_map(data):
                out.append(f.stem)
        except Exception:
            continue
    return out


def run(spec: Path, root: Path, only_form: str | None, check_only: bool = False) -> tuple[int, dict]:
    try:
        text = spec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ExportError(f"작업본 {spec} 를 읽지 못했다: {e}") from None
    srs: SrsDoc | None = None
    if only_form is not None:
        only_form = resolve_form(root, only_form)
        _check_form_name(only_form)
        if is_srs_map(load_map(root, only_form)[0]):
            srs = parse_srs(text)
    if srs is not None:
        jobs: list[tuple[str, dict]] = [(only_form, {})]
    else:
        try:
            forms = parse_spec(text)
        except ExportError as e:
            maps = _srs_map_names(root)
            if only_form is None and maps and "`## 양식 항목` 절이 없다" in e.reason:
                raise ExportError(
                    f"SRS 원본은 --form <지도> 가 필요하다(이 저장소의 SRS 원본 지도: {', '.join(maps)})"
                ) from None
            raise
        for name in forms:
            _check_form_name(name)
        if only_form is not None:
            if only_form not in forms:
                raise ExportError(f"작업본에 양식 {only_form!r} 소절이 없다", form=only_form)
            forms = {only_form: forms[only_form]}
        jobs = list(forms.items())

    writes: list[tuple[Path, bytes]] = []
    problems: list[dict] = []
    warnings: list[dict] = []
    replaced: list[dict] = []
    for form, sections in jobs:
        w, p, wa = build_form(form, sections, root, srs, replaced)
        writes += w
        problems += p
        warnings += wa
    if problems:
        return EXIT_REJECTED, {
            "status": "rejected",
            "files": [],
            "problems": problems,
            "warnings": warnings,
            "next": "다음: 아래 항목을 채우거나 고쳐 작업본을 갱신한 뒤 다시 산출한다. 아무 파일도 만들지 않았다.",
        }
    names = [p for p, _ in writes]
    if len(set(names)) != len(names):
        raise ExportError("서로 다른 양식이 같은 파일 이름을 산출한다")
    outside = any(w.get("type") == "dropdown" for w in warnings)
    unchecked = any(w.get("type") == "dropdown-unchecked" for w in warnings)
    flagged = outside or unchecked
    note = _warning_note(outside, unchecked)
    # 이 브랜치에서 만든 판을 같은 버전으로 덮어쓰는 경우의 표시(덮어쓸 파일이 없으면 빈 dict)
    rp = {"replaced": True, "replaced_files": replaced} if replaced else {}
    rp_note = " 이 브랜치에서 만든 판(origin/main 에 없음)은 같은 버전으로 덮어썼다." if replaced else ""
    if check_only:
        files = [p.relative_to(root).as_posix() for p in names]
        return (EXIT_WARNING if flagged else EXIT_OK), {
            "status": "warning" if flagged else "ok",
            "dry_run": True,
            **rp,
            "files": files,
            "problems": [],
            "warnings": warnings,
            "next": (
                "다음: 확인만 했고 파일은 만들지 않았다. "
                + (note + " 고친 뒤 다시 확인한다." if flagged else "문제가 없으면 --check 없이 다시 실행해 산출한다.")
            ),
        }
    written = _commit(writes, root, frozenset(root / r["file"] for r in replaced))
    if flagged:
        return EXIT_WARNING, {
            "status": "warning",
            **rp,
            "files": written,
            "problems": [],
            "warnings": warnings,
            "next": (
                f"다음: 파일은 만들었지만 {note} "
                "고쳐 다시 산출한다(같은 이름 파일이 있으면 덮지 않으므로 방금 만든 파일을 지우거나 버전을 올린다)."
            ),
        }
    return EXIT_OK, {
        "status": "ok",
        **rp,
        "files": written,
        "problems": [],
        "warnings": warnings,
        "next": "다음:" + rp_note + " 엑셀로 한 번 열어 서식을 확인한다. 올리면 PR 에서 doc-guard(Actions)가 파일 이름과 구조를 검사한다.",
    }


def _warning_note(outside: bool, unchecked: bool) -> str:
    parts = []
    if outside:
        parts.append("`type: dropdown` 경고의 값이 템플릿 드롭다운 목록 밖이다 — 허용 값 중에서 고른다.")
    if unchecked:
        parts.append("허용 값을 읽지 못해 검사하지 못한 열이 있다(`type: dropdown-unchecked`) — 통과가 아니니 그 열의 값을 사람이 확인한다.")
    return " ".join(parts)


def list_values(root: Path, form: str) -> dict:
    """지도 템플릿의 드롭다운 허용 값을 시트·열별로 낸다(스킬이 읽어 사용자에게 고르게 한다).

    열 이름은 지도 표의 `열` 이름이다. 지도에 없는 열의 유효성은 내지 않는다.
    """
    form = resolve_form(root, form)
    _check_form_name(form)
    fmap, map_path = load_map(root, form)
    infos, raw, paths, _, wb_xml = _read_template(root, map_path, fmap, form)
    reader = ListReader(raw, paths, wb_xml)
    sheets: list[dict] = []
    for s in fmap["시트"]:
        sname = norm(s["이름"])
        headers: dict[int, str] = {}
        for t in s.get("표") or []:
            for name, letter in (t.get("열") or {}).items():
                headers.setdefault(col2n(str(letter)), norm(name))
        if not headers or sname not in paths:
            continue
        columns: list[dict] = []
        try:
            validations = reader.validations(sname)
        except Exception as e:
            raise ExportError(f"시트 {sname!r} 의 데이터 유효성을 읽지 못했다: {e}", form=form, sheet=sname) from None
        for v in validations:
            for c in sorted({c for c1, _, c2, _ in v.ranges for c in range(c1, c2 + 1)} & set(headers)):
                cells = " ".join(
                    f"{n2col(c)}{r1}:{n2col(c)}{r2}" if r1 != r2 else f"{n2col(c)}{r1}"
                    for c1, r1, c2, r2 in v.ranges if c1 <= c <= c2
                )
                columns.append({
                    "column": headers[c],
                    "letter": n2col(c),
                    "cells": cells,
                    "allowed": v.allowed,
                    "enforced": v.enforced,
                    **({"unreadable": v.why} if v.allowed is None else {}),
                    **({"empty": v.why} if v.empty else {}),
                })
        columns.sort(key=lambda x: col2n(x["letter"]))
        sheets.append({"sheet": sname, "columns": columns})
    warns = [
        {"form": form, "sheet": sh["sheet"], "item": c["column"], "type": "dropdown-unchecked",
         "reason": f"{c['column']} 열의 허용 값을 읽지 못했다: {c['unreadable']}"}
        for sh in sheets for c in sh["columns"] if c["allowed"] is None
    ] + [
        {"form": form, "sheet": sh["sheet"], "item": c["column"], "type": "dropdown-empty",
         "reason": f"{c['column']} 열의 목록이 비어 있어 허용 값이 없다"}
        for sh in sheets for c in sh["columns"] if c.get("empty")
    ]
    unread = any(w["type"] == "dropdown-unchecked" for w in warns)
    return {
        "status": "warning" if unread else "ok",
        "form": form,
        "sheets": sheets,
        "problems": [],
        "warnings": warns,
        "next": (
            "다음: 드롭다운이 있는 열은 `allowed` 안의 값만 쓴다(`enforced: false` 인 열은 엑셀이 목록 밖 값도 받는다). "
            + ("허용 값을 읽지 못한 열(`allowed: null`)이 있다 — 그 열은 값을 사람이 확인한다." if unread else "목록 밖 값은 산출 때 경고된다.")
        ),
    }


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def _error_report(reason: str, form: str = "", sheet: str = "", item: str = "") -> dict:
    return {
        "status": "error",
        "files": [],
        "problems": [{"form": form, "sheet": sheet, "item": item, "reason": reason}],
        "warnings": [],
        "next": "다음: 읽지 못한 원인을 고친 뒤 다시 시도한다. 산출하지 못했다 — 통과가 아니다.",
    }


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="python -m checker.export",
        description="작업본(md)의 `## 양식 항목` 이나 SRS.md 의 요구사항 표를 양식 xlsx 로 산출한다.",
    )
    parser.add_argument("--spec", type=Path, help="작업본 md(docs/spec/DEV-xxx-….md) 또는 원본이 SRS 인 지도면 docs/ssot/SRS.md")
    parser.add_argument("--root", type=Path, required=True, help="Project Repository 루트")
    parser.add_argument("--form", help="이 양식만 산출한다(생략하면 작업본의 모든 양식). 지도 이름 또는 지도 파일 경로(--root 기준 상대·절대). 원본이 SRS 인 지도는 필수")
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 같은 검사·보고만 한다")
    parser.add_argument("--list-values", action="store_true", help="--form 지도 템플릿의 드롭다운 허용 값을 열별 JSON 으로 낸다")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise ExportError(f"--root {args.root} 가 폴더가 아니다")
        if args.list_values:
            if not args.form:
                raise ExportError("--list-values 에는 --form <지도 이름> 이 필요하다")
            report = list_values(root, args.form)
            code = EXIT_WARNING if report["status"] == "warning" else EXIT_OK
        else:
            if args.spec is None:
                raise ExportError("--spec 이 필요하다(--list-values 가 아니면)")
            code, report = run(args.spec, root, args.form, args.check)
    except ExportError as e:
        code, report = EXIT_ERROR, _error_report(e.reason, e.form, e.sheet, e.item)
    except Exception as e:  # 예상하지 못한 오류도 검사 불능(2)이지 거부(1)가 아니다
        code, report = EXIT_ERROR, _error_report(f"예상하지 못한 오류({type(e).__name__}): {e}")
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
