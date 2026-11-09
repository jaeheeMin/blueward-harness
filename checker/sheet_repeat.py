"""견본 시트 반복 복제(#830) — 지도 시트 항목의 `반복: true` 를 xlsx 산출에서 푼다.

Test Case 마다 시트가 하나씩 있는 양식은 템플릿에 견본 시트를 하나 두고, 작업본 소절마다 그것을 복제해 쓴다.

지도(시트 항목):
  반복: true            이 템플릿 시트를 견본으로 본다. 작업본의 `### <양식> · <견본 이름> · <ID>` 소절마다 시트 하나가
                        복제되고, 복제본의 시트 이름은 ID 다. 견본 시트 자체는 산출에서 빠진다.
  빼기: [시트 이름…]    (반복 항목에만) 템플릿에 함께 들어 있는 다른 견본 시트를 산출에서 뺀다.
  칸 `형식`의 `{ID}`    복제본 안 칸에 소절의 ID 를 넣는다(예 `형식: "{ID} : {값}"`). 항목 `ID` 는 작업본에 적지 않아도 ID 로 채워진다.

작업본의 소절 이름은 `parse_spec` 이 `견본 · ID` 한 덩어리 시트 이름으로 읽는다(파서는 그대로). 복제는 그 덩어리를 ID 이름 시트로 푼다.
복제할 수 없는 구조(drawing·차트·표 파트가 딸린 시트)는 ExportError(검사 불능)다.
시트 순서가 바뀌므로 calcChain 은 지운다(엑셀이 다시 만든다).
"""
from __future__ import annotations

import copy
import posixpath
import re
import zipfile
from xml.sax.saxutils import escape, unescape

from checker.export import _ATTR_RE, ExportError, norm

_BAD_CHARS = set("\\/?*[]:")
_COPY_TYPES = {"printerSettings", "comments", "vmlDrawing"}  # 시트마다 따로 갖는 딸린 파트(복제본에 새 이름으로 복사)
_UNESC = {"&quot;": '"', "&apos;": "'"}
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


# ---------------------------------------------------------------- 지도·작업본 읽기

def name_problem(name: str) -> str | None:
    """시트 이름(ID)이 엑셀 규칙을 어기면 사유."""
    if not name:
        return "시트 이름(ID)이 비어 있다"
    if len(name) > 31:
        return f"시트 이름 {name!r} 이 {len(name)}자다(엑셀은 31자까지)"
    bad = sorted({c for c in name if c in _BAD_CHARS or ord(c) < 32})
    if bad:
        return f"시트 이름 {name!r} 에 쓸 수 없는 문자 {' '.join(repr(c) for c in bad)} 가 있다(\\ / ? * [ ] : 금지)"
    if name.startswith("'") or name.endswith("'"):
        return f"시트 이름 {name!r} 은 작은따옴표로 시작하거나 끝날 수 없다"
    return None


def split_key(key: str) -> tuple[str, str] | None:
    """작업본 시트 이름 `견본 · ID` → (견본, ID). `·` 가 없으면 None."""
    head, sep, rest = key.partition("·")
    return (norm(head), norm(rest)) if sep else None


def repeat_names(map_sheets: dict) -> set[str]:
    return {n for n, s in map_sheets.items() if s.get("반복") is True}


def resolve(map_sheets: dict, key: str) -> tuple[dict, str] | None:
    """작업본 시트 이름이 반복 견본의 소절이면 (견본의 지도 항목, ID)."""
    if key in map_sheets:
        return None
    sp = split_key(key)
    if sp and sp[0] in repeat_names(map_sheets):
        return map_sheets[sp[0]], sp[1]
    return None


def map_problems(fmap: dict) -> list[tuple[str, str]]:
    """`반복`·`빼기` 의 모양 오류 → [(종류, 사유)]."""
    out: list[tuple[str, str]] = []
    sheets = [s for s in fmap.get("시트") or [] if isinstance(s, dict)]
    mapped = {norm(str(s.get("이름"))) for s in sheets}
    for s in sheets:
        sn = s.get("이름")
        rep, ex = s.get("반복"), s.get("빼기")
        if rep is not None and not isinstance(rep, bool):
            out.append(("map", f"시트 {sn!r} 의 `반복` 은 true/false 여야 한다"))
        if ex is None:
            continue
        if rep is not True:
            out.append(("map", f"시트 {sn!r} 의 `빼기` 는 `반복: true` 인 시트 항목에만 쓴다"))
        elif not isinstance(ex, list) or not ex or not all(isinstance(x, str) and x.strip() for x in ex):
            out.append(("map", f"시트 {sn!r} 의 `빼기`(시트 이름 문자열 목록이어야 한다)"))
        else:
            for x in ex:
                if norm(x) in mapped:
                    out.append(("map", f"시트 {sn!r} 의 `빼기` {x!r} 는 지도에 시트 항목으로 있는 시트다 — 빼면서 채울 수 없다"))
    return out


