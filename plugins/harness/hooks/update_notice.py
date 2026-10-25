"""세션 중간에 플러그인이 옛 판이면 Claude 가 한 번 알리게 한다(#314).

Claude Code 자동 업데이트는 세션 첫 메시지 뒤에 한 번만 확인하므로, 오래 열어 둔 세션은
그 뒤에 나온 판을 모른다. 타이머 이벤트가 없어 `UserPromptSubmit` 에서 확인한다. 이 이벤트의
출력은 사용자 화면이 아니라 Claude 컨텍스트로 가므로 `additionalContext` 로 "사용자에게
알려라" 고 시킨다. 갱신은 사용자가 스스로 결정한다 — 훅도 Claude 도 대신 실행하지 않는다
(사용자가 `/harness:update` 를 직접 부르면 그 스킬이 실행한다, #404).

- 현재 판: `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` 의 version — 이 세션에 실제로 실린 판이다.
  뒤처졌는지는 설치 항목(cwd 의 projectPath)이 아니라 이 판으로 정한다(#471). 설치 항목은 안내 문구를
  고르는 참고로만 쓴다.
- 최신 판: 원격의 `v*` 태그 중 가장 큰 것(`git ls-remote --tags`, 5초 제한). 결과(실패 포함)는
  `${CLAUDE_PLUGIN_DATA}` 에 캐시해 10분에 한 번만 묻는다.
- 같은 세션에서 같은 최신 판은 한 번만 알린다.
- 이 안내는 검사가 아니다. 네트워크·git·파싱·권한 등 무엇이 실패하든 출력 없이 exit 0 으로
  끝내 프롬프트를 막거나 늦추지 않는다.
- 플러그인 저장소 자신(꼭대기에 `.claude-plugin/marketplace.json`)과
  `HARNESS_NO_UPDATE_NOTICE=1` 에서는 말하지 않는다.

stdlib 만 쓴다 — 훅은 프로젝트 의존성 없이 `uv run --no-project` 로 돈다.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

REMOTE_URL = "https://github.com/jaeheeMin/blueward-harness.git"
CACHE_SECONDS = 600
LS_REMOTE_TIMEOUT = 5
MAX_NOTIFIED = 20

_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_TAG_RE = re.compile(r"^v([0-9]+(?:\.[0-9]+)*)$")


def parse_version(text: str) -> tuple[int, ...] | None:
    if not isinstance(text, str) or not _VERSION_RE.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split("."))


def _kill_tree(proc: subprocess.Popen) -> None:
    """git.exe 만 죽고 git-remote-https 가 파이프를 쥐는 경우가 있어 프로세스 트리째 끝낸다."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=3, stdin=subprocess.DEVNULL,
            )
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def ls_remote_tags(url: str = REMOTE_URL, timeout: float = LS_REMOTE_TIMEOUT) -> str | None:
    """원격 `v*` 태그 목록의 원문. 어떤 이유로든 못 얻으면 None."""
    cmd = ["git", "-c", "http.lowSpeedLimit=1", "-c", "http.lowSpeedTime=4",
           "ls-remote", "--tags", url, "v*"]
    extra = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, **extra,
        )
    except (OSError, ValueError):
        return None
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)  # 죽인 뒤에는 파이프를 다시 기다리지 않는다
        return None
    except OSError:
        _kill_tree(proc)
        return None
    return out.decode("utf-8", errors="replace") if proc.returncode == 0 else None


def latest_version(ls_remote_output: str | None) -> str | None:
    best: tuple[int, ...] | None = None
    for line in (ls_remote_output or "").splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[1].startswith("refs/tags/"):
            continue
        name = parts[1][len("refs/tags/"):]
        if name.endswith("^{}"):
            name = name[:-3]
        match = _TAG_RE.fullmatch(name)
        parsed = parse_version(match.group(1)) if match else None
        if parsed is not None and (best is None or parsed > best):
            best = parsed
    return ".".join(map(str, best)) if best else None


def _is_plugin_repo(cwd: str | None) -> bool:
    """cwd 에서 위로 올라가며 git 꼭대기까지 보아 marketplace.json 이 있는지."""
    if not cwd:
        return False
    here = Path(cwd).resolve()
    for folder in (here, *here.parents):
        if (folder / ".claude-plugin" / "marketplace.json").is_file():
            return True
        if (folder / ".git").exists():
            return False
    return False


def _read_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _data_dir(env: dict) -> Path:
    data = env.get("CLAUDE_PLUGIN_DATA")
    return Path(data) if data else Path(tempfile.gettempdir()) / "harness-update-notice"


