"""현재 폴더(projectPath)에 설치된 harness 판을 installed_plugins.json 에서 읽는다(#404).

project 범위 설치는 폴더마다 항목이 따로 생긴다. `claude plugin update --scope project` 가
현재 폴더가 아닌 다른 폴더의 항목을 갱신한 일이 있어(2026-10-21), "갱신했다" 는 말이 아니라
**현재 폴더 항목의 version** 으로 판을 확인한다. 이 모듈은 그 확인만 한다 — 갱신·설치는 하지 않는다.

- 파일: `${CLAUDE_CONFIG_DIR:-~/.claude}/plugins/installed_plugins.json`
- 항목: `plugins["harness@blueward-harness"]` 목록에서 `scope` 가 project·local 이고 `projectPath` 가
  현재 폴더(또는 그 상위 폴더)와 같은 것. 경로는 `\\`·`/`, 끝 구분자, (Windows 에서) 대소문자 차이를 무시한다.
- 사용자 범위 항목은 현재 폴더 항목이 아니다 — `user_entry` 로 따로 알릴 뿐 판정에 쓰지 않는다.

**설치 항목이 아니라 "이 세션에 실제로 실린 판" 으로 판정한다**(#471, `--loaded-root`). 같은 저장소의 worktree 마다
project 항목이 따로 있으면 `claude plugin update --scope project` 가 cwd 가 아닌 다른 worktree 의 항목을 고르고,
세션도 그 항목의 판을 싣는다. 그래서 cwd 항목만 보면 실제로는 최신인데 stale 이라고 틀린다. 스킬 본문의
`${CLAUDE_PLUGIN_ROOT}`(훅은 환경변수 CLAUDE_PLUGIN_ROOT)가 실린 판 폴더이고, 거기의
`.claude-plugin/plugin.json` version 이 `loaded` 다. `--loaded-root` 가 주어지면 `state` 는 `loaded` 와 최신 판의
비교로 정하고, cwd 항목(`installed`, `project_path`, `other_project_entries`)과 같은 저장소의 다른 worktree 항목
(`same_repo_entries`)은 참고로만 낸다. `--loaded-root` 가 없으면 아래 옛 동작(cwd 항목 기준) 그대로다.

CLI: `python installed_version.py [--cwd DIR] [--plugin ID] [--loaded-root DIR] [--latest X.Y.Z | --remote]`
JSON 한 줄을 낸다. `state`:
- `current`  기준 판(`--loaded-root` 면 실린 판, 아니면 현재 폴더 항목)이 최신(또는 더 높음)
- `stale`    기준 판이 최신보다 낮다
- `missing`  현재 폴더 항목이 없다(설치가 필요. `--loaded-root` 없을 때만)
- `unknown`  최신 판을 알 수 없어 비교하지 못했다(항목 판은 `installed`, 실린 판은 `loaded` 에 있다)
- `unreadable` installed_plugins.json(`--loaded-root` 면 실린 판의 plugin.json, 사유는 `loaded_error`)을 읽지 못했다

`--all` 은 설치된 **모든 플러그인**의 표를 낸다(#461, `/harness:version`). 위 단일 판정과 별개의 모드다.
`[--cwd DIR] [--all [--json] [--remote] [--loaded-root DIR] [--all-entries]]` — 마크다운 표(`--json` 이면 JSON). 항목마다:
- 이 폴더 판: project·local 항목 중 projectPath 가 cwd(또는 상위)와 맞는 것. 없으면 user 항목.
  둘 다 있으면 project·local 을 고른다 — 공식 문서(plugins/loading)는 `enabledPlugins` 켜짐 여부의 우선순위
  (user < project < local)만 밝히고, 같은 플러그인이 두 범위에 설치됐을 때 어느 설치본이 실리는지는 적지 않았다.
  그래서 설정 우선순위를 따라 project·local 을 고르고, user 판은 `user_version` 으로 함께 보인다.
- 받아 둔 최신 판: 로컬 marketplace 사본(`known_marketplaces.json` 의 installLocation, 없으면
  `plugins/marketplaces/<이름>`)의 marketplace.json(+상대경로 source 의 plugin.json). 원격이 아니다.
  `--remote` 면 harness 만 원격 `v*` 태그로 바꾼다(실패하면 캐시 판).
- state: current / stale / missing(이 폴더에 설치 없음) / unknown(최신 판 또는 설치 판을 읽지 못함).
  `--loaded-root` 가 있으면 harness 행은 "이 세션에 실린 판" 으로 state 를 정한다(#471).
- 기본 표에서는 이 폴더에서 쓰이지 않는 플러그인(user 항목도, 이 폴더·같은 저장소 project 항목도 없는 것)을 뺀다.
  harness 는 설치가 없어도 남긴다(경고). 빠진 것까지 보려면 `--all-entries`.
- projectPath 폴더가 디스크에 없는 항목은 "다른 폴더 설치" 개수에서 뺀다.

stdlib 만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
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


def find_entries(data: dict, plugin_id: str, cwd: str, existing_only: bool = False) -> dict:
    """{"project": 현재 폴더 항목 또는 None, "user": 사용자 범위 항목 또는 None, "others": 다른 폴더 항목 수,
    "other_entries": 다른 폴더의 project·local 항목 목록}.

    cwd 자신과 일치하는 항목이 상위 폴더와 일치하는 항목보다 앞선다.
    `existing_only` 면 projectPath 폴더가 디스크에 없는 다른 폴더 항목은 세지도 목록에 넣지도 않는다.
    """
    entries = data.get("plugins", {}).get(plugin_id)
    entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    cands = _candidates(cwd)
    best, best_rank, user, others, other_entries = None, None, None, 0, []
    for entry in entries:
        scope = entry.get("scope")
        if scope in ("project", "local") and isinstance(entry.get("projectPath"), str):
            key = normalize_path(entry["projectPath"])
            if key in cands:
                rank = cands.index(key)
                if best_rank is None or rank < best_rank:
                    best, best_rank = entry, rank
                continue
            if existing_only and not _dir_exists(entry["projectPath"]):
                continue
            others += 1
            other_entries.append(entry)
        elif scope == "user":
            user = entry
        else:
            others += 1
    return {"project": best, "user": user, "others": others, "other_entries": other_entries}


def _dir_exists(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except OSError:
        return False


def _git_common_dir(folder: str) -> str | None:
    """folder 가 속한 저장소의 git common dir(정규화). worktree 들은 같은 값을 갖는다. 못 구하면 None."""
    try:
        done = subprocess.run(
            ["git", "-C", folder, "rev-parse", "--git-common-dir"],
            capture_output=True, timeout=10, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""
    if not text:
        return None
    path = Path(text)
    return normalize_path(str(path if path.is_absolute() else Path(folder) / path))


def same_repo_entries(other_entries: list[dict], cwd: str) -> list[dict]:
    """다른 폴더 항목 중 cwd 와 같은 저장소(git common dir 이 같음)의 것. [{"folder": 끝 폴더 이름, "version": 판}].

    판정에는 쓰지 않는 참고 정보다. 전체 경로는 내지 않는다(끝 폴더 이름만).
    """
    mine = _git_common_dir(cwd)
    if mine is None:
        return []
    out = []
    for entry in other_entries:
        path = entry.get("projectPath")
        if isinstance(path, str) and _dir_exists(path) and _git_common_dir(path) == mine:
            folder = normalize_path(path).rstrip("/").rsplit("/", 1)[-1]
            out.append({"folder": folder, "version": entry.get("version")})
    return out


def read_loaded(root: str) -> tuple[str | None, str | None]:
    """(실린 판 폴더의 plugin.json version, 못 읽은 사유)."""
    path = Path(root) / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"{path.name} 을 읽지 못했다({type(exc).__name__})"
    except ValueError:
        return None, f"{path.name} 이 JSON 이 아니다"
    version = data.get("version") if isinstance(data, dict) else None
    if parse_version(version) is None:
        return None, f"{path.name} 의 version 을 해석하지 못했다"
    return version, None


def _compare(have_text, want_text) -> str:
    have, want = parse_version(have_text), parse_version(want_text)
    if have is None or want is None:
        return "unknown"
    return "current" if have >= want else "stale"


def check(cwd: str, latest: str | None, env=None, plugin_id: str = PLUGIN_ID, loaded_root: str | None = None) -> dict:
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
    if loaded_root is not None:
        result.update({"loaded_root": str(loaded_root), "loaded": None, "loaded_error": None, "same_repo_entries": []})
    data = read_installed(env)
    entry = None
    if data is None:
        if loaded_root is None:
            result["state"] = "unreadable"
            return result
    else:
        found = find_entries(data, plugin_id, cwd)
        result["other_project_entries"] = found["others"]
        if found["user"]:
            result["user_entry"] = found["user"].get("version")
        entry = found["project"]
        if entry is not None:
            result["installed"] = entry.get("version")
            result["project_path"] = entry.get("projectPath")
        if loaded_root is not None:
            result["same_repo_entries"] = same_repo_entries(found["other_entries"], cwd)
    if loaded_root is not None:
        # 판정은 이 세션에 실린 판으로 한다. 항목 정보는 참고다(#471).
        result["loaded"], result["loaded_error"] = read_loaded(loaded_root)
        result["state"] = "unreadable" if result["loaded"] is None else _compare(result["loaded"], latest)
        return result
    if entry is None:
        result["state"] = "missing"
        return result
    have, want = parse_version(result["installed"]), parse_version(latest)
    if have is None:
        result["state"] = "unreadable"
    elif want is None:
        result["state"] = "unknown"
    else:
        result["state"] = "current" if have >= want else "stale"
    return result


# --- 모든 플러그인 표(#461) ---------------------------------------------------


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def known_latest(plugin_id: str, env=None) -> str | None:
    """로컬 marketplace 사본에 적힌 플러그인 판. 읽지 못하면 None(최신이라고 하지 않는다)."""
    name, _, market = plugin_id.partition("@")
    if not name or not market:
        return None
    root = config_dir(env) / "plugins" / "marketplaces" / market
    known = _read_json(config_dir(env) / "plugins" / "known_marketplaces.json")
    loc = known.get(market, {}).get("installLocation") if isinstance(known, dict) and isinstance(known.get(market), dict) else None
    if isinstance(loc, str) and loc:
        root = Path(loc)
    manifest = _read_json(root / ".claude-plugin" / "marketplace.json")
    plugins = manifest.get("plugins") if isinstance(manifest, dict) else None
    entry = next((p for p in plugins if isinstance(p, dict) and p.get("name") == name), None) if isinstance(plugins, list) else None
    if entry is None:
        return None
    if isinstance(entry.get("version"), str):
        return entry["version"]
    if isinstance(entry.get("source"), str):
        pj = _read_json(root / entry["source"] / ".claude-plugin" / "plugin.json")
        if isinstance(pj, dict) and isinstance(pj.get("version"), str):
            return pj["version"]
    return None




def all_plugins(
    cwd: str,
    env=None,
    remote_latest: str | None = None,
    loaded_root: str | None = None,
    all_entries: bool = False,
) -> dict:
    """{"cwd", "config_file", "rows": [...], "hidden": 뺀 줄 수, "loaded", "loaded_error", "error"}. 행은 플러그인마다 하나.

    `loaded_root` 가 있으면 harness 행의 state 를 이 세션에 실린 판으로 정한다(#471).
    기본은 이 폴더에서 쓰이지 않는 플러그인 줄을 뺀다(harness 는 남긴다). `all_entries` 면 모두 낸다.
    """
    out = {
        "cwd": str(cwd), "config_file": str(installed_plugins_path(env)), "rows": [], "hidden": 0,
        "loaded": None, "loaded_error": None, "error": None,
    }
    if loaded_root is not None:
        out["loaded"], out["loaded_error"] = read_loaded(loaded_root)
    data = read_installed(env)
    if data is None:
        out["error"] = "installed_plugins.json 을 읽지 못했다"
        return out
    for pid in sorted(data["plugins"]):
        found = find_entries(data, pid, cwd, existing_only=True)
        entry = found["project"] or found["user"]
        siblings = same_repo_entries(found["other_entries"], cwd) if found["other_entries"] else []
        if not all_entries and entry is None and not siblings and pid != PLUGIN_ID:
            out["hidden"] += 1
            continue
        latest, source = known_latest(pid, env), "cache"
        if pid == PLUGIN_ID and remote_latest:
            latest, source = remote_latest, "remote"
        row = {
            "plugin": pid,
            "scope": None if entry is None else ("user" if entry is found["user"] else entry.get("scope")),
            "installed": entry.get("version") if entry else None,
            "loaded": out["loaded"] if pid == PLUGIN_ID else None,
            "latest": latest,
            "latest_source": source if latest else None,
            "user_version": found["user"].get("version") if found["user"] and found["project"] else None,
            "other_project_entries": found["others"],
            "same_repo_entries": siblings,
            "no_entry": entry is None,
        }
        if pid == PLUGIN_ID and loaded_root is not None:
            row["state"] = "unknown" if out["loaded"] is None else _compare(out["loaded"], latest)
        elif entry is None:
            row["state"] = "missing"
        else:
            row["state"] = _compare(row["installed"], latest)
        out["rows"].append(row)
    return out


_STATE_TEXT = {"current": "최신", "stale": "갱신 있음", "missing": "이 폴더에 설치 없음", "unknown": "최신 판 확인 불가"}


def render_table(result: dict) -> str:
    lines = [f"기준 폴더: {result['cwd']}", f"설치 목록: {result['config_file']}", ""]
    if result["error"]:
        return "\n".join(lines + [f"확인 불능: {result['error']}"])
    lines += [
        "| 플러그인 | 범위 | 이 폴더 판 | 이 세션에 실린 판 | 받아 둔 최신 판 | 상태 | 다른 폴더 설치 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        scope = r["scope"] or "-"
        if r["user_version"]:
            scope += f" (user {r['user_version']} 도 있음)"
        latest = (r["latest"] or "?") + (" (원격)" if r["latest_source"] == "remote" else "")
        others = f"{r['other_project_entries']}곳" if r["other_project_entries"] else "-"
        if r["same_repo_entries"]:
            same = ", ".join(f"{e['folder']} {e['version'] or '?'}" for e in r["same_repo_entries"])
            others += f" (같은 저장소: {same})"
        state = _STATE_TEXT[r["state"]]
        if r["loaded"] and r["state"] != "missing" and r["no_entry"]:
            state += " (이 폴더 설치 항목은 없음)"
        lines.append(
            f"| {r['plugin']} | {scope} | {r['installed'] or '-'} | {r['loaded'] or '-'} | {latest} | {state} | {others} |"
        )
    lines += ["", '- "받아 둔 최신 판" 은 마지막 `claude plugin marketplace update` 때 내려받은 사본의 판이다(원격 최신과 다를 수 있다).',
              '- "이 세션에 실린 판" 은 지금 세션이 실제로 쓰는 harness 판이고, harness 의 상태는 이것으로 정한다. "이 폴더 판" 은 설치 항목이라 참고다(#471).',
              "- 이 세션이 쓰는 판은 설치 뒤 `/reload-plugins` 를 해야 바뀐다."]
    if result["hidden"]:
        lines.append(f"- 이 폴더에서 쓰이지 않는 플러그인 {result['hidden']}개는 뺐다(`--all-entries` 로 모두 본다).")
    if result.get("loaded_error"):
        lines.append(f"- 실린 판을 읽지 못했다: {result['loaded_error']}")
    return "\n".join(lines)


def _remote_latest() -> str | None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import update_notice  # noqa: PLC0415 - 같은 폴더의 훅 모듈

    return update_notice.latest_version(update_notice.ls_remote_tags())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", default=os.getcwd())
    parser.add_argument("--plugin", default=PLUGIN_ID)
    parser.add_argument("--loaded-root", help="이 세션에 실린 플러그인 폴더(스킬 본문의 ${CLAUDE_PLUGIN_ROOT}). 판정의 기준(#471)")
    parser.add_argument("--all", action="store_true", help="설치된 모든 플러그인의 표(#461)")
    parser.add_argument("--json", action="store_true", help="--all 의 출력을 JSON 으로")
    parser.add_argument("--all-entries", action="store_true", help="--all 에서 이 폴더에서 쓰이지 않는 플러그인 줄도 보인다")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--latest", help="비교할 최신 판(예: 0.10.99)")
    group.add_argument("--remote", action="store_true", help="원격 v* 태그 중 가장 큰 판과 비교")
    args = parser.parse_args(argv)
    if (args.json or args.all_entries) and not args.all:
        parser.error("--json, --all-entries 는 --all 과 함께 쓴다")
    if args.all and args.latest:
        parser.error("--all 은 --latest 와 함께 쓰지 않는다")
    for stream in (sys.stdout,):
        stream.reconfigure(encoding="utf-8")
    if args.all:
        result = all_plugins(
            args.cwd,
            remote_latest=_remote_latest() if args.remote else None,
            loaded_root=args.loaded_root,
            all_entries=args.all_entries,
        )
        sys.stdout.write((json.dumps(result, ensure_ascii=False) if args.json else render_table(result)) + "\n")
        return 0
    latest = args.latest
    if args.remote:
        latest = _remote_latest()
    result = check(args.cwd, latest, plugin_id=args.plugin, loaded_root=args.loaded_root)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
