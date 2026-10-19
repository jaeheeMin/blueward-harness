"""세션 시작 훅의 "내 PR 상태" 블록(#370)과 지난 세션 기록 판정 테스트.

`session-start-sync.sh` 를 임시 저장소에서 직접 돌린다. 엔진(`uvx --from … python -m checker.pr_queue`)은
가짜 `uvx` 로 바꾸고, `gh`·`uv`·`timeout` 의 있고 없음은 PATH 를 shim 폴더 하나로 좁혀 만든다.
origin 이 github.com 인지는 `git remote get-url` 문자열로 보므로, 경로에 `github.com` 이 든 로컬 bare 저장소를 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

pytestmark = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다")

HOOK = PLUGIN_ROOT / "hooks" / "session-start-sync.sh"
# 훅이 부르는 명령. shim 폴더에 이것들만 둬서 gh·uvx·timeout 의 유무를 정한다.
_TOOLS = (
    "git cat head tail tr grep sed wc basename dirname rm mv mkdir sort uniq date cut awk jq ls touch "
    "env sleep cp"
).split()

FAKE_UVX = """#!/bin/sh
case "$*" in
  *checker.pr_queue*)
    echo "run: $*" >> "$FAKE_DIR/calls"
    if [ -f "$FAKE_DIR/sleep" ]; then exec sleep "$(cat "$FAKE_DIR/sleep")"; fi
    if [ -f "$FAKE_DIR/out" ]; then cat "$FAKE_DIR/out"; fi
    if [ -f "$FAKE_DIR/rc" ]; then exit "$(cat "$FAKE_DIR/rc")"; fi
    exit 0
    ;;
  *)
    echo "warm: $*" >> "$FAKE_DIR/calls"
    exit 0
    ;;
