"""세션 시작 훅(session-start-sync.sh)의 SRS 자동 합치기 연결(#977)을 임시 저장소에서 검증한다.

진짜 uvx 대신 가짜 `uvx` 가 같은 엔진(`checker.srs_automerge`)을 로컬 파이썬으로 돌린다. 합침 성공(merge·rebase), 조건 밖 거절, 엔진 실패.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from checker.pairing import SRS_PATH

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "harness"


def _find_bash() -> str | None:
    if os.name == "nt":
        for var, default in (("ProgramFiles", r"C:\Program Files"), ("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cand = Path(os.environ.get(var, default)) / "Git" / "bin" / "bash.exe"
            if cand.is_file():
                return str(cand)
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


_BASH = _find_bash()
pytestmark = pytest.mark.skipif(_BASH is None, reason="bash 가 없으면 훅을 실행해 볼 수 없다")

HEAD = "# P SRS\n\n버전: 0.1\n\n## 범위\n\n- 조회\n\n## 요구사항\n\n"
TABLE_HEAD = "| ID | Title | Status |\n|---|---|---|\n"
ROW = "| REQ-{n:03d} | 제목{n} | New |\n"
DETAIL = "### REQ-{n:03d} 제목{n}\n\n설명{n}\n\n"
TAIL = "## 참조\n\n없음\n"


def doc(nums: list[int], head: str = HEAD) -> str:
    return head + TABLE_HEAD + "".join(ROW.format(n=n) for n in nums) + "\n" + "".join(DETAIL.format(n=n) for n in nums) + TAIL


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    return done


def put(repo: Path, text: str) -> None:
    p = repo / SRS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))


def commit(repo: Path, msg: str) -> None:
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)


def clone(origin: Path, dest: Path) -> None:
    run(origin.parent, "clone", "-q", str(origin), str(dest))
    run(dest, "config", "user.email", "t@example.com")
    run(dest, "config", "user.name", "t")
    run(dest, "config", "core.autocrlf", "false")


def setup(tmp_path: Path, pushed: bool) -> tuple[Path, Path]:
    """(main 쪽 clone, 작업 clone). pushed 면 작업 브랜치가 upstream 을 가진다(merge 경로), 아니면 없다(rebase 경로)."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    run(origin, "init", "-q", "--bare")
    run(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp_path / "seed"
    clone(origin, seed)
    put(seed, doc([1]))
    commit(seed, "init")
    run(seed, "push", "-q", "origin", "HEAD:main")
    work = tmp_path / "work"
    clone(origin, work)
    run(work, "switch", "-q", "-c", "feature/1-thing")
    if pushed:
        run(work, "push", "-q", "-u", "origin", "feature/1-thing")
    return seed, work


def fake_uvx(tmp_path: Path, fail: bool = False) -> Path:
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    body = "exit 1\n" if fail else f'shift 3\nPYTHONPATH="{REPO_ROOT.as_posix()}" exec "{Path(sys.executable).as_posix()}" "$@"\n'
    script = bin_dir / "uvx"
    script.write_text("#!/bin/bash\n" + body, encoding="utf-8", newline="\n")
    script.chmod(0o755)
    return bin_dir


def session_start(work: Path, bin_dir: Path) -> str:
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "CLAUDE_PROJECT_DIR": str(work),
        "DOC_GUARD_ENGINE": "dummy",
        "PYTHONUTF8": "1",
    }
    done = subprocess.run(
        [_BASH, str(PLUGIN_ROOT / "hooks" / "session-start-sync.sh")],
        input="{}", capture_output=True, text=True, encoding="utf-8", env=env, timeout=120,
    )
    return done.stdout


def rev(repo: Path, ref: str = "HEAD") -> str:
    return run(repo, "rev-parse", ref).stdout.strip()


