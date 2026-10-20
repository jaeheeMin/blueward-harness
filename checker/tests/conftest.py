from __future__ import annotations

from pathlib import Path

import pytest

from checker.tests import make_fixtures


@pytest.fixture(scope="session")
def sample(tmp_path_factory) -> Path:
    """실제 문서 저장소와 같은 모양의 가짜 고객사 폴더를 만들어 돌려준다."""
    make_fixtures.main()
    return make_fixtures.ROOT


@pytest.fixture(scope="session")
def rules_dir(sample: Path) -> Path:
    return sample / "rules"


@pytest.fixture(autouse=True)
def _no_previous_spec(monkeypatch):
    """산출은 화면 그림을 그릴 때 origin/main 의 지난 판 작업본을 읽는다(#347). 시험용 임시 폴더는 git 저장소가 아니므로 기본은 "첫 판"으로 둔다.
    git 으로 지난 판을 읽는 시험(test_screen_diff.py)은 같은 이름의 fixture 로 이것을 덮어쓴다."""
    from checker import export

    monkeypatch.setattr(export, "_origin_main_text", lambda root, rel: ("first", ""))
