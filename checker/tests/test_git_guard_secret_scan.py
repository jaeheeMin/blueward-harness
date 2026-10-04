"""git 가드 훅의 커밋 전 비밀정보 검사(#170) 테스트.

`pre-bash-git-guard.sh` 가 `git commit` 일 때만 staged 변경을 gitleaks 로 검사하고,
유출·검사 불능·gitleaks 없음을 서로 다른 문구로 거부하는지 임시 저장소에서 확인한다.
훅이 gitleaks 를 찾는 자리는 환경 변수 `GITLEAKS_BIN` 으로 주입한다(가짜 gitleaks 용).
진짜 gitleaks 로 SAP 규칙과 설정 이어받기를 확인하는 테스트는 `GITLEAKS_BIN_REAL` 이
실행 파일을 가리킬 때만 돈다(없으면 건너뜀). 테스트 파일 자체가 비밀값 모양을 담지 않도록
토큰은 실행 중에 이어 붙여 만든다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import (
    _BASH,
    _HAS_BASH,
    _HAS_JQ,
    PLUGIN_ROOT,
    REPO_ROOT,
    _run_guard,
)

pytestmark = [
    pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 훅을 실행해 볼 수 없다"),
    pytest.mark.skipif(not _HAS_JQ, reason="jq 가 없으면 훅이 모든 git 명령을 거부한다"),
]

REAL = os.environ.get("GITLEAKS_BIN_REAL") or os.environ.get("GITLEAKS_BIN")
HARNESS_CFG_REL = ".harness-engine/checker/gitleaks/harness.toml"

# 가짜 gitleaks: 호출 인자와 현재 폴더를 기록하고 FAKE_CODE 로 끝난다.
FAKE_GITLEAKS = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
pwd >> "$FAKE_LOG"
[ -n "$FAKE_OUT" ] && printf '%s\\n' "$FAKE_OUT"
exit "${FAKE_CODE:-0}"
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _token() -> str:
    return "gh" + "p_" + "aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1fG3hI5"


def _sap_cookie_line() -> str:
    return "SAP_SESSION" + "ID_Z5U_080=" + "abcdEFGH1234567890abcd"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q", "-b", "feat/170-x")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "core.autocrlf", "false")
    (work / "README.md").write_text("test\n", encoding="utf-8", newline="\n")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    return work


def _stage(work: Path, name: str, text: str) -> None:
    (work / name).write_text(text, encoding="utf-8", newline="\n")
    _git(work, "add", name)


def _fake(tmp_path: Path) -> Path:
    path = tmp_path / "fake-gitleaks"
    path.write_text(FAKE_GITLEAKS, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    return path


def _path_without_gitleaks() -> str:
    parts = []
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if d and not any((Path(d) / n).exists() for n in ("gitleaks", "gitleaks.exe")):
            parts.append(d)
    return os.pathsep.join(parts)


def _guard(work: Path, cmd: str, **env: str):
    base = {"HARNESS_SKIP_SECRET_SCAN": "", "GITLEAKS_BIN": ""}
    base.update(env)
    return _run_guard(cmd, env=base, cwd=str(work))


def _fake_env(tmp_path: Path, code: int = 0, out: str = "") -> dict[str, str]:
    return {
        "GITLEAKS_BIN": _fake(tmp_path).as_posix(),
        "FAKE_LOG": (tmp_path / "fake.log").as_posix(),
        "FAKE_CODE": str(code),
        "FAKE_OUT": out,
    }


def _reason(out: dict) -> str:
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "fake.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


# ---- 설정 복사본 ----

def test_훅의_하네스_기본_설정_복사본은_checker_의_것과_같다():
    """플러그인 설치본엔 checker/ 가 없어 훅이 복사본을 쓴다. 둘이 갈라지면 로컬과 Actions 규칙이 달라진다."""
    a = (REPO_ROOT / "checker" / "gitleaks" / "harness.toml").read_bytes().replace(b"\r\n", b"\n")
    b = (PLUGIN_ROOT / "hooks" / "gitleaks-harness.toml").read_bytes().replace(b"\r\n", b"\n")
    assert a == b
    ids = {r["id"] for r in tomllib.loads(b.decode("utf-8"))["rules"]}
    assert {"sap-mysapsso2-cookie", "sap-sessionid-cookie", "sap-password-assignment"} <= ids


# ---- 판정(가짜 gitleaks) ----

def test_깨끗한_staged_는_통과하고_하네스_인자로_부른다(repo, tmp_path):
    _stage(repo, "a.txt", "깨끗한 내용\n")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 0))
    assert code == 0 and out is None
    args = _calls(tmp_path)[0]
    assert "git --pre-commit --staged --redact --exit-code 2" in args
    assert f"-c {HARNESS_CFG_REL}" in args  # 프로젝트 .gitleaks.toml 이 없으면 하네스 기본 설정
    # 설정의 [extend] path 가 풀리도록 현재 폴더는 하네스 복사본이 놓인 임시 폴더다.
    cwd_line = _calls(tmp_path)[1]
    assert Path(cwd_line).name != "work"


def test_종료코드_2_는_유출로_거부하고_값이_아니라_규칙과_파일을_알린다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    fake_out = "Finding: REDACTED\nRuleID:      github-pat\nFile:        a.txt\nLine:        3\n"
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 2, fake_out))
    reason = _reason(out)
    assert "비밀값 발견" in reason and "검사 불능" not in reason
    assert "github-pat a.txt:3" in reason
    assert "값은 가려서" in reason
    assert "다음:" in reason and "폐기" in reason
    assert ".gitleaks.toml" in reason and "[allowlist]" in reason and "사람이 할 일" in reason


@pytest.mark.parametrize("rc", [1, 126, 127])
def test_그_밖의_종료코드는_검사_불능으로_거부하고_유출과_문구가_다르다(repo, tmp_path, rc):
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, rc, "FTL boom \x1b[31mred\x1b[0m"))
    reason = _reason(out)
    assert "검사 불능" in reason and f"종료코드 {rc}" in reason
    assert "비밀값 발견" not in reason
    assert "비밀값이 발견됐다는 뜻이 아니며" in reason
    assert "boom" in reason and "\x1b" not in reason


def test_종료코드_0_이어도_로그에_ERR_가_있으면_검사_불능이다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 0, "1:00AM ERR [git] fatal: broken"))
    assert "검사 불능" in _reason(out)


def test_gitleaks_가_없으면_검사_불능으로_거부하고_설치를_안내한다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    empty = tmp_path / "no-local-app-data"
    empty.mkdir()
    code, out = _guard(repo, "git commit -m x", PATH=_path_without_gitleaks(), LOCALAPPDATA=str(empty))
    reason = _reason(out)
    assert "검사 불능" in reason and "gitleaks 가 없어" in reason
    assert "winget install --id Gitleaks.Gitleaks -e" in reason and "사람이 할 일" in reason
    assert "비밀값 발견" not in reason


def test_winget_이_설치한_자리의_gitleaks_는_PATH_밖이어도_찾는다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    local = tmp_path / "lad"
    links = local / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    shutil.copy(_fake(tmp_path), links / "gitleaks.exe")
    code, out = _guard(
        repo, "git commit -m x",
        PATH=_path_without_gitleaks(), LOCALAPPDATA=str(local),
        FAKE_LOG=(tmp_path / "fake.log").as_posix(), FAKE_CODE="0",
    )
    assert code == 0 and out is None
    assert _calls(tmp_path)  # 실제로 불렸다


# ---- 건너뛰기 ----

def test_훅_환경의_SKIP_1_이면_gitleaks_를_안_부르고_통과하되_알린다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", HARNESS_SKIP_SECRET_SCAN="1", **_fake_env(tmp_path, 2))
    assert code == 0
    assert "permissionDecision" not in out["hookSpecificOutput"]
    assert "비밀정보 검사를 건너뜀" in out["systemMessage"]
    assert "비밀정보 검사를 건너뜀" in out["hookSpecificOutput"]["additionalContext"]
    assert _calls(tmp_path) == []


def test_SKIP_가_1_이_아니면_건너뛰지_않는다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", HARNESS_SKIP_SECRET_SCAN="true", **_fake_env(tmp_path, 2))
    assert "비밀값 발견" in _reason(out)


def test_명령_문자열_안의_SKIP_접두어는_무시하고_여전히_검사한다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    for cmd in (
        "HARNESS_SKIP_SECRET_SCAN=1 git commit -m x",
        "export HARNESS_SKIP_SECRET_SCAN=1 && git commit -m x",
        "env HARNESS_SKIP_SECRET_SCAN=1 git commit -m x",
    ):
        (tmp_path / "fake.log").unlink(missing_ok=True)
        code, out = _guard(repo, cmd, **_fake_env(tmp_path, 2))
        assert "비밀값 발견" in _reason(out), cmd
        assert _calls(tmp_path), cmd


# ---- 검사 범위 ----

@pytest.mark.parametrize("flags", ["-a", "--all", "-am x", "-a -m x", "-m x -a", "--include f", "-i f", "--only f", "-o f"])
def test_staged_밖_변경이_들어가는_커밋은_검사_불능으로_거부한다(repo, tmp_path, flags):
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, f"git commit {flags}", **_fake_env(tmp_path, 0))
    reason = _reason(out)
    assert "검사 불능" in reason and "git add" in reason and "-a" in reason
    assert _calls(tmp_path) == []


def test_메시지_안의_옵션_글자와_값을_받는_옵션은_범위_위반으로_보지_않는다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    cmds = [
        'git commit -m "fix -a flag and --all"',
        "git commit -m 'use -i here'",
        'git commit -m "$(cat <<\'EOF\'\nfeat: say "hi" -a\n\n--all\nEOF\n)"',
        "git commit -F msg.txt",
        "git commit -mfix",
        "git commit --amend --no-edit",
        "git commit --allow-empty -m x",
    ]
    for cmd in cmds:
        (tmp_path / "fake.log").unlink(missing_ok=True)
        code, out = _guard(repo, cmd, **_fake_env(tmp_path, 0))
        assert out is None, cmd
        assert _calls(tmp_path), cmd  # 검사는 했다


def test_git_이_아닌_앞_조각이_있는_커밋은_검사한다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    for cmd in ("cd . && git commit -m x", "ls; git commit -m x", "git -C . commit -m x"):
        code, out = _guard(repo, cmd, **_fake_env(tmp_path, 2))
        assert "비밀값 발견" in _reason(out), cmd
    # heredoc 로 파일을 쓴 뒤의 커밋도 놓치지 않는다.
    code, out = _guard(repo, "cat > f.txt <<'EOF'\nhello\nEOF\ngit commit -m x", **_fake_env(tmp_path, 2))
    assert "비밀값 발견" in _reason(out)


@pytest.mark.parametrize("cmd", [
    "git add leak.txt && git commit -m x",
    "git add -A; git commit -m x",
    "git status && git add . && git commit -m x",
    "git rm --cached a.txt && git commit -m x",
    "git reset HEAD a.txt && git commit -m x",
    "git push origin HEAD && git commit -m x",
])
def test_commit_앞에_git_조각이_있으면_검사_불능으로_거부하고_따로_실행하라고_안내한다(repo, tmp_path, cmd):
    """훅은 명령 전체가 실행되기 전에 돈다. 앞 조각이 인덱스를 바꾸면 훅 시점의 staged 는 커밋될 내용이 아니다."""
    _stage(repo, "a.txt", "x\n")
    (repo / "leak.txt").write_text(f"token={_token()}\n", encoding="utf-8", newline="\n")  # 아직 unstaged
    code, out = _guard(repo, cmd, **_fake_env(tmp_path, 0))
    reason = _reason(out)
    assert "검사 불능" in reason and "비밀값 발견" not in reason
    assert "다음: Claude 가 git add 를 먼저 따로 실행한 뒤 git commit 을 별도 명령으로 실행하십시오" in reason
    assert _calls(tmp_path) == []


def test_읽기_전용_git_조각_뒤의_커밋은_그대로_검사한다(repo, tmp_path):
    """status·diff·log·show·rev-parse 는 인덱스를 못 바꾸므로 예외다."""
    _stage(repo, "a.txt", "x\n")
    for cmd in ("git status && git commit -m x", "git diff --cached && git commit -m x",
                "git log -1 ; git commit -m x", "git rev-parse HEAD && git commit -m x"):
        code, out = _guard(repo, cmd, **_fake_env(tmp_path, 2))
        assert "비밀값 발견" in _reason(out), cmd


def test_add_를_따로_실행한_뒤_커밋하면_정상_검사한다(repo, tmp_path):
    (repo / "leak.txt").write_text(f"token={_token()}\n", encoding="utf-8", newline="\n")
    code, out = _guard(repo, "git add leak.txt", **_fake_env(tmp_path, 2))
    assert code == 0 and out is None  # add 자체는 검사 대상이 아니다
    _git(repo, "add", "leak.txt")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 2))
    assert "비밀값 발견" in _reason(out)


def test_F_로_메시지_파일을_주는_커밋도_검사한다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    (repo / "msg.txt").write_text("feat: x\n", encoding="utf-8", newline="\n")
    (tmp_path / "fake.log").unlink(missing_ok=True)
    code, out = _guard(repo, "git commit -q -F msg.txt", **_fake_env(tmp_path, 0))
    assert code == 0 and out is None and _calls(tmp_path)
    code, out = _guard(repo, "git commit -q -F msg.txt", **_fake_env(tmp_path, 2))
    assert "비밀값 발견" in _reason(out)


def test_staged_변경이_없으면_검사할_것이_없어_gitleaks_를_안_부른다(repo, tmp_path):
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 2))
    assert code == 0 and out is None
    assert _calls(tmp_path) == []


def test_main_커밋은_기존대로_먼저_막고_gitleaks_를_안_부른다(repo, tmp_path):
    _git(repo, "checkout", "-q", "-B", "main")
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 2))
    assert "main 브랜치" in _reason(out)
    assert _calls(tmp_path) == []


def test_git_저장소가_아니면_기존대로_통과한다(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    code, out = _guard(plain, "git commit -m x", **_fake_env(tmp_path, 2))
    assert code == 0 and out is None
    assert _calls(tmp_path) == []


def test_merge_진행_중이면_기존대로_통과한다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    (repo / ".git" / "MERGE_HEAD").write_text(head + "\n", encoding="utf-8")
    code, out = _guard(repo, "git commit -a -m x", **_fake_env(tmp_path, 2))
    assert code == 0 and out is None
    assert _calls(tmp_path) == []


def test_커밋이_아닌_명령에는_gitleaks_를_안_부른다(repo, tmp_path):
    _stage(repo, "a.txt", "x\n")
    for cmd in (
        "git status", "git add -A", "git log --grep commit", "git diff --cached", "ls -la",
        'gh issue create --body "git commit -a 를 쓰지 마"', "git commit-tree HEAD^{tree}",
    ):
        code, out = _guard(repo, cmd, **_fake_env(tmp_path, 2))
        assert code == 0 and out is None, cmd
    assert _calls(tmp_path) == []


def test_모든_거부_문구가_큰따옴표_없이_유효한_JSON_이다(repo, tmp_path):
    # _run_guard 가 json.loads 로 읽으므로 위 테스트들이 이미 유효성을 본다. 사유에 역슬래시가 없는지만 확인.
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", **_fake_env(tmp_path, 1, 'FTL a "quoted" back\\slash'))
    assert "\\" not in _reason(out)


# ---- 진짜 gitleaks ----

needs_real = pytest.mark.skipif(not REAL, reason="GITLEAKS_BIN_REAL(또는 GITLEAKS_BIN)이 없으면 진짜 gitleaks 로 확인하지 않는다")


@needs_real
def test_진짜_gitleaks_깨끗한_staged_는_통과한다(repo):
    _stage(repo, "a.txt", "깨끗한 내용\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    assert code == 0 and out is None


@needs_real
def test_진짜_gitleaks_GitHub_토큰은_유출로_거부하고_값은_안_보인다(repo):
    _stage(repo, "t.txt", f"token={_token()}\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    reason = _reason(out)
    assert "비밀값 발견" in reason and "github-pat t.txt:1" in reason
    assert _token()[4:] not in reason


@needs_real
def test_진짜_gitleaks_SAP_쿠키는_하네스_규칙으로_잡힌다(repo):
    _stage(repo, "s.txt", _sap_cookie_line() + "\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    reason = _reason(out)
    assert "비밀값 발견" in reason and "sap-sessionid-cookie s.txt:1" in reason


@needs_real
def test_진짜_gitleaks_프로젝트_설정이_하네스를_이어받고_allowlist_를_더하면_SAP_규칙은_유지된다(repo):
    (repo / ".gitleaks.toml").write_text(
        f'[extend]\npath = "{HARNESS_CFG_REL}"\n\n[allowlist]\npaths = [\'\'\'^t\\.txt$\'\'\']\n',
        encoding="utf-8", newline="\n",
    )
    _stage(repo, "t.txt", f"token={_token()}\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    assert code == 0 and out is None  # allowlist 로 허용한 경로

    _stage(repo, "s.txt", _sap_cookie_line() + "\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    reason = _reason(out)
    assert "sap-sessionid-cookie s.txt:1" in reason and "github-pat" not in reason


@needs_real
def test_진짜_gitleaks_깨진_프로젝트_설정은_검사_불능이다(repo):
    (repo / ".gitleaks.toml").write_text("[[rules]\n", encoding="utf-8", newline="\n")
    _stage(repo, "a.txt", "x\n")
    code, out = _guard(repo, "git commit -m x", GITLEAKS_BIN=REAL)
    reason = _reason(out)
    assert "검사 불능" in reason and "비밀값 발견" not in reason and "\x1b" not in reason


@needs_real
def test_진짜_gitleaks_다른_폴더에서_불러도_세션_cwd_저장소를_검사한다(repo, tmp_path):
    # 훅은 stdin 의 cwd 저장소를 본다. 임시 폴더로 옮겨 실행해도 저장소 경로 인자로 검사한다.
    _stage(repo, "t.txt", f"token={_token()}\n")
    sub = repo / "sub"
    sub.mkdir()
    code, out = _guard(sub, "git commit -m x", GITLEAKS_BIN=REAL)
    assert "github-pat t.txt:1" in _reason(out)
