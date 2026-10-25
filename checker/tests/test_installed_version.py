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


def _mk(tmp_path, *names):
    """projectPath 폴더를 디스크에 만든다(없는 폴더의 항목은 --all 에서 센 값에 안 든다)."""
    for name in names:
        (tmp_path / name).mkdir(parents=True, exist_ok=True)


def test_all_여러_폴더_설치_중_현재_폴더_판을_고르고_갱신_있음(tmp_path):
    _mk(tmp_path, "a", "w", "b")
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
    _mk(tmp_path, "w", "o")
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.96"), _e(tmp_path / "o", "0.10.98")], "x@m": [{"scope": "user", "version": "1.0.0"}]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.98")])
    _market(tmp_path, "m", [("x", "1.0.0")])
    base = [sys.executable, str(PLUGIN_ROOT / "hooks" / "installed_version.py"), "--cwd", str(tmp_path / "w"), "--all"]
    run = lambda *extra: subprocess.run(  # noqa: E731
        base + list(extra), capture_output=True, text=True, encoding="utf-8",
        env={**__import__("os").environ, **env}, check=True,
    ).stdout
    table = run()
    assert "| 플러그인 | 범위 | 이 폴더 판 | 이 세션에 실린 판 | 받아 둔 최신 판 | 상태 | 다른 폴더 설치 |" in table
    assert f"| {PID} | project | 0.10.96 | - | 0.10.98 | 갱신 있음 | 1곳 |" in table
    assert "| x@m | user | 1.0.0 | - | 1.0.0 | 최신 | - |" in table
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


# --- #471 실제로 실린 판 기준 판정 ---


def _loaded(tmp_path, version, name="loaded"):
    """실린 판 폴더(cache/.../<version>)를 흉내 낸다."""
    root = tmp_path / name
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "harness", "version": version}), encoding="utf-8")
    return str(root)


def _run_git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _repo_with_commit(path):
    path.mkdir()
    _run_git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("x\n", encoding="utf-8")
    _run_git(path, "add", ".")
    _run_git(path, "commit", "-q", "-m", "init")


def test_loaded_cwd_항목이_옛_판이어도_실린_판이_최신이면_current(tmp_path):
    """이슈 재현 — 세션이 다른 worktree 항목의 판을 실었다. 거짓 stale 이 나오면 안 된다."""
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.113"), _e(tmp_path / "other", "0.10.115"))
    r = iv.check(str(tmp_path / "w"), "0.10.115", env, loaded_root=_loaded(tmp_path, "0.10.115"))
    assert (r["state"], r["loaded"], r["installed"]) == ("current", "0.10.115", "0.10.113")


def test_loaded_cwd_항목이_최신이어도_실린_판이_낮으면_stale(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.115"))
    r = iv.check(str(tmp_path / "w"), "0.10.115", env, loaded_root=_loaded(tmp_path, "0.10.113"))
    assert (r["state"], r["loaded"], r["installed"]) == ("stale", "0.10.113", "0.10.115")


def test_loaded_이_폴더_항목이_없어도_실린_판으로_판정한다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "other", "0.10.90"))
    r = iv.check(str(tmp_path / "w"), "0.10.115", env, loaded_root=_loaded(tmp_path, "0.10.115"))
    assert r["state"] == "current" and r["installed"] is None


def test_loaded_installed_plugins_가_없어도_실린_판으로_판정한다(tmp_path):
    r = iv.check(str(tmp_path), "0.10.115", {"CLAUDE_CONFIG_DIR": str(tmp_path / "none")}, loaded_root=_loaded(tmp_path, "0.10.114"))
    assert (r["state"], r["loaded"]) == ("stale", "0.10.114")


def test_loaded_최신_판을_모르면_unknown(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.115"))
    r = iv.check(str(tmp_path / "w"), None, env, loaded_root=_loaded(tmp_path, "0.10.115"))
    assert (r["state"], r["loaded"]) == ("unknown", "0.10.115")


@pytest.mark.parametrize("how", ["no_dir", "no_file", "broken", "no_version", "bad_version"])
def test_loaded_plugin_json_을_못_읽으면_unreadable_이고_사유가_있다(tmp_path, how):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.115"))
    root = tmp_path / "loaded"
    if how != "no_dir":
        (root / ".claude-plugin").mkdir(parents=True)
    pj = root / ".claude-plugin" / "plugin.json"
    if how == "broken":
        pj.write_text("{x", encoding="utf-8")
    elif how == "no_version":
        pj.write_text("{}", encoding="utf-8")
    elif how == "bad_version":
        pj.write_text('{"version": "next"}', encoding="utf-8")
    r = iv.check(str(tmp_path / "w"), "0.10.115", env, loaded_root=str(root))
    assert r["state"] == "unreadable" and r["loaded"] is None and r["loaded_error"]


def test_loaded_없는_호출은_옛_동작을_그대로_한다(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.113"))
    r = iv.check(str(tmp_path / "w"), "0.10.115", env)
    assert r["state"] == "stale" and "loaded" not in r and "same_repo_entries" not in r


def test_loaded_같은_저장소의_다른_worktree_항목을_참고로_낸다(tmp_path):
    main = tmp_path / "main"
    _repo_with_commit(main)
    _run_git(main, "worktree", "add", "-q", str(tmp_path / "work2"), "-b", "b2")
    _run_git(main, "worktree", "add", "-q", str(tmp_path / "work3"), "-b", "b3")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _run_git(unrelated, "init", "-q")
    env = _write(
        tmp_path,
        _e(tmp_path / "work2", "0.10.113"), _e(tmp_path / "work3", "0.10.115"),
        _e(unrelated, "0.10.100"), _e(tmp_path / "gone", "0.10.99"),
    )
    r = iv.check(str(tmp_path / "work2"), "0.10.115", env, loaded_root=_loaded(tmp_path, "0.10.115"))
    assert r["same_repo_entries"] == [{"folder": "work3", "version": "0.10.115"}]
    assert str(tmp_path).lower() not in json.dumps(r["same_repo_entries"]).lower()  # 끝 폴더 이름만


def test_CLI_loaded_root(tmp_path):
    env = _write(tmp_path, _e(tmp_path / "w", "0.10.113"))
    out = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "installed_version.py"), "--cwd", str(tmp_path / "w"),
         "--latest", "0.10.115", "--loaded-root", _loaded(tmp_path, "0.10.115")],
        capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, **env}, check=True,
    ).stdout
    data = json.loads(out)
    assert data["state"] == "current" and data["loaded"] == "0.10.115" and data["installed"] == "0.10.113"


