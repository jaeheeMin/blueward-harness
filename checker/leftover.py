"""산출 결과에 템플릿 견본이 남았는지 검사한다(이슈 #335, PR B).

산출물은 템플릿의 견본 내용이 없는 상태에서 새로 만든다. 템플릿이 견본이 든 파일이거나 새 양식에서 빈 양식 만들기
(`checker.blank_template`)를 빠뜨리면, 다른 개발 건의 내용이 산출물에 섞여 나간다. 지도 최상위 `견본_검사: true` 인 양식은
산출(`checker.export`, `--check` 포함) 끝에서 이 검사를 하고, 견본이 남았으면 산출을 거부한다(종료코드 1).

판정: 산출 결과의 모든 시트에서 값이 있는 셀 가운데 다음 중 하나도 아니면 남은 견본이다.
    - 이번 산출이 쓴 셀(`SheetXml.written`: 칸·표·서술·화면 그림·파일명 자리가 쓴 곳)
    - 지도 `유지:` 범위 안(양식에 원래 있는 고정 문구·작성 안내문을 사람이 적어 둔 곳)
    - 지도 표의 머리글 행(`머리글_행`)
    - 지도 `자동: true` 칸(템플릿이 값을 채워 두는 곳)
지도 밖 칸만이 아니라 시트 전체를 본다 — 지도에 없는 시트(드롭다운 목록 시트 등)도 같다. 그 시트의 고정 값은 지도에 시트 항목
(`이름` + `유지`)을 두어 적는다. 해당 없음 시트도 같은 규칙이다(템플릿 글자가 남으면 견본이다).

그 밖에 견본으로 보는 것
    - 그림·도형·차트(drawing): `유지` 범위 안 셀에 앵커(왼쪽 위)가 있으면 고정 요소로 허용한다. 그 밖은 견본이다.
    - 셀 메모(comments, threaded 포함): `유지` 범위 안 셀의 메모만 허용한다.
    - 시트 배경 그림·머리글 그림·삽입 개체·컨트롤: 위치를 판정할 수 없어 견본으로 보고 막는다(이런 템플릿은 `견본_검사` 를 켜지 않는다).
    - 머리글/바닥글 글자와 직접 적은 드롭다운 목록은 견본인지 고정값인지 엔진이 가를 수 없다 — 거부하지 않고 경고(`leftover-review`)로
      알린다. 직접 적은 목록은 그 범위가 `유지` 안이면 알리지 않는다.

검사하지 못하면 통과로 두지 않고 거부 사유(`leftover-unchecked`)로 알린다: 시트 XML·그림·메모 파트를 못 읽음, 값이 있다고 표시된
셀의 값을 못 읽음(공유 문자열 번호가 범위 밖이거나 sharedStrings 가 없음, `<v>` 모양이 낯섦), 차트 시트(지원 안 함),
데이터 유효성을 읽다 예외가 남. 메모 시트의 VML 에 메모가 아닌 개체(ClientData ObjectType 이 Note 가 아님)가 있으면 견본(개체)이다.
읽을 수 있었지만 목록 항목이 해석되지 않은 유효성(범위 없음·formula1 없음)은 경고(`leftover-review`)다.

검사하지 않는 곳 (경고도 내지 않는다)
    - 이름 정의(definedNames): Print_Area·_FilterDatabase 같은 이름이 양식 원본에 늘 있어 경고하면 늘 뜨는 소음이다. 외부 파일을 가리키는 이름은
      `외부_참조_지우기`(빈 양식 만들기)가 다룬다. 이름이 견본 범위를 가리켜도 산출물 값은 아니다.
    - 시트 이름: 지도가 이름을 정한 시트는 견본이 아니고, 지도에 없는 시트는 값이 있으면 이미 거부된다.
    - 문서 속성(docProps): 양식 원본의 값(제목·작성자·회사)이 늘 들어 있어 경고하면 소음이다. 빈 양식 만들기가 제목·작성자·
      마지막 수정자·Company·Manager 를 비운다. 그 밖 속성(subject·description·keywords·category)은 빈 양식 만들기 `notices` 가 알린다.
    - 차트 안 글자와 캐시 값, 텍스트 상자·도형 안 글자: 개체 단위로만 판정한다. 앵커가 `유지` 밖이면 개체째 거부하고, `유지` 안이면
      작성자가 고정 요소로 선언한 것이라 안의 글자는 보지 않는다.
    - 외부 참조(externalLinks)·조건부 서식·셀 서식·병합 같은 서식 요소.
"""
from __future__ import annotations

