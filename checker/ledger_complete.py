"""main 에 병합된 PR 이 대표 `[DEV-xxx]` 이슈를 닫았는데 진행 원장(`audit/ledger/*.md`)의 그 행이
`완료` 가 아니면 알린다(#346, #445). 파일을 쓰지 않는 검사기다.

원장 `완료` 는 `/harness:deliver` 가 대표 이슈를 `Closes` 하는 PR 에 처음부터 담아 PR 과 함께
병합된다. main 이 보호 규칙(PR 필수) 아래 있으면 Actions 가 직접 push 할 수 없고, push 용 deploy
key secret 은 브랜치 push 워크플로로 새어 나가 규칙을 우회하는 뒷문이 되므로(#445) 쓰지 않는다.
재사용 워크플로 `.github/workflows/ledger-complete.yml` 이 main 에 push 가 들어올 때마다 `check` 를
부른다. 병합된 PR 본문의 `Closes #N` 이 가리키는 이슈 중 제목이 `[DEV-xxx]` 로 시작하는 대표
이슈만 대상이다(`... (DEV-xxx)` 하위 작업 이슈와 DEV 번호 없는 이슈는 아니다).

종료 0 은 통과(모두 완료이거나 볼 것 없음), 1 은 위반(`완료` 아닌 행이 있다), 2 는 **판정 불능**이다
(CLAUDE.md 원칙 7). gh 호출 실패, 원장 파일은 있는데 그 ID 행이 없거나 둘 이상, 표 형식을 못 읽음,
이슈 본문이 가리킨 파일이 없음은 통과도 위반도 아니다.

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
EXIT_VIOLATION = 1
EXIT_UNKNOWN = 2

DONE = "완료"
SECTION = "개발 건"

_CLOSES = re.compile(r"\b(?:closes?|closed|fixes|fix|fixed|resolves?|resolved)\s*:?\s+#(\d+)", re.IGNORECASE)
_REPRESENTATIVE = re.compile(r"^\s*\[(DEV-\d+)\]", re.IGNORECASE)
_LEDGER_LINE = re.compile(r"진행 원장:\s*(DEV-\d+)\s*\(\s*(audit/ledger/[^)\s]+\.md)\s*\)", re.IGNORECASE)
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")
_DEV_NUM = re.compile(r"^DEV-(\d+)$", re.IGNORECASE)


class Unknown(Exception):
    """판정 불능. 종료코드 2 로 이어진다."""


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


def _find_rows(path: Path, rel: str, dev: str, *, skip_without_section: bool) -> list[dict]:
    """원장 파일 한 개에서 `dev` 행을 찾는다. [{line, state}] (`line` 은 0부터).

    `## 개발 건` 절이 아예 없는 파일은 `skip_without_section` 이면 원장이 아닌 것으로 보고 건너뛴다(빈 결과).
    절은 있는데 표를 못 읽으면 항상 Unknown 이다.
    """
    try:
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise Unknown(f"`{rel}` 를 읽지 못했다: {exc}") from exc
    parse = text[1:] if text.startswith("﻿") else text  # BOM
    span = section_span(parse, SECTION)
    if span is None:
        if skip_without_section:
            return []
        raise Unknown(f"`{rel}` 에서 `## {SECTION}` 절을 찾지 못했다(표 형식을 못 읽음).")
    start, end = span
    table = table_indexed(parse.splitlines()[start:end])
    if table is None:
        raise Unknown(f"`{rel}` 의 개발 건 표 머리(`ID` 열)를 찾지 못했다(표 형식을 못 읽음).")
    header, rows = table
    if "상태" not in header:
        raise Unknown(f"`{rel}` 의 개발 건 표 머리에 `상태` 열이 없다(표 형식을 못 읽음).")
    col = header.index("상태")
    body = parse.splitlines()
    found = []
    for offset, cells in rows:
        if cells and _same_dev(cells[0], dev):
            # pairing 의 칸 나누기는 `\|` 도 칸 경계로 세므로, 이 줄은 이스케이프를 살려 다시 나눈다.
            line = body[start + offset].strip()
            raw = [c.strip() for c in _UNESCAPED_PIPE.split(line.strip("|"))]
            if len(raw) <= col:
                raise Unknown(f"`{rel}` 의 {dev} 행에 `상태` 칸이 없다(표 형식을 못 읽음).")
            found.append({"line": start + offset, "state": raw[col]})
    return found


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


def expand_shas(root: Path, sha: str, before: str | None) -> list[str]:
    """push 한 번에 커밋이 여럿이면 `before..sha` 를 오래된 것부터 전부, 아니면 `[sha]`.

    `before` 가 비었거나 전부 0(새 브랜치)이거나 히스토리에 없으면 `[sha]` 하나로 본다.
    """
    if not before or set(before) == {"0"}:
        return [sha]
    try:
        have = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{before}^{{commit}}"],
                              capture_output=True, timeout=30)
        if have.returncode != 0:
            return [sha]
        done = subprocess.run(["git", "-C", str(root), "rev-list", "--reverse", f"{before}..{sha}"],
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unknown(f"커밋 범위 {before[:7]}..{sha[:7]} 를 읽지 못했다: {exc}") from exc
    if done.returncode != 0:
        raise Unknown(f"커밋 범위 {before[:7]}..{sha[:7]} 를 읽지 못했다: {done.stderr.strip()}")
    return done.stdout.split() or [sha]


def check(client: GhClient, repo: str, shas: list[str], root: Path) -> dict:
    """병합 PR 이 닫은 대표 [DEV-xxx] 이슈의 원장 행이 `완료` 인지 본다. 아무 파일도 쓰지 않는다.

    판정 불능이면 `Unknown` 이나 `GhError` 를 올린다. 한 push 에 커밋이 여럿일 수 있어 SHA 를 여럿 받고,
    각 커밋의 병합 PR 을 모두 본다. 같은 DEV 를 여러 PR 이 닫았으면 마지막 PR 기준이다.
    status: ok(모두 완료) / skipped(볼 것 없음) / violation(완료가 아닌 행이 있다).
    """
    root = Path(root)
    ledger_dir = root / LEDGER_DIR
    if not ledger_dir.is_dir():
        return {"status": "skipped", "prs": [], "pending": [], "reason": "audit/ledger 가 없다(원장을 쓰지 않는 저장소)"}

    prs: list[dict] = []
    for sha in shas:
        subject = _commit_subject(root, sha)
        for pr in _merged_prs(client, repo, sha, subject):
            if all(int(pr["number"]) != int(q["number"]) for q in prs):
                prs.append(pr)
    if not prs:
        return {"status": "skipped", "prs": [], "pending": [], "reason": "병합 PR 없음"}

    # DEV -> (PR 번호, 이슈). 나중 PR 이 앞선 것을 덮는다.
    targets: dict[str, tuple[int, dict]] = {}
    for pr in prs:
        for n in closing_issues(pr.get("body")):
            issue = client.get_json(f"repos/{repo}/issues/{n}") or {}
            dev = representative_id(issue.get("title"))
            if dev:
                targets[dev] = (int(pr["number"]), issue)
    if not targets:
        return {"status": "skipped", "prs": [], "pending": [],
                "reason": "확인 대상 아님(대표 [DEV-xxx] 이슈를 닫지 않았다)"}

    pending: list[dict] = []
    done: list[str] = []
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
        hits: list[tuple[str, dict]] = []
        for path in candidates:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
            for row in _find_rows(path, rel, dev, skip_without_section=not hint):
                hits.append((rel, row))
        if not hits:
            where = f"`{hint}`" if hint else "`audit/ledger/*.md`"
            raise Unknown(f"{dev} 행을 {where} 에서 찾지 못했다.")
        if len(hits) > 1:
            places = ", ".join(f"`{rel}`:{row['line'] + 1}" for rel, row in hits)
            raise Unknown(f"{dev} 행이 둘 이상이다({places}). 어느 것을 볼지 정할 수 없다.")
        rel, row = hits[0]
        if row["state"] == DONE:
            done.append(dev)
        else:
            pending.append({"dev": dev, "pr": pr_no, "file": rel, "state": row["state"]})
            if pr_no not in used_prs:
                used_prs.append(pr_no)

    if pending:
        names = ", ".join(f"{p['dev']}(PR #{p['pr']}, 상태 `{p['state'] or '빈 칸'}`)" for p in pending)
        return {"status": "violation", "prs": used_prs, "pending": pending, "done": done,
                "reason": f"대표 이슈를 닫은 PR 이 병합됐는데 원장 행이 `{DONE}` 이 아니다: {names}"}
    return {"status": "ok", "prs": [], "pending": [], "done": done, "reason": "원장 행이 모두 완료다"}


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    try:
        shas = args.sha if len(args.sha) > 1 else expand_shas(root, args.sha[0], args.before)
        result = check(GhClient(), args.repo, shas, root)
    except (GhError, Unknown) as exc:
        _print({"status": "unknown", "prs": [], "pending": [], "reason": f"판정 불능: {exc}"})
        return EXIT_UNKNOWN
    _print(result)
    return EXIT_VIOLATION if result["status"] == "violation" else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger_complete",
        description="병합된 PR 이 닫은 대표 [DEV-xxx] 이슈의 진행 원장 행이 완료인지 본다.",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    ck = sub.add_parser("check", help="main 에 들어온 커밋들의 병합 PR 이 닫은 대표 이슈의 원장 행을 본다")
    ck.add_argument("--repo", required=True, help="owner/repo")
    ck.add_argument("--sha", required=True, action="append",
                    help="main 에 들어온 커밋 SHA(여러 번 줄 수 있다. 오래된 것부터)")
    ck.add_argument("--before", help="push 직전의 main 커밋. --sha 가 하나일 때 before..sha 의 모든 커밋을 본다")
    ck.add_argument("--root", required=True, help="Project Repository 작업 트리")
    ck.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
