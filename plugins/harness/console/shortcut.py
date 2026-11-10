"""바탕화면 "Blueward Harness" 바로가기를 만든다(Windows 만, #866). open.py 가 부른다.

구성: 바로가기(.lnk) -> wscript.exe + 런처.vbs(창 없이 uv 실행) -> launcher.py(최신 판 open.py 를 찾아 실행).
런처 파일 둘은 `<설정 폴더>/harness-console/launcher/` 에 두어 플러그인 판 폴더가 바뀌어도 바로가기가 깨지지 않는다.
사용자가 바로가기를 지우면 `shortcut.json` 에 기록해 두고 다시 만들지 않는다. `open.py --make-shortcut` 으로만 다시 만든다.
"""
from __future__ import annotations

import codecs
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import NamedTuple

import platform_compat

LNK_NAME = "Blueward Harness.lnk"
STATE_FILE = "shortcut.json"


class Result(NamedTuple):
    status: str  # "made" 만들었다 / "fixed" 고쳤다 / "none" 할 일 없음 / "failed" 만들지 못함
    text: str = ""


def config_dir(env=None, home: Path | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return Path(base) if base else (home or Path.home()) / ".claude"


def launcher_dir(env=None, home: Path | None = None) -> Path:
    """CLAUDE_PLUGIN_DATA 가 있든 없든(훅이냐 스킬이냐) 같은 자리여야 하므로 상태 폴더 규칙을 따르지 않는다."""
    return config_dir(env, home) / "harness-console" / "launcher"


def windows_desktop() -> Path | None:
    """바탕화면 폴더(OneDrive 로 옮겨진 것도 포함). 못 찾으면 None."""
    import ctypes
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le)  # FOLDERID_Desktop
    path = ctypes.c_wchar_p()
    try:
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path)) != 0:
            return None
        found = path.value
        ctypes.windll.ole32.CoTaskMemFree(path)
    except (AttributeError, OSError):
        return None
    return Path(found) if found else None


def read_state(ldir: Path) -> str | None:
    try:
        value = json.loads((ldir / STATE_FILE).read_text(encoding="utf-8")).get("state")
    except (OSError, ValueError, AttributeError):
        return None
    return value if value in ("made", "removed") else None


def write_state(ldir: Path, state: str) -> None:
    ldir.mkdir(parents=True, exist_ok=True)
    (ldir / STATE_FILE).write_text(json.dumps({"state": state}), encoding="utf-8")


def vbs_text(uv: str) -> str:
    """창 없이 `uv run --no-project python launcher.py` 를 부르는 스크립트. 폴더는 이 스크립트 자기 위치로 알아낸다."""
    q = '""'
    return "\r\n".join([
        'Set sh = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        'here = fso.GetParentFolderName(WScript.ScriptFullName)',
        f'cmd = Chr(34) & "{uv.replace(chr(34), q)}" & Chr(34) & " run --no-project --quiet python " & Chr(34) & here & "\\launcher.py" & Chr(34)',
        'sh.Run cmd, 0, False',
        '',
    ])


def write_launcher_files(ldir: Path, uv: str) -> Path:
    """launcher.py 와 launcher.vbs 를 최신 내용으로 둔다. 돌려주는 값은 vbs 경로."""
    ldir.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("launcher.py").read_text(encoding="utf-8")
    target = ldir / "launcher.py"
    if not target.is_file() or target.read_text(encoding="utf-8") != source:
        target.write_text(source, encoding="utf-8")
    vbs = ldir / "launcher.vbs"
    data = codecs.BOM_UTF16_LE + vbs_text(uv).encode("utf-16-le")  # wscript 가 한글 경로를 읽으려면 유니코드여야 한다
    if not vbs.is_file() or vbs.read_bytes() != data:
        vbs.write_bytes(data)
    return vbs


def wscript_path(env=None) -> str:
    env = os.environ if env is None else env
    return str(Path(env.get("SystemRoot") or "C:\\Windows") / "System32" / "wscript.exe")


