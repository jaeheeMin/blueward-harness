"""#314 — 세션 중간 옛 판 안내 훅(update_notice.py) 테스트.

원격 조회(`git ls-remote`)는 함수로 주입해 가짜로 바꾼다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import PLUGIN_ROOT

_spec = importlib.util.spec_from_file_location("update_notice", PLUGIN_ROOT / "hooks" / "update_notice.py")
un = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(un)
_ua = importlib.util.spec_from_file_location("user_action", PLUGIN_ROOT / "hooks" / "user_action.py")
_ua_mod = importlib.util.module_from_spec(_ua)
_ua.loader.exec_module(_ua_mod)
USER_ACTION = _ua_mod.USER_ACTION


def _tags(*versions: str) -> str:
    lines = []
    for i, v in enumerate(versions):
        lines.append(f"{i:040x}\trefs/tags/v{v}")
        lines.append(f"{i + 100:040x}\trefs/tags/v{v}^{{}}")
    return "\n".join(lines) + "\n"


class Remote:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


@pytest.fixture
def env(tmp_path):
    """캐시 폴더 구조(.../harness/<version>)를 흉내 낸 플러그인 루트와 데이터 폴더."""
    root = tmp_path / "cache" / "mkt" / "harness" / "0.10.60"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": "0.10.60"}), encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    return {
        "env": {"CLAUDE_PLUGIN_ROOT": str(root), "CLAUDE_PLUGIN_DATA": str(tmp_path / "data")},
        "root": root,
        "payload": {"session_id": "s1", "cwd": str(cwd)},
        "now": [1000.0],
    }


def _go(e, remote, payload=None, env_extra=None):
    return un.run(payload or e["payload"], {**e["env"], **(env_extra or {})}, ls_remote=remote, now=lambda: e["now"][0])


def _context(out) -> str:
    data = json.loads(out)["hookSpecificOutput"]
    assert data["hookEventName"] == "UserPromptSubmit"
    return data["additionalContext"]


def test_뒤처졌고_새_판을_안_받았으면_업데이트_명령을_안내한다(env):
    out = _go(env, Remote(_tags("0.10.59", "0.10.61", "0.10.9")))
    ctx = _context(out)
    assert "0.10.61" in ctx and "0.10.60" in ctx
    assert "claude plugin update harness@blueward-harness --scope project" in ctx
    assert "/reload-plugins" in ctx


def test_사용자_화면용_systemMessage_가_표시로_시작하고_additionalContext_도_유지된다(env):
    """#505 — 사람이 해야 하는 갱신 안내는 화면에 바로 뜨고, Claude 용 안내도 그대로다."""
    data = json.loads(_go(env, Remote(_tags("0.10.61"))))
    msg = data["systemMessage"]
    assert msg.startswith(USER_ACTION) and USER_ACTION == "🚨 직접 해 주세요:"
    assert "0.10.61" in msg and "/harness:update" in msg and "/reload-plugins" in msg
    assert "\n" not in msg
    assert "새 판 0.10.61" in data["hookSpecificOutput"]["additionalContext"]


def test_이미_새_판이_설치된_폴더의_systemMessage_는_reload_만_안내한다(env, tmp_path):
    (env["root"].parent / "0.10.61").mkdir()
    _installed(env, tmp_path, _entry(env["payload"]["cwd"], "0.10.61"))
    msg = json.loads(_go(env, Remote(_tags("0.10.61"))))["systemMessage"]
    assert msg.startswith(USER_ACTION) and "/reload-plugins" in msg and "/harness:update" not in msg


def test_같은_세션에서_같은_판은_systemMessage_도_한_번만(env):
    assert _go(env, Remote(_tags("0.10.61"))) is not None
    assert _go(env, Remote(_tags("0.10.61"))) is None


def _installed(e, tmp_path, *entries):
    """CLAUDE_CONFIG_DIR 아래에 installed_plugins.json 을 쓰고 env 에 건다."""
    cfg = tmp_path / "cfg"
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {"harness@blueward-harness": list(entries)}}), encoding="utf-8"
    )
    e["env"]["CLAUDE_CONFIG_DIR"] = str(cfg)


def _entry(path, version, scope="project"):
    return {"scope": scope, "projectPath": str(path), "version": version}


def test_뒤처졌고_이_폴더_설치가_이미_새_판이면_reload_만_안내한다(env, tmp_path):
    (env["root"].parent / "0.10.61").mkdir()
    _installed(env, tmp_path, _entry(env["payload"]["cwd"], "0.10.61"))
    ctx = _context(_go(env, Remote(_tags("0.10.61"))))
    assert "/reload-plugins" in ctx
    assert "뒤에도 판이 그대로면" in ctx


def test_새_판_폴더가_있어도_이_폴더_설치가_옛_판이면_업데이트를_안내한다(env, tmp_path):
    """#404 — 다른 폴더의 project 설치가 새 판을 캐시에 받아 둔 경우. 폴더가 있다는 것만으로
    이 폴더에 reload 가 새 판을 싣는다고 말하면 틀린다."""
    (env["root"].parent / "0.10.61").mkdir()
    _installed(
        env, tmp_path,
        _entry(env["payload"]["cwd"], "0.10.60"),
        _entry(tmp_path / "other", "0.10.61"),
    )
    ctx = _context(_go(env, Remote(_tags("0.10.61"))))
    assert "/harness:update" in ctx
    assert "이미 새 판" not in ctx
    assert "claude plugin update harness@blueward-harness --scope project" in ctx


