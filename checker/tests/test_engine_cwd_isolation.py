"""훅·스킬의 엔진 호출이 cwd 의 `checker/` 를 잡지 않는지 확인한다(#378).

`python -m` 은 cwd 를 `sys.path[0]` 에 넣는다. 하네스 저장소(작업 트리에 `checker/` 가 있다)에서
훅이 엔진을 부르면 설치본 대신 작업 트리의 옛 `checker` 가 먼저 잡혀, 새 옵션이 없다는
argparse 오류로 "확인 불능" 만 나온다. `-P` 는 cwd 를 sys.path 에서 빼면서 cwd 는 그대로 둔다
(엔진은 cwd 의 저장소를 `gh`·git 대상으로 쓴다).

엔진은 GitHub 에서 받지 않고 이 워크트리를 `--from` 으로 준다(`test_hook.py` 와 같은 방식).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ENGINE_ROOT / "plugins" / "harness"

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 엔진을 받아 실행할 수 없다")

UTF8 = {**os.environ, "PYTHONUTF8": "1"}  # Windows 에서 한글 경로 출력이 cp949 로 깨지지 않게

PROBE = "import checker; print(checker.__file__)"


@pytest.fixture()
def stale_cwd(tmp_path: Path) -> Path:
    """작업 트리에 옛 `checker/` 가 있는 폴더 — 하네스 저장소 루트를 흉내 낸다."""
    pkg = tmp_path / "checker"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("STALE = True\n", encoding="utf-8")
    return tmp_path


def _probe(cwd: Path, *flags: str) -> str:
    done = subprocess.run(
        ["uvx", "--from", str(ENGINE_ROOT), "python", *flags, "-c", PROBE],
        cwd=cwd, env=UTF8, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@needs_uv
def test_without_dash_p_cwd_checker_wins(stale_cwd: Path) -> None:
    # 전제 확인: -P 가 없으면 옛 checker 가 잡힌다(이 테스트가 의미 있는지 스스로 확인).
    assert Path(_probe(stale_cwd)).resolve().is_relative_to(stale_cwd.resolve())


@needs_uv
def test_dash_p_picks_installed_engine(stale_cwd: Path) -> None:
    got = Path(_probe(stale_cwd, "-P")).resolve()
    assert not got.is_relative_to(stale_cwd.resolve())


@needs_uv
def test_dash_p_keeps_cwd(stale_cwd: Path) -> None:
    done = subprocess.run(
        ["uvx", "--from", str(ENGINE_ROOT), "python", "-P", "-c", "import os; print(os.getcwd())"],
        cwd=stale_cwd, env=UTF8, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert Path(done.stdout.strip()).resolve() == stale_cwd.resolve()


def test_every_engine_call_site_uses_dash_p() -> None:
    """훅·스킬에서 엔진을 `python -m checker.` 로 부르는 곳은 모두 `-P` 를 붙인다."""
    bad: list[str] = []
    files = [*(PLUGIN / "hooks").glob("*.sh"), *(PLUGIN / "hooks").glob("*.py"),
             *(PLUGIN / "skills").glob("*/SKILL.md")]
    for path in files:
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"python (-m|\"-m\")", line) and "checker." in line and "-P" not in line:
                bad.append(f"{path.relative_to(ENGINE_ROOT)}:{no}")
            if re.search(r'"python",\s*"-m"', line):
                bad.append(f"{path.relative_to(ENGINE_ROOT)}:{no}")
    assert not bad, bad
