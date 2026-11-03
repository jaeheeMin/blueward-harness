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