# ---------------------------------------------------------------- 풀기

def _rels_of(part: str) -> str:
    d, _, base = part.rpartition("/")
    return f"{d}/_rels/{base}.rels"


def _resolve_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target[1:]
    return posixpath.normpath(posixpath.join(source_part.rpartition("/")[0], target))


def _rel_tags(text: str) -> list[tuple[str, dict[str, str]]]:
    return [(m.group(0), dict(_ATTR_RE.findall(m.group(0)))) for m in re.finditer(r"<Relationship\b[^>]*?/>", text)]


def _override(ct: str, part: str) -> str | None:
    for m in re.finditer(r"<Override\b[^>]*?/>", ct):
        if dict(_ATTR_RE.findall(m.group(0))).get("PartName") == "/" + part:
            return m.group(0)
    return None


def _name_ref(old: str) -> re.Pattern:
    """수식·이름 안에서 시트 `old` 를 가리키는 머리(`'old'!` 또는 `old!`). 문서는 XML 이스케이프 된 글이다."""
    esc = escape(old)
    return re.compile(r"'" + re.escape(esc.replace("'", "''")) + r"'!|(?<![\w.'])" + re.escape(esc) + r"!")


def _quoted(new: str) -> str:
    return "'" + escape(new).replace("'", "''") + "'!"


