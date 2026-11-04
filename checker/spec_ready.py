"""병합 전 관문: 개발 변경(`src/`)이 있는 PR 은 그 DEV 의 Spec 이 base 에 이미 있어야 한다(#668).

규칙은 "SRS → Spec → 개발 순"(`rules/governance.md`)이고 Spec 없이 개발은 없다. SRS 에서 설정으로 정한 건은 개발이 아니다.
`pr-checks.yml` 의 `spec-ready` 단계가 부른다. 파일을 쓰지 않는다(코멘트 본문만 `--markdown-file` 로 쓴다).

판정(PR 하나):
- 해당 없음(통과): 바뀐 파일에 `src/` 아래가 하나도 없다. `src/` 아래는 코드가 아니어도(README·package.devc.xml·템플릿) 개발 변경이다.
- DEV 번호는 `checker.pr_queue._order_devs` 로 찾는다(제목 끝 `(DEV-…)`·제목·브랜치·바꾼 Spec 파일). 모두 없으면 본문의
  하네스 표시만 읽는다(`DEV-xxx 하위 작업`, `진행 원장: DEV-xxx`, `## 진행 원장` 절). 본문에 스친 번호는 읽지 않는다.
- 통과: 찾은 모든 DEV 의 `docs/spec/DEV-<번호>-*.md` 가 base(병합 대상 브랜치)에 있다.
- 위반: DEV 를 못 찾음 / Spec 이 base 에 없음(이 PR 이 Spec 을 새로 추가한 경우 포함 — Spec 은 먼저 승인·병합돼야 한다) /
  원장 `audit/ledger/*.md` 의 그 DEV 행 Spec 칸이 `설정`(설정은 개발이 아니다).
- 검사 불능(통과도 위반도 아니다): PR·파일·base 의 Spec 목록·원장을 읽지 못함, 뜻밖의 예외.
종료코드: 0 통과/해당 없음, 1 위반, 2 검사 불능. 통과이면 마크다운은 빈 문자열이다.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

from checker.ledger_complete import _strip_non_prose
from checker.pairing import LEDGER_DIR, section_span, table_indexed
from checker.pr_queue import _SPEC_FILE, _order_devs
from checker.ssot_approval import GhClient, GhError, _force_utf8

MARKER = "<!-- spec-ready -->"
EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_UNKNOWN = 2

SPEC_DIR = "docs/spec"
SRC_PREFIX = "src/"
CONFIG = "설정"
RERUN = "제목을 고친 뒤 검사를 다시 돌려 줘: 새 커밋을 올리거나 Actions 에서 Re-run"

NO_DEV = "no_dev"
NO_SPEC = "no_spec"
CONFIG_ONLY = "config"
UNKNOWN = "unknown"


class Unknown(Exception):
    """읽지 못해 판정할 수 없다."""


_BODY_SUBTASK = re.compile(r"\bDEV-0*(\d+)\s*하위\s*작업")
_BODY_LEDGER_LINE = re.compile(r"진행\s*원장\s*:\s*DEV-0*(\d+)")
_DEV_IN_TEXT = re.compile(r"\bDEV-0*(\d+)")


def body_devs(body: str | None) -> set[int]:
    """PR 본문에서 하네스가 일부러 쓰는 표시만 읽는다: `DEV-xxx 하위 작업`, `진행 원장: DEV-xxx`, `## 진행 원장` 절 안의 DEV 번호
    (deliver 가 쓰는 형식). 코드·인용·주석 안은 보지 않는다. 그 밖에 본문에 스친 번호(`REQ-` 포함)는 읽지 않는다."""
    text = _strip_non_prose(body or "")
    nums = {int(n) for n in _BODY_SUBTASK.findall(text)}
    nums.update(int(n) for n in _BODY_LEDGER_LINE.findall(text))
    span = section_span(text, "진행 원장")
    if span is not None:
        section = "\n".join(text.splitlines()[span[0]:span[1]])
        nums.update(int(n) for n in _DEV_IN_TEXT.findall(section))
    return nums


def _dev(n: int) -> str:
    return f"DEV-{n:03d}"


def _read_text(client, repo: str, path: str, ref: str) -> str:
    data = client.get_json_or_none_404(f"repos/{repo}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}")
    if not isinstance(data, dict) or not data.get("content"):
        raise Unknown(f"base({ref}) 에서 `{path}` 를 읽지 못했다")
    try:
        return base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise Unknown(f"base({ref}) 의 `{path}` 를 해석하지 못했다: {exc}") from exc


def _base_spec_numbers(client, repo: str, base: str) -> set[int]:
    """base 의 `docs/spec/DEV-<번호>-*.md` 번호들. 폴더가 없으면 빈 집합(Spec 이 하나도 없다)."""
    listing = client.get_json_or_none_404(f"repos/{repo}/contents/{SPEC_DIR}?ref={quote(base, safe='')}")
    if listing is None:
        return set()
    if not isinstance(listing, list):
        raise Unknown(f"base 의 `{SPEC_DIR}` 가 폴더가 아니다")
    nums: set[int] = set()
    for e in listing:
        if isinstance(e, dict) and e.get("type") == "file":
            m = _SPEC_FILE.match(str(e.get("path") or ""))
            if m:
                nums.add(int(m.group(1)))
    return nums


def _config_numbers(client, repo: str, base: str, devs: set[int]) -> set[int]:
    """base 원장에서 Spec 칸이 `설정` 인 DEV 번호들. 원장을 안 쓰는 저장소(base 에 폴더 없음)는 빈 집합.

    원장 폴더가 없다는 404 만 "안 씀" 이다. 읽지 못한 것(404 아님·표 형식)은 Unknown 이다(`ledger_stale` 과 같은 구분)."""
    listing = client.get_json_or_none_404(f"repos/{repo}/contents/{LEDGER_DIR}?ref={quote(base, safe='')}")
    if listing is None:
        return set()
    if not isinstance(listing, list):
        raise Unknown(f"base 의 `{LEDGER_DIR}` 가 폴더가 아니다")
    found: set[int] = set()
    for e in sorted(listing, key=lambda x: str(x.get("path", "")) if isinstance(x, dict) else ""):
        if not (isinstance(e, dict) and e.get("type") == "file" and str(e.get("path", "")).endswith(".md")):
            continue
        path = e["path"]
        text = _read_text(client, repo, path, base)
        text = text[1:] if text.startswith("﻿") else text
        span = section_span(text, "개발 건")
        if span is None:
            continue  # 원장이 아닌 md
        table = table_indexed(text.splitlines()[span[0]:span[1]])
        if table is None:
            raise Unknown(f"`{path}` 의 개발 건 표 머리(`ID` 열)를 찾지 못했다(표 형식을 못 읽음)")
        header, rows = table
        for _, cells in rows:
            if not cells or not cells[0].upper().startswith("DEV-"):
                continue
            digits = cells[0][4:].strip()
            if not digits.isdigit() or int(digits) not in devs:
                continue
            if "Spec" not in header:
                raise Unknown(f"`{path}` 의 개발 건 표 머리에 `Spec` 열이 없어 {cells[0]} 를 판정하지 못했다")
            i = header.index("Spec")
            if i < len(cells) and cells[i].strip() == CONFIG:
                found.add(int(digits))
    return found


def _open_spec_prs(client, repo: str, me: int, nums: set[int]) -> dict[int, list[dict]]:
    """그 DEV 의 Spec 파일을 바꾸는 열린 PR. 읽지 못하면 그 정보만 뺀다(지어내지 않는다)."""
    out: dict[int, list[dict]] = {}
    try:
        prs = client.get_all(f"repos/{repo}/pulls?state=open")
    except GhError:
        return out
    for p in prs:
        if not isinstance(p, dict) or p.get("number") == me:
            continue
        raw = {"title": p.get("title"), "headRefName": (p.get("head") or {}).get("ref"), "body": p.get("body")}
        cand = nums & _order_devs(raw)
        if not cand:
            continue
        try:
            files = client.get_all(f"repos/{repo}/pulls/{p['number']}/files")
        except GhError:
            continue
        for f in files:
            m = _SPEC_FILE.match(str(f.get("filename") or ""))
            if m and int(m.group(1)) in nums:
                out.setdefault(int(m.group(1)), []).append({"number": p["number"], "title": p.get("title") or ""})
                break
    return out


def check_pr(client, repo: str, pr: int) -> dict:
    """status: ok / violation / unknown. `applicable` 가 False 면 해당 없음(`src/` 변경 없음). GhError·Unknown 은 부른 쪽이 처리."""
    data = client.get_json(f"repos/{repo}/pulls/{pr}")
    base = ((data or {}).get("base") or {}).get("ref") if isinstance(data, dict) else None
    if not isinstance(data, dict) or not base:
        raise GhError("PR 응답을 읽지 못했다(기준 브랜치가 없다)")
    entries = client.get_all(f"repos/{repo}/pulls/{pr}/files")
    files = [e for e in entries if isinstance(e, dict) and e.get("filename")]
    if not any(f["filename"].startswith(SRC_PREFIX) or str(f.get("previous_filename") or "").startswith(SRC_PREFIX)
               for f in files):
        return {"status": "ok", "applicable": False, "items": []}
    # 본문은 `_order_devs` 에 넘기지 않는다(본문에 스친 번호·REQ 번호로 통과하지 않게). 제목·브랜치·바꾼 Spec 파일로도 못 찾을 때만
    # 하네스가 일부러 쓰는 표시(`body_devs`)를 인정한다.
    raw = {"title": data.get("title"), "body": "",
           "headRefName": (data.get("head") or {}).get("ref"),
           "files": [{"path": f["filename"]} for f in files]}
    devs = _order_devs(raw) or body_devs(data.get("body"))
    if not devs:
        return {"status": "violation", "applicable": True,
                "items": [{"kind": NO_DEV, "dev": "", "reason": "어느 개발인지 PR 에서 찾지 못했다"}]}
    base_specs = _base_spec_numbers(client, repo, base)
    config = _config_numbers(client, repo, base, devs)
    added_here = {int(m.group(1)) for f in files if f.get("status") == "added"
                  for m in [_SPEC_FILE.match(f["filename"])] if m}
    missing = {n for n in devs - config if n not in base_specs}
    open_prs = _open_spec_prs(client, repo, pr, missing - added_here) if missing - added_here else {}
    items = []
    for n in sorted(devs):
        if n in config:
            items.append({"kind": CONFIG_ONLY, "dev": _dev(n), "reason": "원장 Spec 칸이 설정이다"})
        elif n not in base_specs:
            items.append({"kind": NO_SPEC, "dev": _dev(n), "reason": "Spec 이 base 에 없다",
                          "added_here": n in added_here, "open_prs": open_prs.get(n, [])})
    return {"status": "violation" if items else "ok", "applicable": True, "items": items}


def render_markdown(result: dict) -> str:
    """PR 코멘트·job 요약 본문. 통과·해당 없음이면 빈 문자열(코멘트를 달지 않고 있던 것은 지운다)."""
    if result["status"] == "ok":
        return ""
    lines = [MARKER, "## spec-ready", ""]
    items = result["items"]
    if result["status"] == "unknown":
        lines.append("⚠️ Spec 검사 불능 — 통과도 위반도 아닙니다. 아래 사유를 보고 다시 실행하거나 담당자에게 알리세요.")
        lines.append("")
        lines += [f"- {i['reason']}" for i in items]
        return "\n".join(lines) + "\n"
    lines += ["⚠️ 개발 변경(`src/`)이 있는데 Spec 이 main 에 아직 없어 병합할 수 없습니다. Spec 없이 개발은 없습니다(SRS → Spec → 개발 순).", ""]
    for i in items:
        if i["kind"] == NO_DEV:
            lines.append("- 어느 개발인지 찾지 못했습니다. PR 제목 끝에 `(DEV-xxx)` 로 적어 주세요. " + RERUN + ".")
        elif i["kind"] == CONFIG_ONLY:
            lines.append(f"- {i['dev']}: 설정은 개발이 아닙니다. 진행 원장의 Spec 칸이 `설정` 인 건은 `src/` 를 바꾸지 않습니다. "
                         "개발이 필요하면 SRS 에서 다음 단계를 고치는 것부터 하세요(`/harness:srs`).")
        elif i["kind"] == NO_SPEC:
            msg = f"- {i['dev']}: Spec(`docs/spec/{i['dev']}-*.md`)이 병합 대상 브랜치에 없습니다. `/harness:spec` 으로 Spec 을 먼저 만드세요."
            if i.get("added_here"):
                msg += " 이 PR 이 Spec 을 새로 추가했지만, Spec 은 따로 먼저 승인·병합해야 합니다(개발 PR 에 같이 담지 않습니다)."
            for p in i.get("open_prs") or []:
                msg += f" 열린 Spec PR #{p['number']}({p['title']}) 이 병합되면 이 검사를 다시 돌려 주세요."
            lines.append(msg)
    lines += ["", "Spec 이 병합된 뒤 새 커밋을 올리거나 Actions 에서 Re-run 하면 다시 판정합니다."]
    return "\n".join(lines) + "\n"


def cmd_check_pr(args) -> int:
    def unknown(reason: str) -> dict:
        return {"status": "unknown", "applicable": True, "items": [{"kind": UNKNOWN, "dev": "", "reason": reason}]}

    # 위반(종료 1)은 판정이 violation 일 때만이다. 파이썬이 예외로 죽으면 종료코드가 1 이라 위반처럼 보이므로 모두 잡는다.
    try:
        result = check_pr(GhClient(), args.repo, args.pr)
    except GhError as exc:
        result = unknown(f"GitHub 를 읽지 못했다: {exc}")
    except Unknown as exc:
        result = unknown(str(exc))
    except Exception as exc:  # noqa: BLE001 — 뜻밖의 오류도 통과·위반이 아닌 검사 불능이다(원칙 7)
        result = unknown(f"뜻밖의 오류로 Spec 을 확인하지 못했다(이 PR 의 문제가 아니다): {type(exc).__name__}: {exc}")
    print(json.dumps(result, ensure_ascii=False))
    if args.markdown_file:
        try:
            Path(args.markdown_file).write_text(render_markdown(result), encoding="utf-8")
        except OSError as exc:
            print(f"코멘트 본문을 쓰지 못했다: {exc}", file=sys.stderr)
    return {"ok": EXIT_OK, "violation": EXIT_VIOLATION}.get(result["status"], EXIT_UNKNOWN)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spec_ready", description="병합 전: 개발 변경 PR 의 DEV 에 Spec 이 base 에 있는지 본다.")
    sub = parser.add_subparsers(dest="mode", required=True)
    ck = sub.add_parser("check-pr", help="PR 하나의 Spec 선행 여부")
    ck.add_argument("--repo", required=True, help="owner/repo")
    ck.add_argument("--pr", required=True, type=int)
    ck.add_argument("--markdown-file", help="코멘트·요약 본문을 쓸 파일(통과이면 빈 파일)")
    ck.set_defaults(func=cmd_check_pr)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)
