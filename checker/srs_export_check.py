"""산출 Backlog 엑셀이 SRS 내용과 같은 판인지 확인한다(#976).

산출 PR(SRS `버전:` + 0.1, 그 판 엑셀)을 연 뒤 다른 내용 PR 이 먼저 병합되면, 충돌 없이 병합돼 엑셀만 main SRS 보다 낡을 수 있다(ruleset
`strict:false`, GitHub 는 base 가 바뀌어도 검사를 다시 돌리지 않는다). 이 모듈이 그 어긋남을 세 곳에서 잡는 공통 도구다.

- `compare --root .`: 지금 작업 폴더의 `docs/ssot/SRS.md` 로 엑셀을 **저장소 밖 임시 경로**에 다시 만들고(`checker.export` 의 `--out`), SRS `버전:`
  판 이름의 저장소 엑셀과 **칸 값**으로 비교한다(바이트 비교 아님 — 저장 환경에 따라 압축 바이트가 다르다). 산출은 날짜 같은 바뀌는 값을 넣지 않아
  같은 SRS 면 칸 값이 같다. 비교 범위는 양식 지도 표가 쓰는 시트·열의 머리글 행부터 끝까지다. 결과 `status`: `same` / `differ` / `cannot_check`.
  종료코드: same 0, differ 1, cannot_check 2. PR 검사(`scripts/check_changed.py`)·병합 뒤 검사(`main-checks.yml`)·srs 스킬이 부른다.
- `push-check --added-file F`: 병합 뒤 `main-checks.yml` 이 부른다. 이 push 가 Backlog 엑셀을 추가했을 때만 `compare` 를 돌린다(내용 PR 병합 push 에서는 엑셀이 낡은 게 정상).
- `merge-guard --repo R --pr N`: 병합 직전 훅이 부른다. 이 PR 이 Backlog 엑셀을 추가했고(산출 PR), PR head 의 SRS.md 와 base 브랜치(GitHub 쪽 최신)의
  SRS.md 가 `버전:` 줄 말고 다르면 엑셀을 만든 뒤 base 의 SRS 가 바뀐 것이라 stale(1)이다. 산출 PR 이 아니면 0. gh 가 실패하면 cannot_check(2).
  양식 지도는 지금 작업 폴더의 `templates/forms/` 를 읽는다(`checker.srs_split.backlog_forms`).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import yaml

from checker.pairing import CANNOT_CHECK, SRS_PATH
from checker.readers import xlsx as xlsx_reader
from checker.srs_split import _CannotCheck, _expected_path, backlog_forms
from checker.version_overlap import ADDED_STATUSES, _SRS_VERSION, srs_version_of

SAME = "same"
DIFFER = "differ"
STALE = "stale"
NOT_APPLICABLE = "not_applicable"
EXIT_SAME, EXIT_DIFFER, EXIT_CANNOT = 0, 1, 2
MAX_LISTED = 10  # differ 일 때 결과에 싣는 다른 칸의 수(나머지는 개수만)

_COL = re.compile(r"[A-Z]{1,3}")


def _cannot(message: str) -> dict:
    return {"status": CANNOT_CHECK, "message": message}


def _norm(value) -> str:
    """칸 값을 비교용 글자로. 빈 칸은 "", 줄바꿈은 \\n, 정수로 떨어지는 실수는 정수, 앞뒤 공백은 뗀다."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if hasattr(value, "isoformat"):
        value = value.isoformat()
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _scope(root: Path, form: dict) -> list[tuple[str, int, list[str]]]:
    """양식 지도에서 비교할 (시트 이름, 머리글 행, 열 글자들). 표의 열이 하나도 없으면 비교할 칸을 모르니 _CannotCheck."""
    path = root / "templates" / "forms" / f"{form['name']}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise _CannotCheck(f"양식 지도 {path.name} 를 읽지 못했습니다: {exc}") from None
    out: list[tuple[str, int, list[str]]] = []
    for sheet in data.get("시트") or []:
        if not isinstance(sheet, dict):
            continue
        for table in sheet.get("표") or []:
            if not isinstance(table, dict):
                continue
            cols = sorted({str(v).strip() for v in (table.get("열") or {}).values() if _COL.fullmatch(str(v).strip())})
            first = table.get("머리글_행")
            if sheet.get("이름") and cols and isinstance(first, int):
                out.append((str(sheet["이름"]), first, cols))
    if not out:
        raise _CannotCheck(f"양식 지도 {path.name} 에서 비교할 표의 열·머리글 행을 찾지 못했습니다")
    return out


