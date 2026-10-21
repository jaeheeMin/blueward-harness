"""#404 — 현재 폴더(projectPath) 설치 판 확인(installed_version.py) 테스트."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

import pytest

from checker.tests.test_plugin_layout import PLUGIN_ROOT

_spec = importlib.util.spec_from_file_location("installed_version", PLUGIN_ROOT / "hooks" / "installed_version.py")
iv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iv)

PID = "harness@blueward-harness"


def _write(tmp_path, *entries, plugin=PID):
    cfg = tmp_path / "cfg"
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {plugin: list(entries)}}), encoding="utf-8"
    )
    return {"CLAUDE_CONFIG_DIR": str(cfg)}


def _e(path, version, scope="project"):
    return {"scope": scope, "projectPath": str(path), "version": version}


def test_여러_폴더_중_현재_폴더_항목의_판을_읽는다(tmp_path):
    """이슈의 재현 상태 — 다른 폴더가 0.10.98 이어도 현재 폴더(public-work)는 0.10.96."""
    env = _write(
        tmp_path,
        _e(tmp_path / "analyze", "0.10.94"),
        _e(tmp_path / "update-project-github", "0.10.98"),
        _e(tmp_path / "public-work", "0.10.96"),
    )
    r = iv.check(str(tmp_path / "public-work"), "0.10.98", env)
    assert (r["state"], r["installed"]) == ("stale", "0.10.96")
    assert r["other_project_entries"] == 2


def test_현재_폴더_항목이_최신이면_current(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.98"))
    assert iv.check(str(tmp_path / "w"), "0.10.98", env)["state"] == "current"
    assert iv.check(str(tmp_path / "w"), "0.10.97", env)["state"] == "current"


def test_현재_폴더_항목이_없으면_다른_폴더가_최신이어도_missing(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "other", "0.10.98"))
    r = iv.check(str(tmp_path / "w"), "0.10.98", env)
    assert r["state"] == "missing" and r["installed"] is None


def test_사용자_범위_항목은_현재_폴더_항목이_아니다(tmp_path):
    env = _write(tmp_path, {"scope": "user", "version": "0.10.98"})
    r = iv.check(str(tmp_path / "w"), "0.10.98", env)
    assert r["state"] == "missing" and r["user_entry"] == "0.10.98"


def test_하위_폴더에서_불러도_상위_projectPath_항목을_찾는다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.96"))
    (tmp_path / "w" / "docs").mkdir(parents=True)
    assert iv.check(str(tmp_path / "w" / "docs"), "0.10.98", env)["installed"] == "0.10.96"


def test_더_가까운_항목이_먼저다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.90"), _e(tmp_path / "w" / "sub", "0.10.95"))
    assert iv.check(str(tmp_path / "w" / "sub"), "0.10.98", env)["installed"] == "0.10.95"


@pytest.mark.parametrize(
    "recorded, cwd",
    [
        ("C:\\Users\\Me\\Work\\Proj", "c:/users/me/work/proj"),
        ("C:\\Users\\Me\\Work\\Proj\\", "C:/Users/Me/Work/Proj"),
        ("C:/Users/Me/Work/Proj", "C:\\USERS\\me\\work\\proj\\."),
    ],
)
def test_Windows_경로는_대소문자와_구분자를_무시하고_비교한다(tmp_path, recorded, cwd):
    env = _write(tmp_path, {"scope": "project", "projectPath": recorded, "version": "0.10.96"})
    assert iv.check(cwd, "0.10.98", env)["installed"] == "0.10.96"


def test_CLAUDE_CONFIG_DIR_을_존중한다(tmp_path, monkeypatch):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.96"))
    assert iv.installed_plugins_path(env) == tmp_path / "cfg" / "plugins" / "installed_plugins.json"
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    assert iv.installed_plugins_path({}) == tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"


def test_파일이_없거나_깨졌으면_unreadable(tmp_path):
    assert iv.check(str(tmp_path), "0.10.98", {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")})["state"] == "unreadable"
    cfg = tmp_path / "cfg" / "plugins"
    cfg.mkdir(parents=True)
    (cfg / "installed_plugins.json").write_text("{not json", encoding="utf-8")
    assert iv.check(str(tmp_path), "0.10.98", {"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})["state"] == "unreadable"


@pytest.mark.parametrize("latest", [None, "", "next"])
def test_최신_판을_모르면_비교하지_않고_unknown(tmp_path, latest):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.96"))
    r = iv.check(str(tmp_path / "w"), latest, env)
    assert (r["state"], r["installed"]) == ("unknown", "0.10.96")


def test_판_문자열이_이상하면_current_로_뭉개지_않는다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "unknown"))
    assert iv.check(str(tmp_path / "w"), "0.10.98", env)["state"] == "unreadable"


def test_판은_숫자로_비교한다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.9"))
    assert iv.check(str(tmp_path / "w"), "0.10.10", env)["state"] == "stale"


def test_CLI_가_JSON_한_줄을_낸다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.96"))
    out = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "installed_version.py"),
         "--cwd", str(tmp_path / "w"), "--latest", "0.10.98"],
        capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, **env}, check=True,
    ).stdout
    data = json.loads(out)
    assert data["state"] == "stale" and data["installed"] == "0.10.96" and data["latest"] == "0.10.98"


def test_스킬이_이_스크립트와_갱신_명령_순서를_가리킨다():
    text = (PLUGIN_ROOT / "skills" / "update" / "SKILL.md").read_text(encoding="utf-8")
    assert "hooks/installed_version.py" in text
    steps = text.split("## 절차", 1)[1]
    order = [steps.index(c) for c in (
        "claude plugin marketplace update blueward-harness",
        "claude plugin update harness@blueward-harness --scope project",
        "claude plugin install harness@blueward-harness --scope project",
    )] + [steps.rindex("/reload-plugins")]
    assert order == sorted(order)
    assert "갱신 확인 불능" in text
    # 스킬이 대신 실행하는 명령에 uninstall 이 없다(사용자 몫으로만 언급)
    assert not re.search(r"^\s*claude plugin uninstall", text, re.MULTILINE)