import posixpath
import re
from typing import Callable

from checker import blank_template
from checker.export import ExportError, SheetXml, col2n, is_formula, n2col, norm
from checker.xlsx_validation import _VALIDATION_RE, ListReader

Rect = tuple[int, int, int, int]

MAX_LISTED = 8  # 사유 문장에 앞부분만 싣는다
MAX_CELLS = 500  # 보고의 `cells` 에 싣는 최대 칸 수
PREVIEW = 24

_ATTR = re.compile(r'([\w:]+)="([^"]*)"')
_ANCHOR = re.compile(r"<(?:\w+:)?(twoCellAnchor|oneCellAnchor|absoluteAnchor)\b[^>]*>(.*?)</(?:\w+:)?\1>", re.S)
_FROM = re.compile(r"<(?:\w+:)?from>\s*<(?:\w+:)?col>(\d+)</(?:\w+:)?col>.*?<(?:\w+:)?row>(\d+)</(?:\w+:)?row>", re.S)
_OBJ = re.compile(r"<(?:\w+:)?(sp|pic|graphicFrame|cxnSp|grpSp)[\s>/]")
_TEXT = re.compile(r"<(?:\w+:)?t\b[^>]*>(.*?)</(?:\w+:)?t>", re.S)
_COMMENT = re.compile(r"<comment\b([^>]*)>(.*?)</comment>", re.S)
_THREADED = re.compile(r"<threadedComment\b([^>]*)>(.*?)</threadedComment>", re.S)
_HF = re.compile(r"<(?:\w+:)?headerFooter\b[^>]*>(.*?)</(?:\w+:)?headerFooter>", re.S)
_HF_PART = re.compile(r"<(?:\w+:)?(odd|even|first)(Header|Footer)\b[^>]*>(.*?)</(?:\w+:)?\1\2>", re.S)
_HF_CODE = re.compile(r'&"[^"]*"|&K[0-9A-Fa-f]{6}|&\d{1,3}|&[LCRBIUSXYEGPNDTFAZOH+\-]')
_OBJECT_TYPE = re.compile(r"""<(?:\w+:)?ClientData\b[^>]*?\bObjectType\s*=\s*["']([^"']*)["']""")
_SI = re.compile(r"<si\b[^>]*?(?:/>|>.*?</si>)", re.S)


def keep_rects(smap: dict) -> list[Rect]:
    """시트 항목의 `유지` 범위들(모양은 지도 검증이 이미 봤다)."""
    return [blank_template.parse_range(x) for x in (smap.get("유지") or [])]


def _in(rects: list[Rect], col: int, row: int) -> bool:
    return any(c1 <= col <= c2 and r1 <= row <= r2 for c1, r1, c2, r2 in rects)


def _unesc(text: str) -> str:
    return blank_template._unesc(text)


def _shared_strings(raw: dict[str, bytes]) -> list[str] | None:
    data = raw.get("xl/sharedStrings.xml")
    if not data:
        return None
    return [blank_template._si_text(m.group(0)) for m in _SI.finditer(data.decode("utf-8-sig"))]


class _Unreadable(Exception):
    """값이 있다고 표시된 셀의 값을 읽지 못했다(통과도 위반도 아니다)."""


