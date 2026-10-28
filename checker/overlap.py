"""Spec 끼리 같은 SAP 객체를 만들거나 고치는지 본다(#292).

한 개발이 DEV 둘로 쪼개지면 두 Spec 이 같은 객체를 건드리게 된다. 쪼개진 것은 아닌지 확인하게 하려고
같은 객체를 둘 이상의 Spec 이 만들거나 고치는 곳을 알린다. 각 Spec 의 `## 사용 객체` 표(#287)를 읽어 작업이 `생성`·`수정` 인 행의
(종류, 대문자로 맞춘 이름)이 Spec 둘 이상에 나오면 **경고**한다. `참조` 행은 비교하지 않는다.

- 이 PR 이 바꾼 Spec 목록(`changed_specs`)을 받으면 그 Spec 이 낀 겹침만 경고하고, 바뀐 Spec 이 안 낀
  기존 겹침은 `unrelated` 개수로만 남긴다. 목록이 None 이면 전부 본다(#503).
- 공용 객체 종류(`rules/cross-checks/shared-objects.yaml` 의 `공용_종류`, 기본 `Message Class`)는 여러 개발이
  함께 쓰는 객체라 겹쳐도 경고하지 않고 `shared` 개수와 `shared_kinds` 로 남긴다. 설정을 읽을 수 없으면 검사 불능.
- **경고만** 한다. 위반은 없다 — 쪼갠 뒤 한쪽이 다른 쪽을 쓰는 것은 정당할 수 있다.
- 이름이 비었거나 영문자(또는 `/` 네임스페이스)로 시작하지 않는 행(`미정`, `-` 등)은 비교에서 빼고
  `name_tbd` 개수로만 남긴다.
- 대상은 번호 짝 검사와 같이 `DEV-` 로 시작하는 Spec 만이다(README 등 제외).
- 표 절이 없는 Spec 은 비교에서 빼고 개수만 남긴다(`no_table`).
- Spec 을 읽지 못하거나, 절은 있는데 표가 없거나 머리·칸 수·작업 값이 틀려 읽을 수 없으면
  **검사 불능**이다. 그 Spec 의 경로와 사유를 남긴다. 통과도 위반도 아니다.
- `docs/spec/` 폴더가 없는 저장소는 대상이 아니다(skipped).

표 파서는 `md_table` 규칙과 같은 것을 쓴다(형식 위반 자체는 그 규칙이 잡는다).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from checker.pairing import CANNOT_CHECK, PASS, SKIPPED, SPEC_DIR, number_titles, titled
from checker.rules.md_table import plain_cell, read_section_table

SECTION = "사용 객체"
COLUMNS = ["종류", "이름", "작업", "비고"]
COMPARED = {"생성", "수정"}
ALL_WORK = COMPARED | {"참조"}

SHARED_FILE = "rules/cross-checks/shared-objects.yaml"
SHARED_KEY = "공용_종류"
DEFAULT_SHARED = ["Message Class"]
# rules/ 하위 폴더라 엔진 규칙 로더(rules/ 최상위 *.yaml 만 읽음)가 건드리지 않는다.

_DEV = re.compile(r"DEV-(\d+)")
_NAME_START = re.compile(r"[A-Za-z/]")


def _dev_of(name: str) -> str:
    m = _DEV.match(name)
    return f"DEV-{int(m.group(1)):03d}" if m else Path(name).stem


def _dev_label(dev: str, titles: dict[int, str]) -> str:
    """메시지용 `DEV-002(제목)`(#308). 번호로 읽히지 않는 이름(`DEV-` 없는 파일명)은 그대로 둔다."""
    m = _DEV.fullmatch(dev)
    return titled("DEV", int(m.group(1)), titles) if m else dev


def _objects(text: str) -> tuple[list[tuple[str, str, str]], int] | None:
    """((종류, 이름 대문자, 작업) 행들, 이름 미정 행 수). 절이 없으면 None. 읽을 수 없는 모양이면 ValueError."""
    found, table = read_section_table(text, SECTION)
    if not found:
        return None
    if table is None:
        raise ValueError(f"`## {SECTION}` 절은 있는데 표가 없습니다")
    header, rows = table
    if header != COLUMNS:
        raise ValueError(f"`## {SECTION}` 표의 머리가 {' | '.join(COLUMNS)} 가 아닙니다")
    out = []
    tbd = 0
    for i, cells in enumerate(rows, start=1):
        if not any(cells):
            continue  # 템플릿 자리표시 줄
        if len(cells) != len(COLUMNS):
            raise ValueError(f"표 {i}번째 행의 칸 수가 {len(COLUMNS)}칸이 아닙니다")
        kind, name, work = plain_cell(cells[0]), plain_cell(cells[1]), plain_cell(cells[2])
        if work not in ALL_WORK:
            raise ValueError(f"표 {i}번째 행의 작업 '{work}' 을 읽을 수 없습니다(생성·수정·참조)")
        if work in COMPARED:
            if not name or not _NAME_START.match(name):
                tbd += 1  # 이름 미정: 비교할 수 없다
                continue
            if not kind:
                raise ValueError(f"표 {i}번째 행의 종류가 비었습니다")
            out.append((kind, name.upper(), work))
    return out, tbd


def _kind_key(kind: str) -> str:
    return kind.strip().casefold()


def load_shared_kinds(root: Path) -> list[str]:
    """공용 객체 종류 목록. 파일·키가 없으면 기본값, `[]` 이면 제외 없음. 읽을 수 없는 모양이면 ValueError."""
    path = root / SHARED_FILE
    if not path.exists():
        return list(DEFAULT_SHARED)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"`{SHARED_FILE}` 를 읽지 못했습니다: {exc}") from exc
    if raw is None:
        return list(DEFAULT_SHARED)
    if not isinstance(raw, dict):
        raise ValueError(f"`{SHARED_FILE}` 의 최상위가 사전이어야 합니다")
    unknown = [str(k) for k in raw if k != SHARED_KEY]
    if unknown:
        raise ValueError(f"`{SHARED_FILE}` 에 모르는 키가 있습니다: {', '.join(unknown)} (쓸 수 있는 키: {SHARED_KEY})")
    if SHARED_KEY not in raw:
        return list(DEFAULT_SHARED)
    value = raw[SHARED_KEY]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"`{SHARED_FILE}` 의 {SHARED_KEY} 는 문자열 목록이어야 합니다(지금: {value!r})")
    return [v.strip() for v in value if v.strip()]