def _project_has_latest(latest: str, cwd: str | None, env: dict) -> bool:
    """현재 폴더의 설치 항목(installed_plugins.json)이 이미 최신 판인지.

    캐시 폴더 `.../harness/<latest>` 가 있다는 것만으로는 알 수 없다 — 다른 폴더의 project 범위
    설치가 먼저 받아 둔 것일 수 있어, 그 폴더가 아닌 이 폴더에는 `/reload-plugins` 가 새 판을 싣지 못한다(#404).
    항목을 못 읽거나 없으면 False(갱신 명령을 안내한다).
    """
    if not cwd:
        return False
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import installed_version  # noqa: PLC0415 - 같은 폴더의 모듈

        return installed_version.check(cwd, latest, env)["state"] == "current"
    except Exception:  # noqa: BLE001 - 안내일 뿐이다
        return False


def _message(current: str, latest: str, has_latest: bool) -> str:
    if has_latest:
        how = (
            "이 폴더의 설치는 이미 새 판이라 `/reload-plugins` 를 입력하면 된다. "
            "`/reload-plugins` 뒤에도 판이 그대로면 `/harness:update` 를 입력하거나 업데이트 명령 "
            "(`claude plugin marketplace update blueward-harness` 와 "
            "`claude plugin update harness@blueward-harness --scope project`)을 실행한다."
        )
    else:
        how = (
            "`/harness:update` 를 입력하면 현재 폴더 기준으로 갱신하고 확인한다. 또는 터미널에서 "
            "`claude plugin marketplace update blueward-harness` 와 "
            "`claude plugin update harness@blueward-harness --scope project` 를 차례로 실행한다"
            "(같은 저장소의 worktree 가 여러 개면 다른 worktree 의 항목이 갱신될 수 있어, 갱신됐는지는 "
            "설치 목록이 아니라 `/reload-plugins` 뒤 이 세션에 실린 판으로 본다 — `/harness:update` 가 그렇게 확인한다, #471). "
            "어느 쪽이든 끝나면 `/reload-plugins` 를 입력한다."
        )
    return (
        f"[harness 플러그인 갱신 안내] 새 판 {latest} 이(가) 나왔고 지금 세션은 {current} 판이다. "
        "이번 답변의 첫 줄에, 사용자에게 이 사실과 갱신 방법을 한 번만 짧게 알려라: "
        f"{how} "
        "갱신할지는 사용자가 직접 정한다. 사용자가 `/harness:update` 를 부르기 전에는 대신 실행하지 말고, 묻기 전에는 다시 꺼내지 마라."
    )


def run(
    payload: dict,
    env: dict | None = None,
    ls_remote: Callable[[], str | None] = ls_remote_tags,
    now: Callable[[], float] = time.time,
) -> str | None:
    """출력할 JSON 문자열, 말할 것이 없으면 None."""
    env = os.environ if env is None else env
    if env.get("HARNESS_NO_UPDATE_NOTICE") == "1" or _is_plugin_repo(payload.get("cwd")):
        return None

    root_text = env.get("CLAUDE_PLUGIN_ROOT")
    plugin_root = Path(root_text) if root_text else Path(__file__).resolve().parent.parent
    try:
        current = json.loads((plugin_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    current_v = parse_version(current)
    if current_v is None:
        return None

    state_path = _data_dir(env) / "update-notice.json"
    state = _read_state(state_path)

    checked_at = state.get("checked_at")
    fresh = isinstance(checked_at, (int, float)) and 0 <= now() - checked_at < CACHE_SECONDS
    if fresh:
        latest = state.get("latest")
    else:
        # 조회 전에 먼저 저장한다 — 훅이 조회 중 강제 종료돼도 10분 동안은 다시 묻지 않는다.
        state["checked_at"] = now()
        state["latest"] = None
        _write_state(state_path, state)
        latest = latest_version(ls_remote())
        state["latest"] = latest  # 실패(None)도 캐시해 오프라인에서 매 프롬프트마다 기다리지 않는다
        _write_state(state_path, state)

    latest_v = parse_version(latest) if isinstance(latest, str) else None
    if latest_v is None or latest_v <= current_v:
        return None

    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        return None
    notified = state.get("notified")
    if not isinstance(notified, dict):
        notified = {}
    if notified.get(session) == latest:
        return None
    notified.pop(session, None)
    notified[session] = latest
    state["notified"] = dict(list(notified.items())[-MAX_NOTIFIED:])
    _write_state(state_path, state)

    return json.dumps(
        {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _message(current, latest, _project_has_latest(latest, payload.get("cwd"), env)),
        }},
        ensure_ascii=False,
    )


def main() -> int:
    try:
        for stream in (sys.stdin, sys.stdout):
            stream.reconfigure(encoding="utf-8")
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        out = run(payload)
        if out:
            sys.stdout.write(out + "\n")
    except Exception:  # noqa: BLE001 - 안내일 뿐이라 어떤 실패도 프롬프트를 막지 않는다
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
