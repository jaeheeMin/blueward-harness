"""Spec 의 화면 구성을 개발사양서 화면 시트에 셀·병합으로 그린다(#335, PR C2).

Spec 작업본 `## 양식 항목` 의 `### <양식> · <시트>` 아래에 `#### <화면 이름> 그림` 절을 두면, 산출(`checker.export`)이
지도 시트 항목의 `화면:` 에 적힌 영역 안에 필터 바·액션·결과 테이블을 그린다(SAP Fiori List Report 의 스마트 필터 바, 테이블 위
툴바의 액션, 테이블). 영역·칸 수·색은 코드가 아니라 지도(데이터)가 정한다.

지도(시트 항목)
    화면:
      - 이름: 화면 1                 # md 의 `#### 화면 1 그림` 과 맞춘다
        영역: C7:S14                 # 이 안에만 그린다. 넘치면 자르지 않고 산출을 거절한다
        칸_수: {라벨: 2, 입력: 3, 액션: 2, 열: 2, 간격: 1, 빈_행: 2}   # 선택. 적은 것만 덮어쓴다(아래가 기본값)
        스타일:                       # 선택. 이름(라벨·입력·액션·머리글·행)별로 통째로 바꾼다(cell_style 의 스타일 정의)
          머리글: {채우기: 1F4E78, 글꼴_색: FFFFFF, 굵게: true, 테두리: 얇게, 가로: 가운데}

작업본(md)
    #### 화면 1 그림
    | 항목 | 값 |            (선택) `조회 | 자동` 또는 `조회 | Go`. 생략하면 자동
    ##### 필터 바       | 이름 | 필수 |  (필수 열은 생략 가능, Y 면 라벨 뒤에 ` *`)
    ##### 액션          | 이름 |
    ##### 결과 테이블    | 열 |
각 소절은 없으면 건너뛴다. `#### 화면 N 그림` 절이 없으면 그 영역은 그리지 않고 템플릿 그대로 둔다.

지난 판 비교(#347): 산출은 origin/main 의 같은 Spec 과 그림 절을 비교해(`screen_diff`) 추가·수정·삭제를 번호와 표시 스타일(`추가`·`수정`·`삭제`, 상자 스타일 위에
덮어쓴다)로 그리고, 지도 `변경: {시작_행, 최대_행, 열: {번호, 구분, 대상, 내용}}` 의 변경 내용 표를 채운다. 지난 판을 못 읽으면 `export` 가 검사 불능으로 멈춘다.

배치: 영역 왼쪽 위부터. 필터 바는 (라벨 + 입력) 묶음을 간격 한 칸씩 띄워 한 줄에 들어가는 만큼 놓고 넘치면 다음 줄로,
뒤에 빈 줄 한 줄. `조회: Go` 면 필터 바 마지막 줄의 영역 오른쪽 끝에 `Go` 액션을 놓고(자리가 없으면 다음 줄 오른쪽 끝), 그 뒤에 빈 줄 한 줄.
액션은 결과 테이블 머리글 바로 윗줄(테이블 툴바)에 결과 테이블의 오른쪽 끝에 맞춰 오른쪽 정렬한다(간격 한 칸). 액션이 테이블보다 넓어 영역 왼쪽을
넘으면 영역 오른쪽 끝 기준으로 바꾼다. 결과 테이블이 없으면 영역 오른쪽 끝 기준으로 그 자리(빈 줄 다음 줄)에 둔다.
결과 테이블은 열마다 머리글 칸과 빈 행 `빈_행` 줄(이어 붙음).
"""
from __future__ import annotations

import re
from typing import NamedTuple

from checker.blank_template import RangeError, _hit, parse_range
from checker import screen_diff
from checker.cell_style import StylesXml, merge_range, style_range, validate_style
from checker.export import ExportError, SheetXml, _clean, _parse_table, col2n, is_srs_map, n2col, norm, split_ref

