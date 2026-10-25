"""`.claude/settings.json` 의 키 순서만 바뀐 변경은 미커밋으로 세지 않는다(#448).

`claude plugin install` 이 키 순서만 바꿔 저장하면 Stop 훅·세션 시작 훅이 deliver 를
요구하던 문제다. 값이 바뀌었거나, 파싱할 수 없거나, HEAD 에 없는 새 파일이면 변경으로 센다.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _HAS_BASH, PLUGIN_ROOT
from checker.tests.test_unfinished_snapshot import _fields, _git, _record, _repo, _start, _stop, _write

pytestmark = pytest.mark.skipif(
    not _HAS_BASH or shutil.which("uv") is None, reason="bash 와 uv 가 없으면 훅을 실행해 볼 수 없다"
)

SETTINGS = ".claude/settings.json"
ORIGINAL = '{\n  "a": 1,\n  "plugins": {"x": true, "y": false}\n}\n'
REORDERED = '{"plugins": {"y": false, "x": true},\n "a": 1}'
SYNC_SKIP = "커밋되지 않은 변경이 있어 자동 동기화"


@pytest.fixture(scope="module")
def session_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("settings-root") / "harness"
    (root / "hooks").mkdir(parents=True)
    for name in ("session-start-sync.sh", "json_same_as_head.py"):
        shutil.copy(PLUGIN_ROOT / "hooks" / name, root / "hooks" / name)
    return root


def _repo_with_settings(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, SETTINGS, ORIGINAL)
    _git(repo, "add", SETTINGS)
    _git(repo, "commit", "-q", "-m", "settings")
    return repo


def _counted(session_root: Path, repo: Path) -> tuple[bool, bool]:
    """(Stop 훅이 변경으로 셌는가, 세션 시작 훅이 변경으로 셌는가)."""
    _stop(repo)
    stop_counted = any(_fields(repo).get("snap_commit", []))
    _record(repo).unlink(missing_ok=True)
    return stop_counted, SYNC_SKIP in _start(session_root, repo)


def test_순서만_바뀌면_세지_않는다(session_root, tmp_path):
    repo = _repo_with_settings(tmp_path)
    _write(repo, SETTINGS, REORDERED)
    assert _git(repo, "status", "--porcelain")  # git 은 변경으로 본다
    assert _counted(session_root, repo) == (False, False)
    assert (repo / SETTINGS).read_text(encoding="utf-8") == REORDERED  # 파일은 되돌리지 않는다


def test_값이_바뀌면_센다(session_root, tmp_path):
    repo = _repo_with_settings(tmp_path)
    _write(repo, SETTINGS, '{"plugins": {"y": false, "x": false}, "a": 1}')
    assert _counted(session_root, repo) == (True, True)


def test_파싱할_수_없으면_센다(session_root, tmp_path):
    repo = _repo_with_settings(tmp_path)
    _write(repo, SETTINGS, '{"a": 1,')
    assert _counted(session_root, repo) == (True, True)


def test_HEAD_에_없는_새_파일이면_센다(session_root, tmp_path):
    repo = _repo(tmp_path, with_origin=True)
    _write(repo, SETTINGS, ORIGINAL)
    assert _counted(session_root, repo) == (True, True)


def test_순서만_바뀐_것과_다른_변경이_함께_있으면_다른_변경만_센다(session_root, tmp_path):
    repo = _repo_with_settings(tmp_path)
    _write(repo, SETTINGS, REORDERED)
    _write(repo, "new.txt", "new\n")
    _stop(repo)
    assert "A new.txt" in _fields(repo)["snap_file"]


def test_스테이징된_값_변경이_있으면_작업_트리가_순서만_달라도_센다(session_root, tmp_path):
    # MM: 인덱스에는 값이 바뀐 판, 작업 트리는 HEAD 와 값이 같은 판(순서만 다름).
    repo = _repo_with_settings(tmp_path)
    _write(repo, SETTINGS, '{"plugins": {"y": false, "x": false}, "a": 1}')
    _git(repo, "add", SETTINGS)
    _write(repo, SETTINGS, REORDERED)
    assert _counted(session_root, repo) == (True, True)
