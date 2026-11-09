"""OS 차이를 한 곳에 모은다(web-console.md §1).

분기가 있는 함수는 `os_name` 을 인자로 받는다. 시험이 Windows 값을 넣어 분기 로직만 확인할 수 있게 하려는 것이다.
"""
from __future__ import annotations

import ntpath
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Mapping

DEFAULT_PORT = 4873


def current_os() -> str:
    return "windows" if sys.platform.startswith("win") else "posix"


def port_from_env(env: Mapping[str, str] | None = None) -> int:
    """기본은 4873. 시험이 임시 포트를 쓰도록 HARNESS_CONSOLE_PORT 로 바꿀 수 있다."""
    raw = (env if env is not None else os.environ).get("HARNESS_CONSOLE_PORT", "")
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_PORT
    return port if 0 < port < 65536 else DEFAULT_PORT


def state_dir(env: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    """CLAUDE_PLUGIN_DATA -> <CLAUDE_CONFIG_DIR 또는 ~/.claude>/harness-console."""
    env = os.environ if env is None else env
    data = env.get("CLAUDE_PLUGIN_DATA")
    if data:
        return Path(data)
    base = env.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else (home or Path.home()) / ".claude"
    return root / "harness-console"


def hidden_window_kwargs(os_name: str | None = None) -> dict:
    """Windows 에서 자식 프로세스의 콘솔 창이 뜨지 않게 한다. POSIX 는 필요 없다."""
    if (os_name or current_os()) == "windows":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


CLAUDE_MISSING = ("claude 실행 파일을 찾을 수 없어. Claude Code 를 설치했는지 확인하고, 새 터미널에서 `claude --version` 이 "
                  "되는지 봐 줘. npm 으로 설치했다면 `claude.exe` 가 있는 공식 설치본으로 다시 설치하는 걸 권해.")


def _windows_cmd_target(path: str, which, exists) -> list[str] | None:
    """npm 이 만든 claude.cmd 옆의 node_modules 에서 .cmd 없이 직접 실행할 대상을 찾는다.
    네이티브 exe -> node + cli.js 순서. cmd /c 는 공백·한글 경로와 JSON 인자에서 깨지므로 쓰지 않는다."""
    base = ntpath.join(ntpath.dirname(path), "node_modules", "@anthropic-ai", "claude-code")
    for rel in (("bin", "claude.exe"), ("claude.exe",)):
        exe = ntpath.join(base, *rel)
        if exists(exe):
            return [exe]
    cli = ntpath.join(base, "cli.js")
    if exists(cli):
        node = which("node") or ntpath.join(ntpath.dirname(path), "node.exe")
        if which("node") or exists(node):
            return [node, cli]
    return None


def find_claude(os_name: str | None = None, which: Callable[[str], str | None] = shutil.which,
                exists: Callable[[str], bool] = os.path.exists) -> list[str] | None:
    """claude 실행 명령의 앞부분. 못 찾으면 None(호출한 쪽이 CLAUDE_MISSING 을 보여 준다).
    Windows 는 claude.exe 를 먼저 찾고, .cmd/.bat 이면 옆 node_modules 의 exe 또는 cli.js 를 직접 실행한다.
    cmd /c 로 감싸지 않는다. 뒤에 붙는 인자는 이 모듈이 정한 고정 값뿐이고 사용자 입력은 stdin 으로만 넘긴다."""
    if (os_name or current_os()) != "windows":
        path = which("claude")
        return [path] if path else None
    exe = which("claude.exe")
    if exe:
        return [exe]
    path = which("claude")
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat", ".ps1")):
        return _windows_cmd_target(path, which, exists)
    return [path]


def terminate(proc, os_name: str | None = None, runner=subprocess.run) -> None:
    """프로세스를 끝내 달라고 요청한다. POSIX 는 SIGTERM, Windows 는 taskkill /T /F 로 자식까지 끈다."""
    try:
        if (os_name or current_os()) == "windows":
            pid = getattr(proc, "pid", None)
            if pid is None or not kill_tree(pid, "windows", runner):
                proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass


def kill_tree(pid: int, os_name: str | None = None, runner=subprocess.run) -> bool:
    """Windows: taskkill /PID <pid> /T /F (창 없이). 성공 여부."""
    try:
        done = runner(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=10,
                      **hidden_window_kwargs(os_name or "windows"))
        return getattr(done, "returncode", 1) == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def terminate_pid(pid: int, os_name: str | None = None, runner=subprocess.run) -> bool:
    if (os_name or current_os()) == "windows":
        return kill_tree(pid, "windows", runner)
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


def windows_server_python(exists: Callable[[str], bool] = os.path.exists) -> tuple[str, bool]:
    """Windows 에서 서버를 띄울 (인터프리터, 콘솔 없는 인터프리터인지).
    venv 의 python.exe 는 진짜 python 을 자식으로 다시 띄우는 런처라 콘솔 창이 생기고 프로세스가 둘이 된다.
    그래서 base 인터프리터(sys._base_executable)와 같은 폴더의 pythonw.exe 를 쓴다. 서버는 표준 라이브러리만 쓴다.
    pythonw.exe 가 없으면 지금 인터프리터로 돌아간다(이때 창은 CREATE_NO_WINDOW 로 막는다)."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    pyw = ntpath.join(ntpath.dirname(base), "pythonw.exe")
    if exists(pyw):
        return pyw, True
    return sys.executable, False


def popen_detached_kwargs(os_name: str | None = None, windowless: bool = True, breakaway: bool = True) -> dict:
    """서버를 띄우는 Popen 인자. Windows 는 하나의 creationflags 로 합친다(키워드 중복 방지).
    windowless=True(pythonw.exe): DETACHED_PROCESS. False(콘솔용 인터프리터): DETACHED_PROCESS 와 같이 주면
    CREATE_NO_WINDOW 가 무시되므로 DETACHED_PROCESS 대신 CREATE_NO_WINDOW 를 쓴다.
    breakaway: 부모 Job Object 에 묶여 같이 정리되지 않게 한다(부모 Job 이 허용하지 않으면 호출한 쪽이 빼고 다시 시도한다)."""
    if (os_name or current_os()) != "windows":
        return {"start_new_session": True}
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008) if windowless else getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    if breakaway:
        flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    return {"creationflags": flags}


def open_in_browser(url: str, opener: Callable[[str], bool] = webbrowser.open) -> bool:
    """기본 브라우저로 연다. 서버 프로세스가 직접 호출한다. 열 수 없으면 False."""
    try:
        return bool(opener(url))
    except Exception:
        return False


PICK_TIMEOUT = 600.0  # 사람이 폴더를 고르는 동안 기다리는 시간(초). 넘으면 프로세스를 끝낸다
PICK_FALLBACK = "경로를 직접 적어 줘."
# 고정 스크립트. 사용자 입력을 넣지 않는다. 시작 폴더는 환경변수 HARNESS_PICK_START(UTF-8 base64)로 받는다.
# 탐색기식 창(IFileOpenDialog + FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM)을 Add-Type 한 작은 C# 로 띄우고,
# COM 이 실패하면 옛 FolderBrowserDialog 로 대신한다.
# TopMost 소유 폼을 쓰는 이유: 서버가 창 없이 돌아서 대화상자가 다른 창 뒤에 숨기 쉽다.
# 고르면 UTF-8 경로를 base64 로 한 줄 출력하고, 취소하면 아무것도 출력하지 않고 0 으로 끝난다(한글 경로가 콘솔 코드페이지에 깨지지 않게).
WINDOWS_PICK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$start = [Environment]::GetFolderPath('UserProfile')
try {
  $given = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($env:HARNESS_PICK_START))
  if ($given -and (Test-Path -LiteralPath $given -PathType Container)) { $start = $given }
} catch {}
$title = '작업 폴더 고르기'
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.FormBorderStyle = 'None'
$owner.Opacity = 0
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.StartPosition = 'CenterScreen'
$owner.Show()
$owner.Activate()
$picked = $null
$done = $false
try {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HarnessPick {
  [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")] class FileOpenDialogCom {}
  [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
    void GetParent(out IShellItem ppsi);
    void GetDisplayName(uint sigdnName, [MarshalAs(UnmanagedType.LPWStr)] out string ppszName);
    void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
    void Compare(IShellItem psi, uint hint, out int piOrder);
  }
  [ComImport, Guid("d57c7288-d4ad-4768-be02-9d969532d960"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileOpenDialog {
    [PreserveSig] int Show(IntPtr hwndOwner);
    void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
    void SetFileTypeIndex(uint iFileType);
    void GetFileTypeIndex(out uint piFileType);
    void Advise(IntPtr pfde, out uint pdwCookie);
    void Unadvise(uint dwCookie);
    void SetOptions(uint fos);
    void GetOptions(out uint pfos);
    void SetDefaultFolder(IShellItem psi);
    void SetFolder(IShellItem psi);
    void GetFolder(out IShellItem ppsi);
    void GetCurrentSelection(out IShellItem ppsi);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
    void GetResult(out IShellItem ppsi);
    void AddPlace(IShellItem psi, int fdap);
    void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
    void Close(int hr);
    void SetClientGuid(ref Guid guid);
    void ClearClientData();
    void SetFilter(IntPtr pFilter);
    void GetResults(out IntPtr ppenum);
    void GetSelectedItems(out IntPtr ppsai);
  }
  [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
  static extern void SHCreateItemFromParsingName(string path, IntPtr pbc, ref Guid riid, out IShellItem item);
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] static extern bool AllowSetForegroundWindow(int dwProcessId);
  [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  // 고른 경로를 돌려준다. 취소하면 "". COM 이 실패하면 예외를 던진다(호출한 쪽이 대체 창을 띄운다).
  public static string Pick(IntPtr owner, string start, string title) {
    Guid shellItem = new Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe");
    var dlg = (IFileOpenDialog)new FileOpenDialogCom();
    try {
      dlg.SetOptions(0x20 | 0x40 | 0x800);  // PICKFOLDERS | FORCEFILESYSTEM | PATHMUSTEXIST
      dlg.SetTitle(title);
      IShellItem folder;
      SHCreateItemFromParsingName(start, IntPtr.Zero, ref shellItem, out folder);
      dlg.SetFolder(folder);
      AllowSetForegroundWindow(-1);
      keybd_event(0x12, 0, 0, UIntPtr.Zero);  // Alt 를 한 번 눌러 포그라운드 잠금을 풀어 준다
      keybd_event(0x12, 0, 2, UIntPtr.Zero);
      SetForegroundWindow(owner);
      int hr = dlg.Show(owner);
      if (hr == unchecked((int)0x800704C7)) return "";  // ERROR_CANCELLED
      if (hr != 0) Marshal.ThrowExceptionForHR(hr);
      IShellItem item;
      dlg.GetResult(out item);
      string path;
      item.GetDisplayName(0x80058000, out path);  // SIGDN_FILESYSPATH
      return path ?? "";
    } finally { Marshal.ReleaseComObject(dlg); }
  }
}
'@
  $picked = [HarnessPick]::Pick($owner.Handle, $start, $title)
  $done = $true
} catch {
  $done = $false
}
if (-not $done) {
  $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
  $dlg.Description = '작업 폴더를 골라 주세요.'
  $dlg.ShowNewFolderButton = $true
  $dlg.SelectedPath = $start
  if ($dlg.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { $picked = $dlg.SelectedPath }
}
if ($picked) {
  [Console]::Out.Write([System.Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($picked)))
}
$owner.Dispose()
exit 0
"""


class PickUnavailable(Exception):
    """폴더 선택 창을 띄우지 못했다. 메시지는 화면에 그대로 보여 준다."""


def _windows_pick_command() -> list[str]:
    import base64
    encoded = base64.b64encode(WINDOWS_PICK_SCRIPT.encode("utf-16-le")).decode("ascii")
    return ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded]


