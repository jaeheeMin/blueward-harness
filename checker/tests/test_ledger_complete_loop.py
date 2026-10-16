"""`scripts/ledger_complete_loop.sh`(ledger-complete.yml 의 재시도 루프)를 임시 git 저장소에서 실제로 돌린다(#346).

가짜 apply 와 가짜 원격(bare 저장소)으로 push 충돌, 종료 2, 빈 출력, 여러 커밋 범위를 확인한다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOOP = ROOT / "scripts" / "ledger_complete_loop.sh"
REPO = "o/r"

def _find_bash() -> str | None:
    """진짜 bash 를 찾는다. Windows 에서는 PATH 의 System32 bash.exe(WSL 실행기)를 피하고 Git for Windows 의 것을 쓴다."""
    if os.name == "nt":
        candidates = [
            Path(os.environ.get(key, default)) / "Git" / "bin" / "bash.exe"
            for key, default in (("ProgramFiles", r"C:\Program Files"), ("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        ]
        git = shutil.which("git")
        if git:  # git.exe 가 있는 설치 폴더(…/cmd/git.exe → …/bin/bash.exe)
            root = Path(git).resolve().parent.parent
            candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
        for c in candidates:
            if c.is_file():
                return str(c)
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


_BASH = _find_bash()

pytestmark = pytest.mark.skipif(
    _BASH is None or shutil.which("jq") is None or shutil.which("git") is None,
    reason="bash(WSL 실행기 제외), jq, git 이 필요하다",
)

FAKE_APPLY = """#!/bin/bash
# 가짜 apply: 인자를 기록하고, MODE 에 따라 동작한다.
echo "$@" >> "$FAKE_DIR/args.txt"
n=$(( $(cat "$FAKE_DIR/count.txt" 2>/dev/null || echo 0) + 1 ))
echo $n > "$FAKE_DIR/count.txt"
case "$MODE" in
  unknown) echo '{"status":"unknown","prs":[],"changed":[],"reason":"판정 불능: 가짜"}'; exit 2 ;;
  empty) exit 0 ;;
  exit1) echo "boom" >&2; exit 1 ;;
  noop) echo '{"status":"skipped","prs":[],"changed":[],"reason":"병합 PR 없음"}'; exit 0 ;;
esac
if [ "$MODE" = race ] && [ "$n" = 1 ]; then
  RACE=1
fi
if [ "$MODE" = always_race ]; then
  RACE=1
fi
if [ -n "${RACE:-}" ]; then
  # 도중에 다른 사람이 main 에 먼저 push 해서 이쪽 push 가 밀린다.
  rm -rf "$FAKE_DIR/other" && git clone -q "$FAKE_DIR/../remote.git" "$FAKE_DIR/other"
  ( cd "$FAKE_DIR/other" && git config user.email o@o && git config user.name o \\
    && echo "other$n" > "other$n.txt" && git add . && git commit -qm other && git push -q origin HEAD:main )