DEFAULT_COUNTS = {"라벨": 2, "입력": 3, "액션": 2, "열": 2, "간격": 1, "빈_행": 2}
_COUNT_MIN = {"라벨": 1, "입력": 1, "액션": 1, "열": 1, "간격": 0, "빈_행": 0}
DEFAULT_STYLES = {
    "라벨": {"채우기": "D9E1F2", "테두리": "얇게", "굵게": True, "세로": "가운데"},
    "입력": {"채우기": "FFFFFF", "테두리": "얇게"},
    "액션": {"채우기": "D9D9D9", "테두리": "얇게", "가로": "가운데", "세로": "가운데"},
    "머리글": {"채우기": "1F4E78", "글꼴_색": "FFFFFF", "굵게": True, "테두리": "얇게", "가로": "가운데"},
    "행": {"테두리": "얇게"},
}
# 지난 판과 달라진 항목의 표시(#347). 기존 상자 스타일 위에 덮어쓰는 겹침이다(최종 = {**상자 스타일, **표시 스타일}).
DEFAULT_MARK_STYLES = {
    "추가": {"채우기": "FFFF00"},
    "수정": {"채우기": "FFFF00"},
    "삭제": {"채우기": "D9D9D9", "글꼴_색": "808080", "취소선": True},
}
STYLE_NAMES = (*DEFAULT_STYLES, *DEFAULT_MARK_STYLES)
_ITEM_KEYS = ("이름", "영역", "칸_수", "스타일", "설명", "캡처", "변경")
_CAPTURE_KEYS = ("영역", "설명")
_CHANGE_KEYS = ("시작_행", "최대_행", "열")
CHANGE_COLS = ("번호", "구분", "대상", "내용")
# 소절 이름 → 허용하는 표 머리글(앞의 것이 기본). 필터 바의 `필수` 열은 생략할 수 있다.
SECTIONS: dict[str, list[list[str]]] = {
    "필터 바": [["이름", "필수"], ["이름"]],
    "액션": [["이름"]],
    "결과 테이블": [["열"]],
}
# `#### … 그림` 바로 아래 `| 항목 | 값 |` 표의 키 → 허용 값(앞의 것이 기본). 조회: 자동(live, 필터를 바꾸면 바로 조회) / Go(manual, Go 버튼).
SETTINGS: dict[str, list[str]] = {"조회": ["자동", "Go"]}
SETTINGS_HEADER = ["항목", "값"]


def md_name(item: dict) -> str:
    """작업본 `####` 소제목: `<화면 이름> 그림`."""
    return f"{item['이름']} 그림"


def items(smap: dict) -> list[dict]:
    """시트 지도의 `화면:` → 기본값을 채운 항목들. 지도 검증(`map_problems`)을 통과한 지도만 넘긴다."""
    out = []
    for it in smap.get("화면") or []:
        counts = {**DEFAULT_COUNTS, **{norm(k): v for k, v in (it.get("칸_수") or {}).items()}}
        styles = {**DEFAULT_STYLES, **DEFAULT_MARK_STYLES, **{norm(k): v for k, v in (it.get("스타일") or {}).items()}}
        cap = it.get("캡처")
        capture = None
        if cap is not None:  # 영역을 생략하면 그 화면의 영역을 쓴다
            capture = {"영역": str(cap.get("영역") or it["영역"]).strip(), "설명": str(cap["설명"]).strip()}
        chg = it.get("변경")
        change = None
        if chg is not None:
            change = {"시작_행": chg["시작_행"], "최대_행": chg["최대_행"], "열": {norm(k): str(v).strip() for k, v in chg["열"].items()}}
        out.append({"이름": norm(it["이름"]), "영역": str(it["영역"]).strip(), "칸_수": counts, "스타일": styles, "캡처": capture, "변경": change})
    return out


def capture_name(item: dict) -> str:
    """작업본 `####` 소제목: `<화면 이름> 캡처`."""
    return f"{item['이름']} 캡처"


# ---------------------------------------------------------------- 지도 검증