def _cell_text(cell, sst: list[str] | None) -> str:
    """셀의 눈에 보이는 값(수식은 `=식`). 값이 비어 있으면 빈 문자열. 값이 있다고 표시됐는데 읽지 못하면 _Unreadable."""
    inner = cell.inner
    if is_formula(inner):
        m = re.search(r"<f\b[^>]*>(.*?)</f>", inner, re.S)
        return "=" + _unesc(m.group(1)) if m and m.group(1) else "(수식)"
    t = dict(cell.attrs).get("t", "")
    if t == "inlineStr":
        return blank_template._si_text(inner)
    v = re.search(r"<v\b[^>]*?(?:/>|>(.*?)</v>)", inner, re.S)
    if v is None:
        raise _Unreadable("값 요소(<v>)의 모양을 읽지 못했다")
    body = v.group(1) or ""
    if t == "s":
        if sst is None:
            raise _Unreadable("공유 문자열 파트(sharedStrings)가 없다")
        try:
            return sst[int(body)]
        except (ValueError, IndexError):
            raise _Unreadable(f"공유 문자열 번호 {body.strip()!r} 를 읽지 못했다(범위 밖이거나 숫자가 아니다)") from None
    return _unesc(body).strip()


def _preview(text: str, n: int = PREVIEW) -> str:
    one = re.sub(r"\s+", " ", text).strip()
    return one if len(one) <= n else one[: n - 1] + "…"


def _rels(raw: dict[str, bytes], part: str) -> list[tuple[str, str]]:
    """파트의 관계 → [(종류 마지막 토막, 대상 파트 경로)]. 외부 대상은 뺀다."""
    d, _, base = part.rpartition("/")
    data = raw.get(f"{d}/_rels/{base}.rels" if d else f"_rels/{base}.rels")
    if not data:
        return []
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"<Relationship\b[^>]*>", data.decode("utf-8-sig", "replace")):
        a = dict(_ATTR.findall(m.group(0)))
        if a.get("TargetMode") == "External":
            continue
        t = a.get("Target", "")
        target = posixpath.normpath(t[1:] if t.startswith("/") else posixpath.join(d, t))
        out.append((a.get("Type", "").rsplit("/", 1)[-1], target))
    return out


def _drawing_items(raw: dict[str, bytes], sheet_path: str) -> tuple[list[tuple[str, tuple[int, int] | None, str]], list[str]]:
    """시트 drawing 의 개체들 → ([(종류, (열, 행) 또는 None, 글자)], 읽지 못한 사유들). 열·행은 1부터."""
    items: list[tuple[str, tuple[int, int] | None, str]] = []
    unread: list[str] = []
    for kind, target in _rels(raw, sheet_path):
        if kind != "drawing":
            continue
        data = raw.get(target)
        if data is None:
            unread.append(f"drawing 파트 {target} 가 없다")
            continue
        xml = data.decode("utf-8-sig", "replace")
        for m in _ANCHOR.finditer(xml):
            body = m.group(2)
            fm = _FROM.search(body)
            pos = (int(fm.group(1)) + 1, int(fm.group(2)) + 1) if fm and m.group(1) != "absoluteAnchor" else None
            om = _OBJ.search(body)
            label = {"pic": "그림", "sp": "도형", "graphicFrame": "차트·표", "cxnSp": "연결선", "grpSp": "도형 묶음"}.get(om.group(1), "개체") if om else "개체"
            text = " ".join(_unesc(t) for t in _TEXT.findall(body)).strip()
            items.append((label, pos, text))
        for om in _OBJ.finditer(_ANCHOR.sub("", xml)):  # 앵커 밖에 놓인 개체는 위치를 알 수 없다
            items.append(("개체", None, ""))
    return items, unread


