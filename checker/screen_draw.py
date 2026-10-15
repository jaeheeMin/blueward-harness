"""Spec 의 화면 구성을 개발사양서 화면 시트에 셀·병합으로 그린다(#335, PR C2).

Spec 작업본 `## 양식 항목` 의 `### <양식> · <시트>` 아래에 `#### <화면 이름> 그림` 절을 두면, 산출(`checker.export`)이
지도 시트 항목의 `화면:` 에 적힌 영역 안에 조회 조건·버튼·결과 표를 그린다. 영역·칸 수·색은 코드가 아니라 지도(데이터)가 정한다.

지도(시트 항목)
    화면:
      - 이름: 화면 1                 # md 의 `#### 화면 1 그림` 과 맞춘다
        영역: C7:S14                 # 이 안에만 그린다. 넘치면 자르지 않고 산출을 거절한다
        칸_수: {라벨: 2, 입력: 3, 버튼: 2, 열: 2, 간격: 1, 빈_행: 2}   # 선택. 적은 것만 덮어쓴다(아래가 기본값)
        스타일:                       # 선택. 이름별로 통째로 바꾼다(키는 cell_style 의 스타일 정의)
          머리글: {채우기: 1F4E78, 글꼴_색: FFFFFF, 굵게: true, 테두리: 얇게, 가로: 가운데}

작업본(md)
    #### 화면 1 그림
    ##### 조회 조건      | 이름 | 필수 |  (필수 열은 생략 가능, Y 면 라벨 뒤에 ` *`)
    ##### 버튼           | 이름 |
    ##### 결과 표        | 열 |
각 소절은 없으면 건너뛴다. `#### 화면 N 그림` 절이 없으면 그 영역은 그리지 않고 템플릿 그대로 둔다.

배치: 영역 왼쪽 위부터. 조회 조건은 (라벨 + 입력) 묶음을 간격 한 칸씩 띄워 한 줄에 들어가는 만큼 놓고 넘치면 다음 줄로,
조건 뒤에 빈 줄 한 줄. 버튼은 한 줄에 나란히(간격 한 칸). 결과 표는 열마다 머리글 칸과 빈 행 `빈_행` 줄(이어 붙음).
"""
from __future__ import annotations

import re
from typing import NamedTuple

from checker.blank_template import RangeError, _hit, parse_range
from checker.cell_style import StylesXml, merge_range, style_range, validate_style
from checker.export import ExportError, SheetXml, _clean, _parse_table, col2n, n2col, norm, split_ref

DEFAULT_COUNTS = {"라벨": 2, "입력": 3, "버튼": 2, "열": 2, "간격": 1, "빈_행": 2}
_COUNT_MIN = {"라벨": 1, "입력": 1, "버튼": 1, "열": 1, "간격": 0, "빈_행": 0}
DEFAULT_STYLES = {
    "라벨": {"채우기": "D9E1F2", "테두리": "얇게", "굵게": True, "세로": "가운데"},
    "입력": {"채우기": "FFFFFF", "테두리": "얇게"},
    "버튼": {"채우기": "D9D9D9", "테두리": "얇게", "가로": "가운데", "세로": "가운데"},
    "머리글": {"채우기": "1F4E78", "글꼴_색": "FFFFFF", "굵게": True, "테두리": "얇게", "가로": "가운데"},
    "행": {"테두리": "얇게"},
}
_ITEM_KEYS = ("이름", "영역", "칸_수", "스타일", "설명")
# 소절 이름 → 허용하는 표 머리글(앞의 것이 기본). 조회 조건의 `필수` 열은 생략할 수 있다.
SECTIONS: dict[str, list[list[str]]] = {
    "조회 조건": [["이름", "필수"], ["이름"]],
    "버튼": [["이름"]],
    "결과 표": [["열"]],
}


def md_name(item: dict) -> str:
    """작업본 `####` 소제목: `<화면 이름> 그림`."""
    return f"{item['이름']} 그림"


def items(smap: dict) -> list[dict]:
    """시트 지도의 `화면:` → 기본값을 채운 항목들. 지도 검증(`map_problems`)을 통과한 지도만 넘긴다."""
    out = []
    for it in smap.get("화면") or []:
        counts = {**DEFAULT_COUNTS, **{norm(k): v for k, v in (it.get("칸_수") or {}).items()}}
        styles = {**DEFAULT_STYLES, **{norm(k): v for k, v in (it.get("스타일") or {}).items()}}
        out.append({"이름": norm(it["이름"]), "영역": str(it["영역"]).strip(), "칸_수": counts, "스타일": styles})
    return out


