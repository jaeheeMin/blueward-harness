"""작업본(md) → 양식 xlsx 산출(`checker.export`)을 검증한다(이슈 #192).

픽스처 xlsx 는 커밋하지 않고 테스트 안에서 만든다. openpyxl 로 기본 통합문서를 만든 뒤 zip 수준으로
가짜 drawing 파트를 끼워 넣어, 산출이 손대지 않은 zip 항목을 바이트·순서 그대로 두는지 본다.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import PatternFill

from checker import export

MAP = """\
양식: 시험양식
설명: 시험용
템플릿: ../시험.xlsx
검사_규칙: ../../rules/test.yaml
산출:
  폴더: docs/out
  파일명: "T_{ID}_{제목}_v{버전}.xlsx"
  자리:
    버전: {표: 이력, 열: Ver, 행: 마지막}
    ID: {칸: 코드, 떼기: "X-"}
시트:
  - 이름: Info
    칸:
      - 항목: 코드
        위치: B2
        필수: true
        예시: SAMPLE
      - 항목: 제목
        위치: B3
        필수: true
        형식: "제목 : {값}"
      - 항목: 자동값
        위치: B4
        자동: true
      - 항목: 메모
        위치: B5
        예시: 옛 메모
      - 항목: 수량
        위치: B6
    표:
      - 이름: 이력
        머리글_행: 8
        시작_행: 9
        열:
          Ver: A
          Date: B
          Desc: C
        최대_행: 3
        필수: true
    서술:
      - 이름: 설명
        위치: A14:A16
  - 이름: Log
    표:
      - 이름: 로그
        머리글_행: 1
        시작_행: 2
        열:
          "No": A
          Text: B
        여러_줄: 행
  - 이름: Pair
    표:
      - 이름: 왼쪽
        머리글_행: 1
        시작_행: 2
        열: {L1: A, L2: B}
        짝: 오른쪽
        최대_행: 2
      - 이름: 오른쪽
        머리글_행: 1
        시작_행: 2
        열: {R1: D, R2: E}
        짝: 왼쪽
        최대_행: 2
"""

RULES = """\
관할: "docs/out/**"
규칙:
  - 종류: filename
    패턴: '^T_[0-9A-Za-z]+_.+_v\\d+\\.\\d+\\.xlsx$'
"""

SPEC = """\
# DEV-001 시험

## 근거 요구사항

REQ-001

## 양식 항목

### 시험양식 · Info

| 항목 | 값 |
|---|---|
| 코드 | X-01 |
| 제목 | 시험 건 1 |
| 자동값 | 자동 |
| 메모 | 미정 |
| 수량 | 12 |

#### 이력

| Ver | Date | Desc |
|---|---|---|
| 1.0 | 2026-10-06 | 최초 & <시작> |
| 1.1 | 2026-10-08 | 수정<br>두 줄 |

#### 설명

1. 첫째
2. 둘째

### 시험양식 · Log

#### 로그

| No | Text |
|---|---|
| 1 | a<br>b<br>c |
| 2 | d |
| 3 | e |
| 4 | f |

### 시험양식 · Pair

#### 왼쪽

| L1 | L2 |
|---|---|
| a | b |
| c | d |

#### 오른쪽

| R1 | R2 |
|---|---|
| e | f |
| g | h |