fi
echo "attempt $n" >> audit/ledger/a.md
echo '{"status":"changed","prs":[50,51],"changed":["DEV-001"],"reason":"원장을 고쳤다"}'
"""


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture
def env(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t")
    _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-q", "-B", "main")
    (work / "audit" / "ledger").mkdir(parents=True)
    (work / "audit" / "ledger" / "a.md").write_text("ledger\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "base")
    base = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "origin", "HEAD:main")
    (work / "x.txt").write_text("x", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "second")
    second = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "origin", "HEAD:main")
    fake = tmp_path / "fake"
    fake.mkdir()
    script = fake / "apply.sh"
    with open(script, "w", encoding="utf-8", newline="\n") as f:
        f.write(FAKE_APPLY)
    script.chmod(0o755)
    return {"work": work, "remote": remote, "fake": fake, "script": script, "base": base, "second": second}


def _loop(env: dict, mode: str, before: str = "", attempts: str = "5", sha: str | None = None):
    e = dict(os.environ)
    e.update({
        "REPO": REPO, "SHA": sha or env["second"], "BEFORE": before, "ATTEMPTS": attempts, "RETRY_SLEEP_MAX": "0",
        "APPLY_CMD": env["script"].as_posix(), "FAKE_DIR": env["fake"].as_posix(), "MODE": mode,
        "GITHUB_OUTPUT": (env["fake"] / "out.txt").as_posix(),
    })
    return subprocess.run([_BASH, str(LOOP)], cwd=env["work"], env=e, capture_output=True, text=True, encoding="utf-8")


def _outcome(env: dict) -> str:
    return (env["fake"] / "out.txt").read_text(encoding="utf-8").strip()


def _reason(env: dict) -> str:
    return (env["work"] / "reason.txt").read_text(encoding="utf-8")


def _count(env: dict) -> str:
    return (env["fake"] / "count.txt").read_text().strip()


def test_push_가_한_번_밀려도_다시_받아_성공한다(env):
    done = _loop(env, "race")
    assert done.returncode == 0, done.stderr
    assert _outcome(env) == "outcome=done"
    log = _git(env["remote"], "log", "--format=%s", "main")
    assert "other" in log and "docs: 진행 원장 완료 표시" in log
    assert "Refs #50, #51" in _git(env["remote"], "log", "-1", "--format=%B", "main")
    assert _count(env) == "2"
    assert _git(env["remote"], "log", "-1", "--format=%an", "main") == "github-actions[bot]"
    # 첫 시도의 변경은 reset --hard 로 버려지고 마지막 시도의 줄만 남는다.
    ledger = _git(env["remote"], "show", "main:audit/ledger/a.md")
    assert ledger.count("attempt") == 1 and "attempt 2" in ledger


def test_종료_2_이면_되풀이하지_않고_실패(env):
    done = _loop(env, "unknown")
    assert done.returncode == 0
    assert _outcome(env) == "outcome=failed"
    assert "판정 불능: 가짜" in _reason(env)
    assert _count(env) == "1"
    assert _git(env["remote"], "rev-parse", "main") == env["second"]


def test_출력이_비면_실패로_처리한다(env):
    _loop(env, "empty")
    assert _outcome(env) == "outcome=failed"
    assert "status" in _reason(env)
    assert _git(env["remote"], "rev-parse", "main") == env["second"]


def test_바꿀_것이_없으면_push_없이_성공(env):
    _loop(env, "noop")
    assert _outcome(env) == "outcome=done"
    assert _git(env["remote"], "rev-parse", "main") == env["second"]


def test_before_가_없거나_모르면_SHA_하나만_넘긴다(env):
    for before in ("", "0" * 40, "f" * 40):
        (env["fake"] / "args.txt").unlink(missing_ok=True)
        _loop(env, "noop", before=before)
        args = (env["fake"] / "args.txt").read_text()
        assert args.count("--sha") == 1 and env["second"] in args


def test_before_범위의_커밋을_오래된_것부터_모두_넘긴다(env):
    work = env["work"]
    (work / "y.txt").write_text("y", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "third")
    third = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _loop(env, "noop", before=env["base"], sha=third)
    args = (env["fake"] / "args.txt").read_text().split()
    assert [args[i + 1] for i, a in enumerate(args) if a == "--sha"] == [env["second"], third]


def test_시도를_다_쓰면_실패(env):
    _loop(env, "always_race", attempts="3")
    assert _outcome(env) == "outcome=failed"
    assert "push 가 3번 실패" in _reason(env)
    assert _count(env) == "3"


def test_apply_종료_1_도_되풀이하지_않고_실패(env):
    _loop(env, "exit1")
    assert _outcome(env) == "outcome=failed"
    assert "종료코드 1" in _reason(env) and "boom" in _reason(env)
    assert _count(env) == "1"


def test_권한_거부_같은_push_실패는_즉시_실패(env):
    hook = env["remote"] / "hooks" / "pre-receive"
    with open(hook, "w", encoding="utf-8", newline="\n") as f:
        f.write("#!/bin/sh\necho denied >&2\nexit 1\n")
    hook.chmod(0o755)
    _loop(env, "normal")
    assert _outcome(env) == "outcome=failed"
    assert "거부" in _reason(env)
    assert _count(env) == "1"
    assert _git(env["remote"], "rev-parse", "main") == env["second"]
