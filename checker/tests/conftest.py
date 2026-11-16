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


@pytest.fixture(autouse=True)
def _no_risk_history(request, monkeypatch):
    """risk-gate 의 `remembered` 기준(#1004)은 PR 커밋·브랜치 활동·commit status 를 더 읽는다. 가짜 GhClient 로 decide_pr 를
    부르는 시험은 그 경로를 몰라 KeyError 가 나므로 기본은 "이전 위험 기록 없음" 으로 둔다.
    그 기준 자체를 시험하는 모듈은 모듈 변수 `REAL_RISK_HISTORY = True` 로 이것을 끈다."""
    if getattr(request.module, "REAL_RISK_HISTORY", False):
        return
    from checker import risk_gate

    monkeypatch.setattr(risk_gate, "fetch_risk_history", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _clear_xlsx_cache():
    """xlsx 리더가 열어 둔 통합문서는 프로세스 단위로 재사용된다(#515). 시험끼리 섞이지 않게, 그리고 Windows 에서 임시 파일을 지울 수 있게 매번 닫는다."""
    from checker.readers import xlsx

    xlsx.clear_cache()
    yield
    xlsx.clear_cache()
