"""세션 작업 폴더의 문서 목록·미리보기·열기 안전 검사(web-console.md §7b). 표준 라이브러리만 쓰고, 문서 XML 은 DTD 를 거절한다."""
from __future__ import annotations

import codecs
import datetime
import io
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

from platform_compat import is_within

KIND_BY_EXT = {".md": "md", ".markdown": "md", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx", ".docx": "docx", ".pdf": "pdf",
               ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image", ".bmp": "image", ".svg": "image"}
IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
              ".bmp": "image/bmp", ".svg": "image/svg+xml"}
# 열기(open)를 허용하는 확장자. 실행 파일·스크립트·바로가기(.bat .cmd .exe .ps1 .js .vbs .lnk ...)는 여기 없다(위치 보기 reveal 만 된다).
OPEN_EXTS = {".md", ".txt", ".csv", ".xlsx", ".pptx", ".docx", ".pdf", ".png", ".jpg", ".jpeg", ".gif"}  # .xlsm(매크로)·.xls·.svg(스크립트)는 위치 보기만
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache"}
VERSIONED = re.compile(r"^(?P<stem>.+)_v(?P<ver>\d+(?:\.\d+)*)(?P<ext>\.[^.]+)$")

MAX_LISTED = 300
TEXT_LIMIT = 200 * 1024
MAX_ROWS, MAX_COLS, MAX_SHEETS = 200, 40, 20
MAX_SLIDES, MAX_TEXTS = 200, 200
MAX_SHARED_STRINGS = 200000
MAX_PART_BYTES = 16 << 20    # 부분 하나를 풀어도 되는 크기
MAX_TOTAL_BYTES = 64 << 20   # 미리보기 한 번에 풀어도 되는 총 크기
MAX_RAW_BYTES = 20 << 20
UTF_BOMS = (b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")
XML_ENCODING = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([^"']+)["']""")
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


class PreviewError(Exception):
    """문서를 읽지 못했다(깨졌거나 너무 크거나 형식이 다르다)."""


class PathRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def ext_of(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def kind_of(path: str) -> str:
    return KIND_BY_EXT.get(ext_of(path), "other")


def resolve(cwd: str, raw) -> tuple[str, str]:
    """요청 경로를 작업 폴더 안의 실제 파일로 푼다. (realpath, 작업 폴더 기준 상대 경로 '/' 구분). 밖이면 403, 없으면 404."""
    if not isinstance(raw, str) or not raw.strip() or "\0" in raw:
        raise PathRefused(400, "path 가 비어 있거나 올바르지 않습니다.")
    full = os.path.join(cwd, raw.strip())
    if not is_within(full, cwd):
        raise PathRefused(403, "작업 폴더 밖의 경로입니다.")
    real = os.path.realpath(full)
    if not os.path.isfile(real):
        raise PathRefused(404, "없는 파일입니다.")
    return real, os.path.relpath(real, os.path.realpath(cwd)).replace("\\", "/")


# ---- 목록 ----

def _version_key(ver: str) -> tuple[int, ...]:
    return tuple(int(x) for x in ver.split("."))


def _entry(cwd: str, rel: str, changed: bool) -> dict | None:
    try:
        st = os.stat(os.path.join(cwd, *rel.split("/")))
    except OSError:
        return None
    return {"path": rel, "kind": kind_of(rel), "size": st.st_size, "mtime": st.st_mtime, "changed": changed}


def _rel_key(cwd: str, real_cwd: str, raw) -> tuple[str, str] | None:
    """목록에 넣을 수 있는 파일이면 (normcase 상대 경로, 상대 경로). 밖이거나 없거나 건너뛸 폴더·잠금 파일이면 None."""
    if not isinstance(raw, str) or not raw:
        return None
    full = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
    if not is_within(full, cwd) or not os.path.isfile(full):
        return None
    rel = os.path.relpath(os.path.realpath(full), real_cwd).replace("\\", "/")
    parts = rel.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or parts[-1].startswith("~$"):
        return None
    return os.path.normcase(rel), rel


def collect(cwd: str, changed_paths: list[str], current_paths: list[str] | None = None) -> list[dict]:
    """이 세션이 만든·바꾼 파일(changed_paths)을 작업 폴더 기준 상대 경로로 모은다. 같은 이름의 `_v0.1`, `_v0.2` 판은 하나로 묶어
    versions(최신 먼저)에 담고, 묶인 항목의 path·size·mtime 은 가장 높은 판의 것이다. 판 이름이 아닌 파일은 versions 가 빈 목록이다.
    current_paths 는 지금 git status 에 있는 파일이며, 주어지면 거기 있는 것만 changed(커밋 안 된 변경)로 표시한다. None 이면 모두 changed."""
    real_cwd = os.path.realpath(cwd)
    changed: dict[str, str] = {}  # normcase 상대 경로 -> 상대 경로
    for raw in changed_paths:
        got = _rel_key(cwd, real_cwd, raw)
        if got:
            changed.setdefault(got[0], got[1])
    if current_paths is None:
        dirty = changed
    else:
        dirty = {k for k in (_rel_key(cwd, real_cwd, raw) for raw in current_paths) if k}
        dirty = {k[0] for k in dirty}
    items, grouped = [], {}
    for key, rel in changed.items():
        m = VERSIONED.match(posixpath.basename(rel))
        if not m:
            e = _entry(cwd, rel, key in dirty)
            if e:
                e["versions"] = []
                items.append(e)
            continue
        group = (os.path.normcase(posixpath.dirname(rel)), m["stem"].lower(), m["ext"].lower())
        grouped.setdefault(group, (posixpath.dirname(rel), m["stem"], m["ext"]))
    for (_, _, _), (folder, stem, ext) in grouped.items():
        versions = []
        try:
            names = os.listdir(os.path.join(cwd, *folder.split("/")) if folder else cwd)
        except OSError:
            continue
        for name in names:
            m = VERSIONED.match(name)
            if not m or m["stem"].lower() != stem.lower() or m["ext"].lower() != ext.lower():
                continue
            rel = posixpath.join(folder, name) if folder else name
            e = _entry(cwd, rel, os.path.normcase(rel) in dirty)
            if e and os.path.isfile(os.path.join(cwd, *rel.split("/"))):
                e["version"] = m["ver"]
                versions.append(e)
        if not versions:
            continue
        versions.sort(key=lambda v: _version_key(v["version"]), reverse=True)
        top = dict(versions[0], changed=any(v["changed"] for v in versions))
        top["versions"] = [{k: v[k] for k in ("path", "version", "size", "mtime", "changed")} for v in versions]
        top.pop("version", None)
        items.append(top)
    items.sort(key=lambda e: -e["mtime"])
    return items[:MAX_LISTED]


# ---- 미리보기 ----

def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def open_part(zf: zipfile.ZipFile, name: str):
    """zip 안의 XML 부분을 연다. 너무 크거나 외부·확장 엔티티 선언이 있으면 읽지 않는다(XML 폭탄 방지)."""
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise PreviewError(f"문서 안에 {name} 이 없습니다.")
    if info.file_size > MAX_PART_BYTES:
        raise PreviewError(f"{name} 이 너무 커서 미리볼 수 없습니다.")
    left = getattr(zf, "preview_budget", MAX_TOTAL_BYTES) - info.file_size  # 미리보기 한 번에 풀어도 되는 총 바이트
    if left < 0:
        raise PreviewError("문서가 너무 커서 미리볼 수 없습니다.")
    zf.preview_budget = left
    data = zf.read(info)  # 헤더의 크기만큼만 풀린다(위에서 상한을 이미 확인했다)
    if data[:4] in UTF_BOMS or data[:2] in UTF_BOMS or b"\0" in data[:4]:
        raise PreviewError(f"{name} 이 UTF-16/32 로 되어 있어 읽지 않았습니다.")
    declared = XML_ENCODING.search(data[:200])
    if declared and declared.group(1).lower() not in (b"utf-8", b"utf8", b"us-ascii", b"ascii"):
        raise PreviewError(f"{name} 의 문자 인코딩이 UTF-8 이 아니어서 읽지 않았습니다.")
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:  # 부분 전체에서 찾는다(앞부분만 보면 긴 주석 뒤에 숨길 수 있다)
        raise PreviewError(f"{name} 에 허용하지 않는 선언이 있어 읽지 않았습니다.")
    return io.BytesIO(data)


def open_zip(full: str) -> zipfile.ZipFile:
    zf = zipfile.ZipFile(full)
    zf.preview_budget = MAX_TOTAL_BYTES
    return zf


def read_text(full: str) -> dict:
    with open(full, "rb") as fh:
        raw = fh.read(TEXT_LIMIT + 1)
    cut = len(raw) > TEXT_LIMIT
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    return {"kind": "md", "text": decoder.decode(raw[:TEXT_LIMIT], final=not cut), "truncated": cut}  # 자르는 자리의 반쪽 글자는 버린다


def _si_text(si) -> str:
    parts = []
    for ch in si:
        name = local(ch.tag)
        if name == "t":
            parts.append(ch.text or "")
        elif name == "r":
            parts.extend(t.text or "" for t in ch if local(t.tag) == "t")  # 읽기 힌트(rPh)는 건너뛴다
    return "".join(parts)


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    out: list[str] = []
    with open_part(zf, "xl/sharedStrings.xml") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if local(el.tag) == "si":
                out.append(_si_text(el))
                el.clear()
                if len(out) >= MAX_SHARED_STRINGS:
                    break
    return out


def _sheet_targets(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """(시트 이름, zip 안 경로) 목록. workbook.xml 과 그 rels 로 짝을 짓고, rels 가 없으면 sheetN 순서로 둔다."""
    sheets = []
    with open_part(zf, "xl/workbook.xml") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if local(el.tag) == "sheet":
                sheets.append((el.get("name") or "", el.get(REL_NS)))
            el.clear()
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in zf.namelist():
        with open_part(zf, "xl/_rels/workbook.xml.rels") as fh:
            for _, rel in ET.iterparse(fh, events=("end",)):
                if local(rel.tag) != "Relationship":
                    continue
                target = rel.get("Target") or ""
                path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
                targets[rel.get("Id") or ""] = path
                rel.clear()
    found = []
    for i, (name, rid) in enumerate(sheets, 1):
        path = targets.get(rid or "") or f"xl/worksheets/sheet{i}.xml"
        found.append((name or f"Sheet{i}", path))
    return found[:MAX_SHEETS]


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref or "")
    n = 0
    for ch in (letters.group(0).upper() if letters else ""):
        n = n * 26 + ord(ch) - 64
    return n - 1


DATE_ONLY_IDS = {14, 15, 16, 17}
DATE_TIME_IDS = {22}
TIME_ONLY_IDS = {18, 19, 20, 21, 45, 46, 47}
MAX_SERIAL = 2958465  # 9999-12-31


def _format_kind(code: str) -> str:
    """사용자 서식 코드가 날짜(date)·날짜+시간(datetime)·시간(time) 중 무엇인지. 아니면 빈 문자열."""
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code.lower())
    has_date = bool(re.search(r"[yd]|m{3,}", code))
    has_time = "h" in code
    if has_date and has_time:
        return "datetime"
    return "date" if has_date else "time" if has_time else ""


def _date_styles(zf: zipfile.ZipFile) -> dict[int, str]:
    """셀 서식 번호(cellXfs 의 순서) -> date/datetime/time. 날짜가 아닌 서식은 넣지 않는다."""
    if "xl/styles.xml" not in zf.namelist():
        return {}
    custom: dict[int, str] = {}
    xfs: list[int] = []
    in_xfs = False
    with open_part(zf, "xl/styles.xml") as fh:
        for event, el in ET.iterparse(fh, events=("start", "end")):
            name = local(el.tag)
            if event == "start":
                if name == "cellXfs":
                    in_xfs = True
                continue
            if name == "numFmt":
                try:
                    custom[int(el.get("numFmtId") or "")] = el.get("formatCode") or ""
                except ValueError:
                    pass
            elif name == "cellXfs":
                in_xfs = False
            elif in_xfs and name == "xf":
                try:
                    xfs.append(int(el.get("numFmtId") or "0"))
                except ValueError:
                    xfs.append(0)
            if name in ("numFmt", "xf"):
                el.clear()
    out: dict[int, str] = {}
    for i, fmt in enumerate(xfs):
        if fmt in custom:
            kind = _format_kind(custom[fmt])
        else:
            kind = "date" if fmt in DATE_ONLY_IDS else "datetime" if fmt in DATE_TIME_IDS else "time" if fmt in TIME_ONLY_IDS else ""
        if kind:
            out[i] = kind
    return out


def _is_1904(zf: zipfile.ZipFile) -> bool:
    with open_part(zf, "xl/workbook.xml") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if local(el.tag) == "workbookPr":
                return (el.get("date1904") or "").lower() in ("1", "true")
            el.clear()
    return False


def _serial_text(raw: str, kind: str, is1904: bool) -> str:
    """엑셀 일련번호를 YYYY-MM-DD(시간이 있으면 HH:MM)로. 바꿀 수 없으면 원래 글자를 그대로 둔다."""
    try:
        serial = float(raw)
    except ValueError:
        return raw
    if not 0 <= serial <= MAX_SERIAL:
        return raw
    days = int(serial)
    minutes = round((serial - days) * 1440)
    if minutes >= 1440:
        days, minutes = days + 1, 0
    clock = f"{minutes // 60:02d}:{minutes % 60:02d}"
    if kind == "time":
        return clock
    if is1904:
        base = datetime.date(1904, 1, 1)
    elif days == 60:
        return "1900-02-29" + (f" {clock}" if minutes and kind == "datetime" else "")  # 엑셀이 있는 걸로 치는 1900-02-29
    else:
        base = datetime.date(1899, 12, 30) if days >= 61 else datetime.date(1899, 12, 31)
    day = (base + datetime.timedelta(days=days)).isoformat()
    return f"{day} {clock}" if minutes and kind == "datetime" else day


def _cell_value(c, shared: list[str], dates: dict[int, str] | None = None, is1904: bool = False) -> str:
    kind = c.get("t")
    if kind == "inlineStr":
        return "".join(_si_text(ch) for ch in c if local(ch.tag) == "is")
    raw = next((ch.text or "" for ch in c if local(ch.tag) == "v"), "")
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"
    if dates and kind in (None, "n") and raw:
        try:
            style = dates.get(int(c.get("s") or "0"))
        except ValueError:
            style = None
        if style:
            return _serial_text(raw, style, is1904)
    return raw


def _read_sheet(zf: zipfile.ZipFile, path: str, shared: list[str], dates: dict[int, str] | None = None,
                is1904: bool = False) -> tuple[list[list[str]], bool]:
    rows: list[list[str]] = []
    truncated = False
    with open_part(zf, path) as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if local(el.tag) != "row":
                continue
            if len(rows) >= MAX_ROWS:
                truncated = True
                break
            row: list[str] = []
            for c in el:
                if local(c.tag) != "c":
                    continue
                idx = _col_index(c.get("r") or "")
                idx = idx if idx >= 0 else len(row)
                if idx >= MAX_COLS:
                    truncated = True
                    continue
                row.extend([""] * (idx + 1 - len(row)))
                row[idx] = _cell_value(c, shared, dates, is1904)
            rows.append(row)
            el.clear()
    return rows, truncated


def read_xlsx(full: str) -> dict:
    try:
        with open_zip(full) as zf:
            shared = _shared_strings(zf)
            dates, is1904 = _date_styles(zf), _is_1904(zf)
            sheets = []
            for name, path in _sheet_targets(zf):
                if path not in zf.namelist():
                    sheets.append({"name": name, "rows": [], "truncated": False, "error": "시트 파일을 찾지 못했습니다."})
                    continue
                rows, truncated = _read_sheet(zf, path, shared, dates, is1904)
                sheets.append({"name": name, "rows": rows, "truncated": truncated})
    except (zipfile.BadZipFile, ET.ParseError, OSError, ValueError) as e:
        raise PreviewError(f"엑셀 문서를 읽지 못했습니다: {type(e).__name__}")
    return {"kind": "table", "sheets": sheets}


def read_pptx(full: str) -> dict:
    try:
        with open_zip(full) as zf:
            names = sorted((int(m.group(1)), n) for n in zf.namelist() if (m := re.fullmatch(r"ppt/slides/slide(\d+)\.xml", n)))
            slides = []
            for number, name in names[:MAX_SLIDES]:
                texts: list[str] = []
                with open_part(zf, name) as fh:
                    for _, el in ET.iterparse(fh, events=("end",)):
                        if local(el.tag) == "p":
                            text = "".join(t.text or "" for t in el.iter() if local(t.tag) == "t").strip()
                            if text and len(texts) < MAX_TEXTS:
                                texts.append(text)
                            el.clear()
                slides.append({"index": number, "texts": texts})
    except (zipfile.BadZipFile, ET.ParseError, OSError, ValueError) as e:
        raise PreviewError(f"파워포인트 문서를 읽지 못했습니다: {type(e).__name__}")
    return {"kind": "slides", "slides": slides}


def preview(full: str, rel: str, raw_url: str) -> dict:
    """kind 에 따른 미리보기. md 는 글, xlsx 는 표(값만), pptx 는 슬라이드 글, 이미지는 raw 주소, 그 밖은 none."""
    kind = kind_of(full)
    if kind == "md":
        return read_text(full)
    if kind == "xlsx":
        return read_xlsx(full)
    if kind == "pptx":
        return read_pptx(full)
    if kind == "image":
        return {"kind": "image", "url": raw_url}
    return {"kind": "none"}
