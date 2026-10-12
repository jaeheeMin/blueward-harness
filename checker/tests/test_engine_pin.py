"""#149 — 엔진을 plugin.json version 태그로 고정하고, caller 는 stable 을 부른다.

세 갈래를 본다.
- 훅(py 둘, sh 하나)과 스킬이 엔진 판을 `engine_spec.py` 한 곳에서 얻는다. version 을 못 읽으면
  `@main` 으로 넘어가지 않고 검사 불능으로 막는다.
- 재사용 워크플로의 `engine-ref` 기본값과 scaffold caller 가 `stable` 이다.
- `release-tag.yml` 의 구조와, 안의 셸 스크립트가 실제 git 저장소에서 하는 일.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = ROOT / "plugins" / "harness"
HOOKS = PLUGIN_ROOT / "hooks"
WORKFLOWS = ROOT / ".github" / "workflows"
SKELETON_WORKFLOWS = PLUGIN_ROOT / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows"
REPO_URL = "git+https://github.com/jaeheeMin/blueward-harness"


def _load_engine_spec():
    spec = importlib.util.spec_from_file_location("engine_spec_under_test", HOOKS / "engine_spec.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


engine_spec = _load_engine_spec()


def _plugin_version() -> str:
    return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("DOC_GUARD_ENGINE", raising=False)


# --- engine_spec.py ---------------------------------------------------------


def test_엔진_주소는_plugin_json_version_의_태그다():
    assert engine_spec.engine_spec() == f"{REPO_URL}@v{_plugin_version()}"


def test_DOC_GUARD_ENGINE_이_있으면_그것이_우선이다(monkeypatch):
    monkeypatch.setenv("DOC_GUARD_ENGINE", "/local/checkout")
    assert engine_spec.engine_spec() == "/local/checkout"


def test_다른_plugin_json_의_version_을_따른다(tmp_path):
    pj = tmp_path / "plugin.json"
    pj.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")
    assert engine_spec.engine_spec(pj) == f"{REPO_URL}@v1.2.3"


@pytest.mark.parametrize(
    "text",
    ["", "{깨짐", "{}", json.dumps({"version": 3}), json.dumps({"version": "latest"}),
     json.dumps({"version": "v0.1.0"}), json.dumps({"version": "0.1\n"})],
)
def test_version_을_못_읽으면_main_으로_넘어가지_않고_실패한다(tmp_path, text):
    pj = tmp_path / "plugin.json"
    pj.write_text(text, encoding="utf-8")
    with pytest.raises(engine_spec.EngineSpecError):
        engine_spec.engine_spec(pj)


def test_plugin_json_이_없어도_실패한다(tmp_path):
    with pytest.raises(engine_spec.EngineSpecError):
        engine_spec.engine_spec(tmp_path / "없음.json")


def test_태그_고정일_때만_태그_없음_단서를_낸다():
    assert "v0.10.54" in engine_spec.tag_hint(f"{REPO_URL}@v0.10.54")
    assert "태그" in engine_spec.tag_hint(f"{REPO_URL}@v0.10.54")
    assert engine_spec.tag_hint("/local/checkout") == ""
    assert engine_spec.tag_hint(f"{REPO_URL}@main") == ""


def test_CLI_는_주소를_찍고_못_읽으면_종료코드_2다(tmp_path):
    ok = subprocess.run([sys.executable, str(HOOKS / "engine_spec.py")], capture_output=True, text=True,
                        encoding="utf-8", env={k: v for k, v in os.environ.items() if k != "DOC_GUARD_ENGINE"})
    assert ok.returncode == 0
    assert ok.stdout.strip() == f"{REPO_URL}@v{_plugin_version()}"

    # plugin.json 이 없는 위치로 복사하면 못 읽는다.
    shutil.copy(HOOKS / "engine_spec.py", tmp_path / "engine_spec.py")
    bad = subprocess.run([sys.executable, str(tmp_path / "engine_spec.py")], capture_output=True, text=True,
                         encoding="utf-8", env={k: v for k, v in os.environ.items() if k != "DOC_GUARD_ENGINE"})
    assert bad.returncode == 2
    assert bad.stdout.strip() == ""
    assert "검사 엔진 판을 정하지 못했다" in bad.stderr


# --- 훅과 스킬이 모두 이 한 곳을 쓴다 ----------------------------------------


@pytest.mark.parametrize("name", ["pre_write_guard.py", "mcp_source_guard.py", "pre-bash-git-guard.sh"])
def test_훅에_main_엔진_주소가_남아_있지_않다(name):
    text = (HOOKS / name).read_text(encoding="utf-8")
    assert "blueward-harness@main" not in text
    assert "engine_spec" in text


@pytest.mark.parametrize("name", ["srs", "spec"])
def test_스킬이_main_엔진_주소를_쓰지_않고_engine_spec_을_부른다(name):
    text = (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert "blueward-harness@main" not in text
    assert "hooks/engine_spec.py" in text


def test_저장소_어디에도_엔진을_main_으로_받는_주소가_없다():
    hits = []
    for base in (PLUGIN_ROOT, ROOT / ".github", ROOT / "checker", ROOT / "scripts"):
        for p in base.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts or p.suffix in {".pyc", ".xlsx", ".docx", ".pptx"}:
                continue
            if p.name == "test_engine_pin.py":
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if "blueward-harness@main" in text or ".yml@main" in text:
                hits.append(str(p.relative_to(ROOT)))
    assert hits == []


@pytest.mark.parametrize("name", ["pre_write_guard.py", "mcp_source_guard.py"])
def test_py_훅은_version_을_못_읽으면_검사_불능으로_거부한다(tmp_path, name):
    # plugin.json 이 없는 곳에 훅 폴더만 복사해 "설치가 깨진" 상태를 만든다.
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        f"import {name[:-3]} as m; m.engine_spec()"
    )
    env = {k: v for k, v in os.environ.items() if k != "DOC_GUARD_ENGINE"}
    env["PYTHONIOENCODING"] = "utf-8"  # main() 이 하는 입출력 UTF-8 고정을 대신한다
    done = subprocess.run([sys.executable, "-c", code, str(hooks)], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=60)
    out = json.loads(done.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "판을 정하지 못해" in reason and "다음:" in reason
    assert "@main" not in reason


@pytest.mark.parametrize("name", ["pre_write_guard.py", "mcp_source_guard.py"])
def test_py_훅_엔진_주소가_version_태그다(name):
    spec = importlib.util.spec_from_file_location(f"hook_{name[:-3]}", HOOKS / name)
    sys.path.insert(0, str(HOOKS))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(HOOKS))
    assert mod.engine_spec() == f"{REPO_URL}@v{_plugin_version()}"
    assert "태그" in mod.engine_hint()


def _find_bash() -> str | None:
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            c = Path(base) / "Git" / "bin" / "bash.exe"
            if c.is_file():
                return str(c)
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash")


_BASH = _find_bash()


@pytest.mark.skipif(_BASH is None, reason="bash 가 없으면 sh 훅을 돌려 볼 수 없다")
@pytest.mark.skipif(shutil.which("jq") is None, reason="jq 가 없으면 훅이 gh 명령을 거부만 한다")
@pytest.mark.skipif(shutil.which("uv") is None or shutil.which("uvx") is None, reason="uv 가 필요하다")
def test_sh_훅은_version_을_못_읽으면_검사_불능으로_거부한다(tmp_path):
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOKS, hooks, ignore=shutil.ignore_patterns("__pycache__"))
    env = {k: v for k, v in os.environ.items() if k != "DOC_GUARD_ENGINE"}
    done = subprocess.run(
        [_BASH, str(hooks / "pre-bash-git-guard.sh")],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "gh pr merge 123 -R owner/repo"},
                          "cwd": str(tmp_path)}),
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=180,
    )
    out = json.loads(done.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "엔진의 판을 정하지 못했습니다" in reason and "다음:" in reason
    assert "@main" not in reason


# --- caller 와 재사용 워크플로 ------------------------------------------------


def _on(wf: dict) -> dict:
    return wf.get("on", wf.get(True))


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_재사용_워크플로의_engine_ref_기본값은_stable_이다(path):
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    call = (_on(wf) or {}).get("workflow_call")
    if not isinstance(call, dict) or "engine-ref" not in (call.get("inputs") or {}):
        pytest.skip("engine-ref 입력이 없는 워크플로")
    assert call["inputs"]["engine-ref"]["default"] == "stable"


def test_engine_ref_를_가진_워크플로가_있다():
    names = []
    for path in WORKFLOWS.glob("*.yml"):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        call = (_on(wf) or {}).get("workflow_call")
        if isinstance(call, dict) and "engine-ref" in (call.get("inputs") or {}):
            names.append(path.name)
    assert len(names) >= 5


@pytest.mark.parametrize("path", sorted(SKELETON_WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_scaffold_caller_는_stable_을_부른다(path):
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    uses = [j["uses"] for j in wf["jobs"].values() if "uses" in j]
    assert uses, "caller 가 재사용 워크플로를 부르지 않는다"
    for u in uses:
        assert u.startswith("jaeheeMin/blueward-harness/.github/workflows/")
        assert u.endswith("@stable")


# --- release-tag.yml ---------------------------------------------------------

RELEASE_TAG = WORKFLOWS / "release-tag.yml"


@pytest.fixture(scope="module")
def release_wf() -> dict:
    return yaml.safe_load(RELEASE_TAG.read_text(encoding="utf-8"))


def _script(wf: dict) -> str:
    steps = wf["jobs"]["tag"]["steps"]
    return next(s["run"] for s in steps if s.get("id") == "tag")


def _reusable_workflow_files() -> set[str]:
    found = set()
    for path in WORKFLOWS.glob("*.yml"):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = _on(wf)
        if isinstance(triggers, dict) and "workflow_call" in triggers:
            found.add(f".github/workflows/{path.name}")
    return found


def test_release_tag_는_배포되는_파일_변경과_수동_실행으로_돈다(release_wf):
    on = _on(release_wf)
    assert on["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in on
    paths = on["push"]["paths"]
    for needed in ("plugins/harness/**", "checker/**", "pyproject.toml", "uv.lock", "scripts/**"):
        assert needed in paths
    # 배포물이 아닌 시험과 checker 안의 문서는 빼야 version 을 안 올린 push 가 실패로 번지지 않는다.
    assert paths.index("!checker/tests/**") > paths.index("checker/**")
    assert paths.index("!checker/**/*.md") > paths.index("checker/**")


def test_release_tag_paths_가_재사용_워크플로_전부를_담는다():
    # 재사용 워크플로가 새로 생기거나 사라지면 paths 와 PR 검사가 어긋나므로 여기서 잡는다.
    wf = yaml.safe_load(RELEASE_TAG.read_text(encoding="utf-8"))
    listed = {p for p in _on(wf)["push"]["paths"] if p.startswith(".github/workflows/")}
    assert listed == _reusable_workflow_files()
    assert len(listed) >= 6


def _paths_match(patterns: list[str], f: str) -> bool:
    """GitHub paths 필터를 흉내 낸다: 앞에서부터 보며 일반 패턴이 맞으면 켜고 ! 패턴이 맞으면 끈다."""
    import re

    def to_re(pat: str):
        out, i = "", 0
        while i < len(pat):
            if pat.startswith("**/", i):
                out += "(?:.*/)?"
                i += 3
            elif pat.startswith("**", i):
                out += ".*"
                i += 2
            elif pat[i] == "*":
                out += "[^/]*"
                i += 1
            else:
                out += re.escape(pat[i])
                i += 1
        return re.compile(out + r"\Z")

    on = False
    for pat in patterns:
        if pat.startswith("!"):
            if to_re(pat[1:]).match(f):
                on = False
        elif to_re(pat).match(f):
            on = True
    return on


def test_release_tag_paths_가_PR_검사의_배포_범위와_같다():
    from checker.plugin_version import _is_released

    wf = yaml.safe_load(RELEASE_TAG.read_text(encoding="utf-8"))
    paths = _on(wf)["push"]["paths"]
    reusable = frozenset(_reusable_workflow_files())
    samples = [
        "plugins/harness/skills/start/SKILL.md", "plugins/harness/.claude-plugin/plugin.json",
        "checker/engine.py", "checker/README.md", "checker/tests/test_x.py", "checker/sub/NOTES.md",
        "pyproject.toml", "uv.lock", "scripts/risk_gate.py", ".github/workflows/doc-guard.yml",
        ".github/workflows/checker.yml", ".github/workflows/release-tag.yml", "docs/status.md", "README.md",
    ]
    for f in samples:
        assert _paths_match(paths, f) == _is_released(f, reusable), f


def test_release_tag_는_contents_와_issues_쓰기_권한만_가진다(release_wf):
    assert release_wf["permissions"] == {"contents": "write", "issues": "write"}


def test_release_tag_는_실패하거나_건너뛰면_owner_에게_이슈를_만든다(release_wf):
    notify = release_wf["jobs"]["tag"]["steps"][-1]
    assert "failure()" in notify["if"] and "steps.tag.outputs.problem" in notify["if"]
    assert notify["env"]["GH_REPO"] == "${{ github.repository }}"
    assert notify["env"]["OWNER"] == "${{ github.repository_owner }}"
    assert '--assignee "$OWNER"' in notify["run"]
    assert "gh issue comment" in notify["run"]  # 열린 알림 이슈가 있으면 코멘트만


def test_release_tag_는_main_에서만_돌고_이력과_태그를_받는다(release_wf):
    job = release_wf["jobs"]["tag"]
    assert job["if"] == "github.ref == 'refs/heads/main'"
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0


def test_release_tag_실행이_겹치지_않게_줄_세운다(release_wf):
    assert release_wf["concurrency"] == {"group": "release-tag", "cancel-in-progress": False}


@pytest.mark.skipif(_BASH is None, reason="bash 가 없으면 스크립트를 돌려 볼 수 없다")
class TestReleaseTagScript:
    """워크플로의 run 스크립트를 실제 git 저장소(원격은 bare 저장소)에서 돌린다."""

    @pytest.fixture
    def env(self, tmp_path, release_wf):
        origin = tmp_path / "origin.git"
        work = tmp_path / "work"
        self._git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
        self._git(tmp_path, "clone", "-q", str(origin), str(work))
        script = _script(release_wf).replace("python3", f'"{Path(sys.executable).as_posix()}"')
        (tmp_path / "run.sh").write_text(script, encoding="utf-8", newline="\n")
        self.tmp, self.origin, self.work = tmp_path, origin, work
        self.output = tmp_path / "gh_output.txt"
        self.output.write_text("", encoding="utf-8")
        return self

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        done = subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return done.stdout.strip()

    def commit(self, version: str | None, message: str = "c") -> str:
        pj = self.work / "plugins" / "harness" / ".claude-plugin" / "plugin.json"
        pj.parent.mkdir(parents=True, exist_ok=True)
        if version is not None:
            pj.write_text(json.dumps({"name": "harness", "version": version}), encoding="utf-8", newline="\n")
        (self.work / "f.txt").write_text(message + os.urandom(4).hex(), encoding="utf-8")
        self._git(self.work, "add", "-A")
        self._git(self.work, "commit", "-q", "-m", message)
        self._git(self.work, "push", "-q", "origin", "HEAD:main")
        return self._git(self.work, "rev-parse", "HEAD")

    def run(self, sha: str) -> subprocess.CompletedProcess:
        # Actions 의 checkout 처럼 그 커밋의 작업 트리에서 돈다.
        self._git(self.work, "checkout", "-q", "--detach", sha)
        return subprocess.run(
            [_BASH, str(self.tmp / "run.sh")], cwd=self.work, capture_output=True, text=True,
            encoding="utf-8", env={**os.environ, "GITHUB_SHA": sha, "GITHUB_OUTPUT": str(self.output),
                                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
                                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com"},
            timeout=120,
        )

    def problem(self) -> str:
        for line in self.output.read_text(encoding="utf-8").splitlines():
            if line.startswith("problem="):
                return line[len("problem="):]
        return ""

    def remote_tag(self, name: str) -> str:
        done = subprocess.run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{name}^{{commit}}"],
                              cwd=self.origin, capture_output=True, text=True, encoding="utf-8")
        return done.stdout.strip()

    def test_새_version_이면_태그를_붙이고_stable_을_옮긴다(self, env):
        sha = env.commit("0.10.54")
        done = env.run(sha)
        assert done.returncode == 0, done.stderr
        assert env.remote_tag("v0.10.54") == sha
        assert env.remote_tag("stable") == sha

    def test_다음_version_이면_stable_만_앞으로_옮긴다(self, env):
        first = env.commit("0.10.54")
        assert env.run(first).returncode == 0
        second = env.commit("0.10.55")
        done = env.run(second)
        assert done.returncode == 0, done.stderr
        assert env.remote_tag("v0.10.54") == first
        assert env.remote_tag("v0.10.55") == second
        assert env.remote_tag("stable") == second

    def test_같은_커밋에_다시_돌려도_성공한다(self, env):
        sha = env.commit("0.10.54")
        assert env.run(sha).returncode == 0
        again = env.run(sha)
        assert again.returncode == 0, again.stderr
        assert env.remote_tag("stable") == sha

    def test_같은_version_태그가_다른_커밋에_있으면_실패한다(self, env):
        first = env.commit("0.10.54")
        assert env.run(first).returncode == 0
        second = env.commit(None, "version 을 안 올린 변경")
        done = env.run(second)
        assert done.returncode == 1
        assert "version 을 올리지 않고 병합" in done.stdout + done.stderr
        assert "version 을 올리지 않고 병합" in env.problem()  # 알림 단계가 읽는 사유
        assert env.remote_tag("v0.10.54") == first  # 태그는 옮기지 않는다
        assert env.remote_tag("stable") == first

    def test_모양이_틀린_version_은_실패한다(self, env):
        sha = env.commit("latest")
        done = env.run(sha)
        assert done.returncode == 1
        assert env.remote_tag("stable") == ""
        assert "version 을 읽지 못했" in env.problem()

    def test_오래된_실행이_stable_을_되돌리지_않는다(self, env):
        older = env.commit("0.10.54")
        newer = env.commit("0.10.55")
        assert env.run(newer).returncode == 0
        done = env.run(older)
        assert done.returncode == 0, done.stderr
        assert env.remote_tag("stable") == newer
        assert env.remote_tag("v0.10.54") == older
        assert "조상이 아니라 옮기지 않았다" in env.problem()  # 건너뜀도 알림 사유를 남긴다

    def test_정상이면_알림_사유를_남기지_않는다(self, env):
        sha = env.commit("0.10.54")
        assert env.run(sha).returncode == 0
        assert env.problem() == ""

    def test_밀려난_중간_판의_태그를_다음_실행이_보충한다(self, env):
        first = env.commit("0.10.54")
        assert env.run(first).returncode == 0
        middle = env.commit("0.10.55")  # 이 커밋의 실행이 밀려나 돌지 않았다고 본다
        env.commit(None, "version 은 그대로인 변경")
        last = env.commit("0.10.56")
        done = env.run(last)
        assert done.returncode == 0, done.stderr
        assert env.remote_tag("v0.10.55") == middle
        assert env.remote_tag("v0.10.56") == last
        assert env.remote_tag("stable") == last

    def test_stable_이_없으면_이력_전체를_태깅하지_않는다(self, env):
        old = env.commit("0.10.50")
        last = env.commit("0.10.51")
        assert env.run(last).returncode == 0
        assert env.remote_tag("v0.10.51") == last
        assert env.remote_tag("v0.10.50") == ""
        assert old
