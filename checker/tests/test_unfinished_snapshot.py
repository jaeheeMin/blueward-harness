"""지난 세션 미완료 기록(#224) 테스트.

`stop-deliver.sh` 가 대답마다 작업 사본(refs/harness/unfinished/...)과 기록 파일을 남기고,
`session-start-sync.sh` 가 다음 시작에 이미 처리된 것은 조용히 지우고 사라진 것만 알리는지
임시 git 저장소(와 로컬 bare 원격)에서 훅을 직접 돌려 확인한다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

pytestmark = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")

LOST = "커밋되지 않고 사라진 것이"
PUSH = "push 안 한 커밋이"


@pytest.fixture(scope="module")
def session_root(tmp_path_factory) -> Path:
    # ensure-tools.sh 는 복사하지 않아 winget 설치를 시도하지 않는다.
    root = tmp_path_factory.mktemp("unfinished-root") / "harness"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(PLUGIN_ROOT / "hooks" / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    return root


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    )
    return done.stdout.strip()


def _repo(tmp_path: Path, with_origin: bool = False) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "README.md").write_text("test\n", encoding="utf-8", newline="\n")
    (repo / "other.txt").write_text("other\n", encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    if with_origin:
        bare = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "-u", "origin", "main")
        _git(repo, "checkout", "-q", "-b", "feature/x")
    return repo


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _env(**extra: str) -> dict:
    env = {**os.environ, "HARNESS_NO_SCAFFOLD_HINT": "1", **extra}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return env


def _stop(repo: Path, **extra_env: str) -> str:
    done = subprocess.run(
        [_BASH, str(PLUGIN_ROOT / "hooks" / "stop-deliver.sh")],
        input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True, encoding="utf-8",
        env=_env(**extra_env), timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _start(root: Path, repo: Path) -> str:
    done = subprocess.run(
        [_BASH, str(root / "hooks" / "session-start-sync.sh")],
        input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True, encoding="utf-8",
        env=_env(CLAUDE_PLUGIN_ROOT=str(root)), timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _record(repo: Path) -> Path:
    return repo / ".git" / "project-unfinished"


def _fields(repo: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in _record(repo).read_text(encoding="utf-8").splitlines()[1:]:
        key, _, value = line.partition("=")
        out.setdefault(key, []).append(value)
    return out


def _snap_refs(repo: Path) -> list[str]:
    return _git(repo, "for-each-ref", "--format=%(refname)", "refs/harness/").splitlines()


def test_a_커밋만_하고_작업트리가_깨끗하면_경고는_없고_push_안_됨을_알린다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "README.md", "changed\n")
    assert '"block"' in _stop(repo)
    _git(repo, "commit", "-q", "-am", "work")
    _stop(repo)  # 커밋한 대답도 Stop 으로 끝난다. 변경이 없으니 push 정보만 갱신된다.

    out = _start(session_root, repo)

    assert LOST not in out
    assert PUSH in out and "다음: /harness:deliver" in out
    assert _snap_refs(repo) == []  # 사본은 처리됐으니 조용히 지워졌다
    assert "snap_commit" not in _record(repo).read_text(encoding="utf-8")


def test_b_사라진_파일만_경고하고_안내한_명령으로_복구된다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "changed\n")
    _write(repo, "새 문서/한글 파일.txt", "새 내용\n")
    _stop(repo)
    _git(repo, "commit", "-q", "-am", "readme only")
    shutil.rmtree(repo / "새 문서")  # 커밋 없이 사라진다

    out = _start(session_root, repo)

    assert LOST in out
    assert "새 문서/한글 파일.txt" in out
    assert "- README.md" not in out
    restore = next(l for l in out.splitlines() if l.startswith("다음: git --literal-pathspecs restore"))
    assert "'새 문서/한글 파일.txt'" in restore
    assert len(_snap_refs(repo)) == 1  # 복구용 ref 는 남는다
    assert "git update-ref -d refs/harness/unfinished/" in out

    done = subprocess.run(
        [_BASH, "-c", restore[len("다음: "):]], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stderr
    assert (repo / "새 문서" / "한글 파일.txt").read_text(encoding="utf-8") == "새 내용\n"

    # 같은 경고가 되풀이되지 않는다.
    assert LOST not in _start(session_root, repo)
    assert not _record(repo).exists()


def test_c_같은_파일을_더_고쳐_커밋하면_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "v1\n")
    _stop(repo)
    _write(repo, "README.md", "v2\n")
    _git(repo, "commit", "-q", "-am", "v2")

    out = _start(session_root, repo)

    assert LOST not in out and "확인 불능" not in out
    assert _snap_refs(repo) == []
    assert not _record(repo).exists()


def test_d_인계_메모만_있다가_지우면_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness-handoff.md", "메모\n")
    _write(repo, ".superpowers/state.json", "{}\n")
    _stop(repo)
    (repo / "harness-handoff.md").unlink()
    shutil.rmtree(repo / ".superpowers")

    out = _start(session_root, repo)

    assert LOST not in out and "지난 세션" not in out
    assert _snap_refs(repo) == []
    assert not _record(repo).exists()


def test_인계_메모는_사본에_들어가지_않는다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "changed\n")
    _write(repo, "docs/인계-handoff.md", "메모\n")
    _write(repo, ".superpowers/state.json", "{}\n")
    _write(repo, "sub/.superpowers/x", "{}\n")
    _stop(repo)

    files = _fields(repo)["snap_file"]
    assert files == ["M README.md"]


def test_e_변경이_남아_있으면_지난_경고를_내지_않고_기록을_둔다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    before = _fields(repo)["snap_commit"]

    out = _start(session_root, repo)

    assert LOST not in out
    assert "커밋되지 않은 변경이 있습니다." in out
    assert _fields(repo)["snap_commit"] == before
    assert len(_snap_refs(repo)) == 1


def test_f_변화가_없으면_사본을_다시_뜨지_않는다(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    first = _fields(repo)["snap_commit"]
    _stop(repo)
    assert _fields(repo)["snap_commit"] == first

    _write(repo, "new.txt", "new and more\n")
    _stop(repo)
    assert _fields(repo)["snap_commit"] != first


def test_사본은_실제_index_와_작업트리를_바꾸지_않는다(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "README.md", "changed\n")
    _write(repo, "new.txt", "new\n")
    _git(repo, "add", "README.md")
    status_before = _git(repo, "status", "--porcelain")

    _stop(repo)

    assert _git(repo, "status", "--porcelain") == status_before
    commit = _fields(repo)["snap_commit"][0]
    assert _git(repo, "show", f"{commit}:new.txt") == "new"
    assert _git(repo, "show", f"{commit}:README.md") == "changed"


def test_gitignore_된_파일은_사본에_들어가지_않고_큰_새_파일은_이름만_남는다(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".gitignore", "ignored.log\n")
    _write(repo, "ignored.log", "x\n")
    _write(repo, "big.bin", "x" * 5000)
    _write(repo, "small.txt", "s\n")

    _stop(repo, HARNESS_SNAPSHOT_MAX_BYTES="1000")

    fields = _fields(repo)
    assert sorted(fields["snap_file"]) == ["A .gitignore", "A small.txt"]
    assert fields["big_file"] == ["big.bin"]


def test_g_옛_형식_파일은_한_번_보이고_지워진다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _record(repo).write_text("[경고] 커밋되지 않은 변경이 옛브랜치 브랜치에 남은 채로 세션이 끝났습니다.\n", encoding="utf-8")

    out = _start(session_root, repo)
    assert "지난 세션에서 남은 경고가 있습니다." in out and "옛브랜치" in out
    assert not _record(repo).exists()
    assert "옛브랜치" not in _start(session_root, repo)


def test_옛_형식_파일은_stop_이_덮어쓰기_전에_보존된다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _record(repo).write_text("[경고] 옛브랜치\n", encoding="utf-8")
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    (repo / "new.txt").unlink()

    out = _start(session_root, repo)

    assert "옛브랜치" in out
    assert "옛브랜치" not in _start(session_root, repo)


def test_h_원격에_push_했으면_push_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "README.md", "changed\n")
    _stop(repo)
    _git(repo, "commit", "-q", "-am", "work")
    _stop(repo)
    assert _fields(repo)["unpushed_branch"] == ["feature/x"]
    _git(repo, "push", "-q", "-u", "origin", "feature/x")

    out = _start(session_root, repo)

    assert PUSH not in out
    assert not _record(repo).exists()


def test_원격_브랜치가_병합_뒤_지워졌으면_push_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "README.md", "changed\n")
    _git(repo, "commit", "-q", "-am", "work")
    _git(repo, "push", "-q", "-u", "origin", "feature/x")
    _write(repo, "other.txt", "again\n")
    _git(repo, "commit", "-q", "-am", "more")  # 아직 push 안 한 커밋
    _stop(repo)
    assert _fields(repo)["unpushed_branch"] == ["feature/x"]
    _git(repo, "push", "-q", "origin", "--delete", "feature/x")

    out = _start(session_root, repo)

    assert PUSH not in out
    assert not _record(repo).exists()


def test_push_안_한_커밋이_계속_있으면_시작마다_알린다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "README.md", "changed\n")
    _git(repo, "commit", "-q", "-am", "work")
    _stop(repo)

    assert PUSH in _start(session_root, repo)
    assert PUSH in _start(session_root, repo)


def test_사본을_못_뜨면_확인_불능으로_알린다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "new.txt", "new\n")
    # 임시 index 를 만들 수 없게 TMPDIR 을 없는 곳으로 돌린다.
    _stop(repo, TMPDIR=str(tmp_path / "없는폴더"), TMP=str(tmp_path / "없는폴더"), TEMP=str(tmp_path / "없는폴더"))
    assert _fields(repo)["snap_failed"] == ["1"]
    (repo / "new.txt").unlink()

    out = _start(session_root, repo)

    assert "확인 불능" in out
    assert LOST not in out


# --- 검토 지적 반영 ---------------------------------------------------------


def _restore_line(out: str) -> str:
    return next(l for l in out.splitlines() if l.startswith("다음: git --literal-pathspecs restore"))


def _run_restore(repo: Path, out: str) -> None:
    done = subprocess.run(
        [_BASH, "-c", _restore_line(out)[len("다음: "):]], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    assert done.returncode == 0, done.stderr


def test_큰_새_파일만_있다가_사라지면_복구_불가로_알린다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "big.bin", "x" * 5000)
    _stop(repo, HARNESS_SNAPSHOT_MAX_BYTES="1000")
    fields = _fields(repo)
    assert fields["snap_commit"] == [""]
    assert fields["big_file"] == ["big.bin"]
    (repo / "big.bin").unlink()

    out = _start(session_root, repo)

    assert "big.bin" in out and "복구할 수 없음" in out
    assert not _record(repo).exists()


def test_큰_새_파일이_커밋됐으면_조용히_지운다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "big.bin", "x" * 5000)
    _stop(repo, HARNESS_SNAPSHOT_MAX_BYTES="1000")
    _git(repo, "add", "big.bin")
    _git(repo, "commit", "-q", "-m", "big")

    out = _start(session_root, repo)

    assert "복구할 수 없음" not in out
    assert not _record(repo).exists()


def test_커밋이_없는_저장소도_사본을_뜬다(session_root, tmp_path):
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "first.txt", "first\n")

    _stop(repo)

    fields = _fields(repo)
    assert fields["snap_file"] == ["A first.txt"]
    assert fields["snap_failed"] == [""]
    commit = fields["snap_commit"][0]
    assert _git(repo, "show", f"{commit}:first.txt") == "first"
    (repo / "first.txt").unlink()
    out = _start(session_root, repo)
    assert LOST in out and "first.txt" in out


def test_글롭_문자가_든_파일명을_글자_그대로_판정하고_복구한다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "pages/[id].tsx", "dynamic\n")
    _write(repo, "pages/d.tsx", "d\n")
    _stop(repo)
    _git(repo, "add", "pages/d.tsx")
    _git(repo, "commit", "-q", "-m", "d only")
    (repo / "pages" / "[id].tsx").unlink()

    out = _start(session_root, repo)

    assert LOST in out
    assert "- pages/[id].tsx" in out
    assert "- pages/d.tsx" not in out
    _run_restore(repo, out)
    assert (repo / "pages" / "[id].tsx").read_text(encoding="utf-8") == "dynamic\n"
    assert (repo / "pages" / "d.tsx").read_text(encoding="utf-8") == "d\n"


def test_원격을_가져오지_못하면_판정하지_않고_기록을_남긴다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    (repo / "new.txt").unlink()
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "없는-원격.git"))

    out = _start(session_root, repo)

    assert "원격을 가져오지 못해 지난 작업을 판정하지 못했습니다" in out
    assert LOST not in out
    assert _record(repo).exists() and len(_snap_refs(repo)) == 1

    # 원격이 돌아오면 그때 판정한다.
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "origin.git"))
    assert LOST in _start(session_root, repo)


def test_리베이스_진행_중이면_판정하지_않고_기록을_남긴다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    (repo / "new.txt").unlink()
    (repo / ".git" / "rebase-merge").mkdir()

    out = _start(session_root, repo)

    assert "원격을 가져오지 못해 지난 작업을 판정하지 못했습니다" in out
    assert LOST not in out
    assert _record(repo).exists()


def test_squash_병합처럼_원격_main_에_다른_내용으로_들어갔으면_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, "README.md", "my version\n")
    _stop(repo)
    # 같은 파일이 원격 main 에 다른 내용(squash 결과)으로 들어간다.
    other = tmp_path / "other-clone"
    subprocess.run(["git", "clone", "-q", "-b", "main", str(tmp_path / "origin.git"), str(other)], check=True)
    _git(other, "config", "user.email", "o@example.com")
    _git(other, "config", "user.name", "o")
    _write(other, "README.md", "squashed version\n")
    _git(other, "commit", "-q", "-am", "squash")
    _git(other, "push", "-q", "origin", "HEAD:main")
    _git(repo, "reset", "-q", "--hard")
    _git(repo, "checkout", "-q", "main")

    out = _start(session_root, repo)

    assert LOST not in out and "확인 불능" not in out
    assert _snap_refs(repo) == []


def test_삭제한_파일이_되살아났으면_경고한다(session_root, tmp_path):
    repo = _repo(tmp_path)
    (repo / "other.txt").unlink()
    _stop(repo)
    assert _fields(repo)["snap_file"] == ["D other.txt"]
    _git(repo, "checkout", "--", "other.txt")  # 삭제가 커밋 없이 사라졌다

    out = _start(session_root, repo)

    assert LOST in out and "other.txt" in out and "삭제" in out
    assert not any(l.startswith("다음: git --literal-pathspecs restore") for l in out.splitlines())


def test_삭제를_커밋했으면_조용하다(session_root, tmp_path):
    repo = _repo(tmp_path)
    (repo / "other.txt").unlink()
    _stop(repo)
    _git(repo, "commit", "-q", "-am", "delete")

    out = _start(session_root, repo)

    assert LOST not in out
    assert _snap_refs(repo) == []


def test_이름이_바뀐_파일이_커밋됐으면_경고가_없다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "mv", "other.txt", "renamed.txt")
    _stop(repo)
    assert sorted(_fields(repo)["snap_file"]) == ["A renamed.txt", "D other.txt"]
    _git(repo, "commit", "-q", "-m", "rename")

    out = _start(session_root, repo)

    assert LOST not in out
    assert _snap_refs(repo) == []


def test_이름이_바뀐_파일이_사라지면_새_이름을_복구한다(session_root, tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "mv", "other.txt", "renamed.txt")
    _stop(repo)
    _git(repo, "reset", "-q", "--hard")

    out = _start(session_root, repo)

    assert LOST in out and "- renamed.txt" in out
    _run_restore(repo, out)
    assert (repo / "renamed.txt").read_text(encoding="utf-8") == "other\n"


def test_다른_worktree_의_사본은_판정에_섞이지_않는다(session_root, tmp_path):
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "other")
    _write(repo, "x.txt", "root\n")
    _stop(repo)
    _write(wt, "x.txt", "worktree\n")
    _stop(wt)
    assert sorted(r.rsplit("/", 1)[1] for r in _snap_refs(repo)) == ["root", "wt-wt"]
    (repo / "x.txt").unlink()

    out = _start(session_root, repo)

    # worktree 의 사본이 x.txt 를 건드렸어도 이 worktree 의 유실을 가리지 않는다.
    assert LOST in out and "- x.txt" in out
    # 다른 worktree 의 사본 ref 는 지워지지 않는다.
    assert any(r.endswith("/wt-wt") for r in _snap_refs(repo))


def test_이_worktree_가_깨끗해도_다른_worktree_의_사본은_지우지_않는다(session_root, tmp_path):
    repo = _repo(tmp_path)
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "other")
    _write(repo, "x.txt", "root\n")
    _stop(repo)
    _write(wt, "y.txt", "wt\n")
    _stop(wt)
    _git(repo, "add", "x.txt")
    _git(repo, "commit", "-q", "-m", "x")

    out = _start(session_root, repo)

    assert LOST not in out
    assert [r.rsplit("/", 1)[1] for r in _snap_refs(repo)] == ["wt-wt"]


def test_서명이_같으면_사본을_다시_뜨지_않는다_시각으로_확인(tmp_path):
    import time

    repo = _repo(tmp_path)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    first = _fields(repo)
    time.sleep(1.2)
    _stop(repo)  # 서명이 같으면 snap_time 도 그대로다(다시 떴다면 새 시각이 적힌다)
    assert _fields(repo)["snap_time"] == first["snap_time"]
    assert _fields(repo)["snap_commit"] == first["snap_commit"]


def test_10개를_넘으면_앞_10개와_나머지_개수를_알린다(session_root, tmp_path):
    repo = _repo(tmp_path)
    for i in range(12):
        _write(repo, f"many/f{i:02d}.txt", f"{i}\n")
    _stop(repo)
    shutil.rmtree(repo / "many")

    out = _start(session_root, repo)

    assert "사라진 것이 12개" in out
    assert sum(1 for l in out.splitlines() if l.startswith("- many/")) == 10
    assert "... 외 2개" in out
