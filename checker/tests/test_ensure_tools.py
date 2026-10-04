"""세션 시작 때 uv·jq·gh·gitleaks 를 점검하고 winget 으로 설치하는 스크립트 검사(#116).

진짜 시스템은 건드리지 않는다. 가짜 winget·uv·jq·gh 를 임시 폴더에 만들고 PATH 와
LOCALAPPDATA 를 그 안으로 돌려서 스크립트를 실행한다. winget 을 실제로 부르지 않는다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

pytestmark = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")

ENSURE = PLUGIN_ROOT / "hooks" / "ensure-tools.sh"
SESSION_START = PLUGIN_ROOT / "hooks" / "session-start-sync.sh"

WINDOWS_UNAME = "MINGW64_NT-10.0"

FAKE_WINGET = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$FAKE_WINGET_MODE" in
  fail) exit 1 ;;
  hang) sleep 30; exit 0 ;;
  scope_fail)
    case "$*" in *--scope*) exit 1 ;; esac ;;
esac
id=""
prev=""
for a in "$@"; do
  [ "$prev" = "--id" ] && id="$a"
  prev="$a"
done
case "$id" in
  astral-sh.uv) tool=uv ;;
  jqlang.jq) tool=jq ;;
  GitHub.cli) tool=gh ;;
  Gitleaks.Gitleaks) tool=gitleaks ;;
esac
mkdir -p "$LOCALAPPDATA/Microsoft/WinGet/Links"
echo fake > "$LOCALAPPDATA/Microsoft/WinGet/Links/$tool.exe"
exit 0
"""

FAKE_GH = """#!/bin/sh
if [ "$1" = "auth" ]; then
  [ "$FAKE_GH_LOGIN" = "0" ] && exit 1
  exit 0
fi
exit 0
"""

FAKE_TOOL = "#!/bin/sh\nexit 0\n"


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


_HIDDEN_TOOLS = {"uv", "uvx", "jq", "gh", "gitleaks", "winget"}
_posix_base: str | None = None


def _base_path() -> list[str]:
    """coreutils 가 있는 폴더만. 진짜 uv·jq·gh·winget 이 잡히지 않게 좁힌다.

    Linux(CI 의 ubuntu-latest)는 jq·gh 가 /usr/bin 에 기본으로 깔려 있어 /usr/bin 을
    그대로 넣으면 "도구가 없는 PC" 를 흉내 낼 수 없다. 그래서 /usr/bin 과 /bin 의
    실행 파일을 위 도구만 빼고 임시 폴더에 링크해 그 폴더를 쓴다.
    """
    global _posix_base
    if os.name == "nt":
        usr_bin = Path(_BASH).parent.parent / "usr" / "bin"
        return [str(usr_bin)]
    if _posix_base is None:
        base = Path(tempfile.mkdtemp(prefix="ensure-tools-bin-"))
        for src_dir in ("/usr/bin", "/bin"):
            if not os.path.isdir(src_dir):
                continue
            for name in os.listdir(src_dir):
                if name in _HIDDEN_TOOLS or (base / name).exists():
                    continue
                src = os.path.join(src_dir, name)
                if os.path.isfile(src) and os.access(src, os.X_OK):
                    (base / name).symlink_to(src)
        _posix_base = str(base)
    return [_posix_base]


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bin = tmp_path / "fakebin"
        self.bin.mkdir()
        self.local = tmp_path / "localappdata"
        self.local.mkdir()
        self.data = tmp_path / "plugin-data"
        self.log = tmp_path / "winget.log"
        self.extra_path: list[str] = []
        # 기존 검사는 uv·jq·gh 만 본다. gitleaks(#170)는 기본으로 있는 것으로 두고, 없는 경우는 따로 본다.
        _write_exec(self.bin / "gitleaks", FAKE_TOOL)

    def add_tool(self, name: str) -> None:
        _write_exec(self.bin / name, FAKE_GH if name == "gh" else FAKE_TOOL)

    def add_winget(self) -> None:
        _write_exec(self.bin / "winget", FAKE_WINGET)

    def add_links_exe(self, name: str) -> None:
        links = self.local / "Microsoft" / "WinGet" / "Links"
        links.mkdir(parents=True, exist_ok=True)
        (links / f"{name}.exe").write_text("fake", encoding="utf-8")

    def winget_calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def run(self, script: Path = ENSURE, stdin: str = "", **overrides: str) -> str:
        env = {
            **os.environ,
            "PATH": os.pathsep.join([str(self.bin), *self.extra_path, *_base_path()]),
            "LOCALAPPDATA": str(self.local),
            "HARNESS_PROGRAMFILES": str(self.tmp / "programfiles"),
            # Git Bash 는 $HOME/bin 을 PATH 에 덧붙인다. 진짜 jq 가 잡히지 않게 HOME 도 비운다.
            "HOME": str(self.tmp / "home"),
            "CLAUDE_PLUGIN_DATA": str(self.data),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
            "HARNESS_FAKE_UNAME": WINDOWS_UNAME,
            "FAKE_LOG": str(self.log),
            "FAKE_WINGET_MODE": "ok",
            "FAKE_GH_LOGIN": "1",
        }
        env.pop("HARNESS_NO_AUTO_INSTALL", None)
        env.update(overrides)
        done = subprocess.run(
            [_BASH, str(script)],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=60,
        )
        return done.stdout


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _all_tools(env: Env) -> None:
    for name in ("uv", "jq", "gh"):
        env.add_tool(name)


