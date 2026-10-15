"""고객사 견본 xlsx 에서 빈 양식(템플릿)을 만든다(#335, PR A).

고객사가 준 견본 파일에는 지도 밖 샘플(셀 값, 그림·도형, 다른 파일을 가리키는 외부 참조)이 섞여 있다. 그대로
템플릿으로 쓰면 산출물에 샘플이 새고 고객사 정보(다른 고객사 이름, 사내 서버 경로)가 딸려 간다. 이 모듈은 양식
지도(`templates/forms/<양식>.yaml`, 형식 정본은 `plugins/harness/skills/spec/form-map.md`)가 시킨 것만 지운
빈 xlsx 를 새 파일로 쓴다.

    python -m checker.blank_template --root R --form <양식> --src <견본 xlsx> --out <빈 xlsx> [--check]

지도 시트 항목의 키
    비우기: [범위…]       값만 지운다(서식·병합 유지). 수식 셀은 지우지 않고 알린다.
    그림_지우기: true     그 시트의 drawing(그림·도형)과 그것만 쓰던 media 를 지운다.
    유지: [범위…]         PR B(남은 견본 검사)가 쓴다. 이번엔 키만 인정한다.
지도 최상위 키
    외부_참조_지우기: true  externalLinks 파트와 그것을 가리키던 workbook 항목·이름 정의를 지운다.

쓰기는 openpyxl 을 쓰지 않는다(x14 드롭다운·도형 소실). zip 수준에서 바뀐 파트만 다시 쓰고 나머지는 바이트 그대로 복사한다.

종료코드
    0  만들었고 남은 견본이 없다.
    1  거부. `--out` 이 이미 있다, 경로·범위 오류. 아무 파일도 쓰지 않는다.
    2  읽지 못함·지원 안 함·지도 오류. 검사 불능이지 통과도 위반도 아니다.
    3  만들었으나 결과 패키지(sharedStrings·drawings·이름 정의·externalLinks)에 지운 견본 글자가 다시 보인다.
`--check` 는 파일을 쓰지 않고 같은 처리·검사만 한다(`dry_run: true`).
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from checker import export
from checker.export import ExportError, SheetXml, col2n, n2col, norm

EXIT_OK, EXIT_REJECTED, EXIT_ERROR, EXIT_LEFTOVER = 0, 1, 2, 3

MAX_COL, MAX_ROW = 16384, 1048576
_RANGE = re.compile(r"^([A-Z]{1,3})(\d{1,7})(?::([A-Z]{1,3})(\d{1,7}))?$")
_ATTR = re.compile(r'([\w:]+)="([^"]*)"')
_BOM = b"\xef\xbb\xbf"
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def _unesc(text: str) -> str:
    """XML 글자 참조(`&#53076;` 등)와 기본 다섯 개체를 푼다(openpyxl 등은 한글을 글자 참조로 쓴다)."""
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9A-Fa-f]+);", lambda m: chr(int(m.group(1), 16)), text)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text


class RangeError(ExportError):
    """지도의 범위 문자열이 틀렸다(blank_template CLI 에서는 거부 = 종료코드 1)."""


def parse_range(loc) -> tuple[int, int, int, int]:
    """`B2` 또는 `B2:D9` → (첫 열, 첫 행, 끝 열, 끝 행)."""
    m = _RANGE.match(str(loc).strip())
    if not m:
        raise RangeError(f"범위 {loc!r} 의 모양이 틀렸다(예: A1 또는 B2:D9)")
    c1, r1 = col2n(m.group(1)), int(m.group(2))
    c2, r2 = (col2n(m.group(3)), int(m.group(4))) if m.group(3) else (c1, r1)
    if not (1 <= c1 <= c2 <= MAX_COL and 1 <= r1 <= r2 <= MAX_ROW):
        raise RangeError(f"범위 {loc!r} 가 시트 범위를 벗어났거나 시작이 끝보다 뒤다")
    return c1, r1, c2, r2


def _hit(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


# ---------------------------------------------------------------- 지도 검증(export·form_columns 가 같이 쓴다)

def map_problems(fmap: dict) -> list[tuple[str, str]]:
    """새 키(`비우기`·`그림_지우기`·`유지`·`외부_참조_지우기`)와 서술 `열` 의 오류 → [(종류, 사유)]. 종류: range / map."""
    out: list[tuple[str, str]] = []
    top = fmap.get("외부_참조_지우기")
    if top is not None and not isinstance(top, bool):
        out.append(("map", "`외부_참조_지우기` 는 true/false 여야 한다"))
    for s in fmap.get("시트") or []:
        if not isinstance(s, dict):
            continue
        sn = s.get("이름")
        keyed: dict[str, list[tuple[str, tuple[int, int, int, int]]]] = {}
        for key in ("비우기", "유지"):
            v = s.get(key)
            keyed[key] = []
            if v is None:
                continue
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                out.append(("map", f"시트 {sn!r} 의 `{key}`(범위 문자열 목록이어야 한다)"))
                continue
            for x in v:
                try:
                    keyed[key].append((x, parse_range(x)))
                except RangeError as e:
                    out.append(("range", f"시트 {sn!r} 의 `{key}`: {e.reason}"))
        g = s.get("그림_지우기")
        if g is not None and not isinstance(g, bool):
            out.append(("map", f"시트 {sn!r} 의 `그림_지우기` 는 true/false 여야 한다"))
        # 지도가 이미 맡은 영역
        owned: list[tuple[str, tuple[int, int, int, int]]] = list(keyed["유지"])
        owned = [(f"유지 {x}", r) for x, r in owned]
        for kind, key in (("칸", "위치"), ("서술", "위치")):
            for it in s.get(kind) or []:
                if isinstance(it, dict) and it.get(key):
                    try:
                        owned.append((f"{kind} {it.get('항목', it.get('이름'))!r} {it[key]}", parse_range(it[key])))
                    except RangeError:
                        pass  # 그 키의 오류는 다른 곳이 알린다
        for t in s.get("표") or []:
            if not isinstance(t, dict) or not isinstance(t.get("열"), dict):
                continue
            start = t.get("시작_행")
            if not isinstance(start, int):
                continue
            end = start + t["최대_행"] - 1 if isinstance(t.get("최대_행"), int) else MAX_ROW
            for col in t["열"].values():
                if isinstance(col, str) and re.fullmatch(r"[A-Z]{1,3}", col):
                    n = col2n(col)
                    owned.append((f"표 {t.get('이름')!r} 의 {col} 열", (n, start, n, end)))
        for x, rect in keyed["비우기"]:
            for label, orect in owned:
                if _hit(rect, orect):
                    out.append(("map", f"시트 {sn!r} 의 `비우기` {x} 가 {label} 와 겹친다 — 지도가 맡은 칸·표·서술·유지 범위는 비우기에 넣을 수 없다"))
        for n in s.get("서술") or []:
            if not isinstance(n, dict) or n.get("열") is None:
                continue
            cols = n["열"]
            if (
                not isinstance(cols, dict) or set(cols) != {"제목", "설명"}
                or not all(isinstance(v, str) and re.fullmatch(r"[A-Z]{1,3}", v) for v in cols.values())
                or cols["제목"] == cols["설명"]
            ):
                out.append(("map", f"시트 {sn!r} 서술 {n.get('이름')!r} 의 `열` 은 {{제목: 열 문자, 설명: 열 문자}} 두 개여야 한다"))
                continue
            try:
                c1, _, c2, _ = parse_range(n["위치"])
            except (RangeError, KeyError):
                continue
            if not all(c1 <= col2n(v) <= c2 for v in cols.values()):
                out.append(("map", f"시트 {sn!r} 서술 {n.get('이름')!r} 의 `열` 이 위치 {n['위치']} 의 열 범위 밖이다"))
    return out


def check_map(fmap: dict, label: str, form: str = "") -> None:
    """지도 오류가 있으면 올린다. 범위 문자열 오류가 있으면 RangeError, 그 밖은 ExportError."""
    probs = map_problems(fmap)
    if not probs:
        return
    msg = f"양식 지도 {label} 가 틀렸다: " + "; ".join(m for _, m in probs)
    raise (RangeError if any(k == "range" for k, _ in probs) else ExportError)(msg, form=form)


# ---------------------------------------------------------------- 값 비우기

@dataclass
class Cleared:
    """비운 칸 기록. 공유 문자열 정리와 남은 견본 검사가 쓴다."""
    sst_ids: set[int] = field(default_factory=set)
    sst_refs: int = 0  # 공유 문자열을 가리키던 칸 수
    texts: set[str] = field(default_factory=set)  # 인라인 문자열 본문
    formulas: list[str] = field(default_factory=list)  # 수식이라 남긴 칸
    cells: int = 0


def clear_ranges(ed: SheetXml, ranges: list[str], info: Cleared) -> None:
    """범위의 값을 비운다(서식·병합 유지). 수식 셀은 남기고 `info.formulas` 에 적는다."""
    saved = (ed._max_row, ed._max_col)  # 비우기가 자동 필터·dimension 을 늘리지 않게
    for rng in ranges:
        c1, r1, c2, r2 = parse_range(rng)
        for n in ed.rows_with_content(r1, r2):
            for c in ed.rows[n].cells:
                if not (c1 <= c.col <= c2) or not c.has_content():
                    continue
                if export.is_formula(c.inner):
                    info.formulas.append(c.ref)
                    continue
                t = dict(c.attrs).get("t")
                if t == "s":
                    m = re.search(r"<v>\s*(\d+)\s*</v>", c.inner)
                    if m:
                        info.sst_ids.add(int(m.group(1)))
                        info.sst_refs += 1
                elif t == "inlineStr":
                    info.texts.add(_si_text(c.inner))
                info.cells += 1
        ed.clear_range(f"{n2col(c1)}{r1}", f"{n2col(c2)}{r2}")
    ed._max_row, ed._max_col = saved


# ---------------------------------------------------------------- 공유 문자열

_SI_RE = re.compile(r"<si\b[^>]*?(?:/>|>.*?</si>)", re.S)
_T_RE = re.compile(r"<t\b[^>]*?(?:/>|>(.*?)</t>)", re.S)


def _si_text(si: str) -> str:
    si = re.sub(r"<rPh\b.*?</rPh>", "", si, flags=re.S)  # 읽는 법(후리가나)은 본문이 아니다
    return "".join(_unesc(m.group(1) or "") for m in _T_RE.finditer(si))


def _sheet_parts(parts: dict[str, bytes]) -> list[str]:
    return [n for n in parts if n.startswith("xl/worksheets/") and n.endswith(".xml")]


def _live_sst_ids(parts: dict[str, bytes]) -> set[int]:
    out: set[int] = set()
    for n in _sheet_parts(parts):
        for cm in export._CELL_RE.finditer(parts[n].decode("utf-8-sig")):
            attrs = dict(_ATTR.findall(cm.group(1)))
            if attrs.get("t") == "s":
                m = re.search(r"<v>\s*(\d+)\s*</v>", cm.group(2) or "")
                if m:
                    out.add(int(m.group(1)))
    return out


def _sst_path(parts: dict[str, bytes]) -> str | None:
    rels = parts.get("xl/_rels/workbook.xml.rels")
    if rels is None:
        return None
    for _, a in _parse_rels(rels):
        if a.get("Type", "").endswith("/sharedStrings") and a.get("TargetMode") != "External":
            return _resolve("xl/workbook.xml", a["Target"])
    return None


def blank_strings(parts: dict[str, bytes], info: Cleared) -> tuple[str | None, int, set[str]]:
    """지운 칸이 가리키던 `<si>` 중 아무 칸도 더는 가리키지 않는 것만 본문을 비운다(번호·개수 유지).

    parts 의 sharedStrings 를 고쳐 쓴다. (경로, 비운 개수, 비운 본문들) 을 돌려준다.
    """
    path = _sst_path(parts)
    if not info.sst_ids or path is None or path not in parts:
        return path, 0, set()
    data = parts[path]
    bom = data.startswith(_BOM)
    xml = (data[3:] if bom else data).decode("utf-8")
    dead = info.sst_ids - _live_sst_ids(parts)
    blanked: set[str] = set()
    idx = -1
    n_blank = 0

    def fn(m: re.Match) -> str:
        nonlocal idx, n_blank
        idx += 1
        if idx in dead:
            blanked.add(_si_text(m.group(0)))
            n_blank += 1
            return "<si><t/></si>"
        return m.group(0)

    new = _SI_RE.sub(fn, xml)
    if n_blank:
        def count(m: re.Match) -> str:
            return f'{m.group(1)}{max(0, int(m.group(2)) - info.sst_refs)}"'
        new = re.sub(r'(<sst\b[^>]*?\bcount=")(\d+)"', count, new, count=1)
        parts[path] = (_BOM if bom else b"") + new.encode("utf-8")
    return path, n_blank, blanked


def sst_texts(parts: dict[str, bytes], ids: set[int]) -> set[str]:
    """공유 문자열 번호들의 본문(비우기 전에 부른다)."""
    path = _sst_path(parts)
    if not ids or path is None or path not in parts:
        return set()
    xml = parts[path].decode("utf-8-sig")
    return {_si_text(m.group(0)) for i, m in enumerate(_SI_RE.finditer(xml)) if i in ids}


# ---------------------------------------------------------------- 관계(rels)

def _rels_name(part: str) -> str:
    d, _, b = part.rpartition("/")
    return f"{d}/_rels/{b}.rels" if d else f"_rels/{b}.rels"


def _rels_source(rels: str) -> str:
    d, _, b = rels.rpartition("/")
    base = d[: -len("_rels")].rstrip("/") if d.endswith("_rels") else d
    return posixpath.join(base, b[: -len(".rels")])


def _resolve(src: str, target: str) -> str:
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(posixpath.dirname(src), target))


def _parse_rels(data: bytes) -> list[tuple[str, dict[str, str]]]:
    text = data.decode("utf-8-sig", "replace")
    return [(m.group(0), dict(_ATTR.findall(m.group(0)))) for m in re.finditer(r"<Relationship\b[^>]*>", text)]


def _referenced(parts: dict[str, bytes]) -> set[str]:
    """패키지 안 모든 rels 가 가리키는 파트 경로."""
    out: set[str] = set()
    for name, data in parts.items():
        if not name.endswith(".rels"):
            continue
        src = _rels_source(name)
        for _, a in _parse_rels(data):
            if a.get("TargetMode") != "External" and a.get("Target"):
                out.add(_resolve(src, a["Target"]))
    return out


def _text(parts: dict[str, bytes], p: str) -> tuple[str, bool]:
    d = parts[p]
    bom = d.startswith(_BOM)
    return (d[3:] if bom else d).decode("utf-8"), bom


def _set(parts: dict[str, bytes], p: str, text: str, bom: bool) -> None:
    parts[p] = (_BOM if bom else b"") + text.encode("utf-8")


# ---------------------------------------------------------------- 그림 지우기

_PIC_ELEM = re.compile(r"<(?:\w+:)?(?:drawing|picture)\b([^>]*?)(?:/>|>\s*</(?:\w+:)?(?:drawing|picture)>)")
_NO_SUPPORT = re.compile(r"<(?:\w+:)?(legacyDrawingHF|legacyDrawing|oleObjects|controls)\b")
_DRAWING_TEXT = re.compile(r"<(?:\w+:)?t\b[^>]*>(.*?)</(?:\w+:)?t>", re.S)


@dataclass
class Pictures:
    removed: list[str] = field(default_factory=list)  # 지운 파트
    kept_shared: list[str] = field(default_factory=list)  # 다른 시트가 써서 남긴 drawing
    texts: set[str] = field(default_factory=set)  # 지운 drawing 안의 글자


def remove_pictures(parts: dict[str, bytes], sheets: dict[str, str]) -> Pictures:
    """{시트 이름: 시트 경로} 시트의 drawing 을 떼고 쓰는 곳이 없어진 파트를 지운다."""
    res = Pictures()
    drawing_cands: list[str] = []
    media_cands: list[str] = []
    for sname, sp in sheets.items():
        xml, bom = _text(parts, sp)
        bad = _NO_SUPPORT.search(xml)
        if bad:
            raise ExportError(
                f"시트 {sname!r} 에 {bad.group(1)} 가 있어 그림 지우기를 지원하지 않는다(메모·OLE·컨트롤은 처리하지 않는다)",
                sheet=sname,
            )
        rp = _rels_name(sp)
        entries = _parse_rels(parts[rp]) if rp in parts else []
        by_id = {a.get("Id"): (raw, a) for raw, a in entries}
        drop: dict[str, tuple[str, dict[str, str]]] = {}
        for m in _PIC_ELEM.finditer(xml):
            idm = re.search(r'\b\w+:id="([^"]+)"', m.group(1))
            if not idm:
                continue
            if idm.group(1) not in by_id:
                raise ExportError(f"시트 {sname!r} 의 그림 {idm.group(1)} 가 시트 관계에 없다", sheet=sname)
            drop[idm.group(1)] = by_id[idm.group(1)]
        for raw, a in entries:
            if a.get("Type", "").endswith("/drawing"):
                drop[a["Id"]] = (raw, a)
        for rid, (raw, a) in drop.items():
            typ = a.get("Type", "")
            if not (typ.endswith("/drawing") or typ.endswith("/image")):
                raise ExportError(f"시트 {sname!r} 의 그림 관계 {rid} 의 종류({typ.rsplit('/', 1)[-1]})를 지원하지 않는다", sheet=sname)
            if a.get("TargetMode") == "External":
                continue
            tgt = _resolve(sp, a["Target"])
            (drawing_cands if typ.endswith("/drawing") else media_cands).append(tgt)
        # 지원하지 않는 drawing 내용(차트·도식·삽입 개체)이면 아무것도 바꾸기 전에 멈춘다.
        for d in drawing_cands:
            for _, a in _parse_rels(parts[_rels_name(d)]) if _rels_name(d) in parts else []:
                if a.get("TargetMode") != "External" and not a.get("Type", "").endswith("/image"):
                    raise ExportError(
                        f"{d} 가 그림 아닌 대상({a.get('Type', '').rsplit('/', 1)[-1]}: {a.get('Target')})을 가리켜 그림 지우기를 지원하지 않는다",
                        sheet=sname,
                    )
        if _PIC_ELEM.search(xml):
            _set(parts, sp, _PIC_ELEM.sub("", xml), bom)
        if rp in parts:
            rtext, rbom = _text(parts, rp)
            for raw, _ in drop.values():
                rtext = rtext.replace(raw, "", 1)
            if re.search(r"<Relationship\b", rtext):
                _set(parts, rp, rtext, rbom)
            else:
                del parts[rp]
                res.removed.append(rp)
    refs = _referenced(parts)
    for d in dict.fromkeys(drawing_cands):
        if d not in parts:
            continue
        if d in refs:
            res.kept_shared.append(d)
            continue
        res.texts.update(_unesc(t) for t in _DRAWING_TEXT.findall(parts[d].decode("utf-8-sig", "replace")))
        dr = _rels_name(d)
        if dr in parts:
            for _, a in _parse_rels(parts[dr]):
                if a.get("TargetMode") != "External" and a.get("Target"):
                    media_cands.append(_resolve(d, a["Target"]))
            del parts[dr]
            res.removed.append(dr)
        del parts[d]
        res.removed.append(d)
    refs = _referenced(parts)
    for m in dict.fromkeys(media_cands):
        if m in parts and m not in refs:
            del parts[m]
            res.removed.append(m)
    return res


# ---------------------------------------------------------------- 외부 참조 지우기

_NAME_RE = re.compile(r"<definedName\b([^>]*)>(.*?)</definedName>", re.S)
_FORMULA_EL = re.compile(
    r"<(?:\w+:)?(?:f|formula|formula1|formula2|calculatedColumnFormula)\b[^>]*>(.*?)</(?:\w+:)?(?:f|formula|formula1|formula2|calculatedColumnFormula)>",
    re.S,
)


@dataclass
class ExternalRemoval:
    links: int = 0
    targets: int = 0
    names_removed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    broken_names: list[str] = field(default_factory=list)  # #REF! 를 가리켜 그대로 둔 이름


def _external_links(parts: dict[str, bytes]) -> list[str]:
    rels = parts.get("xl/_rels/workbook.xml.rels")
    if rels is None:
        return []
    return [
        _resolve("xl/workbook.xml", a["Target"])
        for _, a in _parse_rels(rels)
        if a.get("Type", "").endswith("/externalLink") and a.get("TargetMode") != "External"
    ]


def _count_targets(parts: dict[str, bytes], links: list[str]) -> int:
    n = 0
    for p in links:
        rp = _rels_name(p)
        if rp in parts:
            n += sum(1 for _, a in _parse_rels(parts[rp]) if a.get("Target"))
    return n


def _uses(text: str, names: list[str], nlinks: int) -> str | None:
    """수식 글에 외부 참조 `[N]` 나 외부 이름이 있으면 무엇인지 돌려준다."""
    text = _unesc(re.sub(r"<[^>]+>", " ", text))
    for m in re.finditer(r"\[(\d+)\]", text):
        if 1 <= int(m.group(1)) <= nlinks:
            return f"외부 참조 {m.group(0)}"
    for nm in names:
        if re.search(r"(?<![\w.])" + re.escape(nm) + r"(?![\w.])", text):
            return f"이름 {nm!r}"
    return None


def remove_external_links(parts: dict[str, bytes], sheet_names: dict[str, str]) -> ExternalRemoval:
    """externalLinks 를 지운다. 쓰는 곳(드롭다운·수식·조건부 서식·다른 이름)이 있으면 지우지 않고 ExportError."""
    res = ExternalRemoval()
    links = _external_links(parts)
    if not links:
        return res
    res.links, res.targets = len(links), _count_targets(parts, links)
    wb, wbom = _text(parts, "xl/workbook.xml")
    ext_names: list[str] = []
    ext_all: list[tuple[str, str]] = []
    for m in _NAME_RE.finditer(wb):
        nm = re.search(r'\bname="([^"]*)"', m.group(1))
        body = _unesc(m.group(2))
        if nm is None:
            continue
        name = _unesc(nm.group(1))
        if any(1 <= int(x) <= len(links) for x in re.findall(r"\[(\d+)\]", body)):
            ext_names.append(name)
            ext_all.append((name, body))
        elif "#REF!" in body:
            res.broken_names.append(f"{name} = {body}")
    uses: list[str] = []
    for m in _NAME_RE.finditer(wb):  # 다른 이름이 외부 이름을 가리키는 경우
        nm = re.search(r'\bname="([^"]*)"', m.group(1))
        name = _unesc(nm.group(1)) if nm else ""
        if name in ext_names:
            continue
        hit = _uses(m.group(2), ext_names, len(links))
        if hit:
            uses.append(f"이름 {name!r} 의 정의가 {hit} 를 쓴다")
    for sname, sp in sheet_names.items():
        xml = parts[sp].decode("utf-8-sig")
        seen: list[str] = []
        for m in re.finditer(r"<dataValidation\b([^>]*)>(.*?)</dataValidation>", xml, re.S):
            sq = re.search(r'\bsqref="([^"]*)"', m.group(1))
            hit = _uses(m.group(2), ext_names, len(links))
            if hit:
                uses.append(f"시트 {sname!r} 의 드롭다운(데이터 유효성) {sq.group(1) if sq else '?'} 가 {hit} 를 쓴다")
        for m in re.finditer(r"<(\w+:)dataValidation\b[^>]*>(.*?)</\1dataValidation>", xml, re.S):
            sq = re.search(r"<\w+:sqref>(.*?)</\w+:sqref>", m.group(2), re.S)
            hit = _uses(m.group(2), ext_names, len(links))
            if hit:
                uses.append(f"시트 {sname!r} 의 확장(x14) 드롭다운 {sq.group(1) if sq else '?'} 가 {hit} 를 쓴다")
        for m in re.finditer(r"<(?:\w+:)?conditionalFormatting\b[^>]*>(.*?)</(?:\w+:)?conditionalFormatting>", xml, re.S):
            sq = re.search(r'\bsqref="([^"]*)"|<\w+:sqref>(.*?)</\w+:sqref>', m.group(0), re.S)
            hit = _uses("".join(_FORMULA_EL.findall(m.group(1))) or m.group(1), ext_names, len(links))
            if hit:
                uses.append(f"시트 {sname!r} 의 조건부 서식 {(sq.group(1) or sq.group(2)) if sq else '?'} 가 {hit} 를 쓴다")
        for cm in export._CELL_RE.finditer(xml):
            ref = dict(_ATTR.findall(cm.group(1))).get("r", "?")
            hit = _uses(" ".join(re.findall(r"<f\b[^>]*>(.*?)</f>", cm.group(2) or "", re.S)), ext_names, len(links))
            if hit:
                uses.append(f"시트 {sname!r} 의 셀 {ref} 수식이 {hit} 를 쓴다")
    for name, data in parts.items():
        if re.match(r"xl/(charts|tables|pivotCache)/[^/]+\.xml$", name):
            hit = _uses(" ".join(_FORMULA_EL.findall(data.decode("utf-8-sig", "replace"))), ext_names, len(links))
            if hit:
                uses.append(f"{name} 의 수식이 {hit} 를 쓴다")
    if uses:
        raise ExportError(
            "외부 참조를 지울 수 없다 — 아래가 쓰고 있다(지우면 드롭다운·수식이 깨진다). 값을 템플릿 안으로 옮길지 사람이 정한다: "
            + "; ".join(uses[:20]) + (f" … 외 {len(uses) - 20}건" if len(uses) > 20 else "")
        )
    # 쓰는 곳이 없다 — 이름 정의, externalReferences, 관계, 파트를 지운다.
    def drop_name(m: re.Match) -> str:
        nm = re.search(r'\bname="([^"]*)"', m.group(1))
        if nm and _unesc(nm.group(1)) in ext_names:
            res.names_removed.append(_unesc(nm.group(1)))
            return ""
        return m.group(0)

    wb = _NAME_RE.sub(drop_name, wb)
    wb = re.sub(r"<definedNames>\s*</definedNames>|<definedNames\s*/>", "", wb)
    wb = re.sub(r"<externalReferences>.*?</externalReferences>|<externalReferences\s*/>", "", wb, flags=re.S)
    _set(parts, "xl/workbook.xml", wb, wbom)
    rtext, rbom = _text(parts, "xl/_rels/workbook.xml.rels")
    for raw, a in _parse_rels(parts["xl/_rels/workbook.xml.rels"]):
        if a.get("Type", "").endswith("/externalLink"):
            rtext = rtext.replace(raw, "", 1)
    _set(parts, "xl/_rels/workbook.xml.rels", rtext, rbom)
    for p in links:
        for q in (p, _rels_name(p)):
            if q in parts:
                del parts[q]
                res.removed.append(q)
    return res


# ---------------------------------------------------------------- 남은 견본 검사

def _items(parts: dict[str, bytes], live: set[int]) -> list[tuple[str, str, int]]:
    """결과 패키지에서 견본 글자가 새어 나올 수 있는 곳 → [(파트, 본문, 최소 길이)]."""
    out: list[tuple[str, str, int]] = []
    sp = _sst_path(parts)
    if sp and sp in parts:
        for i, m in enumerate(_SI_RE.finditer(parts[sp].decode("utf-8-sig"))):
            if i not in live:  # 칸이 가리키는 문자열은 눈에 보이는 값이다 — 비우기 대상이 아니다
                out.append((sp, _si_text(m.group(0)), 1))
    for n, d in parts.items():
        if re.match(r"xl/drawings/[^/]+\.xml$", n):
            out += [(n, _unesc(t), 1) for t in _DRAWING_TEXT.findall(d.decode("utf-8-sig", "replace"))]
        elif re.match(r"xl/externalLinks/[^/]+\.xml$", n):
            x = d.decode("utf-8-sig", "replace")
            out += [(n, _unesc(t), 2) for t in re.findall(r"<(?:\w+:)?(?:v|t)>(.*?)</(?:\w+:)?(?:v|t)>", x, re.S)]
            out += [(n, _unesc(t), 2) for t in re.findall(r'(?:sheetName|val)="([^"]*)"', x)]
    if "xl/workbook.xml" in parts:
        wb = parts["xl/workbook.xml"].decode("utf-8-sig")
        out += [("xl/workbook.xml", _unesc(m.group(2)), 2) for m in _NAME_RE.finditer(wb)]
    return out


def find_leftovers(parts: dict[str, bytes], samples: set[str]) -> list[dict]:
    samples = {s for s in (norm(x) for x in samples) if s and re.search(r"\w", s)}  # 구두점만 있는 글자는 견본으로 보지 않는다
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for part, text, min_len in _items(parts, _live_sst_ids(parts)):
        t = norm(text)
        if not t:
            continue
        for s in samples:
            if len(s) < min_len:
                continue
            if s == t or (len(s) >= 4 and s in t):
                if (part, s) not in seen:
                    seen.add((part, s))
                    found.append({"part": part, "text": s if len(s) <= 60 else s[:57] + "…"})
    return found


# ---------------------------------------------------------------- 출처 정보와 사람이 볼 곳

_CORE_FIELDS = ("dc:title", "dc:creator", "cp:lastModifiedBy")
_APP_FIELDS = ("Company", "Manager")


def scrub_doc_props(parts: dict[str, bytes]) -> list[str]:
    """docProps 의 제목·작성자·마지막 수정자(core)와 Company·Manager(app)를 비운다. 값이 있어 비운 필드 이름을 돌려준다.

    견본 파일의 출처 정보(다른 고객사 이름, 작성자)라 빈 양식에 남을 이유가 없다. 지도 키 없이 항상 한다.
    """
    cleared: list[str] = []
    for part, fields in (("docProps/core.xml", _CORE_FIELDS), ("docProps/app.xml", _APP_FIELDS)):
        if part not in parts:
            continue
        xml, bom = _text(parts, part)
        for f in fields:
            m = re.search(r"(<" + re.escape(f) + r"\b[^>]*>)(.*?)(</" + re.escape(f) + r">)", xml, re.S)
            if m and m.group(2).strip():
                xml = xml[: m.start()] + m.group(1) + m.group(3) + xml[m.end():]
                cleared.append(f)
        _set(parts, part, xml, bom)
    return cleared


def review_notices(parts: dict[str, bytes], sheets: dict[str, str]) -> list[dict]:
    """견본 여부를 엔진이 판정하지 않는 곳(PR B 범위)에 내용이 있으면 위치와 함께 알린다. 조용히 통과시키지 않는다."""
    out: list[dict] = []

    def add(kind: str, where: str, what: str) -> None:
        out.append({"type": "review-needed", "kind": kind, "where": where, "reason": f"{what} 있음 — 확인 필요"})

    for sname, sp in sheets.items():
        if sp not in parts:
            continue
        xml = parts[sp].decode("utf-8-sig", "replace")
        for m in re.finditer(r"<(?:\w+:)?headerFooter\b[^>]*>(.*?)</(?:\w+:)?headerFooter>", xml, re.S):
            if re.search(r"<(?:\w+:)?(?:odd|even|first)(?:Header|Footer)\b[^>]*>\s*\S", m.group(1)):
                add("header-footer", f"시트 {sname!r}", "머리글·바닥글 글자가")
        if re.search(r"<(?:\w+:)?legacyDrawingHF\b", xml):
            add("header-footer-picture", f"시트 {sname!r}", "머리글·바닥글 그림(legacyDrawingHF)이")
        for m in re.finditer(r"<dataValidation\b([^>]*)>(.*?)</dataValidation>", xml, re.S):
            if re.search(r"<formula[12]>\s*(?:&quot;|\")", m.group(2)):
                sq = re.search(r'\bsqref="([^"]*)"', m.group(1))
                add("validation-literal", f"시트 {sname!r} {sq.group(1) if sq else '?'}", "드롭다운 목록 직접 입력 값이")
    for name in sorted(parts):
        if re.match(r"xl/(comments\d*\.xml|threadedComments/[^/]+\.xml)$", name):
            add("comments", name, "메모(주석)가")
    if sheets:
        add("sheet-names", "시트 이름: " + ", ".join(map(repr, sheets)), "시트 이름이")
    for part, fields in (("docProps/core.xml", ("dc:subject", "dc:description", "cp:keywords", "cp:category")),):
        if part in parts:
            xml = parts[part].decode("utf-8-sig", "replace")
            for f in fields:
                m = re.search(r"<" + re.escape(f) + r"\b[^>]*>(.*?)</" + re.escape(f) + ">", xml, re.S)
                if m and m.group(1).strip():
                    add("doc-props", f"{part} {f}", "문서 속성이")
    return out


# ---------------------------------------------------------------- 본체

@dataclass
class Built:
    data: bytes
    report: dict
    leftovers: list[dict]


def _content_types_drop(parts: dict[str, bytes], gone: list[str]) -> None:
    if "[Content_Types].xml" not in parts or not gone:
        return
    xml, bom = _text(parts, "[Content_Types].xml")
    new = xml
    for g in gone:
        new = re.sub(r'<Override\b[^>]*\bPartName="/' + re.escape(g) + r'"[^>]*/>', "", new)
    if new != xml:
        _set(parts, "[Content_Types].xml", new, bom)


def build_blank(root: Path, form: str, src: Path) -> Built:
    fmap, map_path = export.load_map(root, form)  # 지도 오류(겹침·모양)는 여기서 올라온다
    try:
        with zipfile.ZipFile(src) as zf:
            infos = zf.infolist()
            parts = {i.filename: zf.read(i.filename) for i in infos}
            paths = export._sheet_paths(zf)
        parts["xl/workbook.xml"].decode("utf-8")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
        raise ExportError(f"견본 {src} 를 읽지 못했다: {e}", form=form) from None
    original = set(parts)
    wipe_ext = fmap.get("외부_참조_지우기") is True
    cleared = Cleared()
    per_sheet: dict[str, int] = {}
    pic_sheets: dict[str, str] = {}
    for s in fmap["시트"]:
        sname = norm(s["이름"])
        want_clear, want_pic = s.get("비우기") or [], s.get("그림_지우기") is True
        if not want_clear and not want_pic:
            continue
        if sname not in paths or paths[sname] not in parts:
            raise ExportError(f"견본에서 시트 {sname!r} 의 XML 을 찾지 못했다", form=form, sheet=sname)
        if want_pic:
            pic_sheets[sname] = paths[sname]
        if want_clear:
            xml, bom = _text(parts, paths[sname])
            ed = SheetXml(xml, set(), False)
            before = cleared.cells
            clear_ranges(ed, want_clear, cleared)
            per_sheet[sname] = cleared.cells - before
            if ed.dirty:
                _set(parts, paths[sname], ed.render(), bom)
    samples = set(cleared.texts) | sst_texts(parts, cleared.sst_ids)
    pics = remove_pictures(parts, pic_sheets) if pic_sheets else Pictures()
    samples |= pics.texts
    notices: list[dict] = []
    ext = ExternalRemoval()
    ext_before = _external_links(parts)
    if wipe_ext:
        ext = remove_external_links(parts, paths)
        if ext.broken_names:
            notices.append({
                "type": "broken-names",
                "reason": f"`#REF!` 를 가리키는 이름 {len(ext.broken_names)}개는 외부 참조가 아니라 그대로 뒀다: " + "; ".join(ext.broken_names),
            })
    elif ext_before:
        notices.append({
            "type": "external-links",
            "links": len(ext_before),
            "targets": _count_targets(parts, ext_before),
            "reason": f"외부 참조 {len(ext_before)}개(대상 경로 {_count_targets(parts, ext_before)}개)가 남아 있다 — 지도에 `외부_참조_지우기: true` 를 두면 지운다",
        })
    _, n_blank, blanked = blank_strings(parts, cleared)
    samples |= blanked
    if cleared.formulas:
        notices.append({
            "type": "formula-kept",
            "cells": cleared.formulas[:20],
            "reason": f"수식 셀 {len(cleared.formulas)}개는 값이 아니라 수식이라 비우지 않았다",
        })
    if pics.kept_shared:
        notices.append({"type": "drawing-shared", "parts": pics.kept_shared,
                        "reason": "다른 시트가 쓰는 drawing 은 남겼다(그 시트의 연결만 끊었다)"})
    props_cleared = scrub_doc_props(parts)
    notices += review_notices(parts, paths)
    gone = [n for n in original if n not in parts]
    _content_types_drop(parts, gone)
    leftovers = find_leftovers(parts, samples)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zo:
        for info in infos:
            if info.filename in parts:
                zo.writestr(copy.copy(info), parts[info.filename])
    report = {
        "cleared": per_sheet,
        "strings_blanked": n_blank,
        "removed_parts": sorted(gone),
        "external_links": (
            {"removed": ext.links, "targets": ext.targets, "names_removed": ext.names_removed} if wipe_ext else None
        ),
        "doc_props_cleared": props_cleared,
        "notices": notices,
    }
    return Built(buf.getvalue(), report, leftovers)


# ---------------------------------------------------------------- CLI

def _rel(root: Path, p: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return str(p)


def _report(status: str, **kw) -> dict:
    base = {"status": status, "files": [], "problems": [], "warnings": [], "notices": []}
    base.update(kw)
    return base


def run(root: Path, form: str, src: Path, out: Path, check_only: bool) -> tuple[int, dict]:
    if out.exists():
        return EXIT_REJECTED, _report("rejected", problems=[{
            "form": form, "sheet": "", "item": "--out",
            "reason": f"{_rel(root, out)} 가 이미 있다 — 덮어쓰지 않는다. 다른 이름을 쓰거나 지우고 다시 한다",
        }], next="다음: 아무 파일도 만들지 않았다. --out 을 바꾼다.")
    if out.suffix.lower() != ".xlsx":
        return EXIT_REJECTED, _report("rejected", problems=[{
            "form": form, "sheet": "", "item": "--out", "reason": f"--out 은 .xlsx 여야 한다({out.name})",
        }], next="다음: 아무 파일도 만들지 않았다.")
    try:
        out.resolve().relative_to(root)
    except ValueError:
        return EXIT_REJECTED, _report("rejected", problems=[{
            "form": form, "sheet": "", "item": "--out", "reason": f"--out 이 Project Repository({root}) 밖이다",
        }], next="다음: 아무 파일도 만들지 않았다.")
    if not out.parent.is_dir():
        return EXIT_REJECTED, _report("rejected", problems=[{
            "form": form, "sheet": "", "item": "--out", "reason": f"--out 의 폴더 {_rel(root, out.parent)} 가 없다",
        }], next="다음: 아무 파일도 만들지 않았다.")
    try:
        built = build_blank(root, form, src)
    except RangeError as e:
        return EXIT_REJECTED, _report("rejected", problems=[{
            "form": e.form, "sheet": e.sheet, "item": e.item, "reason": e.reason,
        }], next="다음: 지도의 범위를 고친다. 아무 파일도 만들지 않았다.")
    flagged = bool(built.leftovers)
    rp = {**built.report, "dry_run": check_only, "leftovers": built.leftovers}
    if not check_only:
        tmp = out.with_name(out.name + ".tmp")
        tmp.write_bytes(built.data)
        try:
            os.replace(tmp, out)
        finally:
            if tmp.exists():
                tmp.unlink()
        rp["files"] = [_rel(root, out)]
    if flagged:
        return EXIT_LEFTOVER, _report("warning", **rp, next=(
            "다음: " + ("확인만 했고 " if check_only else "파일은 만들었지만 ")
            + "지운 견본 글자가 아직 남아 있다(`leftovers`) — 그 파트를 사람이 확인하고 지도(`비우기`·`그림_지우기`)를 고쳐 다시 한다. 통과가 아니다."
        ))
    return EXIT_OK, _report("ok", **rp, next=(
        "다음: " + ("확인만 했고 파일은 만들지 않았다. --check 없이 다시 실행해 만든다."
                   if check_only else "엑셀로 한 번 열어 서식과 드롭다운이 양식대로인지 확인한다(엔진은 엑셀에서 열어 보지 못한다).")
    ))


def main(argv: list[str] | None = None) -> int:
    export._force_utf8()
    ap = argparse.ArgumentParser(prog="python -m checker.blank_template", description="견본 xlsx 에서 빈 양식 xlsx 를 만든다.")
    ap.add_argument("--root", type=Path, required=True, help="Project Repository 루트")
    ap.add_argument("--form", required=True, help="양식 지도 이름 또는 지도 파일 경로")
    ap.add_argument("--src", type=Path, required=True, help="견본 xlsx(--root 기준 상대·절대)")
    ap.add_argument("--out", type=Path, required=True, help="만들 빈 xlsx(--root 안, 이미 있으면 거부)")
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 같은 처리·검사만 한다")
    args = ap.parse_args(argv)
    try:
        root = args.root.resolve()
        if not root.is_dir():
            raise ExportError(f"--root {args.root} 가 폴더가 아니다")
        form = export.resolve_form(root, args.form)
        src = args.src if args.src.is_absolute() else root / args.src
        out = args.out if args.out.is_absolute() else root / args.out
        code, report = run(root, form, src, out, args.check)
    except ExportError as e:
        code, report = EXIT_ERROR, export._error_report(e.reason, e.form, e.sheet, e.item)
    except Exception as e:  # 예상하지 못한 오류도 검사 불능(2)이다
        code, report = EXIT_ERROR, export._error_report(f"예상하지 못한 오류({type(e).__name__}): {e}")
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