CREATE_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HB_LNK);"
    "$s.TargetPath=$env:HB_TARGET;$s.Arguments=$env:HB_ARGS;$s.WorkingDirectory=$env:HB_DIR;"
    "$s.Description='Blueward Harness web console';$s.Save()"
)
CHECK_SCRIPT = (
    "$ErrorActionPreference='Stop';"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:HB_LNK);"
    "if($s.TargetPath -eq $env:HB_TARGET -and $s.Arguments -eq $env:HB_ARGS){exit 0}else{exit 3}"
)


def run_powershell(script: str, values: dict, runner=subprocess.run):
    ps = shutil.which("powershell") or "powershell"
    env = dict(os.environ, **{f"HB_{k}": v for k, v in values.items()})
    return runner([ps, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=30, env=env, **platform_compat.hidden_window_kwargs("windows"))


def lnk_values(lnk: Path, target: str, args: str, workdir: Path) -> dict:
    return {"LNK": str(lnk), "TARGET": target, "ARGS": args, "DIR": str(workdir)}


def lnk_matches(lnk: Path, target: str, args: str, workdir: Path, runner=subprocess.run) -> bool:
    return run_powershell(CHECK_SCRIPT, lnk_values(lnk, target, args, workdir), runner).returncode == 0


def create_lnk(lnk: Path, target: str, args: str, workdir: Path, runner=subprocess.run) -> None:
    done = run_powershell(CREATE_SCRIPT, lnk_values(lnk, target, args, workdir), runner)
    if done.returncode != 0:
        raise OSError((done.stderr or done.stdout or "PowerShell 가 실패했습니다.").strip()[:150])


def ensure_shortcut(force: bool = False, os_name: str | None = None, desktop: Path | None = None, ldir: Path | None = None,
                    uv: str | None = None, runner=subprocess.run) -> Result:
    """바탕화면 바로가기를 정해진 규칙대로 만든다. 예외를 밖으로 내지 않는다.
    처음이면 만들고, 있는데 가리키는 곳이 다르면 고치고, 한 번 만든 뒤 사라졌으면 사용자가 지운 것으로 기록하고 다시 만들지 않는다.
    macOS·Linux 는 지원하지 않으므로 아무것도 하지 않는다."""
    if (os_name or platform_compat.current_os()) != "windows":
        return Result("none")
    ldir = ldir or launcher_dir()
    try:
        desk = desktop if desktop is not None else windows_desktop()
        if desk is None or not desk.is_dir():
            return Result("failed", "바로가기를 만들지 못함(바탕화면 폴더를 찾지 못했어요)")
        lnk = desk / LNK_NAME
        state = read_state(ldir)
        if not force:
            if state == "removed":
                return Result("none")
            if state == "made" and not lnk.exists():
                write_state(ldir, "removed")  # 지운 것으로 보고 다시 만들지 않는다
                return Result("none")
        vbs = write_launcher_files(ldir, uv or shutil.which("uv") or "uv")
        target, args = wscript_path(), f'"{vbs}"'
        existed = lnk.exists()
        if existed and not force and lnk_matches(lnk, target, args, ldir, runner):
            if state != "made":
                write_state(ldir, "made")
            return Result("none")
        create_lnk(lnk, target, args, ldir, runner)
        if not lnk_matches(lnk, target, args, ldir, runner):
            return Result("failed", "바로가기를 만들지 못함(만든 바로가기를 다시 읽어 확인하지 못했어요)")
        write_state(ldir, "made")
        if existed and not force:
            return Result("fixed", "바탕화면의 Blueward Harness 바로가기가 가리키는 곳을 고쳤어요.")
        return Result("made", "바탕화면에 Blueward Harness 바로가기를 만들었어요.")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return Result("failed", f"바로가기를 만들지 못함({' '.join(str(exc).split())[:120] or type(exc).__name__})")
