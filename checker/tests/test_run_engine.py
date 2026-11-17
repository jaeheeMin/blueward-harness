"""#1043 — hooks/run_engine.py: 스킬이 엔진을 한 줄로 부르는 래퍼.

가짜 uvx 로 인자 전달·종료 코드·출력 통과, 엔진 판을 못 정할 때의 확인 불능(종료 2), 허용 목록 밖 모듈 거절,
`--timeout` 을 본다. Windows 와 macOS·Linux 모두에서 돈다(가짜 uvx 는 .cmd 또는 sh).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "plugins" / "harness" / "hooks"
SAFE_TOOLS = ROOT / "plugins" / "harness" / "console" / "safe_tools.json"

FAKE = """\
import json, os, sys, time
with open(os.environ["FAKE_OUT"], "w", encoding="utf-8") as f:
    json.dump(sys.argv[1:], f, ensure_ascii=False)
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
sys.stdout.write("엔진 출력\\n")
sys.stderr.write("엔진 오류\\n")
sys.exit(int(os.environ.get("FAKE_EXIT", "0")))
"""


def _fake_uvx(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "fake_uvx.py"
    script.write_text(FAKE, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "uvx.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = bin_dir / "uvx"
        launcher.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{script}' \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o755)


def _run(tmp_path: Path, args: list[str], *, engine: str | None = "git+https://example.test/engine@v9.9.9", path_dirs=None, hook: Path = HOOKS / "run_engine.py", **env):
    bin_dir = tmp_path / "bin"
    if path_dirs is None:
        _fake_uvx(bin_dir)
        path_dirs = [bin_dir]
    base = {k: v for k, v in os.environ.items() if k not in ("DOC_GUARD_ENGINE", "PATH", "PATHEXT")}
    if os.name == "nt":  # 가짜 .cmd 를 실행하려면 cmd.exe 와 PATHEXT 가 있어야 한다
        base["PATHEXT"] = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        base["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        path_dirs = [*path_dirs, os.path.join(base["SYSTEMROOT"], "System32")]
    base["PATH"] = os.pathsep.join(str(p) for p in path_dirs)
    base["FAKE_OUT"] = str(tmp_path / "argv.json")
    base["PYTHONIOENCODING"] = "utf-8"
    if engine is not None:
        base["DOC_GUARD_ENGINE"] = engine
    base.update(env)
    return subprocess.run([sys.executable, str(hook), *args], capture_output=True, text=True, encoding="utf-8", env=base, cwd=str(tmp_path), timeout=60)


def _argv(tmp_path: Path) -> list[str]:
    return json.loads((tmp_path / "argv.json").read_text(encoding="utf-8"))


def test_passes_module_args_exit_code_and_output_through(tmp_path):
    r = _run(tmp_path, ["pr_queue", "--all", "--json"], FAKE_EXIT="1")
    assert r.returncode == 1
    assert "엔진 출력" in r.stdout and "엔진 오류" in r.stderr
    assert _argv(tmp_path) == ["--from", "git+https://example.test/engine@v9.9.9", "python", "-P", "-m", "checker.pr_queue", "--all", "--json"]


def test_paths_with_spaces_hangul_and_backslashes_go_as_list_args_without_a_shell(tmp_path, monkeypatch):
    # 가짜 .cmd 는 cmd.exe 가 인자를 다시 해석하므로, 인자 그대로 전달은 subprocess 호출을 가로채 본다(셸 없이 리스트 인자)
    sys.path.insert(0, str(HOOKS))
    try:
        import run_engine
    finally:
        sys.path.remove(str(HOOKS))
    spec = str(tmp_path / "엔진 폴더 한글" / "체크아웃")
    weird = ["--root", r"C:\work dir\한글 폴더", "--spec", "docs/개발 사양서 v0.1.md", 'a"b', "$HOME", "x;y", "&&"]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 7)

    monkeypatch.setenv("DOC_GUARD_ENGINE", spec)
    monkeypatch.setattr(run_engine.shutil, "which", lambda name: r"C:\Tools\uv bin\uvx.exe")
    monkeypatch.setattr(run_engine.subprocess, "run", fake_run)
    assert run_engine.main(["export", *weird]) == 7
    cmd, kwargs = calls[0]
    assert cmd == [r"C:\Tools\uv bin\uvx.exe", "--from", spec, "python", "-P", "-m", "checker.export", *weird]
    assert not kwargs.get("shell") and kwargs.get("timeout") is None


def test_unknown_module_is_refused_without_calling_uvx(tmp_path):
    for bad in (["evil"], ["pr_queue.x"], ["../pr_queue"], [], ["--timeout", "5"]):
        (tmp_path / "argv.json").unlink(missing_ok=True)
        r = _run(tmp_path, bad)
        assert r.returncode == 2 and r.stderr.startswith("확인 불능"), (bad, r.stderr)
        assert not (tmp_path / "argv.json").exists(), bad


def test_engine_version_unknown_is_cannot_check_not_pass_or_main(tmp_path):
    # plugin.json 이 없는 자리에 두 파일만 복사 → engine_spec 이 실패하고, 래퍼는 uvx 로 넘어가지 않는다(원칙 7)
    hooks = tmp_path / "plugin" / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run_engine.py", "engine_spec.py"):
        shutil.copy(HOOKS / name, hooks / name)
    r = _run(tmp_path, ["pr_queue", "--mine"], engine=None, hook=hooks / "run_engine.py")
    assert r.returncode == 2
    assert r.stderr.startswith("확인 불능") and "엔진 판을 정하지 못했다" in r.stderr and "version" in r.stderr
    assert r.stdout == "" and not (tmp_path / "argv.json").exists()


def test_without_uvx_it_is_cannot_check(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(tmp_path, ["pr_queue"], path_dirs=[empty])
    if os.name == "nt":  # System32 에 uvx 가 있을 리 없다
        assert r.returncode == 2 and "uvx" in r.stderr
    else:
        assert r.returncode == 2 and r.stderr.startswith("확인 불능") and "uvx" in r.stderr


def test_timeout_flag_ends_with_124_and_a_reason(tmp_path):
    r = _run(tmp_path, ["--timeout", "1", "pr_queue", "--mine"], FAKE_SLEEP="30")
    assert r.returncode == 124 and "확인 불능" in r.stderr and "1초" in r.stderr
    ok = _run(tmp_path, ["--timeout", "30", "pr_queue", "--mine"])
    assert ok.returncode == 0 and _argv(tmp_path)[-2:] == ["checker.pr_queue", "--mine"]
    for bad in (["--timeout", "0", "pr_queue"], ["--timeout", "x", "pr_queue"], ["--timeout", "9999", "pr_queue"]):
        assert _run(tmp_path, bad).returncode == 2, bad


def test_module_allow_list_covers_every_engine_module_the_console_calls_read_only():
    sys.path.insert(0, str(HOOKS))
    try:
        import run_engine
    finally:
        sys.path.remove(str(HOOKS))
    reads = set(json.loads(SAFE_TOOLS.read_text(encoding="utf-8"))["harness_modules"])
    assert reads <= run_engine.MODULES, reads - run_engine.MODULES
    assert (ROOT / "checker").is_dir() and all((ROOT / "checker" / f"{m}.py").exists() or (ROOT / "checker" / m).is_dir() for m in run_engine.MODULES)


def test_skills_call_only_listed_modules_through_the_wrapper():
    import re

    sys.path.insert(0, str(HOOKS))
    try:
        import run_engine
    finally:
        sys.path.remove(str(HOOKS))
    seen = set()
    for md in (ROOT / "plugins" / "harness" / "skills").rglob("SKILL.md"):
        for m in re.finditer(r'hooks/run_engine\.py"? (?:--timeout \d+ )?([A-Za-z_][A-Za-z0-9_]*)', md.read_text(encoding="utf-8")):
            seen.add(m.group(1))
    assert seen and seen <= run_engine.MODULES, seen - run_engine.MODULES
