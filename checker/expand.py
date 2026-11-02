"""표를 오른쪽으로 펼치는 열(지도 표 `펼침`, 이슈 #562).

Role 처럼 목록 하나가 가로 열이 되는 양식을 위한 일반 기능이다. 지도의 표에 `펼침` 을 두면 그 표의 오른쪽으로 목록 하나당 열
하나를 쓴다. 양식에 특정 글자를 박지 않는다 — 시트·표·열 이름과 열 문자는 모두 지도가 정한다.

```yaml
표:
  - 이름: 메뉴 배정
    ...
    md_전용: [Role]            # 선택. 작업본에만 있는 열(엑셀에 쓰지 않는다). `표시.열` 은 따로 적지 않아도 허용이다
    펼침:
      원본: {시트: Role 개요, 표: Role 개요, 열: Role ID}   # 열 순서·개수를 정하는 목록(같은 작업본의 다른 표)
      시작_열: G
      끝_열: BB                # 목록이 이 범위를 넘으면 산출을 거부한다(양식에 열이 모자람)
      머리글: {3: Role ID, 4: Description}   # 행 번호: 원본 표의 열 이름. 펼친 열마다 그 행에 원본 값을 쓴다
      표시: {열: Role, 값: O}   # 선택. 이 표의 `Role` 열(쉼표 목록)에 든 항목의 열에 O 를 쓴다
```

- 펼친 열의 순서는 원본 표의 행 순서다. 원본 `열` 값이 빈 행은 건너뛰고, 같은 값이 둘이면 거부한다.
- `머리글` 행은 표의 `시작_행` 보다 위여야 하고(표 `머리글_행` 과 같은 행도 된다), 펼침 범위(`시작_열`~`끝_열`)는 표 `열` 의 열 문자와 겹치지 않아야 한다.
- 표시 열의 값이 원본 목록에 없으면 양식 밖 값이다 — 산출도 저장(훅)·PR(form_columns)도 같은 함수(`unknown_marks`)로 멈춘다.
- 데이터 행 없이 머리글만 펼치는 표(`표시` 없음)도 된다. 수식 행(=COUNTA 등)은 건드리지 않는다.
- 모듈 묶음 같은 병합 머리글 행은 다루지 않는다(`머리글` 에 적지 않은 행은 그대로).
"""
from __future__ import annotations

import re

from checker.export import _clean, _parse_table, col2n, n2col, norm

_COL = re.compile(r"[A-Z]{1,3}")
_KEYS = {"원본", "시작_열", "끝_열", "머리글", "표시"}
MAX_SHOWN = 30  # 사유 문장에 싣는 허용 값 수


def spec_of(t: dict) -> dict | None:
    ex = t.get("펼침") if isinstance(t, dict) else None
    return ex if isinstance(ex, dict) else None


def mark_column(t: dict) -> str | None:
    """`표시.열` 이름(정규화). 없으면 None."""
    ex = spec_of(t)
    mk = ex.get("표시") if ex else None
    if isinstance(mk, dict) and isinstance(mk.get("열"), str) and mk["열"].strip():
        return norm(mk["열"])
    return None


def extra_names(t: dict) -> list[str]:
    """엑셀 열이 아니라 작업본에만 있는 열 이름들: `md_전용` + `표시.열`."""
    names = [norm(str(x)) for x in (t.get("md_전용") or [])] if isinstance(t.get("md_전용"), list) else []
    mk = mark_column(t)
    if mk and mk not in names:
        names.append(mk)
    return names


