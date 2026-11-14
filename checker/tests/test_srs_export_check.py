"""산출 엑셀이 SRS 와 같은 판인지 확인하는 `checker/srs_export_check.py`(#976)를 검증한다.

compare(same·differ·cannot_check), 칸 값 비교(바이트가 달라도 같다), PR 검사 연결(check_changed), push-check, merge-guard(훅이 부르는 엔진) 를 본다.
훅 자체는 test_plugin_layout.py 에서 가짜 uvx 로 본다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl
import pytest

from checker import export, srs_export_check as sec
from checker.pairing import SRS_PATH
from checker.ssot_approval import GhError
from checker.tests import test_export as te

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_changed import main_entry  # noqa: E402
from render_report import render  # noqa: E402

XLSX = "docs/srs/BW_Backlog List_v0.2.xlsx"
MAP = te.BACKLOG_MAP.replace("folder: docs/out", "").replace("폴더: docs/out", "폴더: docs/srs")


def _make_excel(proj: Path, srs_text: str, dest: Path, tmp: Path) -> None:
    """proj 의 지도·틀로 srs_text 를 산출해 dest 에 복사한다(진짜 산출 결과를 저장소 엑셀로 쓴다)."""
    srs = tmp / "SRS_for_excel.md"
    srs.write_text(srs_text, encoding="utf-8")
    out = tmp / "made.xlsx"
    code, report = export.run(srs, proj, "Backlog", False, out)
    assert code == 0, report
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out.read_bytes())


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "templates" / "forms").mkdir(parents=True)
    (root / "templates" / "forms" / "Backlog.yaml").write_text(MAP, encoding="utf-8")
    te._backlog_template(root / "templates" / "Backlog.xlsx")
    (root / "docs" / "ssot").mkdir(parents=True)
    (root / SRS_PATH).write_text(te.SRS_MD, encoding="utf-8")
    _make_excel(root, te.SRS_MD, root / XLSX, tmp_path)
    return root


def _status(root: Path) -> dict:
    result = sec.compare(root)
    sec.xlsx_reader.clear_cache()
    return result


# --- compare ---------------------------------------------------------------

def test_같은_SRS_로_만든_엑셀이면_same(proj):
    result = _status(proj)
    assert result["status"] == "same" and result["version"] == "0.2"
    assert result["forms"][0]["file"] == XLSX


def test_SRS_내용이_바뀌면_differ_이고_다른_칸을_알려_준다(proj):
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("| REQ-002 | 결재 |", "| REQ-002 | 결재 바뀜 |"), encoding="utf-8")
    result = _status(proj)
    assert result["status"] == "differ"
    form = result["forms"][0]
    assert form["differences"] >= 1
    assert {"sheet": "Backlog", "cell": "C4", "repo": "결재", "regenerated": "결재 바뀜"} in form["cells"]


def test_요구사항을_더하면_새_행이_differ_로_잡힌다(proj):
    extra = te.SRS_MD.replace("| REQ-003 | 보고서 | Sales | Planned | 2. Should-Have |  | 메일 |",
                              "| REQ-003 | 보고서 | Sales | Planned | 2. Should-Have |  | 메일 |\n| REQ-004 | 새것 | Sales | New | 2. Should-Have |  | 메일 |")
    (proj / SRS_PATH).write_text(extra, encoding="utf-8")
    result = _status(proj)
    assert result["status"] == "differ"
    assert any(c["cell"] == "C6" and c["repo"] == "" for c in result["forms"][0]["cells"])


def test_버전_줄만_다른_엑셀과_비교하지_않는다_판_이름이_엑셀을_정한다(proj):
    # 버전 0.3 이면 v0.3 엑셀을 찾는다 — 없으면 같다고도 다르다고도 하지 않는다.
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("버전: 0.2", "버전: 0.3"), encoding="utf-8")
    result = _status(proj)
    assert result["status"] == "cannot_check" and "v0.3" in result["message"]


def test_바이트가_달라도_칸_값이_같으면_same(proj, tmp_path):
    """저장 환경에 따라 압축 바이트가 다르다 — 엑셀로 다시 저장해도(바이트 변화) 값이 같으면 같다."""
    before = (proj / XLSX).read_bytes()
    wb = openpyxl.load_workbook(proj / XLSX)
    wb.save(proj / XLSX)
    assert (proj / XLSX).read_bytes() != before
    assert _status(proj)["status"] == "same"


def test_저장소_엑셀의_값을_손으로_고치면_differ(proj):
    wb = openpyxl.load_workbook(proj / XLSX)
    wb["Backlog"]["C4"] = "손으로 고침"
    wb.save(proj / XLSX)
    result = _status(proj)
    assert result["status"] == "differ"
    assert {"sheet": "Backlog", "cell": "C4", "repo": "손으로 고침", "regenerated": "결재"} in result["forms"][0]["cells"]


def test_양식_지도가_쓰지_않는_칸은_비교하지_않는다(proj):
    wb = openpyxl.load_workbook(proj / XLSX)
    wb["Backlog"]["Z30"] = "범위 밖"  # 지도의 열(A~H) 밖
    wb.save(proj / XLSX)
    assert _status(proj)["status"] == "same"


def test_다른_칸_목록은_열_개까지만_싣고_개수는_다_센다(proj):
    rows = "\n".join(f"| REQ-{n:03d} | 항목{n} | Sales | New | 2. Should-Have |  | 메일 |" for n in range(10, 20))
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("| REQ-003 | 보고서 | Sales | Planned | 2. Should-Have |  | 메일 |",
                                                   "| REQ-003 | 보고서 | Sales | Planned | 2. Should-Have |  | 메일 |\n" + rows), encoding="utf-8")
    form = _status(proj)["forms"][0]
    assert form["differences"] > sec.MAX_LISTED and len(form["cells"]) == sec.MAX_LISTED


def test_저장소_엑셀이_없으면_검사_불능(proj):
    (proj / XLSX).unlink()
    result = _status(proj)
    assert result["status"] == "cannot_check" and "없습니다" in result["message"]


def test_버전_줄이_없으면_검사_불능(proj):
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("버전: 0.2\n", ""), encoding="utf-8")
    assert _status(proj)["status"] == "cannot_check"


def test_SRS_를_못_읽으면_검사_불능(proj):
    (proj / SRS_PATH).unlink()
    assert _status(proj)["status"] == "cannot_check"


def test_양식_지도가_없으면_검사_불능(proj):
    (proj / "templates" / "forms" / "Backlog.yaml").unlink()
    result = _status(proj)
    assert result["status"] == "cannot_check" and "양식 지도" in result["message"]


def test_산출_규칙에_걸려_다시_만들지_못하면_검사_불능이다_위반도_통과도_아니다(proj):
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("| ID | Title |", "| ID | 없는열 |"), encoding="utf-8")  # 양식 밖 열은 산출이 거절한다
    assert _status(proj)["status"] == "cannot_check"


def test_임시_파일을_남기지_않고_저장소_안에_아무것도_만들지_않는다(proj, tmp_path):
    import tempfile

    before = sorted(p.name for p in Path(tempfile.gettempdir()).glob("srs-export-check-*"))
    tracked = sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*") if p.is_file())
    _status(proj)
    assert sorted(p.name for p in Path(tempfile.gettempdir()).glob("srs-export-check-*")) == before
    assert sorted(p.relative_to(proj).as_posix() for p in proj.rglob("*") if p.is_file()) == tracked


def test_산출은_바뀌는_값을_넣지_않아_두_번_만들면_칸_값이_같다(proj, tmp_path):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    for out in (a, b):
        code, _ = export.run(proj / SRS_PATH, proj, "Backlog", False, out)
        assert code == 0
    assert sec._cells(a, sec._scope(proj, {"name": "Backlog"})) == sec._cells(b, sec._scope(proj, {"name": "Backlog"}))
    sec.xlsx_reader.clear_cache()


# --- CLI -------------------------------------------------------------------

def test_cli_종료코드는_same_0_differ_1_검사불능_2(proj, capsys):
    assert sec.main(["compare", "--root", str(proj)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "same"
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("결재", "결재2"), encoding="utf-8")
    assert sec.main(["compare", "--root", str(proj)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "differ"
    (proj / XLSX).unlink()
    assert sec.main(["compare", "--root", str(proj)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "cannot_check"


def test_cli_예상_못_한_오류도_검사_불능이다(proj, capsys, monkeypatch):
    monkeypatch.setattr(sec, "compare", lambda root: (_ for _ in ()).throw(RuntimeError("boom")))
    assert sec.main(["compare", "--root", str(proj)]) == 2
    assert "boom" in json.loads(capsys.readouterr().out)["message"]


# --- push-check(병합 뒤) ---------------------------------------------------

def test_push_엑셀을_추가하지_않았으면_돌리지_않는다(proj, tmp_path, monkeypatch, capsys):
    added = tmp_path / "added.txt"
    added.write_text("docs/ssot/SRS.md\ndocs/other.md\n", encoding="utf-8")
    monkeypatch.setattr(sec, "compare", lambda root: pytest.fail("내용 PR 병합 push 에서는 비교하지 않는다"))
    assert sec.main(["push-check", "--added-file", str(added), "--root", str(proj)]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "not_applicable"}


def test_push_엑셀을_추가했고_낡았으면_1(proj, tmp_path, capsys):
    added = tmp_path / "added.txt"
    added.write_text(XLSX + "\n", encoding="utf-8")
    assert sec.main(["push-check", "--added-file", str(added), "--root", str(proj)]) == 0
    capsys.readouterr()
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("결재", "결재2"), encoding="utf-8")
    assert sec.main(["push-check", "--added-file", str(added), "--root", str(proj)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "differ"


def test_push_추가_목록을_못_읽으면_검사_불능(proj, tmp_path, capsys):
    assert sec.main(["push-check", "--added-file", str(tmp_path / "없음.txt"), "--root", str(proj)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "cannot_check"


# --- merge-guard(병합 직전 훅이 부른다) -------------------------------------

class FakeGh:
    """GhClient 대신. files 는 PR 파일 목록, srs 는 {ref: 본문}, fail 은 실패시킬 호출 이름."""

    def __init__(self, files, srs, base="main", head="abc123", fail=None):
        self.files, self.srs, self.base, self.head, self.fail = files, srs, base, head, fail

    def get_json(self, path):
        if self.fail == "pr":
            raise GhError("gh api pulls 실패")
        return {"base": {"ref": self.base}, "head": {"sha": self.head}}

    def get_all(self, path):
        if self.fail == "files":
            raise GhError("gh api files 실패")
        return self.files

    def run(self, args):
        if self.fail == "content":
            raise GhError("gh api contents 실패")
        ref = args[1].split("ref=")[1]
        return self.srs[ref]


def _guard(proj, **kw):
    return sec.merge_guard("o/r", 7, proj, FakeGh(**kw))


ADDED = [{"filename": XLSX, "status": "added"}, {"filename": SRS_PATH, "status": "modified"}]


def test_가드_산출_PR_이_아니면_통과(proj):
    r = _guard(proj, files=[{"filename": SRS_PATH, "status": "modified"}], srs={})
    assert r["status"] == "pass" and r["reason"] == "not_applicable"


def test_가드_산출_PR_이고_base_의_SRS_가_같으면_통과_버전_줄은_무시(proj):
    base = te.SRS_MD.replace("버전: 0.2", "버전: 0.1")
    r = _guard(proj, files=ADDED, srs={"abc123": te.SRS_MD, "main": base})
    assert r["status"] == "pass"


def test_가드_엑셀을_만든_뒤_base_의_SRS_내용이_바뀌었으면_stale(proj):
    changed = te.SRS_MD.replace("첫 줄", "다른 PR 이 고친 줄")
    r = _guard(proj, files=ADDED, srs={"abc123": te.SRS_MD, "main": changed})
    assert r["status"] == "stale" and "main" in r["reason"] and "다시 산출" in r["next"]


def test_가드_줄바꿈만_다르면_같은_것으로_본다(proj):
    r = _guard(proj, files=ADDED, srs={"abc123": te.SRS_MD, "main": te.SRS_MD.replace("\n", "\r\n")})
    assert r["status"] == "pass"


@pytest.mark.parametrize("fail", ["pr", "files", "content"])
def test_가드_gh_가_실패하면_검사_불능이다(proj, fail):
    r = _guard(proj, files=ADDED, srs={"abc123": te.SRS_MD, "main": te.SRS_MD}, fail=fail)
    assert r["status"] == "cannot_check"


def test_가드_양식_지도를_못_읽으면_검사_불능(proj):
    (proj / "templates" / "forms" / "Backlog.yaml").write_text("시트: [깨짐\n", encoding="utf-8")
    r = _guard(proj, files=ADDED, srs={})
    assert r["status"] == "cannot_check"


def test_가드_이름을_바꾼_엑셀도_추가로_센다(proj):
    r = _guard(proj, files=[{"filename": XLSX, "status": "renamed"}], srs={"abc123": te.SRS_MD, "main": te.SRS_MD.replace("첫 줄", "x")})
    assert r["status"] == "stale"


def test_가드_cli_종료코드(proj, monkeypatch, capsys):
    monkeypatch.setattr(sec, "merge_guard", lambda repo, pr, root, client=None: {"status": "stale", "reason": "r"})
    assert sec.main(["merge-guard", "--repo", "o/r", "--pr", "7", "--root", str(proj)]) == 1
    monkeypatch.setattr(sec, "merge_guard", lambda repo, pr, root, client=None: {"status": "cannot_check", "message": "m"})
    assert sec.main(["merge-guard", "--repo", "o/r", "--pr", "7", "--root", str(proj)]) == 2
    monkeypatch.setattr(sec, "merge_guard", lambda repo, pr, root, client=None: {"status": "pass"})
    assert sec.main(["merge-guard", "--repo", "o/r", "--pr", "7", "--root", str(proj)]) == 0


# --- PR 검사 연결(check_changed) -------------------------------------------

def _pr(proj: Path, monkeypatch, capsys, added: list[str]):
    (proj / "rules").mkdir(exist_ok=True)
    (proj / "rules" / "메모.yaml").write_text('관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: ".*"\n', encoding="utf-8")
    changed = [SRS_PATH, XLSX]
    (proj / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
    diff = (
        f"diff --git a/{SRS_PATH} b/{SRS_PATH}\nindex 1..2 100644\n--- a/{SRS_PATH}\n+++ b/{SRS_PATH}\n@@ -3 +3 @@\n-버전: 0.1\n+버전: 0.2\n"
    )
    (proj / "diff.txt").write_text(diff, encoding="utf-8")
    (proj / "added.txt").write_text("\n".join(added) + "\n", encoding="utf-8")
    monkeypatch.chdir(proj)
    monkeypatch.delenv("DOC_GUARD_OPEN_PRS", raising=False)
    monkeypatch.setenv("DOC_GUARD_DIFF_FILE", "diff.txt")
    monkeypatch.setenv("DOC_GUARD_ADDED_FILES", "added.txt")
    code = main_entry(["changed.txt"])
    sec.xlsx_reader.clear_cache()
    out = capsys.readouterr().out
    return code, json.loads(out[out.index("{"):])


def test_PR_검사_엑셀이_SRS_와_같으면_통과(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, [XLSX])
    assert code == 0 and report["srs_split"]["status"] == "pass"


def test_PR_검사_엑셀이_병합_뒤_SRS_와_다르면_위반_stale_xlsx(proj, monkeypatch, capsys):
    (proj / SRS_PATH).write_text(te.SRS_MD.replace("결재", "결재2"), encoding="utf-8")  # 병합 결과 체크아웃에 main 의 새 내용이 들어 있다
    code, report = _pr(proj, monkeypatch, capsys, [XLSX])
    assert code == 1 and report["srs_split"]["status"] == "violation"
    assert [v["rule"] for v in report["srs_split"]["violations"]] == ["stale_xlsx"]
    text = render(report, code)
    assert "stale_xlsx" not in text and "백로그 뽑아 줘" in text and "SRS 내용과 같아야" in text


def test_PR_검사_엑셀을_다시_만들지_못하면_검사_불능이다(proj, monkeypatch, capsys):
    (proj / XLSX).unlink()
    code, report = _pr(proj, monkeypatch, capsys, [XLSX])
    assert code == 2 and report["srs_split"]["status"] == "cannot_check"
    assert "확인하지 못했습니다" in report["srs_split"]["message"]


def test_PR_검사_엑셀을_추가하지_않은_PR_은_비교하지_않는다(proj, monkeypatch, capsys):
    monkeypatch.setattr(sec, "compare", lambda root: pytest.fail("추가하지 않았으면 비교하지 않는다"))
    code, report = _pr(proj, monkeypatch, capsys, [])
    assert "srs_split" in report  # 분리 검사(bump)는 그대로 돈다
    assert report["srs_split"]["status"] == "violation"  # 엑셀이 추가되지 않은 bump 위반 — 비교는 하지 않았다


def test_PR_검사_스위치로_분리_검사를_끄면_비교도_안_한다(proj, monkeypatch, capsys):
    (proj / "rules" / "cross-checks").mkdir(parents=True)
    (proj / "rules" / "cross-checks" / "switches.yaml").write_text("SRS_분리: false\n", encoding="utf-8")
    monkeypatch.setattr(sec, "compare", lambda root: pytest.fail("스위치가 꺼져 있으면 비교하지 않는다"))
    code, report = _pr(proj, monkeypatch, capsys, [XLSX])
    assert report["srs_split"]["status"] == "disabled"
