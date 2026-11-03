"""트랜스포트 JSON 으로 CTS 관리대장 작업본(md)의 요청 표를 채운다(이슈 #563, `/harness:cts` 스킬).

엔진은 MCP 를 부르지 않는다. 스킬이 읽기 전용 ADT 도구로 읽은 값을 JSON 으로 저장하고, 이 모듈이 그 JSON 을 작업본 표 행으로
옮긴다. 어느 열에 무엇이 들어가는지(트랜스포트 값 → 양식 열 이름, 종류 분기, CTS 유형 값)는 코드가 아니라 매핑 파일
(`templates/harness/cts-fill.yaml`, 스킬 폴더의 `cts-fill.yaml` 사본)에서 읽는다.

`--adt` 면 JSON 대신 ADT 응답을 그대로 저장한 파일을 읽어 아래 모양으로 바꾼다(`adt_to_transports`). `date` 는 비워도 된다
(ADT 응답에는 요청일이 없다 — 매핑 `요청일_출처: lastchanged` 일 때만 마지막 변경일을 쓴다).
JSON 모양::

    {"system": "Z5U", "client": "100",
     "transports": [{"number": "Z5UK900001", "description": "…", "owner": "USER", "date": "2026-11-02",
                     "target": "Z5Q", "category": "customizing"}],
     "unread": [{"number": "Z5UK900002", "reason": "…"}]}

종료코드: 0 정상(`--check` 포함) / 2 검사 불능(JSON·매핑·작업본을 읽지 못함, 형식이 다른 값, 읽지 못한 트랜스포트 있음, 매핑의 열이
작업본 머리글에 없음, 인자 오류) / 3 경고(`warnings`: `no-transports` 읽은 요청이 0건, `unrouted` 채울 작업본이 없는 종류의 요청이 있어
그 건은 채우지 못함 — 3 이어도 라우팅된 작업본은 반영됐다). `read` 는 변환된 요청 수. 사람만 아는 칸은 비워 둔다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

EXIT_OK, EXIT_ERROR, EXIT_WARNING = 0, 2, 3

DEFAULT_MAP = Path("templates") / "harness" / "cts-fill.yaml"
_SPLIT = re.compile(r"(?<!\\)\|")
# 매핑 파일의 값 열(트랜스포트 JSON 키 → 양식 열 이름)에서 엔진이 아는 키. 새 키는 코드가 늘어야 한다.
_KEYS = ("number", "description", "owner", "date", "target")


class FillError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def _force_utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")


# ---------------------------------------------------------------- 매핑

def load_map(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise FillError([f"매핑 파일을 읽지 못했다({path}): {e}"])
    problems = []
    if not isinstance(data, dict):
        raise FillError([f"매핑 파일이 객체가 아니다({path})"])
    kinds = data.get("종류")
    if not isinstance(kinds, dict) or not kinds:
        problems.append("매핑 `종류` 가 비어 있다")
    else:
        for cat, v in kinds.items():
            if not isinstance(v, dict) or not isinstance(v.get("작업본"), str) or not v["작업본"]:
                problems.append(f"매핑 `종류.{cat}.작업본` 이 없다")
    pat = data.get("작업본_파일명")
    try:
        if not isinstance(pat, str) or "kind" not in re.compile(pat).groupindex:
            raise re.error("이름 그룹 kind 없음")
    except re.error as e:
        problems.append(f"매핑 `작업본_파일명` 이 이름 그룹 `kind` 가 있는 정규식이 아니다: {e}")
    cols = data.get("열")
    if not isinstance(cols, dict) or not all(isinstance(cols.get(k), str) and cols[k] for k in ("number", "row_no")):
        problems.append("매핑 `열.number`(Request NO 열)와 `열.row_no`(NO 열)가 필요하다")
    else:
        for k, v in cols.items():
            if k not in _KEYS + ("row_no",):
                problems.append(f"매핑 `열.{k}` 는 엔진이 모르는 키다(허용: {', '.join(_KEYS + ('row_no',))})")
            elif not isinstance(v, str) or not v:
                problems.append(f"매핑 `열.{k}` 가 열 이름 글자가 아니다: {v!r} (NO 는 따옴표로 쓴다)")
    vals = data.get("값", {})
    if not isinstance(vals, dict):
        problems.append("매핑 `값` 이 객체가 아니다")
    if problems:
        raise FillError(problems)
    return data


# ---------------------------------------------------------------- 트랜스포트 JSON

def _norm_date(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})(?:$|[T ])", v.strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def _read_json(path: Path, what: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FillError([f"{what} 를 읽지 못했다({path}): {e}"])


def _lastchanged_date(v: object) -> str | None:
    """ADT `tm:lastchanged_timestamp`(YYYYMMDDhhmmss 14자리 숫자·글자)의 날짜. 그 모양이 아니면 None."""
    s = str(v) if isinstance(v, (int, str)) and not isinstance(v, bool) else ""
    return _norm_date(s[:8]) if re.fullmatch(r"\d{14}", s) else None


def adt_to_transports(data: object, mp: dict, include_released: bool = False) -> dict:
    """`transportsByConfig`·`userTransports` 응답(`transports.{workbench|customizing}[]` → 대상 묶음 → modifiable·released
    요청 → tasks)을 중간 JSON 으로 바꾼다. category 는 최상위 키, tasks 는 행으로 만들지 않는다. 요청일은 ADT 응답에 없다 —
    매핑 `요청일_출처: lastchanged` 일 때만 마지막 변경 시각의 날짜를 쓰고, 아니면 비운다. 모양이 다르면 FillError."""
    if not isinstance(data, dict) or not isinstance(data.get("transports"), dict):
        raise FillError(["ADT 응답에 `transports` 객체가 없다(형식이 다르다)"])
    if data.get("status") not in (None, "success"):
        raise FillError([f"ADT 응답 status 가 success 가 아니다: {data.get('status')!r}"])
    src = mp.get("요청일_출처", "없음")
    if src not in ("없음", "lastchanged"):
        raise FillError([f"매핑 `요청일_출처` 는 없음·lastchanged 중 하나여야 한다: {src!r}"])
    problems, out = [], []
    for cat, groups in data["transports"].items():
        if cat not in mp["종류"]:
            problems.append(f"transports.{cat} 가 매핑 `종류` 에 없다(허용: {', '.join(mp['종류'])})")
            continue
        if not isinstance(groups, list):
            problems.append(f"transports.{cat} 가 목록이 아니다")
            continue
        for gi, g in enumerate(groups):
            if not isinstance(g, dict) or not all(isinstance(g.get(k), list) for k in ("modifiable", "released")):
                problems.append(f"transports.{cat}[{gi}] 에 modifiable·released 목록이 없다")
                continue
            for part in ("modifiable", "released") if include_released else ("modifiable",):
                for r in g[part]:
                    num = r.get("tm:number") if isinstance(r, dict) else None
                    if not isinstance(r, dict) or not isinstance(num, str) or not num:
                        problems.append(f"transports.{cat}[{gi}].{part} 요청에 tm:number 가 없다")
                        continue
                    if r.get("tm:parent"):
                        problems.append(f"{num} 는 요청이 아니라 task 다(tm:parent={r.get('tm:parent')!r})")
                        continue
                    missing = [k for k in ("tm:owner", "tm:desc") if not isinstance(r.get(k), str)]
                    if missing:
                        problems.append(f"{num} 에 글자 필드가 없다: {', '.join(missing)}")
                        continue
                    d = ""
                    if src == "lastchanged":
                        d = _lastchanged_date(r.get("tm:lastchanged_timestamp"))
                        if d is None:
                            problems.append(f"{num}.tm:lastchanged_timestamp 가 14자리 시각이 아니다: {r.get('tm:lastchanged_timestamp')!r}")
                            continue
                    out.append({"number": num, "description": r["tm:desc"], "owner": r["tm:owner"], "date": d,
                                "target": r.get("tm:target") or "", "category": cat})
    if problems:
        raise FillError(problems)
    return {"transports": out}


def load_all_transports(paths: list[Path], mp: dict, adt: bool = False, include_released: bool = False) -> list[dict]:
    """파일마다 읽어 검증한 뒤 합친다. 같은 요청 번호가 여러 파일에 있으면 첫 번째만 쓴다(설정이 겹쳐 같은 요청이 나올 수 있다)."""
    problems, out, seen = [], [], set()
    for p in paths:
        try:
            for t in load_transports(p, mp, adt, include_released):
                if t["number"] not in seen:
                    seen.add(t["number"])
                    out.append(t)
        except FillError as e:
            problems += [f"{p.name}: {x}" if len(paths) > 1 else x for x in e.problems]
    if problems:
        raise FillError(problems)
    return out


def load_transports(path: Path, mp: dict, adt: bool = False, include_released: bool = False) -> list[dict]:
    data = _read_json(path, "트랜스포트 JSON")
    if adt:
        data = adt_to_transports(data, mp, include_released)
    if not isinstance(data, dict) or not isinstance(data.get("transports"), list):
        raise FillError(["트랜스포트 JSON 에 `transports` 목록이 없다(형식이 다르다)"])
    problems = []
    unread = data.get("unread") or []
    if not isinstance(unread, list):
        problems.append("`unread` 가 목록이 아니다")
    else:
        for u in unread:
            who = u.get("number") if isinstance(u, dict) else u
            why = u.get("reason") if isinstance(u, dict) else ""
            problems.append(f"읽지 못한 트랜스포트 {who}: {why or '이유 없음'}")
    out, seen = [], set()
    for i, t in enumerate(data["transports"]):
        tag = f"transports[{i}]"
        if not isinstance(t, dict):
            problems.append(f"{tag} 가 객체가 아니다")
            continue
        num = t.get("number")
        if not isinstance(num, str) or not num.strip() or re.search(r"\s", num):
            problems.append(f"{tag}.number 가 비었거나 형식이 다르다: {num!r}")
            continue
        tag = f"{num}"
        if num in seen:
            problems.append(f"{tag} 가 JSON 에 두 번 있다")
            continue
        seen.add(num)
        cat = t.get("category")
        if cat not in mp["종류"]:
            problems.append(f"{tag}.category {cat!r} 가 매핑 `종류` 에 없다(허용: {', '.join(mp['종류'])})")
        for k in ("description", "owner"):
            if not isinstance(t.get(k), str):
                problems.append(f"{tag}.{k} 가 글자가 아니다: {t.get(k)!r}")
        if not isinstance(t.get("target", ""), (str, type(None))):
            problems.append(f"{tag}.target 이 글자가 아니다: {t.get('target')!r}")
        d = "" if t.get("date") in ("", None) else _norm_date(t.get("date"))
        if d is None:
            problems.append(f"{tag}.date 를 날짜로 읽지 못했다: {t.get('date')!r} (YYYY-MM-DD·YYYYMMDD·ISO 날짜만)")
        out.append({"number": num, "description": t.get("description"), "owner": t.get("owner"), "date": d,
                    "target": t.get("target") or "", "category": cat})
    if problems:
        raise FillError(problems)
    return out


# ---------------------------------------------------------------- 작업본 표

def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|").replace("<br>", "\n") for c in _SPLIT.split(s)]


def _fmt(v: str) -> str:
    return v.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _is_sep(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{3,}", line)) and set(line.strip()) <= set("|-: ")


def find_request_table(lines: list[str], request_col: str) -> tuple[int, int, int]:
    """`### …` 소절 안에서 머리글에 Request NO 열이 있는 첫 표. (머리글 줄, 첫 데이터 줄, 끝 줄(포함 다음)) 을 낸다."""
    in_items = False
    for i, ln in enumerate(lines):
        if ln.startswith("## "):
            in_items = ln.strip() == "## 양식 항목"
        if not in_items or not ln.lstrip().startswith("|"):
            continue
        if i + 1 < len(lines) and _is_sep(lines[i + 1]) and request_col in _cells(ln):
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            return i, i + 2, j
    raise FillError([f"작업본 `## 양식 항목` 에서 `{request_col}` 열이 있는 표를 찾지 못했다"])


def fill_note(text: str, kind_transports: list[dict], mp: dict, fill_empty: bool) -> tuple[str, dict]:
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol) if eol == "\r\n" else text.split("\n")
    cols = mp["열"]
    head_i, first, end = find_request_table(lines, cols["number"])
    header = _cells(lines[head_i])
    no_col = cols["row_no"]
    # 매핑이 가리키는 열이 작업본 표 머리글에 없으면 값이 조용히 버려지므로 지도·매핑 오류로 멈춘다.
    wanted = list(cols.values()) + list((mp.get("값") or {}))
    missing = [c for c in dict.fromkeys(wanted) if c not in header]
    if missing:
        raise FillError([f"매핑의 열 {', '.join('`' + c + '`' for c in missing)} 이 작업본 요청 표 머리글에 없다(지도·매핑 오류)"])
    pos = {n: header.index(n) for n in header}

    rows = {}  # Request NO → (줄 번호, 칸)
    nums = []
    problems = []
    for li in range(first, end):
        cs = _cells(lines[li])
        cs += [""] * (len(header) - len(cs))
        req = cs[pos[cols["number"]]].strip()
        if req.startswith("<"):
            continue  # 자리표시 행(`<값>`)은 번호 이어 매기기에서 뺀다
        if cs[pos[no_col]].strip():
            try:
                nums.append(int(cs[pos[no_col]]))
            except ValueError:
                problems.append(f"{li + 1}줄 NO `{cs[pos[no_col]]}` 가 숫자가 아니라 이어 매길 수 없다")
        if req:
            rows[req] = (li, cs)
    if problems:
        raise FillError(problems)

    def values(t: dict) -> dict[str, str]:
        v = {cols[k]: t[k] for k in _KEYS if k in cols and cols[k] in header}
        for col, by_cat in (mp.get("값") or {}).items():
            if col in header and t["category"] in by_cat:
                v[col] = str(by_cat[t["category"]])
        return v

    added, filled, kept = [], [], []
    new_lines = []
    nxt = (max(nums) if nums else 0) + 1
    for t in sorted(kind_transports, key=lambda x: (x["date"], x["number"])):
        v = values(t)
        if t["number"] in rows:
            li, cs = rows[t["number"]]
            if fill_empty:
                changed = [c for c, val in v.items() if val and not cs[pos[c]].strip()]
                for c in changed:
                    cs[pos[c]] = v[c]
                if changed:
                    lines[li] = "| " + " | ".join(_fmt(c) for c in cs) + " |"
                    filled.append({"number": t["number"], "columns": changed})
                    continue
            kept.append(t["number"])
            continue
        cs = [""] * len(header)
        for c, val in v.items():
            cs[pos[c]] = val
        cs[pos[no_col]] = str(nxt)
        new_lines.append("| " + " | ".join(_fmt(c) for c in cs) + " |")
        added.append({"number": t["number"], "no": nxt})
        nxt += 1
    lines[end:end] = new_lines
    report = {"added": added, "filled": filled, "kept": kept}
    return eol.join(lines), report


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise FillError([f"작업본을 읽지 못했다({path}): {e}"])


def _write_all(items: dict[Path, str]) -> None:
    """모두 같은 폴더의 임시 파일(원본 권한 복사)에 먼저 쓰고, 다 됐을 때만 교체한다. 준비 중 실패하면 아무것도 바뀌지 않고,
    교체 중 실패하면 이미 바꾼 것을 원래 내용으로 되돌려 본다."""
    tmps: dict[Path, str] = {}
    originals: dict[Path, bytes] = {}
    try:
        for path, text in items.items():
            originals[path] = path.read_bytes()
            mode = path.stat().st_mode & 0o7777
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
            tmps[path] = tmp
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8"))
            os.chmod(tmp, mode)
        done: list[Path] = []
        try:
            for path, tmp in list(tmps.items()):
                os.replace(tmp, path)
                done.append(path)
                del tmps[path]
        except BaseException:
            for path in done:
                try:
                    path.write_bytes(originals[path])
                except OSError:
                    pass
            raise
    finally:
        for tmp in tmps.values():
            try:
                os.unlink(tmp)
            except OSError:
                pass


def run(specs: list[Path], transports: list[Path], map_path: Path, check: bool, fill_empty: bool,
        adt: bool = False, include_released: bool = False) -> tuple[int, dict]:
    mp = load_map(map_path)
    ts = load_all_transports(transports, mp, adt, include_released)
    name_re = re.compile(mp["작업본_파일명"])
    by_kind: dict[str, Path] = {}
    problems = []
    for sp in specs:
        m = name_re.match(sp.name)
        if not m:
            problems.append(f"작업본 파일 이름이 매핑 `작업본_파일명` 모양이 아니다: {sp.name}")
        elif m["kind"] in by_kind:
            problems.append(f"같은 종류({m['kind']}) 작업본이 둘이다")
        else:
            by_kind[m["kind"]] = sp
    if problems:
        raise FillError(problems)

    unrouted = []
    groups: dict[str, list[dict]] = {}
    for t in ts:
        kind = mp["종류"][t["category"]]["작업본"]
        if kind in by_kind:
            groups.setdefault(kind, []).append(t)
        else:
            unrouted.append({"number": t["number"], "category": t["category"], "kind": kind})

    # 모든 작업본을 먼저 계산하고, 하나라도 못 읽으면 아무것도 쓰지 않는다.
    results, outputs = {}, {}
    for kind, sp in by_kind.items():
        new, rep = fill_note(_read_text(sp), groups.get(kind, []), mp, fill_empty)
        results[kind] = {"spec": str(sp), **rep}
        outputs[sp] = new
    changed = [sp for sp, new in outputs.items() if new != _read_text(sp)]
    if not check and changed:
        _write_all({sp: outputs[sp] for sp in changed})
    warnings = []
    if not ts:
        warnings.append({"type": "no-transports", "message": "읽을 요청이 없거나 읽기 경로가 틀렸다 — userTransports 가 비면 transportsByConfig 로"})
    if unrouted:
        warnings.append({"type": "unrouted", "message": "채울 작업본이 없는 종류의 요청이 있어 그 건은 채우지 못했다", "transports": unrouted})
    report = {"status": "warning" if warnings else "ok", "check": check, "read": len(ts), "results": results,
              "unrouted": unrouted, "warnings": warnings, "written": [] if check else [str(p) for p in changed]}
    return (EXIT_WARNING if warnings else EXIT_OK), report


class _Parser(argparse.ArgumentParser):
    """인자 오류도 usage 를 stderr 로 내고 종료하지 않고, 다른 오류처럼 JSON 한 줄(종료 2)로 낸다."""

    def error(self, message: str):
        raise FillError([f"인자 오류: {message}"])


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    ap = _Parser(prog="python -m checker.cts_fill",
                 description="트랜스포트 JSON 으로 CTS 관리대장 작업본의 요청 표를 채운다.")
    ap.add_argument("--spec", type=Path, action="append", required=True, help="작업본 md(CTS관리대장_<종류>.md). 종류마다 하나씩 여러 번 줄 수 있다")
    ap.add_argument("--transports", type=Path, action="append", required=True,
                    help="스킬이 저장한 트랜스포트 JSON. 여러 번 줄 수 있고 같은 요청 번호는 한 번만 쓴다")
    ap.add_argument("--adt", action="store_true", help="--transports 가 중간 JSON 이 아니라 ADT 응답(transportsByConfig·userTransports)을 그대로 저장한 파일이다")
    ap.add_argument("--include-released", action="store_true", help="--adt 일 때 released(릴리스된) 요청도 넣는다(기본은 modifiable 만)")
    ap.add_argument("--map", type=Path, help=f"매핑 yaml(생략하면 --root 기준 {DEFAULT_MAP.as_posix()})")
    ap.add_argument("--root", type=Path, default=Path("."), help="Project Repository 루트(--map 생략 때만 쓴다)")
    ap.add_argument("--fill-empty", action="store_true", help="이미 있는 행의 비어 있는 칸만 채운다(없는 행은 어느 쪽이든 더한다)")
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 같은 계산·보고만 한다")
    try:
        args = ap.parse_args(argv)
        mp = args.map or (args.root / DEFAULT_MAP)
        code, report = run(args.spec, args.transports, mp, args.check, args.fill_empty, args.adt, args.include_released)
    except FillError as e:
        code, report = EXIT_ERROR, {"status": "error", "problems": [{"reason": p} for p in e.problems]}
    except Exception as e:  # 예상하지 못한 오류도 통과가 아니라 검사 불능이다
        code, report = EXIT_ERROR, {"status": "error", "problems": [{"reason": f"예상하지 못한 오류({type(e).__name__}): {e}"}]}
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