def test_all_이_폴더에서_안_쓰는_플러그인_줄은_기본으로_빼고_harness_는_남긴다(tmp_path):
    _mk(tmp_path, "w", "o")
    env = _install(tmp_path, {
        PID: [_e(tmp_path / "other-gone", "0.10.98")],            # 이 폴더 항목 없음 + 다른 폴더는 디스크에 없음
        "used@m": [{"scope": "user", "version": "1.0.0"}],         # user 항목 → 남김
        "here@m": [_e(tmp_path / "w", "1.0.0")],                  # 이 폴더 항목 → 남김
        "elsewhere@m": [_e(tmp_path / "o", "1.0.0")],             # 다른 폴더에만 있음(같은 저장소 아님) → 뺌
        "ghost@m": [_e(tmp_path / "gone", "1.0.0")],              # 디스크에 없는 폴더에만 → 뺌
    })
    r = iv.all_plugins(str(tmp_path / "w"), env)
    rows = _rows(r)
    assert set(rows) == {PID, "used@m", "here@m"}
    assert rows[PID]["state"] == "missing" and rows[PID]["other_project_entries"] == 0
    assert r["hidden"] == 2 and "2개는 뺐다" in iv.render_table(r) and "--all-entries" in iv.render_table(r)
    full = iv.all_plugins(str(tmp_path / "w"), env, all_entries=True)
    assert set(_rows(full)) == {PID, "used@m", "here@m", "elsewhere@m", "ghost@m"} and full["hidden"] == 0
    assert _rows(full)["elsewhere@m"]["other_project_entries"] == 1
    assert _rows(full)["ghost@m"]["other_project_entries"] == 0  # 디스크에 없는 폴더는 세지 않는다


def test_all_같은_저장소_worktree_에만_설치된_플러그인은_남긴다(tmp_path):
    main = tmp_path / "main"
    _repo_with_commit(main)
    _run_git(main, "worktree", "add", "-q", str(tmp_path / "work2"), "-b", "b2")
    env = _install(tmp_path, {"sib@m": [_e(main, "1.0.0")], PID: [_e(main, "0.10.115")]})
    r = iv.all_plugins(str(tmp_path / "work2"), env)
    rows = _rows(r)
    assert set(rows) == {"sib@m", PID}
    assert rows["sib@m"]["same_repo_entries"] == [{"folder": "main", "version": "1.0.0"}]
    assert "같은 저장소: main 1.0.0" in iv.render_table(r)


def test_all_harness_상태는_실린_판으로_정한다(tmp_path):
    _mk(tmp_path, "w")
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.113")]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.115")])
    r = iv.all_plugins(str(tmp_path / "w"), env, loaded_root=_loaded(tmp_path, "0.10.115"))
    row = _rows(r)[PID]
    assert (row["installed"], row["loaded"], row["state"]) == ("0.10.113", "0.10.115", "current")
    assert f"| {PID} | project | 0.10.113 | 0.10.115 | 0.10.115 | 최신 |" in iv.render_table(r)
    # 실린 판이 낮으면 설치 항목이 최신이어도 갱신 있음
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.115")]})
    r = iv.all_plugins(str(tmp_path / "w"), env, loaded_root=_loaded(tmp_path, "0.10.113", "old"))
    assert _rows(r)[PID]["state"] == "stale"


def test_all_실린_판을_못_읽으면_harness_는_확인_불가이고_사유가_표에_나온다(tmp_path):
    _mk(tmp_path, "w")
    env = _install(tmp_path, {PID: [_e(tmp_path / "w", "0.10.115")]})
    _market(tmp_path, "blueward-harness", [("harness", "0.10.115")])
    r = iv.all_plugins(str(tmp_path / "w"), env, loaded_root=str(tmp_path / "nowhere"))
    assert _rows(r)[PID]["state"] == "unknown" and r["loaded_error"]
    assert "실린 판을 읽지 못했다" in iv.render_table(r)


def test_all_entries_는_all_없이_쓰면_오류():
    script = str(PLUGIN_ROOT / "hooks" / "installed_version.py")
    assert subprocess.run([sys.executable, script, "--all-entries"], capture_output=True).returncode == 2


def test_update_스킬이_실린_판으로_확인하고_uninstall_을_안내하지_않는다():
    text = (PLUGIN_ROOT / "skills" / "update" / "SKILL.md").read_text(encoding="utf-8")
    assert '--loaded-root "${CLAUDE_PLUGIN_ROOT}"' in text
    assert "/reload-plugins" in text and "갱신 확인 불능" in text
    assert "claude plugin uninstall" not in text
    assert "enabledPlugins" in text  # 하지 않는 이유


def test_version_스킬이_실린_판과_all_entries_를_안내한다():
    text = (PLUGIN_ROOT / "skills" / "version" / "SKILL.md").read_text(encoding="utf-8")
    assert '--loaded-root "${CLAUDE_PLUGIN_ROOT}"' in text and "--all-entries" in text