def pick_folder(os_name: str | None = None, runner=subprocess.run, timeout: float = PICK_TIMEOUT,
                start: str | None = None) -> str | None:
    """OS 의 폴더 선택 창을 띄워 고른 경로를 돌려준다. 취소하면 None. 띄우지 못하면 PickUnavailable.
    runner 는 subprocess.run 과 같은 모양이다(시험이 가짜를 넣는다). 셸을 거치지 않고 인자 목록으로만 부른다.
    start 는 Windows 창의 시작 폴더(없거나 폴더가 아니면 사용자 홈). 스크립트 본문이 아니라 환경변수로만 넘긴다."""
    name = os_name or current_os()
    extra: dict = {}
    if name == "windows":
        cmd, cancel_code = _windows_pick_command(), None
        import base64
        extra["env"] = {**os.environ, "HARNESS_PICK_START": base64.b64encode((start or "").encode("utf-8")).decode("ascii")}
    elif name == "macos" or (name == "posix" and sys.platform == "darwin"):
        cmd, cancel_code = ["osascript", "-e", "POSIX path of (choose folder)"], 1
    else:
        raise PickUnavailable("이 컴퓨터에서는 폴더 선택 창을 열 수 없어. " + PICK_FALLBACK)
    try:
        done = runner(cmd, capture_output=True, timeout=timeout, **extra, **hidden_window_kwargs(name))
    except subprocess.TimeoutExpired:
        raise PickUnavailable("폴더 선택 창이 너무 오래 열려 있어 닫았어. " + PICK_FALLBACK)
    except (OSError, subprocess.SubprocessError):
        raise PickUnavailable("폴더 선택 창을 열지 못했어. " + PICK_FALLBACK)
    code = getattr(done, "returncode", 1)
    raw = getattr(done, "stdout", b"") or b""
    if code != 0:
        if code == cancel_code:
            return None
        raise PickUnavailable("폴더 선택 창이 정상적으로 끝나지 않았어. " + PICK_FALLBACK)
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    text = text.strip()
    if not text:
        return None  # 취소(Windows 는 아무것도 출력하지 않는다)
    if name == "windows":
        import base64
        import binascii
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, ValueError):
            raise PickUnavailable("고른 폴더 경로를 읽지 못했어. " + PICK_FALLBACK)
    elif len(text) > 1:
        text = text.rstrip("/") or "/"
    return text


