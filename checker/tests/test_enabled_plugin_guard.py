"""#471 — `.claude/settings.json` 의 enabledPlugins 에서 harness 가 빠지거나 꺼지는 커밋·푸시를 훅이 거절하는지.

`pre-bash-git-guard.sh` 를 임시 저장소에서 돌린다. 커밋 앞단의 gitleaks 검사는 가짜 gitleaks 로 통과시킨다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from checker.tests.test_git_guard_secret_scan import (  # noqa: F401 - repo 는 pytest 픽스처
    _fake_env,
    _git,
    _guard,
    _reason,
    repo,
)
from checker.tests.test_plugin_layout import _HAS_BASH, _HAS_JQ

pytestmark = [
    pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다"),
    pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다"),
]

PID = "harness@blueward-harness"
SETTINGS = ".claude/settings.json"


def _write(work: Path, data) -> None:
    path = work / SETTINGS
    path.parent.mkdir(exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _commit_settings(work: Path, data, msg: str = "settings") -> None:
    _write(work, data)
    _git(work, "add", SETTINGS)
    _git(work, "commit", "-q", "-m", msg)


def _on(**extra) -> dict:
    return {"enabledPlugins": {PID: True, **extra}}


def _stage_settings(work: Path, data) -> None:
    _write(work, data)
    _git(work, "add", SETTINGS)


def _commit(tmp_path: Path, work: Path):
    return _guard(work, "git commit -m x", **_fake_env(tmp_path, 0))


# ---- 커밋 ----


def test_커밋_harness_항목을_지우면_거절하고_되돌리는_방법을_안내한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, {"enabledPlugins": {}})
    code, out = _commit(tmp_path, repo)
    reason = _reason(out)
    assert "enabledPlugins" in reason and PID in reason
    assert "다음:" in reason and f"git restore --staged --worktree {SETTINGS}" in reason


def test_커밋_harness_를_false_로_바꾸면_거절한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, {"enabledPlugins": {PID: False}})
    code, out = _commit(tmp_path, repo)
    assert "enabledPlugins" in _reason(out)


def test_커밋_enabledPlugins_통째로_없어져도_거절한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, {"autoUpdate": True})
    code, out = _commit(tmp_path, repo)
    assert "enabledPlugins" in _reason(out)


def test_커밋_설정_파일을_지워도_거절한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _git(repo, "rm", "-q", SETTINGS)
    code, out = _commit(tmp_path, repo)
    assert "enabledPlugins" in _reason(out)


def test_커밋_키_순서만_바뀌면_통과한다(repo, tmp_path):
    _commit_settings(repo, {"a": 1, "enabledPlugins": {PID: True, "x@y": True}, "z": [1, 2]})
    _stage_settings(repo, {"z": [1, 2], "enabledPlugins": {"x@y": True, PID: True}, "a": 1})
    code, out = _commit(tmp_path, repo)
    assert code == 0 and out is None


def test_커밋_다른_항목만_바꾸면_통과한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, _on(**{"other@market": True}))
    code, out = _commit(tmp_path, repo)
    assert code == 0 and out is None


def test_커밋_파일이_원래_없으면_통과한다(repo, tmp_path):
    _stage_settings(repo, {"enabledPlugins": {}})
    code, out = _commit(tmp_path, repo)
    assert code == 0 and out is None


def test_커밋_harness_항목이_원래_없거나_꺼져_있었으면_통과한다(repo, tmp_path):
    _commit_settings(repo, {"enabledPlugins": {"x@y": True}})
    _stage_settings(repo, {"enabledPlugins": {}})
    assert _commit(tmp_path, repo)[1] is None
    _git(repo, "commit", "-q", "-m", "a")
    _commit_settings(repo, {"enabledPlugins": {PID: False}}, "off")
    _stage_settings(repo, {"enabledPlugins": {}})
    assert _commit(tmp_path, repo)[1] is None


def test_커밋_JSON_을_못_읽으면_검사_불능으로_거절한다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, "{ not json")
    code, out = _commit(tmp_path, repo)
    reason = _reason(out)
    assert "검사 불능" in reason and "다음:" in reason


def test_커밋_원래_JSON_이_깨져_있었고_새_판도_켜지_않았으면_검사_불능이다(repo, tmp_path):
    _commit_settings(repo, "{ broken")
    _stage_settings(repo, {"enabledPlugins": {}})
    assert "검사 불능" in _reason(_commit(tmp_path, repo)[1])


def test_커밋_원래_JSON_이_깨져_있어도_새_판이_켜져_있으면_통과한다(repo, tmp_path):
    _commit_settings(repo, "{ broken")
    _stage_settings(repo, _on())
    assert _commit(tmp_path, repo)[1] is None


# ---- 푸시 ----


@pytest.fixture
def pushed(repo, tmp_path):
    """origin(bare) 에 harness 가 켜진 settings 를 올려 둔 저장소. upstream 이 origin/<브랜치>."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", bare.as_posix())
    _commit_settings(repo, _on())
    _git(repo, "push", "-q", "-u", "origin", "feat/170-x")
    return repo