## 변경 이력
"""

DRAWING = b'<?xml version="1.0"?><xdr:wsDr xmlns:xdr="x"><xdr:sp/><xdr:pic></xdr:pic></xdr:wsDr>'


def _make_template(path: Path) -> None:
    wb = openpyxl.Workbook()
    info = wb.active
    info.title = "Info"
    info["A2"], info["B2"] = "코드", "SAMPLE"
    info["B4"] = '=B2&"x"'
    info["B5"] = "옛 메모"
    for r, v in enumerate(["0.1", "0.2", "0.3"], start=9):
        info.cell(r, 1, v)
        info.cell(r, 2, dt.date(2020, 1, r)).number_format = "yyyy-mm-dd"
        info.cell(r, 3, "샘플 내용")
    info["A8"], info["B8"], info["C8"] = "Ver", "Date", "Desc"
    info["A14"], info["A15"] = "샘플1", "샘플2"
    info["A20"] = "손대지 않을 칸"
    log = wb.create_sheet("Log")
    log["A1"], log["B1"] = "No", "Text"
    fill = PatternFill("solid", fgColor="FFFF00")
    for r in (2, 3, 4):
        log.cell(r, 1, f"s{r}")
        log.cell(r, 2, f"샘플{r}")
    log["A4"].fill = fill
    log["B4"].fill = fill
    pair = wb.create_sheet("Pair")
    for c, h in zip("ABDE", ["L1", "L2", "R1", "R2"]):
        pair[f"{c}1"] = h
    pair["A2"], pair["D2"] = "old", "old"
    buf = io.BytesIO()
    wb.save(buf)
    # 가짜 drawing 파트를 끼운다(내용은 산출이 건드리지 않아야 한다).
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zi, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            data = zi.read(it.filename)
            if it.filename == "[Content_Types].xml":
                data = data.replace(
                    b"</Types>",
                    b'<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>',
                )
            zo.writestr(it.filename, data)
        zo.writestr("xl/drawings/drawing1.xml", DRAWING)
        zo.writestr("xl/drawings/_rels/drawing1.xml.rels", b'<?xml version="1.0"?><Relationships/>')
        # Pair 시트(sheet3)가 그 drawing 을 쓴다.
        zo.writestr(
            "xl/worksheets/_rels/sheet3.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
            'Target="../drawings/drawing1.xml"/></Relationships>'.encode("utf-8"),
        )


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "templates" / "forms").mkdir(parents=True)
    (tmp_path / "rules").mkdir()
    (tmp_path / "templates" / "forms" / "시험양식.yaml").write_text(MAP, encoding="utf-8")
    (tmp_path / "rules" / "test.yaml").write_text(RULES, encoding="utf-8")
    _make_template(tmp_path / "templates" / "시험.xlsx")
    return tmp_path


def _spec(proj: Path, text: str = SPEC) -> Path:
    p = proj / "spec.md"
    p.write_text(text, encoding="utf-8")
    return p


def _run(proj: Path, capsys, text: str = SPEC, *extra: str):
    code = export.main(["--spec", str(_spec(proj, text)), "--root", str(proj), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _assert_sheets_sane(path: Path) -> None:
    """well-formed 에 더해 행·셀이 오름차순이고 셀 r 이 행 번호와 맞는지 본다."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        for n in zf.namelist():
            if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
                last_row = 0
                for row in ET.fromstring(zf.read(n)).iter(ns + "row"):
                    r = int(row.get("r"))
                    assert r > last_row, f"{n}: 행 순서"
                    last_row, last_col = r, 0
                    for c in row.findall(ns + "c"):
                        m = re.fullmatch(r"([A-Z]+)(\d+)", c.get("r"))
                        assert m and int(m.group(2)) == r, f"{n}: 셀 {c.get('r')} 가 {r}행에 있다"
                        col = export.col2n(m.group(1))
                        assert col > last_col, f"{n}: {r}행 셀 순서"
                        last_col = col


def _produced(proj: Path, report: dict) -> Path:
    assert len(report["files"]) == 1
    path = proj / report["files"][0]
    _assert_sheets_sane(path)
    return path


def test_산출이_성공하고_JSON_모양이_맞다(proj, capsys):
    code, report = _run(proj, capsys)
    assert code == 0
    assert report["status"] == "ok"
    assert report["problems"] == []
    assert report["warnings"] == []
    assert report["next"].startswith("다음:")
    assert report["files"] == ["docs/out/T_01_시험 건 1_v1.1.xlsx"]
    assert _produced(proj, report).exists()


def test_파일명_자리_표_마지막_행과_떼기(proj, capsys):
    _, report = _run(proj, capsys)
    # ID: 코드 X-01 에서 `X-` 를 뗀 01, 버전: 이력 표 Ver 의 마지막 행 1.1
    assert Path(report["files"][0]).name.startswith("T_01_")
    assert Path(report["files"][0]).name.endswith("_v1.1.xlsx")


def test_칸_형식_자동_샘플_지우기(proj, capsys):
    _, report = _run(proj, capsys)
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert ws["B2"].value == "X-01"
    assert ws["B3"].value == "제목 : 시험 건 1"
    assert ws["B4"].value == '=B2&"x"'  # 자동 칸은 쓰지 않는다
    assert ws["B5"].value is None  # 예시 칸이 미정 → 샘플 지움
    assert ws["B6"].value == 12  # 정수는 숫자로
    assert ws["A20"].value == "손대지 않을 칸"  # 지도에 없는 칸은 그대로


