"""세션 시작 훅의 scaffold 안내(#128) 테스트.

기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더)가 없는 저장소에서만
`/harness:scaffold` 를 안내하는지 `session-start-sync.sh` 를 임시 저장소에서 돌려 확인한다.
ensure-tools.sh 는 복사하지 않아(winget 설치를 시도한다) 도구 설치는 일어나지 않고,
원격이 없는 저장소라 fetch 도 하지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

pytestmark = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")

HINT = "기준 폴더(templates/ 와 rules/)가 없습니다."


@pytest.fixture(scope="module")
def session_plugin_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("hint-root") / "harness"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(PLUGIN_ROOT / "hooks" / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    (root / "console").mkdir()
    shutil.copy(PLUGIN_ROOT / "console" / "standards_scan.py", root / "console" / "standards_scan.py")
    return root


def _run(root: Path, cwd: Path, **extra_env: str) -> str:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root), **extra_env}
    env.pop("CLAUDE_PROJECT_DIR", None)
    if "HARNESS_NO_SCAFFOLD_HINT" not in extra_env:
        env.pop("HARNESS_NO_SCAFFOLD_HINT", None)
    done = subprocess.run(
        [_BASH, str(root / "hooks" / "session-start-sync.sh")],
        input=json.dumps({"cwd": str(cwd)}), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _standards(folder: Path) -> None:
    (folder / "templates").mkdir(parents=True)
    (folder / "rules").mkdir()


def test_기준_폴더가_없으면_scaffold_를_안내한다(session_plugin_root, tmp_path):
    out = _run(session_plugin_root, _git_repo(tmp_path))
    assert HINT in out
    line = next(l for l in out.splitlines() if HINT in l)
    assert "다음: /harness:scaffold" in line
    assert "현재 브랜치:" in out  # 다른 출력이 깨지지 않는다


def test_templates_만_있고_rules_가_없으면_안내한다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "templates").mkdir()
    assert HINT in _run(session_plugin_root, repo)


def test_꼭대기에_기준_폴더가_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    assert HINT not in _run(session_plugin_root, repo)


def test_하위_폴더에_기준_폴더가_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo / "customer-a" / "std")
    assert HINT not in _run(session_plugin_root, repo)


def test_하위_폴더에서_세션을_열어도_저장소_꼭대기_기준으로_본다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    (repo / "docs").mkdir()
    assert HINT not in _run(session_plugin_root, repo / "docs")


def test_node_modules_안의_기준_폴더는_세지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo / "node_modules" / "pkg")
    assert HINT in _run(session_plugin_root, repo)


def test_marketplace_json_이_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    assert HINT not in _run(session_plugin_root, repo)


def test_환경_변수로_안내를_끈다(session_plugin_root, tmp_path):
    out = _run(session_plugin_root, _git_repo(tmp_path), HARNESS_NO_SCAFFOLD_HINT="1")
    assert HINT not in out
    assert "현재 브랜치:" in out


def test_git_저장소가_아니면_안내하지_않는다(session_plugin_root, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    out = _run(session_plugin_root, plain)
    assert HINT not in out
    assert "git 저장소가 아닙니다" in out


FORMS_HINT = "templates/ 에 고객 양식 파일"


def test_준비됐는데_고객_양식_원본이_없으면_양식을_안내한다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    (repo / "templates" / "harness").mkdir()
    (repo / "templates" / "harness" / "base.xlsx").write_text("x", encoding="utf-8")  # 기본 틀은 고객 양식이 아니다
    (repo / "templates" / "~$임시.xlsx").write_text("x", encoding="utf-8")
    out = _run(session_plugin_root, repo)
    assert FORMS_HINT in out
    assert HINT not in out
    assert "현재 브랜치:" in out


def test_고객_양식_원본이_있으면_양식을_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    (repo / "templates" / "개발사양서.xlsx").write_text("x", encoding="utf-8")
    assert FORMS_HINT not in _run(session_plugin_root, repo)


def test_양식_안내는_환경_변수와_플러그인_저장소에서_끈다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    _standards(repo)
    assert FORMS_HINT not in _run(session_plugin_root, repo, HARNESS_NO_SCAFFOLD_HINT="1")
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
    assert FORMS_HINT not in _run(session_plugin_root, repo)


def test_양식_판정_스크립트가_없으면_양식을_안내하지_않는다(tmp_path):
    root = tmp_path / "bare" / "harness"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(PLUGIN_ROOT / "hooks" / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    repo = _git_repo(tmp_path)
    _standards(repo)
    out = _run(root, repo)  # 판정을 못 하면 "없음" 으로 말하지 않는다
    assert FORMS_HINT not in out
    assert "현재 브랜치:" in out


# ---- 시작 때 최신 받기 결과를 웹 콘솔에 알린다(#1059) ----

import http.server
import threading
import time


@pytest.fixture
def sync_plugin_root(tmp_path) -> Path:
    root = tmp_path / "sync-root" / "harness"
    (root / "hooks").mkdir(parents=True)
    (root / "console").mkdir()
    shutil.copy(PLUGIN_ROOT / "hooks" / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    shutil.copy(PLUGIN_ROOT / "console" / "start_sync_post.py", root / "console" / "start_sync_post.py")
    return root


class _FakeConsole:
    def __init__(self):
        self.got = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.got.append((self.path, json.loads(self.rfile.read(n).decode("utf-8"))))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def wait(self, timeout=60.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.got:
            time.sleep(0.1)
        return self.got

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def _run_with_session(root: Path, cwd: Path, **extra_env: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root), **extra_env}
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run([_BASH, str(root / "hooks" / "session-start-sync.sh")],
                          input=json.dumps({"cwd": str(cwd), "session_id": "sess-1", "hook_event_name": "SessionStart"}),
                          capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 콘솔로 보내는 스크립트를 돌릴 수 없다")
def test_원격이_없으면_콘솔에_확인_못_함으로_알린다(sync_plugin_root, tmp_path):
    fake = _FakeConsole()
    try:
        done = _run_with_session(sync_plugin_root, _git_repo(tmp_path), HARNESS_CONSOLE_PORT=str(fake.port))
        assert done.returncode == 0, done.stderr
        got = fake.wait()
    finally:
        fake.close()
    assert got, "콘솔이 결과를 받지 못했다"
    path, body = got[0]
    assert path == "/hooks/event" and body["hook_event_name"] == "HarnessStartSync" and body["session_id"] == "sess-1"
    assert body["state"] == "unknown" and body["reason"] and body["cwd"]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 콘솔로 보내는 스크립트를 돌릴 수 없다")
def test_원격과_같으면_콘솔에_됐음으로_알린다(sync_plugin_root, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    repo = _git_repo(tmp_path)
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(git + ["add", "."], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "feat/1-a"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "feat/1-a"], cwd=repo, check=True)
    fake = _FakeConsole()
    try:
        done = _run_with_session(sync_plugin_root, repo, HARNESS_CONSOLE_PORT=str(fake.port))
        assert done.returncode == 0, done.stderr
        got = fake.wait()
    finally:
        fake.close()
    assert got and got[0][1]["state"] == "ok" and "최신" in got[0][1]["reason"]


def test_콘솔이_없어도_훅_출력과_종료_코드는_그대로다(sync_plugin_root, session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    quiet = _run_with_session(sync_plugin_root, repo, HARNESS_CONSOLE_PORT="1")  # 아무도 듣지 않는 포트
    bare = _run_with_session(session_plugin_root, repo)  # 콘솔로 보내는 스크립트가 아예 없는 플러그인 폴더
    assert quiet.returncode == 0 and bare.returncode == 0
    same = lambda r, root: r.stdout.replace(str(root), "ROOT").replace("\\", "/")  # 플러그인 폴더 경로만 다르다
    assert same(quiet, sync_plugin_root) == same(bare, session_plugin_root) and "현재 브랜치:" in quiet.stdout
    assert quiet.stderr == bare.stderr


def test_콘솔로_보내는_스크립트는_입력이_이상해도_조용히_끝난다():
    for raw in (b"", b"not json", b"[1]", json.dumps({"cwd": "/x"}).encode()):
        done = subprocess.run([sys.executable, "-I", str(PLUGIN_ROOT / "console" / "start_sync_post.py"), "latest"], input=raw, capture_output=True, timeout=30)
        assert done.returncode == 0 and done.stdout == b"" and done.stderr == b""