def expand(form, fmap, sections, infos, raw, paths, wb_xml, problem, warn):
    """반복 견본을 푼다. (fmap, sections, infos, raw, paths, wb_xml) 를 낸다. 반복 시트가 없으면 입력 그대로."""
    sheets = fmap.get("시트") or []
    reps = [s for s in sheets if s.get("반복") is True]
    if not reps:
        return fmap, sections, infos, raw, paths, wb_xml
    raw, infos = dict(raw), list(infos)
    map_names = {norm(s["이름"]) for s in sheets}

    m = re.search(r"<sheets>(.*?)</sheets>", wb_xml, re.S)
    if not m:
        raise ExportError("workbook.xml 에 sheets 가 없다", form=form)
    tags = re.findall(r"<sheet\b[^>]*?/>", m.group(1))
    order: list[tuple[str, str, dict[str, str]]] = []  # (정규화 이름, 태그, 속성)
    for t in tags:
        a = dict(_ATTR_RE.findall(t))
        order.append((norm(unescape(a["name"], _UNESC)), t, a))
    tmpl_names = [n for n, _, _ in order]

    # 견본별 소절과 뺄 시트
    plan: dict[str, list[tuple[str, str]]] = {}  # 견본 이름 → [(작업본 시트 이름, ID)]
    remove: set[str] = set()
    for s in reps:
        rn = norm(s["이름"])
        if rn not in tmpl_names:
            raise ExportError(f"반복 견본 시트 {rn!r} 가 템플릿에 없다", form=form, sheet=rn)
        if rn in sections:
            raise ExportError(
                f"{rn!r} 는 반복 견본이라 `### {form} · {rn}` 으로 쓸 수 없다 — `### {form} · {rn} · <ID>` 소절을 쓴다(소절마다 시트 하나)",
                form=form, sheet=rn,
            )
        remove.add(rn)
        for x in s.get("빼기") or []:
            if norm(x) not in tmpl_names:
                raise ExportError(f"`빼기` 의 시트 {x!r} 가 템플릿에 없다", form=form, sheet=rn)
            remove.add(norm(x))
        plan[rn] = [(k, sp[1]) for k in sections if (sp := split_key(k)) and sp[0] == rn and k not in map_names]

    kept = {n.lower() for n in tmpl_names if n not in remove}
    seen: set[str] = set()
    accepted: dict[str, list[tuple[str, str]]] = {}
    for rn, items in plan.items():
        accepted[rn] = []
        for key, sid in items:
            why = name_problem(sid)
            if not why and sid.lower() in kept | seen:
                why = f"시트 이름 {sid!r} 이 다른 시트와 겹친다(대소문자는 구분하지 않는다)"
            if why:
                problem(key, sid, why)
                continue
            seen.add(sid.lower())
            accepted[rn].append((key, sid))
        if not items:
            warn(rn, "", f"작업본에 `### {form} · {rn} · <ID>` 소절이 없어 견본 시트 {rn!r} 만 산출에서 뺐다(복제본 없음)")

    # ---- 부품 복사
    wb_rels_path = "xl/_rels/workbook.xml.rels"
    wb_rels = raw[wb_rels_path].decode("utf-8-sig")
    ct = raw["[Content_Types].xml"].decode("utf-8-sig")
    next_sheet = max(int(n) for n in (re.findall(r"xl/worksheets/sheet(\d+)\.xml", "\n".join(raw)) or ["0"])) + 1
    next_rid = max([int(x) for x in re.findall(r'Id="rId(\d+)"', wb_rels)] or [0]) + 1
    next_sid = max([int(a.get("sheetId", "0")) for _, _, a in order] or [0]) + 1
    added: list[str] = []
    gone: set[str] = set()

    def unique(path: str) -> str:
        mm = re.fullmatch(r"(.*?)(\d*)(\.[^./]+)", path)
        prefix, num, ext = mm.groups()
        n = int(num or 0) + 1
        while f"{prefix}{n}{ext}" in raw:
            n += 1
        return f"{prefix}{n}{ext}"

    def add(path: str, data: bytes) -> None:
        raw[path] = data
        added.append(path)

    def copy_related(src_sheet: str, new_sheet: str) -> None:
        rp = _rels_of(src_sheet)
        if rp not in raw:
            return
        text = raw[rp].decode("utf-8-sig")
        for tag, a in _rel_tags(text):
            if a.get("TargetMode") == "External":
                continue
            typ = a.get("Type", "").rsplit("/", 1)[-1]
            if typ not in _COPY_TYPES:
                raise ExportError(
                    f"견본 시트에 복제할 수 없는 딸린 파트({typ})가 있다 — 복제하지 않았다(검사 불능, 통과 아님). "
                    f"drawing·차트·표가 없는 견본으로 만든다", form=form, sheet=src_sheet,
                )
            target = a["Target"]
            src = _resolve_target(src_sheet, target)
            if src not in raw:
                raise ExportError(f"견본 시트의 딸린 파트 {src} 가 템플릿에 없다", form=form, sheet=src_sheet)
            dst = unique(src)
            add(dst, raw[src])
            ov = _override(ct, src)
            if ov:
                ct_adds.append(ov.replace(f'PartName="/{src}"', f'PartName="/{dst}"'))
            sub = _rels_of(src)
            if sub in raw:  # 파트가 다시 딸린 것(예: vml 의 그림)은 그림만 같이 쓴다
                for _, sa in _rel_tags(raw[sub].decode("utf-8-sig")):
                    if sa.get("TargetMode") != "External" and not sa.get("Type", "").endswith("/image"):
                        raise ExportError(
                            f"견본 시트의 딸린 파트 {src} 에 복제할 수 없는 연결({sa.get('Type', '').rsplit('/', 1)[-1]})이 있다 — 복제하지 않았다(검사 불능, 통과 아님)",
                            form=form, sheet=src_sheet,
                        )
                add(_rels_of(dst), raw[sub])
            new_target = target[: len(target) - len(target.rsplit("/", 1)[-1])] + dst.rsplit("/", 1)[-1]
            text = text.replace(tag, tag.replace(f'Target="{target}"', f'Target="{new_target}"'))
        add(_rels_of(new_sheet), text.encode("utf-8"))

    ct_adds: list[str] = []
    clones: dict[str, list[tuple[str, str, str, str]]] = {}  # 견본 → [(ID, 새 경로, rId, 태그)]
    for rn, items in accepted.items():
        src = paths[rn]
        src_text = raw[src].decode("utf-8-sig")
        tag0 = next(t for n, t, _ in order if n == rn)
        clones[rn] = []
        for key, sid in items:
            new = f"xl/worksheets/sheet{next_sheet}.xml"
            next_sheet += 1
            body = re.sub(r'\s+xr:uid="[^"]*"', "", src_text, count=1)  # 시트마다 하나여야 하는 식별자
            body = re.sub(r'\s+tabSelected="(?:1|true)"', "", body)  # 시트 여럿이 선택되면 묶음 편집이 된다
            add(new, body.encode("utf-8"))
            copy_related(src, new)
            ov = _override(ct, src)
            if ov:
                ct_adds.append(ov.replace(f'PartName="/{src}"', f'PartName="/{new}"'))
            rid = f"rId{next_rid}"
            next_rid += 1
            tag = re.sub(r'\bname="[^"]*"', f'name="{escape(sid, {chr(34): "&quot;"})}"', tag0, count=1)
            tag = re.sub(r'\bsheetId="[^"]*"', f'sheetId="{next_sid}"', tag, count=1)
            tag = re.sub(r'\br:id="[^"]*"', f'r:id="{rid}"', tag, count=1)
            next_sid += 1
            clones[rn].append((sid, new, rid, tag))

    # ---- 새 시트 목록·workbook.xml
    new_tags: list[str] = []
    new_names: list[str] = []
    old_to_new: dict[int, int] = {}
    new_index: dict[str, list[int]] = {}
    for i, (n, t, a) in enumerate(order):
        if n in clones:
            for sid, _, _, tag in clones[n]:
                new_index.setdefault(n, []).append(len(new_tags))
                new_tags.append(tag)
                new_names.append(sid)
        elif n not in remove:
            old_to_new[i] = len(new_tags)
            new_tags.append(t)
            new_names.append(n)
    removed_names = [n for n in tmpl_names if n in remove]

    dn = re.search(r"<definedNames>(.*?)</definedNames>", wb_xml, re.S)
    dn_new = None
    if dn:
        parts: list[str] = []
        for dm in re.finditer(r"(<definedName\b[^>]*?>)(.*?)</definedName>|<definedName\b[^>]*?/>", dn.group(1), re.S):
            if dm.group(1) is None:
                parts.append(dm.group(0))
                continue
            opening, text = dm.group(1), dm.group(2)
            a = dict(_ATTR_RE.findall(opening))
            if "localSheetId" in a:
                idx = int(a["localSheetId"])
                owner = tmpl_names[idx] if idx < len(tmpl_names) else None
                if owner in clones:  # 견본에 걸린 이름(인쇄 제목 등)은 복제본마다 하나씩
                    for (sid, *_), ni in zip(clones[owner], new_index.get(owner, [])):
                        o2 = re.sub(r'localSheetId="\d+"', f'localSheetId="{ni}"', opening)
                        parts.append(f"{o2}{_name_ref(owner).sub(lambda _m: _quoted(sid), text)}</definedName>")
                    continue
                if idx not in old_to_new:
                    continue
                opening = re.sub(r'localSheetId="\d+"', f'localSheetId="{old_to_new[idx]}"', opening)
            for gone_name in removed_names:
                if _name_ref(gone_name).search(text):
                    warn(gone_name, a.get("name", ""), f"정의된 이름 {a.get('name')!r} 이 산출에서 빠진 시트 {gone_name!r} 를 가리켜 #REF! 가 된다")
            parts.append(f"{opening}{text}</definedName>")
        dn_new = "".join(parts)
    new_wb = wb_xml.replace(m.group(0), "<sheets>" + "".join(new_tags) + "</sheets>", 1)
    if dn:
        new_wb = new_wb.replace(dn.group(0), f"<definedNames>{dn_new}</definedNames>" if dn_new else "", 1)
    am = re.search(r'activeTab="(\d+)"', new_wb)
    if am:
        ai = int(am.group(1))
        new_wb = re.sub(r'activeTab="\d+"', f'activeTab="{old_to_new.get(ai, 0)}"', new_wb, count=1)
    new_wb = re.sub(r'\s+firstSheet="\d+"', "", new_wb)

    # ---- 지울 파트(빠지는 시트와 거기만 딸린 파트), 계산 순서(calcChain)
    tmpl_ts = {n: paths[n] for n in remove}
    cands: set[str] = set()
    for sp in tmpl_ts.values():
        gone.add(sp)
        rp = _rels_of(sp)
        if rp in raw:
            gone.add(rp)
            cands |= {_resolve_target(sp, a["Target"]) for _, a in _rel_tags(raw[rp].decode("utf-8-sig")) if a.get("TargetMode") != "External"}
    still = set()
    for name, data in raw.items():
        if name.endswith(".rels") and name not in gone:
            base = name.replace("/_rels/", "/")[: -len(".rels")]
            still |= {_resolve_target(base, a["Target"]) for _, a in _rel_tags(data.decode("utf-8-sig", "replace")) if a.get("TargetMode") != "External"}
    for c in cands - still:
        gone.add(c)
        if _rels_of(c) in raw:
            gone.add(_rels_of(c))
    for name in list(raw):
        if name.endswith("calcChain.xml"):
            gone.add(name)

    drop = {a["Id"] for _, a in _rel_tags(wb_rels) if _resolve_target("xl/workbook.xml", a["Target"]) in gone}
    for tag, a in _rel_tags(wb_rels):
        if a["Id"] in drop:
            wb_rels = wb_rels.replace(tag, "")
    typ_ws = f"{_REL_NS}/worksheet"
    adds = "".join(
        f'<Relationship Id="{rid}" Type="{typ_ws}" Target="worksheets/{new.rsplit("/", 1)[-1]}"/>'
        for cl in clones.values() for _, new, rid, _ in cl
    )
    wb_rels = wb_rels.replace("</Relationships>", adds + "</Relationships>")

    for g in gone:
        ov = _override(ct, g)
        if ov:
            ct = ct.replace(ov, "")
    ct = ct.replace("</Types>", "".join(ct_adds) + "</Types>")

    # 다른 시트의 수식이 빠진 시트를 가리키면 알린다
    for n, p in paths.items():
        if p in gone or n in remove or p not in raw:
            continue
        txt = raw[p].decode("utf-8-sig", "replace")
        for gone_name in removed_names:
            if any(_name_ref(gone_name).search(f) for f in re.findall(r"<f\b[^>]*>([^<]*)</f>", txt)):
                warn(n, gone_name, f"시트 {n!r} 의 수식이 산출에서 빠진 시트 {gone_name!r} 를 가리킨다 — #REF! 가 된다")

    app = raw.get("docProps/app.xml")
    if app is not None:
        raw["docProps/app.xml"] = _app_xml(app.decode("utf-8-sig"), new_names, lambda r: warn("", "docProps/app.xml", r))

    raw["xl/workbook.xml"] = new_wb.encode("utf-8")
    raw[wb_rels_path] = wb_rels.encode("utf-8")
    raw["[Content_Types].xml"] = ct.encode("utf-8")
    for g in gone:
        raw.pop(g, None)
    infos = [i for i in infos if i.filename not in gone]
    stamp = infos[0].date_time if infos else (1980, 1, 1, 0, 0, 0)
    for name in added:
        zi = zipfile.ZipInfo(name, date_time=stamp)
        zi.compress_type = zipfile.ZIP_DEFLATED
        infos.append(zi)

    # ---- 지도·작업본
    new_paths = {n: p for n, p in paths.items() if n not in remove}
    out_sheets: list[dict] = []
    plan_keys = {key for items in plan.values() for key, _ in items}  # 이름 검사에서 거부된 소절도 지도에 없으므로 뺀다(problem 으로 이미 알렸다)
    new_sections = {k: v for k, v in sections.items() if k not in plan_keys}
    for s in sheets:
        rn = norm(s["이름"])
        if s.get("반복") is True:
            for (key, sid), (_, path, _, _) in zip(accepted[rn], clones[rn]):
                cs = copy.deepcopy(s)
                cs.pop("반복", None)
                cs.pop("빼기", None)
                cs["이름"] = sid
                for f in cs.get("칸") or []:
                    if isinstance(f, dict) and f.get("형식"):
                        f["형식"] = str(f["형식"]).replace("{ID}", sid)
                out_sheets.append(cs)
                new_paths[sid] = path
                sec, subs = sections[key]
                sec = copy.deepcopy(sec)
                if any(isinstance(f, dict) and norm(str(f.get("항목", ""))) == "ID" for f in cs.get("칸") or []):
                    sec.fields.setdefault("ID", sid)
                new_sections[sid] = (sec, subs)
        elif rn not in remove:
            out_sheets.append(s)
    new_fmap = dict(fmap, 시트=out_sheets)
    return new_fmap, new_sections, infos, raw, new_paths, new_wb