def map_problems(t: dict) -> list[str]:
    """표 하나의 `펼침`·`md_전용` 오류(지도 오류)."""
    out: list[str] = []
    if t.get("md_전용") is not None and not (isinstance(t["md_전용"], list) and all(isinstance(x, str) for x in t["md_전용"])):
        out.append("`md_전용` 은 열 이름 목록이어야 한다")
    if "펼침" not in t:
        return out
    ex = t["펼침"]
    if not isinstance(ex, dict):
        return out + ["`펼침` 은 사전이어야 한다"]
    stray = [str(k) for k in ex if k not in _KEYS]
    if stray:
        out.append(f"`펼침` 에 모르는 키가 있다: {', '.join(stray)}(쓸 수 있는 키: {', '.join(sorted(_KEYS))})")
    src = ex.get("원본")
    if not (isinstance(src, dict) and all(isinstance(src.get(k), str) and src[k].strip() for k in ("시트", "표", "열"))):
        out.append("`펼침.원본` 은 {시트: 이름, 표: 이름, 열: 열 이름} 이어야 한다")
    cols = [ex.get("시작_열"), ex.get("끝_열")]
    if not all(isinstance(c, str) and _COL.fullmatch(c) for c in cols):
        out.append("`펼침.시작_열`·`펼침.끝_열` 은 열 문자(A~ZZZ)여야 한다")
        c1 = c2 = None
    else:
        c1, c2 = col2n(cols[0]), col2n(cols[1])
        if c1 > c2:
            out.append("`펼침.시작_열` 이 `끝_열` 보다 오른쪽이다")
    head = ex.get("머리글")
    if not (isinstance(head, dict) and head and all(
        isinstance(k, int) and not isinstance(k, bool) and k > 0 and isinstance(v, str) and v.strip() for k, v in head.items()
    )):
        out.append("`펼침.머리글` 은 {행 번호: 원본 표의 열 이름} 사전이어야 한다(비어 있으면 안 된다)")
    else:
        first = t.get("시작_행")
        if isinstance(first, int) and any(k >= first for k in head):
            out.append(f"`펼침.머리글` 의 행 번호는 표의 `시작_행`({first}) 보다 위여야 한다")
    mk = ex.get("표시")
    if mk is not None:
        if not (isinstance(mk, dict) and set(mk) == {"열", "값"} and all(isinstance(v, str) and v.strip() for v in mk.values())):
            out.append("`펼침.표시` 는 {열: 작업본 열 이름, 값: 칸에 쓸 글자} 이어야 한다")
        else:
            if norm(mk["열"]) in {norm(str(k)) for k in (t.get("열") or {})}:
                out.append("`펼침.표시.열` 은 표 `열` 에 없는 작업본 전용 열 이름이어야 한다")
            if t.get("여러_줄") == "행":
                out.append("`펼침.표시` 는 `여러_줄: 행` 과 같이 쓸 수 없다(행 번호가 어긋난다)")
    if c1 is not None and isinstance(t.get("열"), dict):
        for name, letter in t["열"].items():
            if isinstance(letter, str) and _COL.fullmatch(letter) and c1 <= col2n(letter) <= c2:
                out.append(f"`펼침` 범위 {cols[0]}~{cols[1]} 가 표 `열` 의 {name!r}({letter})와 겹친다")
    return out


def owned_rects(t: dict, last_row: int | None = None) -> list[tuple[str, tuple[int, int, int, int]]]:
    """펼침이 맡은 영역 [(설명, (열1, 행1, 열2, 행2))]. 지도 오류 검사(`비우기`·`서식_지우기` 겹침)가 쓴다. 형식이 틀리면 빈 목록."""
    ex = spec_of(t)
    if ex is None or map_problems(t):
        return []
    c1, c2 = col2n(ex["시작_열"]), col2n(ex["끝_열"])
    out = [(f"표 {t.get('이름')!r} 의 펼친 머리글 {r}행", (c1, r, c2, r)) for r in ex["머리글"]]
    if ex.get("표시") and isinstance(t.get("시작_행"), int):
        end = t["시작_행"] + t["최대_행"] - 1 if isinstance(t.get("최대_행"), int) else (last_row or 1048576)
        out.append((f"표 {t.get('이름')!r} 의 펼친 표시 열", (c1, t["시작_행"], c2, end)))
    return out


def fill_ranges(t: dict, start: int, last: int) -> list[str]:
    """빈 양식·산출이 값 없이 두면 비우는 범위: 머리글 행과(표시가 있으면) 데이터 영역."""
    ex = spec_of(t)
    if ex is None or map_problems(t):
        return []
    s, e = ex["시작_열"], ex["끝_열"]
    out = [f"{s}{r}:{e}{r}" for r in sorted(ex["머리글"])]
    if ex.get("표시") and last >= start:
        out.append(f"{s}{start}:{e}{last}")
    return out


