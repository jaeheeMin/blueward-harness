"""#1039: 상태줄 감싸개(statusline_wrap.py)와 설정 "한도 표시" 켜기·끄기, 헤더 한도 합치기 시험.

Windows(windows-latest)에서도 그대로 돈다 — 경로 공백·한글, 따옴표 섞인 원래 명령, CRLF·ANSI·한글 출력의 바이트 보존을
실제 셸(Windows 는 Git Bash, 그 밖은 /bin/sh)로 확인한다. 이 PC 의 실제 settings.json 은 건드리지 않는다(모두 임시 폴더).
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
CONSOLE = ROOT / "plugins" / "harness" / "console"
sys.path.insert(0, str(CONSOLE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import limits_setup  # noqa: E402
import statusline_wrap  # noqa: E402
import store as store_mod  # noqa: E402

PAYLOAD = {"model": {"display_name": "한글 모델"}, "cwd": "C:\\사용자\\이름 공백",
           "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": 4102444800},
                           "seven_day": {"used_percentage": 7.5, "resets_at": 4102444900}}}
# 한글·ANSI 색·CRLF 와 LF 섞인 여러 줄, 끝 줄바꿈 없음, 잘못된 UTF-8 바이트 하나
ORIGINAL_OUT = "한글 상태줄 ✓ \x1b[32m초록\x1b[0m\r\n둘째 줄\n\x1b]8;;https://x.y\x1b\\링크\x1b]8;;\x1b\\".encode("utf-8") + b"\xff\xfe"
EMIT = """import sys
data = sys.stdin.buffer.read()
sys.stdout.buffer.write(sys.argv[1].encode('utf-8') if False else open(sys.argv[0] + '.out', 'rb').read())
sys.stderr.buffer.write('원래 명령의 stderr\\n'.encode('utf-8'))  # 시험용 명령도 바이트로 쓴다(Windows 기본 인코딩 영향 없이)
sys.exit(int(open(sys.argv[0] + '.rc').read()))
"""


def fwd(p) -> str:
    return Path(p).as_posix()


def make_state(tmp_path, original_cmd="USE_EMIT"):
    """공백·한글이 든 상태 폴더에 감싸개를 복사하고, 원래 상태줄 기록을 둔다."""
    state = tmp_path / "상태 폴더 with space" / "harness-console"
    state.mkdir(parents=True)
    shutil.copyfile(CONSOLE / "statusline_wrap.py", state / "statusline_wrap.py")
    emit = tmp_path / "원래 명령" / "emit.py"
    emit.parent.mkdir()
    emit.write_text(EMIT, encoding="utf-8")
    (tmp_path / "원래 명령" / "emit.py.out").write_bytes(ORIGINAL_OUT)
    (tmp_path / "원래 명령" / "emit.py.rc").write_text("3")
    if original_cmd == "USE_EMIT":
        original_cmd = f'"{fwd(sys.executable)}" "{fwd(emit)}"'
    if original_cmd is not None:
        (state / "statusline_orig.json").write_text(
            json.dumps({"present": True, "value": {"type": "command", "command": original_cmd, "padding": 1}}, ensure_ascii=False), encoding="utf-8")
    else:
        (state / "statusline_orig.json").write_text(json.dumps({"present": False, "value": None}), encoding="utf-8")
    return state


def run_wrapper(state, stdin: bytes):
    # PYTHONIOENCODING=cp1252: Windows 기본 인코딩을 어디서나 흉내 낸다. 감싸개가 stderr 를 텍스트로 쓰면 한글이 \uXXXX 로 깨진다
    env = dict(os.environ, PYTHONIOENCODING="cp1252:backslashreplace")
    env.pop("PYTHONUTF8", None)
    return subprocess.run([sys.executable, str(state / "statusline_wrap.py")], input=stdin, capture_output=True, timeout=60, env=env)


STDIN = json.dumps(PAYLOAD, ensure_ascii=False).encode("utf-8")


def test_wrapper_passes_original_output_byte_for_byte_and_exit_code(tmp_path):
    state = make_state(tmp_path)
    r = run_wrapper(state, STDIN)
    assert r.stdout == ORIGINAL_OUT  # 한글·ANSI·OSC 8·CRLF·잘못된 바이트까지 그대로, 줄바꿈 변환 없음
    assert r.returncode == 3  # 원래 명령의 종료 코드
    assert "원래 명령의 stderr".encode("utf-8") in r.stderr  # 원래 명령의 stderr 도 막지 않는다
    rec = json.loads((state / "statusline_limits.json").read_text(encoding="utf-8"))
    assert rec["rate_limits"] == {"five_hour": {"used_percentage": 42, "resets_at": 4102444800},
                                  "seven_day": {"used_percentage": 7.5, "resets_at": 4102444900}}
    assert isinstance(rec["t"], float) and set(rec) == {"t", "rate_limits"}  # rate_limits 외의 입력(cwd·모델)은 남기지 않는다
    assert not list(state.glob("*.tmp"))


def test_wrapper_without_original_prints_nothing_but_records(tmp_path):
    for orig in (None, "no-record"):
        state = make_state(tmp_path / str(orig), None)
        if orig == "no-record":
            (state / "statusline_orig.json").unlink()
        r = run_wrapper(state, STDIN)
        assert r.stdout == b"" and r.returncode == 0
        assert json.loads((state / "statusline_limits.json").read_text(encoding="utf-8"))["rate_limits"]["five_hour"]["used_percentage"] == 42


def test_wrapper_keeps_output_when_recording_fails(tmp_path):
    state = make_state(tmp_path)
    (state / "statusline_limits.json").mkdir()  # 파일 자리를 폴더로 막아 기록을 실패시킨다
    r = run_wrapper(state, STDIN)
    assert r.stdout == ORIGINAL_OUT and r.returncode == 3  # 상태줄은 그대로
    err = r.stderr.decode("utf-8", "replace")
    assert "harness-statusline: 한도를 기록하지 못했어" in err and err.count("harness-statusline") == 1  # stderr 한 줄, stdout 에는 안 섞인다
    assert not list(state.glob("*.tmp"))


def test_wrapper_ignores_inputs_without_rate_limits(tmp_path):
    state = make_state(tmp_path)
    for raw in (b"", b"not json \xff", b'{"model":{}}', b'{"rate_limits":"x"}', b'{"rate_limits":{"five_hour":{"used_percentage":"9"}}}', b"[1]"):
        r = run_wrapper(state, raw)
        assert r.stdout == ORIGINAL_OUT, raw  # 어떤 입력이든 원래 명령은 같은 입력으로 돌고 출력은 그대로
        assert not (state / "statusline_limits.json").exists(), raw


def test_wrapper_runs_original_string_through_shell_without_requoting(tmp_path):
    """settings.json 의 원래 command 문자열을 그대로 셸에 넘긴다: 큰따옴표·작은따옴표·공백·한글이 섞인 문자열."""
    expected = "한글 \"q\" 'a b' 끝"
    state = make_state(tmp_path, "printf '%s' \"한글 \\\"q\\\" 'a b' 끝\"")
    r = run_wrapper(state, STDIN)
    assert r.stdout == expected.encode("utf-8") and r.returncode == 0
    # 이 PC 의 claude-hud 처럼 bash -c '...' 안에 따옴표가 중첩된 문자열
    state2 = make_state(tmp_path / "b", "bash -c 'printf \"%s|%s\" \"a b\" '\"'\"'c d'\"'\"")
    assert run_wrapper(state2, STDIN).stdout == b"a b|c d"


def test_generated_command_runs_in_shell_with_spaces_and_korean_path(tmp_path):
    """settings.json 에 들어갈 실제 명령 문자열(uv run --no-project python "<경로>")을 Claude Code 와 같은 셸로 돌린다."""
    assert shutil.which("uv"), "uv 가 있어야 하네스 훅과 같은 방식으로 시험할 수 있다"
    state = make_state(tmp_path)
    cmd = limits_setup.wrapper_command(state)
    assert cmd.startswith('uv run --no-project python "') and "\\" not in cmd  # 역슬래시 없는 슬래시 경로(Git Bash 가 역슬래시를 먹는다)
    r = subprocess.run(statusline_wrap.shell_argv(cmd), input=STDIN, capture_output=True, timeout=120, cwd=tmp_path)
    assert r.stdout == ORIGINAL_OUT and r.returncode == 3, r.stderr
    assert json.loads((state / "statusline_limits.json").read_text(encoding="utf-8"))["rate_limits"]["seven_day"]["used_percentage"] == 7.5


def test_shell_argv_follows_claude_code_windows_rule(tmp_path):
    """Windows: Git Bash 가 있으면 bash -c, 없으면 PowerShell(공식 문서). WSL 의 System32\\bash.exe 는 고르지 않는다."""
    wsl = r"C:\Windows\System32\bash.exe"
    which = lambda n: {"git": r"C:\Program Files\Git\cmd\git.exe", "bash": wsl, "powershell": r"C:\ps\powershell.exe"}.get(n)  # noqa: E731
    gb = str(Path(r"C:\Program Files\Git\cmd\git.exe").resolve().parent.parent / "bin" / "bash.exe")
    assert statusline_wrap.git_bash({}, which, lambda p: p == gb) == gb
    assert statusline_wrap.git_bash({"CLAUDE_CODE_GIT_BASH_PATH": r"D:\g\bash.exe"}, which, lambda p: p == r"D:\g\bash.exe") == r"D:\g\bash.exe"
    assert statusline_wrap.git_bash({}, which, lambda p: p == wsl) is None
    assert statusline_wrap.shell_argv("echo hi", "posix") == ["/bin/sh", "-c", "echo hi"]
    cmd = "bash -c 'x \"y\"'"
    nt = statusline_wrap.shell_argv(cmd, "nt", {"CLAUDE_CODE_GIT_BASH_PATH": sys.executable})
    assert nt == [sys.executable, "-c", cmd]  # 원래 문자열은 한 인자로 그대로
    ps = statusline_wrap.shell_argv(cmd, "nt", {"PATH": ""})
    assert ps[1:] == ["-NoProfile", "-Command", cmd] or ps[0].lower().endswith("bash.exe")  # Git Bash 가 없으면 PowerShell


# ---- settings.json 켜기·끄기 ----

def cfg_env(tmp_path):
    cfg = tmp_path / "설정 폴더 cfg"
    cfg.mkdir()
    return cfg, {"CLAUDE_CONFIG_DIR": str(cfg)}


ORIG_TEXT = ('{\n  "model": "opus",\n  "z_first": {"b": 1, "a": [3, 2, 1]},\n  "env": {"한글": "값", "A": "1"},\n'
             '  "statusLine": {\n    "type": "command",\n    "command": "bash -c \'echo \\"a b\\"\'",\n    "padding": 2\n  },\n  "hooks": {}\n}\n')
ABSENT_TEXT = '{\n  "model": "opus",\n  "z_first": {"b": 1, "a": [3, 2, 1]},\n  "env": {"한글": "값", "A": "1"},\n  "hooks": {}\n}\n'


@pytest.mark.parametrize("text", [ORIG_TEXT, ABSENT_TEXT, ORIG_TEXT.replace("\n", "\r\n"), ABSENT_TEXT.replace("  ", "\t")])
def test_enable_disable_round_trip_restores_settings_exactly(tmp_path, text):
    cfg, env = cfg_env(tmp_path)
    sp = cfg / "settings.json"
    sp.write_bytes(text.encode("utf-8"))
    before = sp.read_bytes()
    state = tmp_path / "state"
    assert limits_setup.settings_path(env) == sp
    st = limits_setup.status(state, env)
    assert not st["enabled"] and st["canEnable"] and st["settingsPath"] == str(sp)
    on = limits_setup.enable(state, CONSOLE, env)
    assert on["enabled"] and (state / "statusline_wrap.py").exists()
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert list(data)[:3] == ["model", "z_first", "env"]  # 다른 키 순서·값 그대로
    assert data["z_first"] == {"b": 1, "a": [3, 2, 1]} and data["env"] == {"한글": "값", "A": "1"} and data["hooks"] == {}
    assert data["statusLine"]["command"] == on["newCommand"] and data["statusLine"]["type"] == "command"
    if "padding" in text:
        assert data["statusLine"]["padding"] == 2  # 원래 객체의 다른 키는 그대로
    # 멱등: 다시 켜도 설정·기억 파일이 그대로(다시 감싸지 않는다)
    after_on, rec = sp.read_bytes(), (state / "statusline_orig.json").read_bytes()
    assert limits_setup.enable(state, CONSOLE, env)["enabled"]
    assert sp.read_bytes() == after_on and (state / "statusline_orig.json").read_bytes() == rec
    assert json.loads(rec)["present"] == ("padding" in text)
    assert ("padding" not in text) or json.loads(rec)["value"]["command"].startswith("bash")  # 원래 객체를 통째로 기억
    off = limits_setup.disable(state, env)
    assert not off["enabled"] and not (state / "statusline_orig.json").exists()
    assert sp.read_bytes() == before  # 켠 뒤 아무도 안 고쳤으면 켜기 전 바이트 그대로(들여쓰기·CRLF·탭·한글 포함)
    assert json.loads(sp.read_text(encoding="utf-8")) == json.loads(before.decode("utf-8"))  # 항상 값은 같다
    assert ("statusLine" in json.loads(sp.read_text(encoding="utf-8"))) == ("padding" in text)  # 없던 설정은 키가 없다


def test_enable_creates_missing_settings_and_disable_removes_file(tmp_path):
    cfg, env = cfg_env(tmp_path)
    state = tmp_path / "state"
    on = limits_setup.enable(state, CONSOLE, env)
    sp = cfg / "settings.json"
    assert on["enabled"] and json.loads(sp.read_text(encoding="utf-8")) == {"statusLine": {"type": "command", "command": on["newCommand"]}}
    limits_setup.disable(state, env)
    assert not sp.exists()  # 설정 파일 자체가 없었으면 없던 대로


@pytest.mark.parametrize("had_statusline", [True, False])
def test_disable_after_other_settings_changed_restores_only_statusline(tmp_path, had_statusline):
    cfg, env = cfg_env(tmp_path)
    sp, state = cfg / "settings.json", tmp_path / "state"
    sp.write_text(ORIG_TEXT if had_statusline else ABSENT_TEXT, encoding="utf-8")
    limits_setup.enable(state, CONSOLE, env)
    data = json.loads(sp.read_text(encoding="utf-8"))
    data["newKey"] = "그 사이 추가"
    sp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    limits_setup.disable(state, env)
    now = json.loads(sp.read_text(encoding="utf-8"))
    assert now["newKey"] == "그 사이 추가" and ("statusLine" in now) == had_statusline
    if had_statusline:
        assert now["statusLine"] == json.loads(ORIG_TEXT)["statusLine"]


def test_disable_leaves_a_statusline_the_user_changed_meanwhile(tmp_path):
    cfg, env = cfg_env(tmp_path)
    sp, state = cfg / "settings.json", tmp_path / "state"
    sp.write_text(ORIG_TEXT, encoding="utf-8")
    limits_setup.enable(state, CONSOLE, env)
    data = json.loads(sp.read_text(encoding="utf-8"))
    data["statusLine"] = {"type": "command", "command": "echo mine"}
    sp.write_text(json.dumps(data), encoding="utf-8")
    off = limits_setup.disable(state, env)
    assert json.loads(sp.read_text(encoding="utf-8"))["statusLine"]["command"] == "echo mine" and off["note"]


def test_enable_refuses_bad_settings_and_touches_nothing(tmp_path):
    cfg, env = cfg_env(tmp_path)
    sp, state = cfg / "settings.json", tmp_path / "state"
    for bad in (b"{ nope", b"[1]", b"\xff\xfe\x00"):
        sp.write_bytes(bad)
        with pytest.raises(limits_setup.LimitsError):
            limits_setup.enable(state, CONSOLE, env)
        assert sp.read_bytes() == bad and not (state / "statusline_orig.json").exists()
        assert not limits_setup.status(state, env)["canEnable"]
    sp.write_text('{"statusLine": "echo x"}', encoding="utf-8")  # command 객체가 아니면 감싸지 않는다
    with pytest.raises(limits_setup.LimitsError):
        limits_setup.enable(state, CONSOLE, env)
    with pytest.raises(limits_setup.LimitsError):  # 따옴표·$ 가 든 경로는 명령에 안전하게 쓸 수 없다
        limits_setup.wrapper_command(tmp_path / 'a"b')


def test_settings_path_uses_config_dir_else_home(tmp_path):
    assert limits_setup.settings_path({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / "settings.json"
    assert limits_setup.settings_path({}, home=tmp_path) == tmp_path / ".claude" / "settings.json"


# ---- 서버: 한도 합치기, 설정 API ----

def test_statusline_windows_converts_percent_to_ratio(tmp_path):
    f = tmp_path / "statusline_limits.json"
    f.write_text(json.dumps({"t": 50.0, "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": 99}, "seven_day": {"used_percentage": 250, "resets_at": 5}, "x": {}}}), encoding="utf-8")
    w = store_mod.statusline_windows(tmp_path)
    assert w["five_hour"] == {"type": "five_hour", "status": "allowed", "resetsAt": 99, "utilization": 0.42, "t": 50.0, "source": "statusline"}
    assert w["seven_day"]["utilization"] is None and w["seven_day"]["resetsAt"] == 5 and "x" not in w  # 범위 밖 비율은 모름
    f.write_text("{깨짐", encoding="utf-8")
    assert store_mod.statusline_windows(tmp_path) == {} and store_mod.statusline_windows(None) == {}


def test_account_limits_takes_latest_of_event_and_statusline(tmp_path, monkeypatch):
    from test_web_console import Console
    cfg, env = cfg_env(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
    c = Console(tmp_path, monkeypatch)
    try:
        c.login()
        c.state.mkdir(parents=True, exist_ok=True)
        (c.state / "statusline_limits.json").write_text(json.dumps({"t": 100.0, "rate_limits": {"five_hour": {"used_percentage": 30, "resets_at": 9}, "seven_day": {"used_percentage": 5, "resets_at": 8}}}), encoding="utf-8")
        s = c.app.store.ensure("a", str(c.work))
        s["rateWindows"] = {"five_hour": {"status": "allowed_warning", "resetsAt": 7, "utilization": 0.95, "t": 200.0}, "seven_day": {"status": "allowed", "resetsAt": 6, "utilization": 0.9, "t": 50.0}}
        got = {w["type"]: w for w in c.call("GET", "/api/account-limits")[1]["windows"]}
        assert got["five_hour"]["utilization"] == 0.95 and got["five_hour"]["source"] == "rate_limit_event"  # 이벤트가 더 최신
        assert got["seven_day"]["utilization"] == 0.05 and got["seven_day"]["source"] == "statusline"  # 상태줄이 더 최신(5% → 0.05 단위 맞춤)
    finally:
        c.close()


def test_limits_settings_api_requires_confirmation_and_round_trips(tmp_path, monkeypatch):
    from test_web_console import Console
    cfg, env = cfg_env(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", env["CLAUDE_CONFIG_DIR"])
    (cfg / "settings.json").write_text(ORIG_TEXT, encoding="utf-8")
    before = (cfg / "settings.json").read_bytes()
    c = Console(tmp_path, monkeypatch)
    try:
        c.login()
        st, body, _ = c.call("GET", "/api/settings/limits")
        assert st == 200 and not body["enabled"] and body["settingsPath"] == str(cfg / "settings.json") and body["current"]["padding"] == 2
        assert c.call("PUT", "/api/settings/limits", {"enabled": True})[0] == 400  # 확인 없이는 바꾸지 않는다
        assert c.call("PUT", "/api/settings/limits", {"enabled": "x"})[0] == 400
        assert (cfg / "settings.json").read_bytes() == before
        st, body, _ = c.call("PUT", "/api/settings/limits", {"enabled": True, "confirmed": True})
        assert st == 200 and body["enabled"] and json.loads((cfg / "settings.json").read_text(encoding="utf-8"))["statusLine"]["command"] == body["newCommand"]
        assert c.call("GET", "/api/settings/limits")[1]["enabled"]
        st, body, _ = c.call("PUT", "/api/settings/limits", {"enabled": False})
        assert st == 200 and not body["enabled"] and (cfg / "settings.json").read_bytes() == before
        assert c.call("GET", "/api/settings/limits", cookie=False)[0] == 401
    finally:
        c.close()


def test_wrapper_path_follows_state_dir_and_script_is_standalone(tmp_path):
    """감싸개는 콘솔 모듈을 import 하지 않는다(상태 폴더로 복사돼 혼자 돈다)."""
    src = (CONSOLE / "statusline_wrap.py").read_text(encoding="utf-8")
    assert not any(line.startswith(("import store", "import server", "from store", "from server")) for line in src.splitlines())
    assert "sys.stdin.buffer" in src and "sys.stdout.buffer" in src and "text=True" not in src and "universal_newlines" not in src
    assert os.path.exists(CONSOLE / "limits_setup.py")
