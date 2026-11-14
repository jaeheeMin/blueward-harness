"""`srs_shape` 규칙(#975): 버전 줄 1개, 표 REQ = 상세 절 REQ, 중복 금지, 읽지 못하면 검사 불능."""
from __future__ import annotations

from pathlib import Path

import pytest

from checker.model import ConfigError
from checker.rules.srs_shape import check

HEAD = "# P SRS\n\n이 문서는 SSOT 다.\n\n버전: 0.1\n\n## 범위\n\n- 하는 것: 조회\n\n## 요구사항\n\n"
TABLE = "| ID | Title | Status |\n|---|---|---|\n{rows}\n"
ROW = "| REQ-{n:03d} | 제목 | New |"
DETAIL = "### REQ-{n:03d} 제목\n\n#### Short Description\n\n설명\n\n"
TAIL = "## 참조\n\n없음\n"


def doc(table: list[int], details: list[int], head: str = HEAD) -> str:
    rows = "\n".join(ROW.format(n=n) for n in table)
    return head + TABLE.format(rows=rows) + "\n" + "".join(DETAIL.format(n=n) for n in details) + TAIL


def run(tmp_path: Path, text: str) -> list:
    p = tmp_path / "SRS.md"
    p.write_text(text, encoding="utf-8")
    return check(p, {})


def test_정상_SRS는_통과(tmp_path):
    assert run(tmp_path, doc([1, 2], [1, 2])) == []


def test_버전_줄_0개는_위반(tmp_path):
    v = run(tmp_path, doc([1], [1], head=HEAD.replace("버전: 0.1\n\n", "")))
    assert len(v) == 1 and "버전" in v[0].message and v[0].actual == "0개"


def test_버전_줄_2개는_위반(tmp_path):
    v = run(tmp_path, doc([1], [1], head=HEAD.replace("버전: 0.1\n", "버전: 0.1\n버전: 0.2\n")))
    assert len(v) == 1 and v[0].actual.startswith("2개")


def test_본문의_버전_줄은_세지_않는다(tmp_path):
    text = doc([1], [1]).replace("설명\n", "버전: 9\n", 1)
    assert run(tmp_path, text) == []


def test_표에만_있는_REQ(tmp_path):
    v = run(tmp_path, doc([1, 2], [1]))
    assert len(v) == 1 and "표에만 있음: REQ-002" in v[0].actual


def test_절에만_있는_REQ(tmp_path):
    v = run(tmp_path, doc([1], [1, 2]))
    assert len(v) == 1 and "상세 절에만 있음: REQ-002" in v[0].actual


def test_표_행_중복(tmp_path):
    v = run(tmp_path, doc([1, 1], [1]))
    assert len(v) == 1 and "REQ-001 행이 2개" in v[0].actual


def test_상세_절_중복(tmp_path):
    v = run(tmp_path, doc([1], [1, 1]))
    assert len(v) == 1 and "REQ-001" in v[0].actual and "2개" in v[0].actual


def test_코드_펜스_안_제목은_절이_아니다(tmp_path):
    text = doc([1], [1]).replace("## 참조", "```\n### REQ-009 예시\n```\n\n## 참조")
    assert run(tmp_path, text) == []


def test_위반이_겹치면_모두_낸다(tmp_path):
    v = run(tmp_path, doc([1, 1, 2], [3], head=HEAD.replace("버전: 0.1\n\n", "")))
    assert len(v) == 4  # 버전 0개, 표 행 중복, 표에만, 절에만


def test_요구사항_절이_없으면_검사_불능(tmp_path):
    with pytest.raises(ConfigError, match="요구사항"):
        run(tmp_path, "# P SRS\n\n버전: 0.1\n\n## 범위\n\n없음\n")


def test_표_머리가_없는데_상세_절이_있으면_검사_불능(tmp_path):
    with pytest.raises(ConfigError, match="표 머리"):
        run(tmp_path, HEAD + "표 없음\n\n" + DETAIL.format(n=1) + TAIL)


def test_표_머리가_없는데_REQ_행이_있으면_검사_불능(tmp_path):
    with pytest.raises(ConfigError, match="표 머리"):
        run(tmp_path, HEAD + "| 번호 | 제목 |\n|---|---|\n| REQ-001 | 제목 |\n\n" + TAIL)


def test_읽지_못하면_검사_불능(tmp_path):
    p = tmp_path / "SRS.md"
    p.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError, match="읽지 못해"):
        check(p, {})


def test_작성_전_SRS는_버전만_본다(tmp_path):
    text = "# P SRS\n\n버전: 0.1\n\n## 요구사항\n\n아직 작성 전이다.\n\n## 참조\n\n없음\n"
    assert run(tmp_path, text) == []
    assert len(run(tmp_path, text.replace("버전: 0.1\n\n", ""))) == 1


def test_CRLF_파일도_읽는다(tmp_path):
    p = tmp_path / "SRS.md"
    p.write_bytes(doc([1], [1]).replace("\n", "\r\n").encode("utf-8"))
    assert check(p, {}) == []
