"""바탕화면 바로가기가 실행하는 작은 런처. 표준 라이브러리만 쓴다(#866).

`shortcut.py` 가 이 파일을 판과 무관한 폴더(`<설정 폴더>/harness-console/launcher/`)에 복사해 두고, 바로가기는 그 복사본을 부른다.
플러그인이 새 판으로 갱신돼 캐시 폴더 이름(`.../harness/<판>/`)이 바뀌어도 바로가기는 그대로이고,
이 런처가 누르는 순간 지금 설치된 가장 높은 판의 `console/open.py` 를 찾아 실행한다. open.py 가 서버를 띄우고 인증된 브라우저를 연다.
창이 없으므로 실패하면 메시지 상자로 이유를 보여 준다(조용히 사라지지 않게).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

MARKETPLACE = "blueward-harness"
PLUGIN = "harness"
TITLE = "Blueward Harness"


def config_dir(env=None) -> Path:
    env = os.environ if env is None else env
    base = env.get("CLAUDE_CONFIG_DIR")
    return Path(base) if base else Path.home() / ".claude"


def version_key(name: str) -> tuple[int, ...] | None:
    """"0.10.247" -> (0, 10, 247). 숫자 점 표기가 아니면 None."""
    parts = name.split(".")
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


def find_latest_open(config: Path | None = None) -> Path | None:
    """설치 캐시에서 가장 높은 판의 console/open.py. 없으면 None."""
    base = (config or config_dir()) / "plugins" / "cache" / MARKETPLACE / PLUGIN
    best: tuple[tuple[int, ...], Path] | None = None
    try:
        entries = list(base.iterdir())
    except OSError:
        return None
    for entry in entries:
        key = version_key(entry.name)
        target = entry / "console" / "open.py"
        if key is None or not target.is_file():
            continue
        if best is None or key > best[0]:
            best = (key, target)
    return best[1] if best else None


def message_box(text: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)
    except (AttributeError, OSError):
        print(text)


def main() -> int:
    open_py = find_latest_open()
    if open_py is None:
        message_box("하네스 플러그인을 찾지 못했어요. Claude Code 에서 /harness:update 를 실행한 뒤 다시 눌러 주세요.")
        return 1
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    try:
        done = subprocess.run([sys.executable, str(open_py), "--from-shortcut"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        message_box(f"웹 콘솔을 열지 못했어요: {exc}")
        return 1
    if done.returncode != 0:
        message_box((done.stdout or done.stderr or "웹 콘솔을 열지 못했어요.").strip()[:600])
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