def _push(work: Path):
    return _guard(work, "git push origin HEAD")


def test_푸시_범위에서_harness_가_빠졌으면_거절한다(pushed):
    _commit_settings(pushed, {"enabledPlugins": {}}, "drop")
    code, out = _push(pushed)
    reason = _reason(out)
    assert "enabledPlugins" in reason and PID in reason
    assert "다음:" in reason and "git restore --source=" in reason and SETTINGS in reason


def test_푸시_중간에_빠졌다가_되돌렸으면_통과한다(pushed):
    _commit_settings(pushed, {"enabledPlugins": {}}, "drop")
    _commit_settings(pushed, _on(), "restore")
    code, out = _push(pushed)
    # enabledPlugins 검사는 지나고 뒤의 "스킬을 거치지 않은 푸시" 거절에 닿는다
    assert "enabledPlugins" not in _reason(out) and "/harness:deliver" in _reason(out)


def test_푸시_설정_파일을_안_건드린_커밋은_통과한다(pushed):
    (pushed / "a.txt").write_text("x\n", encoding="utf-8")
    _git(pushed, "add", "a.txt")
    _git(pushed, "commit", "-q", "-m", "a")
    assert "enabledPlugins" not in _reason(_push(pushed)[1])


def test_푸시_키_순서만_바뀌었으면_통과한다(pushed):
    _commit_settings(pushed, {"enabledPlugins": {PID: True}, "a": 1}, "reorder")
    _commit_settings(pushed, {"a": 1, "enabledPlugins": {PID: True}}, "reorder2")
    assert "enabledPlugins" not in _reason(_push(pushed)[1])


def test_푸시_기준_브랜치를_못_찾으면_검사_불능으로_거절한다(repo, tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    _git(repo, "remote", "add", "origin", bare.as_posix())
    _commit_settings(repo, _on())
    _git(repo, "push", "-q", "origin", "HEAD:refs/heads/other")  # upstream 없이 origin/other 만 생김
    _commit_settings(repo, {"enabledPlugins": {}}, "drop")
    reason = _reason(_push(repo)[1])
    assert "검사 불능" in reason and "다음:" in reason


def test_푸시_받아_둔_원격_브랜치가_없으면_견줄_기준이_없어_통과한다(repo):
    _commit_settings(repo, _on())
    _commit_settings(repo, {"enabledPlugins": {}}, "drop")
    assert "enabledPlugins" not in _reason(_push(repo)[1])


# ---- 저장소 하위 폴더에서 실행 ----


def test_하위_폴더에서_커밋해도_저장소_루트의_설정을_본다(repo, tmp_path):
    _commit_settings(repo, _on())
    _stage_settings(repo, {"enabledPlugins": {}})
    sub = repo / "docs" / "deep"
    sub.mkdir(parents=True)
    code, out = _guard(sub, "git commit -m x", **_fake_env(tmp_path, 0))
    assert "enabledPlugins" in _reason(out)


def test_하위_폴더에서_푸시해도_저장소_루트의_설정을_본다(pushed):
    _commit_settings(pushed, {"enabledPlugins": {}}, "drop")
    sub = pushed / "docs" / "deep"
    sub.mkdir(parents=True)
    code, out = _guard(sub, "git push origin HEAD")
    assert "enabledPlugins" in _reason(out)