def _owned(s: dict) -> tuple[list[tuple[str, tuple[int, int, int, int]]], list[tuple[str, str]]]:
    """(지도가 이미 맡은 영역, 지도 오류). 맡은 영역: 칸·서술 위치, 표 데이터 영역, 유지. 화면 영역은 여기와 겹치면 안 된다."""
    owned: list[tuple[str, tuple[int, int, int, int]]] = []
    bad: list[tuple[str, str]] = []
    lists: dict[str, list] = {}
    for key in ("유지", "칸", "서술", "표"):
        v = s.get(key)
        if v is None:
            lists[key] = []
        elif isinstance(v, list):
            lists[key] = v
        else:
            lists[key] = []
            bad.append(("map", f"시트 {s.get('이름')!r} 의 `{key}`(목록이어야 한다)"))
    for x in lists["유지"]:
        try:
            owned.append((f"유지 {x}", parse_range(x)))
        except (RangeError, TypeError):
            pass
    for kind in ("칸", "서술"):
        for it in lists[kind]:
            if isinstance(it, dict) and it.get("위치"):
                try:
                    owned.append((f"{kind} {it.get('항목', it.get('이름'))!r} {it['위치']}", parse_range(it["위치"])))
                except RangeError:
                    pass
    for t in lists["표"]:
        if not isinstance(t, dict) or not isinstance(t.get("열"), dict) or not isinstance(t.get("시작_행"), int):
            continue
        start = t["시작_행"]
        end = start + t["최대_행"] - 1 if isinstance(t.get("최대_행"), int) else 1048576
        for col in t["열"].values():
            if isinstance(col, str) and re.fullmatch(r"[A-Z]{1,3}", col):
                n = col2n(col)
                owned.append((f"표 {t.get('이름')!r} 의 {col} 열", (n, start, n, end)))
    return owned, bad


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
        try:
            srs_map = is_srs_map(fmap)
        except (TypeError, AttributeError):
            srs_map = False
        if srs_map:
            out.append(("map", f"시트 {sn!r} 의 `화면` — 원본이 SRS 인 지도에는 화면 그림을 둘 수 없다(작업본 `## 양식 항목` 이 원본인 지도에만 쓴다)"))
            continue
        owned, owned_bad = _owned(s)
        out += owned_bad
        reserved = {
            norm(str(x.get("이름")))
            for k in ("표", "서술") if isinstance(s.get(k), list) for x in s[k] if isinstance(x, dict)
        }
        seen: set[str] = set()
        rects: list[tuple[str, tuple[int, int, int, int]]] = []
        mine: list[tuple[str, str, tuple[int, int, int, int], str]] = []  # (화면, 종류, 범위, 적힌 글) — 영역·캡처 영역·캡처 설명
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
            if rect is not None:
                mine.append((name, "영역", rect, str(it["영역"])))
            if f"{name} 캡처" in reserved:
                out.append(("map", f"{where}: `{name} 캡처` 는 같은 시트의 표·서술 이름과 같아 구분할 수 없다"))
            cap = it.get("캡처")
            if cap is not None:
                if not isinstance(cap, dict):
                    out.append(("map", f"{where}: `캡처` 는 `영역`·`설명` 목록이어야 한다"))
                else:
                    for k in cap:
                        if k not in _CAPTURE_KEYS:
                            out.append(("map", f"{where}: 캡처의 모르는 키 {k!r} — 가능한 키: {', '.join(_CAPTURE_KEYS)}"))
                    if cap.get("설명") is None:
                        out.append(("map", f"{where}: 캡처에 `설명` 범위가 없다 — 번호별 설명을 쓸 칸 범위를 적는다"))
                    for k in _CAPTURE_KEYS:
                        if cap.get(k) is None:
                            continue
                        try:
                            r = parse_range(cap[k])
                        except RangeError as e:
                            out.append(("range", f"{where} 의 캡처 `{k}`: {e.reason}"))
                            continue
                        mine.append((name, "캡처 영역" if k == "영역" else "캡처 설명", r, str(cap[k])))
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
                        if norm(str(k)) not in STYLE_NAMES:
                            out.append(("map", f"{where}: 스타일 이름 {k!r} 는 모른다 — 가능한 이름: {', '.join(STYLE_NAMES)}"))
                        else:
                            out += [("map", f"{where}: 스타일 {k}: {why}") for why in validate_style(defn)]
            if it.get("변경") is not None:
                why, crects = _change_problems(it["변경"])
                out += [("map", f"{where}: {w}") for w in why]
                mine += [(name, "변경 표", r, text) for r, text in crects]
            if rect is not None:
                for label, orect in owned:
                    if _hit(rect, orect):
                        out.append(("map", f"{where} 영역 {it['영역']} 가 {label} 와 겹친다 — 화면 영역은 지도가 맡은 칸·표·서술·유지 범위 밖이어야 한다"))
                for other, orect in rects:
                    if _hit(rect, orect):
                        out.append(("map", f"{where} 영역 {it['영역']} 가 화면 {other!r} 영역과 겹친다"))
                rects.append((name, rect))
        out += _capture_overlaps(sn, owned, mine)
    return out


def _change_problems(chg) -> tuple[list[str], list[tuple[tuple[int, int, int, int], str]]]:
    """`변경:` 의 오류 사유들과, 쓰는 칸(열마다 시작_행~시작_행+최대_행-1)의 [(범위, 적을 글)]."""
    if not isinstance(chg, dict):
        return ["`변경` 은 `시작_행`·`최대_행`·`열` 목록이어야 한다"], []
    why: list[str] = []
    for k in chg:
        if k not in _CHANGE_KEYS:
            why.append(f"변경의 모르는 키 {k!r} — 가능한 키: {', '.join(_CHANGE_KEYS)}")
    ints: dict[str, int] = {}
    for k in ("시작_행", "최대_행"):
        v = chg.get(k)
        if v is None:
            why.append(f"변경에 `{k}` 가 없다")
        elif isinstance(v, bool) or not isinstance(v, int) or v < 1:
            why.append(f"변경의 {k} 는 1 이상의 정수여야 한다(받은 값 {v!r})")
        else:
            ints[k] = v
    cols = chg.get("열")
    letters: dict[str, str] = {}
    if cols is None:
        why.append(f"변경에 `열` 이 없다 — {'·'.join(CHANGE_COLS)} 열 문자를 적는다")
    elif not isinstance(cols, dict):
        why.append("변경의 `열` 은 이름: 열 문자 목록이어야 한다")
    else:
        for k, v in cols.items():
            if norm(str(k)) not in CHANGE_COLS:
                why.append(f"변경 열 이름 {k!r} 는 모른다 — 가능한 이름: {', '.join(CHANGE_COLS)}")
            elif not (isinstance(v, str) and re.fullmatch(r"[A-Z]{1,3}", v.strip())):
                why.append(f"변경 열 {k} 의 {v!r} 는 열 문자(A~XFD)가 아니다")
            else:
                letters[norm(str(k))] = v.strip()
        for k in CHANGE_COLS:
            if k not in {norm(str(x)) for x in cols}:
                why.append(f"변경 열에 `{k}` 항목이 없다 — {'·'.join(CHANGE_COLS)} 네 열 모두 필요하다")
    rects: list[tuple[tuple[int, int, int, int], str]] = []
    if len(ints) == 2:
        start = ints["시작_행"]
        end = start + ints["최대_행"] - 1
        if end > 1048576:
            why.append("변경 표가 엑셀 마지막 행(1048576)을 넘는다")
        else:
            for col in letters.values():
                n = col2n(col)
                rects.append(((n, start, n, end), f"{col}{start}:{col}{end}"))
    return why, rects