def source_rows(sections: dict, src: dict) -> list[dict[str, str]]:
    """같은 작업본 양식의 원본 표 → [{열 이름: 값}]. 시트·표가 작업본에 없거나 비었으면 빈 목록. 표 구조가 깨졌으면 ExportError."""
    sheet = sections.get(norm(src["시트"]))
    if sheet is None:
        return []
    body = sheet[1].get(norm(src["표"]))
    if not body:
        return []
    parsed = _parse_table(body, f"{src['시트']} · {src['표']}")
    if not parsed:
        return []
    header, rows, _ = parsed
    return [{h: _clean(v) for h, v in zip(header, r)} for r in rows]


def keys_of(sections: dict, ex: dict) -> list[str]:
    """펼친 열의 순서대로 원본 `열` 값(빈 값은 건너뛴다)."""
    key = norm(ex["원본"]["열"])
    return [r[key] for r in source_rows(sections, ex["원본"]) if r.get(key)]


def split_values(text: str) -> list[str]:
    """표시 열 한 칸의 값을 쉼표·줄바꿈(`<br>`)으로 나눈다."""
    return [x.strip() for x in re.split(r"[,\n]|<br\s*/?>", text or "", flags=re.I) if x.strip()]


def unknown_marks(sections: dict, t: dict, header: list[str], rows: list[list[str]]) -> tuple[str, list[str], list[str]] | None:
    """표시 열의 값 가운데 원본 목록에 없는 것. (표시 열 이름, 없는 값들, 허용 값들) — 없으면 None.

    산출(`export.spec_offenders`)과 저장·PR 검사(form_columns)가 같이 쓴다.
    """
    ex, mk = spec_of(t), mark_column(t)
    if ex is None or mk is None or mk not in header or map_problems(t):
        return None
    allowed = keys_of(sections, ex)
    i = header.index(mk)
    bad = list(dict.fromkeys(v for r in rows for v in split_values(r[i]) if v not in allowed))
    return (mk, bad, allowed) if bad else None


def shown(allowed: list[str]) -> list[str]:
    return allowed if len(allowed) <= MAX_SHOWN else allowed[:MAX_SHOWN] + [f"… (전체 {len(allowed)}개)"]


def write(form, sname, tname, t, sections, extras: list[str], start: int, last_row: int, ed, put, problem) -> None:
    """펼친 머리글과 표시를 쓴다. `extras[i]` 는 i 번째 데이터 행의 표시 열 값(없으면 빈 글자)이다."""
    ex = spec_of(t)
    src = ex["원본"]
    keys = keys_of(sections, ex)
    dup = [k for k in dict.fromkeys(keys) if keys.count(k) > 1]
    if dup:
        problem(sname, tname, f"펼칠 목록({src['표']} 의 {src['열']})에 같은 값이 둘 이상이다: {', '.join(dup)}")
        return
    c1, c2 = col2n(ex["시작_열"]), col2n(ex["끝_열"])
    cap = c2 - c1 + 1
    if len(keys) > cap:
        problem(sname, tname, f"펼칠 목록({src['표']} 의 {src['열']})이 {len(keys)}개라 양식의 {ex['시작_열']}~{ex['끝_열']}({cap}열)을 넘는다 — 양식에 열을 더하거나 목록을 줄인다")
        return
    rows = source_rows(sections, src)
    keycol = norm(src["열"])
    items = [r for r in rows if r.get(keycol)]
    head = {int(r): norm(c) for r, c in ex["머리글"].items()}
    for r in head:
        ed.clear_range(f"{n2col(c1)}{r}", f"{n2col(c2)}{r}")
    for r, cname in head.items():
        for i, item in enumerate(items):
            if item.get(cname):  # 원본 표에 그 열이 없거나 값이 비면 빈칸(빠진 열은 허용이다)
                put(tname, f"{n2col(c1 + i)}{r}", re.sub(r"<br\s*/?>", "\n", item[cname], flags=re.I), header=cname)
    mk = ex.get("표시")
    if not mk:
        return
    ed.clear_range(f"{n2col(c1)}{start}", f"{n2col(c2)}{max(last_row, start)}")
    for i, text in enumerate(extras):
        for v in split_values(text):
            if v not in keys:  # 위 unknown_marks 가 먼저 멈추지만 안전망
                problem(sname, tname, f"{i + 1}번째 행의 {mk['열']} 값 {v!r} 이 펼친 목록에 없다")
                continue
            put(tname, f"{n2col(c1 + keys.index(v))}{start + i}", str(mk["값"]), header=str(mk["열"]))
