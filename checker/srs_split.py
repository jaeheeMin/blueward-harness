"""SRS 고치기(내용 PR)와 고객에게 주기(산출 PR)를 가르는 PR 검사(#974).

여럿이 SRS 를 동시에 고치면 `버전:` 줄과 같은 이름 Backlog 엑셀이 부딪힌다. 그래서 SRS 를 둘로 나눈다.

- **내용 PR**: SRS.md 내용과 `audit/changes/` 기록만. `버전:` 줄도 엑셀도 건드리지 않는다.
- **산출 PR**: `버전:` 줄(main + 0.1)과 그 판 이름의 Backlog xlsx 와 산출 기록만. 내용은 고치지 않는다.

이 모듈은 그 약속을 PR diff 로 확인한다. 네트워크도 git 도 쓰지 않고, 워크플로가 만든 두 파일만 본다.

- `diff_text`: `git diff -U0 --no-renames <base>...HEAD` 출력(환경변수 `DOC_GUARD_DIFF_FILE`).
- `added`: `--diff-filter=A` 로 만든 추가 파일 목록(환경변수 `DOC_GUARD_ADDED_FILES`).

판정(위반이면 `violations` 에 규칙 이름과 사유·고칠 방법이 담긴다):

- `mixed`: SRS.md 에서 `버전:` 줄과 그 밖의 줄(빈 줄 제외)이 함께 바뀜. 옛 플러그인이 예전 방식(고치면서 버전을 올림)으로 만든 PR 을 막는다.
- `bump`: `버전:` 줄이 바뀌었는데 새 값이 base 값 + 0.1 이 아니거나, 그 판 이름의 Backlog xlsx 가 같은 PR 에 추가되지 않음.
- `orphan_xlsx`: Backlog xlsx 를 추가했는데 SRS.md `버전:` 이 그 판으로 바뀌지 않음.
- SRS.md 를 이 PR 이 새로 만들었으면(만들기, base 에 없음) `mixed`·`bump` 는 대상이 아니다. 첫 판은 `버전: 0.1` 줄을 그대로 둔다.
  `orphan_xlsx` 는 그대로 본다.
- 읽지 못하면(diff·추가 목록, 양식 지도, 파일명 자리, base 에 `버전:` 줄이 없음) **검사 불능**이다. 통과도 위반도 아니다.
- 이 PR 이 SRS.md 도 Backlog xlsx 도 건드리지 않았으면 대상이 아니다(`not_applicable`).

Backlog xlsx 는 `templates/forms/*.yaml` 중 표에 `원본: SRS` 가 있는 지도의 `산출.폴더`·`산출.파일명` 으로 알아본다(`checker.export`
가 판 이름을 만드는 방식과 같다. 자리 `버전` 은 `메타: 버전` 이어야 한다). 그런 지도가 없는 저장소는 엑셀 짝을 따지지 않는다(`mixed`·`bump` 의 +0.1 만 본다).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from checker.pairing import CANNOT_CHECK, PASS, SRS_PATH, VIOLATION
from checker.version_overlap import _SRS_VERSION, next_version

NOT_APPLICABLE = "not_applicable"

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
_VERSION = r"(\d+(?:\.\d+)*)"


class _CannotCheck(Exception):
    """검사할 수 없는 상태. 통과도 위반도 아니다."""


def _cannot(message: str) -> dict:
    return {"status": CANNOT_CHECK, "violations": [], "message": message}


def srs_changes(diff_text: str) -> dict | None:
    """diff 에서 SRS.md 구역의 바뀐 줄을 읽는다. SRS.md 가 diff 에 없으면 None.

    돌려주는 값: `created`(이 PR 이 새로 만듦), `deleted`, `old`/`new`(`버전:` 줄의 값, 없으면 None),
    `version_lines`(버전 줄의 바뀐 줄 수), `other_lines`(그 밖의 바뀐 줄 수, 공백뿐인 줄 제외).
    """
    section: list[str] | None = None
    sections: list[list[str]] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            section = []
            sections.append(section)
        if section is not None:
            section.append(line)
    target = None
    for sec in sections:
        header = sec[0]
        # `diff --git a/<경로> b/<경로>`. 경로에 공백이 있어도 b/ 쪽 접미사로 비교한다.
        if header.endswith(" b/" + SRS_PATH):
            target = sec
    if target is None:
        return None
    created = deleted = False
    old = new = None
    version_lines = other_lines = 0
    in_hunk = False
    for line in target[1:]:
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            if line.startswith("--- /dev/null") or line.startswith("new file mode"):
                created = True
            elif line.startswith("+++ /dev/null") or line.startswith("deleted file mode"):
                deleted = True
            continue
        if line[:1] not in ("+", "-"):
            continue  # `\ No newline at end of file`
        sign, body = line[0], line[1:]
        m = _SRS_VERSION.match(body)
        if m:
            version_lines += 1
            if sign == "-":
                old = m.group(1)
            else:
                new = m.group(1)
        elif body.strip():
            other_lines += 1
    return {
        "created": created, "deleted": deleted, "old": old, "new": new,
        "version_lines": version_lines, "other_lines": other_lines,
    }


def backlog_forms(root: Path) -> list[dict]:
    """`원본: SRS` 표가 있는 양식 지도마다 `{name, folder, pattern, template}`. 읽지 못한 지도가 있으면 _CannotCheck.

    `template` 은 파일명 틀(`BW_Backlog List_v{버전}.xlsx`). 틀의 자리는 `버전`(`메타: 버전`) 하나뿐이어야 판 이름을 알 수 있다.
    """
    from checker.export import is_srs_map

    folder = root / "templates" / "forms"
    out: list[dict] = []
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise _CannotCheck(f"양식 지도 {f.relative_to(root).as_posix()} 를 읽지 못했습니다: {exc}") from None
        if not isinstance(data, dict) or not isinstance(data.get("시트"), list) or not is_srs_map(data):
            continue
        prod = data.get("산출")
        if not isinstance(prod, dict) or not prod.get("폴더") or not prod.get("파일명"):
            raise _CannotCheck(f"양식 지도 {f.name} 에 `산출.폴더`·`산출.파일명` 이 없어 Backlog 파일 이름을 알 수 없습니다")
        template = str(prod["파일명"])
        slots = prod.get("자리") or {}
        names = _PLACEHOLDER.findall(template)
        for name in names:
            spec = slots.get(name)
            if name.strip() != "버전" or not (isinstance(spec, dict) and str(spec.get("메타", "")).strip() == "버전"):
                raise _CannotCheck(
                    f"양식 지도 {f.name} 의 파일명 자리 {{{name}}} 를 알 수 없습니다(Backlog 파일명은 `버전: {{메타: 버전}}` 자리만 지원합니다)"
                )
        if "버전" not in [n.strip() for n in names]:
            raise _CannotCheck(f"양식 지도 {f.name} 의 파일명 {template!r} 에 `{{버전}}` 자리가 없어 판을 알 수 없습니다")
        prefix = str(prod["폴더"]).replace("\\", "/").strip("/")
        parts = _PLACEHOLDER.split(template)  # 글자, 자리 이름, 글자, ...
        regex = "".join(_VERSION if i % 2 else re.escape(p) for i, p in enumerate(parts))
        out.append({"name": f.stem, "folder": prefix, "template": template, "pattern": re.compile(f"{re.escape(prefix)}/{regex}")})
    return out


def _expected_path(form: dict, version: str) -> str:
    return f"{form['folder']}/{_PLACEHOLDER.sub(version, form['template'])}"


def check_srs_split(diff_text: str, added: list[str], root: Path, srs_listed: bool = False) -> dict:
    """위 판정을 돌린다. 결과 `status` 는 pass / violation / cannot_check / not_applicable.

    `srs_listed` 는 바뀐 파일 목록에 SRS.md 가 있다는 뜻이다. 그런데 diff 에 SRS.md 구역이 없으면 diff 가 불완전한 것이라 검사 불능이다.
    """
    added = [a.replace("\\", "/") for a in added]
    srs = srs_changes(diff_text)
    if srs is None and srs_listed:
        return _cannot(f"바뀐 파일 목록에는 {SRS_PATH} 가 있는데 바뀐 줄 목록(diff)에서 그 구역을 찾지 못해 확인하지 못했습니다.")
    try:
        forms = backlog_forms(root)
    except _CannotCheck as exc:
        return _cannot(str(exc))

    new_xlsx: list[tuple[str, str]] = []  # (경로, 판)
    for path in added:
        for form in forms:
            m = form["pattern"].fullmatch(path)
            if m:
                new_xlsx.append((path, m.group(1)))
    if (srs is None or srs["deleted"]) and not new_xlsx:
        return {"status": NOT_APPLICABLE, "violations": []}

    violations: list[dict] = []
    new_version = srs["new"] if srs else None
    version_changed = bool(srs and srs["version_lines"] and not srs["deleted"])

    if srs and not srs["deleted"] and not srs["created"]:
        if version_changed and srs["other_lines"]:
            violations.append({
                "rule": "mixed",
                "reason": (
                    f"{SRS_PATH} 에서 `버전:` 줄과 그 밖의 내용({srs['other_lines']}줄)이 함께 바뀌었습니다. "
                    "내용을 고치는 PR 과 고객에게 주는(산출) PR 은 나눕니다."
                ),
                "fix": (
                    "내용 PR 에서는 `버전:` 줄과 Backlog 엑셀을 빼고, 고객에게 줄 때 \"백로그 뽑아 줘\" 로 따로 냅니다. "
                    "이 PR 이 옛 플러그인으로 만들어졌다면 /harness:update 로 플러그인을 갱신한 뒤 다시 하십시오."
                ),
            })
        if version_changed:
            if srs["old"] is None:
                return _cannot(
                    f"{SRS_PATH} 의 `버전:` 이 바뀌었는데 기준(main)에 `버전:` 줄이 없어 +0.1 인지 확인하지 못했습니다. "
                    "다음: 이 PR 에서 `버전:` 줄을 지우고 base 의 값을 그대로 둔 채 다시 올리십시오."
                )
            if srs["new"] is None:
                return _cannot(f"{SRS_PATH} 의 `버전:` 줄이 지워졌거나 읽을 수 없는 모양입니다. 새 값을 알 수 없어 확인하지 못했습니다.")
            try:
                want = next_version(srs["old"])
            except ValueError:
                return _cannot(f"{SRS_PATH} 의 기준 `버전: {srs['old']}` 이 숫자 판 번호가 아니라 +0.1 을 계산하지 못했습니다.")
            if srs["new"] != want:
                violations.append({
                    "rule": "bump",
                    "reason": f"`버전:` 이 {srs['old']} → {srs['new']} 로 바뀌었습니다. 새 판은 기준(main)의 {srs['old']} + 0.1 = {want} 여야 합니다.",
                    "fix": f"`버전:` 을 {want} 로 하십시오. 다른 PR 이 먼저 병합됐다면 sync 뒤 그 다음 판으로 다시 산출합니다.",
                })
            for form in forms:
                expected = _expected_path(form, srs["new"])
                if expected not in added:
                    violations.append({
                        "rule": "bump",
                        "reason": f"`버전:` 이 {srs['new']} 로 바뀌었는데 그 판의 Backlog 엑셀 `{expected}` 이 이 PR 에 추가되지 않았습니다.",
                        "fix": "\"백로그 뽑아 줘\" 로 그 판 엑셀을 만들어 같은 PR 에 넣으십시오. 판을 올리지 않으려면 `버전:` 줄을 base 값으로 되돌립니다.",
                    })
    # 만들기(srs["created"])는 첫 판이라 +0.1 도 엑셀도 요구하지 않는다. 엑셀을 같이 냈다면 아래에서 판을 맞춰 본다.

    for path, ver in new_xlsx:
        if not srs or srs["deleted"] or not version_changed or new_version is None:
            violations.append({
                "rule": "orphan_xlsx",
                "reason": f"Backlog 엑셀 `{path}` 을 추가했는데 {SRS_PATH} 의 `버전:` 이 이 PR 에서 바뀌지 않았습니다.",
                "fix": f"엑셀은 산출 PR 에서만 냅니다. `버전:` 을 {ver} 로 하거나(기준 + 0.1 일 때), 엑셀을 PR 에서 뺍니다.",
            })
        elif new_version != ver:
            violations.append({
                "rule": "orphan_xlsx",
                "reason": f"Backlog 엑셀 `{path}` 은 v{ver} 판인데 {SRS_PATH} 의 `버전:` 은 {new_version} 입니다. 판이 서로 다릅니다.",
                "fix": "`버전:` 과 엑셀의 판을 맞추십시오(기준 + 0.1).",
            })

    return {"status": VIOLATION if violations else PASS, "violations": violations}


def touches(names: list[str]) -> tuple[bool, bool]:
    """바뀐 파일 목록에 (SRS.md 가 있는지, .xlsx 가 있는지)."""
    posix = [n.replace("\\", "/") for n in names]
    return SRS_PATH in posix, any(n.lower().endswith(".xlsx") for n in posix)


def evaluate(diff_path: str | None, added_path: str | None, root: Path, names: list[str]) -> dict | None:
    """파일을 읽어 판정한다. 대상이 아니면 None.

    `names` 는 바뀐 파일 목록이다. SRS.md 도 .xlsx 도 없으면 읽지 않고 대상 아님. 환경변수가 없으면(push, 로컬) 대상이 아니다.
    diff 나 추가 목록을 읽지 못하면 검사 불능이다 — 통과로 넘기지 않는다.
    """
    srs_listed, xlsx_listed = touches(names)
    if not diff_path or not added_path or not (srs_listed or xlsx_listed):
        return None
    try:
        diff_text = Path(diff_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return _cannot(f"바뀐 줄 목록(diff) {diff_path} 를 읽지 못했습니다: {exc}")
    try:
        added = [ln.strip() for ln in Path(added_path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, UnicodeDecodeError) as exc:
        return _cannot(f"추가된 파일 목록 {added_path} 를 읽지 못했습니다: {exc}")
    result = check_srs_split(diff_text, added, root, srs_listed)
    return None if result["status"] == NOT_APPLICABLE else result