def _capture_overlaps(sname, owned, mine) -> list[tuple[str, str]]:
    """캡처 영역·설명 범위의 겹침. 지도가 맡은 칸·표·서술·유지, 다른 화면의 모든 범위, 같은 화면의 설명 범위와 겹치면 안 된다.
    같은 화면의 그림 영역과 캡처 영역이 겹치는 것은 지도 오류가 아니다(둘 중 하나만 쓰면 되므로) — 산출이 둘 다 쓴 작업본에서만 멈춘다.
    그림 영역끼리와 그림 영역·표·서술은 위 본 검사가 이미 한다."""
    out: list[tuple[str, str]] = []
    for i, (name, kind, rect, text) in enumerate(mine):
        if kind != "영역":
            for label, orect in owned:
                if _hit(rect, orect):
                    out.append(("map", f"시트 {sname!r} 화면 {name!r} 의 {kind} {text} 가 {label} 와 겹친다 — 캡처 범위는 지도가 맡은 칸·표·서술·유지 범위 밖이어야 한다"))
        for oname, okind, orect, otext in mine[i + 1:]:
            if kind == okind == "영역" or not _hit(rect, orect):
                continue
            if name == oname and {kind, okind} == {"영역", "캡처 영역"}:
                continue
            out.append(("map", f"시트 {sname!r} 화면 {name!r} 의 {kind} {text} 가 화면 {oname!r} 의 {okind} {otext} 와 겹친다"))
    return out


# ---------------------------------------------------------------- 작업본(md) 읽기

def parse_body(body: list[str], where: str) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """`#### … 그림` 본문 → ({`##### 소절`: 표 줄들}, 표·소절 밖 글 줄들, 첫 소절 앞의 표 줄들(조회 방식 표))."""
    secs: dict[str, list[str]] = {}
    stray: list[str] = []
    pre: list[str] = []
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
        elif not line.lstrip().startswith("|"):
            stray.append(line.strip())
        elif cur is None:
            pre.append(line)
        else:
            secs[cur].append(line)
    return secs, stray, pre


def _tables(body: list[str], where: str):
    """(소절별 표, 밖 글, 조회 방식 표). 조회 방식 표가 없으면 None."""
    secs, stray, pre = parse_body(body, where)
    settings = _parse_table(pre, f"{where} · 항목 표") if pre else None
    return {name: _parse_table(lines, f"{where} · {name}") for name, lines in secs.items()}, stray, settings


def settings_of(item: dict, body: list[str]) -> dict[str, str]:
    """`| 항목 | 값 |` 표 → {키: 값}. 없으면 기본값. 모르는 키·값은 offenders 가 잡는다."""
    out = {k: v[0] for k, v in SETTINGS.items()}
    _, _, settings = _tables(body, md_name(item))
    if settings:
        for r in settings[1]:
            out[norm(r[0])] = norm(r[1])
    return out


