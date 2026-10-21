"""현재 폴더(projectPath)에 설치된 harness 판을 installed_plugins.json 에서 읽는다(#404).

project 범위 설치는 폴더마다 항목이 따로 생긴다. `claude plugin update --scope project` 가
현재 폴더가 아닌 다른 폴더의 항목을 갱신한 일이 있어(2026-10-21), "갱신했다" 는 말이 아니라
**현재 폴더 항목의 version** 으로 판을 확인한다. 이 모듈은 그 확인만 한다 — 갱신·설치는 하지 않는다.

- 파일: `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json`
- 항목: `plugins["harness@blueward-harness"]` 목록에서 `scope` 가 project·local 이고 `projectPath` 가
  현재 폴더(또는 그 상위 폴더)와 같은 것. 경로는 `\\`·`/`, 끝 구분자, (Windows 에서) 대소문자 차이를 무시한다.
- 사용자 범위 항목은 현재 폴더 항목이 아니다 — `user_entry` 로 따로 알릴 뿐 판정에 쓰지 않는다.

CLI: `python installed_version.py [--cwd DIR] [--plugin ID] [--latest X.Y.Z | --remote]`
JSON 한 줄을 낸다. `state`:
- `current`  현재 폴더 항목이 최신(또는 더 높음)
- `stale`    현재 폴더 항목이 최신보다 낮다
- `missing`  현재 폴더 항목이 없다(설치가 필요)
- `unknown`  최신 판을 알 수 없어 비교하지 못했다(항목 판은 `installed` 에 있다)
- `unreadable` installed_plugins.json 을 읽지 못했다

stdlib 만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ID = "harness@blueward-harness"
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:/")


def parse_version(text) -> tuple[int, ...] | None:
    if not isinstance(text, str) or not _VERSION_RE.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split("."))


def normalize_path(path: str) -> str:
    """`\\`→`/`, 끝 `/` 제거, `..`·`.` 정리, Windows 경로(드라이브 문자)나 Windows 실행이면 소문자로."""
    text = str(path).replace("\\", "/")
    drive = _DRIVE_RE.match(text) is not None
    prefix = "//" if text.startswith("//") else ""
    parts: list[str] = []
    for piece in text.split("/"):
        if piece in ("", "."):
            continue
        if piece == ".." and parts and parts[-1] != "..":
            parts.pop()
            continue
        parts.append(piece)
    lead = "/" if text.startswith("/") and not prefix else prefix
    out = lead + "/".join(parts)
    return out.lower() if drive or os.name == "nt" else out


def config_dir(env=None) -> Path:
    env = os.environ if env is None else env
    text = env.get("CLAUDE_CONFIG_DIR")
    return Path(text) if text else Path.home() / ".claude"


def installed_plugins_path(env=None) -> Path:
    return config_dir(env) / "plugins" / "installed_plugins.json"


def read_installed(env=None) -> dict | None:
    """파싱한 installed_plugins.json, 읽지 못하면 None."""
    try:
        data = json.loads(installed_plugins_path(env).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("plugins"), dict) else None


def _candidates(cwd: str) -> list[str]:
    """cwd 와 그 상위 폴더(가까운 순)를 정규화한 목록."""
    here = normalize_path(cwd)
    out = [here]
    while True:
        parent = here.rsplit("/", 1)[0]
        if parent == here or not parent or parent.endswith(":") or parent in out:
            break  # 루트·드라이브에서 멈춘다
        out.append(parent)
        here = parent
    return out


def find_entries(data: dict, plugin_id: str, cwd: str) -> dict:
    """{"project": 현재 폴더 항목 또는 None, "user": 사용자 범위 항목 또는 None, "others": 다른 폴더 항목 수}.

    cwd 자신과 일치하는 항목이 상위 폴더와 일치하는 항목보다 앞선다.
    """
    entries = data.get("plugins", {}).get(plugin_id)
    entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    cands = _candidates(cwd)
    best, best_rank, user, others = None, None, None, 0
    for entry in entries:
        scope = entry.get("scope")
        if scope in ("project", "local") and isinstance(entry.get("projectPath"), str):
            key = normalize_path(entry["projectPath"])
            if key in cands:
                rank = cands.index(key)
                if best_rank is None or rank < best_rank:
                    best, best_rank = entry, rank
                continue
            others += 1
        elif scope == "user":
            user = entry
        else:
            others += 1
    return {"project": best, "user": user, "others": others}


def check(cwd: str, latest: str | None, env=None, plugin_id: str = PLUGIN_ID) -> dict:
    result = {
        "plugin": plugin_id,
        "cwd": str(cwd),
        "config_file": str(installed_plugins_path(env)),
        "installed": None,
        "project_path": None,
        "latest": latest,
        "user_entry": None,
        "other_project_entries": 0,
    }
    data = read_installed(env)
    if data is None:
        result["state"] = "unreadable"
        return result
    found = find_entries(data, plugin_id, cwd)
    result["other_project_entries"] = found["others"]
    if found["user"]:
        result["user_entry"] = found["user"].get("version")
    entry = found["project"]
    if entry is None:
        result["state"] = "missing"
        return result
    result["installed"] = entry.get("version")
    result["project_path"] = entry.get("projectPath")
    have, want = parse_version(result["installed"]), parse_version(latest)
    if have is None:
        result["state"] = "unreadable"
    elif want is None:
        result["state"] = "unknown"
    else:
        result["state"] = "current" if have >= want else "stale"
    return result


def _remote_latest() -> str | None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import update_notice  # noqa: PLC0415 - 같은 폴더의 훅 모듈

    return update_notice.latest_version(update_notice.ls_remote_tags())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--plugin", default=PLUGIN_ID)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--latest", help="비교할 최신 판(예: 0.10.99)")
    group.add_argument("--remote", action="store_true", help="원격 v* 태그 중 가장 큰 판과 비교")
    args = parser.parse_args(argv)
    for stream in (sys.stdout,):
        stream.reconfigure(encoding="utf-8")
    latest = args.latest
    if args.remote:
        latest = _remote_latest()
    sys.stdout.write(json.dumps(check(args.cwd, latest, plugin_id=args.plugin), ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
