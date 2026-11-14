"""SRS 고치기·주기 분리 PR 검사(`checker/srs_split.py`, #974)를 검증한다.

판정 규칙(mixed·bump·orphan_xlsx)과 검사 불능, check_changed 통합(리포트 키·종료코드·스위치·환경변수 없음), 워크플로가 두 환경변수를
항상 넘기는지를 본다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from checker.cross_switches import KEYS
from checker.pairing import CANNOT_CHECK, PASS, SRS_PATH, VIOLATION
from checker.srs_split import NOT_APPLICABLE, check_srs_split, evaluate, srs_changes
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_changed import main_entry  # noqa: E402
from render_report import exit2_cause, render  # noqa: E402

BACKLOG_MAP = """\
양식: Backlog
템플릿: ../Backlog.xlsx
산출:
  폴더: docs/srs
  파일명: "BW_Backlog List_v{버전}.xlsx"
  자리:
    버전: {메타: 버전}
시트:
  - 이름: Backlog
    표:
      - 이름: Backlog
        원본: SRS
        머리글_행: 3
        시작_행: 4
        번호_열: Backlog ID
        열:
          Backlog ID: A
"""


def xlsx(ver: str) -> str:
    return f"docs/srs/BW_Backlog List_v{ver}.xlsx"


def srs_diff(old: str | None, new: str | None, other: list[str] | None = None, created: bool = False) -> str:
    """`git diff -U0 --no-renames` 모양의 SRS.md 구역."""
    lines = [f"diff --git a/{SRS_PATH} b/{SRS_PATH}"]
    if created:
        lines += ["new file mode 100644", "index 0000000..1111111", "--- /dev/null", f"+++ b/{SRS_PATH}", "@@ -0,0 +1,3 @@"]
    else:
        lines += ["index 1111111..2222222 100644", f"--- a/{SRS_PATH}", f"+++ b/{SRS_PATH}", "@@ -3 +3 @@"]
    if old is not None:
        lines.append(f"-버전: {old}")
    if new is not None:
        lines.append(f"+버전: {new}")
    for text in other or []:
        lines += [f"-{text}", f"+{text} 고침"]
    return "\n".join(lines) + "\n"


def other_diff(other: list[str]) -> str:
    return srs_diff(None, None, other)


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    (tmp_path / "templates" / "forms").mkdir(parents=True)
    (tmp_path / "templates" / "forms" / "Backlog.yaml").write_text(BACKLOG_MAP, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _엑셀_비교는_따로_본다(monkeypatch):
    """check_changed 통합 시험의 엑셀은 진짜 xlsx 가 아니다. 산출 엑셀 비교(#976)는 test_srs_export_check.py 가 따로 본다."""
    from checker import srs_export_check

    monkeypatch.setattr(srs_export_check, "compare", lambda root: {"status": "same", "forms": []})


def rules(result: dict) -> list[str]:
    return [v["rule"] for v in result["violations"]]


# --- diff 읽기 ---------------------------------------------------------------

def test_diff에서_SRS_구역만_읽고_버전_줄과_나머지를_가른다():
    other_file = "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-x\n+y\n"
    got = srs_changes(other_file + srs_diff("0.2", "0.3", ["본문 한 줄"]))
    assert got == {"created": False, "deleted": False, "old": "0.2", "new": "0.3", "version_lines": 2, "other_lines": 2}


def test_SRS가_diff에_없으면_None이다():
    assert srs_changes("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-x\n+y\n") is None


def test_공백뿐인_줄은_내용_변경으로_세지_않는다():
    diff = srs_diff("0.2", "0.3") + "+\n-\n"
    assert srs_changes(diff)["other_lines"] == 0


def test_굵게_표시나_목록_기호가_붙은_버전_줄도_버전_줄로_본다():
    diff = srs_diff(None, None) + "-- **버전**: 0.2\n+- **버전**: 0.3\n"
    got = srs_changes(diff)
    assert got["old"] == "0.2" and got["new"] == "0.3" and got["other_lines"] == 0


# --- 판정: 통과 --------------------------------------------------------------

def test_내용만_바꾼_PR은_버전도_엑셀도_없이_통과한다(proj):
    r = check_srs_split(other_diff(["REQ-003 줄"]), [], proj, srs_listed=True)
    assert r == {"status": PASS, "violations": []}


def test_산출_PR은_버전_올림과_그_판_엑셀이_짝이면_통과한다(proj):
    r = check_srs_split(srs_diff("0.3", "0.4"), [xlsx("0.4")], proj, srs_listed=True)
    assert r["status"] == PASS


def test_만들기_PR은_첫_판_버전_줄과_내용이_함께_있어도_통과한다(proj):
    r = check_srs_split(srs_diff(None, "0.1", ["요구사항"], created=True), [SRS_PATH], proj, srs_listed=True)
    assert r["status"] == PASS


def test_SRS도_엑셀도_안_건드리면_대상이_아니다(proj):
    assert check_srs_split("diff --git a/README.md b/README.md\n", ["README.md"], proj)["status"] == NOT_APPLICABLE


def test_Backlog가_아닌_xlsx를_추가해도_대상이_아니다(proj):
    assert check_srs_split("", ["docs/spec/개발사양서_v0.1.xlsx"], proj)["status"] == NOT_APPLICABLE


# --- 판정: 위반 --------------------------------------------------------------

def test_버전과_내용을_함께_바꾸면_거절한다(proj):
    r = check_srs_split(srs_diff("0.3", "0.4", ["REQ-003 줄"]), [xlsx("0.4")], proj, srs_listed=True)
    assert r["status"] == VIOLATION and rules(r) == ["mixed"]
    v = r["violations"][0]
    assert "버전:" in v["reason"] and "백로그 뽑아 줘" in v["fix"] and "/harness:update" in v["fix"]


def test_버전이_main_보다_0_1이_아니면_거절한다(proj):
    r = check_srs_split(srs_diff("0.3", "0.5"), [xlsx("0.5")], proj, srs_listed=True)
    assert r["status"] == VIOLATION and rules(r) == ["bump"]
    assert "0.4" in r["violations"][0]["reason"]


def test_버전을_내리거나_그대로_두는_것도_거절한다(proj):
    assert rules(check_srs_split(srs_diff("0.3", "0.2"), [xlsx("0.2")], proj, srs_listed=True)) == ["bump"]


def test_0_9_다음은_0_10이다(proj):
    assert check_srs_split(srs_diff("0.9", "0.10"), [xlsx("0.10")], proj, srs_listed=True)["status"] == PASS


def test_버전을_올렸는데_그_판_엑셀이_없으면_거절한다(proj):
    r = check_srs_split(srs_diff("0.3", "0.4"), [], proj, srs_listed=True)
    assert r["status"] == VIOLATION and rules(r) == ["bump"]
    assert xlsx("0.4") in r["violations"][0]["reason"]


def test_다른_판_엑셀만_있으면_둘_다_거절한다(proj):
    r = check_srs_split(srs_diff("0.3", "0.4"), [xlsx("0.5")], proj, srs_listed=True)
    assert r["status"] == VIOLATION and sorted(rules(r)) == ["bump", "orphan_xlsx"]


def test_엑셀만_추가하고_버전을_안_바꾸면_거절한다(proj):
    r = check_srs_split(other_diff(["본문"]), [xlsx("0.4")], proj, srs_listed=True)
    assert r["status"] == VIOLATION and rules(r) == ["orphan_xlsx"]


def test_SRS를_안_건드리고_엑셀만_추가해도_거절한다(proj):
    r = check_srs_split("diff --git a/x b/x\n", [xlsx("0.4")], proj)
    assert r["status"] == VIOLATION and rules(r) == ["orphan_xlsx"]


# --- 판정: 검사 불능 ---------------------------------------------------------

def test_기준에_버전_줄이_없었는데_버전이_바뀌면_검사_불능이다(proj):
    r = check_srs_split(srs_diff(None, "0.2"), [xlsx("0.2")], proj, srs_listed=True)
    assert r["status"] == CANNOT_CHECK and "기준(main)에 `버전:` 줄이 없어" in r["message"]


def test_버전_줄이_지워졌으면_검사_불능이다(proj):
    assert check_srs_split(srs_diff("0.3", None), [], proj, srs_listed=True)["status"] == CANNOT_CHECK


def test_목록에는_SRS가_있는데_diff에_없으면_검사_불능이다(proj):
    r = check_srs_split("", [], proj, srs_listed=True)
    assert r["status"] == CANNOT_CHECK and "diff" in r["message"]


def test_양식_지도가_깨졌으면_검사_불능이다(proj):
    (proj / "templates" / "forms" / "깨짐.yaml").write_text("시트: [", encoding="utf-8")
    assert check_srs_split(srs_diff("0.3", "0.4"), [xlsx("0.4")], proj, srs_listed=True)["status"] == CANNOT_CHECK


def test_파일명_자리를_알_수_없으면_검사_불능이다(proj):
    (proj / "templates" / "forms" / "Backlog.yaml").write_text(
        BACKLOG_MAP.replace('v{버전}', 'v{버전}_{고객}'), encoding="utf-8")
    r = check_srs_split(srs_diff("0.3", "0.4"), [xlsx("0.4")], proj, srs_listed=True)
    assert r["status"] == CANNOT_CHECK and "고객" in r["message"]


def test_SRS_원본_지도가_없는_저장소는_엑셀_짝을_따지지_않고_버전만_본다(tmp_path):
    assert check_srs_split(srs_diff("0.3", "0.4"), [], tmp_path, srs_listed=True)["status"] == PASS
    assert rules(check_srs_split(srs_diff("0.3", "0.5"), [], tmp_path, srs_listed=True)) == ["bump"]


# --- 파일 읽기 ---------------------------------------------------------------

def test_diff나_추가_목록을_읽지_못하면_검사_불능이다(proj):
    (proj / "added.txt").write_text("", encoding="utf-8")
    r = evaluate(str(proj / "없는diff.txt"), str(proj / "added.txt"), proj, [SRS_PATH])
    assert r["status"] == CANNOT_CHECK and "diff" in r["message"]
    (proj / "diff.txt").write_text(other_diff(["x"]), encoding="utf-8")
    r = evaluate(str(proj / "diff.txt"), str(proj / "없는added.txt"), proj, [SRS_PATH])
    assert r["status"] == CANNOT_CHECK and "추가된 파일 목록" in r["message"]


def test_환경변수가_없거나_대상_파일이_없으면_읽지_않는다(proj):
    assert evaluate(None, None, proj, [SRS_PATH]) is None
    assert evaluate("없음", "없음", proj, ["README.md"]) is None


# --- check_changed 통합 ------------------------------------------------------

def _pr(tmp: Path, monkeypatch, capsys, diff: str | None, added: list[str], changed: list[str], env: bool = True):
    (tmp / "rules").mkdir(exist_ok=True)
    (tmp / "rules" / "메모.yaml").write_text('관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: ".*"\n', encoding="utf-8")
    for n in changed:
        (tmp / n).parent.mkdir(parents=True, exist_ok=True)
        if not (tmp / n).exists():
            (tmp / n).write_text("버전: 0.4\n", encoding="utf-8")
    (tmp / "changed.txt").write_text("\n".join(changed) + "\n", encoding="utf-8")
    if diff is not None:
        (tmp / "diff.txt").write_text(diff, encoding="utf-8")
    (tmp / "added.txt").write_text("\n".join(added) + ("\n" if added else ""), encoding="utf-8")
    monkeypatch.chdir(tmp)
    monkeypatch.delenv("DOC_GUARD_OPEN_PRS", raising=False)
    if env:
        monkeypatch.setenv("DOC_GUARD_DIFF_FILE", "diff.txt")
        monkeypatch.setenv("DOC_GUARD_ADDED_FILES", "added.txt")
    else:
        monkeypatch.delenv("DOC_GUARD_DIFF_FILE", raising=False)
        monkeypatch.delenv("DOC_GUARD_ADDED_FILES", raising=False)
    code = main_entry(["changed.txt"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip().startswith("{") else None


def test_통합_짝이_맞는_산출_PR은_통과하고_리포트에_srs_split이_실린다(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, srs_diff("0.3", "0.4"), [xlsx("0.4")], [SRS_PATH, xlsx("0.4")])
    assert code == 0 and report["srs_split"]["status"] == PASS
    assert "약속대로 나뉘어" in render(report, code)


def test_통합_섞인_PR은_종료코드_1이고_코멘트에_고칠_방법이_나온다(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, srs_diff("0.3", "0.4", ["본문"]), [xlsx("0.4")], [SRS_PATH, xlsx("0.4")])
    assert code == 1 and report["srs_split"]["status"] == VIOLATION
    text = render(report, code)
    assert "## SRS 고치기·주기 분리" in text and "백로그 뽑아 줘" in text and "/harness:update" in text


def test_통합_diff를_못_읽으면_종료코드_2다(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, None, [], [SRS_PATH])
    assert code == 2 and report["srs_split"]["status"] == CANNOT_CHECK
    assert exit2_cause(report) == "config"
    assert "검사 불능" in render(report, code)


def test_통합_환경변수가_없으면_돌리지_않는다(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, srs_diff("0.3", "0.9"), [], [SRS_PATH], env=False)
    assert code == 0 and (report is None or "srs_split" not in report)


def test_통합_SRS도_엑셀도_없는_PR은_키가_없다(proj, monkeypatch, capsys):
    code, report = _pr(proj, monkeypatch, capsys, "", [], ["memo/a.md"])
    assert code == 0 and (report is None or "srs_split" not in report)


def _switch(tmp: Path, text: str) -> None:
    path = tmp / "rules" / "cross-checks" / "switches.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_통합_스위치를_끄면_돌리지_않고_꺼짐을_표시한다(proj, monkeypatch, capsys):
    _switch(proj, "SRS_분리: false\n")
    code, report = _pr(proj, monkeypatch, capsys, srs_diff("0.3", "0.9", ["본문"]), [], [SRS_PATH])
    assert code == 0 and report["srs_split"] == {"status": "disabled"}
    assert "SRS 고치기·주기 분리: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" in render(report, code)


def test_통합_다른_스위치만_꺼도_SRS_분리는_돈다(proj, monkeypatch, capsys):
    _switch(proj, "번호_짝: false\n")
    code, report = _pr(proj, monkeypatch, capsys, srs_diff("0.3", "0.4", ["본문"]), [xlsx("0.4")], [SRS_PATH, xlsx("0.4")])
    assert code == 1 and report["srs_split"]["status"] == VIOLATION


def test_스위치_키에_SRS_분리가_있고_스캐폴드_예시가_그_키를_담는다():
    assert "SRS_분리" in KEYS
    skeleton = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "rules" / "cross-checks" / "switches.yaml"
    assert "SRS_분리: true" in skeleton.read_text(encoding="utf-8")


# --- 워크플로 ----------------------------------------------------------------

def test_재사용_워크플로는_두_환경변수를_조건_없이_검사_앞에서_넘긴다():
    import yaml

    wf = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr-checks.yml").read_text(encoding="utf-8"))
    run = next(s for s in wf["jobs"]["check"]["steps"] if s.get("id") == "doc-guard")["run"]
    for env in ("export DOC_GUARD_ADDED_FILES=added.txt", "export DOC_GUARD_DIFF_FILE=diff.txt"):
        line = next(l for l in run.splitlines() if l.strip() == env)
        assert line == line.lstrip()  # if 안쪽(들여쓰기)이 아니라 단계 맨 바깥
        assert run.index(env) < run.index("check_changed.py")


# --- 판 겹침 경고와의 관계(#974 4) -------------------------------------------

def test_산출_PR_끼리만_판_겹침으로_경고되고_내용_PR_은_겹침_대상이_아니다():
    from checker.version_overlap import check_version_overlap

    def pr(number, added=(), version=None, base="0.3", changed=True):
        return {"number": number, "title": f"PR{number}", "added": list(added), "srs_changed": changed,
                "srs_version": version or base, "srs_base_version": base, "srs_error": None}

    exporting = pr(205, [xlsx("0.4")], "0.4")
    result = check_version_overlap({"status": "ok", "prs": [exporting, pr(200, [xlsx("0.4")], "0.4")]}, 205)
    assert {w["kind"] for w in result["warnings"]} == {"file", "srs"}
    content = pr(201)  # 내용 PR: SRS.md 는 바뀌었지만 버전도 엑셀도 그대로
    assert check_version_overlap({"status": "ok", "prs": [exporting, content]}, 205)["warnings"] == []