def test_표_날짜_최대행_샘플_지우기(proj, capsys):
    _, report = _run(proj, capsys)
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert [ws.cell(9, c).value for c in (1, 2, 3)] == ["1.0", dt.datetime(2026, 10, 6), "최초 & <시작>"]
    assert ws["C10"].value == "수정\n두 줄"  # 여러_줄 셀 기본: 셀 안 줄바꿈
    assert [ws.cell(11, c).value for c in (1, 2, 3)] == [None, None, None]  # 채우지 않은 샘플 행


def test_서술_범위는_줄마다_첫_열의_한_행씩_쓰고_나머지_샘플을_지운다(proj, capsys):
    _, report = _run(proj, capsys)
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert [ws[f"A{r}"].value for r in (14, 15, 16)] == ["1. 첫째", "2. 둘째", None]


def test_서술_줄은_빈_줄을_빼고_br도_줄로_나눈다(proj, capsys):
    text = SPEC.replace("1. 첫째\n2. 둘째", "1. a<br>2. b\n\n3. c")
    _, report = _run(proj, capsys, text)
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert [ws[f"A{r}"].value for r in (14, 15, 16)] == ["1. a", "2. b", "3. c"]


def test_서술이_범위_행_수를_넘으면_거부(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("1. 첫째\n2. 둘째", "1\n2\n3\n4"))
    assert code == 1
    assert any(p["item"] == "설명" and "넘는다" in p["reason"] for p in report["problems"])


def test_서술_위치가_한_셀이면_줄바꿈_포함_한_셀(proj, capsys):
    (proj / "templates" / "forms" / "시험양식.yaml").write_text(MAP.replace("A14:A16", "A14"), encoding="utf-8")
    _, report = _run(proj, capsys)
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert ws["A14"].value == "1. 첫째\n2. 둘째"
    assert ws["A15"].value == "샘플2"  # 지도 위치(A14) 밖이라 건드리지 않는다


def test_여러_줄_행_표와_새_행_스타일_복제(proj, capsys):
    _, report = _run(proj, capsys)
    wb = openpyxl.load_workbook(_produced(proj, report))
    ws = wb["Log"]
    got = [(ws.cell(r, 1).value, ws.cell(r, 2).value) for r in range(2, 9)]
    assert got == [(1, "a"), (None, "b"), (None, "c"), (2, "d"), (3, "e"), (4, "f"), (None, None)]
    # 템플릿 마지막 데이터 행(4행)의 서식이 새 행(5~7행)에 복제된다.
    for r in (5, 6, 7):
        assert ws.cell(r, 1).fill.fgColor.rgb == ws["A4"].fill.fgColor.rgb == "00FFFF00"
    assert ws.cell(8, 1).fill.fgColor.rgb != "00FFFF00"


def test_짝_표_채우기(proj, capsys):
    _, report = _run(proj, capsys)
    ws = openpyxl.load_workbook(_produced(proj, report))["Pair"]
    assert [ws.cell(2, c).value for c in (1, 2, 4, 5)] == ["a", "b", "e", "f"]
    assert [ws.cell(3, c).value for c in (1, 2, 4, 5)] == ["c", "d", "g", "h"]


def test_손대지_않은_zip_항목은_바이트와_순서가_그대로(proj, capsys):
    _, report = _run(proj, capsys)
    tpl = zipfile.ZipFile(proj / "templates" / "시험.xlsx")
    out = zipfile.ZipFile(_produced(proj, report))
    assert [i.filename for i in out.infolist()] == [i.filename for i in tpl.infolist()]
    changed = {n for n in tpl.namelist() if tpl.read(n) != out.read(n)}
    sheets = {n for n in tpl.namelist() if n.startswith("xl/worksheets/sheet")}
    assert changed <= sheets | {"xl/workbook.xml"}
    assert out.read("xl/drawings/drawing1.xml") == DRAWING
    assert out.read("xl/styles.xml") == tpl.read("xl/styles.xml")


def test_시트_XML이_well_formed이고_수식_통합문서는_전체_재계산(proj, capsys):
    _, report = _run(proj, capsys)
    out = zipfile.ZipFile(_produced(proj, report))
    for n in out.namelist():
        if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"):
            ET.fromstring(out.read(n))
    wb = out.read("xl/workbook.xml").decode("utf-8")
    ET.fromstring(wb)
    assert 'fullCalcOnLoad="1"' in wb


def test_산출물이_openpyxl로_다시_읽히고_파일명_규칙을_통과한다(proj, capsys):
    _, report = _run(proj, capsys)
    wb = openpyxl.load_workbook(_produced(proj, report))
    assert wb.sheetnames == ["Info", "Log", "Pair"]


