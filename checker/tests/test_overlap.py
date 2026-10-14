"""Spec 간 SAP 객체 겹침 검사와 교차 검사 스위치(#292)를 단언한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_changed import main_entry  # noqa: E402
from render_report import render  # noqa: E402

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION  # noqa: E402
from checker.cross_switches import SwitchError, load_switches  # noqa: E402
from checker.overlap import check_overlap  # noqa: E402
from checker.pairing import CANNOT_CHECK, PASS, SKIPPED  # noqa: E402

HEAD = "| 종류 | 이름 | 작업 | 비고 |\n|---|---|---|---|\n"


def _spec(tmp: Path, filename: str, rows: list[str] | None, head: str = HEAD) -> Path:
    path = tmp / "docs" / "spec" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# 제목\n\n## 상세 설계\n\n내용\n\n"
    if rows is not None:
        body += "## 사용 객체\n\n" + head + "\n".join(rows) + "\n\n"
    body += "## 메모\n\n없음\n"
    path.write_text(body, encoding="utf-8")
    return path


def _row(kind: str, name: str, work: str) -> str:
    return f"| {kind} | {name} | {work} |  |"


def test_docs_spec이_없으면_건너뛴다(tmp_path):
    assert check_overlap(tmp_path)["status"] == SKIPPED


def test_둘이_같은_객체를_만들거나_고치면_경고한다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_Order", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_Order", "수정")])
    r = check_overlap(tmp_path)
    assert r["status"] == PASS and len(r["warnings"]) == 1
    w = r["warnings"][0]
    assert (w["kind"], w["name"]) == ("CDS View", "ZI_ORDER")
    assert {(s["dev"], s["work"]) for s in w["specs"]} == {("DEV-002", "생성"), ("DEV-003", "수정")}
    assert {s["file"] for s in w["specs"]} == {"docs/spec/DEV-002-a.md", "docs/spec/DEV-003-b.md"}


def test_겹치는_객체가_없으면_경고가_없다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_B", "생성")])
    assert check_overlap(tmp_path)["warnings"] == []


def test_종류가_다르면_이름이_같아도_겹침이_아니다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZX", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("ABAP Class", "ZX", "생성")])
    assert check_overlap(tmp_path)["warnings"] == []


def test_참조만_겹치면_경고하지_않는다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "참조")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_A", "참조")])
    _spec(tmp_path, "DEV-004-c.md", [_row("CDS View", "ZI_A", "수정")])
    assert check_overlap(tmp_path)["warnings"] == []


def test_대소문자가_달라도_같은_객체다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("ABAP Class", "zcl_salesorder", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("ABAP Class", "`ZCL_SalesOrder`", "수정")])
    assert len(check_overlap(tmp_path)["warnings"]) == 1


def test_한_Spec_안의_중복_행은_겹침이_아니다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성"), _row("CDS View", "zi_a", "수정")])
    assert check_overlap(tmp_path)["warnings"] == []


def test_한글_파일명도_읽는다(tmp_path):
    _spec(tmp_path, "DEV-002-판매주문.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp_path, "DEV-003-납품 처리.md", [_row("CDS View", "ZI_A", "생성")])
    r = check_overlap(tmp_path)
    assert len(r["warnings"]) == 1 and r["status"] == PASS


def test_표가_없는_Spec은_세기만_한다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", None)
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_A", "생성")])
    r = check_overlap(tmp_path)
    assert r["status"] == PASS and r["no_table"] == 1 and r["warnings"] == []
    assert r["no_table_files"] == ["docs/spec/DEV-002-a.md"]


def test_자리표시_빈_행은_무시한다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", ["|  |  |  |  |"])
    assert check_overlap(tmp_path) == {**check_overlap(tmp_path), "status": PASS, "warnings": []}


def test_읽지_못하는_Spec은_검사_불능이고_경로가_남는다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성")])
    bad = tmp_path / "docs" / "spec" / "DEV-003-깨짐.md"
    bad.write_bytes(b"\xff\xfe\x00bad")
    r = check_overlap(tmp_path)
    assert r["status"] == CANNOT_CHECK
    assert [c["file"] for c in r["cannot_check"]] == ["docs/spec/DEV-003-깨짐.md"]


@pytest.mark.parametrize("rows,head", [
    ([_row("CDS View", "ZI_A", "삭제")], HEAD),                       # 모르는 작업
    ([_row("CDS View", "ZI_A", "생성")], "| 종류 | 이름 |\n|---|---|\n"),  # 머리가 다름
    (["| CDS View | ZI_A | 생성 |"], HEAD),                            # 칸 수
])
def test_표_모양이_깨지면_검사_불능이다(tmp_path, rows, head):
    _spec(tmp_path, "DEV-002-a.md", rows, head=head)
    r = check_overlap(tmp_path)
    assert r["status"] == CANNOT_CHECK and r["cannot_check"][0]["file"] == "docs/spec/DEV-002-a.md"


def test_절은_있는데_표가_없으면_검사_불능이다(tmp_path):
    path = tmp_path / "docs" / "spec" / "DEV-002-a.md"
    path.parent.mkdir(parents=True)
    path.write_text("# x\n\n## 사용 객체\n\n아직 없음\n", encoding="utf-8")
    assert check_overlap(tmp_path)["status"] == CANNOT_CHECK


# --- 스위치 ---------------------------------------------------------------

def _switch(tmp: Path, text: str) -> None:
    path = tmp / "rules" / "cross-checks" / "switches.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_스위치_파일이_없으면_둘_다_켠다(tmp_path):
    assert load_switches(tmp_path) == {"번호_짝": True, "객체_겹침": True}


def test_스위치를_끄고_켠다(tmp_path):
    _switch(tmp_path, "번호_짝: false\n객체_겹침: true\n")
    assert load_switches(tmp_path) == {"번호_짝": False, "객체_겹침": True}


def test_파일에_없는_키는_켠다(tmp_path):
    _switch(tmp_path, "객체_겹침: false\n")
    assert load_switches(tmp_path) == {"번호_짝": True, "객체_겹침": False}


@pytest.mark.parametrize("text", ["번호_짝: 꺼짐\n", "번호_짝: 0\n", "객체_겹침: 'false'\n", "오타: true\n", "- a\n", "번호_짝: [\n"])
def test_잘못된_스위치는_검사_불능이다(tmp_path, text):
    _switch(tmp_path, text)
    with pytest.raises(SwitchError):
        load_switches(tmp_path)


def test_빈_스위치_파일은_둘_다_켠다(tmp_path):
    _switch(tmp_path, "# 비움\n")
    assert load_switches(tmp_path) == {"번호_짝": True, "객체_겹침": True}


def test_스위치_파일이_rules_로더를_깨지_않는다(tmp_path):
    from checker.loader import load

    (tmp_path / "templates").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "메모.yaml").write_text(
        '관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: ".*"\n', encoding="utf-8"
    )
    _switch(tmp_path, "번호_짝: true\n")
    assert len(load(tmp_path / "rules")) == 1


# --- check_changed 통합 ---------------------------------------------------

def _std_root(tmp: Path) -> None:
    (tmp / "templates").mkdir(exist_ok=True)
    (tmp / "rules").mkdir(exist_ok=True)
    (tmp / "rules" / "메모.yaml").write_text(
        '관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: ".*"\n', encoding="utf-8"
    )


def _run(tmp, monkeypatch, capsys, changed="docs/spec/DEV-002-a.md\n"):
    (tmp / "changed.txt").write_text(changed, encoding="utf-8")
    monkeypatch.chdir(tmp)
    code = main_entry(["changed.txt"])
    return code, json.loads(capsys.readouterr().out)


def _two_specs(tmp):
    _std_root(tmp)
    _spec(tmp, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp, "DEV-003-b.md", [_row("CDS View", "zi_a", "수정")])


def test_Spec이_바뀌면_겹침이_리포트에_합쳐지고_통과다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    code, report = _run(tmp_path, monkeypatch, capsys)
    assert code == EXIT_PASS and report["overlap"]["status"] == PASS
    text = render(report, 0)
    assert "## 객체 겹침" in text and "ZI_A" in text and "DEV-002-a.md" in text


def test_겹침이_없으면_없다고_쓴다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp_path, "DEV-003-b.md", None)
    code, report = _run(tmp_path, monkeypatch, capsys)
    text = render(report, 0)
    assert code == EXIT_PASS and "고치는 곳이 없습니다" in text and "1건" in text


def test_읽지_못하는_Spec이면_종료코드_2다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "삭제")])
    code, report = _run(tmp_path, monkeypatch, capsys)
    assert code == EXIT_CONFIG_ERROR and report["overlap"]["status"] == CANNOT_CHECK
    assert "검사 불능" in render(report, 2)


def test_겹침_스위치를_끄면_돌리지_않는다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    _switch(tmp_path, "객체_겹침: false\n")
    code, report = _run(tmp_path, monkeypatch, capsys)
    assert code == EXIT_PASS and report["overlap"] == {"status": "disabled"}
    text = render(report, 0)
    assert "객체 겹침: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" in text
    assert "ZI_A" not in text


def test_번호_짝_스위치를_꺼도_겹침은_돈다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    _switch(tmp_path, "번호_짝: false\n")
    _, report = _run(tmp_path, monkeypatch, capsys)
    assert report["overlap"]["status"] == PASS and report["pairing"] == {"status": "disabled"}
    assert "번호 짝: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" in render(report, 0)


def test_번호_짝_스위치를_끄면_짝_검사를_돌리지_않는다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    ledger = tmp_path / "audit" / "ledger" / "판매.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# x\n", encoding="utf-8")  # 켜져 있으면 검사 불능이 되는 원장
    _switch(tmp_path, "번호_짝: false\n")
    code, report = _run(tmp_path, monkeypatch, capsys, changed="audit/ledger/판매.md\n")
    assert report["pairing"] == {"status": "disabled"} and code == EXIT_PASS


def test_스위치_파일이_없으면_둘_다_돈다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    ledger = tmp_path / "audit" / "ledger" / "판매.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# x\n\n## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n", encoding="utf-8")
    _, report = _run(tmp_path, monkeypatch, capsys)
    assert "overlap" in report and "pairing" in report


def test_잘못된_스위치면_검사_불능이고_코멘트에_나온다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    _switch(tmp_path, "객체_겹침: 꺼짐\n")
    code, report = _run(tmp_path, monkeypatch, capsys)
    assert code == EXIT_CONFIG_ERROR and report["cross_checks"]["status"] == CANNOT_CHECK
    assert "overlap" not in report
    assert "교차 검사 설정" in render(report, 2)


def test_Spec_말고_다른_파일만_바뀌면_겹침을_돌리지_않는다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    (tmp_path / "README.md").write_text("# a\n", encoding="utf-8")
    code, report = _run(tmp_path, monkeypatch, capsys, changed="README.md\n")
    assert code == EXIT_PASS and "overlap" not in report and "cross_checks" not in report


def test_모양이_잘못된_스위치도_Spec이_안_바뀌면_영향이_없다(tmp_path, monkeypatch, capsys):
    _two_specs(tmp_path)
    _switch(tmp_path, "오타: true\n")
    (tmp_path / "README.md").write_text("# a\n", encoding="utf-8")
    code, _ = _run(tmp_path, monkeypatch, capsys, changed="README.md\n")
    assert code == EXIT_PASS


# --- 이름 미정, DEV- 파일만 ----------------------------------------------

def test_이름이_비었거나_영문자로_시작하지_않으면_비교에서_빼고_센다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "미정", "생성"), _row("CDS View", "-", "수정"),
                                     _row("CDS View", "", "생성"), _row("CDS View", "/DMO/I_X", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "미정", "생성"), _row("CDS View", "-", "수정"),
                                     _row("CDS View", "", "생성"), _row("CDS View", "/dmo/i_x", "수정")])
    r = check_overlap(tmp_path)
    assert r["status"] == PASS and r["name_tbd"] == 6
    assert [w["name"] for w in r["warnings"]] == ["/DMO/I_X"]


def test_이름_미정은_코멘트에_참고로_나온다(tmp_path, monkeypatch, capsys):
    _std_root(tmp_path)
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "미정", "생성")])
    _, report = _run(tmp_path, monkeypatch, capsys)
    assert "이름 미정 **1건**" in render(report, 0)


def test_DEV로_시작하지_않는_파일은_보지_않는다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp_path, "README.md", [_row("CDS View", "ZI_A", "생성")])
    _spec(tmp_path, "메모.md", [_row("CDS View", "ZI_A", "삭제")])  # 깨져 있어도 검사 불능이 아니다
    r = check_overlap(tmp_path)
    assert r["status"] == PASS and r["warnings"] == [] and r["no_table"] == 0


def _srs_titles(tmp: Path, rows: dict[int, str]) -> None:
    path = tmp / "docs" / "ssot" / "SRS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"| REQ-{n:03d} | {t} | New |\n" for n, t in rows.items())
    path.write_text("# SRS\n\n## 요구사항\n\n| ID | Title | Status |\n|---|---|---|\n" + body + "\n", encoding="utf-8")


def test_메시지의_DEV_번호_뒤에_SRS_제목을_붙인다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_Order", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_Order", "수정")])
    _srs_titles(tmp_path, {2: "판매오더 조회 앱", 3: "판매오더 변경 앱"})
    (w,) = check_overlap(tmp_path)["warnings"]
    assert w["message"] == (
        "CDS View ZI_ORDER — 같은 객체를 여러 Spec 이 다룹니다: DEV-002(판매오더 조회 앱) 생성; DEV-003(판매오더 변경 앱) 수정"
    )
    # 기계가 읽는 값은 번호 그대로다
    assert {s["dev"] for s in w["specs"]} == {"DEV-002", "DEV-003"}


def test_SRS에_없는_번호는_원장_내용으로_그것도_없으면_제목_미확인이다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_Order", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_Order", "수정")])
    _srs_titles(tmp_path, {1: "다른 요구사항"})
    ledger = tmp_path / "audit" / "ledger" / "p.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "# 원장\n\n## 개발 건\n\n| ID | 내용 | Spec | 담당 | 상태 | 마지막 PR |\n|---|---|---|---|---|---|\n"
        "| DEV-002 | 원장에만 있는 내용 | - | 홍 | 진행 |  |\n",
        encoding="utf-8",
    )
    (w,) = check_overlap(tmp_path)["warnings"]
    assert "DEV-002(원장에만 있는 내용) 생성" in w["message"]
    assert "DEV-003(제목 미확인) 수정" in w["message"]


def test_SRS를_읽지_못해도_제목만_빠지고_검사_결과는_그대로다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_Order", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_Order", "수정")])
    srs = tmp_path / "docs" / "ssot" / "SRS.md"
    srs.parent.mkdir(parents=True)
    srs.write_bytes(b"\xff\xfe\x00 \x80 not utf-8")  # 읽을 수 없는 SRS
    r = check_overlap(tmp_path)
    assert r["status"] == PASS and r["cannot_check"] == [] and len(r["warnings"]) == 1
    assert "DEV-002(제목 미확인) 생성; DEV-003(제목 미확인) 수정" in r["warnings"][0]["message"]


def test_SRS도_원장도_없으면_제목_미확인이고_파일명_요약을_제목으로_쓰지_않는다(tmp_path):
    _spec(tmp_path, "DEV-002-a.md", [_row("CDS View", "ZI_Order", "생성")])
    _spec(tmp_path, "DEV-003-b.md", [_row("CDS View", "ZI_Order", "수정")])
    (w,) = check_overlap(tmp_path)["warnings"]
    assert "DEV-002(제목 미확인) 생성; DEV-003(제목 미확인) 수정" in w["message"]
