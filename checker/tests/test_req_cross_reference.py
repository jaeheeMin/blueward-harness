"""`req_cross_reference` 규칙(#261)과 엑셀 산출과의 자리 충돌 여부를 검증한다."""
from __future__ import annotations

from pathlib import Path

import pytest

from checker import export
from checker.model import ConfigError
from checker.rules.req_cross_reference import check

HEAD = """# P SRS

## 범위

- 하는 것: 판매오더 조회 (REQ-002 와 DEV-002 는 다른 절에서 다룬다)

## 요구사항

| ID | Title | Status |
|---|---|---|
| REQ-001 | 판매오더 조회 앱 | New |
| REQ-002 | 판매오더 생성 | New |

"""


def run(tmp_path: Path, body: str, **params):
    p = tmp_path / "SRS.md"
    p.write_text(HEAD + body, encoding="utf-8")
    return check(p, params)


def test_다른_번호가_없으면_통과(tmp_path):
    assert run(tmp_path, "### REQ-001 조회 앱\n\n#### Short Description\n\n조회한다. DEV-001 로 진행.\n") == []


def test_자기_DEV_는_통과(tmp_path):
    body = "### REQ-002 생성\n\n#### Dependencies\n\nDEV-002 개발 중\n"
    assert run(tmp_path, body) == []


def test_다른_REQ_를_말하고_관계가_없으면_위반(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\nREQ-001 의 조회 앱에 붙인다.\n"
    v = run(tmp_path, body)
    assert len(v) == 1
    assert v[0].rule == "req_cross_reference"
    assert "REQ-002" in v[0].message and "REQ-001" in v[0].message
    assert "범위를 넓힌다" in v[0].message and "관계: 별개 —" in v[0].message


def test_다른_DEV_도_위반(tmp_path):
    body = "### REQ-002 생성\n\n#### Dependencies\n\nDEV-001 개발 중\n"
    assert len(run(tmp_path, body)) == 1


def test_관계_줄이_있으면_통과(tmp_path):
    body = "### REQ-002 생성\n\n관계: 별개 — 생성은 조회와 화면이 다르다 (REQ-001)\n\n#### Short Description\n\nREQ-001 참고.\n"
    assert run(tmp_path, body) == []


def test_관계_줄_이유가_비면_위반(tmp_path):
    body = "### REQ-002 생성\n\n관계:\n\n#### Short Description\n\nREQ-001 참고.\n"
    v = run(tmp_path, body)
    assert len(v) == 1 and "이유가 비어" in v[0].message
    assert len(run(tmp_path, body.replace("관계:", "관계: —"))) == 1  # 이유 없이 구분 기호만


def test_관계_줄이_소제목_아래면_인정하지_않는다(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\n관계: 별개 — 이유\nREQ-001 참고.\n"
    v = run(tmp_path, body)
    assert len(v) == 1 and "소제목 아래" in v[0].message


def test_옛_번호_표기는_제외(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\n옛 REQ-001 에서 옮겨 왔다.\n"
    assert run(tmp_path, body) == []


def test_제외_패턴은_데이터로_바꾼다(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\n폐기된 REQ-001 에서 옮겨 왔다.\n"
    assert len(run(tmp_path, body)) == 1
    assert run(tmp_path, body, 제외_패턴=[r"폐기된\s*$"]) == []


def test_접두어는_데이터로_바꾼다(tmp_path):
    body = "### REQ-002 생성\n\nRelation: separate - reason\n\n#### Short Description\n\nREQ-001 참고.\n"
    assert len(run(tmp_path, body)) == 1
    assert run(tmp_path, body, 관계_접두어="Relation:") == []


def test_상세_절_밖의_언급은_무시(tmp_path):
    # HEAD 의 범위 절·요구사항 표가 REQ-002/DEV-002 를 말하지만 상세 절이 아니다.
    body = "### REQ-001 조회 앱\n\n#### Short Description\n\n조회한다.\n\n## 참조\n\nREQ-002 와 DEV-002 를 본다.\n"
    assert run(tmp_path, body) == []


def test_절마다_따로_본다(tmp_path):
    body = (
        "### REQ-001 조회 앱\n\n#### Dependencies\n\nREQ-002\n\n"
        "### REQ-002 생성\n\n관계: 별개 — 이유\n\n#### Dependencies\n\nREQ-001\n"
    )
    v = run(tmp_path, body)
    assert len(v) == 1 and v[0].message.startswith("REQ-001")


def test_코드_펜스_안의_제목은_절이_아니다(tmp_path):
    body = "### REQ-001 조회 앱\n\n```\n### REQ-009 예시\nREQ-009\n```\n"
    assert run(tmp_path, body) == []


def test_번호_뒤에_조사가_붙어도_잡는다(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\nREQ-001의 조회에 붙인다.\n"
    v = run(tmp_path, body)
    assert len(v) == 1 and "REQ-001" in v[0].message
    body = "### REQ-002 생성\n\n#### Dependencies\n\nDEV-001는 별개\n"
    assert len(run(tmp_path, body)) == 1


def test_조사가_붙은_옛_표기는_제외(tmp_path):
    body = "### REQ-002 생성\n\n#### Short Description\n\n옛 REQ-001의 범위를 옮겼다.\n"
    assert run(tmp_path, body) == []


def test_번호가_아닌_글자는_잡지_않는다(tmp_path):
    # XREQ-001 은 번호가 아니다. REQ-0012 는 REQ-001 이 아니라 REQ-0012 통째로 다른 번호다.
    body = "### REQ-001 조회 앱\n\n#### Short Description\n\nXREQ-001 과 MYDEV-001 참고.\n"
    assert run(tmp_path, body) == []
    body = "### REQ-001 조회 앱\n\n#### Short Description\n\nREQ-0012 참고.\n"
    v = run(tmp_path, body)
    assert len(v) == 1 and v[0].actual == "REQ-0012"


def test_제목_뒤에_조사가_붙어도_절로_본다(tmp_path):
    body = "### REQ-002의 생성\n\n#### Short Description\n\nREQ-001 참고.\n"
    assert len(run(tmp_path, body)) == 1


def test_H1_도_상세_절을_닫는다(tmp_path):
    body = "### REQ-001 조회 앱\n\n#### Short Description\n\n조회한다.\n\n# 부록\n\nREQ-002 와 DEV-002 를 본다.\n"
    assert run(tmp_path, body) == []


def test_틸드_코드_펜스_안은_보지_않는다(tmp_path):
    body = "### REQ-001 조회 앱\n\n~~~\n### REQ-009 예시\nREQ-009\n~~~\n\n#### Short Description\n\n조회한다.\n"
    assert run(tmp_path, body) == []


def test_인용_관계_줄은_인정하지_않고_자리를_안내한다(tmp_path):
    body = "### REQ-002 생성\n\n> 관계: 별개 — 이유\n\n#### Short Description\n\nREQ-001 참고.\n"
    v = run(tmp_path, body)
    assert len(v) == 1 and "인용" in v[0].message and "일반 줄" in v[0].message


def test_제외_패턴이_정규식이_아니면_설정_오류(tmp_path):
    with pytest.raises(ConfigError):
        run(tmp_path, "### REQ-001 x\n", 제외_패턴=["("])


def test_관계_줄_자리는_엑셀_산출이_읽지_않는다():
    text = HEAD + (
        "### REQ-002 생성\n\n관계: 별개 — 이유 REQ-001\n\n#### Short Description\n\n요약\n"
    )
    srs = export.parse_srs(text)
    assert srs.details["REQ-002"] == {"Short Description": "요약"}
    assert all("관계" not in v for v in srs.details["REQ-002"].values())
