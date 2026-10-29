"""Agent 도구 훅(`agent_delegation_guard.py`)이 위임 규칙을 거는지 확인한다(#400).

훅은 stdlib 만 쓰므로 현재 파이썬으로 바로 실행한다(엔진을 받지 않는다).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "agent_delegation_guard.py"


def run_hook(stdin: str) -> tuple[int, dict | None]:
    done = subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    out = json.loads(done.stdout) if done.stdout.strip() else None
    return done.returncode, out


def call(tool_input) -> tuple[int, dict | None]:
    return run_hook(json.dumps({"tool_name": "Agent", "tool_input": tool_input}))


def reason(out: dict | None) -> str:
    assert out is not None, "거절 출력이 없다"
    spec = out["hookSpecificOutput"]
    assert spec["permissionDecision"] == "deny"
    return spec["permissionDecisionReason"]


def assert_allowed(code: int, out: dict | None) -> None:
    assert code == 0
    assert out is None


def test_model_을_넘기면_거절한다():
    code, out = call({"subagent_type": "harness:researcher", "prompt": "x", "model": "sonnet"})
    assert code == 0
    text = reason(out)
    assert "model" in text and "정의 파일" in text and "빼고" in text


@pytest.mark.parametrize("model", ["opus", "haiku"])
def test_어떤_model_값이든_거절한다(model):
    _, out = call({"subagent_type": "harness:implementer", "prompt": "x", "model": model})
    assert "model" in reason(out)


def test_빈_model_은_넘기지_않은_것으로_본다():
    assert_allowed(*call({"subagent_type": "harness:researcher", "prompt": "x", "model": ""}))


@pytest.mark.parametrize("kind", ["general-purpose", "General-Purpose", "claude"])
def test_기본_에이전트는_거절하고_harness_에이전트를_안내한다(kind):
    _, out = call({"subagent_type": kind, "prompt": "x"})
    text = reason(out)
    assert "harness:researcher" in text and "harness:implementer" in text and "harness:reviewer" in text


@pytest.mark.parametrize("tool_input", [
    {"prompt": "x"},
    {"prompt": "x", "subagent_type": ""},
    {"prompt": "x", "subagent_type": "  "},
    {"prompt": "x", "subagent_type": None},
    {"prompt": "x", "subagent_type": 3},
])
def test_subagent_type_이_없거나_비면_거절한다(tool_input):
    _, out = call(tool_input)
    assert "subagent_type" in reason(out)


@pytest.mark.parametrize("kind", [
    "harness:researcher", "harness:implementer", "harness:reviewer",
    "fork", "web-fetch", "claude-code-guide", "Explore", "Plan", "statusline-setup",
    "other-plugin:agent",
])
def test_그_밖의_타입은_model_없이_통과한다(kind):
    assert_allowed(*call({"subagent_type": kind, "prompt": "x", "description": "d"}))


@pytest.mark.parametrize("stdin", [
    "",
    "not json",
    "[]",
    "null",
    json.dumps({"tool_name": "Agent"}),
    json.dumps({"tool_name": "Agent", "tool_input": "text"}),
    json.dumps({"tool_name": "Agent", "tool_input": ["a"]}),
    json.dumps({"tool_name": "Agent", "tool_input": None}),
])
def test_입력을_해석하지_못하면_검사_불능으로_거절한다(stdin):
    code, out = run_hook(stdin)
    assert code == 0
    assert "검사 불능" in reason(out)
