"""PR 이 main 에 병합되면 진행 원장(`audit/ledger/*.md`)의 개발 건을 `완료` 로 바꾼다(#346).

재사용 워크플로 `.github/workflows/ledger-complete.yml` 이 main 에 push 가 들어올 때마다
`apply` 를 부른다. 병합된 PR 본문의 `Closes #N` 이 가리키는 이슈 중 제목이 `[DEV-xxx]` 로
시작하는 대표 이슈만 대상이다(`... (DEV-xxx)` 하위 작업 이슈와 DEV 번호 없는 이슈는 아니다).
원장의 그 행 상태 칸을 `완료`, 마지막 PR 칸을 `#<PR>` 로 바꾸고 파일에 쓴다. 커밋과 push 는
워크플로가 한다.

**판정 불능(종료 2)은 아무 파일도 바꾸지 않는다(CLAUDE.md 원칙 7).** gh 호출 실패, 원장 파일은
있는데 그 ID 행이 없거나 둘 이상, 표 형식을 못 읽음, 이슈 본문이 가리킨 파일이 없음. 위반(종료 1)
이라는 개념은 없다 — 할 일이 없거나(0) 못 정하거나(2) 둘 중 하나다.

GitHub 호출은 `checker.ssot_approval.GhClient` 를 그대로 쓴다. 표 파싱은 `checker.pairing` 의
것을 재사용한다.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from checker.pairing import LEDGER_DIR, section_span, table_indexed
from checker.ssot_approval import GhClient, GhError, _force_utf8

EXIT_OK = 0
EXIT_UNKNOWN = 2

DONE = "완료"
OWN_COMMIT_SUBJECT = "docs: 진행 원장 완료 표시"
SECTION = "개발 건"

_CLOSES = re.compile(r"\b(?:closes?|closed|fixes|fix|fixed|resolves?|resolved)\s*:?\s+#(\d+)", re.IGNORECASE)
_REPRESENTATIVE = re.compile(r"^\s*\[(DEV-\d+)\]", re.IGNORECASE)
_LEDGER_LINE = re.compile(r"진행 원장:\s*(DEV-\d+)\s*\(\s*(audit/ledger/[^)\s]+\.md)\s*\)", re.IGNORECASE)
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_DEV_NUM = re.compile(r"^DEV-(\d+)$", re.IGNORECASE)


class Unknown(Exception):
    """판정 불능. 종료코드 2 로 이어지고, 파일은 아무것도 바꾸지 않는다."""


_INLINE_CODE = re.compile(r"`[^`\n]*`")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_QUOTE_LINE = re.compile(r"^[ \t]*>.*$", re.MULTILINE)


def _strip_non_prose(body: str) -> str:
    """HTML 주석·코드 펜스·들여쓴 코드 블록·인라인 코드·인용 줄은 지운다. 예시로 적은 `Closes #N` 이 진짜 닫기로 읽히지 않게."""
    body = _HTML_COMMENT.sub("", body)  # 주석이 펜스·코드 경계를 가리지 않게 가장 먼저 지운다
    kept: list[str] = []
    fence: str | None = None
    for line in body.splitlines():
        marker = line.lstrip()[:3]
        if fence is None and marker in ("```", "~~~"):
            fence = marker
            continue
        if fence is not None:
            if marker == fence:
                fence = None
            continue
        if line.startswith(("    ", "\t")):  # 들여쓴 코드 블록
            continue
        kept.append(line)
    text = _INLINE_CODE.sub("", "\n".join(kept))
    return _QUOTE_LINE.sub("", text)


def closing_issues(body: str | None) -> list[int]:
    """PR 본문에서 `Closes|Fixes|Resolves #N` 의 N 을 나온 순서대로(중복 없이) 모은다."""
    seen: list[int] = []
    for m in _CLOSES.finditer(_strip_non_prose(body or "")):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def representative_id(title: str | None) -> str | None:
    """이슈 제목이 `[DEV-xxx]` 로 시작하면 그 ID(대문자), 아니면 None."""
    m = _REPRESENTATIVE.match(title or "")
    return m.group(1).upper() if m else None


def ledger_file_hint(body: str | None, dev: str) -> str | None:
    """이슈 본문의 `진행 원장: DEV-xxx (audit/ledger/<파일>.md)` 줄에서 파일 경로. 없으면 None."""
    for m in _LEDGER_LINE.finditer(body or ""):
        if _same_dev(m.group(1), dev):
            return m.group(2)
    return None


def _num(dev: str) -> int | None:
    m = _DEV_NUM.match(dev.strip())
    return int(m.group(1)) if m else None


def _same_dev(a: str, b: str) -> bool:
    na, nb = _num(a), _num(b)
    return na is not None and na == nb


def _split_line(line: str) -> tuple[str, str]:
    """(줄 내용, 줄 끝 문자)."""
    content = line.splitlines()[0] if line.splitlines() else ""
    return content, line[len(content):]


def _raw_cells(content: str) -> tuple[list[str], str, str, bool]:
    """표 줄을 칸 원문(공백 포함)으로 나눈다. (칸들, 앞 공백, 뒤 공백, 끝이 `|` 인가)."""
    lead = content[: len(content) - len(content.lstrip())]
    trail = content[len(content.rstrip()):]
    core = content.strip()
    parts = _UNESCAPED_PIPE.split(core)
    # core 는 `|` 로 시작하므로 parts[0] 는 빈 문자열이다.
    closed = core.endswith("|") and len(parts) > 1
    return (parts[1:-1] if closed else parts[1:]), lead, trail, closed


def _with_value(raw: str, value: str) -> str:
    """칸 원문의 앞뒤 공백을 살려 값만 바꾼다. 공백이 없던 칸은 한 칸씩 둔다."""
    if not raw.strip():
        return f" {value} "
    lead = raw[: len(raw) - len(raw.lstrip())] or " "
    trail = raw[len(raw.rstrip()):] or " "
    return f"{lead}{value}{trail}"


def _find_rows(path: Path, rel: str, dev: str, *, skip_without_section: bool) -> tuple[list[str], list[dict]]:
    """원장 파일 한 개에서 `dev` 행을 찾는다. (줄들(줄 끝 포함), [{line, header, cells}]).

    `## 개발 건` 절이 아예 없는 파일은 `skip_without_section` 이면 원장이 아닌 것으로 보고 건너뛴다(빈 결과).
    절은 있는데 표를 못 읽으면 항상 Unknown 이다.
    """
    try:
        # 줄 끝 문자를 그대로 두려고 newline="" 로 읽는다(read_text 는 CRLF 를 LF 로 바꾼다).
        # BOM 은 utf-8 로 읽으면 첫 줄 앞에 남아 그대로 다시 써진다.
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise Unknown(f"`{rel}` 를 읽지 못했다: {exc}") from exc
    lines = text.splitlines(keepends=True)
    parse = text[1:] if text.startswith("﻿") else text
    span = section_span(parse, SECTION)
    if span is None:
        if skip_without_section:
            return lines, []
        raise Unknown(f"`{rel}` 에서 `## {SECTION}` 절을 찾지 못했다(표 형식을 못 읽음).")
    start, end = span
    table = table_indexed(parse.splitlines()[start:end])
    if table is None:
        raise Unknown(f"`{rel}` 의 개발 건 표 머리(`ID` 열)를 찾지 못했다(표 형식을 못 읽음).")
    header, rows = table
    for col in ("상태", "마지막 PR"):
        if col not in header:
            raise Unknown(f"`{rel}` 의 개발 건 표 머리에 `{col}` 열이 없다(표 형식을 못 읽음).")
    found = []
    for offset, cells in rows:
        if cells and _same_dev(cells[0], dev):
            found.append({"line": start + offset, "header": header, "cells": cells})
    return lines, found


def _rewrite_row(rel: str, line: str, header: list[str], pr: int) -> tuple[str, bool]:
    """행 한 줄의 상태·마지막 PR 칸을 바꾼 새 줄과 바뀌었는지."""
    for col in ("상태", "마지막 PR"):
        if col not in header:
            raise Unknown(f"`{rel}` 의 개발 건 표 머리에 `{col}` 열이 없다(표 형식을 못 읽음).")
    content, ending = _split_line(line)
    raw, lead, trail, closed = _raw_cells(content)
    if len(raw) != len(header):
        raise Unknown(f"`{rel}` 의 행 `{content.strip()}` 의 칸 수가 표 머리와 다르다(표 형식을 못 읽음).")
    new = list(raw)
    changed = False
    for col, value in (("상태", DONE), ("마지막 PR", f"#{pr}")):
        i = header.index(col)
        if raw[i].strip() != value:
            new[i] = _with_value(raw[i], value)
            changed = True
    if not changed:
        return line, False
    return f"{lead}|{'|'.join(new)}{'|' if closed else ''}{trail}{ending}", True


_SQUASH_PR = re.compile(r"\(#(\d+)\)\s*$")


def _commit_subject(root: Path, sha: str) -> str:
    """작업 트리의 커밋 제목. 읽지 못하면 Unknown(검사 불능)."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%s", sha],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unknown(f"커밋 {sha[:7]} 의 제목을 읽지 못했다: {exc}") from exc
    if done.returncode != 0:
        raise Unknown(f"커밋 {sha[:7]} 의 제목을 읽지 못했다: {done.stderr.strip()}")
    return done.stdout.strip()


