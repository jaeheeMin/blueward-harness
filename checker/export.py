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
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, unescape

import yaml

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_ERROR = 2

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

    def render(self) -> str:
        pre = self.pre
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
        return f"{pre}<sheetData>{body}</sheetData>{self.post}"


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

def build_form(
    form: str, spec_sections: dict, root: Path
) -> tuple[list[tuple[Path, bytes]], list[dict], list[dict]]:
    """한 양식을 산출한다. (쓸 파일, 거부 사유들, 경고들) 을 낸다. 못 읽으면 ExportError."""
    fmap, map_path = load_map(root, form)
    problems: list[dict] = []
    warnings: list[dict] = []

    def problem(sheet: str, item: str, reason: str) -> None:
        problems.append({"form": form, "sheet": sheet, "item": item, "reason": reason})

    def warn(sheet: str, item: str, reason: str) -> None:
        warnings.append({"form": form, "sheet": sheet, "item": item, "reason": reason})

    map_sheets = {norm(s["이름"]): s for s in fmap["시트"]}
    for sheet in spec_sections:
        if sheet not in map_sheets:
            raise ExportError(f"작업본의 시트 {sheet!r} 이 양식 지도에 없다", form=form, sheet=sheet)

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

    for sname, smap in map_sheets.items():
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
            _write_table(form, sname, tname, t, tables, subs, ed, md_values, problem, sheet_tops, put)

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
    out_name = _file_name(form, fmap, map_sheets, spec_sections, md_values, problem)
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
                problem("", "파일명", f"{out_path.relative_to(root.resolve()).as_posix()} 가 이미 있다. 이전 판은 덮어쓰지 않는다 — 버전을 올려 새 판으로 산출한다")
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
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zo:
        for info in infos:
            data = raw[info.filename]
            if info.filename in changed:
                bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
                data = bom + changed[info.filename].render().encode("utf-8")
            elif info.filename == "xl/workbook.xml" and has_formula:
                data = _with_full_calc(data.decode("utf-8")).encode("utf-8")
            zo.writestr(copy.copy(info), data)
    return [(out_path, buf.getvalue())], [], warnings


def _write_table(form, sname, tname, t, tables, subs, ed, md_values, problem, sheet_tops, put) -> None:
    cols = {norm(k): str(v) for k, v in (t.get("열") or {}).items()}
    start = int(t["시작_행"])
    max_rows = int(t["최대_행"]) if t.get("최대_행") is not None else None
    partner = norm(t["짝"]) if t.get("짝") else None
    if partner and partner not in tables:
        raise ExportError(f"표 {tname!r} 의 짝 {partner!r} 이 지도에 없다", form=form, sheet=sname, item=tname)

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
    split_rows = t.get("여러_줄") == "행"
    for r in md_rows:
        if split_rows:
            lines = {c: _BR.split(v) if v else [""] for c, v in r.items()}
            h = max(len(v) for v in lines.values()) if lines else 1
            for i in range(h):
                out_rows.append({c: (v[i].strip() if i < len(v) else "") for c, v in lines.items()})
        else:
            out_rows.append({c: _BR.sub("\n", v) for c, v in r.items()})
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
            elif not new_row:
                ed.clear(ref)
            elif clone:
                ed.blank(ref, ed.style_of(f"{c}{clone}"), clone)
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


def _file_name(form, fmap, map_sheets, spec_sections, md_values, problem) -> str | None:
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
            raise ExportError(f"`자리.{name}` 에 `칸` 이나 `표` 가 없다", form=form, item=name)
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

def _commit(writes: list[tuple[Path, bytes]], root: Path) -> list[str]:
    """산출물을 원자적으로 쓴다.

    모두 같은 폴더의 임시 파일로 먼저 쓰고, 전부 성공하면 최종 이름으로 rename 한다. 최종 이름이
    그 사이 생겼거나 하나라도 실패하면 이번 실행이 만든 임시·최종 파일(과 새로 만든 폴더)을 모두
    지우고 ExportError 를 낸다.
    """
    temps: list[Path] = []
    finals: list[Path] = []
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
                raise ExportError(f"{path} 가 이미 있다. 이전 판은 덮어쓰지 않는다")
            os.rename(tmp, path)
            finals.append(path)
    except BaseException as e:
        for f in temps + finals:
            try:
                f.unlink()
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
    return [p.relative_to(root).as_posix() for p, _ in writes]


def run(spec: Path, root: Path, only_form: str | None) -> tuple[int, dict]:
    try:
        text = spec.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ExportError(f"작업본 {spec} 를 읽지 못했다: {e}") from None
    forms = parse_spec(text)
    for name in forms:
        _check_form_name(name)
    if only_form is not None:
        _check_form_name(only_form)
        if only_form not in forms:
            raise ExportError(f"작업본에 양식 {only_form!r} 소절이 없다", form=only_form)
        forms = {only_form: forms[only_form]}

    writes: list[tuple[Path, bytes]] = []
    problems: list[dict] = []
    warnings: list[dict] = []
    for form, sections in forms.items():
        w, p, wa = build_form(form, sections, root)
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
    written = _commit(writes, root)
    return EXIT_OK, {
        "status": "ok",
        "files": written,
        "problems": [],
        "warnings": warnings,
        "next": "다음: 엑셀로 한 번 열어 서식을 확인한다. 올리면 PR 에서 doc-guard(Actions)가 파일 이름과 구조를 검사한다.",
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
        description="작업본(md)의 `## 양식 항목` 을 양식 xlsx 로 산출한다.",
    )
    parser.add_argument("--spec", type=Path, required=True, help="작업본 md(docs/spec/DEV-xxx-….md)")
    parser.add_argument("--root", type=Path, required=True, help="Project Repository 루트")
    parser.add_argument("--form", help="이 양식만 산출한다(생략하면 작업본의 모든 양식)")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise ExportError(f"--root {args.root} 가 폴더가 아니다")
        code, report = run(args.spec, root, args.form)
    except ExportError as e:
        code, report = EXIT_ERROR, _error_report(e.reason, e.form, e.sheet, e.item)
    except Exception as e:  # 예상하지 못한 오류도 검사 불능(2)이지 거부(1)가 아니다
        code, report = EXIT_ERROR, _error_report(f"예상하지 못한 오류({type(e).__name__}): {e}")
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
