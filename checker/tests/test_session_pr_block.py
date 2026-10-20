"""세션 시작 훅의 "내 PR 상태" 블록(#370, #389)과 지난 세션 기록 판정 테스트.

PR 표는 뒤에서 만들어 `.git/harness-pr-table.<session_id>` 에 쓰고, 첫 프롬프트에 `pr_table_notice.py` 가 낸다.

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
    "env sleep cp find"
).split()
SID = "sess-1"

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
    # Linux 에서는 실행 권한이 없으면 PATH 의 shim 을 부를 수 없다(Windows bash 는 권한을 보지 않는다).
    for shim in bin_dir.iterdir():
        shim.chmod(0o755)
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
        input=json.dumps({"cwd": str(repo), "session_id": SID}), capture_output=True, text=True, encoding="utf-8",
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


def _result_file(repo: Path, sid: str = SID) -> Path:
    return repo / ".git" / f"harness-pr-table.{sid}"


def _wait_result(repo: Path, sid: str = SID, seconds: float = 20) -> str:
    """뒤에서 돈 엔진이 최종 파일을 쓸 때까지 기다려 내용을 돌려준다."""
    deadline = time.monotonic() + seconds
    path = _result_file(repo, sid)
    while time.monotonic() < deadline:
        if path.exists():
            return path.read_text(encoding="utf-8")
        time.sleep(0.2)
    raise AssertionError(f"결과 파일이 생기지 않았다: {sorted(p.name for p in (repo / '.git').iterdir())}")


def test_pr_block_runs_in_background_and_writes_result_file(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개 상태와 병합 순서\n\n| 순서 | PR |\n| 1 | #5 제목 |\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    # 세션 시작 출력에는 표가 없고 "뒤에서 확인 중" 한 줄만 있다. 없음·문제없음으로 읽히는 말은 없다.
    assert "내 PR 상태를 뒤에서 확인하는 중입니다" in out
    assert "#5 제목" not in out and "문제없" not in out and "확인 불능" not in out
    text = _wait_result(repo)
    assert text.startswith("rc=0\n")
    assert "o/r 내 PR 1개 상태와 병합 순서" in text and "#5 제목" in text
    assert not (repo / ".git" / f"harness-pr-table.{SID}.tmp").exists()
    calls = _calls(fake)
    assert len(calls) == 1
    assert "--from fake-engine python -m checker.pr_queue --mine --quiet-empty --max-rows 10" in calls[0]


def test_pr_block_does_not_wait_for_engine(tmp_path):
    repo = _repo(tmp_path, "github")
    # 엔진이 20초 걸려도 훅은 먼저 끝난다. Windows 에서는 git 프로세스 기동만으로 몇 초가 걸리므로
    # 한계를 엔진 시간보다 한참 아래로 잡는다(기다렸다면 20초를 넘는다).
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0, sleep=20)
    out, elapsed = _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert "내 PR 상태를 뒤에서 확인하는 중입니다" in out
    assert elapsed < 15, f"훅이 엔진을 기다렸다: {elapsed:.1f}초"
    assert not _result_file(repo).exists()  # 아직 진행 중
    assert _wait_result(repo, seconds=40).startswith("rc=")


def test_pr_block_empty_output_is_recorded_as_rc0_without_body(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="", rc=0)
    _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert _wait_result(repo) == "rc=0\n"


def test_pr_block_records_engine_failure_code_and_output(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="Traceback boom\n", rc=1)
    _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    assert _wait_result(repo) == "rc=1\nTraceback boom\n"


def test_pr_block_timeout_is_recorded_as_rc124(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, sleep=30)
    _, elapsed = _start(tmp_path, repo, _shim_dir(tmp_path), fake, HARNESS_PR_TIMEOUT="1")
    assert elapsed < 15
    assert _wait_result(repo).startswith("rc=124\n")


def test_pr_block_without_timeout_command_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path, timeout=False), fake, hide_timeout=True)
    assert ("PR 상태 확인 불능(timeout 명령이 없어 시간을 제한할 수 없음) - /harness:prs 로 다시 확인하십시오."
            in out)
    assert "뒤에서 확인하는 중" not in out
    assert _calls(fake) == []
    assert not list((repo / ".git").glob("harness-pr-table.*"))


def test_pr_block_without_session_id_is_cannot_check_and_runs_nothing(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    shim = _shim_dir(tmp_path)
    root = tmp_path / "plugin-root" / "harness"
    (root / "hooks").mkdir(parents=True)
    (root / "hooks" / "session-start-sync.sh").write_bytes(HOOK.read_bytes().replace(b"\r\n", b"\n"))
    env = {"PATH": str(shim), "HOME": str(tmp_path), "HARNESS_NO_SCAFFOLD_HINT": "1", "CLAUDE_PLUGIN_ROOT": str(root),
           "FAKE_DIR": fake.as_posix(), "DOC_GUARD_ENGINE": "fake-engine"}
    done = subprocess.run([_BASH, str(root / "hooks" / "session-start-sync.sh")], input=json.dumps({"cwd": str(repo)}),
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    # 첫 프롬프트 훅이 찾을 이름이 없으므로 뒤 실행을 하지 않고 바로 불능으로 낸다.
    assert "PR 상태 확인 불능(세션 ID 를 받지 못함)" in done.stdout
    assert "뒤에서 확인하는 중" not in done.stdout
    assert not list((repo / ".git").glob("harness-pr-table.*"))
    assert _calls(fake) == []


def test_pr_block_removes_result_files_older_than_a_day(tmp_path):
    repo = _repo(tmp_path, "github")
    old = repo / ".git" / "harness-pr-table.old-session"
    old.write_text("rc=0\n", encoding="utf-8")
    fresh = repo / ".git" / "harness-pr-table.fresh-session"
    fresh.write_text("rc=0\n", encoding="utf-8")
    two_days_ago = time.time() - 2 * 86400
    os.utime(old, (two_days_ago, two_days_ago))
    fake = _fake(tmp_path, out="", rc=0)
    _start(tmp_path, repo, _shim_dir(tmp_path), fake)
    _wait_result(repo)
    assert not old.exists()
    assert fresh.exists()


def test_pr_block_without_gh_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    out, _ = _start(tmp_path, repo, _shim_dir(tmp_path, gh=False), fake)
    assert "PR 상태 확인 불능(uvx 나 gh 가 없음)" in out
    assert _calls(fake) == []
    assert not _result_file(repo).exists()


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
    assert not list((repo / ".git").glob("harness-pr-table.*"))


def test_pr_block_engine_spec_failure_is_cannot_check(tmp_path):
    repo = _repo(tmp_path, "github")
    fake = _fake(tmp_path, out="o/r 내 PR 1개\n", rc=0)
    shim = _shim_dir(tmp_path, uv="#!/bin/sh\nexit 1\n")
    out, _ = _start(tmp_path, repo, shim, fake, engine=None)
    assert "PR 상태 확인 불능(검사 엔진의 판을 정하지 못함)" in out
    assert _calls(fake) == []
