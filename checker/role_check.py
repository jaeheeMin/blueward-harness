"""Spec 의 `## Launchpad 노출` 카탈로그가 Role 작업본의 메뉴 배정 표에 있는지 대조한다(이슈 #562, `/harness:role`).

Spec(`docs/spec/DEV-*.md`)에는 개발 건이 만든 Launchpad 타일과 비즈니스 카탈로그가 적혀 있다. 카탈로그가 Role 작업본의 메뉴 배정
표에 없으면 그 개발의 앱이 어느 Role 에도 배정되지 않은 채 남는다. 이 명령은 빠진 카탈로그를 Spec 별 목록으로 낸다.
고치지는 않는다 — 어느 Role 에 배정할지는 사람이 정한다.

    python -P -m checker.role_check --workbook <작업본.md> --form <양식> --sheet <시트> --table <표> --column <카탈로그 열> \\
        [--root <Project Repository 루트, 기본 .>] (--spec-dir docs/spec | --spec <Spec.md>...)

양식·시트·표·열 이름은 호출하는 스킬이 양식 지도에서 읽어 넘긴다(여기에 양식 글자를 박지 않는다). Spec 쪽은 `## Launchpad 노출` 표의
`카탈로그` 열(`--spec-section`·`--spec-column` 으로 바꿀 수 있다)과 `타일 제목` 열(알림용)을 읽는다.

카탈로그 값은 쉼표·줄바꿈·공백으로 나눠 밑줄이 든 ASCII 이름만 취한다(`ZPP_BC_X`). 백틱은 버리고, 칸이 `-`·`없음`·`해당 없음`·`미정`·빈칸이면
카탈로그가 없는 줄이다. 그 밖의 글자가 있는데 이름을 뽑지 못한 칸은 통과로 두지 않고 `unchecked` 로 올린다.

`--form`·`--sheet`·`--table`·`--column` 은 양식 지도(`<root>/templates/forms/<양식>.yaml`)에 있는 이름이어야 한다. 지도에 없는 이름(오타)은
검사 불능이다. 지도에는 있는데 작업본에 그 소절이 아직 없으면 빈 작업본이라 카탈로그가 모두 빠진 것으로 본다.

종료코드와 stdout JSON 한 줄(`status`):
- 0 `ok` — 대조한 Spec 이 하나 이상이고 그 카탈로그가 모두 작업본에 있다.
- 1 `missing` — 작업본에 없는 카탈로그가 있다. `missing` 에 Spec·타일·카탈로그가 나온다.
- 2 `error` — 읽지 못한 파일·이름이 있다(작업본, 지도에 없는 이름, Spec 의 Launchpad 표 구조, 열 없음, 이름을 뽑지 못한 카탈로그 칸).
  대조한 Spec 이 하나도 없을 때도 같다. 통과도 위반도 아니다. 읽은 Spec 의 대조 결과(`missing`)는 함께 낸다.
Launchpad 절이 아예 없는 Spec 은 `skipped` 로 알리고 그것만으로는 오류가 아니다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from checker.export import ExportError, _force_utf8, _parse_table, norm, parse_spec

EXIT_OK, EXIT_MISSING, EXIT_ERROR = 0, 1, 2
_CATALOG = re.compile(r"[A-Za-z0-9/]+(?:_[A-Za-z0-9/]+)+")
_NO_CATALOG = {"", "-", "없음", "해당 없음", "미정"}  # 카탈로그가 없는 줄을 뜻하는 칸 값


def catalogs_in(text: str) -> list[str]:
    """한 칸의 카탈로그 이름들(백틱·설명 글자는 버리고 밑줄이 든 ASCII 이름만)."""
    return list(dict.fromkeys(_CATALOG.findall(text.replace("`", " "))))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ExportError(f"{path} 를 읽지 못했다: {e}") from None


def _map_check(root: Path, form: str, sheet: str, table: str, column: str) -> None:
    """이름이 양식 지도에 있는지 본다. 없으면(오타) ExportError — 빈 작업본과 이름이 틀린 것을 가른다."""
    path = root / "templates" / "forms" / f"{form}.yaml"
    try:
        fmap = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ExportError(f"양식 지도 {path} 를 읽지 못해 이름을 확인하지 못했다: {e}") from None
    sheets = {norm(str(s.get("이름"))): s for s in (fmap or {}).get("시트") or [] if isinstance(s, dict)} if isinstance(fmap, dict) else {}
    if norm(sheet) not in sheets:
        raise ExportError(f"시트 {sheet!r} 이 양식 지도 {form} 에 없다(시트: {', '.join(sheets) or '없음'})")
    tabs = {norm(str(t.get("이름"))): t for t in sheets[norm(sheet)].get("표") or [] if isinstance(t, dict)}
    if norm(table) not in tabs:
        raise ExportError(f"표 {table!r} 이 양식 지도 {form} 의 시트 {sheet!r} 에 없다(표: {', '.join(tabs) or '없음'})")
    cols = [norm(str(k)) for k in (tabs[norm(table)].get("열") or {})]
    if norm(column) not in cols:
        raise ExportError(f"열 {column!r} 이 양식 지도 {form} 의 표 {table!r} 에 없다(열: {', '.join(cols)})")


def workbook_catalogs(path: Path, root: Path, form: str, sheet: str, table: str, column: str) -> set[str]:
    """작업본의 메뉴 배정 표에서 카탈로그 열 값을 모은다.

    이름이 지도에 없으면 ExportError(검사 불능). 지도에 있는데 작업본에 양식·시트·표 소절이 아직 없으면 빈 집합(아직 안 채운 작업본).
    표는 있는데 그 열이 없으면 ExportError."""
    _map_check(root, form, sheet, table, column)
    text = _read(path)
    if not re.search(r"(?m)^###\s", text):  # 소절이 하나도 없는 새 작업본
        return set()
    forms = parse_spec(text)
    body = forms.get(norm(form), {}).get(norm(sheet), (None, {}))[1].get(norm(table))
    if not body:
        return set()
    parsed = _parse_table(body, f"{form} · {sheet} · {table}")
    if not parsed:
        return set()
    header, rows, _ = parsed
    if norm(column) not in header:
        raise ExportError(f"작업본 표 {table!r} 에 {column!r} 열이 없다(머리글: {', '.join(header)})")
    i = header.index(norm(column))
    return {c for r in rows for c in catalogs_in(r[i])}


def spec_catalogs(path: Path, section: str, column: str, tile_column: str) -> tuple[list[tuple[str, str]], list[str]] | None:
    """Spec 의 Launchpad 노출 표 → ([(카탈로그, 타일 제목)], 이름을 뽑지 못한 칸 설명들). 절이 없으면 None. 표 구조가 깨졌거나 열이 없으면 ExportError."""
    lines = re.split(r"\r\n|\n|\r", _read(path))
    start = next((i for i, l in enumerate(lines) if re.match(rf"^##\s+{re.escape(section)}\s*$", l)), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^##\s", lines[i])), len(lines))
    # 절 안의 표는 여럿일 수 있다(타일 표 뒤에 객체 표). 카탈로그 열이 있는 첫 표를 쓴다.
    block: list[str] = []
    tables: list[list[str]] = []
    for l in lines[start + 1:end] + [""]:
        if l.lstrip().startswith("|"):
            block.append(l)
        elif block:
            tables.append(block)
            block = []
    for tb in tables:
        try:
            parsed = _parse_table(tb, f"{path.name} · {section}")
        except ExportError as e:
            raise ExportError(e.reason) from None
        if parsed and norm(column) in parsed[0]:
            header, rows, _ = parsed
            ci = header.index(norm(column))
            ti = header.index(norm(tile_column)) if norm(tile_column) in header else None
            found: list[tuple[str, str]] = []
            unparsed: list[str] = []
            for r in rows:
                tile = r[ti] if ti is not None else ""
                cats = catalogs_in(r[ci])
                found += [(c, tile) for c in cats]
                if not cats and r[ci].strip().strip("`").strip() not in _NO_CATALOG:
                    unparsed.append(f"타일 {tile!r} 의 카탈로그 칸 {r[ci].strip()!r} 에서 이름을 뽑지 못했다")
            return found, unparsed
    raise ExportError(f"{path.name} 의 `## {section}` 에 `{column}` 열이 있는 표가 없다")


def run(args) -> tuple[int, dict]:
    specs = [Path(p) for p in args.spec or []]
    if args.spec_dir:
        d = Path(args.spec_dir)
        if not d.is_dir():
            raise ExportError(f"--spec-dir {d} 가 폴더가 아니다")
        specs += sorted(d.glob("DEV-*.md"))
    have = workbook_catalogs(Path(args.workbook), Path(args.root).resolve(), args.form, args.sheet, args.table, args.column)
    missing: list[dict] = []
    skipped: list[str] = []
    unchecked: list[dict] = []
    checked = 0
    for sp in specs:
        try:
            found = spec_catalogs(sp, args.spec_section, args.spec_column, args.tile_column)
        except ExportError as e:
            unchecked.append({"spec": sp.name, "reason": e.reason})
            continue
        if found is None:
            skipped.append(sp.name)
            continue
        found, unparsed = found
        checked += 1
        unchecked += [{"spec": sp.name, "reason": u} for u in unparsed]
        for cat, tile in dict.fromkeys(found):
            if cat not in have:
                missing.append({"spec": sp.name, "catalog": cat, "tile": tile})
    if not checked and not unchecked:
        unchecked.append({"spec": "", "reason": "대조한 Spec 이 하나도 없다(Spec 이 없거나 모두 `## Launchpad 노출` 절이 없다)"})
    status = "error" if unchecked else ("missing" if missing else "ok")
    report = {
        "status": status, "specs_checked": checked, "missing": missing, "skipped": skipped, "unchecked": unchecked,
        "next": (
            "다음: 읽지 못한 Spec 을 고친 뒤 다시 대조한다. 대조하지 못했다 — 통과가 아니다." if unchecked
            else "다음: 빠진 카탈로그를 어느 Role 에 배정할지 정해 작업본 메뉴 배정 표에 더한다." if missing else ""
        ),
    }
    return {"ok": EXIT_OK, "missing": EXIT_MISSING, "error": EXIT_ERROR}[status], report


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    p = argparse.ArgumentParser(prog="python -m checker.role_check", description="Spec 의 Launchpad 카탈로그가 Role 작업본에 있는지 대조한다.")
    p.add_argument("--workbook", required=True, help="Role 작업본 md")
    p.add_argument("--form", required=True, help="작업본의 양식 이름(`### <양식> · <시트>` 의 앞부분)")
    p.add_argument("--sheet", required=True, help="메뉴 배정 표가 있는 시트")
    p.add_argument("--table", required=True, help="메뉴 배정 표 이름")
    p.add_argument("--column", required=True, help="표의 카탈로그 열 이름")
    p.add_argument("--root", default=".", help="Project Repository 루트(양식 지도 templates/forms/ 를 찾는다)")
    p.add_argument("--spec", action="append", help="대조할 Spec(여러 번 줄 수 있다)")
    p.add_argument("--spec-dir", help="이 폴더의 DEV-*.md 를 모두 대조한다")
    p.add_argument("--spec-section", default="Launchpad 노출")
    p.add_argument("--spec-column", default="카탈로그")
    p.add_argument("--tile-column", default="타일 제목")
    args = p.parse_args(argv)
    try:
        if not args.spec and not args.spec_dir:
            raise ExportError("--spec 이나 --spec-dir 가 필요하다")
        code, report = run(args)
    except ExportError as e:
        code, report = EXIT_ERROR, {"status": "error", "missing": [], "skipped": [], "unchecked": [{"spec": "", "reason": e.reason}],
                                    "next": "다음: 읽지 못한 원인을 고친 뒤 다시 대조한다. 대조하지 못했다 — 통과가 아니다."}
    except Exception as e:  # 예상하지 못한 오류도 검사 불능(2)이다
        code, report = EXIT_ERROR, {"status": "error", "missing": [], "skipped": [], "unchecked": [{"spec": "", "reason": f"예상하지 못한 오류({type(e).__name__}): {e}"}],
                                    "next": "다음: 읽지 못한 원인을 고친 뒤 다시 대조한다. 대조하지 못했다 — 통과가 아니다."}
    sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
