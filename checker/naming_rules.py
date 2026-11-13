"""개발 표준 이름 규칙 검사(#943).

고객사마다 개발 표준이 다르므로 이름 규칙은 코드가 아니라 데이터다(CLAUDE.md 원칙 2). Project Repository 의
`conventions/naming.yaml` 이 객체 종류별 이름 형식(정규식)과 최대 길이를 정하고, 이 모듈이 읽어 판정한다.
SAP 객체를 만들거나 이름을 바꾸기 직전 훅(`mcp_source_guard.py`)과 PR 검사(`scripts/check_changed.py`)가 부른다.

파일 모양(예시는 `plugins/harness/conventions/naming.example.yaml`):

    영역코드: [SD, LE]            # 형식 안의 `{영역}` 이 `(SD|LE)` 로 바뀐다
    객체:
      MSAG: {형식: '^Z{영역}$', 최대_길이: 20}
    예외: [ZMM_MSG]               # 형식·길이 검사를 건너뛰는 이름

- 객체 종류는 ADT objtype 앞 4글자(CLAS, DDLS, TABL ...)다. `TABL/DT` 처럼 하위 종류까지 적으면 그 종류만 따로 본다.
  하위 종류 없이 종류만 알 때(파일 이름, 이름 바꾸기)는 `TABL` 규칙이 있으면 그것을, 없고 `TABL/..` 규칙만 있으면
  그중 하나라도 맞으면 통과로 본다.
- 이름 비교는 대소문자를 무시하고 형식은 전체 일치(fullmatch)다.
- 파일에 없는 종류는 규칙이 없는 것이라 통과다(위반 아님). 파일 자체가 없으면 검사하지 않는다(`not_applicable`).
- 알 수 없는 키, 정규식 오류, 형식이 없는 항목은 설정 오류다 — 검사 불능으로 낸다(원칙 7).

종료코드: 0 통과(또는 검사 안 함), 1 위반, 2 검사 불능.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

CONFIG_RELATIVE_PATH = "conventions/naming.yaml"
SRC_PREFIX = "src/"

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_CANNOT_CHECK = 2

_TOP_KEYS = {"영역코드", "객체", "예외"}
_RULE_KEYS = {"형식", "최대_길이"}
_TYPE_KEY_RE = re.compile(r"^[A-Z]{4}(/[A-Z0-9]{1,4})?$")
AREA_TOKEN = "{영역}"


class NamingConfigError(RuntimeError):
    """`conventions/naming.yaml` 을 읽을 수 없다. 통과도 위반도 아닌 검사 불능이다."""


class Rule:
    def __init__(self, kind: str, pattern: str, regex: re.Pattern[str], max_length: int | None):
        self.kind = kind
        self.pattern = pattern  # 사람에게 보일 원문(영역 치환 전)
        self.regex = regex
        self.max_length = max_length


class NamingConfig:
    def __init__(self, path: Path, rules: dict[str, Rule], exceptions: frozenset[str]):
        self.path = path
        self.rules = rules
        self.exceptions = exceptions


def find_config(start: Path) -> Path | None:
    """`start` 에서 위로 올라가며 `conventions/naming.yaml` 을 찾는다. `.git` 이 있는 폴더까지만 본다."""
    try:
        start = start.resolve()
    except OSError:
        pass
    for parent in [start, *start.parents]:
        candidate = parent / CONFIG_RELATIVE_PATH
        if candidate.is_file():
            return candidate
        if (parent / ".git").exists():
            return None
    return None


def parse_config(text: str, path: Path) -> NamingConfig:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 이 올바른 YAML 이 아니다: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 최상위는 키와 값의 목록이어야 한다")
    unknown = sorted(str(k) for k in set(data) - _TOP_KEYS)
    if unknown:
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 에 알 수 없는 키가 있다: {', '.join(unknown)}")

    areas = data.get("영역코드") or []
    if not isinstance(areas, list) or not all(isinstance(a, str) and a.strip() for a in areas):
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 영역코드는 문자열 목록이어야 한다")
    area_group = "(" + "|".join(re.escape(a.strip()) for a in areas) + ")" if areas else None

    exceptions = data.get("예외") or []
    if not isinstance(exceptions, list) or not all(isinstance(e, str) and e.strip() for e in exceptions):
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 예외는 이름 문자열 목록이어야 한다")

    objects = data.get("객체") or {}
    if not isinstance(objects, dict):
        raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 객체는 종류별 규칙 목록이어야 한다")
    rules: dict[str, Rule] = {}
    for raw_kind, item in objects.items():
        kind = str(raw_kind).strip().upper()
        if not _TYPE_KEY_RE.match(kind):
            raise NamingConfigError(
                f"{CONFIG_RELATIVE_PATH} 의 객체 종류 '{raw_kind}' 가 올바르지 않다(CLAS 처럼 영문 4글자, 또는 TABL/DT)"
            )
        if not isinstance(item, dict):
            raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 항목은 형식·최대_길이를 가진 목록이어야 한다")
        extra = sorted(str(k) for k in set(item) - _RULE_KEYS)
        if extra:
            raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 에 알 수 없는 키가 있다: {', '.join(extra)}")
        pattern = item.get("형식")
        if not isinstance(pattern, str) or not pattern.strip():
            raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 에 형식이 없다")
        expanded = pattern
        if AREA_TOKEN in pattern:
            if area_group is None:
                raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 형식이 {AREA_TOKEN} 을 쓰는데 영역코드가 없다")
            expanded = pattern.replace(AREA_TOKEN, area_group)
        try:
            regex = re.compile(expanded, re.IGNORECASE)
        except re.error as exc:
            raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 형식 '{pattern}' 이 올바른 정규식이 아니다: {exc}") from exc
        max_length = item.get("최대_길이")
        if max_length is not None and (isinstance(max_length, bool) or not isinstance(max_length, int) or max_length <= 0):
            raise NamingConfigError(f"{CONFIG_RELATIVE_PATH} 의 {kind} 최대_길이는 1 이상의 정수여야 한다")
        rules[kind] = Rule(kind, pattern, regex, max_length)
    return NamingConfig(path, rules, frozenset(e.strip().upper() for e in exceptions))


def load_config(path: Path) -> NamingConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NamingConfigError(f"{path} 을 읽지 못했다: {exc}") from exc
    return parse_config(text, path)


def _rules_for(cfg: NamingConfig, kind: str) -> list[Rule]:
    """종류(`TABL/DT` 또는 `TABL`)에 맞는 규칙들. 없으면 빈 목록."""
    kind = kind.strip().upper()
    if kind in cfg.rules:
        return [cfg.rules[kind]]
    head = kind[:4]
    if "/" in kind and head in cfg.rules:
        return [cfg.rules[head]]
    if "/" not in kind:
        return [r for k, r in cfg.rules.items() if k.startswith(head + "/")]
    return []


def _judge_one(rule: Rule, name: str) -> list[str]:
    reasons = []
    if not rule.regex.fullmatch(name):
        reasons.append(f"형식 {rule.pattern} 에 맞지 않는다")
    if rule.max_length is not None and len(name) > rule.max_length:
        reasons.append(f"{len(name)}자라 최대 {rule.max_length}자를 넘는다")
    return reasons


def check_name(cfg: NamingConfig, kind: str, name: str) -> dict:
    """이름 하나를 판정한다. status: pass, violation, no_rule(규칙 없는 종류), exception(예외 목록)."""
    kind = kind.strip().upper()
    name = name.strip()
    item = {"type": kind, "name": name}
    if name.upper() in cfg.exceptions:
        return {**item, "status": "exception"}
    rules = _rules_for(cfg, kind)
    if not rules:
        return {**item, "status": "no_rule"}
    outcomes = [(r, _judge_one(r, name)) for r in rules]
    if any(not reasons for _, reasons in outcomes):
        return {**item, "status": "pass"}
    return {
        **item,
        "status": "violation",
        "reasons": [reason for _, reasons in outcomes for reason in reasons],
        "rules": [
            {"type": r.kind, "형식": r.pattern, "최대_길이": r.max_length} for r, _ in outcomes
        ],
    }


def object_from_path(path: str) -> tuple[str, str] | None:
    """abapGit 파일 경로(`src/<이름>.<종류>.<확장자>`)에서 (종류, 이름). 객체 파일이 아니면 None.

    `.clas.locals_imp.abap`·`.clas.testclasses.abap`·`.clas.xml` 은 같은 객체의 딸림 파일이라 같은 값이 나온다.
    패키지(`package.devc.xml`)는 이름이 파일에 없어 건너뛴다. 이름의 `#` 은 네임스페이스 `/` 다.
    """
    posix = Path(path).as_posix()
    if not posix.startswith(SRC_PREFIX):
        return None
    parts = posix.rsplit("/", 1)[-1].split(".")
    if len(parts) < 3 or not parts[0]:
        return None
    kind = parts[1].upper()
    if not re.fullmatch(r"[A-Z]{4}", kind) or kind == "DEVC":
        return None
    return kind, parts[0].replace("#", "/").upper()


def check_files(cfg: NamingConfig, paths: list[str]) -> dict:
    """파일 경로 목록에서 객체를 뽑아(중복 한 번) 검사한다."""
    seen: dict[tuple[str, str], str] = {}
    for p in paths:
        found = object_from_path(p)
        if found and found not in seen:
            seen[found] = p
    results = []
    for (kind, name), first_path in seen.items():
        results.append({**check_name(cfg, kind, name), "file": first_path})
    violations = [r for r in results if r["status"] == "violation"]
    return {
        "status": "violation" if violations else "pass",
        "checked": len(results),
        "violations": violations,
        "config": str(cfg.path),
    }


def evaluate_files(paths: list[str], root: Path) -> dict:
    """`root` 에서 설정을 찾아 파일 목록을 검사한다. 설정이 없으면 `not_applicable`, 못 읽으면 `cannot_check`."""
    config_path = find_config(root)
    if config_path is None:
        return {"status": "not_applicable"}
    try:
        cfg = load_config(config_path)
    except NamingConfigError as exc:
        return {"status": "cannot_check", "message": str(exc)}
    return check_files(cfg, paths)


def exit_code_for(result: dict) -> int:
    status = result.get("status")
    if status == "cannot_check":
        return EXIT_CANNOT_CHECK
    if status == "violation":
        return EXIT_VIOLATION
    return EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="naming_rules", description="개발 표준 이름 규칙(conventions/naming.yaml)을 검사한다.")
    sub = p.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check", help="객체 하나의 종류와 이름을 검사한다")
    one.add_argument("--type", required=True, help="객체 종류(CLAS 또는 CLAS/OC)")
    one.add_argument("--name", required=True)
    one.add_argument("--root", default=".", help="설정을 찾기 시작할 폴더")
    many = sub.add_parser("files", help="abapGit 파일 경로 목록(한 줄에 하나)을 검사한다")
    many.add_argument("listing", help="경로 목록 파일")
    many.add_argument("--root", default=".")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    if args.command == "check":
        config_path = find_config(root)
        if config_path is None:
            result: dict = {"status": "not_applicable"}
        else:
            try:
                result = check_name(load_config(config_path), args.type, args.name)
                result["config"] = str(config_path)
            except NamingConfigError as exc:
                result = {"status": "cannot_check", "message": str(exc)}
    else:
        try:
            lines = Path(args.listing).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            result = {"status": "cannot_check", "message": f"목록 {args.listing} 를 읽지 못했다: {exc}"}
        else:
            result = evaluate_files([ln.strip() for ln in lines if ln.strip()], root)
    print(json.dumps(result, ensure_ascii=False))
    return exit_code_for(result)


if __name__ == "__main__":
    raise SystemExit(main())