def in_progress(repo: Path) -> bool:
    git_dir = repo / run(repo, "rev-parse", "--git-dir").stdout.strip()
    return any((git_dir / n).exists() for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply"))


def test_merge_경로_SRS_줄_추가_충돌은_자동으로_합쳐_커밋한다(tmp_path):
    seed, work = setup(tmp_path, pushed=True)
    put(work, doc([1, 3]))
    commit(work, "feat: 내 요구사항")
    run(work, "push", "-q", "origin", "feature/1-thing")
    put(seed, doc([1, 2]))
    commit(seed, "feat: main 요구사항")
    run(seed, "push", "-q", "origin", "HEAD:main")

    out = session_start(work, fake_uvx(tmp_path))

    assert "자동으로 합쳤어" in out and "승인을 다시 받아야 해" in out
    assert "충돌 2곳" in out
    assert not in_progress(work)
    text = (work / SRS_PATH).read_text(encoding="utf-8")
    assert text.index("REQ-002") < text.index("REQ-003")
    assert run(work, "log", "-1", "--format=%s").stdout.strip() == "chore: main 의 새 변경 합쳐 받기"
    assert len(run(work, "log", "-1", "--format=%P").stdout.split()) == 2


def test_merge_경로_버전_줄_충돌은_거절하고_되돌린다(tmp_path):
    seed, work = setup(tmp_path, pushed=True)
    put(work, doc([1], head=HEAD.replace("0.1", "0.3")))
    commit(work, "feat: 내 버전")
    run(work, "push", "-q", "origin", "feature/1-thing")
    put(seed, doc([1], head=HEAD.replace("0.1", "0.2")))
    commit(seed, "feat: main 버전")
    run(seed, "push", "-q", "origin", "HEAD:main")
    before = rev(work)

    out = session_start(work, fake_uvx(tmp_path))

    assert "합치다 충돌해 원래 상태로 되돌렸습니다" in out
    assert "자동으로 합쳤어" not in out
    assert not in_progress(work) and rev(work) == before


def test_merge_경로_엔진이_실패하면_검사_불능으로_되돌린다(tmp_path):
    seed, work = setup(tmp_path, pushed=True)
    put(work, doc([1, 3]))
    commit(work, "feat: 내 요구사항")
    run(work, "push", "-q", "origin", "feature/1-thing")
    put(seed, doc([1, 2]))
    commit(seed, "feat: main 요구사항")
    run(seed, "push", "-q", "origin", "HEAD:main")
    before = rev(work)

    out = session_start(work, fake_uvx(tmp_path, fail=True))

    assert "합치다 충돌해 원래 상태로 되돌렸습니다" in out
    assert not in_progress(work) and rev(work) == before


def test_rebase_경로_커밋_여럿의_SRS_충돌도_이어서_자동으로_합친다(tmp_path):
    seed, work = setup(tmp_path, pushed=False)
    put(work, doc([1, 3]))
    commit(work, "feat: 내 요구사항 3")
    put(work, doc([1, 3, 4]))
    commit(work, "feat: 내 요구사항 4")
    put(seed, doc([1, 2]))
    commit(seed, "feat: main 요구사항")
    run(seed, "push", "-q", "origin", "HEAD:main")

    out = session_start(work, fake_uvx(tmp_path))

    assert "자동으로 합쳤어" in out and "승인을 다시 받아야 해" in out
    assert not in_progress(work)
    text = (work / SRS_PATH).read_text(encoding="utf-8")
    assert all(f"| REQ-00{n} |" in text and f"### REQ-00{n}" in text for n in (1, 2, 3, 4))
    assert text.index("REQ-002") < text.index("REQ-003") < text.index("REQ-004")
    assert run(work, "merge-base", "--is-ancestor", "origin/main", "HEAD").returncode == 0
    assert run(work, "log", "--format=%s", "-2").stdout.splitlines() == ["feat: 내 요구사항 4", "feat: 내 요구사항 3"]


def test_rebase_경로_버전_줄_충돌은_거절하고_되돌린다(tmp_path):
    seed, work = setup(tmp_path, pushed=False)
    put(work, doc([1], head=HEAD.replace("0.1", "0.3")))
    commit(work, "feat: 내 버전")
    put(seed, doc([1], head=HEAD.replace("0.1", "0.2")))
    commit(seed, "feat: main 버전")
    run(seed, "push", "-q", "origin", "HEAD:main")
    before = rev(work)

    out = session_start(work, fake_uvx(tmp_path))

    assert "리베이스가 충돌해 원래 상태로 되돌렸습니다" in out
    assert "자동으로 합쳤어" not in out
    assert not in_progress(work) and rev(work) == before


def test_엔진_JSON_이_merged_가_아니면_합친_것으로_보지_않는다(tmp_path):
    # 가짜 uvx 가 종료코드 0 인데 merged 가 없는 출력을 내도 abort 한다.
    seed, work = setup(tmp_path, pushed=False)
    put(work, doc([1], head=HEAD.replace("0.1", "0.3")))
    commit(work, "feat: 내 버전")
    put(seed, doc([1], head=HEAD.replace("0.1", "0.2")))
    commit(seed, "feat: main 버전")
    run(seed, "push", "-q", "origin", "HEAD:main")
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    script = bin_dir / "uvx"
    script.write_text("#!/bin/bash\necho '" + json.dumps({"status": "refused"}) + "'\nexit 0\n", encoding="utf-8", newline="\n")
    script.chmod(0o755)
    before = rev(work)

    out = session_start(work, bin_dir)

    assert "되돌렸습니다" in out and not in_progress(work) and rev(work) == before