def _comments(raw: dict[str, bytes], sheet_path: str) -> tuple[list[tuple[str, str]], list[str], bool]:
    """시트 메모 → ([(셀, 글자)], 읽지 못한 사유들, 메모 파트가 있는가)."""
    out: list[tuple[str, str]] = []
    unread: list[str] = []
    found = False
    for kind, target in _rels(raw, sheet_path):
        if kind not in ("comments", "threadedComment"):
            continue
        found = True
        data = raw.get(target)
        if data is None:
            unread.append(f"메모 파트 {target} 가 없다")
            continue
        xml = data.decode("utf-8-sig", "replace")
        pattern = _THREADED if kind == "threadedComment" else _COMMENT
        hits = 0
        for m in pattern.finditer(xml):
            ref = dict(_ATTR.findall(m.group(1))).get("ref", "")
            text = " ".join(_unesc(t) for t in _TEXT.findall(m.group(2))).strip()
            if kind == "threadedComment":
                tm = re.search(r"<(?:\w+:)?text>(.*?)</(?:\w+:)?text>", m.group(2), re.S)
                text = _unesc(tm.group(1)).strip() if tm else text
            out.append((ref, text))
            hits += 1
        if not hits and re.search(r"<(?:\w+:)?(?:comment|threadedComment)\b", xml):
            unread.append(f"메모 파트 {target} 를 읽지 못했다")
    return out, unread, found


def _header_footer_texts(sheet_xml: str) -> list[str]:
    out: list[str] = []
    for hm in _HF.finditer(sheet_xml):
        for pm in _HF_PART.finditer(hm.group(1)):
            text = _HF_CODE.sub("", _unesc(pm.group(3))).replace("&&", "&").strip()
            if re.search(r"\w", text):  # 쪽 번호 코드 사이의 구분 기호(`/`)뿐인 것은 글자가 아니다
                out.append(_preview(text, 40))
    return out