def offenders(item: dict, body: list[str]) -> list[tuple[str, str, list[str]]]:
    """한 `#### … 그림` 절의 양식 밖 항목 → [(분류, 이름, 허용 이름들)]. 구조가 깨졌으면 ExportError."""
    where = md_name(item)
    tables, stray, settings = _tables(body, where)
    out: list[tuple[str, str, list[str]]] = []
    for line in stray[:1]:
        out.append(("화면 그림의 표 밖 글", f"{where}: {line[:30]}", [f"##### {s} 아래 표" for s in SECTIONS]))
    if settings is not None:
        header, rows, wrong = settings
        if header != SETTINGS_HEADER:
            out.append(("화면 항목 표 머리", f"{where}: {' | '.join(header)}", [" | ".join(SETTINGS_HEADER)]))
        else:
            for n, cnt in wrong:
                out.append(("화면 표 행", f"{where} · 항목 표: {n}번째 행의 셀 수 {cnt}", [f"머리글과 같은 {len(header)}칸"]))
            seen: set[str] = set()
            for r in rows:
                key, val = norm(r[0]), norm(r[1])
                if key not in SETTINGS:
                    out.append(("화면 항목", f"{where}: {key or '(빈 이름)'}", list(SETTINGS)))
                elif key in seen:
                    out.append(("화면 항목", f"{where}: {key} (두 번)", list(SETTINGS)))
                elif val not in SETTINGS[key]:
                    out.append(("화면 항목 값", f"{where} · {key}: {val or '(빈칸)'}", SETTINGS[key]))
                seen.add(key)
    for name, parsed in tables.items():
        if parsed is not None and parsed[0] == SETTINGS_HEADER:  # 설정 표가 소절 뒤에 있으면 소절 표로 오인하지 않는다
            out.append(("화면 항목 표 위치", f"{where} · {name}: 설정 표(조회)는 그림 절 바로 아래, 첫 소절 앞에 둔다", ["첫 소절 앞"]))
            continue
        if name not in SECTIONS:
            out.append(("화면 소절", f"{where} · {name}", list(SECTIONS)))
            continue
        ok = [" | ".join(h) for h in SECTIONS[name]]
        if parsed is None:
            out.append(("화면 표 머리", f"{where} · {name}: (표 없음)", ok))
            continue
        header, rows, wrong = parsed
        if header not in SECTIONS[name]:
            out.append(("화면 표 머리", f"{where} · {name}: {' | '.join(header)}", ok))
            continue
        for n, cnt in wrong:  # 값·행 모양 검사도 여기 둔다 — 저장 훅·PR(form_columns)과 --check·산출이 같은 검사를 한다
            out.append(("화면 표 행", f"{where} · {name}: {n}번째 행의 셀 수 {cnt}", [f"머리글과 같은 {len(header)}칸"]))
        counts: dict[str, int] = {}
        for r in rows:
            if _clean(r[0]):
                counts[_clean(r[0])] = counts.get(_clean(r[0]), 0) + 1
        go_on = name == "액션" and settings is not None and settings[0] == SETTINGS_HEADER and any(
            norm(r[0]) == "조회" and norm(r[1]) == "Go" for r in settings[1]
        )
        for nm, c in counts.items():  # 지난 판과 이름으로 짝지으므로 소절 안 이름이 겹치면 비교가 흐려진다(#347)
            if c > 1 or (go_on and nm == "Go"):
                out.append(("화면 항목 중복", f"{where} · {name}: '{nm}'" + (" (조회: Go 가 이미 Go 액션을 그린다)" if c == 1 else f" ({c}번)"), ["소절 안에서 이름이 겹치지 않게"]))
        if name == "필터 바" and len(header) > 1:
            for r in rows:
                flag = _clean(r[1]).upper()
                if flag not in ("Y", "N", ""):
                    out.append(("화면 필수 값", f"{where} · 필터 바 '{_clean(r[0])}': {r[1]}", ["Y", "N", "(빈칸)"]))
    return out


# ---------------------------------------------------------------- 캡처 절(`#### <화면> 캡처`)

CAPTURE_HEADER = ["번호", "설명"]
_IMAGE_LINE = re.compile(r"^!\[([^\]]*)\]\(([^()\s]*)\)\s*$")


def parse_capture(body: list[str], where: str) -> tuple[list[tuple[int, str, str]], list[str], list[str], list[str]]:
    """`#### … 캡처` 본문 → (그림 줄들 [(줄 순서, 대체 글, 경로)], 표 줄들, 그 밖의 글 줄들, 순서 문제들). 빈 줄은 건너뛴다."""
    imgs: list[tuple[int, str, str]] = []
    table: list[str] = []
    stray: list[str] = []
    order: list[str] = []
    for n, line in enumerate(body):
        if not line.strip():
            continue
        m = _IMAGE_LINE.match(line.strip())
        if m:
            if table:
                order.append(f"{where}: 그림 줄이 표 뒤에 있다 — 그림 한 줄이 먼저, 그다음 표")
            imgs.append((n, m.group(1), m.group(2)))
        elif line.lstrip().startswith("|"):
            table.append(line)
        else:
            stray.append(line.strip())
    return imgs, table, stray, order


def capture_path_problem(path: str) -> str | None:
    """그림 경로가 저장소 루트 기준 상대 경로 `….png` 가 아니면 사유."""
    if not path:
        return "경로가 비어 있다"
    if not path.lower().endswith(".png"):
        return "PNG(`.png`) 파일만 쓴다"
    if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", path) or path.startswith(("/", "\\", "~")) or "\\" in path:
        return "저장소 루트 기준 상대 경로(`docs/spec/img/…png`)만 쓴다 — 주소(URL)·절대 경로·역슬래시는 안 된다"
    if ".." in path.split("/") or "." in path.split("/"):
        return "경로에 `.` `..` 조각이 들어 있다 — 저장소 루트 기준 상대 경로를 그대로 적는다"
    return None


def capture_rows(body: list[str], where: str) -> list[tuple[str, str]]:
    """표의 (번호, 설명) 행들. 구조가 맞는지는 `capture_offenders` 가 먼저 본다."""
    parsed = _parse_table(parse_capture(body, where)[1], where)
    return [(norm(r[0]), r[1].strip()) for r in parsed[1]] if parsed else []