def test_이_폴더_설치_항목이_없으면_업데이트를_안내한다(env, tmp_path):
    (env["root"].parent / "0.10.61").mkdir()
    _installed(env, tmp_path, _entry(tmp_path / "other", "0.10.61"))
    assert "이미 새 판" not in _context(_go(env, Remote(_tags("0.10.61"))))


def test_갱신_안내에_harness_update_가_들어_있다(env):
    assert "/harness:update" in _context(_go(env, Remote(_tags("0.10.61"))))


def test_최신이면_말하지_않는다(env):
    assert _go(env, Remote(_tags("0.10.60"))) is None


def test_앞서_있으면_말하지_않는다(env):
    assert _go(env, Remote(_tags("0.10.50", "0.10.59"))) is None


@pytest.mark.parametrize("output", [None, "", "garbage\n", "x\trefs/tags/vnext\n"])
def test_원격을_못_읽으면_조용히_넘어간다(env, output):
    assert _go(env, Remote(output)) is None


def test_ls_remote_가_시간초과이면_None(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(un.subprocess, "Popen", boom)
    assert un.ls_remote_tags() is None


def test_응답_없는_서버에서_자식_프로세스가_걸려도_상한_안에_끝난다():
    """연결만 받고 응답하지 않는 로컬 서버에 진짜 git 을 붙인다."""
    import socket
    import threading
    import time

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    conns = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conns.append(srv.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        started = time.monotonic()
        out = un.ls_remote_tags(f"http://127.0.0.1:{srv.getsockname()[1]}/x.git", timeout=2)
        elapsed = time.monotonic() - started
    finally:
        stop.set()
        t.join(2)
        for c in conns:
            c.close()
        srv.close()
    assert out is None
    assert elapsed < 8


def test_조회_전에_checked_at_을_먼저_저장한다(env):
    seen = {}

    def remote():
        seen["state"] = json.loads((Path(env["env"]["CLAUDE_PLUGIN_DATA"]) / "update-notice.json").read_text(encoding="utf-8"))
        return None

    _go(env, remote)
    assert seen["state"]["checked_at"] == 1000.0


def test_캐시_10분_안에는_원격을_다시_묻지_않는다(env):
    remote = Remote(_tags("0.10.61"))
    _go(env, remote)
    env["now"][0] += 599
    _go(env, remote, {**env["payload"], "session_id": "s2"})
    assert remote.calls == 1
    env["now"][0] += 2
    _go(env, remote, {**env["payload"], "session_id": "s3"})
    assert remote.calls == 2


def test_실패도_캐시해서_바로_다시_묻지_않는다(env):
    remote = Remote(None)
    _go(env, remote)
    _go(env, remote)
    assert remote.calls == 1


def test_같은_세션_같은_판은_두_번째_알림이_없다(env):
    remote = Remote(_tags("0.10.61"))
    assert _go(env, remote) is not None
    assert _go(env, remote) is None


def test_다른_세션은_다시_알린다(env):
    remote = Remote(_tags("0.10.61"))
    assert _go(env, remote) is not None
    assert _go(env, remote, {**env["payload"], "session_id": "other"}) is not None


def test_같은_세션에서_더_새_판이_나오면_다시_알린다(env):
    assert _go(env, Remote(_tags("0.10.61"))) is not None
    env["now"][0] += 700
    ctx = _context(_go(env, Remote(_tags("0.10.61", "0.10.62"))))
    assert "0.10.62" in ctx


def test_플러그인_저장소에서는_꺼진다(env, tmp_path):
    repo = tmp_path / "plugin-repo"
    (repo / ".claude-plugin").mkdir(parents=True)
    (repo / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    (repo / ".git").mkdir()
    sub = repo / "plugins" / "harness"
    sub.mkdir(parents=True)
    remote = Remote(_tags("0.10.61"))
    assert _go(env, remote, {**env["payload"], "cwd": str(sub)}) is None
    assert remote.calls == 0


def test_환경변수로_끈다(env):
    remote = Remote(_tags("0.10.61"))
    assert _go(env, remote, env_extra={"HARNESS_NO_UPDATE_NOTICE": "1"}) is None
    assert remote.calls == 0


def test_plugin_json_을_못_읽으면_조용히_넘어간다(env):
    (env["root"] / ".claude-plugin" / "plugin.json").write_text("not json", encoding="utf-8")
    assert _go(env, Remote(_tags("0.10.61"))) is None


def test_세션_id_가_없으면_알리지_않는다(env):
    assert _go(env, Remote(_tags("0.10.61")), {"cwd": env["payload"]["cwd"]}) is None


def test_git_이_없어도_스크립트는_exit_0_에_출력_없음이다(env, tmp_path):
    """진짜 프로세스로: PATH 에 git 이 없으면 원격을 못 읽어도 조용히 끝난다."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    done = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "update_notice.py")],
        input=json.dumps(env["payload"]), capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, **env["env"], "PATH": str(empty)},
        timeout=30,
    )
    assert done.returncode == 0
    assert done.stdout == ""


def test_hooks_json_에_UserPromptSubmit_으로_등록돼_있다():
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    commands = [h.get("command", "") for e in hooks["UserPromptSubmit"] for h in e["hooks"]]
    assert any("update_notice.py" in c for c in commands)
