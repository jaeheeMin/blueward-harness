"""요구사항·개발 번호를 이슈 제목에 찜한다(#227).

`/harness:start`·`/harness:srs`·`/harness:spec` 이 같이 쓴다. 번호 계산과 겹침 확인은
결정적인 일이라 모델이 매번 손으로 하지 않게 스크립트로 둔다. 표준 라이브러리만 쓰고
`git` 과 `gh` 를 부른다.

번호 하나: SRS 의 `REQ-003`, Spec 의 `DEV-003`, 원장의 `DEV-003`, 이슈 제목의 `[DEV-003]`.
다음 번호 = max( origin/main 의 SRS REQ, docs/spec/DEV-*, audit/ledger 의 DEV,
모든 이슈(열림+닫힘) 제목의 `[DEV-xxx]` ) + 1. 3자리 0 채움.

하위 명령
  next                         다음 번호를 `DEV-xxx` 로 출력한다.
  reserve --title T [--body-file F] [--label L ...] [--confirmed-new]
                               이슈를 `[DEV-xxx] T` 로 만들고 겹침을 확인한다.
  claim --issue N [--confirmed-new]
                               이슈에 번호가 없으면 붙이고, 있으면 그 번호를 낸다.
  list                         origin/main 기준 지금 있는 개발 목록을 JSON 한 줄로 낸다(#258).
                               번호마다 SRS 표 줄·원장 줄·Spec·`[DEV-xxx]` 이슈·하위 작업 이슈.

종료코드
  0  성공 (stdout: next 는 `DEV-xxx`, 나머지는 JSON 한 줄)
  2  판정 불능(git·gh 실패 등). 통과나 위반으로 뭉개지 않는다. stdout JSON 에 사유.
  3  찜 안 함. 저장소 꼭대기에 `audit/ledger/` 가 없다(하네스 저장소 자신 포함).
  4  확인 필요(#261). 새 제목이 origin/main SRS 의 기존 REQ 제목을 포함하거나 그 반대다.
     #304: 범위 "하지 않는 것" 항목과 포함 관계이거나 핵심 단어(2자 이상 토큰)가 둘 이상 겹치고 새 제목 토큰의 2/3 이상이어도 같다. 항목 끝 `(REQ-001)` 꼬리표는 그 요구사항에서 뺀 일이라는 표기다.
     이슈를 만들지도 번호를 붙이지도 않고, stdout JSON
     `{"status":"confirm","matches":[{"number","title","label"}],"excluded_matches":[{"item","reqs","reqs_labeled"}],"title"}`
     (`label`·`reqs_labeled` 는 사람용 `DEV-002(제목)`·`REQ-001(제목)` 표기, 제목을 모르면 `(제목 미확인)`)
     (`reqs` 가 빈 목록이면 프로젝트 전체에서 하지 않는 일).
     기존 개발의 하위 작업이면 번호를 새로 받지 않는다. 새 개발이 맞다고 사람이 확인하면
     `--confirmed-new` 를 붙여 다시 부른다. 새 번호를 붙일 때만 본다(이미 번호가 있는 이슈의 claim 은 안 본다).
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
EXIT_CONFIRM = 4
MIN_TITLE_LEN = 4  # 이보다 짧은 제목·"하지 않는 것" 항목(정규화 뒤)은 포함 비교에서 뺀다. 짧은 글자열이 우연히 들어 있는 오탐을 막는다.
SCOPE_EXCLUDED_MARKER = "하지 않는 것"  # SRS 범위 절 목록 머리말. 엔진 checker/risk_gate.py 와 같다(플러그인은 엔진을 import 못 해 파서가 따로 있다).
# 항목 끝의 꼬리표 `(REQ-001)`, `(REQ-001, REQ-002)`. checker/risk_gate.py 의 EXCLUDED_TAG_RE 와 같은 식이어야 한다(테스트가 본다).
EXCLUDED_TAG_RE = re.compile(r"\s*[(（]\s*(REQ-\d+(?:\s*[,，、]\s*REQ-\d+)*)\s*[)）]\s*$")

MAX_RECHECKS = 3
TAG_RE = re.compile(r"^\s*\[DEV-(\d+)\]\s*")
REQ_ROW_RE = re.compile(r"^\|\s*REQ-(\d+)\s*\|", re.MULTILINE)
DEV_ROW_RE = re.compile(r"^\|\s*DEV-(\d+)\s*\|", re.MULTILINE)
SUBTASK_RE = re.compile(r"\(DEV-(\d+)\)\s*$")
SPEC_NAME_RE = re.compile(r"(?:^|/)DEV-(\d+)[^/]*\.md$")
ISSUE_LIMIT = "1000"


class Undecidable(Exception):
    """판정 불능. 종료코드 2."""


class NoLedger(Exception):
    """원장이 없는 저장소. 종료코드 3."""


class NeedConfirm(Exception):
    """새 제목이 기존 REQ 제목이나 SRS 의 "하지 않는 것" 항목과 겹친다. 사람 확인이 필요하다. 종료코드 4."""

    def __init__(self, title: str, matches: list[dict], excluded_matches: list[dict] | None = None):
        super().__init__(title)
        self.title = title
        self.matches = matches
        self.excluded_matches = excluded_matches or []


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
    tree = git(["-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "origin/main", "--", "docs/spec", "audit/ledger"], root)
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


def list_issues(root: str, fields: str = "number,title") -> list[dict]:
    out = gh(["issue", "list", "--state", "all", "--limit", ISSUE_LIMIT, "--json", fields], root)
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        raise Undecidable(f"gh issue list 출력을 읽지 못했다: {exc}") from exc
    return data


def subtask_of(title: str) -> int | None:
    """제목 끝 `(DEV-xxx)` 의 번호. 하위 작업 이슈이며 번호 계산에는 쓰지 않는다."""
    m = SUBTASK_RE.search(title or "")
    return int(m.group(1)) if m else None


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


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table_rows(text: str, id_re: re.Pattern) -> list[tuple[int, dict[str, str]]]:
    """마크다운 표에서 `ID` 칸이 id_re 인 줄을 (번호, {머리줄 이름: 값}) 로 읽는다. 열 순서는 가정하지 않는다."""
    rows: list[tuple[int, dict[str, str]]] = []
    header: list[str] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("|"):
            header = []
            continue
        cells = _cells(line)
        if cells and cells[0] == "ID":
            header = cells
            continue
        m = id_re.match(line)
        if m and header:
            rows.append((int(m.group(1)), dict(zip(header, cells))))
    return rows


TITLE_UNKNOWN = "제목 미확인"


def titled_label(number: str, title: str | None) -> str:
    """사람에게 보여 줄 `DEV-002(제목)`(#308). 제목을 모르면 `(제목 미확인)` 이고 추측하지 않는다."""
    title = (title or "").strip()
    return f"{number}({title if title and title not in ('-', '—', '–') else TITLE_UNKNOWN})"


def _pick(row: dict[str, str], *names: str) -> str | None:
    for n in names:
        if row.get(n):
            return row[n]
    return None


def main_snapshot(root: str) -> dict[int, dict]:
    """origin/main 의 SRS·Spec·원장을 번호별로 모은다."""
    git(["fetch", "origin", "main"], root)
    devs: dict[int, dict] = {}

    def entry(n: int) -> dict:
        return devs.setdefault(n, {"number": format_number(n)})

    srs = _show_main(root, "docs/ssot/SRS.md")
    if srs:
        for n, row in _table_rows(srs, REQ_ROW_RE):
            e = entry(n)
            for key, names in (
                ("req_title", ("Title", "요구사항")), ("lob", ("LoB",)),
                ("next_step", ("다음 단계",)), ("status", ("Status", "상태")),
            ):
                val = _pick(row, *names)
                if val:
                    e[key] = val
    tree = git(["-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "origin/main", "--", "docs/spec", "audit/ledger"], root)
    for line in tree.splitlines():
        line = line.strip()
        if line.startswith("docs/spec/"):
            m = SPEC_NAME_RE.search(line)
            if m:
                entry(int(m.group(1)))["spec"] = line
        elif line.startswith("audit/ledger/") and line.endswith(".md"):
            for n, row in _table_rows(_show_main(root, line) or "", DEV_ROW_RE):
                entry(n).setdefault("ledger", {
                    "path": line, "content": row.get("내용", ""), "status": row.get("상태", ""),
                })
    return devs


def _norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


_FENCE_LINE = re.compile(r"^\s*(`{3,}|~{3,})")
_SCOPE_HEAD = re.compile(r"^(\s*)[-*]\s*" + re.escape(SCOPE_EXCLUDED_MARKER))
_ITEM_HEAD = re.compile(r"^[-*]\s*" + re.escape(SCOPE_EXCLUDED_MARKER) + r"\s*[:：]?")
_ITEM_BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_ITEM_SEP = ",、;；，"
_ITEM_TRAIL = " \t.。,、;；，"


def _split_items(text: str) -> list[str]:
    """한 줄 형태의 항목을 `,`·`、`·`;`·` · ` 로 쪼갠다. 괄호 안은 쪼개지 않는다."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for i, ch in enumerate(text):
        if ch in "(（[":
            depth += 1
        elif ch in ")）]":
            depth = max(depth - 1, 0)
        if depth == 0 and (ch in _ITEM_SEP or (ch == "·" and text[i - 1:i].isspace() and text[i + 1:i + 2].isspace())):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def scope_excluded_items(srs: str) -> list[dict]:
    """SRS 범위 "하지 않는 것" 목록의 항목 [{"item": 꼬리표를 뗀 항목, "reqs": ["REQ-001", …]}]. 꼬리표가 없으면 reqs 는 빈 목록.

    목록은 `- 하지 않는 것` 머리말 줄과 그 아래로 더 들여쓴 줄이다. 머리말에 이어 쓴 항목은 쪼개고 들여쓴 줄은
    줄마다 항목이다. 코드 펜스 안은 보지 않는다. checker/risk_gate.py 의 같은 이름 파서와 규칙이 같다.
    """
    lines: list[str] = []
    fence: str | None = None
    for line in srs.splitlines():
        fm = _FENCE_LINE.match(line)
        if fm:
            fence = fm.group(1)[0] if fence is None else (None if fm.group(1)[0] == fence else fence)
            continue
        if fence is None:
            lines.append(line)
    block: list[str] = []
    for i, line in enumerate(lines):
        m = _SCOPE_HEAD.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        block = [line.strip()]
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt.strip())
        break
    if not block:
        return []
    raws = _split_items(_ITEM_HEAD.sub("", block[0], count=1)) + [_ITEM_BULLET.sub("", ln, count=1) for ln in block[1:]]
    items: list[dict] = []
    seen: dict[str, dict] = {}
    for raw in raws:
        shown = re.sub(r"\s+", " ", raw).strip(_ITEM_TRAIL).strip()
        tag = EXCLUDED_TAG_RE.search(shown)
        reqs: list[str] = []
        if tag:
            reqs = re.findall(r"REQ-\d+", tag.group(1))
            shown = shown[:tag.start()].rstrip(_ITEM_TRAIL).strip()
        if not shown:
            continue
        if shown.casefold() in seen:  # 같은 본문이 꼬리표만 달리 두 번 나오면 번호를 합친다
            prev = seen[shown.casefold()]["reqs"]
            prev += [r for r in reqs if r not in prev]
            continue
        seen[shown.casefold()] = entry = {"item": shown, "reqs": reqs}
        items.append(entry)
    return items


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
MIN_TOKEN_LEN = 2  # 이보다 짧은 토큰은 겹침에서 뺀다
MIN_SHARED_TOKENS = 2  # 핵심 단어가 이만큼 이상 겹쳐야 한다
SHARED_TOKEN_RATIO = (2, 3)  # 그리고 새 제목 토큰의 2/3 이상


_PAREN_RE = re.compile(r"[(（\[][^()（）\[\]]*[)）\]]")


def _strip_parens(text: str) -> str:
    """괄호 `(…)` 안 내용을 공백으로 바꾼다(안쪽부터). 항목의 부연(`(조회 전용)`)이 비교에 끼는 오탐을 막는다."""
    prev = None
    while prev != text:
        prev, text = text, _PAREN_RE.sub(" ", text)
    return text


def _tokens(text: str) -> set[str]:
    """공백·구두점으로 나눈 토큰 집합. 영문은 소문자, 2자 미만은 뺀다(불용어 목록은 두지 않는다)."""
    return {t for t in _TOKEN_RE.findall((text or "").casefold()) if len(t) >= MIN_TOKEN_LEN}


def _token_overlap(new_tokens: set[str], item_tokens: set[str]) -> bool:
    """"하지 않는 것" 항목 비교 전용. 포함 판정이 못 잡는 `Launchpad 타일 노출` vs `Fiori Launchpad 노출(…)` 을 잡는다(#304)."""
    shared = len(new_tokens & item_tokens)
    num, den = SHARED_TOKEN_RATIO
    return shared >= MIN_SHARED_TOKENS and shared * den >= num * len(new_tokens)


def check_title_overlap(root: str, core_title: str) -> None:
    """origin/main SRS 의 REQ 제목이나 "하지 않는 것" 항목과 포함 관계면 NeedConfirm. SRS 가 없으면 건너뛴다. 읽기 실패는 Undecidable."""
    git(["fetch", "origin", "main"], root)
    srs = _show_main(root, "docs/ssot/SRS.md")
    if not srs:
        return
    new = _norm_title(core_title)
    if len(new) < MIN_TITLE_LEN:
        return
    matches: list[dict] = []
    req_titles: dict[str, str | None] = {}
    for n, row in _table_rows(srs, REQ_ROW_RE):
        title = _pick(row, "Title", "요구사항")
        req_titles.setdefault(f"REQ-{n:03d}", title)
        old = _norm_title(title or "")
        if len(old) >= MIN_TITLE_LEN and (old in new or new in old):
            matches.append({"number": format_number(n), "title": title, "label": titled_label(format_number(n), title)})
    excluded: list[dict] = []
    new_tokens = _tokens(core_title)
    for entry in scope_excluded_items(srs):
        # 사람에게 보일 `REQ-001(제목)` 목록. `reqs` 는 그대로 둔다(기계가 읽는 값).
        entry["reqs_labeled"] = [
            titled_label(r, req_titles.get(f"REQ-{int(r.split('-')[1]):03d}")) for r in entry["reqs"]
        ]
        body = _strip_parens(entry["item"])  # 괄호 속 부연은 비교에서 뺀다. 보여 주는 항목은 원문 그대로
        old = _norm_title(body)
        if len(old) >= MIN_TITLE_LEN and (old in new or new in old):
            excluded.append(entry)
        elif _token_overlap(new_tokens, _tokens(body)):
            excluded.append(entry)
    if matches or excluded:
        raise NeedConfirm(core_title, matches, excluded)


def cmd_list(args: argparse.Namespace) -> dict:
    root = repo_root()
    require_ledger(root)
    devs = main_snapshot(root)
    subtasks: dict[int, list[dict]] = {}
    issues = list_issues(root, "number,title,state")
    for issue in issues:
        tag = issue_tag(issue["title"])
        if tag is not None:
            devs.setdefault(tag, {"number": format_number(tag)}).setdefault("issues", []).append(
                {"number": issue["number"], "title": issue["title"], "state": issue.get("state", "")}
            )
        else:
            parent = subtask_of(issue["title"])
            if parent is not None:
                subtasks.setdefault(parent, []).append(
                    {"number": issue["number"], "title": issue["title"], "state": issue.get("state", "")}
                )
    for n, subs in subtasks.items():
        if n in devs:
            devs[n]["subtasks"] = subs
    for n, dev in devs.items():
        # 사람용 표기. SRS 제목, 없으면 원장 내용, 그것도 없으면 이슈 제목(`[DEV-xxx]` 뗀 것), 그것도 없으면 제목 미확인.
        issue_title = strip_tag(dev["issues"][0]["title"]).strip() if dev.get("issues") else None
        candidates = [dev.get("req_title"), (dev.get("ledger") or {}).get("content"), issue_title]
        # `-`·빈 값은 건너뛰고 다음 후보로 간다
        title = next((c for c in candidates if c and c.strip() not in ("-", "—", "–")), None)
        dev["label"] = titled_label(dev["number"], title)
    return {"status": "ok", "devs": [devs[n] for n in sorted(devs)]}


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
    if not args.confirmed_new:
        check_title_overlap(root, core)
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
    if not args.confirmed_new:
        check_title_overlap(root, core)
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
    p_res.add_argument("--confirmed-new", action="store_true", help="기존 REQ 제목이나 SRS 의 하지 않는 것 항목과 겹친다는 확인을 건너뛴다(사람이 새 개발이라고 확인한 뒤)")
    sub.add_parser("list")
    p_claim = sub.add_parser("claim")
    p_claim.add_argument("--issue", type=int, required=True)
    p_claim.add_argument("--confirmed-new", action="store_true", help="기존 REQ 제목이나 SRS 의 하지 않는 것 항목과 겹친다는 확인을 건너뛴다(사람이 새 개발이라고 확인한 뒤)")
    args = parser.parse_args(argv)

    handler = {"next": cmd_next, "reserve": cmd_reserve, "claim": cmd_claim, "list": cmd_list}[args.cmd]
    try:
        res = handler(args)
    except NoLedger as exc:
        print(json.dumps({"status": "no_ledger", "message": str(exc)}, ensure_ascii=False))
        return EXIT_NO_LEDGER
    except NeedConfirm as exc:
        print(json.dumps(
            {"status": "confirm", "matches": exc.matches, "excluded_matches": exc.excluded_matches, "title": exc.title},
            ensure_ascii=False,
        ))
        return EXIT_CONFIRM
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