def check_overlap(root: Path, changed_specs: list[str] | None = None) -> dict:
    """`root/docs/spec/*.md` 의 객체 겹침. 결과는 pass(경고 포함)/cannot_check/skipped.

    changed_specs: 이 PR 이 바꾼 Spec 경로(`docs/spec/xxx.md`). 주면 그 Spec 이 낀 겹침만 경고한다. None 이면 전부.
    """
    spec_dir = root / SPEC_DIR
    empty = {"warnings": [], "no_table": 0, "no_table_files": [], "name_tbd": 0, "cannot_check": [],
             "unrelated": 0, "shared": 0, "shared_kinds": []}
    if not spec_dir.is_dir():
        return {"status": SKIPPED, **empty}
    try:
        shared_kinds = load_shared_kinds(root)
    except ValueError as exc:
        # 공용 종류를 모르면 어느 겹침을 빼야 할지 모른다. 경고를 내지도 않고 검사 불능으로 알린다.
        return {"status": CANNOT_CHECK, **empty, "config_error": str(exc), "message": str(exc)}
    shared_keys = {_kind_key(k) for k in shared_kinds}
    changed = None if changed_specs is None else {Path(c).as_posix().removeprefix("./") for c in changed_specs}

    by_key: dict[tuple[str, str], dict[str, dict]] = {}
    no_table: list[str] = []
    name_tbd = 0
    cannot: list[dict] = []
    for path in sorted(spec_dir.glob("DEV-*.md")):
        rel = f"{SPEC_DIR}/{path.name}"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            cannot.append({"file": rel, "message": f"읽지 못했습니다: {exc}"})
            continue
        try:
            rows = _objects(text)
        except ValueError as exc:
            cannot.append({"file": rel, "message": str(exc)})
            continue
        if rows is None:
            no_table.append(rel)
            continue
        rows, tbd = rows
        name_tbd += tbd
        for kind, name, work in rows:
            entry = by_key.setdefault((kind, name), {}).setdefault(
                rel, {"file": rel, "dev": _dev_of(path.name), "works": []}
            )
            if work not in entry["works"]:
                entry["works"].append(work)

    titles = number_titles(root)
    warnings = []
    unrelated = 0
    shared = 0
    shared_seen: list[str] = []
    for (kind, name), specs in sorted(by_key.items()):
        if len(specs) < 2:
            continue
        if changed is not None and not (set(specs) & changed):
            unrelated += 1
            continue
        if _kind_key(kind) in shared_keys:
            shared += 1
            if kind not in shared_seen:
                shared_seen.append(kind)
            continue
        items = [{"file": s["file"], "dev": s["dev"], "work": "·".join(s["works"])} for s in specs.values()]
        who = "; ".join(f"{_dev_label(i['dev'], titles)} {i['work']}" for i in items)
        warnings.append({
            "kind": kind, "name": name, "specs": items,
            "message": f"{kind} {name} — 같은 객체를 여러 Spec 이 다룹니다: {who}",
        })

    result = {
        "status": CANNOT_CHECK if cannot else PASS,
        "warnings": warnings,
        "no_table": len(no_table),
        "no_table_files": no_table,
        "name_tbd": name_tbd,
        "cannot_check": cannot,
        "unrelated": unrelated,
        "shared": shared,
        "shared_kinds": shared_seen,
    }
    if cannot:
        result["message"] = "; ".join(f"`{c['file']}` {c['message']}" for c in cannot)
    return result
