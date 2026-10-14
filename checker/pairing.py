"""SRS·개발 Spec·진행 원장의 번호 짝을 맞춘다(#284).

한 개발의 번호는 세 곳에 나뉘어 적힌다 — SRS 요구사항 표(`REQ-n`, `다음 단계`,
`Development RICEFW ID`), `docs/spec/DEV-n-*.md`(파일명과 `## 근거 요구사항`), 진행 원장
`audit/ledger/*.md` 의 `## 개발 건` 표. doc-guard 규칙은 파일을 하나씩만 보므로 셋이 서로
맞는지는 이 모듈이 저장소 전체를 보고 따로 확인한다. 번호는 숫자로 정규화해 비교한다
(`REQ-3` == `DEV-003`).

- **위반**: 확실히 어긋난 경우(RICEFW ID 불일치, 같은 DEV 중복, 깨진 Spec 링크 …).
- **경고**: 진행 중이라 그럴 수 있는 경우. 통과를 유지하고 코멘트에만 싣는다.
- **검사 불능**: 표 머리를 찾지 못하거나 파일을 읽지 못한 경우. 통과도 위반도 아니다.
- **skipped**: `audit/ledger/` 가 없는 저장소는 대상이 아니다.

SRS 파일이 없으면 SRS 가 걸린 대조만 건너뛰고 원장·Spec 끼리의 대조는 한다. SRS 에 요구사항
표가 아직 없는(`아직 작성 전`) 상태도 같다.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

SRS_PATH = "docs/ssot/SRS.md"
SPEC_DIR = "docs/spec"
LEDGER_DIR = "audit/ledger"

PASS = "pass"
VIOLATION = "violation"
CANNOT_CHECK = "cannot_check"
SKIPPED = "skipped"

EXEMPT_STATUSES = {"on hold", "dropped", "duplicate", "폐기"}
EMPTY_VALUES = {"", "-", "—", "–"}

_REQ_ID = re.compile(r"^REQ-(\d+)$")
_DEV_ID = re.compile(r"^DEV-(\d+)$")
_DEV_IN = re.compile(r"DEV-(\d+)")
_REQ_IN = re.compile(r"REQ-(\d+)(?![\w~])")
_SPEC_NAME = re.compile(r"^DEV-(\d+)")
_LINK = re.compile(r"\]\(([^)]*)\)")


class CannotCheck(Exception):
    """검사할 수 없는 상태. 통과도 위반도 아니다."""


def _fmt(n: int) -> str:
    return f"{n:03d}"


TITLE_UNKNOWN = "제목 미확인"


def titled(prefix: str, n: int, titles: dict[int, str]) -> str:
    """사람에게 보이는 번호 표기 `DEV-002(판매오더 조회 앱)`(#308). 제목을 모르면 `(제목 미확인)` — 추측하지 않는다."""
    return f"{prefix}-{_fmt(n)}({titles.get(n) or TITLE_UNKNOWN})"


def _title_cell(value: str) -> str:
    """제목 칸 값. `-`·`—`·`–`·빈 값은 제목 없음(빈 문자열)이다."""
    value = value.strip()
    return "" if value in EMPTY_VALUES else value


def _ledger_contents(ledger: list[dict]) -> dict[int, str]:
    out: dict[int, str] = {}
    for r in ledger:
        content = r.get("content", "").strip()
        if content not in EMPTY_VALUES:
            out.setdefault(r["id"], content)
    return out


def number_titles(root: Path) -> dict[int, str]:
    """{번호: 제목}. SRS 요구사항 표의 제목이 먼저, SRS 에 없는 번호는 원장 `내용` 칸으로 채운다.

    읽지 못하면 그 출처는 건너뛴다(메시지 꾸밈일 뿐이라 검사 결과를 바꾸지 않는다).
    """
    root = Path(root)
    titles: dict[int, str] = {}
    try:
        reqs, _ = _load_srs(root)
        titles.update({n: r["title"] for n, r in (reqs or {}).items() if r["title"]})
    except CannotCheck:
        pass
    try:
        if (root / LEDGER_DIR).is_dir():
            for n, c in _ledger_contents(_load_ledgers(root)).items():
                titles.setdefault(n, c)
    except CannotCheck:
        pass
    return titles


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _read(path: Path, root: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CannotCheck(f"`{_rel(path, root)}` 를 읽지 못했습니다: {exc}") from exc


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _section(text: str, heading: str) -> list[str] | None:
    """`## heading` 아래 줄들(다음 `## ` 전까지). 코드 펜스 안의 `##` 는 제목이 아니다."""
    lines: list[str] = []
    found = False
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        if not fence and re.match(r"^##\s+", line):
            if found:
                break
            if line[2:].strip() == heading:
                found = True
            continue
        if found:
            lines.append(line)
    return lines if found else None


def _table(lines: list[str]) -> tuple[list[str], list[list[str]]] | None:
    """첫 번째 표(머리줄 첫 칸이 `ID`)의 (머리, 본문 줄 칸들). 표가 없으면 None."""
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in lines:
        if not line.lstrip().startswith("|"):
            if header is not None:
                break
            continue
        cells = _cells(line)
        if header is None:
            if cells and cells[0] == "ID":
                header = cells
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        rows.append(cells)
    return (header, rows) if header is not None else None


def _row(header: list[str], cells: list[str]) -> dict[str, str]:
    return dict(zip(header, cells))


def _load_srs(root: Path) -> tuple[dict[int, dict] | None, bool]:
    """SRS 요구사항 표를 ({번호: {next, status, ricefw(없으면 None)}}, 다음 단계 열 없음 여부) 로.

    SRS 가 없거나 표가 아직 없으면 (None, False). `다음 단계` 열이 없는 옛·Backlog 양식 SRS 는
    spec 스킬과 같이 모든 REQ 를 `개발` 로 본다.
    """
    path = root / SRS_PATH
    if not path.is_file():
        return None, False
    text = _read(path, root)
    section = _section(text, "요구사항")
    if section is None:
        raise CannotCheck(f"`{SRS_PATH}` 에서 `## 요구사항` 절을 찾지 못했습니다.")
    table = _table(section)
    if table is None:
        if any(_REQ_IN.search(line) for line in section):
            raise CannotCheck(f"`{SRS_PATH}` 의 요구사항 표 머리(`ID` 열)를 찾지 못했습니다.")
        return None, False  # 아직 작성 전
    header, rows = table
    no_step_column = "다음 단계" not in header
    reqs: dict[int, dict] = {}
    for cells in rows:
        row = _row(header, cells)
        m = _REQ_ID.match(row.get("ID", ""))
        if not m:
            continue
        status = row.get("Status") or row.get("상태") or ""
        reqs.setdefault(int(m.group(1)), {
            "next": "개발" if no_step_column else row.get("다음 단계", ""),
            "status": status,
            "title": _title_cell(row.get("Title") or row.get("요구사항") or ""),
            "ricefw": row.get("Development RICEFW ID") if "Development RICEFW ID" in header else None,
        })
    return reqs, no_step_column


def _first_block(section: list[str]) -> str:
    """절의 첫 문단(앞의 빈 줄을 건너뛰고 다음 빈 줄 전까지). 근거 REQ 는 여기에만 적는다."""
    block: list[str] = []
    for line in section:
        if not line.strip():
            if block:
                break
            continue
        block.append(line)
    return "\n".join(block)


def _load_specs(root: Path) -> dict[int, list[dict]]:
    """`docs/spec/DEV-n-*.md` → {번호: [{path, reqs(근거 요구사항 절의 REQ 번호 집합 또는 None)}]}."""
    specs: dict[int, list[dict]] = {}
    spec_dir = root / SPEC_DIR
    if not spec_dir.is_dir():
        return specs
    for path in sorted(spec_dir.glob("DEV-*.md")):
        m = _SPEC_NAME.match(path.name)
        if not m:
            continue
        section = _section(_read(path, root), "근거 요구사항")
        reqs = {int(n) for n in _REQ_IN.findall(_first_block(section))} if section is not None else None
        specs.setdefault(int(m.group(1)), []).append({"path": _rel(path, root), "reqs": reqs})
    return specs


def _load_ledgers(root: Path) -> list[dict]:
    """원장 개발 건 표의 줄 → [{file, id(int), spec(원문), dir}]."""
    rows: list[dict] = []
    for path in sorted((root / LEDGER_DIR).glob("*.md")):
        rel = _rel(path, root)
        section = _section(_read(path, root), "개발 건")
        if section is None:
            raise CannotCheck(f"`{rel}` 에서 `## 개발 건` 절을 찾지 못했습니다.")
        table = _table(section)
        if table is None:
            raise CannotCheck(f"`{rel}` 의 개발 건 표 머리(`ID` 열)를 찾지 못했습니다.")
        header, body = table
        if "Spec" not in header:
            raise CannotCheck(f"`{rel}` 의 개발 건 표 머리에 `Spec` 열이 없습니다.")
        for cells in body:
            row = _row(header, cells)
            m = _DEV_ID.match(row.get("ID", ""))
            if m:
                rows.append({"file": rel, "id": int(m.group(1)), "spec": row.get("Spec", ""),
                             "content": row.get("내용", ""), "dir": path.parent})
    return rows


def _link_target(cell: str) -> str | None:
    m = _LINK.search(cell)
    target = m.group(1) if m else cell
    target = unquote(target.strip().strip("<>")).split("#", 1)[0].strip()
    return target or None


def check_pairing(root: Path) -> dict:
    """저장소 루트를 받아 번호 짝을 맞춘다. 결과는 `status`·`violations`·`warnings`·`message`."""
    root = Path(root)
    if not (root / LEDGER_DIR).is_dir():
        return {"status": SKIPPED, "violations": [], "warnings": []}

    violations: list[dict] = []
    warnings: list[dict] = []

    def v(kind: str, file: str, msg: str) -> None:
        violations.append({"kind": kind, "file": file, "message": msg})

    def w(kind: str, file: str, msg: str) -> None:
        warnings.append({"kind": kind, "file": file, "message": msg})

    try:
        reqs, no_step_column = _load_srs(root)
        specs = _load_specs(root)
        ledger = _load_ledgers(root)
    except CannotCheck as exc:
        return {"status": CANNOT_CHECK, "violations": [], "warnings": [], "message": str(exc)}

    titles = {n: r["title"] for n, r in (reqs or {}).items() if r["title"]}
    for n, c in _ledger_contents(ledger).items():
        titles.setdefault(n, c)

    def t(prefix: str, n: int) -> str:
        return titled(prefix, n, titles)

    if not (root / SRS_PATH).is_file():
        w("srs_missing", SRS_PATH, f"`{SRS_PATH}` 가 없어 SRS 와의 대조는 건너뛰었습니다.")

    if reqs is not None and no_step_column:
        w("srs_no_next_step", SRS_PATH, "`다음 단계` 열이 없어 모두 개발로 보고 대조했습니다.")

    by_dev: dict[int, list[dict]] = {}
    for r in ledger:
        by_dev.setdefault(r["id"], []).append(r)

    # 같은 DEV 가 원장 여러 줄에 있다.
    for n, rs in sorted(by_dev.items()):
        if len(rs) > 1:
            where = ", ".join(f"`{r['file']}`" for r in rs)
            v("ledger_duplicate", rs[0]["file"], f"{t('DEV', n)} 가 원장에 {len(rs)}번 있습니다: {where}")

    # 원장 Spec 칸 링크.
    for r in ledger:
        cell = r["spec"].strip()
        if cell in EMPTY_VALUES or cell == "설정":
            continue
        target = _link_target(cell)
        if target is None:
            continue
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target):
            w("spec_link_external", r["file"],
              f"{t('DEV', r['id'])} 의 Spec 칸이 외부 링크라 파일 대조는 하지 않았습니다: `{target}`")
            continue
        path =(r["dir"] / target)
        if not path.is_file():
            v("spec_link_missing", r["file"],
              f"{t('DEV', r['id'])} 의 Spec 칸 링크 대상 파일이 없습니다: `{target}`")
        m = _SPEC_NAME.match(Path(target).name)
        if m and int(m.group(1)) != r["id"]:
            v("spec_link_mismatch", r["file"],
              f"{t('DEV', r['id'])} 줄의 Spec 칸이 다른 번호의 파일을 가리킵니다: `{target}`")

    # Spec 근거 요구사항.
    for n, items in sorted(specs.items()):
        for s in items:
            if s["reqs"] and s["reqs"] != {n}:
                found = ", ".join(t("REQ", x) for x in sorted(s["reqs"]))
                v("spec_req_mismatch", s["path"],
                  f"파일명은 {t('DEV', n)} 인데 `## 근거 요구사항` 의 번호가 {found} 입니다.")

    if reqs is not None:
        for n, req in sorted(reqs.items()):
            label = t("REQ", n)
            step = req["next"].strip()
            ricefw = req["ricefw"]
            if ricefw is not None:
                value = ricefw.strip()
                has_value = value not in EMPTY_VALUES
                if step == "개발" and has_value is False:
                    pass  # 빈칸은 아직 안 정한 것 — 위반이 아니다
                elif step == "개발" and n not in {int(x) for x in _DEV_IN.findall(value)}:
                    v("ricefw_mismatch", SRS_PATH,
                      f"{label} 는 다음 단계가 `개발` 인데 Development RICEFW ID 가 `{value}` 입니다(`DEV-{_fmt(n)}` 이어야 합니다).")
                elif step in ("설정", "미정") and has_value:
                    v("ricefw_not_empty", SRS_PATH,
                      f"{label} 는 다음 단계가 `{step}` 인데 Development RICEFW ID 에 `{value}` 가 적혀 있습니다(비워야 합니다).")

            if req["status"].strip().casefold() in EXEMPT_STATUSES:
                continue
            rows = by_dev.get(n, [])
            if step == "개발":
                spec_cell = rows[0]["spec"].strip() if rows else None
                has_spec = n in specs
                if not rows and not has_spec:
                    w("no_ledger_no_spec", SRS_PATH, f"{label} (개발): 원장 줄도 Spec 도 아직 없습니다.")
                elif not rows:
                    w("no_ledger", SRS_PATH, f"{label} (개발): Spec 은 있으나 원장 줄이 없습니다.")
                elif spec_cell == "설정":
                    w("spec_cell_config", rows[0]["file"],
                      f"{label} 는 다음 단계가 `개발` 인데 원장 {t('DEV', n)} 줄의 Spec 칸이 `설정` 입니다.")
                elif not has_spec:
                    if spec_cell in EMPTY_VALUES:
                        w("spec_not_yet", rows[0]["file"], f"{label} (개발): Spec 은 아직 작성 전입니다(원장 Spec 칸 `-`).")
                    # 링크가 있는데 파일이 없는 것은 위반으로 이미 잡혔다
            elif step == "설정" and not rows:
                w("no_ledger_config", SRS_PATH, f"{label} (설정): 원장에 설정 건 줄이 아직 없습니다.")

        for n, rs in sorted(by_dev.items()):
            if n not in reqs:
                w("ledger_without_req", rs[0]["file"], f"원장의 {t('DEV', n)} 에 대응하는 SRS 요구사항 {t('REQ', n)} 가 없습니다.")
        for n, items in sorted(specs.items()):
            if n not in reqs:
                w("spec_without_req", items[0]["path"], f"Spec {t('DEV', n)} 에 대응하는 SRS 요구사항 {t('REQ', n)} 가 없습니다.")

    return {"status": VIOLATION if violations else PASS, "violations": violations, "warnings": warnings}


def exit_code_for(result: dict) -> int:
    """검사 불능 2, 위반 1, 그 밖 0."""
    status = result.get("status")
    if status == CANNOT_CHECK:
        return 2
    if status == VIOLATION:
        return 1
    return 0
