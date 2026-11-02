"""`이번 차례` 판단(web-console.md §7). 위에서부터 처음 맞는 것을 고른다."""
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Callable

from platform_compat import hidden_window_kwargs

Runner = Callable[[list[str], str], tuple[int, str]]
GIT_UNAVAILABLE = 127  # run_command 가 실행 불능(없음·시간 초과)에 돌려주는 종료코드


def run_command(args: list[str], cwd: str, timeout: float = 5.0, merge_stderr: bool = False) -> tuple[int, str]:
    """명령을 실행해 (종료코드, stdout) 을 돌려준다. 실행 불능은 (127, ""). merge_stderr 면 오류 글도 stdout 에 합친다(오류 요약용)."""
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=not merge_stderr, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, **({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT} if merge_stderr else {}),
                              **hidden_window_kwargs())
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout


def _git(run: Runner, cwd: str, *args: str) -> tuple[int, str]:
    return run(["git", "-c", "core.quotepath=false", *args], cwd)  # 한글 파일명을 \\ooo 로 바꾸지 않게


def default_branch(run: Runner, cwd: str) -> str:
    rc, out = _git(run, cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and out.strip():
        return out.strip().split("/", 1)[-1]
    for name in ("main", "master"):
        if _git(run, cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")[0] == 0:
            return name
    return "main"


def inspect(cwd: str, run: Runner = run_command) -> dict:
    """{"isRepo", "repo", "branch", "changedFiles", "skill", "unknown", "ahead"}. skill 은 start/deliver/prs/None."""
    result = {"isRepo": False, "repo": "", "branch": "", "changedFiles": [], "skill": None, "unknown": False, "ahead": 0,
              "onBase": False}
    if not cwd or not os.path.isdir(cwd):
        return result
    rc, top = _git(run, cwd, "rev-parse", "--show-toplevel")
    if rc != 0 or not top.strip():
        return result  # 1. git 저장소가 아니다 -> 차례 없음
    result["isRepo"] = True
    result["repo"] = os.path.basename(top.strip().rstrip("/\\"))
    rc, branch = _git(run, cwd, "rev-parse", "--abbrev-ref", "HEAD")
    branch = branch.strip() if rc == 0 else ""
    result["branch"] = branch
    rc, status = _git(run, cwd, "status", "--porcelain")
    files = [line[3:].strip().strip('"') for line in status.splitlines() if len(line) > 3] if rc == 0 else []
    result["changedFiles"] = files
    base = default_branch(run, cwd)
    result["onBase"] = branch in (base, "HEAD", "")  # 기본 브랜치(또는 분리된 HEAD)에 있다 = 새 작업 브랜치가 아직 없다
    if result["onBase"]:
        result["skill"] = "start"  # 2. 기본 브랜치에 있다
        return result
    ahead = 0
    rc, out = _git(run, cwd, "rev-list", "--count", "@{u}..HEAD")
    if rc != 0:  # 올려 둔 곳이 없으면 기본 브랜치 대비로 센다
        rc, out = _git(run, cwd, "rev-list", "--count", f"origin/{base}..HEAD")
    if rc == 0 and out.strip().isdigit():
        ahead = int(out.strip())
    result["ahead"] = ahead
    if files or ahead:
        result["skill"] = "deliver"  # 3. 커밋 안 된 변경이나 원격보다 앞선 커밋
        return result
    rc, out = run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"], cwd)
    if rc != 0:
        result["unknown"] = True  # gh 가 없거나 실패 -> PR 판단을 건너뛴다
        result["skill"] = "start"
        return result
    if out.strip() not in ("", "[]"):
        result["skill"] = "prs"  # 4. 열린 PR
        return result
    result["skill"] = "start"  # 5. 그 밖
    return result


# ---- 갈래 진행 판정과 승인자 판정에 쓰는 gh 조회. 실패는 "unknown" 으로 돌려주고 없음·통과로 뭉개지 않는다 ----
GH_TIMEOUT = 20.0
PR_LIST_LIMIT = 100
PR_FIELDS = "number,state,url,title,mergedAt,statusCheckRollup"
FAILED_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"}
PASSED_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
ADMIN_PERMISSION = "ADMIN"
WHEN_NO_FILE_ADMIN = "admin"


def gh_runner() -> Runner:
    """gh 호출은 git 보다 오래 걸릴 수 있어 제한 시간을 늘린 실행기."""
    return lambda args, cwd: run_command(args, cwd, GH_TIMEOUT)


def repo_root(run: Runner, cwd: str) -> str:
    rc, top = _git(run, cwd, "rev-parse", "--show-toplevel")
    return top.strip() if rc == 0 and top.strip() else ""


def repo_root_checked(run: Runner, cwd: str) -> tuple[str, bool]:
    """(맨 위 폴더, git 을 실행하지 못했는가). 저장소가 아닌 것(("", False))과 git 실행 실패(("", True))를 가른다."""
    rc, top = _git(run, cwd, "rev-parse", "--show-toplevel")
    if rc == GIT_UNAVAILABLE:
        return "", True
    return (top.strip() if rc == 0 and top.strip() else ""), False


# ---- 문서 목록(바뀐 파일)과 작업용 폴더(worktree) ----
SLOW_GIT_TIMEOUT = 180.0   # fetch·worktree add 는 네트워크와 체크아웃 때문에 오래 걸릴 수 있다
ERROR_SUMMARY_LIMIT = 300


def status_paths(run: Runner, cwd: str) -> tuple[list[str], str]:
    """git status 의 바뀐·새 파일을 절대 경로로. (경로 목록, 못 읽은 사유). 저장소가 아니면 ([], ""), git 을 실행하지 못했거나
    status 가 실패하면 ([], 사유) — 빈 목록을 '바뀐 것 없음' 으로 읽지 않게 사유를 따로 낸다."""
    root, failed = repo_root_checked(run, cwd)
    if failed:
        return [], "git 을 실행하지 못했습니다."
    if not root:
        return [], ""
    rc, out = _git(run, cwd, "status", "--porcelain", "-z", "-uall")
    if rc != 0:
        return [], "git status 가 실패했습니다."
    entries, paths, i = out.split("\0"), [], 0
    while i < len(entries):
        entry, i = entries[i], i + 1
        if len(entry) < 4:
            continue
        if entry[0] in "RC" or entry[1] in "RC":
            i += 1  # 이름을 바꾼 줄은 원래 이름이 다음 항목으로 따라온다
        if "D" in entry[:2]:
            continue
        paths.append(os.path.join(root, *entry[3:].split("/")))
    return paths, ""


def summarize_error(out: str) -> str:
    text = " ".join((out or "").split())
    return text[-ERROR_SUMMARY_LIMIT:] if text else "자세한 오류 글이 없습니다."


def worktree_path(root: str, short_id: str) -> str:
    root = root.rstrip("/\\")
    return os.path.join(os.path.dirname(root), f"{os.path.basename(root)}-wt-{short_id}")


def add_worktree(run: Runner, slow_run: Runner, root: str, path: str) -> str:
    """origin 을 가져와 기본 브랜치 끝에서 떼어낸(detached) 작업용 폴더를 만든다. 브랜치는 만들지 않는다. 성공이면 "", 실패면 사유."""
    rc, out = _git(slow_run, root, "fetch", "origin")
    if rc != 0:
        return "git fetch 가 실패했습니다: " + summarize_error(out)
    base = default_branch(run, root)
    rc, out = _git(slow_run, root, "worktree", "add", "--detach", path, f"origin/{base}")
    if rc != 0:
        return "git worktree add 가 실패했습니다: " + summarize_error(out)
    return ""


def _json(out: str):
    try:
        return json.loads(out)
    except ValueError:
        return None


def summarize_checks(rollup) -> str:
    """statusCheckRollup 을 fail/pending/pass/none 으로 줄인다."""
    if not isinstance(rollup, list) or not rollup:
        return "none"
    pending = False
    for item in rollup:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        conclusion = str(item.get("conclusion") or item.get("state") or "").upper()
        if conclusion in FAILED_CONCLUSIONS:
            return "fail"
        if (status and status != "COMPLETED") or conclusion not in PASSED_CONCLUSIONS:
            pending = True
    return "pending" if pending else "pass"


def _pr_item(raw: dict) -> dict:
    return {"number": raw.get("number"), "state": str(raw.get("state") or "").upper(), "url": raw.get("url", ""),
            "title": raw.get("title", ""), "checks": summarize_checks(raw.get("statusCheckRollup"))}


def pr_status(run: Runner, cwd: str, branch: str, number: int | None = None) -> dict:
    """{"state": "ok"|"unknown", "pr": {number,state,url,title,checks}|None, "reason"}. 병합된 PR 은 번호로 다시 본다(브랜치가 바뀌어도)."""
    if number:
        rc, out = run(["gh", "pr", "view", str(number), "--json", PR_FIELDS], cwd)
        data = _json(out) if rc == 0 else None
        if not isinstance(data, dict):
            return {"state": "unknown", "pr": None, "reason": f"gh 로 PR #{number} 를 읽지 못했습니다."}
        return {"state": "ok", "pr": _pr_item(data), "reason": ""}
    if not branch or branch in ("HEAD", default_branch(run, cwd)):
        return {"state": "ok", "pr": None, "reason": ""}
    rc, out = run(["gh", "pr", "list", "--head", branch, "--state", "all", "--limit", "5", "--json", PR_FIELDS], cwd)
    data = _json(out) if rc == 0 else None
    if not isinstance(data, list):
        return {"state": "unknown", "pr": None, "reason": "gh 로 PR 상태를 읽지 못했습니다(gh 가 없거나 로그인·네트워크 문제)."}
    items = [_pr_item(d) for d in data if isinstance(d, dict)]
    for want in ("OPEN", "MERGED", "CLOSED"):
        hit = next((i for i in items if i["state"] == want), None)
        if hit:
            return {"state": "ok", "pr": hit, "reason": ""}
    return {"state": "ok", "pr": None, "reason": ""}


def parse_approvers(text: str | None) -> tuple[dict[str, set[str]], set[str], bool]:
    """`.github/ssot-approvers` 읽기. checker.ssot_approval.parse_approvers 와 같은 형식이다(엔진은 이 플러그인 밖이라 따로 둔다).
    (작성자별 승인자, 기본 승인자, 내용이 있는가)."""
    by_author: dict[str, set[str]] = {}
    default: set[str] = set()
    has_entries = False
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        has_entries = True
        if ":" not in line:
            default.add(line.lstrip("@").strip().lower())
            continue
        left, right = line.split(":", 1)
        key = left.strip().lstrip("@").strip().lower()
        logins = {t.lstrip("@").lower() for t in re.split(r"[\s,]+", right) if t.lstrip("@")}
        if key == "*":
            default |= logins
        elif key:
            by_author.setdefault(key, set()).update(logins)
    return by_author, default, has_entries


GITHUB_REMOTE = re.compile(r"github\.com[:/]", re.IGNORECASE)


def is_github_repo(run: Runner, cwd: str) -> bool:
    """폴더가 git 저장소이고 원격 하나라도 GitHub 이면 True. git 을 실행하지 못했으면(127) 판단하지 못하므로 True 로 두어 gh 가 말하게 한다."""
    rc, out = _git(run, cwd, "remote", "-v")
    if rc == 127:
        return True
    return rc == 0 and bool(GITHUB_REMOTE.search(out))


def _approver_rules(run: Runner, cwd: str, rel_file: str, when_no_file: str) -> dict:
    """{"state": "yes"|"no"|"unknown", "reason", "login", "rules", "admin"}. rules 는 (by_author, default, has_entries)."""
    if not is_github_repo(run, cwd):
        return {"state": "no", "reason": "git 원격이 GitHub 인 저장소가 아니라 승인자를 따지지 않습니다.", "login": "", "rules": None,
                "admin": None, "github": False}
    rc, out = run(["gh", "api", "user", "--jq", ".login"], cwd)
    login = out.strip().lower() if rc == 0 else ""
    if not login:
        return {"state": "unknown", "reason": "gh 로 내 GitHub 아이디를 읽지 못했습니다(gh 로그인·네트워크 확인).", "login": "", "rules": None, "admin": None}
    root = repo_root(run, cwd) or cwd
    text = None
    path = os.path.join(root, *rel_file.split("/"))
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            return {"state": "unknown", "reason": f"{rel_file} 을 읽지 못했습니다: {e}", "login": login, "rules": None, "admin": None}
    rules = parse_approvers(text)
    base = {"login": login, "rules": rules, "admin": None}
    if rules[2]:
        everyone = set(rules[1]).union(*rules[0].values())
        yes = login in everyone
        return dict(base, state="yes" if yes else "no",
                    reason="" if yes else f"{rel_file} 의 승인자에 {login} 가 없습니다.")
    rc, out = run(["gh", "repo", "view", "--json", "viewerPermission", "--jq", ".viewerPermission"], cwd)
    if rc != 0 or not out.strip():
        return dict(base, state="unknown", reason="gh 로 저장소 권한을 읽지 못했습니다(gh 로그인·네트워크 확인).")
    admin = out.strip().upper() == ADMIN_PERMISSION
    return dict(base, state="yes" if admin else "no", admin=admin,
                reason=f"{rel_file} 이 없어 저장소 admin 만 승인자로 봅니다." + ("" if admin else " 내 권한은 admin 이 아닙니다."))


def approver_state(run: Runner, cwd: str, rel_file: str, when_no_file: str) -> dict:
    info = _approver_rules(run, cwd, rel_file, when_no_file)
    return {"state": info["state"], "reason": info["reason"], "login": info["login"]}


def approval_prs(run: Runner, cwd: str, rel_file: str, when_no_file: str) -> dict:
    """내 승인을 기다리는 열린 PR. {"state": "ok"|"no"|"unknown", "reason", "login", "items"}. 병합 순서는 계산하지 않는다(/harness:approvals 가 한다)."""
    info = _approver_rules(run, cwd, rel_file, when_no_file)
    out_base = {"state": info["state"], "reason": info["reason"], "login": info["login"], "items": []}
    if info["state"] != "yes":
        return out_base
    rc, out = run(["gh", "pr", "list", "--state", "open", "--limit", str(PR_LIST_LIMIT), "--json",
                   "number,title,url,author,isDraft,headRefOid,latestReviews"], cwd)
    data = _json(out) if rc == 0 else None
    if not isinstance(data, list):
        return dict(out_base, state="unknown", reason="gh 로 열린 PR 목록을 읽지 못했습니다.")
    by_author, default, has_entries = info["rules"]
    login, items = info["login"], []
    for pr in data:
        if not isinstance(pr, dict) or pr.get("isDraft"):
            continue
        author = str((pr.get("author") or {}).get("login", "")).lower()
        if not author or author == login:
            continue
        if has_entries and login not in {a for a in (by_author[author] if author in by_author else default) if a != author}:
            continue
        head = pr.get("headRefOid")
        mine = [r for r in pr.get("latestReviews") or [] if isinstance(r, dict) and str((r.get("author") or {}).get("login", "")).lower() == login]
        if any(r.get("state") == "APPROVED" and (r.get("commit") or {}).get("oid") == head for r in mine):
            continue  # 최신 커밋을 이미 승인했다
        items.append({"number": pr.get("number"), "title": pr.get("title", ""), "url": pr.get("url", ""), "author": author,
                      "staleApproval": any(r.get("state") == "APPROVED" for r in mine)})
    items.sort(key=lambda i: i["number"] or 0)
    return dict(out_base, items=items)
