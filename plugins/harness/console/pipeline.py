"""요구사항 파이프라인(Post 테마 파이프라인 탭): 저장소의 요구사항마다 SRS → 개발 Spec → 개발 → 검토 → 합쳐짐 칸을 정할 사실을 읽는다.

읽는 것: origin/main 의 SRS(제목·다음 단계·Status), 진행 원장(내용·상태), docs/spec/DEV-xxx 유무, 열린 PR(바뀐 파일·제목·브랜치의 번호, 검사 결과),
열린 이슈 제목의 DEV 번호(Cozy Office 가 터미널 세션을 팀에 앉히는 근거, post-logic.js reqFlowOf).
설정·표준·Spec 판정은 devready.read 를 그대로 쓴다(새 작업 화면·PR 검사 spec-ready 와 같은 기준). 세션을 요구사항에 붙이는 일과
칸 배정은 화면(post-pipeline.js)이 한다 — 세션 목록은 화면이 이미 가지고 있다.

합쳐짐: 원장 상태 `완료` 또는 SRS Status `Done`. 작업 PR: 열린 PR 이 src/ 를 바꿨다. Spec PR: docs/spec/DEV-xxx 를 바꿨다.
PR 이 어느 요구사항 것인지는 바뀐 Spec 파일 이름과 PR 제목·브랜치 이름의 REQ-/DEV- 번호로만 안다(커밋 제목 규칙이 DEV 번호를 적는다).

state: yes(읽음) / no(SRS·원장이 없는 저장소, git 저장소 아님 = 해당 없음) / unknown(읽지 못함, 지어내지 않는다).
PR 을 못 읽어도 요구사항 판은 보이되 prs.state 가 unknown 이라고 따로 말한다(검토 칸이 비었다고 단정하지 않게).
"""
from __future__ import annotations

import os
import re

import devready
import gitstate

PR_LIMIT = 100
ISSUE_LIMIT = 300  # 이보다 오래된 열린 이슈는 표에 없다 — 그 브랜치 세션은 팀 없음(근거 없음)으로 떨어진다
ISSUE_TAG_RE = re.compile(r"^\s*\[DEV-(\d+)\]")  # start 스킬 reserve_number.py TAG_RE(개발 본체 이슈)
ISSUE_SUB_RE = re.compile(r"\(DEV-(\d+)\)\s*$")  # 같은 파일 SUBTASK_RE(하위 작업 이슈)
SPEC_FILE_RE = re.compile(r"^docs/spec/DEV-(\d+)[^/]*\.md$")
# 제목·브랜치의 번호: `DEV-013`, `REQ-019`, 브랜치의 `dev013`. 앞이 글자면(device 따위) 번호로 보지 않는다
NUM_RE = re.compile(r"(?<![A-Za-z])(?:REQ|DEV)-?(\d{1,6})(?!\d)", re.IGNORECASE)
WORK_PREFIX = "src/"
DONE_SRS = "done"
HIDDEN_STATUS = {"dropped", "duplicate", "on hold"}  # 보류·취소된 요구사항은 판에 올리지 않고 수만 센다


def repo_key(run: gitstate.Runner, cwd: str) -> tuple[str, str]:
    """(저장소 열쇠, 이름). 같은 저장소의 worktree 들은 같은 열쇠다(git 공통 폴더). 저장소가 아니면 (폴더, 폴더 이름)."""
    rc, out = run(["git", "rev-parse", "--git-common-dir"], cwd)
    common = out.strip() if rc == 0 else ""
    if not common:
        return os.path.normcase(os.path.realpath(cwd)), os.path.basename(os.path.realpath(cwd))
    common = os.path.realpath(os.path.join(cwd, common))
    name = os.path.basename(os.path.dirname(common)) if os.path.basename(common) == ".git" else os.path.basename(common).removesuffix(".git")
    return os.path.normcase(common), name


def _has_git_above(cwd: str) -> bool:
    p = os.path.realpath(cwd)
    while True:
        if os.path.exists(os.path.join(p, ".git")) or os.path.basename(p) == ".git":
            return True
        up = os.path.dirname(p)
        if up == p:
            return False
        p = up