def _cells(path: Path, scope: list[tuple[str, int, list[str]]]) -> dict[tuple[str, str], str]:
    """비교 범위의 값이 있는 칸만 {(시트, 칸 이름): 값} 으로. 시트가 없으면 _CannotCheck."""
    cells: dict[tuple[str, str], str] = {}
    for sheet, first, cols in scope:
        rows = xlsx_reader.read_values(path, sheet, first)
        if rows is None:
            raise _CannotCheck(f"{path.name} 에 시트 `{sheet}` 가 없습니다")
        for r, row in enumerate(rows, start=first):
            for col in cols:
                i = _col_index(col)
                value = _norm(row[i]) if i < len(row) else ""
                if value:
                    cells[(sheet, f"{col}{r}")] = value
    return cells


def _short(text: str) -> str:
    return text if len(text) <= 40 else text[:40] + "…"


def _compare_one(root: Path, form: dict, version: str, tmp: Path) -> dict:
    from checker import export

    repo_file = root / _expected_path(form, version)
    if not repo_file.is_file():
        return _cannot(f"SRS `버전: {version}` 판의 엑셀 `{repo_file.relative_to(root).as_posix()}` 이 저장소에 없습니다")
    scope = _scope(root, form)
    out = tmp / f"{form['name']}.xlsx"
    try:
        code, report = export.run(root / SRS_PATH, root, form["name"], False, out)
    except export.ExportError as exc:
        return _cannot(f"엑셀을 다시 만들지 못했습니다: {exc.reason}")
    if code not in (export.EXIT_OK, export.EXIT_WARNING) or not out.is_file():
        probs = "; ".join(str(p.get("reason", p)) for p in (report.get("problems") or [])[:3]) or str(report.get("reason", ""))
        return _cannot(f"SRS 내용으로 엑셀을 다시 만들지 못했습니다(종료코드 {code}): {probs}")
    try:
        want = _cells(out, scope)
        have = _cells(repo_file, scope)
    except _CannotCheck as exc:
        return _cannot(str(exc))
    except Exception as exc:  # noqa: BLE001 - 엑셀을 못 읽은 것은 같다고도 다르다고도 하지 않는다
        return _cannot(f"엑셀을 읽지 못했습니다: {type(exc).__name__}: {exc}")
    diffs = [
        {"sheet": s, "cell": c, "repo": _short(have.get((s, c), "")), "regenerated": _short(want.get((s, c), ""))}
        for (s, c) in sorted(set(want) | set(have), key=lambda k: (k[0], int(re.sub(r"\D", "", k[1])), k[1]))
        if want.get((s, c), "") != have.get((s, c), "")
    ]
    if diffs:
        return {"status": DIFFER, "file": repo_file.relative_to(root).as_posix(), "differences": len(diffs), "cells": diffs[:MAX_LISTED]}
    return {"status": SAME, "file": repo_file.relative_to(root).as_posix()}


def compare(root: Path) -> dict:
    """지금 작업 폴더의 SRS 와 그 판의 저장소 엑셀을 칸 값으로 비교한다. 결과 `status` 는 same / differ / cannot_check."""
    srs = root / SRS_PATH
    try:
        text = srs.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _cannot(f"{SRS_PATH} 를 읽지 못했습니다: {exc}")
    version = srs_version_of(text)
    if version is None:
        return _cannot(f"{SRS_PATH} 에 `버전:` 줄이 없어 어느 판의 엑셀과 비교할지 알 수 없습니다")
    try:
        forms = backlog_forms(root)
    except _CannotCheck as exc:
        return _cannot(str(exc))
    if not forms:
        return _cannot("`원본: SRS` 인 양식 지도(`templates/forms/`)가 없어 비교할 Backlog 엑셀을 알 수 없습니다")
    tmp = Path(tempfile.mkdtemp(prefix="srs-export-check-"))
    try:
        results = [dict(form=f["name"], **_compare_one(root, f, version, tmp)) for f in forms]
    finally:
        xlsx_reader.clear_cache()  # Windows 에서는 열린 xlsx 를 지울 수 없다
        shutil.rmtree(tmp, ignore_errors=True)
    statuses = {r["status"] for r in results}
    status = DIFFER if DIFFER in statuses else CANNOT_CHECK if CANNOT_CHECK in statuses else SAME
    out: dict = {"status": status, "version": version, "forms": results}
    if status == CANNOT_CHECK:
        out["message"] = "; ".join(r["message"] for r in results if r["status"] == CANNOT_CHECK)
    return out