def test_다_있으면_아무것도_내지_않고_winget_도_부르지_않는다(env):
    _all_tools(env)
    env.add_winget()

    assert env.run() == ""
    assert env.winget_calls() == []


def test_uv_가_없으면_winget_으로_설치하고_새로_열라고_알린다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()

    out = env.run()

    calls = env.winget_calls()
    assert len(calls) == 1
    assert "install --id astral-sh.uv -e --silent" in calls[0]
    assert "--accept-package-agreements" in calls[0]
    assert "--accept-source-agreements" in calls[0]
    assert "--disable-interactivity" in calls[0]
    assert "--scope user" in calls[0]
    assert "uv 가 없어 winget 으로 설치했습니다" in out
    assert "다음: 이 세션은 새 프로그램을 아직 못 찾으니 Claude Code 를 새로 여십시오." in out
    assert not (env.data / "tool-install-failures").exists()


def test_user_scope_설치가_실패하면_scope_없이_다시_시도한다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()

    out = env.run(FAKE_WINGET_MODE="scope_fail")

    calls = env.winget_calls()
    assert len(calls) == 2
    assert "--scope user" in calls[0]
    assert "--scope" not in calls[1]
    assert "uv 가 없어 winget 으로 설치했습니다" in out


def test_gh_는_scope_없이_설치한다(env):
    env.add_tool("uv")
    env.add_tool("jq")
    env.add_winget()

    env.run()

    calls = env.winget_calls()
    assert len(calls) == 1
    assert "--id GitHub.cli" in calls[0]
    assert "--scope" not in calls[0]


def test_설치가_실패하면_수동_명령을_안내하고_실패를_기록한다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()

    out = env.run(FAKE_WINGET_MODE="fail")

    assert "uv 를 winget 으로 설치하지 못했습니다" in out
    assert "다음: 사람이 할 일 - PowerShell 에서 winget install --id astral-sh.uv -e" in out
    assert "설치했습니다" not in out
    state = (env.data / "tool-install-failures").read_text(encoding="utf-8")
    assert state.startswith("uv ")


def test_24시간_안에_다시_열면_winget_을_부르지_않고_안내만_한다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()
    env.run(FAKE_WINGET_MODE="fail")
    first_calls = len(env.winget_calls())

    out = env.run(FAKE_WINGET_MODE="fail")

    assert len(env.winget_calls()) == first_calls
    assert "24시간 동안 다시 시도하지 않습니다" in out
    assert "winget install --id astral-sh.uv -e" in out


def test_24시간이_지난_실패_기록은_다시_시도한다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()
    env.data.mkdir()
    (env.data / "tool-install-failures").write_text("uv 1000\n", encoding="utf-8")

    out = env.run()

    assert len(env.winget_calls()) == 1
    assert "winget 으로 설치했습니다" in out
    assert "uv 1000" not in (env.data / "tool-install-failures").read_text(encoding="utf-8")


def test_winget_이_없으면_설치_안내만_한다(env):
    env.add_tool("jq")
    env.add_tool("gh")

    out = env.run()

    assert "uv 가 없고 winget 도 찾지 못해" in out
    assert "winget install --id astral-sh.uv -e" in out
    assert env.winget_calls() == []


def test_Windows_가_아니면_설치하지_않고_brew_를_안내한다(env):
    env.add_tool("gh")
    env.add_winget()

    out = env.run(HARNESS_FAKE_UNAME="Darwin")

    assert env.winget_calls() == []
    assert "brew install uv jq" in out
    assert "Windows 가 아니라" in out


def test_HARNESS_NO_AUTO_INSTALL_이면_설치하지_않는다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()

    out = env.run(HARNESS_NO_AUTO_INSTALL="1")

    assert env.winget_calls() == []
    assert "HARNESS_NO_AUTO_INSTALL=1" in out
    assert "winget install --id astral-sh.uv -e" in out
    assert not (env.data / "tool-install-failures").exists()


def test_winget_링크_폴더에만_있으면_새로_열라고_알린다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()
    env.add_links_exe("uv")

    out = env.run()

    assert env.winget_calls() == []
    assert "uv 는 설치돼 있지만 이 세션이 아직 못 찾습니다. 다음: Claude Code 를 새로 여십시오." in out


def test_winget_패키지_폴더에만_있어도_찾는다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()
    pkg = env.local / "Microsoft" / "WinGet" / "Packages" / "astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe"
    pkg.mkdir(parents=True)
    (pkg / "uv.exe").write_text("fake", encoding="utf-8")

    out = env.run()

    assert env.winget_calls() == []
    assert "uv 는 설치돼 있지만 이 세션이 아직 못 찾습니다" in out


