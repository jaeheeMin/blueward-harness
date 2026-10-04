"""gitleaks 비밀정보 검사(#159) 테스트.

`scripts/gitleaks_scan.sh` 의 종료 코드 분기(통과·유출·검사 불능)를 가짜 gitleaks 로 확인하고,
워크플로·기본 설정 파일의 모양을 고정한다. 진짜 gitleaks 로 SAP 규칙을 확인하는 테스트는
환경 변수 `GITLEAKS_BIN` 이 실행 파일을 가리킬 때만 돈다(없으면 건너뜀).
"""
from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "gitleaks_scan.sh"
WORKFLOW = REPO / ".github" / "workflows" / "gitleaks.yml"
SKELETON_WORKFLOW = REPO / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows" / "gitleaks.yml"
HARNESS_CONFIG = REPO / "checker" / "gitleaks" / "harness.toml"
HARNESS_CONFIG_REL = ".harness-engine/checker/gitleaks/harness.toml"

needs_bash = pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")


# ---- 워크플로·설정 파일의 모양 ----

def test_재사용_워크플로는_바이너리를_버전과_해시로_고정하고_gitleaks_action_을_쓰지_않는다():
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert "workflow_call" in data[True]
    env = data["jobs"]["gitleaks"]["env"]
    assert str(env["GITLEAKS_VERSION"]).count(".") == 2
    assert len(env["GITLEAKS_SHA256"]) == 64
    assert "sha256sum -c" in text
    assert "gitleaks/gitleaks-action" not in text
    assert "fetch-depth: 0" in text
    assert "scripts/gitleaks_scan.sh" in text


def test_호출_워크플로는_스켈레톤에_있고_재사용_워크플로를_한_줄로_부른다():
    data = yaml.safe_load(SKELETON_WORKFLOW.read_text(encoding="utf-8"))
    job = data["jobs"]["gitleaks"]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/gitleaks.yml@main"
    assert job["permissions"] == {"contents": "read"}
    assert set(data[True]) == {"pull_request", "push"}


def test_기본_설정은_기본_규칙을_이어받고_SAP_규칙을_더한다():
    cfg = tomllib.loads(HARNESS_CONFIG.read_text(encoding="utf-8"))
    assert cfg["extend"]["useDefault"] is True
    ids = {r["id"] for r in cfg["rules"]}
    assert {"sap-mysapsso2-cookie", "sap-sessionid-cookie", "sap-password-assignment"} <= ids


# ---- 판정 스크립트(가짜 gitleaks) ----