def capture_offenders(item: dict, body: list[str]) -> list[tuple[str, str, list[str]]]:
    """한 `#### … 캡처` 절의 양식 밖 항목 → [(분류, 이름, 허용 이름들)]. 표 구조가 깨졌으면 ExportError."""
    where = capture_name(item)
    imgs, table, stray, order = parse_capture(body, where)
    out: list[tuple[str, str, list[str]]] = []
    for line in stray[:1]:
        out.append(("화면 캡처의 그림·표 밖 글", f"{where}: {line[:30]}", ["![설명](docs/spec/img/…_v0.1.png) 한 줄", "| 번호 | 설명 | 표"]))
    for why in order[:1]:
        out.append(("화면 캡처 순서", why, ["그림 한 줄 → 표"]))
    if len(imgs) != 1:
        out.append(("화면 캡처 그림", f"{where}: 그림 {len(imgs)}개", ["![설명](저장소 루트 기준 .png 경로) 정확히 한 줄"]))
    for _, _, path in imgs[:1]:
        why = capture_path_problem(path)
        if why:
            out.append(("화면 캡처 그림 경로", f"{where}: {path or '(빈 경로)'} — {why}", ["저장소 루트 기준 상대 경로의 .png"]))
    parsed = _parse_table(table, where) if table else None
    if parsed is None:
        out.append(("화면 캡처 표 머리", f"{where}: (표 없음)", [" | ".join(CAPTURE_HEADER)]))
        return out
    header, rows, wrong = parsed
    if header != CAPTURE_HEADER:
        out.append(("화면 캡처 표 머리", f"{where}: {' | '.join(header)}", [" | ".join(CAPTURE_HEADER)]))
        return out
    for n, cnt in wrong:
        out.append(("화면 캡처 표 행", f"{where}: {n}번째 행의 셀 수 {cnt}", [f"머리글과 같은 {len(header)}칸"]))
    if not rows:
        out.append(("화면 캡처 표 행", f"{where}: 행이 없다", ["번호 1부터 한 행 이상"]))
    for k, r in enumerate(rows, start=1):
        if norm(r[0]) != str(k):
            out.append(("화면 캡처 번호", f"{where}: {k}번째 행의 번호 {norm(r[0]) or '(빈칸)'}", [f"1부터 연속한 정수({k} 여야 한다)"]))
            break
    return out


# ---------------------------------------------------------------- 배치

class Box(NamedTuple):
    col: int
    row: int
    width: int
    kind: str  # 라벨 입력 액션 머리글 행
    text: str
    mark: str = ""  # 이 칸에 겹쳐 쓸 표시 스타일 이름(추가·수정·삭제). 없으면 빈 문자열


def layout(
    item: dict, conds: list[tuple[str, bool]], actions: list[str], cols: list[str], go: bool = False,
    marks: dict[tuple[str, str], tuple[str, int]] | None = None,
) -> tuple[list[Box], list[str]]:
    """(그릴 칸들, 영역을 넘친 항목들). 넘친 항목이 있으면 그리지 않고 거절한다. `go` 면 필터 바 오른쪽 끝에 Go 액션을 둔다.

    `marks` 는 지난 판과 달라진 항목 {(소절, 이름): (구분, 번호)}(`screen_diff`). 표시한 칸은 글자 앞에 번호를 붙이고 `Box.mark` 를 단다.
    필터 바는 추가·삭제면 라벨·입력 둘 다, 수정이면 라벨만. 결과 테이블은 추가면 머리글만, 삭제면 머리글과 빈 행 모두.
    """
    c0, r0, c1, r1 = parse_range(item["영역"])
    n = item["칸_수"]
    label_w, field_w, gap, act_w, col_w, empty = (n[k] for k in ("라벨", "입력", "간격", "액션", "열", "빈_행"))
    boxes: list[Box] = []
    over: list[str] = []
    marks = marks or {}

    def put(col: int, row: int, width: int, kind: str, text: str, what: str, key: tuple[str, str] | None = None, role: str = "") -> None:
        """key: 표시 키. role: 번호를 붙이고 늘 표시하는 칸(`head`) / 입력 칸(`extra`, 수정이면 표시하지 않는다) / 빈 행(`row`, 삭제일 때만 표시)."""
        mark = ""
        got = marks.get(key) if key else None
        if got:
            kind_of_change, num = got
            if role == "head":
                mark = kind_of_change
                text = f"{screen_diff.circled(num)} {text}"
            elif role == "extra" and kind_of_change != "수정":
                mark = kind_of_change
            elif role == "row" and kind_of_change == "삭제":
                mark = kind_of_change
        if col < c0 or col + width - 1 > c1:
            what += "(열)"
        elif row > r1:
            what += "(행)"
        else:
            boxes.append(Box(col, row, width, kind, text, mark))
            return
        if what not in over:
            over.append(what)

    row = r0
    last: int | None = None  # 필터 바의 마지막 줄
    last_end = c0 - 1  # 그 줄에서 쓴 마지막 열
    if conds:
        pair = label_w + field_w + gap
        per = (c1 - c0 + 1 + gap) // pair  # 한 줄에 들어가는 묶음 수
        last = r0
        for i, (name, required) in enumerate(conds):
            what = f"필터 바 '{name}'"
            if per < 1:
                over.append(what + "(열)")
                continue
            line = r0 + i // per
            col = c0 + (i % per) * pair
            last = max(last, line)
            last_end = col + label_w + field_w - 1 if line == last else last_end
            put(col, line, label_w, "라벨", f"{name} *" if required else name, what, ("필터 바", name), "head")
            put(col + label_w, line, field_w, "입력", "", what, ("필터 바", name), "extra")
    if go:
        go_col = c1 - act_w + 1  # 영역 오른쪽 끝
        line = r0 if last is None else last
        if last is not None and go_col < last_end + 1 + gap:  # 그 줄에 자리가 없으면 다음 줄 오른쪽 끝
            line = last + 1
        put(go_col, line, act_w, "액션", "Go", "Go 액션", screen_diff.GO_KEY, "head")
        last = line
    if last is not None:
        row = last + 2  # 필터 바 뒤 빈 줄 하나
    if actions:  # 테이블 툴바: 결과 테이블 머리글 바로 윗줄. 테이블의 오른쪽 끝에 맞춰 오른쪽 정렬(테이블이 없거나 액션이 더 넓으면 영역 오른쪽 끝 기준)
        total = len(actions) * act_w + (len(actions) - 1) * gap
        end = min(c0 + len(cols) * col_w - 1, c1) if cols else c1
        if end - total + 1 < c0:
            end = c1
        start = end - total + 1
        for i, name in enumerate(actions):
            put(start + i * (act_w + gap), row, act_w, "액션", name, f"액션 '{name}'", ("액션", name), "head")
        row += 1
    for i, name in enumerate(cols):
        what = f"결과 테이블 '{name}'"
        put(c0 + i * col_w, row, col_w, "머리글", name, what, ("결과 테이블", name), "head")
        for k in range(1, empty + 1):
            put(c0 + i * col_w, row + k, col_w, "행", "", what, ("결과 테이블", name), "row")
    return boxes, over


