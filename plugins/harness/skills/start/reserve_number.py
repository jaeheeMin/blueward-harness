"""요구사항·개발 번호를 이슈 제목에 찜한다(#227).

`/harness:start`·`/harness:srs`·`/harness:spec` 이 같이 쓴다. 번호 계산과 겹침 확인은
결정적인 일이라 모델이 매번 손으로 하지 않게 스크립트로 둔다. 표준 라이브러리만 쓰고
`git` 과 `gh` 를 부른다.

번호 하나: SRS 의 `REQ-003`, Spec 의 `DEV-003`, 원장의 `DEV-003`, 이슈 제목의 `[DEV-003]`.
다음 번호 = max( origin/main 의 SRS REQ, docs/spec/DEV-*, audit/ledger 의 DEV,
모든 이슈(열림+닫힘) 제목의 `[DEV-xxx]` ) + 1. 3자리 0 채움.

하위 명령
  next                         다음 번호를 `DEV-xxx` 로 출력한다.
  reserve --title T [--body-file F] [--label L ...]
                               이슈를 `[DEV-xxx] T` 로 만들고 겹침을 확인한다.
  claim --issue N              이슈에 번호가 없으면 붙이고, 있으면 그 번호를 낸다.

종료코드
  0  성공 (stdout: next 는 `DEV-xxx`, 나머지는 JSON 한 줄)
  2  판정 불능(git·gh 실패 등). 통과나 위반으로 뭉개지 않는다. stdout JSON 에 사유.
  3  찜 안 함. 저장소 꼭대기에 `audit/ledger/` 가 없다(하네스 저장소 자신 포함).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_NO_LEDGER = 3

MAX_RECHECKS = 3
TAG_RE = re.compile(r"^\s*\[DEV-(\d+)\]\s*")
REQ_ROW_RE = re.compile(r"^\|\s*REQ-(\d+)\s*\|", re.MULTILINE)
DEV_ROW_RE = re.compile(r"^\|\s*DEV-(\d+)\s*\|", re.MULTILINE)
SPEC_NAME_RE = re.compile(r"(?:^|/)DEV-(\d+)[^/]*\.md$")
ISSUE_LIMIT = "1000"


class Undecidable(Exception):
    """판정 불능. 종료코드 2."""


class NoLedger(Exception):
    """원장이 없는 저장소. 종료코드 3."""


def _run(cmd: list[str], cwd: str | None = None) -> str:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError as exc:
        raise Undecidable(f"{cmd[0]} 를 실행하지 못했다: {exc}") from exc
    if proc.returncode != 0:
        raise Undecidable(f"{' '.join(cmd[:3])} 실패(종료코드 {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def gh(args: list[str], cwd: str | None = None) -> str:
    return _run(["gh", *args], cwd)


def git(args: list[str], cwd: str | None = None) -> str:
    return _run(["git", *args], cwd)


def format_number(n: int) -> str:
    return f"DEV-{n:03d}"


def repo_root() -> str:
    return git(["rev-parse", "--show-toplevel"]).strip()


def require_ledger(root: str) -> None:
    if not (Path(root) / "audit" / "ledger").is_dir():
        raise NoLedger("audit/ledger/ 가 없는 저장소라 번호를 찜하지 않는다.")


def _show_main(root: str, path: str) -> str | None:
    """origin/main 의 파일. 파일이 없으면 None, 읽기 자체가 실패하면 Undecidable."""
    listed = git(["ls-tree", "--name-only", "origin/main", "--", path], root).strip()
    if not listed:
        return None
    return git(["show", f"origin/main:{path}"], root)


def main_numbers(root: str) -> list[int]:
    git(["fetch", "origin", "main"], root)
    nums: list[int] = []
    srs = _show_main(root, "docs/ssot/SRS.md")
    if srs:
        nums += [int(m) for m in REQ_ROW_RE.findall(srs)]
    tree = git(["ls-tree", "-r", "--name-only", "origin/main", "--", "docs/spec", "audit/ledger"], root)
    for line in tree.splitlines():
        line = line.strip()
        if line.startswith("docs/spec/"):
            m = SPEC_NAME_RE.search(line)
            if m:
                nums.append(int(m.group(1)))
        elif line.startswith("audit/ledger/") and line.endswith(".md"):
            text = _show_main(root, line) or ""
            nums += [int(m) for m in DEV_ROW_RE.findall(text)]
    return nums


def list_issues(root: str) -> list[dict]:
    out = gh(["issue", "list", "--state", "all", "--limit", ISSUE_LIMIT, "--json", "number,title"], root)
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise Undecidable(f"gh issue list 출력을 읽지 못했다: {exc}") from exc
    return data


def issue_tag(title: str) -> int | None:
    m = TAG_RE.match(title or "")
    return int(m.group(1)) if m else None


def compute_next(root: str, exclude_issue: int | None = None) -> int:
    nums = main_numbers(root)
    for issue in list_issues(root):
        if issue["number"] == exclude_issue:
            continue
        tag = issue_tag(issue["title"])
        if tag is not None:
            nums.append(tag)
    return (max(nums) if nums else 0) + 1


def strip_tag(title: str) -> str:
    return TAG_RE.sub("", title, count=1)


def settle(root: str, issue: int, core_title: str, number: int) -> tuple[int, int | None]:
    """이슈 제목이 `[DEV-number]` 인 상태에서, 더 앞선 이슈와 겹치면 다시 번호를 매긴다.

    반환: (최종 번호, 처음 번호 — 안 바뀌었으면 None).
    """
    first: int | None = None
    for _ in range(MAX_RECHECKS):
        rival = [
            i for i in list_issues(root)
            if i["number"] < issue and issue_tag(i["title"]) == number
        ]
        if not rival:
            return number, first
        if first is None:
            first = number
        number = compute_next(root, exclude_issue=issue)
        gh(["issue", "edit", str(issue), "--title", f"[{format_number(number)}] {core_title}"], root)
    rival = [
        i for i in list_issues(root)
        if i["number"] < issue and issue_tag(i["title"]) == number
    ]
    if rival:
        raise Undecidable(
            f"{MAX_RECHECKS}번 다시 매겼지만 [{format_number(number)}] 가 계속 겹친다. 이슈 #{issue} 제목을 직접 확인한다."
        )
    return number, first


def _result(issue: int, number: int, first: int | None, title: str, url: str = "") -> dict:
    res = {
        "status": "ok",
        "number": format_number(number),
        "issue": issue,
        "title": f"[{format_number(number)}] {title}",
        "url": url,
        "renumbered_from": format_number(first) if first is not None else None,
    }
    if first is not None:
        res["notice"] = f"번호가 겹쳐 {format_number(number)} 로 바꿨다"
    return res


def cmd_next(args: argparse.Namespace) -> dict:
    root = repo_root()
    require_ledger(root)
    return {"_plain": format_number(compute_next(root))}


def cmd_reserve(args: argparse.Namespace) -> dict:
    root = repo_root()
    require_ledger(root)
    core = strip_tag(args.title).strip()
    if not core:
        raise Undecidable("제목이 비어 있다.")
    number = compute_next(root)
    cmd = ["issue", "create", "--title", f"[{format_number(number)}] {core}"]
    if args.body_file:
        cmd += ["--body-file", args.body_file]
    else:
        cmd += ["--body", ""]
    for label in args.label or []:
        cmd += ["--label", label]
    out = gh(cmd, root).strip()
    m = re.search(r"/issues/(\d+)\s*$", out.splitlines()[-1] if out else "")
    if not m:
        raise Undecidable(f"gh issue create 출력에서 이슈 번호를 찾지 못했다: {out!r}")
    issue = int(m.group(1))
    final, first = settle(root, issue, core, number)
    return _result(issue, final, first, core, out.splitlines()[-1])


def cmd_claim(args: argparse.Namespace) -> dict:
    root = repo_root()
    require_ledger(root)
    out = gh(["issue", "view", str(args.issue), "--json", "number,title,url"], root)
    try:
        info = json.loads(out)
    except json.JSONDecodeError as exc:
        raise Undecidable(f"gh issue view 출력을 읽지 못했다: {exc}") from exc
    title = info["title"]
    core = strip_tag(title).strip()
    existing = issue_tag(title)
    if existing is not None:
        # 이미 찜된 이슈. 더 앞선 이슈와 겹치는지도 한 번 확인한다.
        final, first = settle(root, args.issue, core, existing)
        return _result(args.issue, final, first, core, info.get("url", ""))
    number = compute_next(root, exclude_issue=args.issue)
    gh(["issue", "edit", str(args.issue), "--title", f"[{format_number(number)}] {core}"], root)
    final, first = settle(root, args.issue, core, number)
    return _result(args.issue, final, first, core, info.get("url", ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="요구사항·개발 번호를 이슈 제목에 찜한다.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("next")
    p_res = sub.add_parser("reserve")
    p_res.add_argument("--title", required=True)
    p_res.add_argument("--body-file")
    p_res.add_argument("--label", action="append")
    p_claim = sub.add_parser("claim")
    p_claim.add_argument("--issue", type=int, required=True)
    args = parser.parse_args(argv)

    handler = {"next": cmd_next, "reserve": cmd_reserve, "claim": cmd_claim}[args.cmd]
    try:
        res = handler(args)
    except NoLedger as exc:
        print(json.dumps({"status": "no_ledger", "message": str(exc)}, ensure_ascii=False))
        return EXIT_NO_LEDGER
    except Undecidable as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return EXIT_ERROR
    if "_plain" in res:
        print(res["_plain"])
    else:
        print(json.dumps(res, ensure_ascii=False))
    return EXIT_OK


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
