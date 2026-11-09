"""개발 준비 상태(#668): 이 폴더의 개발 건 중 Spec 이 origin/main 에 있는 것·없는 것·설정·표준 건을 읽는다.

새 작업 화면이 종류 버튼에 "Spec 있는 건 없음" 같은 것을 미리 보이고, 개발을 시작하지 못하는 때를 알려 주는 데 쓴다.
기준은 start 스킬·PR 검사 spec-ready 와 같다: origin/main 에 `docs/spec/DEV-xxx-*.md` 가 있는가, SRS `다음 단계` 가 `설정`·`표준` 인가
(옛 데이터 호환으로 원장 Spec 칸 `설정` 도 설정 건으로 본다, #718). 원장이 없어도 SRS 만으로 읽는다.
번호는 REQ 와 DEV 가 같다(SRS `REQ-001` = Spec·원장 `DEV-001`).

state: yes(판정 대상, 읽음) / no(원장도 SRS 도 없는 저장소·git 저장소 아님 = 해당 없음) / unknown(읽지 못함, 지어내지 않는다).
"""
from __future__ import annotations

import os
import re

import gitstate

REQ_ROW_RE = re.compile(r"^\|\s*REQ-(\d+)\s*\|")
DEV_ROW_RE = re.compile(r"^\|\s*DEV-(\d+)\s*\|")
SPEC_NAME_RE = re.compile(r"(?:^|/)DEV-(\d+)[^/]*\.md$")
TITLE_UNKNOWN = "제목 미확인"
SETUP = "설정"
STANDARD = "표준"
DEV_NEXT = "개발"
INACTIVE_STATUS = {"dropped", "duplicate", "on hold"}  # 보류·취소된 요구사항은 "할 차례" 가 아니다
DONE_LEDGER = "완료"
NEED_LIMIT = 20


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _rows(text: str, id_re: re.Pattern) -> list[tuple[int, dict[str, str]]]:
    """마크다운 표에서 ID 칸이 id_re 인 줄을 (번호, {머리줄 이름: 값}) 로 읽는다. 열 순서는 가정하지 않는다."""
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
        m = id_re.match(line.strip())
        if m and header:
            rows.append((int(m.group(1)), dict(zip(header, cells))))
    return rows


def _pick(row: dict[str, str], *names: str) -> str:
    for n in names:
        if row.get(n):
            return row[n]
    return ""


def _title(text: str) -> str:
    text = (text or "").strip()
    return text if text and text not in ("-", "—", "–") else TITLE_UNKNOWN


def _unknown(reason: str) -> dict:
    return {"state": "unknown", "reason": reason}