# ---------------------------------------------------------------- 지도 검증

def _owned(s: dict) -> list[tuple[str, tuple[int, int, int, int]]]:
    """지도가 이미 맡은 영역(칸·서술 위치, 표 데이터 영역, 유지). 화면 영역은 여기와 겹치면 안 된다."""
    owned: list[tuple[str, tuple[int, int, int, int]]] = []
    for x in s.get("유지") or []:
        try:
            owned.append((f"유지 {x}", parse_range(x)))
        except (RangeError, TypeError):
            pass
    for kind in ("칸", "서술"):
        for it in s.get(kind) or []:
            if isinstance(it, dict) and it.get("위치"):
                try:
                    owned.append((f"{kind} {it.get('항목', it.get('이름'))!r} {it['위치']}", parse_range(it["위치"])))
                except RangeError:
                    pass
    for t in s.get("표") or []:
        if not isinstance(t, dict) or not isinstance(t.get("열"), dict) or not isinstance(t.get("시작_행"), int):
            continue
        start = t["시작_행"]
        end = start + t["최대_행"] - 1 if isinstance(t.get("최대_행"), int) else 1048576
        for col in t["열"].values():
            if isinstance(col, str) and re.fullmatch(r"[A-Z]{1,3}", col):
                n = col2n(col)
                owned.append((f"표 {t.get('이름')!r} 의 {col} 열", (n, start, n, end)))
    return owned


def map_problems(fmap: dict) -> list[tuple[str, str]]:
    """`화면:` 의 오류 → [(종류, 사유)]. 종류: range / map. `blank_template.map_problems` 가 불러 산출·form_columns 가 같이 쓴다."""
    out: list[tuple[str, str]] = []
    for s in fmap.get("시트") or []:
        if not isinstance(s, dict) or s.get("화면") is None:
            continue
        sn = s.get("이름")
        v = s["화면"]
        if not isinstance(v, list):
            out.append(("map", f"시트 {sn!r} 의 `화면`(목록이어야 한다)"))
            continue
        owned = _owned(s)
        reserved = {norm(str(x.get("이름"))) for k in ("표", "서술") for x in s.get(k) or [] if isinstance(x, dict)}
        seen: set[str] = set()
        rects: list[tuple[str, tuple[int, int, int, int]]] = []
        for it in v:
            if not isinstance(it, dict) or not isinstance(it.get("이름"), str) or not it["이름"].strip():
                out.append(("map", f"시트 {sn!r} 의 `화면` 항목에는 문자열 `이름` 이 있어야 한다"))
                continue
            name = norm(it["이름"])
            where = f"시트 {sn!r} 화면 {name!r}"
            if name in seen:
                out.append(("map", f"{where}: 같은 이름의 화면이 둘 이상이다"))
            if f"{name} 그림" in reserved:
                out.append(("map", f"{where}: `{name} 그림` 은 같은 시트의 표·서술 이름과 같아 구분할 수 없다"))
            for k in it:
                if k not in _ITEM_KEYS:
                    out.append(("map", f"{where}: 모르는 키 {k!r} — 가능한 키: {', '.join(_ITEM_KEYS)}"))
            rect = None
            if it.get("영역") is None:
                out.append(("map", f"{where}: `영역` 이 없다"))
            else:
                try:
                    rect = parse_range(it["영역"])
                except RangeError as e:
                    out.append(("range", f"{where} 의 `영역`: {e.reason}"))
            seen.add(name)
            counts = it.get("칸_수")
            if counts is not None:
                if not isinstance(counts, dict):
                    out.append(("map", f"{where}: `칸_수` 는 키: 숫자 목록이어야 한다"))
                else:
                    for k, n in counts.items():
                        if norm(str(k)) not in _COUNT_MIN:
                            out.append(("map", f"{where}: 칸_수 키 {k!r} 는 모른다 — 가능한 키: {', '.join(_COUNT_MIN)}"))
                        elif isinstance(n, bool) or not isinstance(n, int) or n < _COUNT_MIN[norm(str(k))]:
                            out.append(("map", f"{where}: 칸_수 {k} 는 {_COUNT_MIN[norm(str(k))]} 이상의 정수여야 한다(받은 값 {n!r})"))
            styles = it.get("스타일")
            if styles is not None:
                if not isinstance(styles, dict):
                    out.append(("map", f"{where}: `스타일` 은 이름: 스타일 정의 목록이어야 한다"))
                else:
                    for k, defn in styles.items():
                        if norm(str(k)) not in DEFAULT_STYLES:
                            out.append(("map", f"{where}: 스타일 이름 {k!r} 는 모른다 — 가능한 이름: {', '.join(DEFAULT_STYLES)}"))
                        else:
                            out += [("map", f"{where}: 스타일 {k}: {why}") for why in validate_style(defn)]
            if rect is not None:
                for label, orect in owned:
                    if _hit(rect, orect):
                        out.append(("map", f"{where} 영역 {it['영역']} 가 {label} 와 겹친다 — 화면 영역은 지도가 맡은 칸·표·서술·유지 범위 밖이어야 한다"))
                for other, orect in rects:
                    if _hit(rect, orect):
                        out.append(("map", f"{where} 영역 {it['영역']} 가 화면 {other!r} 영역과 겹친다"))
                rects.append((name, rect))
    return out


