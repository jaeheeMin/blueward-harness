"""harness 플러그인의 레이아웃이 이슈 #37 이 요구하는 모양을 갖췄는지 검증한다.

`doc-guard` 플러그인을 `harness` 로 이름을 바꾸고, 협업 Skill·규칙·훅을
플러그인 안으로 옮긴 뒤 생긴 새 계약을 지킨다.

- 플러그인 이름이 실제로 `harness` 로 바뀌었는가 (`plugin.json`, `marketplace.json`)
- `hooks.json` 이 유효한 JSON 이고, 네 훅이 모두 등록되어 있으며, 각 훅이 가리키는
  파일이 실제로 존재하는가
- Skill 넷(`start`, `deliver`, `wrapup`, `scaffold`)이 모두 있고 frontmatter 에
  `name:` 이 있는가
- Skill 이 규칙 문서를 저장소 루트 기준 경로(`rules/xxx.md`)로 참조하고 있지
  않은가 — 설치된 플러그인은 저장소 루트가 아니므로 그런 경로는 항상 깨진다
- 훅 스크립트에 특정 저장소 이름이 하드코딩되어 있지 않은가
"""
from __future__ import annotations

import json
import re
import shutil
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "harness"


def test_플러그인_이름이_harness_다():
    plugin_json = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    assert plugin_json["name"] == "harness"