def test_양식을_지정하면_그_양식만(proj, capsys):
    code, report = _run(proj, capsys, SPEC, "--form", "시험양식")
    assert code == 0 and len(report["files"]) == 1


def test_필수_칸이_미정이면_거부하고_아무것도_쓰지_않는다(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 제목 | 시험 건 1 |", "| 제목 | 미정 |"))
    assert code == 1
    assert report["status"] == "rejected" and report["files"] == []
    assert {"form": "시험양식", "sheet": "Info", "item": "제목", "reason": "필수 칸이 미정이거나 비어 있다"} in report["problems"]
    assert not (proj / "docs").exists()


def test_필수_표가_비면_거부(proj, capsys):
    text = SPEC.replace("| 1.0 | 2026-10-06 | 최초 & <시작> |\n| 1.1 | 2026-10-08 | 수정<br>두 줄 |\n", "|  |  |  |\n")
    code, report = _run(proj, capsys, text)
    assert code == 1
    assert any(p["item"] == "이력" for p in report["problems"])


def test_최대_행_초과는_거부(proj, capsys):
    rows = "".join(f"| 1.{i} | 2026-10-0{i} | x |\n" for i in range(1, 5))
    text = SPEC.replace("| 1.0 | 2026-10-06 | 최초 & <시작> |\n| 1.1 | 2026-10-08 | 수정<br>두 줄 |\n", rows)
    code, report = _run(proj, capsys, text)
    assert code == 1
    assert any("최대 3행" in p["reason"] for p in report["problems"])


def test_짝_표_행_수가_다르면_거부(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| g | h |\n", ""))
    assert code == 1
    assert any(p["item"] in ("왼쪽", "오른쪽") and "행 수" in p["reason"] for p in report["problems"])


def test_금지_문자가_파일명에_들어가면_거부(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("시험 건 1", "a/b"))
    assert code == 1
    assert any(p["item"] == "파일명" and "쓸 수 없는 문자" in p["reason"] for p in report["problems"])


def test_파일명_자리_값이_없으면_거부(proj, capsys):
    text = SPEC.replace("| 1.0 | 2026-10-06 | 최초 & <시작> |\n| 1.1 | 2026-10-08 | 수정<br>두 줄 |\n", "|  |  |  |\n")
    code, report = _run(proj, capsys, text)
    assert code == 1
    assert any("{버전}" in p["item"] for p in report["problems"])


def test_이미_있는_파일은_덮지_않고_거부(proj, capsys):
    code, report = _run(proj, capsys)
    assert code == 0
    produced = _produced(proj, report)
    before = produced.read_bytes()
    code, report = _run(proj, capsys)
    assert code == 1
    assert "이미 있다" in report["problems"][0]["reason"] and "버전" in report["problems"][0]["reason"]
    assert produced.read_bytes() == before


def test_파일명이_검사_규칙_패턴과_다르면_거부(proj, capsys):
    (proj / "rules" / "test.yaml").write_text(RULES.replace("^T_", "^Z_"), encoding="utf-8")
    code, report = _run(proj, capsys)
    assert code == 1
    assert any("패턴" in p["reason"] for p in report["problems"])


def test_지도에_없는_항목은_읽지_못함_종료코드_2(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 수량 | 12 |", "| 없는칸 | 1 |"))
    assert code == 2
    assert report["status"] == "error" and report["files"] == []
    assert report["problems"][0]["item"] == "없는칸"


def test_지도에_없는_시트_표_열은_종료코드_2(proj, capsys):
    assert _run(proj, capsys, SPEC.replace("시험양식 · Pair", "시험양식 · 없는시트"))[0] == 2
    assert _run(proj, capsys, SPEC.replace("#### 로그", "#### 없는표"))[0] == 2
    assert _run(proj, capsys, SPEC.replace("| No | Text |", "| No | 없는열 |"))[0] == 2


def test_지도나_템플릿을_못_읽으면_종료코드_2(proj, capsys):
    (proj / "templates" / "시험.xlsx").unlink()
    code, report = _run(proj, capsys)
    assert code == 2 and report["status"] == "error"
    (proj / "templates" / "forms" / "시험양식.yaml").unlink()
    assert _run(proj, capsys)[0] == 2


def test_작업본에_양식_항목_절이_없으면_종료코드_2(proj, capsys):
    assert _run(proj, capsys, "# 제목\n\n## 개요\n")[0] == 2


def test_해당_없음_시트는_예시와_표_샘플을_비운다(proj, capsys):
    text = SPEC.replace("시험양식 · Pair\n", "시험양식 · Pair\n\n해당 없음\n").split("#### 왼쪽")[0] + "\n## 변경 이력\n"
    code, report = _run(proj, capsys, text)
    assert code == 0
    ws = openpyxl.load_workbook(_produced(proj, report))["Pair"]
    assert ws["A2"].value is None and ws["D2"].value is None
    # 지도 밖 샘플(머리글 셀, 그림·도형 2개)은 남기고 알린다.
    warns = [w for w in report["warnings"] if w["sheet"] == "Pair"]
    assert len(warns) == 1 and "그림·도형 2개" in warns[0]["reason"] and "엑셀에서 확인" in warns[0]["reason"]


def test_새_행이_아래_다른_항목과_겹치면_거부(proj, capsys):
    # Info 시트의 이력(최대_행 있음)은 해당 없고, Log 표 아래에 서술을 둔 지도로 바꿔 본다.
    map_text = MAP.replace(
        "        여러_줄: 행\n",
        "        여러_줄: 행\n    서술:\n      - 이름: 아래\n        위치: A30\n",
    )
    (proj / "templates" / "forms" / "시험양식.yaml").write_text(map_text, encoding="utf-8")
    code, report = _run(proj, capsys)
    assert code == 1
    assert any(p["item"] == "로그" and "아래에 다른 항목" in p["reason"] for p in report["problems"])


def _set_map(proj: Path, text: str) -> None:
    (proj / "templates" / "forms" / "시험양식.yaml").write_text(text, encoding="utf-8")


def _nothing_written(proj: Path) -> bool:
    return not any(p.is_file() for p in (proj / "docs").rglob("*")) if (proj / "docs").exists() else True


def test_산출_폴더가_root_밖이면_종료코드_2(proj, capsys):
    outside = proj.parent / "outside-out"
    _set_map(proj, MAP.replace("폴더: docs/out", "폴더: ../outside-out"))
    code, report = _run(proj, capsys)
    assert code == 2 and report["status"] == "error" and "밖" in report["problems"][0]["reason"]
    assert not outside.exists()
    _set_map(proj, MAP.replace("폴더: docs/out", f'폴더: "{outside.as_posix()}"'))
    code, report = _run(proj, capsys)
    assert code == 2 and not outside.exists()


def test_템플릿_검사_규칙_경로가_root_밖이면_종료코드_2(proj, capsys):
    _set_map(proj, MAP.replace("템플릿: ../시험.xlsx", "템플릿: ../../../시험.xlsx"))
    assert _run(proj, capsys)[0] == 2
    _set_map(proj, MAP.replace("검사_규칙: ../../rules/test.yaml", "검사_규칙: ../../../rules/test.yaml"))
    code, report = _run(proj, capsys)
    assert code == 2 and "밖" in report["problems"][0]["reason"]


def test_양식_이름에_경로_구분자가_있으면_종료코드_2(proj, capsys):
    for bad in ("../x", "a/b", "a\\b", "C:x"):
        assert _run(proj, capsys, SPEC.replace("### 시험양식 · Info", f"### {bad} · Info"))[0] == 2
    assert _run(proj, capsys, SPEC, "--form", "../시험양식")[0] == 2


def test_예상하지_못한_예외는_종료코드_2와_JSON(proj, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(export, "build_form", boom)
    code, report = _run(proj, capsys)
    assert code == 2 and report["status"] == "error" and report["files"] == []
    assert "boom" in report["problems"][0]["reason"]


def _two_form_spec() -> str:
    second = SPEC.split("### 시험양식 · Info", 1)[1].split("## 변경 이력")[0].replace("시험양식", "시험양식2")
    return SPEC.replace("## 변경 이력", "### 시험양식2 · Info" + second + "## 변경 이력")


def _add_second_form(proj: Path) -> None:
    second = MAP.replace("양식: 시험양식", "양식: 시험양식2").replace("docs/out", "docs/out2").replace(
        "T_{ID}_{제목}_v{버전}", "T_{ID}_{제목}_B_v{버전}"
    )
    (proj / "templates" / "forms" / "시험양식2.yaml").write_text(second, encoding="utf-8")


def test_두_양식을_함께_산출한다(proj, capsys):
    _add_second_form(proj)
    code, report = _run(proj, capsys, _two_form_spec())
    assert code == 0 and len(report["files"]) == 2


def test_둘째_양식_쓰기가_실패하면_아무_파일도_남기지_않는다(proj, capsys, monkeypatch):
    _add_second_form(proj)
    real = os.rename
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("디스크 오류")
        real(src, dst)

    monkeypatch.setattr(os, "rename", flaky)
    code, report = _run(proj, capsys, _two_form_spec())
    assert code == 2 and report["status"] == "error" and "디스크 오류" in report["problems"][0]["reason"]
    assert len(calls) == 2  # 첫째는 최종 이름까지 갔다가 지워졌다
    assert _nothing_written(proj)
    assert not (proj / "docs").exists()


def test_셀_값이_32767자를_넘으면_거부(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 메모 | 미정 |", "| 메모 | " + "가" * 32768 + " |"))
    assert code == 1 and report["files"] == []
    assert any(p["item"] == "메모" and "32767" in p["reason"] for p in report["problems"])
    code, _ = _run(proj, capsys, SPEC.replace("| 메모 | 미정 |", "| 메모 | " + "가" * 32767 + " |"))
    assert code == 0


def test_XML에_못_넣는_문자는_지우고_warnings로_알린다(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 메모 | 미정 |", "| 메모 | a\x0bb\x01c" + chr(0xFFFE) + " |"))
    assert code == 0
    ws = openpyxl.load_workbook(_produced(proj, report))["Info"]
    assert ws["B5"].value == "abc"
    assert [w["item"] for w in report["warnings"]] == ["메모"] and "3개" in report["warnings"][0]["reason"]


def test_표가_끊긴_뒤_다시_나오면_종료코드_2(proj, capsys):
    text = SPEC.replace("| 1.0 | 2026-10-06 | 최초 & <시작> |\n| 1.1", "| 1.0 | 2026-10-06 | 최초 & <시작> |\n\n| 1.1")
    code, report = _run(proj, capsys, text)
    assert code == 2 and "끊긴" in report["problems"][0]["reason"]


def test_머리글_다음_줄이_구분선이_아니면_종료코드_2(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| Ver | Date | Desc |\n|---|---|---|\n", "| Ver | Date | Desc |\n"))
    assert code == 2 and "구분선" in report["problems"][0]["reason"]


def test_행의_셀_수가_머리글과_다르면_거부(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 1.1 | 2026-10-08 | 수정<br>두 줄 |", "| 1.1 | 2026-10-08 |"))
    assert code == 1
    assert any(p["item"] == "이력" and "셀 수" in p["reason"] for p in report["problems"])


def test_같은_소절이_두_번이면_종료코드_2(proj, capsys):
    text = SPEC.replace("## 변경 이력", "### 시험양식 · Pair\n\n해당 없음\n\n## 변경 이력")
    code, report = _run(proj, capsys, text)
    assert code == 2 and "두 번" in report["problems"][0]["reason"]


def test_칸_표_머리글이_항목_값이_아니면_종료코드_2(proj, capsys):
    code, report = _run(proj, capsys, SPEC.replace("| 항목 | 값 |", "| 이름 | 값 |"))
    assert code == 2 and "항목" in report["problems"][0]["reason"]


def test_calcPr_삽입은_스키마_순서를_지킨다():
    base = '<workbook><sheets><sheet name="a" sheetId="1" r:id="rId1"/></sheets>{mid}<oleSize ref="A1"/></workbook>'
    with_names = export._with_full_calc(
        base.format(mid="<definedNames><definedName name=\"x\">a!A1</definedName></definedNames>")
    )
    assert with_names.index("</definedNames>") < with_names.index("<calcPr") < with_names.index("<oleSize")
    without = export._with_full_calc(base.format(mid=""))
    assert without.index("</sheets>") < without.index("<calcPr") < without.index("<oleSize")
    again = export._with_full_calc('<workbook><sheets/><calcPr calcId="1"/></workbook>')
    assert 'calcId="1" fullCalcOnLoad="1"/>' in again and again.count("calcPr") == 1


def test_자동_표시_없는_수식_칸에_쓰려_하면_종료코드_2(proj, capsys):
    _set_map(proj, MAP.replace("        위치: B4\n        자동: true\n", "        위치: B4\n"))
    code, report = _run(proj, capsys)
    assert code == 2 and "수식" in report["problems"][0]["reason"]
    assert _nothing_written(proj)


def test_검사_규칙의_pattern_별칭도_읽는다(proj, capsys):
    (proj / "rules" / "test.yaml").write_text(
        RULES.replace("패턴:", "pattern:").replace("^T_", "^Z_"), encoding="utf-8"
    )
    code, report = _run(proj, capsys)
    assert code == 1 and any("패턴" in p["reason"] for p in report["problems"])
