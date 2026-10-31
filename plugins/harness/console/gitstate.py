"""`이번 차례` 판단(web-console.md §7). 위에서부터 처음 맞는 것을 고른다."""
from __future__ import annotations

import os
import subprocess
from typing import Callable

from platform_compat import hidden_window_kwargs

Runner = Callable[[list[str], str], tuple[int, str]]


def run_command(args: list[str], cwd: str, timeout: float = 5.0) -> tuple[int, str]:
    """명령을 실행해 (종료코드, stdout) 을 돌려준다. 실행 불능은 (127, "")."""
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, **hidden_window_kwargs())
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
    """{"isRepo", "repo", "branch", "changedFiles", "skill", "unknown"}. skill 은 start/deliver/prs/None."""
    result = {"isRepo": False, "repo": "", "branch": "", "changedFiles": [], "skill": None, "unknown": False}
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
    if branch in (base, "HEAD", ""):
        result["skill"] = "start"  # 2. 기본 브랜치에 있다
        return result
    ahead = 0
    rc, out = _git(run, cwd, "rev-list", "--count", "@{u}..HEAD")
    if rc != 0:  # 올려 둔 곳이 없으면 기본 브랜치 대비로 센다
        rc, out = _git(run, cwd, "rev-list", "--count", f"origin/{base}..HEAD")
    if rc == 0 and out.strip().isdigit():
        ahead = int(out.strip())
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