def _merged_prs(client: GhClient, repo: str, sha: str, subject: str) -> list[dict]:
    """커밋에 딸린 PR 중 병합됐고 main 으로 들어간 것(병합 시각순).

    `commits/{sha}/pulls` 가 비어 오는 때가 있어(색인이 늦음), 커밋 제목이 squash 병합 기본 제목
    `... (#N)` 이면 PR N 을 직접 조회한다. 조회가 실패하면 GhError(검사 불능)다.
    """
    prs = client.get_json(f"repos/{repo}/commits/{sha}/pulls") or []
    if not prs:
        m = _SQUASH_PR.search(subject)
        if m:
            prs = [client.get_json(f"repos/{repo}/pulls/{int(m.group(1))}") or {}]
    merged = [p for p in prs if p.get("merged_at") and (p.get("base") or {}).get("ref") == "main"]
    return sorted(merged, key=lambda p: p.get("merged_at") or "")


def apply(client: GhClient, repo: str, shas: list[str], root: Path) -> dict:
    """원장을 고쳐 쓰고 결과를 돌려준다. 판정 불능이면 `Unknown` 이나 `GhError` 를 올리고 아무것도 쓰지 않는다.

    한 push 에 커밋이 여럿일 수 있어 SHA 를 여럿 받는다. 각 커밋의 병합 PR 을 순서대로 모두 처리하고,
    같은 DEV 가 여러 번 나오면 마지막 PR 기준이다.
    """
    root = Path(root)
    ledger_dir = root / LEDGER_DIR
    if not ledger_dir.is_dir():
        return {"status": "skipped", "prs": [], "changed": [], "reason": "audit/ledger 가 없다(원장을 쓰지 않는 저장소)"}

    prs: list[dict] = []
    for sha in shas:
        subject = _commit_subject(root, sha)
        if subject == OWN_COMMIT_SUBJECT:  # 이 워크플로가 만든 커밋은 건너뛴다
            continue
        for pr in _merged_prs(client, repo, sha, subject):
            if all(int(pr["number"]) != int(q["number"]) for q in prs):
                prs.append(pr)
    if not prs:
        return {"status": "skipped", "prs": [], "changed": [], "reason": "병합 PR 없음"}

    # DEV -> (PR 번호, 이슈). 나중 PR 이 앞선 것을 덮는다.
    targets: dict[str, tuple[int, dict]] = {}
    for pr in prs:
        for n in closing_issues(pr.get("body")):
            issue = client.get_json(f"repos/{repo}/issues/{n}") or {}
            dev = representative_id(issue.get("title"))
            if dev:
                targets[dev] = (int(pr["number"]), issue)
    if not targets:
        return {"status": "skipped", "prs": [], "changed": [],
                "reason": "완료 대상 아님(대표 [DEV-xxx] 이슈를 닫지 않았다)"}

    # 먼저 전부 계산하고, 하나라도 못 정하면 아무것도 쓰지 않는다.
    new_text: dict[str, list[str]] = {}
    changed: list[str] = []
    unchanged: list[str] = []
    used_prs: list[int] = []
    for dev, (pr_no, issue) in targets.items():
        hint = ledger_file_hint(issue.get("body"), dev)
        if hint:
            hint_path = (root / hint).resolve()
            if ledger_dir.resolve() not in hint_path.parents or not hint_path.is_file():
                raise Unknown(f"{dev} 이슈 본문이 가리킨 원장 파일 `{hint}` 이(가) 없다.")
            candidates = [hint_path]
        else:
            candidates = sorted(ledger_dir.glob("*.md"))
        hits: list[tuple[str, list[str], dict]] = []
        for path in candidates:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
            lines, found = _find_rows(path, rel, dev, skip_without_section=not hint)
            lines = new_text.get(rel, lines)
            for row in found:
                hits.append((rel, lines, row))
        if not hits:
            where = f"`{hint}`" if hint else "`audit/ledger/*.md`"
            raise Unknown(f"{dev} 행을 {where} 에서 찾지 못했다.")
        if len(hits) > 1:
            places = ", ".join(f"`{rel}`:{row['line'] + 1}" for rel, _, row in hits)
            raise Unknown(f"{dev} 행이 둘 이상이다({places}). 어느 것을 바꿀지 정할 수 없다.")
        rel, lines, row = hits[0]
        lines = list(lines)
        lines[row["line"]], did = _rewrite_row(rel, lines[row["line"]], row["header"], pr_no)
        new_text[rel] = lines
        if did:
            changed.append(dev)
            if pr_no not in used_prs:
                used_prs.append(pr_no)
        else:
            unchanged.append(dev)

    for rel, lines in new_text.items():
        # 줄 끝 문자를 그대로 두려고 newline="" 로 쓴다.
        with open(root / rel, "w", encoding="utf-8", newline="") as f:
            f.write("".join(lines))
    status = "changed" if changed else "unchanged"
    reason = "원장을 고쳤다" if changed else "이미 완료로 표시돼 있어 바꿀 것이 없다"
    return {"status": status, "prs": used_prs, "changed": changed, "unchanged": unchanged, "reason": reason}


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def cmd_apply(args: argparse.Namespace) -> int:
    try:
        result = apply(GhClient(), args.repo, args.sha, Path(args.root))
    except (GhError, Unknown) as exc:
        _print({"status": "unknown", "prs": [], "changed": [], "reason": f"판정 불능: {exc}"})
        return EXIT_UNKNOWN
    _print(result)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger_complete",
        description="병합된 PR 이 닫은 대표 [DEV-xxx] 이슈의 진행 원장 행을 완료로 바꾼다.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    ap = sub.add_parser("apply", help="main 에 들어온 커밋들에 대해 원장을 고쳐 쓴다")
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--sha", required=True, action="append", help="main 에 들어온 커밋 SHA(여러 번 줄 수 있다. 오래된 것부터)")
    ap.add_argument("--root", required=True, help="Project Repository 작업 트리")
    ap.set_defaults(func=cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