def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path):
    """커밋 둘(c1, c2)이 있는 저장소와 하네스 기본 설정이 놓인 작업 폴더."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "core.autocrlf", "false")
    (work / "a.txt").write_text("a\n", encoding="utf-8")
    _git(work, "add", "a.txt")
    _git(work, "commit", "-q", "-m", "c1")
    c1 = _git(work, "rev-parse", "HEAD")
    (work / "b.txt").write_text("b\n", encoding="utf-8")
    _git(work, "add", "b.txt")
    _git(work, "commit", "-q", "-m", "c2")
    c2 = _git(work, "rev-parse", "HEAD")
    cfg = work / HARNESS_CONFIG_REL
    cfg.parent.mkdir(parents=True)
    cfg.write_text("title = 'x'\n", encoding="utf-8")
    return work, c1, c2


def _fake_gitleaks(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-gitleaks"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > \"$FAKE_LOG\"\n"
        "while [ $# -gt 0 ]; do if [ \"$1\" = \"--config\" ]; then cp \"$2\" \"$FAKE_CFG_COPY\"; fi; shift; done\n"
        "exit \"${FAKE_CODE:-0}\"\n",
        encoding="utf-8", newline="\n",
    )
    return fake


def _run(work: Path, tmp_path: Path, code: int = 0, **env: str):
    log = tmp_path / "fake.log"
    out = tmp_path / "github_output"
    full = {
        **os.environ,
        "GITLEAKS_BIN": _fake_gitleaks(tmp_path).as_posix(),
        "FAKE_CODE": str(code), "FAKE_LOG": log.as_posix(),
        "FAKE_CFG_COPY": (tmp_path / "cfg.copy").as_posix(),
        "GITHUB_OUTPUT": out.as_posix(),
        "REPORT_PATH": (tmp_path / "report.json").as_posix(),
        **env,
    }
    done = subprocess.run([_BASH, str(SCRIPT)], cwd=work, env=full, capture_output=True, text=True, encoding="utf-8")
    result = None
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.startswith("result="):
                result = line.split("=", 1)[1]
    args = log.read_text(encoding="utf-8").strip() if log.exists() else None
    return done, result, args


@needs_bash
def test_종료코드_0_은_통과(repo, tmp_path):
    work, c1, c2 = repo
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=c1, HEAD_SHA=c2)
    assert done.returncode == 0, done.stdout + done.stderr
    assert result == "clean"
    assert "통과" in done.stdout
    # 값을 가리고, 유출 전용 종료코드를 지정하고, PR 범위만 훑는다.
    assert "--redact" in args and "--exit-code 2" in args
    assert f"--log-opts {c1}..{c2}" in args
    assert f"--config {HARNESS_CONFIG_REL}" in args


@needs_bash
def test_종료코드_2_는_유출_발견으로_실패한다(repo, tmp_path):
    work, c1, c2 = repo
    done, result, _ = _run(work, tmp_path, 2, EVENT_NAME="pull_request", BASE_SHA=c1, HEAD_SHA=c2)
    assert done.returncode == 1
    assert result == "leak"
    assert "유출 발견" in done.stdout
    assert "검사 불능" not in done.stdout


@needs_bash
@pytest.mark.parametrize("code", [1, 126, 127, 3, 137])
def test_그_밖의_종료코드는_검사_불능으로_실패하고_유출과_메시지가_다르다(repo, tmp_path, code):
    work, c1, c2 = repo
    done, result, _ = _run(work, tmp_path, code, EVENT_NAME="pull_request", BASE_SHA=c1, HEAD_SHA=c2)
    assert done.returncode == 1
    assert result == "error"
    assert "검사 불능" in done.stdout
    assert f"종료코드 {code}" in done.stdout
    assert "유출 발견" not in done.stdout


@needs_bash
def test_push_는_체크아웃된_gitleaks_toml_이_있으면_그것을_쓴다(repo, tmp_path):
    work, c1, c2 = repo
    (work / ".gitleaks.toml").write_text("title = 'proj'\n", encoding="utf-8")
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="push", BASE_SHA=c1, HEAD_SHA=c2)
    assert result == "clean"
    assert "--config .gitleaks.toml" in args
    assert HARNESS_CONFIG_REL in done.stdout  # 이어받는 방법을 안내한다


ALLOW_ALL = "[allowlist]\npaths = ['''.*''']\n"


def _commit_config(work: Path, text: str | None) -> str:
    """.gitleaks.toml 을 text 로 쓰고(None 이면 지우고) 커밋한 뒤 그 커밋을 돌려준다."""
    path = work / ".gitleaks.toml"
    if text is None:
        _git(work, "rm", "-q", ".gitleaks.toml")
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
        _git(work, "add", ".gitleaks.toml")
    _git(work, "commit", "-q", "-m", "cfg")
    return _git(work, "rev-parse", "HEAD")


@needs_bash
def test_PR_은_head_가_아니라_base_의_gitleaks_toml_로_검사하고_변경을_경고한다(repo, tmp_path):
    work, c1, c2 = repo
    base = _commit_config(work, "title = 'base'\n")
    head = _commit_config(work, "title = 'head'\n" + ALLOW_ALL)
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=base, HEAD_SHA=head)
    assert result == "clean"
    assert "--config .gitleaks.toml" not in args  # 체크아웃된(= head 의) 파일이 아니다
    assert (tmp_path / "cfg.copy").read_text(encoding="utf-8") == "title = 'base'\n"
    assert "::warning" in done.stdout and "병합 뒤부터 적용" in done.stdout


@needs_bash
def test_PR_이_gitleaks_toml_을_안_바꾸면_경고_없이_base_설정을_쓴다(repo, tmp_path):
    work, c1, c2 = repo
    base = _commit_config(work, "title = 'base'\n")
    (work / "c.txt").write_text("c\n", encoding="utf-8")
    _git(work, "add", "c.txt")
    _git(work, "commit", "-q", "-m", "c")
    head = _git(work, "rev-parse", "HEAD")
    done, result, _ = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=base, HEAD_SHA=head)
    assert result == "clean"
    assert (tmp_path / "cfg.copy").read_text(encoding="utf-8") == "title = 'base'\n"
    assert "::warning" not in done.stdout


@needs_bash
def test_base_에_gitleaks_toml_이_없으면_PR_이_추가해도_하네스_기본_설정을_쓴다(repo, tmp_path):
    work, c1, c2 = repo
    head = _commit_config(work, "title = 'head'\n" + ALLOW_ALL)
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=c2, HEAD_SHA=head)
    assert result == "clean"
    assert f"--config {HARNESS_CONFIG_REL}" in args
    assert "::warning" in done.stdout


@needs_bash
def test_PR_이_gitleaks_toml_을_지워도_base_설정을_쓴다(repo, tmp_path):
    work, c1, c2 = repo
    base = _commit_config(work, "title = 'base'\n")
    head = _commit_config(work, None)
    done, result, _ = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=base, HEAD_SHA=head)
    assert result == "clean"
    assert (tmp_path / "cfg.copy").read_text(encoding="utf-8") == "title = 'base'\n"
    assert "::warning" in done.stdout


@needs_bash
def test_하네스_설정도_없으면_검사_불능(repo, tmp_path):
    work, c1, c2 = repo
    (work / HARNESS_CONFIG_REL).unlink()
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=c1, HEAD_SHA=c2)
    assert result == "error" and done.returncode == 1
    assert args is None  # gitleaks 를 부르지 않았다


@needs_bash
def test_없는_커밋_범위는_통과가_아니라_검사_불능(repo, tmp_path):
    # gitleaks 자체는 없는 범위에도 "0 commits scanned" 로 종료코드 0 을 낸다 — 스크립트가 먼저 막아야 한다.
    work, c1, c2 = repo
    bogus = "deadbeef" * 5
    for base, head in ((bogus, c2), (c1, bogus), ("", c2)):
        done, result, args = _run(work, tmp_path, 0, EVENT_NAME="pull_request", BASE_SHA=base, HEAD_SHA=head)
        assert result == "error" and done.returncode == 1, (base, head)
        assert args is None


@needs_bash
def test_git_저장소가_아니면_검사_불능(tmp_path):
    work = tmp_path / "plain"
    work.mkdir()
    done, result, _ = _run(work, tmp_path, 0, EVENT_NAME="push", BASE_SHA="", HEAD_SHA="abc",
                           GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert result == "error" and done.returncode == 1


@needs_bash
def test_지원하지_않는_이벤트는_검사_불능(repo, tmp_path):
    work, c1, c2 = repo
    done, result, _ = _run(work, tmp_path, 0, EVENT_NAME="schedule", BASE_SHA=c1, HEAD_SHA=c2)
    assert result == "error" and done.returncode == 1


@needs_bash
def test_push_는_이전_커밋부터_새_커밋까지를_본다(repo, tmp_path):
    work, c1, c2 = repo
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="push", BASE_SHA=c1, HEAD_SHA=c2)
    assert result == "clean"
    assert f"--log-opts {c1}..{c2}" in args


@needs_bash
def test_push_가_새_브랜치면_그_이력_전체를_본다(repo, tmp_path):
    work, c1, c2 = repo
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="push", BASE_SHA="0" * 40, HEAD_SHA=c2)
    assert result == "clean"
    assert f"--log-opts {c2} " in args + " "


@needs_bash
def test_push_이전_커밋이_사라졌으면_마지막_커밋만_보고_경고한다(repo, tmp_path):
    work, c1, c2 = repo
    done, result, args = _run(work, tmp_path, 0, EVENT_NAME="push", BASE_SHA="deadbeef" * 5, HEAD_SHA=c2)
    assert result == "clean"
    assert f"--log-opts -1 {c2}" in args
    assert "::warning" in done.stdout


@needs_bash
def test_범위에_커밋이_없으면_gitleaks_를_부르지_않고_통과(repo, tmp_path):
    work, c1, c2 = repo
    done, result, args = _run(work, tmp_path, 2, EVENT_NAME="push", BASE_SHA=c2, HEAD_SHA=c2)
    assert done.returncode == 0 and result == "clean"
    assert args is None


# ---- 진짜 gitleaks (GITLEAKS_BIN 이 있을 때만) ----

REAL = os.environ.get("GITLEAKS_BIN")


@pytest.mark.skipif(not (REAL and _HAS_BASH), reason="GITLEAKS_BIN 이 없으면 진짜 gitleaks 로 확인하지 않는다")
def test_진짜_gitleaks_로_SAP_규칙과_종료코드_구분을_확인한다(repo, tmp_path):
    work, c1, c2 = repo
    shutil_cfg = HARNESS_CONFIG.read_text(encoding="utf-8")
    (work / HARNESS_CONFIG_REL).write_text(shutil_cfg, encoding="utf-8")
    (work / "leak.txt").write_text(
        "Cookie: MYSAPSSO2=AjQxMDMBABhWAEUARQBTAFQAUgBPAEcAIAAgACAAIAAgAgAGMDAwMTAx\n"
        "SAP_SESSIONID_Z5U_080=abcDEF123456ghiJKL789012mnoPQR\n"
        "SAP_PASSWORD=Wq7!zLp29xRt\n"
        "ADT_PASSWORD=${ADT_PASSWORD}\n",
        encoding="utf-8",
    )
    _git(work, "add", "leak.txt")
    _git(work, "commit", "-q", "-m", "leak")
    c3 = _git(work, "rev-parse", "HEAD")
    report = tmp_path / "report.json"
    env = {"GITLEAKS_BIN": REAL, "EVENT_NAME": "push", "BASE_SHA": c2, "HEAD_SHA": c3,
           "REPORT_PATH": report.as_posix()}
    done = subprocess.run([_BASH, str(SCRIPT)], cwd=work, env={**os.environ, **env},
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 1 and "유출 발견" in done.stdout, done.stdout + done.stderr
    findings = json.loads(report.read_text(encoding="utf-8"))
    assert {f["RuleID"] for f in findings} == {"sap-mysapsso2-cookie", "sap-sessionid-cookie", "sap-password-assignment"}
    assert "Wq7" not in done.stdout and "Wq7" not in report.read_text(encoding="utf-8")  # 값은 가려진다

    # 깨진 설정은 유출과 다른 검사 불능이다.
    (work / ".gitleaks.toml").write_text("[[rules]\n", encoding="utf-8")
    done = subprocess.run([_BASH, str(SCRIPT)], cwd=work, env={**os.environ, **env},
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 1 and "검사 불능" in done.stdout and "유출 발견" not in done.stdout

    # 프로젝트 설정이 하네스 설정을 이어받으면 SAP 규칙이 유지된다.
    (work / ".gitleaks.toml").write_text(f'[extend]\npath = "{HARNESS_CONFIG_REL}"\n', encoding="utf-8")
    done = subprocess.run([_BASH, str(SCRIPT)], cwd=work, env={**os.environ, **env},
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 1 and "유출 발견" in done.stdout


def _real_env(tmp_path, base, head, event="pull_request"):
    return {**os.environ, "GITLEAKS_BIN": REAL, "EVENT_NAME": event, "BASE_SHA": base, "HEAD_SHA": head,
            "REPORT_PATH": (tmp_path / "report.json").as_posix()}


def _real_run(work, tmp_path, base, head, event="pull_request"):
    return subprocess.run([_BASH, str(SCRIPT)], cwd=work, env=_real_env(tmp_path, base, head, event),
                          capture_output=True, text=True, encoding="utf-8")


EXTEND_HARNESS = f'[extend]\npath = "{HARNESS_CONFIG_REL}"\n'


@pytest.mark.skipif(not (REAL and _HAS_BASH), reason="GITLEAKS_BIN 이 없으면 진짜 gitleaks 로 확인하지 않는다")
def test_진짜_gitleaks_PR_이_allowlist_를_추가해도_base_설정으로_잡힌다(repo, tmp_path):
    work, c1, c2 = repo
    (work / HARNESS_CONFIG_REL).write_text(HARNESS_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    base = _commit_config(work, EXTEND_HARNESS)
    (work / "leak.txt").write_text("SAP_PASSWORD=Wq7!zLp29xRt\n", encoding="utf-8")
    _git(work, "add", "leak.txt")
    head = _commit_config(work, EXTEND_HARNESS + "[allowlist]\npaths = ['''^leak\\.txt$''']\n")
    done = _real_run(work, tmp_path, base, head)
    assert done.returncode == 1 and "유출 발견" in done.stdout, done.stdout + done.stderr
    assert "병합 뒤부터 적용" in done.stdout
    # 같은 커밋을 push 로 보면 체크아웃된(head) 설정의 allowlist 가 적용돼 통과한다 — 병합 뒤부터 적용된다는 뜻.
    done = _real_run(work, tmp_path, base, head, "push")
    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.skipif(not (REAL and _HAS_BASH), reason="GITLEAKS_BIN 이 없으면 진짜 gitleaks 로 확인하지 않는다")
def test_진짜_gitleaks_강제_push_경로는_마지막_커밋_하나만_본다(repo, tmp_path):
    # --log-opts "-1 <sha>" 가 한 인자로 넘어가도 gitleaks 가 공백으로 나눠 git log 에 전달하는지 확인한다.
    work, c1, c2 = repo
    (work / HARNESS_CONFIG_REL).write_text(HARNESS_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    (work / "leak.txt").write_text("SAP_PASSWORD=Wq7!zLp29xRt\n", encoding="utf-8")
    _git(work, "add", "leak.txt")
    _git(work, "commit", "-q", "-m", "leak")
    leak = _git(work, "rev-parse", "HEAD")
    (work / "d.txt").write_text("d\n", encoding="utf-8")
    _git(work, "add", "d.txt")
    _git(work, "commit", "-q", "-m", "clean")
    clean = _git(work, "rev-parse", "HEAD")
    gone = "deadbeef" * 5
    # 마지막 커밋(clean)만 본다 — 앞 커밋의 유출은 범위 밖이므로 통과.
    done = _real_run(work, tmp_path, gone, clean, "push")
    assert done.returncode == 0 and "::warning" in done.stdout, done.stdout + done.stderr
    # 마지막 커밋이 유출 커밋이면 잡는다.
    done = _real_run(work, tmp_path, gone, leak, "push")
    assert done.returncode == 1 and "유출 발견" in done.stdout, done.stdout + done.stderr