def _read(item: dict, body: list[str], sname: str, problem) -> tuple[list[tuple[str, bool]], list[str], list[str], bool] | None:
    """md 소절을 읽는다. 값 문제는 problem 으로 알리고 None."""
    where = md_name(item)
    off = offenders(item, body)  # 구조·머리글·행 모양·필수 값 (spec_offenders 와 같은 검사. 단독으로 불러도 조용히 넘기지 않는다)
    if off:
        raise ExportError(f"{sname} 시트의 {where} 에 양식 밖 항목이 있다: " + "; ".join(f"{k} {n!r}" for k, n, _ in off), sheet=sname, item=where)
    tables = _tables(body, where)[0]
    go = settings_of(item, body)["조회"] == "Go"
    bad = False
    conds: list[tuple[str, bool]] = []
    actions: list[str] = []
    cols: list[str] = []
    for sec, parsed in tables.items():
        header, rows, _wrong = parsed
        for k, r in enumerate(rows, start=1):
            name = _clean(r[0])
            if not name:  # 빈 행·`미정` 은 조용히 빼지 않고 거부한다
                problem(sname, where, f"{sec} 표 {k}번째 행의 이름이 {'미정' if r[0].strip() == '미정' else '비어 있다'} — 이름을 적거나 행을 지운다")
                bad = True
                continue
            if sec == "필터 바":
                flag = _clean(r[1]).upper() if len(r) > 1 else ""
                conds.append((name, flag == "Y"))
            elif sec == "액션":
                actions.append(name)
            else:
                cols.append(name)
    return None if bad else (conds, actions, cols, go)


def read_previous(item: dict, body: list[str], sname: str) -> tuple[list[tuple[str, bool]], list[str], list[str], bool]:
    """지난 판(origin/main)의 `#### … 그림` 본문을 느슨하게 읽는다. main 은 고칠 수 없고 그 모양을 고치는 PR 도 비교가 돼야 하므로
    표 밖 글, 빈 이름·`미정` 행, 소절 안 중복 이름(처음 것만), 모르는 설정 키·값(`조회` 기본값)은 무시한다.
    소절 머리글이 틀렸거나 표를 읽을 수 없을 때만 비교하지 못하므로 ExportError(검사 불능)."""
    where = md_name(item)

    def unreadable(why: str) -> ExportError:
        return ExportError(
            f"지난 판(origin/main)의 {where} 를 읽을 수 없어 변경을 비교하지 못했다(검사 불능, 통과 아님): {why} — main 의 해당 그림 절을 먼저 고친다",
            sheet=sname, item=where,
        )

    try:
        tables, _stray, settings = _tables(body, where)
    except ExportError as e:
        raise unreadable(e.reason) from None
    go = False
    if settings is not None and settings[0] == SETTINGS_HEADER:
        for r in settings[1]:
            if norm(r[0]) == "조회":
                go = norm(r[1]) == "Go"
                break
    conds: list[tuple[str, bool]] = []
    actions: list[str] = []
    cols: list[str] = []
    for sec, parsed in tables.items():
        if sec not in SECTIONS or parsed is None:
            continue  # 모르는 소절·표 없는 소절은 무시한다
        header, rows, _wrong = parsed
        if header not in SECTIONS[sec]:
            raise unreadable(f"{sec} 표 머리글이 {' | '.join(header)} 이다(허용: {' 또는 '.join(' | '.join(h) for h in SECTIONS[sec])})")
        seen: set[str] = set()
        for r in rows:
            name = _clean(r[0])
            if not name or name in seen:
                continue
            seen.add(name)
            if sec == "필터 바":
                conds.append((name, len(header) > 1 and _clean(r[1]).upper() == "Y"))
            elif sec == "액션":
                actions.append(name)
            else:
                cols.append(name)
    return conds, actions, cols, go


