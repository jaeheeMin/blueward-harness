"""세션 시작 훅의 scaffold 안내(#128) 테스트.

기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더)가 없는 저장소에서만
`/harness:scaffold` 를 안내하는지 `session-start-sync.sh` 를 임시 저장소에서 돌려 확인한다.
ensure-tools.sh 는 복사하지 않아(winget 설치를 시도한다) 도구 설치는 일어나지 않고,
원격이 없는 저장소라 fetch 도 하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

pytestmark = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")

HINT = "기준 폴더(templates/ 와 rules/)가 없습니다."


@pytest.fixture(scope="module")
def session_plugin_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("hint-root") / "harness"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(PLUGIN_ROOT / "hooks" / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    return root


def _run(root: Path, cwd: Path, **extra_env: str) -> str:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root), **extra_env}
    env.pop("CLAUDE_PROJECT_DIR", None)
    if "HARNESS_NO_SCAFFOLD_HINT" not in extra_env:
        env.pop("HARNESS_NO_SCAFFOLD_HINT", None)
    done = subprocess.run(
        [_BASH, str(root / "hooks" / "session-start-sync.sh")],
        input=json.dumps({"cwd": str(cwd)}), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _standards(folder: Path) -> None:
    (folder / "templates").mkdir(parents=True)
    (folder / "rules").mkdir()


def test_기준_폴더가_없으면_scaffold_를_안내한다(session_plugin_root, tmp_path):
    out = _run(session_plugin_root, _git_repo(tmp_path))
    assert HINT in out
    line = next(l for l in out.splitlines() if HINT in l)
    assert "다음: /harness:scaffold" in line
    assert "현재 브랜치:" in out  # 다른 출력이 깨지지 않는다


def test_templates_만_있고_rules_가_없으면_안내한다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "templates").mkdir()
    assert HINT in _run(session_plugin_root, repo)


def test_꼭대기에_기준_폴더가_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    assert HINT not in _run(session_plugin_root, repo)


def test_하위_폴더에_기준_폴더가_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo / "customer-a" / "std")
    assert HINT not in _run(session_plugin_root, repo)


def test_하위_폴더에서_세션을_열어도_저장소_꼭대기_기준으로_본다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    (repo / "docs").mkdir()
    assert HINT not in _run(session_plugin_root, repo / "docs")


def test_node_modules_안의_기준_폴더는_세지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo / "node_modules" / "pkg")
    assert HINT in _run(session_plugin_root, repo)


def test_marketplace_json_이_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    assert HINT not in _run(session_plugin_root, repo)


def test_환경_변수로_안내를_끈다(session_plugin_root, tmp_path):
    out = _run(session_plugin_root, _git_repo(tmp_path), HARNESS_NO_SCAFFOLD_HINT="1")
    assert HINT not in out
    assert "현재 브랜치:" in out


def test_git_저장소가_아니면_안내하지_않는다(session_plugin_root, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    out = _run(session_plugin_root, plain)
    assert HINT not in out
    assert "git 저장소가 아닙니다" in out