# ------------------------------------------------------------------ PR 검사

def adds_backlog_xlsx(added: list[str], root: Path) -> bool:
    """추가된 파일 목록에 Backlog 엑셀이 있는지. 양식 지도를 못 읽으면 _CannotCheck."""
    names = [a.replace("\\", "/") for a in added]
    return any(form["pattern"].fullmatch(n) for form in backlog_forms(root) for n in names)


def merge_into_split(split: dict | None, added_path: str | None, root: Path) -> dict | None:
    """PR 검사(`scripts/check_changed.py`)의 `srs_split` 결과에 "엑셀이 SRS 와 같은 판인가" 를 더한다(#976).

    이 PR 이 Backlog 엑셀을 추가했을 때만 `compare` 를 돌린다. PR 검사는 병합 결과(refs/pull/N/merge)를 체크아웃하므로 그 시점 main 의 내용이 들어 있다.
    differ 는 위반(`stale_xlsx`), cannot_check 는 검사 불능이다. 이미 검사 불능이거나 꺼진 결과, 추가 목록이 없는 경우는 손대지 않는다.
    """
    if not added_path or (split or {}).get("status") in ("disabled", CANNOT_CHECK):
        return split
    try:
        added = [ln.strip() for ln in Path(added_path).read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not adds_backlog_xlsx(added, root):
            return split
    except (OSError, UnicodeDecodeError, _CannotCheck) as exc:
        return {"status": CANNOT_CHECK, "violations": [], "message": f"산출 엑셀이 SRS 와 같은지 확인하지 못했습니다: {exc}"}
    result = compare(root)
    split = dict(split or {"status": "pass", "violations": []})
    if result["status"] == CANNOT_CHECK:
        return {"status": CANNOT_CHECK, "violations": [], "message": f"산출 엑셀이 SRS 와 같은지 확인하지 못했습니다: {result['message']}"}
    if result["status"] == DIFFER:
        form = next((r for r in result["forms"] if r["status"] == DIFFER), {})
        cells = ", ".join(c["cell"] for c in form.get("cells", [])[:5])
        split["violations"] = list(split.get("violations") or []) + [{
            "rule": "stale_xlsx",
            "reason": (
                f"`{form.get('file')}` 이 이 PR 이 병합된 뒤의 SRS 내용과 다릅니다({form.get('differences')}칸, 예: {cells}). "
                "산출 PR 을 연 뒤 main 의 SRS 가 바뀐 것입니다."
            ),
            "fix": "main 위로 옮겨(/harness:sync) \"백로그 뽑아 줘\" 로 그 판을 다시 산출하십시오.",
        }]
        split["status"] = "violation"
    return split


def push_check(added_file: Path, root: Path) -> dict:
    """병합 뒤 main push 검사(#976). 이 push 가 Backlog 엑셀을 추가했을 때만 `compare` 를 돌린다.

    내용 PR 이 병합된 push 에서는 엑셀이 낡은 것이 정상이라 돌리지 않는다(`not_applicable`). 목록을 읽지 못하면 검사 불능이다.
    """
    try:
        added = [ln.strip() for ln in added_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        if not adds_backlog_xlsx(added, root):
            return {"status": NOT_APPLICABLE}
    except (OSError, UnicodeDecodeError, _CannotCheck) as exc:
        return _cannot(f"이 push 가 Backlog 엑셀을 추가했는지 확인하지 못했습니다: {exc}")
    return compare(root)


# ------------------------------------------------------------------ 병합 직전(훅)

def _strip_version(text: str) -> str:
    """`버전:` 줄을 빼고 줄바꿈을 맞춘다(비교용)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(ln for ln in text.split("\n") if not _SRS_VERSION.match(ln))


def merge_guard(repo: str, pr: int, root: Path, client=None) -> dict:
    """산출 PR 이면 PR head 의 SRS 와 base 브랜치의 SRS 가 `버전:` 줄 말고 같은지 본다. status: pass / stale / cannot_check."""
    from checker.ssot_approval import GhError, GhClient

    # 양식 지도를 먼저 본다. Backlog 지도가 없는 저장소(이 하네스 저장소 등)는 gh 를 부르지 않고 대상이 아니다 —
    # 산출과 무관한 모든 PR 의 병합이 gh 조회 실패로 막히지 않게.
    try:
        forms = backlog_forms(root)
    except _CannotCheck as exc:
        return _cannot(str(exc))
    if not forms:
        return {"status": "pass", "reason": NOT_APPLICABLE}

    gh = client or GhClient()
    try:
        info = gh.get_json(f"repos/{repo}/pulls/{pr}")
        base = (info.get("base") or {}).get("ref")
        head_sha = (info.get("head") or {}).get("sha")
        if not base or not head_sha:
            return _cannot(f"PR #{pr} 의 base 브랜치나 head 커밋을 읽지 못했습니다")
        files = gh.get_all(f"repos/{repo}/pulls/{pr}/files")
    except GhError as exc:
        return _cannot(f"PR #{pr} 의 정보를 gh 로 읽지 못했습니다: {exc}")
    added ={f.get("filename", "") for f in files if f.get("status") in ADDED_STATUSES}
    if not any(form["pattern"].fullmatch(name) for form in forms for name in added):
        return {"status": "pass", "reason": NOT_APPLICABLE}

    def srs_at(ref: str) -> str:
        return gh.run(["api", f"repos/{repo}/contents/{SRS_PATH}?ref={quote(ref, safe='')}", "-H", "Accept: application/vnd.github.raw"])

    try:
        head_srs, base_srs = srs_at(head_sha), srs_at(base)
    except GhError as exc:
        return _cannot(f"{SRS_PATH} 를 gh 로 읽지 못했습니다: {exc}")
    if _strip_version(head_srs) != _strip_version(base_srs):
        return {
            "status": STALE,
            "reason": f"엑셀을 만든 뒤 {base} 의 SRS 가 바뀌었습니다(PR head 의 {SRS_PATH} 가 {base} 의 것과 `버전:` 줄 말고 다릅니다).",
            "next": f"다음: {base} 위로 옮겨(/harness:sync) '백로그 뽑아 줘' 로 다시 산출하십시오.",
        }
    return {"status": "pass", "reason": "산출 PR 의 SRS 가 base 와 같습니다"}


# ------------------------------------------------------------------ 진입점

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="산출 Backlog 엑셀이 SRS 와 같은 판인지 확인한다(#976)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("compare", help="작업 폴더의 SRS 로 엑셀을 다시 만들어 저장소 엑셀과 칸 값을 비교한다")
    p1.add_argument("--root", type=Path, default=Path("."))
    p3 = sub.add_parser("push-check", help="병합 뒤(main push): 이 push 가 Backlog 엑셀을 추가했을 때만 compare 를 돌린다")
    p3.add_argument("--added-file", type=Path, required=True, help="이 push 가 추가한 파일 목록(`git diff --diff-filter=A --name-only`)")
    p3.add_argument("--root", type=Path, default=Path("."))
    p2 = sub.add_parser("merge-guard", help="병합 직전: 산출 PR 의 SRS 가 base 의 SRS 와 같은지 본다")
    p2.add_argument("--repo", required=True)
    p2.add_argument("--pr", type=int, required=True)
    p2.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        if args.cmd == "compare":
            result = compare(args.root.resolve())
            code = {SAME: EXIT_SAME, DIFFER: EXIT_DIFFER}.get(result["status"], EXIT_CANNOT)
        elif args.cmd == "push-check":
            result = push_check(args.added_file, args.root.resolve())
            code = {SAME: EXIT_SAME, NOT_APPLICABLE: EXIT_SAME, DIFFER: EXIT_DIFFER}.get(result["status"], EXIT_CANNOT)
        else:
            result = merge_guard(args.repo, args.pr, args.root.resolve())
            code = {"pass": 0, STALE: 1}.get(result["status"], EXIT_CANNOT)
    except Exception as exc:  # noqa: BLE001 - 예상 못 한 오류도 검사 불능이다
        result, code = _cannot(f"예상하지 못한 오류: {type(exc).__name__}: {exc}"), EXIT_CANNOT
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