def repo_info(run: gitstate.Runner, cwd: str) -> dict:
    """세션 작업 폴더가 어느 저장소인가(#1070, Post 의 프로젝트 거르기). repo_key 와 같은 기준(git 공통 폴더)이라 같은 저장소의 worktree 는 같은 key 다.
    state: yes(저장소, key·name·top(그 폴더의 맨 위 폴더)·folder(맨 위 폴더 이름)) / no(폴더는 있는데 git 저장소가 아님)
    / unknown(폴더가 없거나 git 을 실행하지 못함, .git 이 있는데 git 이 못 읽음 — 어느 저장소라고 지어내지 않는다)."""
    if not cwd or not os.path.isdir(cwd):
        return {"state": "unknown", "reason": "작업 폴더가 없어."}
    rc, out = run(["git", "rev-parse", "--git-common-dir", "--show-toplevel"], cwd)
    if rc == gitstate.GIT_UNAVAILABLE:
        return {"state": "unknown", "reason": "git 을 실행하지 못했어."}
    lines = [x.strip() for x in out.splitlines() if x.strip()] if rc == 0 else []
    if not lines:
        if _has_git_above(cwd):  # .git 은 있는데 git 이 못 읽었다(소유자 검사 dubious ownership, 권한, .git 안쪽 폴더) — 저장소 아님으로 단정하지 않는다
            return {"state": "unknown", "reason": "git 이 이 폴더의 저장소를 읽지 못했어."}
        return {"state": "no", "reason": "git 저장소가 아니야."}
    key, name = repo_key(lambda a, c: (0, lines[0]), cwd)
    top = os.path.realpath(lines[1] if len(lines) > 1 else cwd)
    return {"state": "yes", "key": key, "name": name, "top": top, "folder": os.path.basename(top) or top}


def nums_in(text: str) -> set[int]:
    return {int(m.group(1)) for m in NUM_RE.finditer(text or "")}


def open_prs(run: gitstate.Runner, root: str) -> dict:
    """열린 PR 을 요구사항 번호별로 묶는다. {"state": "ok"|"no"|"unknown", "reason", "byNumber": {번호: [{number,url,title,kind,checks,awaitApproval,draft}]}}.
    kind: work(src/ 를 바꿈) / spec(그 번호의 Spec 파일을 바꿈) / doc(그 밖)."""
    if not gitstate.is_github_repo(run, root):
        return {"state": "no", "reason": "git 원격이 GitHub 인 저장소가 아니라 PR 은 보지 않아.", "byNumber": {}}
    rc, out = run(["gh", "pr", "list", "--state", "open", "--limit", str(PR_LIMIT), "--json",
                   "number,title,url,headRefName,isDraft,files,statusCheckRollup"], root)
    data = gitstate._json(out) if rc == 0 else None
    if not isinstance(data, list):
        return {"state": "unknown", "reason": "gh 로 열린 PR 을 읽지 못했어(gh 로그인·네트워크 확인).", "byNumber": {}}
    by: dict[int, list[dict]] = {}
    for d in data:
        if not isinstance(d, dict) or not d.get("number"):
            continue
        paths = [str(f.get("path")) for f in d.get("files") or [] if isinstance(f, dict) and f.get("path")]
        spec_nums = {int(m.group(1)) for m in (SPEC_FILE_RE.match(p) for p in paths) if m}
        work = any(p.startswith(WORK_PREFIX) for p in paths)
        base = {"number": d["number"], "url": d.get("url", ""), "title": d.get("title", ""), "draft": bool(d.get("isDraft")), "branch": d.get("headRefName", ""),
                "checks": gitstate.summarize_checks(d.get("statusCheckRollup")), "awaitApproval": gitstate.awaiting_approval(d.get("statusCheckRollup"))}
        for n in sorted(spec_nums | nums_in(f"{d.get('title', '')} {d.get('headRefName', '')}")):
            by.setdefault(n, []).append(dict(base, kind="work" if work else "spec" if spec_nums else "doc"))
    return {"state": "ok", "reason": "", "byNumber": by}