esac
"""


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.strip()


def _repo(tmp_path: Path, origin: str | None) -> Path:
    """origin: None 이면 없음, "github" 이면 경로에 github.com 이 든 bare, "other" 면 아닌 bare, "dead" 면 없는 경로."""
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "README.md").write_text("test\n", encoding="utf-8", newline="\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    if origin in ("github", "other"):
        bare = tmp_path / ("github.com" if origin == "github" else "elsewhere") / "o" / "r.git"
        bare.parent.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        _git(repo, "remote", "add", "origin", bare.as_posix())
        _git(repo, "push", "-q", "-u", "origin", "main")
        _git(repo, "checkout", "-q", "-b", "feature/x")
    elif origin == "dead":
        _git(repo, "remote", "add", "origin", (tmp_path / "github.com" / "none" / "gone.git").as_posix())
        _git(repo, "checkout", "-q", "-b", "feature/x")
    return repo


def _resolve_tools() -> dict[str, str]:
    script = "for t in " + " ".join(_TOOLS + ["timeout"]) + '; do p="$(command -v $t)"; echo "$t=$p"; done'
    done = subprocess.run([_BASH, "-c", script], capture_output=True, text=True, encoding="utf-8", check=True)
    found = {}
    for line in done.stdout.splitlines():
        name, _, path = line.strip().partition("=")
        if path.startswith("/") or path[1:3] == ":/":
            found[name] = path
    return found


def _shim_dir(tmp_path: Path, *, timeout: bool = True, gh: bool = True, uvx: bool = True, uv: str | None = None) -> Path:
    """PATH 로 쓸 폴더. gh·uvx·uv·timeout 은 요청한 것만 둔다."""
    bin_dir = tmp_path / "shim-bin"
    bin_dir.mkdir()
    tools = _resolve_tools()
    for name, path in tools.items():
        if name == "timeout" and not timeout:
            continue
        (bin_dir / name).write_text(f'#!/bin/sh\nexec "{path}" "$@"\n', encoding="utf-8", newline="\n")
    if gh:
        (bin_dir / "gh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    if uvx:
        (bin_dir / "uvx").write_text(FAKE_UVX, encoding="utf-8", newline="\n")
    if uv is not None:
        (bin_dir / "uv").write_text(uv, encoding="utf-8", newline="\n")
    return bin_dir


def _start(tmp_path: Path, repo: Path, bin_dir: Path, fake: Path | None = None, engine: str | None = "fake-engine",
           hide_timeout: bool = False, **extra):
    root = tmp_path / "plugin-root" / "harness"
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    script = HOOK.read_bytes().decode("utf-8")  # ensure-tools.sh 는 복사하지 않는다
    if hide_timeout:
        # msys bash 는 PATH 와 무관하게 /usr/bin 을 붙여서 timeout 을 PATH 에서 뺄 수 없다.
        # 복사본에서 timeout 이 있는지 보는 검사만 없는 명령으로 바꿔 "timeout 없음" 경로를 탄다.
        assert "command -v timeout" in script
        script = script.replace("command -v timeout", "command -v timeout-is-not-installed")
    (root / "hooks" / "session-start-sync.sh").write_bytes(script.replace("\r\n", "\n").encode("utf-8"))
    env = {
        "PATH": str(bin_dir),
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "USERPROFILE": os.environ.get("USERPROFILE", str(tmp_path)),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HARNESS_NO_SCAFFOLD_HINT": "1",
        "CLAUDE_PLUGIN_ROOT": str(root),
        "FAKE_DIR": (fake or tmp_path / "fake").as_posix(),
        **extra,
    }
    if engine is not None:
        env["DOC_GUARD_ENGINE"] = engine
    started = time.monotonic()
    done = subprocess.run(
        [_BASH, str(root / "hooks" / "session-start-sync.sh")],
        input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout, time.monotonic() - started


def _fake(tmp_path: Path, out: str | None = None, rc: int | None = None, sleep: int | None = None) -> Path:
    fake = tmp_path / "fake"
    fake.mkdir()
    if out is not None:
        (fake / "out").write_text(out, encoding="utf-8", newline="\n")
    if rc is not None:
        (fake / "rc").write_text(str(rc), encoding="utf-8", newline="\n")
    if sleep is not None:
        (fake / "sleep").write_text(str(sleep), encoding="utf-8", newline="\n")
    return fake


def _calls(fake: Path) -> list[str]:
    path = fake / "calls"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


# --- 지난 세션 기록 판정(원본의 CR 리터럴이 줄바꿈으로 깨진 일) -----------------------------


def test_hook_source_strips_cr_in_one_line():
    text = HOOK.read_bytes().decode("utf-8")
    assert "tr -d '\\r')\" = \"format=2\"" in text
    assert "tr -d '\r\n" not in text and "tr -d '\n" not in text


def test_crlf_carryover_record_with_failed_fetch_reports_cannot_judge(tmp_path):
    repo = _repo(tmp_path, "dead")
    record = repo / ".git" / "project-unfinished"
    record.write_bytes(b"format=2\r\nunstaged=README.md\r\n")
    fake = _fake(tmp_path)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "fetch 에 실패했습니다" in out
    assert "지난 작업 확인 불능" in out
    assert _calls(fake) == []  # fetch 가 실패하면 PR 블록은 아예 돌지 않는다


def test_lf_carryover_record_with_failed_fetch_also_reports(tmp_path):
    repo = _repo(tmp_path, "dead")
    (repo / ".git" / "project-unfinished").write_bytes(b"format=2\nunstaged=README.md\n")
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), _fake(tmp_path))
    assert "지난 작업 확인 불능" in out


def test_non_format2_record_with_failed_fetch_is_not_reported_as_cannot_judge(tmp_path):
    repo = _repo(tmp_path, "dead")
    (repo / ".git" / "project-unfinished").write_bytes(b"format=1\r\nx\r\n")
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), _fake(tmp_path))
    assert "지난 작업 확인 불능" not in out


# --- PR 블록 -------------------------------------------------------------------


def test_pr_block_shows_engine_output_and_passes_row_limit(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개 상태와 병합 순서\n\n| 순서 | PR |\n| 1 | #5 제목 |\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "o/r 내 PR 1개 상태와 병합 순서" in out and "#5 제목" in out
    assert "자세한 상태와 다음 할 일은 /harness:prs 로 봅니다." in out
    calls = _calls(fake)
    assert len(calls) == 1
    assert "--from fake-engine python -m checker.pr_queue --mine --quiet-empty --max-rows 10" in calls[0]


def test_pr_block_silent_when_no_open_pr(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "/harness:prs" not in out and "PR 상태" not in out
    assert len(_calls(fake)) == 1  # 엔진은 불렀다


def test_pr_block_engine_rc2_shows_engine_message(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="PR 상태 확인 불능 — 네트워크 실패\n", rc=2)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "PR 상태 확인 불능 — 네트워크 실패 다음: /harness:prs 로 다시 확인하십시오." in out


def test_pr_block_engine_rc1_is_cannot_check_not_pass(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="Traceback boom\n", rc=1)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "PR 상태 확인 불능(Traceback boom)" in out


def test_pr_block_engine_rc1_without_output_shows_exit_code(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, rc=1)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "PR 상태 확인 불능(종료코드 1)" in out


def test_pr_block_timeout_skips_with_one_line_and_warms_engine_in_background(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, sleep=30)
    out, elapsed = _start(tmp_path, repo, _shim_dir(tmp_path), fake, HARNESS_PR_TIMEOUT="1")
    assert "PR 상태 확인이 오래 걸려 건너뜀 — /harness:prs 로 확인하십시오." in out
    assert "확인 불능" not in out
    assert elapsed < 25
    deadline = time.monotonic() + 15
    warm: list[str] = []
    while time.monotonic() < deadline:
        warm = [c for c in _calls(fake) if c.startswith("warm:")]
        if warm:
            break
        time.sleep(0.3)
    assert warm and "--from fake-engine python" in warm[0]
    assert "checker.pr_queue" not in warm[0]


def test_pr_block_without_timeout_command_skips_with_one_line(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path, timeout=False), fake, hide_timeout=True)
    assert "PR 상태 확인을 건너뜁니다(timeout 명령이 없어" in out
    assert "o/r 내 PR 1개" not in out
    assert _calls(fake) == []


def test_pr_block_without_gh_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path, gh=False), fake)
    assert "PR 상태 확인 불능(uvx 나 gh 가 없음)" in out
    assert _calls(fake) == []


def test_pr_block_without_uvx_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path, uvx=False), _fake(tmp_path))
    assert "PR 상태 확인 불능(uvx 나 gh 가 없음)" in out


def test_pr_block_skipped_for_non_github_origin(tmp_path):
    repo = _repo(tmp_path, "other")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "PR 상태" not in out and "o/r 내 PR 1개" not in out
    assert _calls(fake) == []


def test_pr_block_engine_spec_failure_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    shim = _shim_dir(tmp_path, uv="#!/bin/sh\nexit 1\n")
    out, _ = _start(tmp_path, repo, shim, fake, engine=None)
    assert "PR 상태 확인 불능(검사 엔진의 판을 정하지 못함)" in out
    assert _calls(fake) == []