def _col_row(ref: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return (col2n(m.group(1)), int(m.group(2))) if m else None


def check(
    form: str,
    fmap: dict,
    raw: dict[str, bytes],
    paths: dict[str, str],
    wb_xml: str,
    editor: Callable[[str], SheetXml],
) -> tuple[list[dict], list[dict]]:
    """(거부 사유들, 경고들). `editor(시트)` 는 산출이 손댄 뒤의 시트 편집기다(`written` 이 쓴 셀을 안다)."""
    problems: list[dict] = []
    warnings: list[dict] = []
    sst = _shared_strings(raw)
    map_sheets = {norm(s["이름"]): s for s in fmap.get("시트") or [] if isinstance(s, dict) and "이름" in s}
    reader = ListReader(raw, paths, wb_xml)

    def problem(sheet: str, item: str, type_: str, reason: str, **extra) -> None:
        problems.append({"form": form, "sheet": sheet, "item": item, "type": type_, "reason": reason, **extra})

    for sname, spath in paths.items():
        smap = map_sheets.get(sname, {})
        keep = keep_rects(smap)
        head = raw.get(spath, b"")[:4096].decode("utf-8-sig", "replace")
        if re.search(r"<(?:\w+:)?(?:chartsheet|dialogsheet)\b", head):
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 는 차트 시트(또는 대화 시트)라 지원하지 않는다 — 남은 견본을 검사하지 못했다(통과도 위반도 아니다)")
            continue
        try:
            ed = editor(sname)
            sheet_xml = raw[spath].decode("utf-8-sig", "replace")
        except (ExportError, KeyError) as e:
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 를 읽지 못해 남은 견본을 검사하지 못했다(통과도 위반도 아니다): {getattr(e, 'reason', e)}")
            continue

        # -- 셀 값
        header_rows = {
            t["머리글_행"] for t in smap.get("표") or []
            if isinstance(t, dict) and isinstance(t.get("머리글_행"), int) and not isinstance(t.get("머리글_행"), bool)
        }
        auto: list[Rect] = []
        for f in smap.get("칸") or []:
            if isinstance(f, dict) and f.get("자동") and f.get("위치"):
                auto.append(blank_template.parse_range(f["위치"]))
        left: list[tuple[str, str]] = []
        unreadable: list[tuple[str, str]] = []
        for n in sorted(ed.rows):
            if n in header_rows:
                continue
            for c in ed.rows[n].cells:
                if not c.has_content() or c.ref in ed.written or _in(keep, c.col, n) or _in(auto, c.col, n):
                    continue
                try:
                    text = _cell_text(c, sst)
                except _Unreadable as e:
                    unreadable.append((c.ref, str(e)))
                    continue
                if text.strip():
                    left.append((c.ref, text))
        if unreadable:
            shown = ", ".join(f"{ref}({why})" for ref, why in unreadable[:MAX_LISTED]) + (f" … 외 {len(unreadable) - MAX_LISTED}칸" if len(unreadable) > MAX_LISTED else "")
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 의 값이 있다고 표시된 셀 {len(unreadable)}칸을 읽지 못해 남은 견본을 검사하지 못했다(통과도 위반도 아니다): {shown}", count=len(unreadable))
        if left:
            shown = ", ".join(f"{ref} {_preview(v)!r}" for ref, v in left[:MAX_LISTED]) + (f" … 외 {len(left) - MAX_LISTED}칸" if len(left) > MAX_LISTED else "")
            problem(
                sname, "견본 남음(셀)", "leftover-sample",
                f"시트 {sname} 에 템플릿 견본으로 보이는 값이 {len(left)}칸 남아 있다(이번 산출이 쓰지 않았고 지도 `유지` 범위도 아니다): {shown}",
                kind="cells", count=len(left),
                cells=[{"cell": ref, "value": _preview(v, 60)} for ref, v in left[:MAX_CELLS]],
            )

        # -- 그림·도형
        items, unread = _drawing_items(raw, spath)
        stray = [(k, pos, t) for k, pos, t in items if pos is None or not _in(keep, pos[0], pos[1])]
        if stray:
            def where(pos) -> str:
                return f"{n2col(pos[0])}{pos[1]}" if pos else "위치 불명"
            shown = ", ".join(f"{where(pos)} {k}" + (f" {_preview(t)!r}" if t else "") for k, pos, t in stray[:MAX_LISTED]) + (f" … 외 {len(stray) - MAX_LISTED}개" if len(stray) > MAX_LISTED else "")
            problem(
                sname, "견본 남음(그림)", "leftover-sample",
                f"시트 {sname} 에 템플릿의 그림·도형 {len(stray)}개가 남아 있다(왼쪽 위 칸이 지도 `유지` 범위 밖): {shown}",
                kind="drawings", count=len(stray),
            )
        for why in unread:
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 의 그림을 읽지 못해 검사하지 못했다(통과도 위반도 아니다): {why}")

        # -- 메모
        notes, unread, has_notes = _comments(raw, spath)
        stray_notes = []
        for ref, text in notes:
            pos = _col_row(ref)
            if pos is None or not _in(keep, pos[0], pos[1]):
                stray_notes.append((ref or "위치 불명", text))
        if stray_notes:
            shown = ", ".join(f"{ref} {_preview(t)!r}" for ref, t in stray_notes[:MAX_LISTED]) + (f" … 외 {len(stray_notes) - MAX_LISTED}개" if len(stray_notes) > MAX_LISTED else "")
            problem(
                sname, "견본 남음(메모)", "leftover-sample",
                f"시트 {sname} 에 템플릿의 셀 메모 {len(stray_notes)}개가 남아 있다(셀이 지도 `유지` 범위 밖): {shown}",
                kind="comments", count=len(stray_notes),
            )
        for why in unread:
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 의 메모를 읽지 못해 검사하지 못했다(통과도 위반도 아니다): {why}")

        # -- 위치를 판정할 수 없는 개체
        odd = [
            label for label, pat in (
                ("시트 배경 그림", r"<picture\b"),
                ("머리글·바닥글 그림", r"<legacyDrawingHF\b"),
                ("삽입 개체", r"<oleObjects\b"),
                ("컨트롤", r"<controls\b"),
            ) if re.search(pat, sheet_xml)
        ]
        if re.search(r"<legacyDrawing\b", sheet_xml):
            if not has_notes:
                odd.append("옛 형식 개체(legacyDrawing)")
            else:  # 메모 시트의 VML 도형 가운데 메모(Note)가 아닌 것(버튼·컨트롤·그림)은 견본이다
                for kind, target in _rels(raw, spath):
                    if kind != "vmlDrawing":
                        continue
                    vml = raw.get(target)
                    if vml is None:
                        problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 의 VML 파트 {target} 가 없어 메모 시트의 개체를 검사하지 못했다(통과도 위반도 아니다)")
                        continue
                    kinds = _OBJECT_TYPE.findall(vml.decode("utf-8-sig", "replace"))
                    other = sorted({k for k in kinds if k != "Note"})
                    if other:
                        odd.append(f"메모가 아닌 VML 개체({', '.join(other)})")
        if odd:
            problem(
                sname, "견본 남음(개체)", "leftover-sample",
                f"시트 {sname} 에 위치를 판정할 수 없는 개체({', '.join(odd)})가 있어 견본이 아니라고 볼 수 없다 — 템플릿에서 지우거나 이 양식은 `견본_검사` 를 끈다",
                kind="objects", count=len(odd),
            )

        # -- 머리글/바닥글: 엔진이 견본인지 가를 수 없다
        for text in _header_footer_texts(sheet_xml):
            warnings.append({
                "form": form, "sheet": sname, "item": "머리글·바닥글", "type": "leftover-review",
                "reason": f"시트 {sname} 의 머리글·바닥글에 글자 {text!r} 가 있다 — 고정 문구인지 견본인지 엔진이 가르지 못한다(통과 아님). 견본이면 템플릿에서 지운다",
            })

        # -- 직접 적은 드롭다운 목록
        try:
            vals = reader.validations(sname)
            listed = sum(1 for m in _VALIDATION_RE.finditer(sheet_xml) if dict(_ATTR.findall(m.group(2))).get("type") == "list")
            if listed > len(vals):
                warnings.append({
                    "form": form, "sheet": sname, "item": "드롭다운 목록", "type": "leftover-review",
                    "reason": (
                        f"시트 {sname} 의 목록형 데이터 유효성 {listed}개 가운데 {listed - len(vals)}개는 적용 범위나 목록 수식이 없어 해석하지 못했다"
                        "(통과 아님) — 템플릿에서 확인한다"
                    ),
                })
            for v in vals:
                if not v.formula.lstrip("=").startswith('"'):
                    continue
                if all(any(k[0] <= c1 and c2 <= k[2] and k[1] <= r1 and r2 <= k[3] for k in keep) for c1, r1, c2, r2 in v.ranges):
                    continue
                warnings.append({
                    "form": form, "sheet": sname, "item": "드롭다운 목록", "type": "leftover-review",
                    "reason": (
                        f"시트 {sname} 의 {v.cells_text()} 드롭다운 목록이 템플릿에 직접 적혀 있다({_preview(v.formula, 40)}) — 고정 선택지인지 견본인지 "
                        "엔진이 가르지 못한다(통과 아님). 고정 선택지면 그 범위를 지도 `유지` 에 넣고, 견본이면 `유효성_지우기` 로 빈 양식을 만든다"
                    ),
                })
        except Exception as e:  # 유효성 XML 이 예상과 다르면 읽지 못한 파트다 — 통과로 두지 않고 거부한다
            problem(sname, "검사 불능", "leftover-unchecked", f"시트 {sname} 의 데이터 유효성을 읽지 못해 직접 적은 목록을 검사하지 못했다(통과도 위반도 아니다): {type(e).__name__}: {e}")
    return problems, warnings
