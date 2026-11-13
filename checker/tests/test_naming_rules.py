"""개발 표준 이름 규칙 검사(#943): 엔진 모듈과 PR 검사(check_changed) 연결."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from checker import naming_rules as nr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_changed import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main_entry  # noqa: E402

CONFIG = """\
영역코드: [SD, LE, PP]
객체:
  MSAG: {형식: '^Z{영역}$', 최대_길이: 20}
  CLAS: {형식: '^Z(CL|BP)_.+$', 최대_길이: 30}
  TABL/DT: {형식: '^Z{영역}[AD]\\d{4}(_TEXT)?$', 최대_길이: 16}
  TABL/DS: {형식: '^Z{영역}_S_.+$', 최대_길이: 30}
예외: [ZMM_MSG]
"""


def _cfg(text: str = CONFIG) -> nr.NamingConfig:
    return nr.parse_config(text, Path("naming.yaml"))


def _project(tmp_path: Path, text: str | None = CONFIG) -> Path:
    (tmp_path / ".git").mkdir()
    if text is not None:
        (tmp_path / "conventions").mkdir()
        (tmp_path / "conventions" / "naming.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_형식에_맞으면_통과한다():
    assert nr.check_name(_cfg(), "CLAS", "ZCL_ORDER")["status"] == "pass"


def test_형식에_안_맞으면_위반이고_이유와_규칙을_준다():
    r = nr.check_name(_cfg(), "CLAS", "YCL_ORDER")
    assert r["status"] == "violation"
    assert "형식" in r["reasons"][0]
    assert r["rules"][0]["형식"] == "^Z(CL|BP)_.+$"


def test_최대_길이를_넘으면_위반이다():
    r = nr.check_name(_cfg(), "CLAS", "ZCL_" + "A" * 27)
    assert r["status"] == "violation"
    assert "31자" in r["reasons"][0]


def test_대소문자는_무시한다():
    assert nr.check_name(_cfg(), "clas", "zcl_order")["status"] == "pass"


def test_영역은_코드_목록으로_바뀐다():
    cfg = _cfg()
    assert nr.check_name(cfg, "MSAG", "ZSD")["status"] == "pass"
    assert nr.check_name(cfg, "MSAG", "ZXX")["status"] == "violation"
    assert nr.check_name(cfg, "MSAG", "ZSDLE")["status"] == "violation"  # 전체 일치


def test_예외_이름은_형식과_길이를_건너뛴다():
    assert nr.check_name(_cfg(), "MSAG", "zmm_msg")["status"] == "exception"


def test_파일에_없는_종류는_규칙이_없어_통과한다():
    assert nr.check_name(_cfg(), "INTF", "whatever")["status"] == "no_rule"


def test_하위_종류를_알면_그_규칙만_본다():
    cfg = _cfg()
    assert nr.check_name(cfg, "TABL/DT", "ZSDA0001")["status"] == "pass"
    assert nr.check_name(cfg, "TABL/DT", "ZSD_S_ORDER")["status"] == "violation"
    assert nr.check_name(cfg, "TABL/DS", "ZSD_S_ORDER")["status"] == "pass"


def test_하위_종류를_모르면_하위_규칙_중_하나라도_맞으면_통과한다():
    cfg = _cfg()
    assert nr.check_name(cfg, "TABL", "ZSDA0001")["status"] == "pass"
    assert nr.check_name(cfg, "TABL", "ZSD_S_ORDER")["status"] == "pass"
    assert nr.check_name(cfg, "TABL", "ZSD_ORDER")["status"] == "violation"


def test_하위_종류가_규칙에_없으면_4글자_규칙을_쓴다():
    assert nr.check_name(_cfg(), "CLAS/OC", "YCL_X")["status"] == "violation"


@pytest.mark.parametrize(
    "text",
    [
        "이상한키: 1\n",
        "객체:\n  CLAS: {최대_길이: 30}\n",  # 형식 없음
        "객체:\n  CLAS: {형식: '(', 최대_길이: 30}\n",  # 정규식 오류
        "객체:\n  CLAS: {형식: '^Z', 모름: 1}\n",
        "객체:\n  CLAS: {형식: '^Z', 최대_길이: 0}\n",
        "객체:\n  CLASS: {형식: '^Z'}\n",  # 종류 4글자 아님
        "객체:\n  MSAG: {형식: '^Z{영역}$'}\n",  # 영역코드 없이 {영역}
        "영역코드: SD\n",
        ": : :\n",
    ],
)
def test_설정_오류는_검사_불능이다(text):
    with pytest.raises(nr.NamingConfigError):
        nr.parse_config(text, Path("naming.yaml"))


@pytest.mark.parametrize(
    "path,expected",
    [
        ("src/zcl_order.clas.abap", ("CLAS", "ZCL_ORDER")),
        ("src/zcl_order.clas.locals_imp.abap", ("CLAS", "ZCL_ORDER")),
        ("src/zcl_order.clas.testclasses.abap", ("CLAS", "ZCL_ORDER")),
        ("src/zcl_order.clas.xml", ("CLAS", "ZCL_ORDER")),
        ("src/zcsh_c_griv.ddls.asddls", ("DDLS", "ZCSH_C_GRIV")),
        ("src/sub/zsda0001.tabl.astabldt", ("TABL", "ZSDA0001")),
        ("src/#cust#zcl_x.clas.abap", ("CLAS", "/CUST/ZCL_X")),
        ("src/package.devc.xml", None),
        ("src/.abapgit.xml", None),
        ("docs/zcl_order.clas.abap", None),
        ("src/README.md", None),
    ],
)
def test_파일_경로에서_종류와_이름을_뽑는다(path, expected):
    assert nr.object_from_path(path) == expected


def test_딸림_파일은_같은_객체로_한_번만_검사한다():
    r = nr.check_files(
        _cfg(),
        ["src/ycl_x.clas.abap", "src/ycl_x.clas.locals_imp.abap", "src/ycl_x.clas.xml"],
    )
    assert r["checked"] == 1 and len(r["violations"]) == 1
    assert r["violations"][0]["file"] == "src/ycl_x.clas.abap"


def test_설정_파일을_위로_올라가며_찾고_git에서_멈춘다(tmp_path):
    root = _project(tmp_path)
    deep = root / "a" / "b"
    deep.mkdir(parents=True)
    assert nr.find_config(deep) == (root / "conventions" / "naming.yaml").resolve()
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    assert nr.find_config(other) is None


def test_설정_파일이_없으면_검사하지_않는다(tmp_path):
    root = _project(tmp_path, None)
    assert nr.evaluate_files(["src/ycl_x.clas.abap"], root) == {"status": "not_applicable"}


def test_cli_check는_종료코드로_답한다(tmp_path, capsys):
    root = _project(tmp_path)
    assert nr.main(["check", "--type", "CLAS/OC", "--name", "ZCL_A", "--root", str(root)]) == 0
    assert nr.main(["check", "--type", "CLAS/OC", "--name", "XCL_A", "--root", str(root)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert json.loads(out[-1])["status"] == "violation"


def test_cli_check는_설정_오류를_2로_답한다(tmp_path):
    root = _project(tmp_path, "모르는키: 1\n")
    assert nr.main(["check", "--type", "CLAS", "--name", "ZCL_A", "--root", str(root)]) == 2


def test_cli_check는_설정이_없으면_0이다(tmp_path):
    root = _project(tmp_path, None)
    assert nr.main(["check", "--type", "CLAS", "--name", "X", "--root", str(root)]) == 0


def test_cli_files(tmp_path, capsys):
    root = _project(tmp_path)
    listing = tmp_path / "added.txt"
    listing.write_text("src/zcl_ok.clas.abap\nsrc/xcl_bad.clas.abap\n", encoding="utf-8")
    assert nr.main(["files", str(listing), "--root", str(root)]) == 1
    result = json.loads(capsys.readouterr().out)
    assert [v["name"] for v in result["violations"]] == ["XCL_BAD"]


# --- check_changed 연결: 추가된 파일만 본다 ------------------------------------


def _pr(tmp_path: Path, monkeypatch, changed: list[str], added: list[str], config: str | None = CONFIG):
    root = _project(tmp_path, config)
    for name in changed:
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("CLASS x DEFINITION.\n", encoding="utf-8")
    (root / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
    (root / "added.txt").write_text("\n".join(added) + "\n", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setenv("DOC_GUARD_ADDED_FILES", "added.txt")
    return root


def test_추가된_파일의_형식_밖_이름은_위반이다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/xcl_bad.clas.abap"], ["src/xcl_bad.clas.abap"])
    assert main_entry(["changed.txt"]) == EXIT_VIOLATION
    out = json.loads(capsys.readouterr().out)
    assert out["naming"]["status"] == "violation"
    assert out["naming"]["violations"][0]["name"] == "XCL_BAD"


def test_수정만_된_파일은_형식_밖이어도_통과한다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/xcl_old.clas.abap"], [])
    assert main_entry(["changed.txt"]) == EXIT_PASS
    out = json.loads(capsys.readouterr().out)
    assert out["naming"] == {
        "status": "pass", "checked": 0, "violations": [], "config": out["naming"]["config"],
    }


def test_추가된_딸림_파일은_한_번만_센다(tmp_path, monkeypatch, capsys):
    files = ["src/zcl_ok.clas.abap", "src/zcl_ok.clas.testclasses.abap"]
    _pr(tmp_path, monkeypatch, files, files)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert json.loads(capsys.readouterr().out)["naming"]["checked"] == 1


def test_설정이_없으면_이름_검사_키가_없다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/xcl_bad.clas.abap"], ["src/xcl_bad.clas.abap"], config=None)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert "naming" not in json.loads(capsys.readouterr().out)


def test_설정이_깨졌으면_검사_불능이다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/zcl_ok.clas.abap"], ["src/zcl_ok.clas.abap"], config="모르는키: 1\n")
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR
    assert json.loads(capsys.readouterr().out)["naming"]["status"] == "cannot_check"


def test_추가_목록을_못_읽으면_검사_불능이다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/zcl_ok.clas.abap"], [])
    monkeypatch.setenv("DOC_GUARD_ADDED_FILES", "없는파일.txt")
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR


def test_환경변수가_없으면_이름_검사를_하지_않는다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, ["src/xcl_bad.clas.abap"], ["src/xcl_bad.clas.abap"])
    monkeypatch.delenv("DOC_GUARD_ADDED_FILES")
    assert main_entry(["changed.txt"]) == EXIT_PASS
