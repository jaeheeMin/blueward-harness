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


# --- #461 모든 플러그인 표(--all) ---


def _install(tmp_path, plugins):
    cfg = tmp_path / "cfg"
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8"
    )
    return {"CLAUDE_CONFIG_DIR": str(cfg)}


def _market(tmp_path, market, plugins, versions=None):
    """로컬 marketplace 사본. plugins: [(name, 항목 version 또는 None)], versions: {name: plugin.json version}."""
    root = tmp_path / "cfg" / "plugins" / "marketplaces" / market
    (root / ".claude-plugin").mkdir(parents=True)
    entries = []
    for name, ver in plugins:
        e = {"name": name, "source": f"./plugins/{name}"}
        if ver:
            e["version"] = ver
        entries.append(e)
        if versions and name in versions:
            (root / "plugins" / name / ".claude-plugin").mkdir(parents=True)
            (root / "plugins" / name / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": versions[name]}), encoding="utf-8"
            )
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": entries}), encoding="utf-8")


def _rows(result):
    return {r["plugin"]: r for r in result["rows"]}


def test_all_여러_폴더_설치_중_현재_폴더_판을_고르고_갱신_있음(tmp_path):
    env = _install(tmp_path, {PID: [_e(tmp_path / "a", "0.10.94"), _e(tmp_path / "w", "0.10.96"), _e(tmp_path / "b", "0.10.98")]})
    _market(tmp_path, "blueward-harness", [("harness", None)], {"harness": "0.10.98"})
    r = _rows(iv.all_plugins(str(tmp_path / "w"), env))[PID]
    assert (r["installed"], r["latest"], r["state"], r["scope"]) == ("0.10.96", "0.10.98", "stale", "project")
    assert r["other_project_entries"] == 2


def test_all_user_와_project_가_함께_있으면_project_를_고르고_user_판도_보인다(tmp_path):
    env = _install(tmp_path, {PID: [{"scope": "user", "version": "0.10.90"}, _e(tmp_path / "w", "0.10.98")]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    r = _rows(iv.all_plugins(str(tmp_path / "w"), env))[PID]
    assert (r["scope"], r["installed"], r["user_version"], r["state"]) == ("project", "0.10.98", "0.10.90", "current")
    # 다른 폴더에서는 user 항목이 이 폴더 판이다
    r = _rows(iv.all_plugins(str(tmp_path / "x"), env))[PID]
    assert (r["scope"], r["installed"], r["user_version"]) == ("user", "0.10.90", None)


def test_all_이_폴더에_설치_없음(tmp_path):
    env = _install(tmp_path, {PID: [_e(tmp_path / "other", "0.10.98")]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    r = _rows(iv.all_plugins(str(tmp_path / "w"), env))[PID]
    assert (r["state"], r["installed"], r["scope"]) == ("missing", None, None)


@pytest.mark.parametrize("how", ["none", "broken", "no_entry", "no_version"])
def test_all_marketplace_사본을_못_읽으면_확인_불가이고_최신이_아니다(tmp_path, how):
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.98")]})
    if how == "broken":
        _market(tmp_path, "blueward-harness", [])
        (tmp_path / "cfg" / "plugins" / "marketplaces" / "blueward-harness" / ".claude-plugin" / "marketplace.json").write_text("{x", encoding="utf-8")
    elif how == "no_entry":
        _market(tmp_path, "blueward-harness", [("other", "1.0.0")])
    elif how == "no_version":
        _market(tmp_path, "blueward-harness", [("harness", None)])  # plugin.json 없음
    r = _rows(iv.all_plugins(str(tmp_path / "w"), env))[PID]
    assert (r["state"], r["latest"], r["installed"]) == ("unknown", None, "0.10.98")


def test_all_설치_판_문자열이_이상하면_확인_불가(tmp_path):
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "abc123")]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    assert _rows(iv.all_plugins(str(tmp_path / "w"), env))[PID]["state"] == "unknown"


def test_all_installed_plugins_가_없으면_error(tmp_path):
    r = iv.all_plugins(str(tmp_path), {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")})
    assert r["rows"] == [] and r["error"]
    assert "확인 불능" in iv.render_table(r)


def test_all_remote_판은_harness_만_바꾼다(tmp_path):
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.98")], "x@m": [{"scope": "user", "version": "1.0.0"}]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    _market(tmp_path, "m", [("x", "1.0.0")])
    rows = _rows(iv.all_plugins(str(tmp_path / "w"), env, remote_latest="0.10.120"))
    assert (rows[PID]["latest"], rows[PID]["latest_source"], rows[PID]["state"]) == ("0.10.120", "remote", "stale")
    assert (rows["x@m"]["latest"], rows["x@m"]["latest_source"]) == ("1.0.0", "cache")


def test_all_표와_JSON_출력(tmp_path):
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.96"), _e(tmp_path / "o", "0.10.98")], "x@m": [{"scope": "user", "version": "1.0.0"}]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    _market(tmp_path, "m", [("x", "1.0.0")])
    base = [sys.executable, str(PLUGIN_ROOT / "hooks" / "installed_version.py"), "--cwd", str(tmp_path / "w"), "--all"]
    run = lambda *extra: subprocess.run(  # noqa: E731
        base + list(extra), capture_output=True, text=True, encoding="utf-8",
        env={**__import__("os").environ, **env}, check=True,
    ).stdout
    table = run()
    assert "| 플러그인 | 범위 | 이 폴더 판 | 받아 둔 최신 판 | 상태 | 다른 폴더 설치 |" in table
    assert f"| {PID} | project | 0.10.96 | 0.10.98 | 갱신 있음 | 1곳 |" in table
    assert "| x@m | user | 1.0.0 | 1.0.0 | 최신 | - |" in table
    data = json.loads(run("--json"))
    assert {r["plugin"]: r["state"] for r in data["rows"]} == {PID: "stale", "x@m": "current"}


def test_all_옵션_조합_오류():
    script = str(PLUGIN_ROOT / "hooks" / "installed_version.py")
    for args in (["--json"], ["--all", "--latest", "0.1.0"]):
        assert subprocess.run([sys.executable, script, *args], capture_output=True).returncode == 2


def test_version_스킬이_스크립트와_update_안내를_가리킨다():
    text = (PLUGIN_ROOT / "skills" / "version" / "SKILL.md").read_text(encoding="utf-8")
    assert "hooks/installed_version.py" in text and "--all" in text and "/harness:update" in text
    assert not re.search(r"^\s*claude plugin (install|update|uninstall)", text, re.MULTILINE)