def _app_xml(xml: str, names: list[str], warn_) -> str:
    """docProps/app.xml 의 시트 이름 목록을 새 시트 목록으로 맞춘다(이름 범위 표는 엑셀이 다시 만든다)."""
    hp = re.search(r"<HeadingPairs>.*?</HeadingPairs>", xml, re.S)
    tp = re.search(r"<TitlesOfParts>.*?</TitlesOfParts>", xml, re.S)
    if not hp or not tp:
        return xml
    first = re.search(r"<vt:variant><vt:lpstr>([^<]*)</vt:lpstr></vt:variant><vt:variant><vt:i4>\d+</vt:i4></vt:variant>", hp.group(0))
    if not first:
        warn_("docProps/app.xml 의 시트 목록 모양을 몰라 고치지 못했다(엑셀 열기에는 영향이 없다)")
        return xml
    heading = f'<HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>{first.group(1)}</vt:lpstr></vt:variant><vt:variant><vt:i4>{len(names)}</vt:i4></vt:variant></vt:vector></HeadingPairs>'
    titles = f'<TitlesOfParts><vt:vector size="{len(names)}" baseType="lpstr">' + "".join(f"<vt:lpstr>{escape(n)}</vt:lpstr>" for n in names) + "</vt:vector></TitlesOfParts>"
    return xml.replace(hp.group(0), heading, 1).replace(tp.group(0), titles, 1)
