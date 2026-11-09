"""서브에이전트 수정 점검 훅(`subagent_edit_guard.py`)을 가짜 입력으로 돌려 확인한다(#601).

훅은 stdlib 만 쓰므로 현재 파이썬으로 바로 실행한다. 임시 git 저장소에서
SubagentStart → (편집) → SubagentStop 순서를 흉내 낸다. "Bash 로 파일을 씀" 은 시험 코드가
직접 파일을 써서 흉내 내고 PostToolUse 기록을 보내지 않는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "subagent_edit_guard.py"


def hook(mode: str, payload: dict) -> tuple[int, dict | None, str]:
    done = subprocess.run(
        [sys.executable, str(HOOK), mode], input=json.dumps(payload), capture_output=True,
        text=True, encoding="utf-8", timeout=60,
    )
    out = json.loads(done.stdout) if done.stdout.strip() else None
    return done.returncode, out, done.stderr


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def base(repo: Path, agent: str = "ag1") -> dict:
    return {"session_id": "s1", "cwd": str(repo), "agent_id": agent, "agent_type": "implementer"}


def start(repo: Path, agent: str = "ag1") -> None:
    code, out, _ = hook("start", {**base(repo, agent), "hook_event_name": "SubagentStart"})
    assert code == 0 and out is None


def stop(repo: Path, agent: str = "ag1") -> tuple[int, dict | None, str]:
    return hook("stop", {**base(repo, agent), "hook_event_name": "SubagentStop", "stop_hook_active": False})


def edit_tool(
    repo: Path, name: str, text: str, agent: str | None = "ag1", tool: str = "Edit", with_pre: bool = True,
) -> None:
    """Edit/Write 도구로 고친 것을 흉내 낸다: 파일을 쓰고 PostToolUse 를 보낸다."""
    global _TOOL_SEQ
    _TOOL_SEQ += 1
    payload = base(repo, agent or "x")
    if agent is None:
        del payload["agent_id"], payload["agent_type"]
    payload.update({
        "tool_name": tool, "tool_input": {"file_path": str(repo / name)},
        "tool_use_id": f"toolu_{_TOOL_SEQ}",
    })
    if with_pre:
        code, out, _ = hook("pre", payload)
        assert code == 0 and out is None
    (repo / name).write_text(text, encoding="utf-8")
    code, out, _ = hook("record", payload)
    assert code == 0 and out is None


_TOOL_SEQ = 0


def test_edit_only_passes(repo: Path) -> None:
    start(repo)
    edit_tool(repo, "a.txt", "a2\n")
    edit_tool(repo, "new.txt", "n\n", tool="Write")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_bash_write_blocks(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("via bash\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0
    assert out is not None and out["decision"] == "block"
    assert "a.txt" in out["reason"] and "Edit/Write" in out["reason"]


def test_bash_write_new_file_blocks(repo: Path) -> None:
    start(repo)
    (repo / "made.py").write_text("x\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and "made.py" in out["reason"]


def test_edit_then_bash_overwrite_blocks(repo: Path) -> None:
    start(repo)
    edit_tool(repo, "a.txt", "a2\n")
    (repo / "a.txt").write_text("a3 by script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and "a.txt" in out["reason"]


def test_read_only_passes(repo: Path) -> None:
    start(repo)
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_changes_before_start_pass(repo: Path) -> None:
    (repo / "a.txt").write_text("dirty before\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("u\n", encoding="utf-8")
    start(repo)
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_change_after_start_to_dirty_file_blocks(repo: Path) -> None:
    (repo / "a.txt").write_text("dirty before\n", encoding="utf-8")
    start(repo)
    (repo / "a.txt").write_text("dirty again via script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and "a.txt" in out["reason"]


def test_main_session_edit_is_not_blamed(repo: Path) -> None:
    start(repo)
    edit_tool(repo, "b.txt", "main edit\n", agent=None)
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_concurrent_agents_each_own_edits_pass(repo: Path) -> None:
    start(repo, "ag1")
    start(repo, "ag2")
    edit_tool(repo, "a.txt", "from ag1\n", agent="ag1")
    edit_tool(repo, "b.txt", "from ag2\n", agent="ag2")
    for agent in ("ag1", "ag2"):
        code, out, _ = stop(repo, agent)
        assert code == 0 and out is None


def test_block_limit_passes_with_warning(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("script\n", encoding="utf-8")
    for _ in range(2):
        _, out, _ = stop(repo)
        assert out is not None and out["decision"] == "block"
    code, out, err = stop(repo)
    assert code == 0
    assert out is not None and "decision" not in out
    assert "a.txt" in out["systemMessage"] and "a.txt" in err


def test_fixing_with_edit_after_block_passes(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block"
    edit_tool(repo, "a.txt", "script\n")  # 같은 내용을 Edit/Write 로 다시 쓴다
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_not_a_git_repo_warns_and_passes(tmp_path: Path) -> None:
    code, out, _ = stop(tmp_path)
    assert code == 0
    assert out is not None and "decision" not in out
    assert "확인 못 함" in out["systemMessage"]


def test_missing_baseline_warns_and_passes(repo: Path) -> None:
    (repo / "a.txt").write_text("script\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0
    assert out is not None and "decision" not in out
    assert "확인 못 함" in out["systemMessage"]


def test_bad_input_warns_and_passes(repo: Path) -> None:
    done = subprocess.run(
        [sys.executable, str(HOOK), "stop"], input="not json", capture_output=True,
        text=True, encoding="utf-8", timeout=60,
    )
    assert done.returncode == 0
    assert "확인 못 함" in json.loads(done.stdout)["systemMessage"]


def test_main_session_stop_without_agent_id_is_ignored(repo: Path) -> None:
    code, out, _ = hook("stop", {"session_id": "s1", "cwd": str(repo)})
    assert code == 0 and out is None


def test_hooks_json_registers_all_three() -> None:
    hooks = json.loads((HOOK.parent / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    def commands(event: str) -> list[str]:
        return [h["command"] for e in hooks[event] for h in e["hooks"]]
    assert any("subagent_edit_guard.py\" record" in c for c in commands("PostToolUse"))
    assert any("subagent_edit_guard.py\" start" in c for c in commands("SubagentStart"))
    assert any("subagent_edit_guard.py\" stop" in c for c in commands("SubagentStop"))
    record = [e for e in hooks["PostToolUse"] if e.get("matcher") == "Write|Edit|NotebookEdit"]
    assert len(record) == 1 and "subagent_edit_guard" in json.dumps(record[0])
    inject = [e for e in hooks["PostToolUse"] if e.get("matcher") == "Agent|Task"]
    assert len(inject) == 1 and "subagent_edit_guard.py\\\" inject" in json.dumps(inject[0])
    pre = [e for e in hooks["PreToolUse"] if e.get("matcher") == "Write|Edit|NotebookEdit"]
    assert len(pre) == 1 and "subagent_edit_guard.py\\\" pre" in json.dumps(pre[0])


# --- 검토 지적 반영 -------------------------------------------------------------

def state_dir(repo: Path) -> Path:
    return repo / ".git" / "harness-subagent-guard"


def exhaust_limit(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("script\n", encoding="utf-8")
    for _ in range(2):
        stop(repo)
    code, out, _ = stop(repo)
    assert code == 0 and out is not None and "decision" not in out


def inject(repo: Path, **extra) -> dict | None:
    payload = {"session_id": "s1", "cwd": str(repo), "tool_name": "Agent", **extra}
    code, out, _ = hook("inject", payload)
    assert code == 0
    return out


def test_warning_reaches_main_model_once(repo: Path) -> None:
    exhaust_limit(repo)
    assert inject(repo, agent_id="nested") is None  # 서브에이전트 안의 호출은 건드리지 않는다
    out = inject(repo)
    assert out is not None
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse"
    assert "a.txt" in spec["additionalContext"]
    assert inject(repo) is None  # 한 번만 주입하고 비웠다


def test_unavailable_warning_also_reaches_main_model(repo: Path) -> None:
    code, out, _ = stop(repo)  # 기준 없음
    assert code == 0 and "확인 못 함" in out["systemMessage"]
    got = inject(repo)
    assert got is not None and "확인 못 함" in got["hookSpecificOutput"]["additionalContext"]


def test_no_start_stops_are_bundled_into_one_line(repo: Path) -> None:
    for agent in ("x1", "x2", "x3", "x1"):  # x1 은 두 번 — 한 번만 센다
        stop(repo, agent)
    got = inject(repo)
    assert got is not None
    text = got["hookSpecificOutput"]["additionalContext"]
    assert "시작 기록이 없는 서브에이전트 3개" in text and "확인 못 함" in text
    assert "x1" not in text and text.count("\n") == 1  # 머리글 + 묶음 한 줄
    assert inject(repo) is None


def test_internal_agent_with_empty_type_is_silent(repo: Path) -> None:
    payload = {**base(repo, "int1"), "agent_type": "", "hook_event_name": "SubagentStop", "stop_hook_active": False}
    code, out, _ = hook("stop", payload)
    assert code == 0 and out is None
    assert inject(repo) is None


def test_started_agent_warning_stays_per_line_beside_bundle(repo: Path) -> None:
    stop(repo, "ghost")
    exhaust_limit(repo)
    text = inject(repo)["hookSpecificOutput"]["additionalContext"]
    assert "a.txt" in text and "시작 기록이 없는 서브에이전트 1개" in text


def test_inject_without_warnings_is_silent(repo: Path) -> None:
    assert inject(repo) is None


def test_records_from_before_start_are_ignored(repo: Path) -> None:
    edit_tool(repo, "a.txt", "script\n", agent="old")  # 시작 전에 Edit 로 한 편집
    git(repo, "checkout", "--", "a.txt")
    start(repo)
    (repo / "a.txt").write_text("script\n", encoding="utf-8")  # 해시가 옛 기록과 같지만 이번엔 스크립트
    _, out, _ = stop(repo)
    assert out is not None and "a.txt" in out["reason"]


def test_bash_then_edit_cannot_hide(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("bash\n", encoding="utf-8")
    edit_tool(repo, "a.txt", "bash\nedit\n")
    _, out, _ = stop(repo)
    assert out is not None and "a.txt" in out["reason"]


def test_bash_then_edit_cannot_hide_on_dirty_baseline(repo: Path) -> None:
    (repo / "a.txt").write_text("d1\n", encoding="utf-8")
    start(repo)
    (repo / "a.txt").write_text("d2\n", encoding="utf-8")
    edit_tool(repo, "a.txt", "d2\nedit\n")
    _, out, _ = stop(repo)
    assert out is not None and "a.txt" in out["reason"]


def test_normal_edit_chains_pass(repo: Path) -> None:
    (repo / "b.txt").write_text("dirty\n", encoding="utf-8")
    start(repo)
    edit_tool(repo, "a.txt", "1\n")
    edit_tool(repo, "a.txt", "2\n")
    edit_tool(repo, "b.txt", "dirty2\n")  # 시작 전부터 변경된 파일
    edit_tool(repo, "new.txt", "n1\n", tool="Write")
    edit_tool(repo, "new.txt", "n2\n")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_write_over_bash_change_passes(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("bash\n", encoding="utf-8")
    edit_tool(repo, "a.txt", "whole new\n", tool="Write")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_edit_without_pre_record_is_not_blamed(repo: Path) -> None:
    start(repo)
    edit_tool(repo, "a.txt", "1\n", with_pre=False)
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_head_change_warns_instead_of_blocking(repo: Path) -> None:
    start(repo)
    (repo / "a.txt").write_text("committed by script\n", encoding="utf-8")
    git(repo, "commit", "-q", "-am", "by subagent")
    code, out, _ = stop(repo)
    assert code == 0
    assert out is not None and "decision" not in out and "HEAD" in out["systemMessage"]
    got = inject(repo)
    assert got is not None and "HEAD" in got["hookSpecificOutput"]["additionalContext"]


def test_stale_unfinished_agent_does_not_count_as_overlap(repo: Path) -> None:
    start(repo, "ag1")
    start(repo, "ag2")
    (repo / "a.txt").write_text("script\n", encoding="utf-8")
    _, out, _ = stop(repo, "ag1")
    assert out is not None and "근거" in out["reason"]  # ag2 가 아직 돌고 있다

    other = next(state_dir(repo).glob("*.ag2.agent.json"))
    meta = json.loads(other.read_text(encoding="utf-8"))
    meta["started"] -= 7200
    other.write_text(json.dumps(meta), encoding="utf-8")
    _, out, _ = stop(repo, "ag1")
    assert out is not None and "근거" not in out["reason"]


# --- 세션 폴더 밖 worktree·저장소(#829) ------------------------------------------

@pytest.fixture()
def other_tree(repo: Path) -> Path:
    """같은 저장소의 다른 worktree(세션 폴더는 `repo`)."""
    other = repo.parent / (repo.name + "-wt")
    git(repo, "worktree", "add", "-q", "-b", "other", str(other))
    return other


def edit_abs(cwd: Path, target: Path, text: str, agent: str = "ag1", tool: str = "Edit") -> None:
    """세션 폴더(`cwd`)에서 절대 경로 `target` 을 Edit/Write 로 고친 것을 흉내 낸다."""
    global _TOOL_SEQ
    _TOOL_SEQ += 1
    payload = {
        **base(cwd, agent), "tool_name": tool, "tool_input": {"file_path": str(target)},
        "tool_use_id": f"toolu_{_TOOL_SEQ}",
    }
    assert hook("pre", payload)[:2] == (0, None)
    target.write_text(text, encoding="utf-8")
    assert hook("record", payload)[:2] == (0, None)


def agent_prompt(cwd: Path, text: str) -> None:
    """PreToolUse(Agent) — 메인 세션이 서브에이전트에게 넘기는 프롬프트."""
    payload = {"session_id": "s1", "cwd": str(cwd), "tool_name": "Agent", "tool_input": {"prompt": text}}
    assert hook("prompt", payload)[:2] == (0, None)


def agent_bash(cwd: Path, command: str, agent: str = "ag1") -> None:
    """PreToolUse(Bash) — 서브에이전트가 실행하려는 명령(실행은 시험이 따로 흉내 낸다)."""
    payload = {**base(cwd, agent), "tool_name": "Bash", "tool_input": {"command": command}}
    assert hook("bash", payload)[:2] == (0, None)


def test_unconnected_worktree_changes_do_not_block(repo: Path, other_tree: Path) -> None:
    """같은 저장소의 다른 세션이 일하는 worktree 는 이 서브에이전트와 연결되지 않으면 막지 않는다."""
    start(repo)
    (other_tree / "a.txt").write_text("another session by script or IDE\n", encoding="utf-8")
    (other_tree / "made.txt").write_text("test output\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_script_write_in_prompt_worktree_blocks(repo: Path, other_tree: Path) -> None:
    """11-09 사고: 프롬프트로 넘긴 다른 worktree 를 서브에이전트가 스크립트로 고쳤다."""
    agent_prompt(repo, f"{other_tree} 에서 a.txt 를 고쳐라")
    start(repo)
    (other_tree / "a.txt").write_text("via script\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0
    assert out is not None and out["decision"] == "block"
    assert "a.txt" in out["reason"] and other_tree.name in out["reason"]


def test_prompt_path_style_is_normalized(repo: Path, other_tree: Path) -> None:
    mangled = str(other_tree).replace("\\", "/").upper()  # 구분자·대소문자가 달라도 같은 worktree
    if sys.platform != "win32":
        mangled = str(other_tree)
    agent_prompt(repo, f"작업 폴더: {mangled}\n")
    start(repo)
    (other_tree / "a.txt").write_text("via script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block"


def test_prompt_naming_similar_worktree_does_not_connect_it(repo: Path, other_tree: Path) -> None:
    agent_prompt(repo, f"{repo} 만 고쳐라")  # other_tree 이름은 repo 이름 + "-wt" — 접두사만 같다
    start(repo)
    (other_tree / "a.txt").write_text("someone else\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_old_prompt_is_not_linked(repo: Path, other_tree: Path) -> None:
    agent_prompt(repo, f"{other_tree}")
    prompts = next(state_dir(repo).glob("prompts.*.jsonl"))
    prompts.write_text(json.dumps({"t": 1.0, "k": [json.loads(prompts.read_text().splitlines()[0])["k"][0]]}) + "\n")
    start(repo)
    (other_tree / "a.txt").write_text("via script\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_script_write_in_bash_command_worktree_blocks(repo: Path, other_tree: Path) -> None:
    start(repo)
    script = f"python -c \"open(r'{other_tree}/a.txt','w').write('x')\""
    agent_bash(repo, script)
    (other_tree / "a.txt").write_text("via script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block" and "a.txt" in out["reason"]


def test_bash_command_without_worktree_path_links_nothing(repo: Path, other_tree: Path) -> None:
    start(repo)
    agent_bash(repo, "ls -la")
    (other_tree / "a.txt").write_text("someone else\n", encoding="utf-8")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_worktree_created_by_agent_command_is_baselined_then_checked(repo: Path) -> None:
    start(repo)
    other = repo.parent / (repo.name + "-late")
    git(repo, "worktree", "add", "-q", "-b", "late", str(other))
    agent_bash(repo, f"cd {other}")  # 만든 뒤 처음 나온 명령 — 이때부터 연결·기준
    (other / "a.txt").write_text("via script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block" and "a.txt" in out["reason"]


def test_edit_in_other_worktree_passes(repo: Path, other_tree: Path) -> None:
    start(repo)
    edit_abs(repo, other_tree / "a.txt", "a2\n")
    edit_abs(repo, other_tree / "new.txt", "n\n", tool="Write")
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_edit_then_script_in_other_worktree_blocks(repo: Path, other_tree: Path) -> None:
    start(repo)
    edit_abs(repo, other_tree / "a.txt", "a2\n")  # Edit 한 트리는 연결된다
    (other_tree / "a.txt").write_text("a3 by script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block" and "a.txt" in out["reason"]


def test_other_worktree_changes_before_start_pass(repo: Path, other_tree: Path) -> None:
    (other_tree / "a.txt").write_text("dirty before\n", encoding="utf-8")
    agent_prompt(repo, f"{other_tree}")
    start(repo)
    code, out, _ = stop(repo)
    assert code == 0 and out is None


def test_other_session_edit_record_explains_change_in_linked_tree(repo: Path, other_tree: Path) -> None:
    agent_prompt(repo, f"{other_tree}")
    start(repo)
    edit_tool(other_tree, "a.txt", "by the other session\n", agent=None)  # 그 worktree 의 기록 폴더에만 남는다
    code, out, _ = stop(repo)
    assert code == 0 and out is None
    (other_tree / "b.txt").write_text("script\n", encoding="utf-8")  # 기록 없는 변경은 여전히 막는다
    _, out, _ = stop(repo)
    assert out is not None and "b.txt" in out["reason"] and "a.txt" not in out["reason"]


def test_script_write_in_other_repo_after_edit_blocks(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    foreign = tmp_path_factory.mktemp("foreign")
    git(foreign, "init", "-q")
    git(foreign, "config", "user.email", "t@example.com")
    git(foreign, "config", "user.name", "t")
    (foreign / "f.txt").write_text("f\n", encoding="utf-8")
    (foreign / "g.txt").write_text("g\n", encoding="utf-8")
    git(foreign, "add", ".")
    git(foreign, "commit", "-q", "-m", "init")
    start(repo)
    edit_abs(repo, foreign / "f.txt", "f2\n")  # 이때 그 저장소의 기준이 더해진다
    code, out, _ = stop(repo)
    assert code == 0 and out is None
    (foreign / "g.txt").write_text("via script\n", encoding="utf-8")
    _, out, _ = stop(repo)
    assert out is not None and out["decision"] == "block"
    assert "g.txt" in out["reason"] and "f.txt" not in out["reason"]


def test_worktree_created_during_run_is_reported_not_passed_silently(repo: Path) -> None:
    start(repo)
    other = repo.parent / (repo.name + "-late")
    git(repo, "worktree", "add", "-q", "-b", "late", str(other))
    agent_prompt(repo, f"{other} 에서 이어서 일해라")  # 시작 뒤 연결된 worktree — 기준이 없다
    code, out, _ = stop(repo)
    assert code == 0
    assert out is not None and "decision" not in out
    assert "확인 못 함" in out["systemMessage"] and "worktree" in out["systemMessage"]


def load_hook_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("subagent_edit_guard_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unreadable_worktree_list_warns_and_still_checks_session_folder(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_hook_module()

    def broken(_top: str) -> list[str]:
        raise module.Unavailable("git worktree 실패")

    monkeypatch.setattr(module, "list_worktrees", broken)
    payload = {**base(repo), "hook_event_name": "SubagentStart"}
    module.do_start(payload)
    assert capsys.readouterr().out == ""

    module.do_stop(payload)  # 바뀐 것 없음 — 통과가 아니라 "확인 못 함" 이어야 한다
    out = json.loads(capsys.readouterr().out)
    assert "decision" not in out and "확인 못 함" in out["systemMessage"] and "worktree 목록" in out["systemMessage"]

    (repo / "a.txt").write_text("script\n", encoding="utf-8")  # 세션 폴더는 그래도 막는다
    module.do_stop(payload)
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block" and "확인 못 함" in out["reason"]


def test_old_state_files_are_pruned_at_stop(repo: Path) -> None:
    import os
    import time
    start(repo)
    old = state_dir(repo) / "old.session.edits.jsonl"
    old.write_text("", encoding="utf-8")
    long_ago = time.time() - 8 * 24 * 3600
    os.utime(old, (long_ago, long_ago))
    stop(repo)
    assert not old.exists()