def same_path(a: str | os.PathLike, b: str | os.PathLike, os_name: str | None = None) -> bool:
    if (os_name or current_os()) == "windows":  # 경로 구분자와 대소문자를 구별하지 않는다
        return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))
    return str(a) == str(b)


def clean_user_path(raw: str) -> str:
    """탐색기 '경로로 복사' 의 "C:\\Work\\proj" 처럼 앞뒤 공백과 따옴표가 붙은 입력을 정리한다."""
    return raw.strip().strip("\"'").strip()


def is_within(path: str | os.PathLike, root: str | os.PathLike, os_name: str | None = None) -> bool:
    """realpath 로 풀어서 path 가 root 안(같은 곳 포함)인지 본다. 심볼릭 링크 탈출을 막는다."""
    try:
        p = os.path.realpath(path)
        r = os.path.realpath(root)
    except (OSError, ValueError):
        return False
    if (os_name or current_os()) == "windows":
        p, r = os.path.normcase(p), os.path.normcase(r)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:  # Windows 에서 드라이브가 다르면
        return False


def socket_closed(sock: socket.socket) -> bool:
    """상대가 연결을 끊었는지 본다. 읽을 게 있으면 건드리지 않고 엿보기만 한다."""
    try:
        readable, _, _ = select.select([sock], [], [], 0)
        if not readable:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return True


def opener_os() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def open_path(path: str, mode: str, os_name: str | None = None, popen=subprocess.Popen, startfile=None) -> str:
    """파일을 기본 앱으로 열거나(open) 탐색기·Finder 에서 위치를 보여 준다(reveal). 성공이면 "", 실패면 사유 문장.
    셸을 거치지 않고 인자 목록(Windows 의 reveal 만 explorer 가 요구하는 /select,"경로" 한 줄)으로 부른다.
    호출한 쪽이 path 가 작업 폴더 안의 존재하는 파일이고 열어도 되는 확장자인지 이미 검사해야 한다."""
    name = os_name or opener_os()
    if '"' in path or "\0" in path:
        return "경로에 쓸 수 없는 문자가 들어 있어."
    quiet = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    try:
        if name == "windows":
            if mode == "reveal":
                popen(f'explorer /select,"{path}"', **quiet)
            else:
                (startfile or os.startfile)(path)
        elif name == "macos":
            popen(["open", "-R", path] if mode == "reveal" else ["open", path], **quiet)
        else:
            popen(["xdg-open", os.path.dirname(path) if mode == "reveal" else path], **quiet)
    except OSError as e:
        return f"열지 못했어: {e}"
    return ""
