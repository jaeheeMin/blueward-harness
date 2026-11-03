"""트랜스포트 JSON 으로 CTS 관리대장 작업본을 채우는 엔진을 검증한다(이슈 #563, `/harness:cts` 스킬).

실제 MCP 는 부르지 않는다. 스킬이 저장하는 JSON 모양의 견본으로 시험하고, 시험용 양식·작업본 생성기는
test_cts_ledger.py 것을 쓴다. 매핑은 스킬 폴더의 사본을 그대로 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from checker import cts_fill, export
from checker.tests.test_cts_ledger import KINDS, SKILL, _req, _worknote, _write, proj  # noqa: F401  (proj 는 픽스처)


def _tr(n: int, cat: str = "customizing", **extra) -> dict:
    return {"number": f"Z5UK90000{n}", "description": f"설명 {n}", "owner": "USER1", "date": "2026-11-02",
            "target": "Z5Q", "category": cat, **extra}


def _json(proj: Path, transports: list[dict], **top) -> Path:
    p = proj / "transports.json"
    p.write_text(json.dumps({"system": "Z5U", "client": "100", "transports": transports, **top}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def _fill(proj: Path, capsys, kinds: list[str], *extra: str):
    args = []
    for k in kinds:
        args += ["--spec", str(proj / "docs" / "CTS관리대장" / f"CTS관리대장_{k}.md")]
    code = cts_fill.main([*args, "--transports", str(proj / "transports.json"), "--map",
                          str(SKILL / "cts-fill.yaml"), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _note(proj: Path, kind: str) -> Path:
    return proj / "docs" / "CTS관리대장" / f"CTS관리대장_{kind}.md"


def _rows(proj: Path, kind: str) -> list[list[str]]:
    lines = _note(proj, kind).read_text(encoding="utf-8").split("\n")
    i = next(i for i, ln in enumerate(lines) if ln.startswith("| 오픈단계") and "Request NO" in ln)
    out = []
    for ln in lines[i + 2:]:
        if not ln.startswith("|"):
            break
        out.append(cts_fill._cells(ln))
    return out


COLS = KINDS["Configuration"][1]


def test_매핑_사본은_읽히고_종류는_두_작업본으로_간다():
    mp = cts_fill.load_map(SKILL / "cts-fill.yaml")
    assert {v["작업본"] for v in mp["종류"].values()} == set(KINDS)
    assert mp["값"]["CTS 유형"] == {"customizing": "IMG", "workbench": "PGM"}


def test_빈_표에_새_행을_더하고_사람_칸은_비운다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1), _tr(2, date="20261103")])
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 0 and [a["no"] for a in rep["results"]["Configuration"]["added"]] == [1, 2]
    r1, r2 = _rows(proj, "Configuration")
    assert r1[COLS.index("NO")] == "1" and r2[COLS.index("NO")] == "2"
    assert r1[COLS.index("Request NO")] == "Z5UK900001" and r1[COLS.index("Description")] == "설명 1"
    assert r1[COLS.index("요청자")] == "USER1" and r1[COLS.index("Target System")] == "Z5Q"
    assert r1[COLS.index("요청일")] == "2026-11-02" and r2[COLS.index("요청일")] == "2026-11-03"  # YYYYMMDD 변환
    assert r1[COLS.index("CTS 유형")] == "IMG"
    for human in ("오픈단계", "모둘", "주요변경 및 특이사항", "처리일자", "처리자", "처리결과", "승인"):
        assert r1[COLS.index(human)] == "", human


def test_기존_행은_건드리지_않고_NO는_이어_매긴다(proj, capsys):
    old = _req(1, **{"Request NO": "Z5UK900001", "Description": "사람이 쓴 설명", "모둘": "FI"})
    _write(proj, "Configuration", _worknote("Configuration", [old, _req(7, **{"Request NO": "다른요청"})], []))
    _json(proj, [_tr(1), _tr(2)])
    before = _note(proj, "Configuration").read_text(encoding="utf-8")
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 0
    res = rep["results"]["Configuration"]
    assert res["kept"] == ["Z5UK900001"] and [a["no"] for a in res["added"]] == [8]
    after = _note(proj, "Configuration").read_text(encoding="utf-8")
    assert all(ln in after for ln in before.split("\n") if ln.startswith("|"))  # 기존 줄은 그대로 남는다
    rows = _rows(proj, "Configuration")
    assert rows[0][COLS.index("Description")] == "사람이 쓴 설명" and rows[0][COLS.index("모둘")] == "FI"
    assert rows[2][COLS.index("Request NO")] == "Z5UK900002" and rows[2][COLS.index("NO")] == "8"


def test_fill_empty는_기존_행의_빈_칸만_채운다(proj, capsys):
    old = _req(1, **{"Request NO": "Z5UK900001", "Description": "사람이 쓴 설명", "요청자": "", "Target System": ""})
    old["요청일"] = ""
    _write(proj, "Configuration", _worknote("Configuration", [old], []))
    _json(proj, [_tr(1)])
    code, rep = _fill(proj, capsys, ["Configuration"], "--fill-empty")
    assert code == 0 and rep["results"]["Configuration"]["filled"][0]["number"] == "Z5UK900001"
    [row] = _rows(proj, "Configuration")
    assert row[COLS.index("Description")] == "사람이 쓴 설명"  # 있던 값은 그대로
    assert row[COLS.index("요청자")] == "USER1" and row[COLS.index("요청일")] == "2026-11-02"
    assert row[COLS.index("모둘")] == "FI"  # 사람 칸 유지


def test_종류_분기_워크벤치는_CBO_작업본으로_간다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _write(proj, "CBO", _worknote("CBO", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench", target="")])
    code, rep = _fill(proj, capsys, ["Configuration", "CBO"])
    assert code == 0
    assert [r[COLS.index("Request NO")] for r in _rows(proj, "Configuration")] == ["Z5UK900001"]
    cbo = KINDS["CBO"][1]
    [row] = _rows(proj, "CBO")
    assert row[cbo.index("Request NO")] == "Z5UK900002" and row[cbo.index("CTS 유형")] == "PGM"
    assert row[cbo.index("Target System")] == "" and row[cbo.index("Client 종속여부")] == ""


def test_채울_작업본이_없는_종류는_경고_3이고_그_건은_조용히_빠지지_않는다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench")])
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 3 and rep["status"] == "warning"
    assert rep["unrouted"] == [{"number": "Z5UK900002", "category": "workbench", "kind": "CBO"}]
    assert len(_rows(proj, "Configuration")) == 1


@pytest.mark.parametrize("bad", [
    {"transports": "x"},
    {"nothing": []},
    {"transports": [_tr(1, date="11/2")]},
    {"transports": [_tr(1, date="2026-13-01")]},
    {"transports": [_tr(1, date=1730505600000)]},
    {"transports": [_tr(1, category="mystery")]},
    {"transports": [{"number": "Z5UK900001", "description": "d", "date": "2026-11-02", "category": "workbench"}]},  # owner 없음
    {"transports": [{**_tr(1), "number": ""}]},
    {"transports": [_tr(1), _tr(1)]},
    {"transports": [_tr(1)], "unread": [{"number": "Z5UK900009", "reason": "401"}]},
])
def test_형식이_다르거나_읽지_못한_값은_검사_불능_2이고_파일을_바꾸지_않는다(proj, capsys, bad):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    (proj / "transports.json").write_text(json.dumps(bad), encoding="utf-8")
    before = _note(proj, "Configuration").read_bytes()
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 2 and rep["status"] == "error" and rep["problems"]
    assert _note(proj, "Configuration").read_bytes() == before


def test_JSON이_아니거나_없으면_검사_불능이다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    (proj / "transports.json").write_text("<html>401</html>", encoding="utf-8")
    assert _fill(proj, capsys, ["Configuration"])[0] == 2
    (proj / "transports.json").unlink()
    assert _fill(proj, capsys, ["Configuration"])[0] == 2


def test_요청_표가_없거나_NO가_숫자가_아니면_검사_불능이다(proj, capsys):
    _write(proj, "Configuration", "# CTS 관리대장 Configuration\n\n버전: 0.1\n\n## 양식 항목\n")
    _json(proj, [_tr(1)])
    assert _fill(proj, capsys, ["Configuration"])[0] == 2
    _write(proj, "Configuration", _worknote("Configuration", [_req(1, NO="가")], []))
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 2 and "숫자가 아니라" in rep["problems"][0]["reason"]


def test_check는_쓰지_않고_같은_보고를_낸다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1)])
    before = _note(proj, "Configuration").read_bytes()
    code, rep = _fill(proj, capsys, ["Configuration"], "--check")
    assert code == 0 and rep["written"] == [] and len(rep["results"]["Configuration"]["added"]) == 1
    assert _note(proj, "Configuration").read_bytes() == before


def test_줄바꿈_CRLF를_유지하고_파이프_줄바꿈은_이스케이프한다(proj, capsys):
    text = _worknote("Configuration", [], []).replace("\n", "\r\n")
    _note(proj, "Configuration").write_bytes(text.encode("utf-8"))
    _json(proj, [_tr(1, description="a|b\nc")])
    code, _ = _fill(proj, capsys, ["Configuration"])
    assert code == 0
    raw = _note(proj, "Configuration").read_bytes().decode("utf-8")
    assert "\n" not in raw.replace("\r\n", "")
    assert "a\\|b<br>c" in raw
    [row] = [cts_fill._cells(ln) for ln in raw.split("\r\n") if "Z5UK900001" in ln]
    assert row[COLS.index("Description")] == "a|b\nc"


def test_채운_작업본은_산출_check를_통과한다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _write(proj, "CBO", _worknote("CBO", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench"), _tr(3)])
    assert _fill(proj, capsys, ["Configuration", "CBO"])[0] == 0
    for kind in KINDS:
        code = export.main(["--spec", str(_note(proj, kind)), "--form", f"CTS_관리대장_{kind}", "--root", str(proj), "--check"])
        rep = json.loads(capsys.readouterr().out)
        assert code == 0, rep


def test_다시_돌려도_같은_결과다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1), _tr(2)])
    assert _fill(proj, capsys, ["Configuration"])[0] == 0
    once = _note(proj, "Configuration").read_bytes()
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 0 and rep["written"] == [] and _note(proj, "Configuration").read_bytes() == once


def test_작업본_이름이_틀리면_검사_불능이다(proj, capsys):
    p = proj / "docs" / "CTS관리대장" / "아무거나.md"
    p.write_text(_worknote("Configuration", [], []), encoding="utf-8")
    _json(proj, [_tr(1)])
    code = cts_fill.main(["--spec", str(p), "--transports", str(proj / "transports.json"), "--map", str(SKILL / "cts-fill.yaml")])
    assert code == 2 and "이름" in capsys.readouterr().out


def test_매핑에_모르는_키가_있으면_검사_불능이다(proj, capsys, tmp_path):
    mp = yaml.safe_load((SKILL / "cts-fill.yaml").read_text(encoding="utf-8"))
    mp["열"]["rank"] = "순위"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1)])
    code = cts_fill.main(["--spec", str(_note(proj, "Configuration")), "--transports", str(proj / "transports.json"), "--map", str(bad)])
    assert code == 2


# ---------------------------------------------------------------- ADT 응답(실측 견본) → 중간 JSON

ADT_SAMPLE = Path(__file__).parent / "data" / "adt-transports-sample.json"
CBO = KINDS["CBO"][1]


def _adt(proj: Path, data: dict) -> None:
    (proj / "transports.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _adt_fill(proj: Path, capsys, kinds: list[str], *extra: str, mp: Path = SKILL / "cts-fill.yaml"):
    args = []
    for k in kinds:
        args += ["--spec", str(_note(proj, k))]
    code = cts_fill.main([*args, "--transports", str(proj / "transports.json"), "--adt", "--map", str(mp), *extra])
    return code, json.loads(capsys.readouterr().out)


def test_실측_응답은_task를_빼고_요청_세_건으로_바뀐다():
    mp = cts_fill.load_map(SKILL / "cts-fill.yaml")
    out = cts_fill.adt_to_transports(json.loads(ADT_SAMPLE.read_text(encoding="utf-8")), mp)
    assert [t["number"] for t in out["transports"]] == ["Z5UK900700", "Z5UK900698", "Z5UK900690"]
    assert all(t["category"] == "workbench" and t["owner"] == "TESTUSER" and t["target"] == "" and t["date"] == "" for t in out["transports"])


def test_실측_응답을_CBO_작업본에_채우면_요청일은_비고_export_check를_통과한다(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [], []))
    (proj / "transports.json").write_text(ADT_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    code, rep = _adt_fill(proj, capsys, ["CBO"])
    assert code == 0 and [a["no"] for a in rep["results"]["CBO"]["added"]] == [1, 2, 3]
    rows = _rows(proj, "CBO")
    assert [r[CBO.index("Request NO")] for r in rows] == ["Z5UK900690", "Z5UK900698", "Z5UK900700"]  # 요청일이 같아 번호순
    assert all(r[CBO.index("요청일")] == "" and r[CBO.index("CTS 유형")] == "PGM" and r[CBO.index("요청자")] == "TESTUSER" for r in rows)
    assert not any("Z5UK900701" in ln for ln in _note(proj, "CBO").read_text(encoding="utf-8").split("\n"))  # task 는 행이 아니다
    code = export.main(["--spec", str(_note(proj, "CBO")), "--form", "CTS_관리대장_CBO", "--root", str(proj), "--check"])
    assert code == 0, capsys.readouterr().out


def test_요청일_출처가_lastchanged일_때만_마지막_변경일을_쓴다(proj, capsys, tmp_path):
    mp = yaml.safe_load((SKILL / "cts-fill.yaml").read_text(encoding="utf-8"))
    mp["요청일_출처"] = "lastchanged"
    mpf = tmp_path / "m.yaml"
    mpf.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    _write(proj, "CBO", _worknote("CBO", [], []))
    (proj / "transports.json").write_text(ADT_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    code, _ = _adt_fill(proj, capsys, ["CBO"], mp=mpf)
    assert code == 0
    assert [r[CBO.index("요청일")] for r in _rows(proj, "CBO")] == ["2026-09-01", "2026-09-23", "2026-09-29"]


def _sample() -> dict:
    return json.loads(ADT_SAMPLE.read_text(encoding="utf-8"))


def test_released는_옵션일_때만_들어간다():
    mp = cts_fill.load_map(SKILL / "cts-fill.yaml")
    d = _sample()
    rel = dict(d["transports"]["workbench"][0]["modifiable"][0], **{"tm:number": "Z5UK900500", "tm:tasks": None})
    d["transports"]["workbench"][0]["released"] = [rel]
    assert len(cts_fill.adt_to_transports(d, mp)["transports"]) == 3
    assert len(cts_fill.adt_to_transports(d, mp, include_released=True)["transports"]) == 4


def _mut(fn):
    d = _sample()
    fn(d)
    return d


@pytest.mark.parametrize("bad", [
    {"status": "success"},
    {"transports": []},
    {"status": "error", "transports": {}},
    _mut(lambda d: d["transports"].update(other=[])),
    _mut(lambda d: d["transports"].update(workbench={})),
    _mut(lambda d: d["transports"]["workbench"][0].pop("released")),
    _mut(lambda d: d["transports"]["workbench"][0]["modifiable"][0].pop("tm:number")),
    _mut(lambda d: d["transports"]["workbench"][0]["modifiable"][0].update({"tm:parent": "Z5UK900001"})),
    _mut(lambda d: d["transports"]["workbench"][0]["modifiable"][0].pop("tm:owner")),
])
def test_ADT_응답_모양이_다르면_검사_불능이고_파일을_바꾸지_않는다(proj, capsys, bad):
    _write(proj, "CBO", _worknote("CBO", [], []))
    _adt(proj, bad)
    before = _note(proj, "CBO").read_bytes()
    code, rep = _adt_fill(proj, capsys, ["CBO"])
    assert code == 2 and rep["status"] == "error"
    assert _note(proj, "CBO").read_bytes() == before


def test_lastchanged_시각이_14자리가_아니면_검사_불능이다(proj, capsys, tmp_path):
    mp = yaml.safe_load((SKILL / "cts-fill.yaml").read_text(encoding="utf-8"))
    mp["요청일_출처"] = "lastchanged"
    mpf = tmp_path / "m.yaml"
    mpf.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    _write(proj, "CBO", _worknote("CBO", [], []))
    _adt(proj, _mut(lambda d: d["transports"]["workbench"][0]["modifiable"][0].update({"tm:lastchanged_timestamp": 20260929})))
    code, rep = _adt_fill(proj, capsys, ["CBO"], mp=mpf)
    assert code == 2 and "14자리" in rep["problems"][0]["reason"]


# ---------------------------------------------------------------- 독립 검토 뒤 보완

def test_읽은_요청이_0건이면_no_transports_경고_3이다(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [], []))
    _adt(proj, {"status": "success", "transports": {"workbench": [], "customizing": []}})
    code, rep = _adt_fill(proj, capsys, ["CBO"])
    assert code == 3 and rep["status"] == "warning" and rep["read"] == 0
    [w] = rep["warnings"]
    assert w["type"] == "no-transports" and "transportsByConfig" in w["message"]
    # 그룹은 있는데 요청이 없는 응답도 같다
    _adt(proj, {"status": "success", "transports": {"workbench": [{"modifiable": [], "released": []}]}})
    assert _adt_fill(proj, capsys, ["CBO"])[0] == 3


def test_보고에_읽은_요청_수가_있다(proj, capsys):
    _write(proj, "CBO", _worknote("CBO", [], []))
    (proj / "transports.json").write_text(ADT_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    code, rep = _adt_fill(proj, capsys, ["CBO"])
    assert code == 0 and rep["read"] == 3 and rep["warnings"] == []


def test_경고_3이어도_라우팅된_작업본은_반영된다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench")])
    code, rep = _fill(proj, capsys, ["Configuration"])
    assert code == 3 and rep["written"] and [w["type"] for w in rep["warnings"]] == ["unrouted"]
    assert len(_rows(proj, "Configuration")) == 1


def _mapfile(tmp_path: Path, **edit) -> Path:
    mp = yaml.safe_load((SKILL / "cts-fill.yaml").read_text(encoding="utf-8"))
    for k, fn in edit.items():
        fn(mp[k])
    p = tmp_path / "m.yaml"
    p.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    return p


def test_매핑의_열이_작업본_머리글에_없으면_조용히_버리지_않고_종료_2(proj, capsys, tmp_path):
    _write(proj, "CBO", _worknote("CBO", [], []))
    _json(proj, [_tr(1, "workbench")])
    before = _note(proj, "CBO").read_bytes()
    for edit in (lambda c: c.update(owner="없는열"), lambda c: c.update(target="Target Systm")):
        mpf = _mapfile(tmp_path, 열=edit)
        code = cts_fill.main(["--spec", str(_note(proj, "CBO")), "--transports", str(proj / "transports.json"), "--map", str(mpf)])
        out = json.loads(capsys.readouterr().out)
        assert code == 2 and "지도·매핑 오류" in out["problems"][0]["reason"]
    code = cts_fill.main(["--spec", str(_note(proj, "CBO")), "--transports", str(proj / "transports.json"),
                          "--map", str(_mapfile(tmp_path, 값=lambda v: v.update({"없는 값 열": {"workbench": "x"}})))])
    assert code == 2 and "없는 값 열" in capsys.readouterr().out
    assert _note(proj, "CBO").read_bytes() == before


def test_작업본_파일명_정규식은_매핑에서_읽는다(proj, capsys, tmp_path):
    mpf = _mapfile(tmp_path, 종류=lambda k: None)  # 그대로 저장
    mp = yaml.safe_load(mpf.read_text(encoding="utf-8"))
    mp["작업본_파일명"] = r"^대장_(?P<kind>.+)\.md$"
    mpf.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    p = proj / "docs" / "CTS관리대장" / "대장_CBO.md"
    p.write_text(_worknote("CBO", [], []), encoding="utf-8")
    _json(proj, [_tr(1, "workbench")])
    assert cts_fill.main(["--spec", str(p), "--transports", str(proj / "transports.json"), "--map", str(mpf)]) == 0
    capsys.readouterr()
    mp["작업본_파일명"] = r"^대장_.+\.md$"  # 이름 그룹 kind 없음
    mpf.write_text(yaml.safe_dump(mp, allow_unicode=True), encoding="utf-8")
    assert cts_fill.main(["--spec", str(p), "--transports", str(proj / "transports.json"), "--map", str(mpf)]) == 2


def test_transports를_여러_번_주면_합치고_같은_번호는_한_번만_쓴다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    a, b = proj / "a.json", proj / "b.json"
    a.write_text(json.dumps({"transports": [_tr(1), _tr(2)]}), encoding="utf-8")
    b.write_text(json.dumps({"transports": [_tr(2), _tr(3)]}), encoding="utf-8")
    code = cts_fill.main(["--spec", str(_note(proj, "Configuration")), "--transports", str(a), "--transports", str(b),
                          "--map", str(SKILL / "cts-fill.yaml")])
    rep = json.loads(capsys.readouterr().out)
    assert code == 0 and rep["read"] == 3
    assert [r[COLS.index("Request NO")] for r in _rows(proj, "Configuration")] == ["Z5UK900001", "Z5UK900002", "Z5UK900003"]


def test_여러_파일_중_하나라도_형식이_이상하면_아무것도_쓰지_않는다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    a, b = proj / "a.json", proj / "b.json"
    a.write_text(json.dumps({"transports": [_tr(1)]}), encoding="utf-8")
    b.write_text(json.dumps({"transports": [_tr(2, date="내일")]}), encoding="utf-8")
    before = _note(proj, "Configuration").read_bytes()
    code = cts_fill.main(["--spec", str(_note(proj, "Configuration")), "--transports", str(a), "--transports", str(b),
                          "--map", str(SKILL / "cts-fill.yaml")])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and "b.json" in out["problems"][0]["reason"]
    assert _note(proj, "Configuration").read_bytes() == before


def test_자리표시_행의_NO는_이어_매기기에서_뺀다(proj, capsys):
    _write(proj, "Configuration", _worknote("Configuration", [_req(99, **{"Request NO": "<값>"})], []))
    _json(proj, [_tr(1)])
    assert _fill(proj, capsys, ["Configuration"])[0] == 0
    rows = _rows(proj, "Configuration")
    assert rows[0][COLS.index("Request NO")] == "<값>" and rows[1][COLS.index("NO")] == "1"


def test_쓸_때_원래_파일_권한을_임시_파일에_복사한다(proj, capsys, monkeypatch):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    note = _note(proj, "Configuration")
    note.chmod(0o640)
    want = note.stat().st_mode & 0o7777
    seen = []
    real = cts_fill.os.chmod
    monkeypatch.setattr(cts_fill.os, "chmod", lambda p, m: (seen.append((str(p), m)), real(p, m))[1])
    _json(proj, [_tr(1)])
    assert _fill(proj, capsys, ["Configuration"])[0] == 0
    assert seen and all(m == want for _, m in seen) and all(p.endswith(".tmp") for p, _ in seen)


def test_교체가_중간에_실패하면_이미_바꾼_작업본도_되돌리고_임시_파일을_남기지_않는다(proj, capsys, monkeypatch):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _write(proj, "CBO", _worknote("CBO", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench")])
    before = {k: _note(proj, k).read_bytes() for k in KINDS}
    real, calls = cts_fill.os.replace, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise OSError("교체 실패 시험")
        return real(src, dst)

    monkeypatch.setattr(cts_fill.os, "replace", flaky)
    code, rep = _fill(proj, capsys, ["Configuration", "CBO"])
    assert code == 2 and "교체 실패 시험" in json.dumps(rep, ensure_ascii=False)
    assert {k: _note(proj, k).read_bytes() for k in KINDS} == before
    assert not list((proj / "docs" / "CTS관리대장").glob("*.tmp"))


def test_임시_파일_준비가_실패하면_아무것도_바뀌지_않는다(proj, capsys, monkeypatch):
    _write(proj, "Configuration", _worknote("Configuration", [], []))
    _write(proj, "CBO", _worknote("CBO", [], []))
    _json(proj, [_tr(1), _tr(2, "workbench")])
    before = {k: _note(proj, k).read_bytes() for k in KINDS}
    real, n = cts_fill.tempfile.mkstemp, []

    def flaky(*a, **kw):
        n.append(1)
        if len(n) == 2:
            raise OSError("임시 파일 시험")
        return real(*a, **kw)

    monkeypatch.setattr(cts_fill.tempfile, "mkstemp", flaky)
    assert _fill(proj, capsys, ["Configuration", "CBO"])[0] == 2
    assert {k: _note(proj, k).read_bytes() for k in KINDS} == before
    assert not list((proj / "docs" / "CTS관리대장").glob("*.tmp"))


def test_인자_오류도_JSON_한_줄_종료_2다(capsys):
    code = cts_fill.main(["--nothing"])
    out = capsys.readouterr()
    assert code == 2 and out.out.count("\n") == 1 and json.loads(out.out)["status"] == "error"
    assert out.err == ""