def test_gh_가_있어도_로그인이_안_돼_있으면_로그인을_안내한다(env):
    _all_tools(env)
    env.add_winget()

    out = env.run(FAKE_GH_LOGIN="0")

    assert env.winget_calls() == []
    assert "다음: 사람이 할 일 - gh auth login 을 실행해 GitHub 에 로그인하십시오." in out


def test_세션_시작_요약에_설치_결과가_실린다(env):
    env.add_tool("jq")
    env.add_tool("gh")
    env.add_winget()
    git = shutil.which("git")
    assert git
    env.extra_path.append(str(Path(git).parent))
    repo = env.tmp / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    out = env.run(SESSION_START, stdin="{}", CLAUDE_PROJECT_DIR=str(repo))

    assert "uv 가 없어 winget 으로 설치했습니다" in out
    assert "현재 브랜치:" in out


def test_winget_이_계속_멈추면_상한에서_멈추고_다음_세션_재시도를_안내한다(env):
    env.add_winget()  # uv·jq·gh 모두 없다

    out = env.run(FAKE_WINGET_MODE="hang", HARNESS_TOOLS_BUDGET="3", HARNESS_INSTALL_TIMEOUT="2")

    # uv 첫 시도(2초) + 둘째 시도(남은 1초)에서 상한이 다 찬다. jq·gh 는 시도하지 않는다.
    assert len(env.winget_calls()) in (1, 2)
    assert "uv 설치가 도구 설치 시간 상한(3초)에 걸려" in out
    assert "jq 가 없지만 도구 설치에 쓸 시간(3초)을 넘겨 설치하지 않았습니다" in out
    assert "gh 가 없지만 도구 설치에 쓸 시간(3초)을 넘겨 설치하지 않았습니다" in out
    assert "다음: 다음 세션을 열면 자동으로 다시 시도합니다" in out
    assert "설치했습니다" not in out
    # 상한에 걸린 것은 실패 기록에 넣지 않는다 - 다음 세션에 바로 다시 시도한다.
    assert not (env.data / "tool-install-failures").exists()


def test_상한에_걸린_뒤에도_세션_시작_동기화와_지난_경고가_나온다(env):
    env.add_winget()
    git = shutil.which("git")
    assert git
    env.extra_path.append(str(Path(git).parent))
    repo = env.tmp / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / ".git" / "project-unfinished").write_text("지난 경고 내용\n", encoding="utf-8")

    out = env.run(
        SESSION_START,
        stdin="{}",
        CLAUDE_PROJECT_DIR=str(repo),
        FAKE_WINGET_MODE="hang",
        HARNESS_TOOLS_BUDGET="2",
        HARNESS_INSTALL_TIMEOUT="1",
    )

    # 시간은 초 단위(SECONDS)라 빠른 머신에서는 상한보다 한 번 시도의 시간 초과가 먼저 온다.
    # 이 테스트가 보는 것은 설치가 멈춰도 아래 동기화·경고가 나온다는 점이다.
    assert "도구 설치 시간 상한(2초)" in out or "설치하지 못했습니다(시간 초과)" in out
    assert "설치했습니다" not in out
    assert "지난 세션에서 남은 경고가 있습니다." in out
    assert "지난 경고 내용" in out
    assert "현재 브랜치:" in out
    assert "원격 저장소가 연결되어 있지 않습니다" in out


# --- gitleaks(#170) ---------------------------------------------------------


def test_gitleaks_가_없으면_winget_Gitleaks_Gitleaks_로_설치한다(env):
    for name in ("uv", "jq", "gh"):
        env.add_tool(name)
    (env.bin / "gitleaks").unlink()
    env.add_winget()

    out = env.run()

    calls = env.winget_calls()
    assert len(calls) == 1
    assert "install --id Gitleaks.Gitleaks -e --silent" in calls[0]
    assert "--scope user" in calls[0]
    assert "gitleaks 가 없어 winget 으로 설치했습니다" in out


def test_gitleaks_는_설치돼_있지만_PATH_밖이면_새로_열라고만_안내한다(env):
    for name in ("uv", "jq", "gh"):
        env.add_tool(name)
    (env.bin / "gitleaks").unlink()
    env.add_links_exe("gitleaks")
    env.add_winget()

    out = env.run()

    assert env.winget_calls() == []
    assert "gitleaks 는 설치돼 있지만 이 세션이 아직 못 찾습니다" in out


def test_gitleaks_도_끄는_변수와_수동_설치_안내를_따른다(env):
    for name in ("uv", "jq", "gh"):
        env.add_tool(name)
    (env.bin / "gitleaks").unlink()
    env.add_winget()

    out = env.run(HARNESS_NO_AUTO_INSTALL="1")

    assert env.winget_calls() == []
    assert "winget install --id Gitleaks.Gitleaks -e" in out