def draw(
    ed: SheetXml, styles: StylesXml, item: dict, body: list[str], sname: str, problem,
    old_body: list[str] | None = None,
) -> int | None:
    """한 화면을 그린다. 그린 칸 수를 낸다(소절이 없거나 비어 0). 이름 빈칸·영역 초과·영역 안 값은 쓰지 않고 problem 으로 알리고 None.

    `old_body` 가 있으면 지난 판의 같은 그림 절과 비교해(`screen_diff`) 달라진 항목에 번호와 표시 스타일을 겹쳐 쓰고,
    지도 `변경:` 의 변경 내용 표를 채운다. 없으면(첫 판 등) 표시 없이 그린다.
    """
    where = md_name(item)
    read = _read(item, body, sname, problem)
    if read is None:
        return None
    merged = None
    if old_body is not None:
        merged = screen_diff.merge(read_previous(item, old_body, sname), read)
        read = (merged.conds, merged.actions, merged.cols, merged.go)
    boxes, over = layout(item, *read, marks=merged.marks if merged else None)
    if over:
        problem(sname, where, (
            f"{where} 이 영역 {item['영역']} 를 넘는다 — 넘친 항목: {', '.join(over[:12])}{' …' if len(over) > 12 else ''}. "
            "영역을 넓히거나 항목을 줄이거나 지도의 `칸_수` 를 줄인다(자르지 않는다)"
        ))
        return None
    c0, r0, c1, r1 = parse_range(item["영역"])
    taken = [r for r in ed.valued_refs() if c0 <= col2n(split_ref(r)[0]) <= c1 and r0 <= split_ref(r)[1] <= r1]
    if taken and boxes:
        problem(sname, where, (
            f"영역 {item['영역']} 안에 이미 값이 있다({', '.join(taken[:5])}{' …' if len(taken) > 5 else ''}) — "
            "견본이 남은 자리에는 그리지 않는다. 지도 `비우기` 로 지운 빈 양식을 템플릿으로 쓴다"
        ))
        return None
    changes = merged.changes if merged else []
    table = _change_table(ed, item, changes, where, sname, problem) if changes else []
    if changes and table is None:
        return None
    saved = (ed._max_row, ed._max_col)  # 글자 쓰기가 자동 필터 범위를 늘리지 않게(dimension 은 set_style 이 넓힌다)
    try:
        for b in boxes:
            a, z = f"{n2col(b.col)}{b.row}", f"{n2col(b.col + b.width - 1)}{b.row}"
            if b.text:
                ed.set(a, b.text, as_text=True)
            style = {**item["스타일"][b.kind], **item["스타일"][b.mark]} if b.mark else item["스타일"][b.kind]
            style_range(ed, styles, a, z, style, sname)
            if b.width > 1:
                merge_range(ed, a, z, sname)
        for ref, text in table:
            ed.set(ref, text, as_text=True)
    except ExportError as e:
        raise ExportError(f"{where}: {e.reason}", sheet=sname, item=where) from None
    finally:
        ed._max_row, ed._max_col = saved
    return len(boxes)


def _change_table(ed: SheetXml, item: dict, changes: list, where: str, sname: str, problem) -> list[tuple[str, str]] | None:
    """변경 내용 표에 쓸 [(칸, 글)]. 자리가 없거나 모자라거나 쓸 칸에 값이 남아 있으면 problem 으로 알리고 None(자르지 않는다)."""
    spot = item["변경"]
    if spot is None:
        problem(sname, where, f"변경 {len(changes)}건이 있는데 변경 내용 표 자리가 지도에 없다 — 지도 `화면:` 에 `변경:` 을 적는다")
        return None
    if len(changes) > spot["최대_행"]:
        problem(sname, where, f"변경 {len(changes)}건이 변경 내용 표의 최대_행 {spot['최대_행']} 을 넘는다 — 지도의 `변경:` 최대_행(과 양식의 표)을 늘린다(자르지 않는다)")
        return None
    cols = spot["열"]
    start = spot["시작_행"]
    cells: list[tuple[str, str]] = []
    for i, ch in enumerate(changes):
        for key, text in zip(CHANGE_COLS, (screen_diff.circled(ch.number), ch.kind, ch.target, ch.content)):
            cells.append((f"{cols[key]}{start + i}", text))
    taken = [r for r in ed.valued_refs() if r in {ref for ref, _ in cells}]
    if taken:
        problem(sname, where, (
            f"변경 내용 표를 쓸 칸에 이미 값이 있다({', '.join(taken[:5])}{' …' if len(taken) > 5 else ''}) — "
            "견본이 남은 자리에는 쓰지 않는다. 지도 `비우기` 로 지운 빈 양식을 템플릿으로 쓴다"
        ))
        return None
    return cells