def open_issues(run: gitstate.Runner, root: str) -> dict:
    """열린 이슈 중 DEV 번호가 붙은 것: {"state": "ok"|"no"|"unknown", "reason", "byIssue": {"이슈번호": {"dev": n, "main": bool}}}.
    main: 제목 맨 앞 `[DEV-xxx]`(개발 본체 이슈 — start·srs 의 번호 찜), 아니면 제목 끝 `(DEV-xxx)`(하위 작업 이슈). 형식은 start 스킬
    reserve_number.py 의 TAG_RE·SUBTASK_RE 와 같다. Cozy Office 가 세션 브랜치(`{type}/{이슈번호}-…`)의 이슈로 그 세션의 요구사항을 안다."""
    if not gitstate.is_github_repo(run, root):
        return {"state": "no", "reason": "git 원격이 GitHub 인 저장소가 아니라 이슈는 보지 않아.", "byIssue": {}}
    rc, out = run(["gh", "issue", "list", "--state", "open", "--limit", str(ISSUE_LIMIT), "--json", "number,title"], root)
    data = gitstate._json(out) if rc == 0 else None
    if not isinstance(data, list):
        return {"state": "unknown", "reason": "gh 로 열린 이슈를 읽지 못했어(gh 로그인·네트워크 확인).", "byIssue": {}}
    by: dict[str, dict] = {}
    for d in data:
        if not isinstance(d, dict) or not d.get("number"):
            continue
        title = str(d.get("title") or "")
        m, sub = ISSUE_TAG_RE.match(title), ISSUE_SUB_RE.search(title)
        if m or sub:
            by[str(d["number"])] = {"dev": int((m or sub).group(1)), "main": bool(m)}
    return {"state": "ok", "reason": "", "byIssue": by}


def read(run: gitstate.Runner, slow_run: gitstate.Runner, cwd: str) -> dict:
    ready = devready.read(run, slow_run, cwd)  # 저장소·SRS·원장 확인, origin/main 받기, Spec·설정·표준 판정
    if ready.get("state") != "yes":
        return {"state": ready.get("state", "unknown"), "reason": ready.get("reason", "")}
    root = gitstate.repo_root(run, cwd) or cwd

    def show(path: str) -> str | None:
        rc, text = run(["git", "show", f"origin/main:{path}"], root)
        return text if rc == 0 else None

    rc, tree = run(["git", "-c", "core.quotepath=false", "ls-tree", "-r", "--name-only", "origin/main", "--", "docs/ssot/SRS.md", "audit/ledger"], root)
    if rc != 0:
        return {"state": "unknown", "reason": "origin/main 의 파일 목록을 읽지 못했어."}
    srs: dict[int, dict] = {}
    ledger: dict[int, dict] = {}
    for line in tree.splitlines():
        line = line.strip()
        if line == "docs/ssot/SRS.md" or (line.startswith("audit/ledger/") and line.endswith(".md")):
            text = show(line)
            if text is None:
                return {"state": "unknown", "reason": f"origin/main 의 {line} 을 읽지 못했어."}
            if line == "docs/ssot/SRS.md":
                for n, row in devready._rows(text, devready.REQ_ROW_RE):
                    srs[n] = {"title": devready._pick(row, "Title", "요구사항"), "status": devready._pick(row, "Status", "상태")}
            else:
                for n, row in devready._rows(text, devready.DEV_ROW_RE):
                    ledger.setdefault(n, {"title": devready._pick(row, "내용"), "status": devready._pick(row, "상태")})

    prs = open_prs(run, root)
    items, hidden = [], 0
    for it in ready.get("items", []):
        n = it["number"]
        s, lg = srs.get(n), ledger.get(n)
        if s is None and lg is None and not it["spec"]:
            continue  # RICEFW 칸이 가리키기만 한 번호: 제목도 진행도 모른다
        status = (s or {}).get("status", "").strip()
        if status.casefold() in HIDDEN_STATUS:
            hidden += 1
            continue
        title = (s or {}).get("title") or (lg or {}).get("title") or ""
        next_step = it.get("next", "").strip()
        items.append({
            "number": n, "req": f"REQ-{n:03d}" if s else "", "dev": f"DEV-{n:03d}", "title": devready._title(title),
            "kind": devready.STANDARD if it["standard"] else devready.SETUP if it["setup"] else "",
            "spec": it["spec"], "next": next_step,
            # SRS 에 있는데 다음 단계가 개발·설정·표준 어느 것도 아니다 = 아직 갈래가 정해지지 않았다
            "unsure": bool(s) and not it["setup"] and next_step != devready.DEV_NEXT and not it["spec"],
            "done": status.casefold() == DONE_SRS or (lg or {}).get("status", "").strip() == devready.DONE_LEDGER,
            "srsStatus": status, "ledgerStatus": (lg or {}).get("status", "").strip(),
            "prs": prs["byNumber"].get(n, []),
        })
    return {"state": "yes", "reason": "", "items": items, "hidden": hidden, "srsCount": len(srs),
            "prs": {"state": prs["state"], "reason": prs["reason"]}, "issues": open_issues(run, root)}