# ---------------------------------------------------------------- 작업본(md) 읽기

def parse_body(body: list[str], where: str) -> tuple[dict[str, list[str]], list[str]]:
    """`#### … 그림` 본문 → ({`##### 소절`: 줄들}, 표·소절 밖 글 줄들)."""
    secs: dict[str, list[str]] = {}
    stray: list[str] = []
    cur: str | None = None
    for line in body:
        m = re.match(r"^#####\s+(.+?)\s*$", line)
        if m:
            cur = norm(m.group(1))
            if cur in secs:
                raise ExportError(f"{where}: `##### {cur}` 이 두 번 나온다")
            secs[cur] = []
        elif not line.strip():
            continue
        elif cur is None or not line.lstrip().startswith("|"):
            stray.append(line.strip())
        else:
            secs[cur].append(line)
    return secs, stray


def _tables(body: list[str], where: str):
    secs, stray = parse_body(body, where)
    return {name: _parse_table(lines, f"{where} · {name}") for name, lines in secs.items()}, stray


def offenders(item: dict, body: list[str]) -> list[tuple[str, str, list[str]]]:
    """한 `#### … 그림` 절의 양식 밖 항목 → [(분류, 이름, 허용 이름들)]. 구조가 깨졌으면 ExportError."""
    where = md_name(item)
    tables, stray = _tables(body, where)
    out: list[tuple[str, str, list[str]]] = []
    for line in stray[:1]:
        out.append(("화면 그림의 표 밖 글", f"{where}: {line[:30]}", [f"##### {s} 아래 표" for s in SECTIONS]))
    for name, parsed in tables.items():
        if name not in SECTIONS:
            out.append(("화면 소절", f"{where} · {name}", list(SECTIONS)))
            continue
        ok = [" | ".join(h) for h in SECTIONS[name]]
        if parsed is None:
            out.append(("화면 표 머리", f"{where} · {name}: (표 없음)", ok))
        elif parsed[0] not in SECTIONS[name]:
            out.append(("화면 표 머리", f"{where} · {name}: {' | '.join(parsed[0])}", ok))
    return out


# ---------------------------------------------------------------- 배치

class Box(NamedTuple):
    col: int
    row: int
    width: int
    kind: str  # 라벨 입력 버튼 머리글 행
    text: str


def layout(item: dict, conds: list[tuple[str, bool]], buttons: list[str], cols: list[str]) -> tuple[list[Box], list[str]]:
    """(그릴 칸들, 영역을 넘친 항목들). 넘친 항목이 있으면 그리지 않고 거절한다."""
    c0, r0, c1, r1 = parse_range(item["영역"])
    n = item["칸_수"]
    label_w, field_w, gap, btn_w, col_w, empty = (n[k] for k in ("라벨", "입력", "간격", "버튼", "열", "빈_행"))
    boxes: list[Box] = []
    over: list[str] = []

    def put(col: int, row: int, width: int, kind: str, text: str, what: str) -> None:
        if col + width - 1 > c1:
            what += "(열)"
        elif row > r1:
            what += "(행)"
        else:
            boxes.append(Box(col, row, width, kind, text))
            return
        if what not in over:
            over.append(what)

    row = r0
    if conds:
        pair = label_w + field_w + gap
        per = (c1 - c0 + 1 + gap) // pair  # 한 줄에 들어가는 묶음 수
        last = r0
        for i, (name, required) in enumerate(conds):
            what = f"조회 조건 '{name}'"
            if per < 1:
                over.append(what + "(열)")
                continue
            line = r0 + i // per
            col = c0 + (i % per) * pair
            last = max(last, line)
            put(col, line, label_w, "라벨", f"{name} *" if required else name, what)
            put(col + label_w, line, field_w, "입력", "", what)
        row = last + 2  # 조건 뒤 빈 줄 하나
    for i, name in enumerate(buttons):
        put(c0 + i * (btn_w + gap), row, btn_w, "버튼", name, f"버튼 '{name}'")
    if buttons:
        row += 1
    for i, name in enumerate(cols):
        what = f"결과 표 '{name}'"
        put(c0 + i * col_w, row, col_w, "머리글", name, what)
        for k in range(1, empty + 1):
            put(c0 + i * col_w, row + k, col_w, "행", "", what)
    return boxes, over