def read(run: gitstate.Runner, slow_run: gitstate.Runner, cwd: str) -> dict:
    root, failed = gitstate.repo_root_checked(run, cwd)
    if failed:
        return _unknown("git 을 실행하지 못해 개발 준비 상태를 확인하지 못했어.")
    if not root:
        return {"state": "no", "reason": "git 저장소가 아니라 개발 준비 상태를 따지지 않아."}
    if not (os.path.isdir(os.path.join(root, "audit", "ledger")) or os.path.isfile(os.path.join(root, "docs", "ssot", "SRS.md"))):
        return {"state": "no", "reason": "audit/ledger/ 도 docs/ssot/SRS.md 도 없는 저장소라 개발 준비 상태를 따지지 않아."}
    rc, out = slow_run(["git", "fetch", "origin", "main"], root)
    if rc != 0:
        return _unknown("origin/main 을 받지 못해 Spec 이 있는지 확인하지 못했어.")
    rc, tree = run(["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "origin/main", "--",
                    "docs/ssot/SRS.md", "docs/spec", "audit/ledger"], root)
    if rc != 0:
        return _unknown("origin/main 의 파일 목록을 읽지 못했어.")

    def show(path: str) -> str | None:
        rc, text = run(["git", "show", f"origin/main:{path}"], root)
        return text if rc == 0 else None

    nums: dict[int, dict] = {}

    def entry(n: int) -> dict:
        return nums.setdefault(n, {})

    for line in tree.splitlines():
        line = line.strip()
        if line == "docs/ssot/SRS.md":
            text = show(line)
            if text is None:
                return _unknown("origin/main 의 SRS 를 읽지 못했어.")
            for n, row in _rows(text, REQ_ROW_RE):
                entry(n)["srs"] = {"title": _pick(row, "Title", "요구사항"), "next": _pick(row, "다음 단계"), "status": _pick(row, "Status", "상태")}
        elif line.startswith("docs/spec/"):
            m = SPEC_NAME_RE.search(line)
            if m:
                entry(int(m.group(1)))["spec"] = line
        elif line.startswith("audit/ledger/") and line.endswith(".md"):
            text = show(line)
            if text is None:
                return _unknown("origin/main 의 진행 원장을 읽지 못했어.")
            for n, row in _rows(text, DEV_ROW_RE):
                entry(n).setdefault("ledger", {"title": _pick(row, "내용"), "spec": _pick(row, "Spec"), "status": _pick(row, "상태")})

    spec_ready, setup, standard, need, items = 0, 0, 0, [], []
    for n in sorted(nums):
        e = nums[n]
        srs, ledger, has_spec = e.get("srs"), e.get("ledger"), "spec" in e
        step = srs["next"].strip() if srs else ""
        is_standard = step == STANDARD
        # 설정·표준 갈래의 기준은 SRS 다음 단계다. 옛 원장의 Spec 칸 `설정` 도 설정 건으로 읽는다(PR 검사 spec-ready 와 같다, #718).
        # SRS 가 그 번호를 개발로 정했으면 옛 원장 `설정` 은 무시한다(spec_ready 와 같다).
        is_setup = step == SETUP or is_standard or (step != DEV_NEXT and bool(ledger) and ledger["spec"].strip() == SETUP)
        # 개발 건: SRS 다음 단계가 개발이거나, SRS 에 없는데 원장에 있는 건. 다음 단계가 미정·빈 칸이면 개발인지 모르니 세지 않는다.
        is_dev = not is_setup and ((srs and srs["next"].strip() == DEV_NEXT) or (not srs and bool(ledger)))
        inactive = (bool(srs) and srs["status"].strip().casefold() in INACTIVE_STATUS) or (bool(ledger) and ledger["status"].strip() == DONE_LEDGER)
        label = f"REQ-{n:03d}({_title(srs['title'])})" if srs else f"DEV-{n:03d}({_title(ledger['title']) if ledger else TITLE_UNKNOWN})"
        item = {"number": n, "label": label, "spec": has_spec, "setup": is_setup, "standard": is_standard, "dev": is_dev,
                "next": srs["next"] if srs else ""}
        items.append(item)
        if is_setup:
            setup += 1
            standard += is_standard
        elif is_dev and has_spec:
            spec_ready += 1
        elif is_dev and not inactive:
            need.append({"number": n, "label": label})
    return {"state": "yes", "reason": "", "specReady": spec_ready, "setup": setup, "standard": standard, "needSpec": need[:NEED_LIMIT],
            "needSpecCount": len(need), "items": items}


def srs_status(run: gitstate.Runner, cwd: str) -> dict:
    """세션 작업 폴더의 SRS 에서 요구사항별 Status·다음 단계를 읽는다(#718). 설정·표준 건의 진행(In Process·Done)은
    작업 브랜치의 SRS 에 먼저 적히므로 origin/main 이 아니라 작업 폴더 파일을 읽는다. 캐시하지 않는다(가벼운 파일 읽기).
    state: yes(읽음, items = {"REQ-002": {"status", "next"}}) / no(SRS 가 없음) / unknown(읽지 못함, 지어내지 않는다)."""
    root, failed = gitstate.repo_root_checked(run, cwd)
    if failed:
        return _unknown("git 을 실행하지 못해 SRS 를 찾지 못했어.")
    path = os.path.join(root or cwd, "docs", "ssot", "SRS.md")
    if not os.path.isfile(path):
        return {"state": "no", "reason": "작업 폴더에 docs/ssot/SRS.md 가 없어."}
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return _unknown("작업 폴더의 SRS 를 읽지 못했어.")
    items = {f"REQ-{n:03d}": {"status": _pick(row, "Status", "상태"), "next": _pick(row, "다음 단계")} for n, row in _rows(text, REQ_ROW_RE)}
    return {"state": "yes", "reason": "", "items": items}