def test_마켓플레이스_항목이_harness_를_가리킨다():
    marketplace = json.loads(
        (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    entries = [p for p in marketplace["plugins"] if p["name"] == "harness"]
    assert len(entries) == 1
    assert entries[0]["source"] == "./plugins/harness"


HOOK_MATCHERS = {"Write|Edit", "Bash|PowerShell", "mcp__.*__setObjectSource"}


def _hook_file_refs(hooks_json: dict) -> list[str]:
    """hooks.json 의 모든 command 문자열에서 `hooks/<파일>` 참조를 뽑는다."""
    refs: list[str] = []
    for entries in hooks_json["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                match = re.search(r"hooks/([A-Za-z0-9_.\-]+)", hook["command"])
                assert match, f"훅 command 에서 파일을 못 찾았다: {hook['command']}"
                refs.append(match.group(1))
    return refs


def test_hooks_json_이_유효하고_네_훅을_모두_담고_있다():
    hooks_json = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    refs = _hook_file_refs(hooks_json)
    assert set(refs) == {
        "pre_write_guard.py",
        "pre-bash-git-guard.sh",
        "session-start-sync.sh",
        "stop-deliver.sh",
        "mcp_source_guard.py",
    }

    # 각 훅이 가리키는 파일이 실제로 플러그인 안에 있어야 한다.
    for ref in refs:
        assert (PLUGIN_ROOT / "hooks" / ref).is_file(), f"{ref} 가 없다"

    events = hooks_json["hooks"]
    assert "PreToolUse" in events
    assert "SessionStart" in events
    assert "Stop" in events

    pre_matchers = {entry["matcher"] for entry in events["PreToolUse"]}
    assert pre_matchers == HOOK_MATCHERS


@pytest.mark.parametrize("name", ["start", "deliver", "wrapup", "scaffold", "prd", "spec"])
def test_스킬이_있고_frontmatter_에_name_이_있다(name):
    skill_md = PLUGIN_ROOT / "skills" / name / "SKILL.md"
    assert skill_md.is_file(), f"{skill_md} 가 없다"

    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---"), "frontmatter 로 시작하지 않는다"
    frontmatter = text.split("---", 2)[1]
    assert re.search(r"^name:\s*\S+", frontmatter, re.MULTILINE), "name: 이 없다"


@pytest.mark.parametrize("name", ["start", "deliver", "wrapup", "prd", "spec"])
def test_스킬이_저장소_루트_기준_규칙_경로를_쓰지_않는다(name):
    """설치된 플러그인은 저장소 루트가 아니므로 `rules/xxx.md` 처럼 곧바로 쓴
    경로는 항상 깨진다. 스킬의 base directory 에서 상대 경로(`../../rules/`)로
    참조해야 한다."""
    skill_md = PLUGIN_ROOT / "skills" / name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")

    broken = []
    for match in re.finditer(r"rules/[a-zA-Z][a-zA-Z\-]*\.md", text):
        prefix = text[max(0, match.start() - 6) : match.start()]
        if prefix != "../../":
            broken.append(text[max(0, match.start() - 20) : match.end()])

    assert not broken, f"{skill_md} 에 저장소 루트 기준 rules/ 경로가 남아 있다: {broken}"


def test_공통_개발_규칙_문서에_CR_001부터_008까지_있다():
    """#53 — common.md 가 CR-001 ~ CR-008 여덟 개 헤딩을 모두 가지고 있는가."""
    common_md = PLUGIN_ROOT / "conventions" / "common.md"
    assert common_md.is_file(), f"{common_md} 가 없다"

    text = common_md.read_text(encoding="utf-8")
    for n in range(1, 9):
        assert re.search(rf"^## CR-{n:03d}\b", text, re.MULTILINE), f"CR-{n:03d} 헤딩이 없다"


@pytest.mark.parametrize(
    "sh_name",
    ["pre-bash-git-guard.sh", "session-start-sync.sh", "stop-deliver.sh"],
)
def test_훅_스크립트에_저장소_이름이_하드코딩되어_있지_않다(sh_name):
    text = (PLUGIN_ROOT / "hooks" / sh_name).read_text(encoding="utf-8")
    assert "doc-guard-unfinished" not in text
    assert "sap-unfinished" not in text


# --- push 가드 훅이 실제로 동작하는지 -----------------------------------

def _find_bash() -> str | None:
    """훅을 돌릴 진짜 bash 를 찾는다.

    Windows 에서는 PATH 에서 `System32\bash.exe`(WSL 실행기)가 먼저 잡히곤 한다. 리눅스
    배포판이 없는 곳에서는 이것이 JSON 대신 안내 문구를 내므로 훅 검사에 쓸 수 없다.
    Claude Code 가 Windows 에서 훅을 돌리는 Git Bash 를 먼저 찾는다.
    """
    if os.name == "nt":
        for candidate in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe",
        ):
            if candidate.is_file():
                return str(candidate)
        found = shutil.which("bash")
        if found and "system32" not in found.lower():
            return found
        return None
    return shutil.which("bash")


_BASH = _find_bash()
_HAS_BASH = _BASH is not None
_HAS_JQ = shutil.which("jq") is not None


def _run_guard(command: str, env: dict | None = None) -> tuple[int, dict | None]:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    full_env = {**os.environ, **(env or {})}
    done = subprocess.run(
        [_BASH, str(PLUGIN_ROOT / "hooks" / "pre-bash-git-guard.sh")],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=180,
    )
    out = json.loads(done.stdout) if done.stdout.strip() else None
    return done.returncode, out


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다")
def test_선언_없는_push_는_막는다():
    code, out = _run_guard("git push origin HEAD")
    assert code == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다")
def test_DELIVER_선언이_있으면_통과시킨다():
    code, out = _run_guard("DELIVER=1 git push -u origin HEAD")
    assert code == 0
    assert out is None


# --- gh pr merge 가드(#49) ---------------------------------------------------
#
# 여기서는 실제 gh api 를 부르지 않는다(네트워크 필요). PR 번호와 저장소를
# 명령 자체에서 뽑을 수 있는 형태(`-R owner/repo` + 숫자 PR)로 줘서 `gh pr
# view` 호출 없이 곧장 판정 로직 호출로 넘어가게 하고, `DOC_GUARD_ENGINE` 을
# 존재하지 않는 경로로 줘 판정 로직 자체를 받지 못하게 만든다. CLAUDE.md
# 원칙 7 — 판정 불가는 통과가 아니라 거부다.

_HAS_UVX = shutil.which("uvx") is not None
_HAS_GH = shutil.which("gh") is not None


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git/gh 명령을 거부한다")
@pytest.mark.skipif(not _HAS_UVX, reason="uvx 가 없으면 이 경로를 재현할 수 없다")
@pytest.mark.skipif(not _HAS_GH, reason="gh 가 없으면 이 경로를 재현할 수 없다")
def test_gh_pr_merge_는_판정_엔진을_못_받으면_거부한다(tmp_path):
    missing_engine = str(tmp_path / "존재하지-않는-엔진-경로")
    code, out = _run_guard(
        "gh pr merge 123 -R owner/repo",
        env={"DOC_GUARD_ENGINE": missing_engine},
    )
    assert code == 0
    assert out is not None
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason or "확인하지 못해" in reason


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
@pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git/gh 명령을 거부한다")
def test_gh_pr_가_아닌_명령은_영향을_받지_않는다():
    """`gh` 로 시작하지만 `pr merge` 가 아닌 명령은 이 검사를 타지 않는다."""
    code, out = _run_guard("gh pr view 123 -R owner/repo")
    assert code == 0
    assert out is None


# --- 세션 시작 훅의 공통 개발 규칙 요약(#53) --------------------------------
#
# 임시 git 저장소를 만들어 그 안에서 session-start-sync.sh 를 직접 돌린다.
# 원격을 연결하지 않으므로 훅의 fetch/pull 단계는 "원격이 없다" 로 바로
# 건너뛴다 — 네트워크를 기다리거나 실패해 멈추지 않는다.


def _init_temp_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "README.md").write_text("test\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _run_session_start_sync(repo: Path) -> str:
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        "CLAUDE_PROJECT_DIR": str(repo),
    }
    done = subprocess.run(
        [_BASH, str(PLUGIN_ROOT / "hooks" / "session-start-sync.sh")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )
    return done.stdout


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
def test_세션_시작_요약에_공통_개발_규칙이_들어간다(tmp_path):
    repo = tmp_path / "project"
    _init_temp_git_repo(repo)

    out = _run_session_start_sync(repo)

    assert "공통 개발 규칙" in out
    assert "CR-001" in out
    expected_common_md = f"{PLUGIN_ROOT}/conventions/common.md"
    assert expected_common_md in out

    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if "공통 개발 규칙(harness)" in line)
    block = lines[start:]
    assert len(block) <= 14, f"요약 블록이 너무 길다({len(block)}줄): {block}"


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")
def test_프로젝트_conventions_가_있으면_함께_안내한다(tmp_path):
    repo = tmp_path / "project"
    _init_temp_git_repo(repo)
    (repo / "conventions").mkdir()
    (repo / "conventions" / "naming.md").write_text(
        "# naming\n", encoding="utf-8", newline="\n"
    )
    (repo / "conventions" / "README.md").write_text(
        "# conventions\n", encoding="utf-8", newline="\n"
    )

    out = _run_session_start_sync(repo)

    assert "conventions/naming.md" in out
    assert "이 저장소의 Convention" in out
    assert "CR-004 제외" in out