def _read(item: dict, body: list[str], sname: str, problem) -> tuple[list[tuple[str, bool]], list[str], list[str]] | None:
    """md 소절을 읽는다. 값 문제는 problem 으로 알리고 None."""
    where = md_name(item)
    off = offenders(item, body)
    if off:  # 보통 spec_offenders 가 먼저 막지만 단독으로 불러도 조용히 넘기지 않는다
        raise ExportError(f"{sname} 시트의 {where} 에 양식 밖 항목이 있다: " + "; ".join(f"{k} {n!r}" for k, n, _ in off), sheet=sname, item=where)
    tables, _ = _tables(body, where)
    bad = False
    conds: list[tuple[str, bool]] = []
    buttons: list[str] = []
    cols: list[str] = []
    for sec, parsed in tables.items():
        header, rows, wrong = parsed
        for n, cnt in wrong:
            problem(sname, where, f"{sec} 표 {n}번째 행의 셀 수({cnt})가 머리글({len(header)})과 다르다")
            bad = True
        for r in rows:
            name = _clean(r[0])
            if not name:
                continue
            if sec == "조회 조건":
                flag = _clean(r[1]).upper() if len(r) > 1 else ""
                if flag not in ("Y", "N", ""):
                    problem(sname, where, f"조회 조건 '{name}' 의 필수 값 {r[1]!r} 는 Y 또는 N(빈칸)이어야 한다")
                    bad = True
                conds.append((name, flag == "Y"))
            elif sec == "버튼":
                buttons.append(name)
            else:
                cols.append(name)
    return None if bad else (conds, buttons, cols)


def draw(ed: SheetXml, styles: StylesXml, item: dict, body: list[str], sname: str, problem) -> int:
    """한 화면을 그린다. 그린 칸 수를 낸다(거절하면 0). 영역을 넘치거나 영역 안에 값이 있으면 쓰지 않고 problem 으로 알린다."""
    where = md_name(item)
    read = _read(item, body, sname, problem)
    if read is None:
        return 0
    boxes, over = layout(item, *read)
    if over:
        problem(sname, where, (
            f"{where} 이 영역 {item['영역']} 를 넘는다 — 넘친 항목: {', '.join(over[:12])}{' …' if len(over) > 12 else ''}. "
            "영역을 넓히거나 항목을 줄이거나 지도의 `칸_수` 를 줄인다(자르지 않는다)"
        ))
        return 0
    c0, r0, c1, r1 = parse_range(item["영역"])
    taken = [r for r in ed.valued_refs() if c0 <= col2n(split_ref(r)[0]) <= c1 and r0 <= split_ref(r)[1] <= r1]
    if taken and boxes:
        problem(sname, where, (
            f"영역 {item['영역']} 안에 이미 값이 있다({', '.join(taken[:5])}{' …' if len(taken) > 5 else ''}) — "
            "견본이 남은 자리에는 그리지 않는다. 지도 `비우기` 로 지운 빈 양식을 템플릿으로 쓴다"
        ))
        return 0
    saved = (ed._max_row, ed._max_col)  # 글자 쓰기가 자동 필터 범위를 늘리지 않게(dimension 은 set_style 이 넓힌다)
    try:
        for b in boxes:
            a, z = f"{n2col(b.col)}{b.row}", f"{n2col(b.col + b.width - 1)}{b.row}"
            if b.text:
                ed.set(a, b.text)
            style_range(ed, styles, a, z, item["스타일"][b.kind], sname)
            if b.width > 1:
                merge_range(ed, a, z, sname)
    except ExportError as e:
        raise ExportError(f"{where}: {e.reason}", sheet=sname, item=where) from None
    finally:
        ed._max_row, ed._max_col = saved
    return len(boxes)
