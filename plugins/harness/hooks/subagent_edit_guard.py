"""서브에이전트가 Edit/Write 밖(Bash·PowerShell 스크립트)에서 파일을 고치면 멈추지 못하게 한다(#601).

스크립트로 고치면 Write/Edit 에 걸린 훅(코드 규칙 검사 등)이 돌지 않는다. 지시문에 "Edit/Write 로만
고친다" 를 적어도 지켜지지 않아 코드로 막는다. 이벤트마다 한 스크립트를 나눠 쓴다(`argv[1]`).

- `pre`     — PreToolUse(Write|Edit|NotebookEdit). 고치기 직전 해시와 "이미 git 상태에 변경으로 잡혔는가" 를
              `pre.<tool_use_id>.json` 에 적는다.
- `record`  — PostToolUse(Write|Edit|NotebookEdit). 고친 파일의 경로, 직전(pre)·직후(post) 해시를 적는다.
              서브에이전트(`agent_id` 있음)든 메인 세션이든 모두 적는다(다른 사람의 편집을 "설명된 변경" 으로
              쳐 잘못 막는 일을 줄이기 위해서다).
- `start`   — SubagentStart. 그 시점의 작업 트리(`git status --porcelain` 경로와 각 파일 내용 해시)와 HEAD 를 저장.
              세션 폴더만이 아니라 같은 저장소의 모든 worktree(`git worktree list`)를 담는다(#829).
              목록을 못 읽으면 세션 폴더만 담고 stop 이 "확인 못 함" 으로 알린다.
- `prompt`  — PreToolUse(Agent|Task). 넘기는 프롬프트에 경로가 나온 worktree 를 세션 기록에 남긴다.
- `bash`    — PreToolUse(Bash|PowerShell). 서브에이전트의 명령·cwd 에 경로가 나온 worktree 를 그 에이전트에 연결한다.
              막는 판정은 연결된 트리(세션 폴더, prompt·bash·Edit/Write 로 이어진 worktree)에만 한다 — 같은 저장소의
              다른 세션이 일하는 worktree 변경을 탓하지 않기 위해서다. 연결된 트리의 다른 세션 Edit/Write 기록도 읽는다.
- `stop`    — SubagentStop. 연결된 worktree 의 지금 상태와 기준을 비교해 "도는 동안 바뀐 파일" 을 구한다. 파일마다
              기준 해시 -> pre -> post -> pre -> post ... -> 현재 내용 사슬이 끊김 없이 이어질 때만 "설명된
              변경" 으로 보고, 아니면 `decision: block` 으로 다시 고치게 한다. Write 는 파일 전체를 새로 쓰므로
              사슬을 다시 시작시킨다. 막힌 뒤에 그 파일을 다시 쓴 기록도 같다(막힌 사실을 알고 고친 것).
- `inject`  — PostToolUse(Agent|Task), 메인 세션에서만. 서브에이전트 점검이 남긴 경고(`pending-warnings`)를
              `additionalContext` 로 메인 모델에 한 번 주입하고 비운다. `systemMessage` 는 사용자 화면 전용이라
              메인 모델이 모르기 때문이다.

**기록 위치.** 세션 폴더의 `<git 디렉터리>/harness-subagent-guard/`. git 이 추적하지 않고 worktree 별로 갈린다.
Edit/Write 로 고친 파일이 다른 worktree·저장소에 있어도 기록은 이 한 곳에 모으되, 해시와 상대 경로는 그
파일이 속한 작업 트리 기준이다(`pre`/`record`). 시작 때 기준이 없던 작업 트리는 서브에이전트가 거기를 처음
Edit/Write 하기 직전에 기준을 더한다(그 전의 스크립트 수정은 못 본다).

**무한 반복 방지.** 같은 `agent_id` 가 `MAX_BLOCKS` 번 막힌 뒤에는 더 막지 않고 통과시키며 메인 세션에 경고한다.

**검사 불능.** git 저장소가 아니거나, 기준이 없거나, 읽기에 실패하면 막지 않고 "확인 못 함" 경고만 낸다.
통과·위반으로 뭉개지 않는다(CLAUDE.md 원칙 7). 어떤 경우에도 종료 코드는 0 이다(SubagentStop 에서 2 는
멈추지 못하게 하므로, 훅 오류가 서브에이전트를 가두면 안 된다).

stdlib 만 쓴다 — 훅은 `uv run --no-project` 로 실행된다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import console_block  # noqa: E402

MAX_BLOCKS = 2
STATE_DIRNAME = "harness-subagent-guard"
PENDING = "pending-warnings"
NO_START = "pending-no-start"
KEEP_SECONDS = 7 * 24 * 3600
STALE_ACTIVE_SECONDS = 3600  # 끝났다는 기록 없이 이만큼 지난 서브에이전트는 겹침 판정에서 뺀다
PROMPT_WINDOW_SECONDS = 900  # 서브에이전트 시작 이만큼 전부터 넘긴 프롬프트에 나온 worktree 를 연결한다
GIT_TIMEOUT = 20
MISSING = "-"  # 파일이 없거나 디렉터리


class Unavailable(Exception):
    """판정할 수 없다(통과도 위반도 아니다)."""


def _force_utf8_io() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def warn(message: str, state: Path | None = None) -> None:
    """사용자에게 `systemMessage` 로 보이고, 상태 폴더를 알면 메인 모델용으로도 남긴다."""
    print(message, file=sys.stderr)
    emit({"systemMessage": message})
    if state is not None:
        remember(state, message)


def remember(state: Path, message: str) -> None:
    """메인 모델에게 주입할 경고로 남긴다(`inject` 가 비운다)."""
    try:
        state.mkdir(parents=True, exist_ok=True)
        with open(state / PENDING, "a", encoding="utf-8") as fh:
            fh.write(message.replace("\n", " / ") + "\n")
    except OSError:
        pass


def note_no_start(state: Path, session: str, agent: str) -> None:
    """시작 기록 없는 에이전트는 메인 모델에게 개별 경고 대신 묶어 알린다(#690). 같은 세션·id 는 한 번만 남긴다."""
    line = f"{session}\t{agent}"
    path = state / NO_START
    try:
        state.mkdir(parents=True, exist_ok=True)
        if path.exists() and line in path.read_text(encoding="utf-8").splitlines():
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


# ---- git / 해시 ------------------------------------------------------------

def _git(cwd: str, *args: str) -> bytes:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, timeout=GIT_TIMEOUT, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unavailable(f"git 을 실행하지 못했다({type(exc).__name__})") from exc
    if done.returncode != 0:
        raise Unavailable("git 저장소가 아니거나 git 이 실패했다")
    return done.stdout


def repo_paths(cwd: str) -> tuple[str, Path]:
    """(작업 트리 최상위, 상태 폴더)."""
    top = _git(cwd, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()
    gitdir = _git(cwd, "rev-parse", "--absolute-git-dir").decode("utf-8", "replace").strip()
    if not top or not gitdir:
        raise Unavailable("git 경로를 알 수 없다")
    return top, Path(gitdir) / STATE_DIRNAME


def head_of(top: str) -> str | None:
    try:
        return _git(top, "rev-parse", "HEAD").decode("ascii", "replace").strip() or None
    except Unavailable:
        return None  # 커밋이 아직 없는 저장소


def nk(rel: str) -> str:
    return os.path.normcase(rel.replace("\\", "/"))


def hash_file(top: str, rel: str) -> str:
    path = os.path.join(top, rel)
    if not os.path.isfile(path):
        return MISSING
    digest = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status_paths(top: str, only: str | None = None) -> list[str]:
    args = ["status", "--porcelain", "-z", "-uall"]
    if only is not None:
        args += ["--", only]
    entries = _git(top, *args).split(b"\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code = entry[:2].decode("ascii", "replace")
        paths.append(entry[3:].decode("utf-8", "replace"))
        if "R" in code or "C" in code:  # 다음 항목이 원래 경로
            if i < len(entries) and entries[i]:
                paths.append(entries[i].decode("utf-8", "replace"))
            i += 1
    return paths


def snapshot(top: str, extra: list[str] | None = None) -> tuple[dict[str, str], list[str]]:
    """{상대경로: 해시}, 읽지 못한 경로 목록."""
    result: dict[str, str] = {}
    unreadable: list[str] = []
    seen: set[str] = set()
    for rel in [*status_paths(top), *(extra or [])]:
        if nk(rel) in seen:
            continue
        seen.add(nk(rel))
        try:
            result[rel] = hash_file(top, rel)
        except OSError:
            unreadable.append(rel)
    return result, unreadable


def rel_of(top: str, file_path: str) -> str | None:
    try:
        rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(top))
    except ValueError:  # 다른 드라이브
        return None
    rel = rel.replace("\\", "/")
    if rel == ".." or rel.startswith("../"):
        return None
    return rel


def tkey(top: str) -> str:
    """작업 트리를 가리키는 비교용 키."""
    return nk(os.path.realpath(top))


def list_worktrees(top: str) -> list[str]:
    """같은 저장소의 모든 worktree 경로(`git worktree list --porcelain`). 디렉터리가 사라진 것(prunable)과
    작업 트리가 없는 bare 항목은 고칠 수 없으니 뺀다."""
    text = _git(top, "worktree", "list", "--porcelain").decode("utf-8", "replace")
    paths: list[str] = []
    current: str | None = None
    skip = False
    for line in [*text.splitlines(), ""]:
        if line.startswith("worktree "):
            current, skip = line[len("worktree "):], False
        elif line == "bare" or line.startswith("prunable"):
            skip = True
        elif line == "":
            if current is not None and not skip:
                paths.append(current)
            current = None
    return paths


def snapshot_tree(top: str) -> dict:
    base, unreadable = snapshot(top)
    return {"top": top, "baseline": base, "unreadable": unreadable, "head": head_of(top)}


def take_trees(top: str) -> tuple[dict[str, dict], list[str]]:
    """세션 폴더의 작업 트리와 같은 저장소의 모든 worktree 의 기준. ({키: 기준}, 확인 못 한 사유 목록)"""
    problems: list[str] = []
    try:
        tops = list_worktrees(top)
    except Unavailable as exc:
        problems.append(f"worktree 목록을 읽지 못해 세션 폴더 밖 worktree 는 볼 수 없다({exc})")
        tops = []
    if tkey(top) not in {tkey(t) for t in tops}:
        tops.insert(0, top)
    trees: dict[str, dict] = {}
    for item in tops:
        try:
            trees[tkey(item)] = snapshot_tree(item)
        except (Unavailable, OSError) as exc:
            problems.append(f"{item} 의 기준을 찍지 못했다({exc})")
    return trees, problems


# ---- 상태 파일 --------------------------------------------------------------

def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)[:80] or "x"


def agent_file(state: Path, session: str, agent: str) -> Path:
    return state / f"{safe(session)}.{safe(agent)}.agent.json"


def edits_file(state: Path, session: str, actor: str) -> Path:
    return state / f"{safe(session)}.{safe(actor)}.edits.jsonl"


def prompts_file(state: Path, session: str) -> Path:
    return state / f"prompts.{safe(session)}.jsonl"


def pre_file(state: Path, tool_use_id: str) -> Path:
    return state / f"pre.{safe(tool_use_id)}.json"


def save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def prune(state: Path) -> None:
    cutoff = time.time() - KEEP_SECONDS
    for item in state.iterdir():
        if item.name in (PENDING, NO_START):
            continue
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


def row_key(tree_key: str, rel: str) -> str:
    return tree_key + "\0" + nk(rel)


def read_rows(state: Path, since: float, default_tree: str) -> dict[str, list[dict]]:
    """`since` 이후의 Edit/Write 기록. 모든 세션·행위자를 모아 {row_key(작업 트리, 경로): 시각순 행}.
    작업 트리 키(`r`)가 없는 옛 행은 `default_tree` 로 본다.

    마지막으로 쓰인 시각이 `since` 이전인 기록 파일은 열지 않는다(읽는 양을 줄인다).
    """
    found: dict[str, list[dict]] = {}
    for item in state.glob("*.edits.jsonl"):
        try:
            if item.stat().st_mtime < since:
                continue
            lines = item.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise Unavailable(f"편집 기록을 읽지 못했다({type(exc).__name__})") from exc
        for line in lines:
            try:
                row = json.loads(line)
                if float(row["t"]) < since:
                    continue
                found.setdefault(row_key(row.get("r") or default_tree, row["p"]), []).append(row)
            except (ValueError, KeyError, TypeError):
                continue  # 깨진 한 줄은 건너뛴다(그 파일은 기록 없음으로 취급)
    for rows in found.values():
        rows.sort(key=lambda r: r["t"])
    return found


def explained(base_hash: str | None, rows: list[dict], cur: str, blocked_at: float | None) -> bool:
    """기준 해시 -> (pre -> post)* -> 현재 내용이 끊김 없이 이어지는가.

    `base_hash` 가 None 이면 기준 시점에 변경 없던 파일(HEAD 와 같다)이다. 그 파일의 첫 편집 직전에
    이미 변경으로 잡혀 있었다면(`d`) 편집 밖에서 먼저 고쳐진 것이다. `pre` 가 없는 행(pre 훅이 못 돈 경우)은
    그 고리만 확인하지 않는다(판정 불능을 위반으로 만들지 않는다).
    """
    prev = base_hash
    ok = True
    for row in rows:
        if row.get("w") or (blocked_at is not None and row["t"] > blocked_at):
            ok = True  # Write 는 파일 전체를 새로 쓴다 / 막힌 뒤에 알고 다시 쓴 것
        elif prev is None:
            if row.get("d"):
                ok = False
        elif row.get("pre") is not None and row["pre"] != prev:
            ok = False
        prev = row["h"]
    return ok and prev == cur


# ---- 이벤트 -----------------------------------------------------------------

def _file_path_of(payload: dict) -> str | None:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return file_path if isinstance(file_path, str) and file_path else None


def top_of(file_path: str) -> str:
    """고친 파일이 속한 작업 트리의 최상위. 세션 폴더와 다른 worktree·저장소일 수 있다(#829)."""
    folder = os.path.dirname(os.path.abspath(file_path))
    while not os.path.isdir(folder):
        parent = os.path.dirname(folder)
        if parent == folder:
            raise Unavailable("파일이 속한 폴더를 찾을 수 없다")
        folder = parent
    top = _git(folder, "rev-parse", "--show-toplevel").decode("utf-8", "replace").strip()
    if not top:
        raise Unavailable("git 경로를 알 수 없다")
    return top


def link_trees(state: Path, payload: dict, tops: list[str]) -> None:
    """이 서브에이전트와 연결된 작업 트리로 적는다(#829). 막는 판정은 연결된 트리에만 한다 — 같은 저장소의 다른
    세션이 일하는 worktree 의 변경까지 이 서브에이전트 탓으로 돌리지 않기 위해서다.

    시작 때 기준을 찍지 않은 작업 트리(다른 저장소, 시작 뒤 생긴 worktree)는 이때 기준도 더한다. 연결되기
    전에 스크립트로 고친 것은 볼 수 없다(한계)."""
    agent = payload.get("agent_id")
    if not agent or not tops:
        return
    me = agent_file(state, str(payload.get("session_id") or "s"), str(agent))
    try:
        meta = json.loads(me.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return  # 시작 기록이 없다 — stop 이 알린다
    trees = meta.get("trees")
    if not isinstance(trees, dict):
        return
    linked = meta.setdefault("linked", [])
    problems = meta.setdefault("problems", [])
    changed = False
    for top in tops:
        key = tkey(top)
        if key not in linked:
            linked.append(key)
            changed = True
        if key in trees:
            continue
        changed = True
        try:
            trees[key] = snapshot_tree(top)
        except (Unavailable, OSError) as exc:
            message = f"{top} 의 기준을 찍지 못했다({exc})"
            if message not in problems:
                problems.append(message)
    if changed:
        save_json(me, meta)


def mentioned_tops(top: str, text: str) -> list[str]:
    """`text`(명령·프롬프트) 안에 경로가 나온 같은 저장소의 worktree. 대소문자·구분자를 맞춰 비교하고
    Git Bash 식 `/c/…` 도 `c:/…` 로 읽는다. 상대 경로는 `../이름` 꼴만 본다. 목록을 못 읽으면 Unavailable."""
    hay = nk(re.sub(r"(?<![A-Za-z0-9_.-])/([A-Za-z])/", r"\1:/", text))
    edge_before, edge_after = r"(?<![A-Za-z0-9_.-])", r"(?![A-Za-z0-9_.-])"
    found: list[str] = []
    for item in list_worktrees(top):
        names = {nk(item), nk(os.path.realpath(item))}
        patterns = [edge_before + re.escape(n) + edge_after for n in names]
        patterns.append(r"\.\.[/\\]" + re.escape(nk(os.path.basename(item.rstrip("/\\")))) + edge_after)
        if any(re.search(p, hay) for p in patterns):
            found.append(item)
    return found


def do_prompt(payload: dict) -> None:
    """PreToolUse(Agent|Task). 서브에이전트에게 넘기는 프롬프트에 나온 worktree 를 이 세션 기록에 남긴다."""
    tool_input = payload.get("tool_input")
    text = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(text, str) or not text:
        return
    try:
        top, state = repo_paths(payload.get("cwd") or os.getcwd())
    except Unavailable:
        return  # git 이 아니면 stop 이 알린다
    row: dict = {"t": time.time()}
    try:
        row["k"] = [tkey(t) for t in mentioned_tops(top, text)]
    except Unavailable:
        row["unknown"] = True  # stop 이 "확인 못 함" 으로 알린다
    if not row.get("k") and not row.get("unknown"):
        return
    state.mkdir(parents=True, exist_ok=True)
    with open(prompts_file(state, str(payload.get("session_id") or "s")), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def do_bash(payload: dict) -> None:
    """PreToolUse(Bash|PowerShell). 서브에이전트가 실행하는 명령·작업 폴더에 나온 worktree 를 그 에이전트와 연결한다."""
    if not payload.get("agent_id"):
        return
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    cwd = payload.get("cwd") or os.getcwd()
    try:
        top, state = repo_paths(cwd)
        tops = mentioned_tops(top, f"{command if isinstance(command, str) else ''}\n{cwd}")
    except Unavailable as exc:
        add_problem(state_of_or_none(cwd), payload, f"명령에 나온 worktree 를 알아내지 못했다({exc})")
        return
    link_trees(state, payload, tops)


def state_of_or_none(cwd: str) -> Path | None:
    try:
        return repo_paths(cwd)[1]
    except Unavailable:
        return None


def add_problem(state: Path | None, payload: dict, message: str) -> None:
    if state is None:
        return
    me = agent_file(state, str(payload.get("session_id") or "s"), str(payload.get("agent_id")))
    try:
        meta = json.loads(me.read_text(encoding="utf-8"))
        problems = meta.setdefault("problems", [])
        if message not in problems:
            problems.append(message)
            save_json(me, meta)
    except (OSError, ValueError):
        return  # 시작 기록이 없다 — stop 이 알린다


def read_prompt_links(state: Path, session: str, since: float) -> tuple[set[str], bool]:
    """`since` 이후 이 세션이 서브에이전트에게 넘긴 프롬프트에 나온 worktree 키, 알아내지 못한 프롬프트가 있었는가."""
    keys: set[str] = set()
    unknown = False
    path = prompts_file(state, session)
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError as exc:
        raise Unavailable(f"프롬프트 기록을 읽지 못했다({type(exc).__name__})") from exc
    for line in lines:
        try:
            row = json.loads(line)
            if float(row["t"]) < since:
                continue
            keys.update(str(k) for k in row.get("k", []))
            unknown = unknown or bool(row.get("unknown"))
        except (ValueError, KeyError, TypeError):
            continue  # 깨진 한 줄은 건너뛴다
    return keys, unknown


def do_pre(payload: dict) -> None:
    file_path = _file_path_of(payload)
    tool_use_id = payload.get("tool_use_id")
    if not file_path or not isinstance(tool_use_id, str) or not tool_use_id:
        return
    try:
        _, state = repo_paths(payload.get("cwd") or os.getcwd())
        top = top_of(file_path)
        rel = rel_of(top, file_path)
        if rel is None:
            return
        dirty = any(nk(p) == nk(rel) for p in status_paths(top, rel))
        state.mkdir(parents=True, exist_ok=True)
        link_trees(state, payload, [top])
    except (Unavailable, OSError):
        return  # pre 가 없으면 stop 이 그 고리를 확인하지 않는다
    save_json(pre_file(state, tool_use_id), {"h": hash_file(top, rel), "d": dirty})


def do_record(payload: dict) -> None:
    file_path = _file_path_of(payload)
    if file_path is None:
        return
    try:
        _, state = repo_paths(payload.get("cwd") or os.getcwd())
        top = top_of(file_path)
    except Unavailable:
        return  # git 이 아니면 기록할 곳도 대조할 곳도 없다(stop 이 알린다)
    rel = rel_of(top, file_path)
    if rel is None:
        return
    state.mkdir(parents=True, exist_ok=True)
    row = {
        "p": rel, "r": tkey(top), "h": hash_file(top, rel), "t": time.time(),
        "w": payload.get("tool_name") == "Write",
    }
    tool_use_id = payload.get("tool_use_id")
    if isinstance(tool_use_id, str) and tool_use_id:
        pre = pre_file(state, tool_use_id)
        try:
            saved = json.loads(pre.read_text(encoding="utf-8"))
            row["pre"], row["d"] = saved["h"], bool(saved["d"])
        except (OSError, ValueError, KeyError):
            pass  # pre 가 없으면 그 고리는 확인하지 않는다
        try:
            pre.unlink()
        except OSError:
            pass
    actor = payload.get("agent_id") or "main"
    with open(edits_file(state, str(payload.get("session_id") or "s"), str(actor)), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def do_start(payload: dict) -> None:
    agent = payload.get("agent_id")
    if not agent:
        return
    state: Path | None = None
    try:
        top, state = repo_paths(payload.get("cwd") or os.getcwd())
        state.mkdir(parents=True, exist_ok=True)
        prune(state)
        trees, problems = take_trees(top)
        if tkey(top) not in trees:
            raise Unavailable("세션 폴더의 작업 트리를 읽지 못했다: " + "; ".join(problems))
        save_json(
            agent_file(state, str(payload.get("session_id") or "s"), str(agent)),
            {
                "started": time.time(), "trees": trees, "problems": problems, "primary": tkey(top),
                "blocks": 0, "blocked": {}, "done": None,
            },
        )
    except (Unavailable, OSError) as exc:
        warn(
            f"harness: 서브에이전트({agent}) 시작 시점의 작업 트리를 기록하지 못했다 — 끝날 때 "
            f"Edit/Write 밖 수정을 확인할 수 없다(확인 못 함): {exc}",
            state,
        )


def _overlapping(state: Path, me: Path, started: float) -> bool:
    now = time.time()
    for item in state.glob("*.agent.json"):
        if item == me:
            continue
        try:
            other = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        done = other.get("done")
        if done is None:
            if now - float(other.get("started") or 0) <= STALE_ACTIVE_SECONDS:
                return True
        elif done >= started:
            return True
    return False


def trees_of(meta: dict, top: str) -> dict[str, dict]:
    """시작 기록의 작업 트리별 기준. 옛 기록(세션 폴더 하나만)도 읽는다."""
    trees = meta.get("trees")
    if isinstance(trees, dict) and trees:
        return trees
    base = meta["baseline"]
    if not isinstance(base, dict):
        raise ValueError("baseline")
    return {tkey(top): {"top": top, "baseline": base, "unreadable": meta.get("unreadable", []), "head": meta.get("head")}}


def do_stop(payload: dict) -> None:
    agent = payload.get("agent_id")
    if not agent:
        return
    cwd = payload.get("cwd") or os.getcwd()
    try:
        top, state = repo_paths(cwd)
    except Unavailable as exc:
        warn(f"harness: 서브에이전트({agent})가 Edit/Write 밖에서 파일을 고쳤는지 확인하지 못했다(확인 못 함): {exc}")
        return
    try:
        prune(state)
    except OSError:
        pass
    me = agent_file(state, str(payload.get("session_id") or "s"), str(agent))
    try:
        meta = json.loads(me.read_text(encoding="utf-8"))
        trees = trees_of(meta, top)
    except (OSError, ValueError, KeyError, TypeError):
        if payload.get("agent_type") == "":
            # 공식 문서: 프롬프트 제안·/btw 같은 Claude Code 내부 에이전트는 SubagentStart 없이 Stop 만 내고
            # agent_type 이 빈 문자열이다(--agent 를 쓰면 세션 에이전트 이름이라 가릴 수 없다). 우리가 부른 게 아니다.
            return
        message = f"harness: 서브에이전트({agent})의 시작 기준이 없어 Edit/Write 밖 수정을 확인하지 못했다(확인 못 함)."
        print(message, file=sys.stderr)
        emit({"systemMessage": message})
        note_no_start(state, str(payload.get("session_id") or "s"), str(agent))
        return
    started = float(meta.get("started") or 0)

    primary = tkey(top)
    session = str(payload.get("session_id") or "s")
    notes: list[str] = [str(p) for p in (meta.get("problems") or [])]
    try:
        rows = read_rows(state, started, primary)
        prompt_keys, prompt_unknown = read_prompt_links(state, session, started - PROMPT_WINDOW_SECONDS)
    except (Unavailable, OSError) as exc:
        warn(f"harness: 서브에이전트({agent})가 고친 파일을 확인하지 못했다(확인 못 함): {exc}", state)
        return
    if prompt_unknown:
        notes.append("서브에이전트에게 넘긴 프롬프트에 나온 worktree 를 알아내지 못했다")

    # 막는 판정은 이 서브에이전트와 연결된 작업 트리에만 한다: 세션 폴더, 프롬프트·Bash 명령에 나온 worktree,
    # Edit/Write 한 작업 트리. 같은 저장소의 다른 세션이 일하는 worktree 변경은 이 서브에이전트 탓이 아니다.
    connected = {primary, *(str(k) for k in meta.get("linked") or []), *prompt_keys}
    head_changed: list[str] = []
    try:
        listed = {tkey(t) for t in list_worktrees(top)}
        for key in sorted((listed & connected) - set(trees)):
            notes.append(f"도는 동안 생긴 worktree({key})는 시작 기준이 없어 보지 못했다")
    except Unavailable as exc:
        notes.append(f"worktree 목록을 다시 읽지 못했다({exc})")

    blocked = {nk(p): float(t) for p, t in (meta.get("blocked") or {}).items()}
    bad: list[str] = []
    skipped: set[str] = set()
    for key, tree in trees.items():
        if key not in connected:
            continue
        ttop = str(tree["top"])
        shown_top = "" if key == primary else ttop.rstrip("/\\") + "/"
        if key != primary:
            # 그 작업 트리에서 다른 세션이 Edit/Write 로 고친 기록도 설명된 변경으로 본다.
            try:
                other_rows = read_rows(repo_paths(ttop)[1], started, key)
            except (Unavailable, OSError) as exc:
                notes.append(f"{ttop} 의 다른 세션 편집 기록을 읽지 못했다({exc})")
                continue
            for row_name, found in other_rows.items():
                rows[row_name] = sorted([*rows.get(row_name, []), *found], key=lambda r: r["t"])
        head_then = tree.get("head")
        if head_then is not None and head_of(ttop) != head_then:
            head_changed.append(ttop)
            continue
        base = tree["baseline"]
        try:
            now, unreadable_now = snapshot(ttop, extra=list(base))
        except (Unavailable, OSError) as exc:
            notes.append(f"{ttop} 의 지금 상태를 읽지 못했다({exc})")
            continue
        base_keys = {nk(p): h for p, h in base.items()}
        skip_here = {nk(p) for p in [*unreadable_now, *tree.get("unreadable", [])]}
        skipped |= {shown_top + p for p in skip_here}
        for rel, cur in now.items():
            name = nk(rel)
            if name in skip_here:
                continue
            if name in base_keys and base_keys[name] == cur:
                continue  # 시작 전부터 있던 변경, 그대로
            if explained(base_keys.get(name), rows.get(row_key(key, rel), []), cur, blocked.get(nk(shown_top + rel))):
                continue
            bad.append(shown_top + rel)

    if skipped:
        notes.append("읽지 못해 확인하지 못한 파일: " + ", ".join(sorted(skipped)[:10]))
    if head_changed:
        notes.append(
            "도는 동안 HEAD 가 바뀌었다(커밋·체크아웃). 커밋된 파일은 작업 트리에서 사라져 Edit/Write 밖 수정을 "
            "확인하지 못했다. 메인 세션이 `git show` 로 직접 확인한다: " + ", ".join(head_changed[:5])
        )
    notes_text = "; ".join(notes)

    if not bad:
        meta["done"] = time.time()
        save_json(me, meta)
        if notes:
            warn("harness: 서브에이전트(" + str(agent) + ") 점검 — " + notes_text + "(확인 못 함)", state)
        return

    shown = "\n".join(f"- {p}" for p in sorted(bad)[:20]) + ("\n- …" if len(bad) > 20 else "")
    blocks = int(meta.get("blocks") or 0)
    if blocks >= MAX_BLOCKS:
        meta["done"] = time.time()
        save_json(me, meta)
        warn(
            f"harness: 서브에이전트({agent})가 Edit/Write 밖에서 고친 것으로 보이는 파일이 {MAX_BLOCKS}번 막은 뒤에도 "
            f"남아 더는 막지 않고 통과시켰다. 메인 세션이 직접 확인한다:\n{shown}"
            + (f"\n(확인 못 함: {notes_text})" if notes else ""),
            state,
        )
        return

    t_block = time.time()
    meta["blocks"] = blocks + 1
    meta["blocked"] = {**(meta.get("blocked") or {}), **{p: t_block for p in bad}}
    save_json(me, meta)
    reason = (
        "도는 동안 바뀐 파일 중 Edit/Write 도구로 고친 기록과 맞지 않는 파일이 있다. 파일은 Bash·PowerShell·"
        "python 으로 쓰지 말고 Edit 또는 Write 도구로만 고친다(rules/delegation.md). 다음 파일을 "
        "Edit/Write 로 다시 고쳐라(같은 내용을 한 번 더 써도 된다):\n" + shown
        + f"\n(이 점검은 {MAX_BLOCKS}번까지 막는다. 지금 {blocks + 1}번째.)"
    )
    if notes:
        reason += f"\n(확인 못 함: {notes_text})"
        remember(state, f"harness: 서브에이전트({agent}) 점검 — {notes_text}(확인 못 함)")
    if _overlapping(state, me, started):
        reason += (
            "\n동시에 다른 서브에이전트가 돌았다. 그 파일을 다른 에이전트가 고쳤다면 최종 답에 파일 이름과 "
            "그렇게 판단한 근거를 적어라(근거 없는 \"내가 한 게 아님\" 은 받아들여지지 않는다)."
        )
    emit({"decision": "block", "reason": reason})
    console_block.report(payload, "subagent_edit_guard", reason)  # 웹 콘솔에 알린다(#765). 실패해도 조용히 돌아온다


def _take(state: Path, name: str) -> str:
    taking = state / (name + ".taking")
    try:
        os.replace(state / name, taking)  # 읽는 사이에 새로 쌓이는 경고를 잃지 않게 먼저 떼어 낸다
    except OSError:
        return ""  # 경고 없음
    try:
        text = taking.read_text(encoding="utf-8").strip()
        taking.unlink()
    except OSError:
        return ""
    return text


def do_inject(payload: dict) -> None:
    if payload.get("agent_id"):
        return  # 서브에이전트 안에서 부른 Agent 호출이면 메인이 아니다
    try:
        _, state = repo_paths(payload.get("cwd") or os.getcwd())
    except Unavailable:
        return
    text = _take(state, PENDING)
    no_start = {ln for ln in _take(state, NO_START).splitlines() if ln.strip()}
    if no_start:
        extra = f"시작 기록이 없는 서브에이전트 {len(no_start)}개(Edit/Write 밖 수정 확인 못 함)"
        text = (text + "\n" + extra) if text else extra
    if text:
        emit({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "harness 서브에이전트 수정 점검이 남긴 경고(메인 세션이 직접 확인한다):\n" + text,
        }})


def _main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        warn("harness: 서브에이전트 수정 점검 훅이 입력을 읽지 못했다(확인 못 함).")
        return
    handlers = {
        "pre": do_pre, "prompt": do_prompt, "bash": do_bash, "record": do_record, "start": do_start, "stop": do_stop, "inject": do_inject,
    }
    handler = handlers.get(mode)
    if handler is None:
        warn(f"harness: 서브에이전트 수정 점검 훅의 모드({mode!r})를 알 수 없다(확인 못 함).")
        return
    handler(payload)


def main() -> None:
    _force_utf8_io()
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 - 훅 오류가 서브에이전트를 가두면 안 된다
        warn(f"harness: 서브에이전트 수정 점검 훅에서 예상치 못한 오류가 났다(확인 못 함): {type(exc).__name__}: {exc}")
    sys.exit(0)


if __name__ == "__main__":
    main()
