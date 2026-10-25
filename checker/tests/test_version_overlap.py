"""열린 PR 끼리 문서 판 번호 겹침 경고(#315)를 단언한다. 네트워크는 쓰지 않는다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_changed import main_entry  # noqa: E402
from fetch_open_prs import FetchError, collect, paged  # noqa: E402
from render_report import render  # noqa: E402

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS  # noqa: E402
from checker.pairing import CANNOT_CHECK, PASS  # noqa: E402
from checker.version_overlap import (  # noqa: E402
    artifact_version, check_version_overlap, next_version, srs_version_of,
)

BACKLOG = "docs/srs/BW_Backlog List_v0.3.xlsx"


def _pr(number, title="제목", added=(), srs=None, base="0.2", srs_error=None):
    return {
        "number": number, "title": title, "added": list(added),
        "srs_changed": srs is not None or srs_error is not None,
        "srs_version": srs, "srs_base_version": base, "srs_error": srs_error,
    }


def _ok(*prs):
    return {"status": "ok", "prs": list(prs)}


# --- 판정 ------------------------------------------------------------------

def test_겹침이_없으면_경고가_없다():
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG], srs="0.3"), _pr(200, added=["docs/srs/x_v0.4.xlsx"], srs="0.4")), 205)
    assert r["status"] == PASS and r["warnings"] == [] and r["compared"] == 1


def test_산출_파일만_겹치면_파일_경고다():
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG]), _pr(200, "기간별 재고 수불부", added=[BACKLOG])), 205)
    assert r["status"] == PASS
    (w,) = r["warnings"]
    assert (w["kind"], w["version"], w["file"]) == ("file", "0.3", BACKLOG)
    assert w["prs"] == [{"number": 200, "title": "기간별 재고 수불부"}]
    assert "이 판 번호(v0.3)를 열린 PR #200(`기간별 재고 수불부`) 도 씁니다" in w["message"]
    assert "먼저 병합되는 쪽이 v0.3 을 갖고" in w["message"] and "sync 뒤 0.4 로 다시 산출" in w["message"]


def test_SRS_버전만_겹치면_SRS_경고다():
    r = check_version_overlap(_ok(_pr(205, srs="0.3"), _pr(200, srs="0.3")), 205)
    (w,) = r["warnings"]
    assert (w["kind"], w["version"]) == ("srs", "0.3")
    assert "#200" in w["message"]


def test_둘_다_겹치면_경고_둘이다():
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG], srs="0.3"), _pr(200, added=[BACKLOG], srs="0.3")), 205)
    assert {w["kind"] for w in r["warnings"]} == {"file", "srs"}


def test_SRS_값이_달라도_산출_파일이_다르면_겹침이_아니다():
    r = check_version_overlap(_ok(_pr(205, srs="0.3"), _pr(200, srs="0.4")), 205)
    assert r["warnings"] == []


def test_SRS를_고쳤어도_버전이_그대로면_겹침이_아니다():
    # 둘 다 SRS 본문만 고쳐 버전이 base(0.2) 그대로다
    r = check_version_overlap(_ok(_pr(205, srs="0.2"), _pr(200, srs="0.2")), 205)
    assert r["warnings"] == []


def test_다른_PR이_여럿이면_모두_적는다():
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG]), _pr(200, "가", added=[BACKLOG]), _pr(210, "나", added=[BACKLOG])), 205)
    (w,) = r["warnings"]
    assert [p["number"] for p in w["prs"]] == [200, 210]
    assert "#200(`가`), #210(`나`)" in w["message"]


def test_자기_PR은_비교에서_뺀다():
    # 목록에 나만 있다
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG], srs="0.3")), 205)
    assert r["warnings"] == [] and r["compared"] == 0


def test_다른_PR이_기존_파일을_고친_것은_추가가_아니라_겹침이_아니다():
    # fetch 가 modified 를 added 에 싣지 않으므로 다른 PR 의 added 는 비어 있다
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG]), _pr(200, added=[])), 205)
    assert r["warnings"] == []


def test_목록을_못_읽으면_검사_불능이다():
    r = check_version_overlap({"status": "cannot_check", "message": "열린 PR 목록을 읽지 못했습니다: 403"}, 205)
    assert r["status"] == CANNOT_CHECK and "403" in r["message"]


def test_이_PR이_목록에_없으면_검사_불능이다():
    assert check_version_overlap(_ok(_pr(200)), 205)["status"] == CANNOT_CHECK


def test_모르는_모양이면_검사_불능이다():
    assert check_version_overlap({"status": "이상함"}, 205)["status"] == CANNOT_CHECK
    assert check_version_overlap({"status": "ok", "prs": "x"}, 205)["status"] == CANNOT_CHECK


def test_다른_PR의_SRS_버전을_못_읽으면_검사_불능이다():
    r = check_version_overlap(_ok(_pr(205, srs="0.3"), _pr(200, srs_error="GitHub API 500")), 205)
    assert r["status"] == CANNOT_CHECK and "#200" in r["message"]


def test_이_PR이_SRS를_안_올렸으면_다른_PR의_SRS_읽기_실패는_상관없다():
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG]), _pr(200, srs_error="GitHub API 500")), 205)
    assert r["status"] == PASS


def test_이_PR의_SRS를_못_읽으면_검사_불능이다():
    assert check_version_overlap(_ok(_pr(205, srs_error="404"), _pr(200)), 205)["status"] == CANNOT_CHECK


@pytest.mark.parametrize("path,version", [
    ("docs/srs/BW_Backlog List_v0.3.xlsx", "0.3"),
    ("docs/개발사양서/판매_개발사양서_v1.10.xlsx", "1.10"),
    ("docs/인터페이스/IF_v0.1.docx", "0.1"),
    ("docs/x_v2.pptx", "2"),
    ("docs/ssot/SRS.md", None),
    ("docs/x_v0.3.md", None),
    ("templates/BW_Backlog List_v0.1.xlsx", None),
    ("docs/srs/x.xlsx", None),
])
def test_산출_파일_판_번호_읽기(path, version):
    assert artifact_version(path) == version


@pytest.mark.parametrize("text,version", [
    ("# SRS\n\n버전: 0.3\n", "0.3"),
    ("# SRS\n\n- 버전: v1.3\n", "1.3"),
    ("# SRS\n\n**버전**: 0.4\n", "0.4"),
    ("# SRS\n\n본문\n", None),
])
def test_SRS_버전_줄_읽기(text, version):
    assert srs_version_of(text) == version


def test_다음_판():
    assert next_version("0.3") == "0.4" and next_version("1.9") == "1.10"


# --- 열린 PR 읽기(가짜 API) --------------------------------------------------

def _file(name, status="added"):
    return {"filename": name, "status": status}


class FakeApi:
    """경로 -> 응답. 파일 내용은 (경로, ref) -> 문자열."""

    def __init__(self, files, pulls, texts, fail=None):
        self.files, self.pulls, self.texts, self.fail = files, pulls, texts, fail
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        if self.fail:
            raise FetchError(self.fail)
        base = path.split("?")[0]
        if base.endswith("/pulls"):
            return self.pulls
        if base.endswith("/files"):
            return self.files[int(base.split("/")[-2])]
        return next(p for p in self.pulls if base.endswith(f"/pulls/{p['number']}"))

    def get_text(self, path, ref):
        if self.fail:
            raise FetchError(self.fail)
        return self.texts.get(ref)


def _pull(n, title="t", base_ref="main", draft=False):
    return {"number": n, "title": title, "draft": draft, "head": {"sha": f"h{n}"}, "base": {"sha": f"b{n}", "ref": base_ref}}


def test_읽기는_추가한_산출_파일과_SRS_버전을_모은다():
    api = FakeApi(
        files={
            205: [_file(BACKLOG), _file("docs/ssot/SRS.md", "modified")],
            200: [_file(BACKLOG), _file("docs/ssot/SRS.md", "modified"), _file("docs/srs/old_v0.1.xlsx", "modified")],
        },
        pulls=[_pull(200, "기간별 재고 수불부"), _pull(205)],
        texts={"h205": "버전: 0.3\n", "b205": "버전: 0.2\n", "h200": "버전: 0.3\n", "b200": "버전: 0.2\n"},
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    assert data["status"] == "ok"
    by = {p["number"]: p for p in data["prs"]}
    assert by[200]["added"] == [BACKLOG] and by[200]["srs_version"] == "0.3" and by[200]["srs_base_version"] == "0.2"
    assert len(data["prs"]) == 2  # 자기 자신은 한 번만
    assert check_version_overlap(data, 205)["warnings"]


def test_기존_산출_파일을_고치기만_했으면_추가로_보지_않는다():
    api = FakeApi(
        files={205: [_file("docs/srs/old_v0.1.xlsx", "modified")], 200: []},
        pulls=[_pull(200), _pull(205)],
        texts={},
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    assert data == {"status": "not_needed"}
    assert not any(c.startswith("/repos/o/r/pulls?") for c in api.calls)  # 다른 PR 을 읽지 않았다


def test_이름이_바뀐_산출_파일은_추가로_본다():
    api = FakeApi(files={205: [_file(BACKLOG, "renamed")], 200: []}, pulls=[_pull(200), _pull(205)], texts={})
    assert collect(api.get_json, api.get_text, "o/r", 205)["status"] == "ok"


def test_API가_실패하면_검사_불능으로_남긴다():
    api = FakeApi(files={}, pulls=[], texts={}, fail="GitHub API 403 Forbidden (토큰에 pull-requests 읽기 권한이 없을 수 있습니다)")
    data = collect(api.get_json, api.get_text, "o/r", 205)
    assert data["status"] == "cannot_check" and "403" in data["message"]


def test_SRS_내용을_못_읽으면_그_PR_에_오류를_남긴다():
    class Flaky(FakeApi):
        def get_text(self, path, ref):
            if ref == "h200":
                raise FetchError("GitHub API 500")
            return super().get_text(path, ref)

    api = Flaky(
        files={205: [_file(BACKLOG)], 200: [_file("docs/ssot/SRS.md", "modified")]},
        pulls=[_pull(200), _pull(205)],
        texts={"h205": "버전: 0.3\n", "b205": "버전: 0.2\n"},
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    by = {p["number"]: p for p in data["prs"]}
    assert by[200]["srs_error"] and by[200]["srs_version"] is None


_SRS_SELF = {205: [_file(BACKLOG), _file("docs/ssot/SRS.md", "modified")]}


def test_다른_PR_의_head_SRS가_404면_그_PR_에_오류를_남긴다():
    api = FakeApi(
        files={**_SRS_SELF, 200: [_file("docs/ssot/SRS.md", "modified")]},
        pulls=[_pull(200), _pull(205)],
        texts={"h205": "버전: 0.3\n", "b205": "버전: 0.2\n", "b200": "버전: 0.2\n"},  # h200 은 get_text -> None
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    by = {p["number"]: p for p in data["prs"]}
    assert by[200]["srs_error"] and "head" in by[200]["srs_error"]
    result = check_version_overlap(data, 205)
    assert result["status"] == CANNOT_CHECK and result["read_failure"]  # 조용히 비교에서 빠지지 않는다


def test_이_PR_의_head_SRS가_404면_판을_안_건드린_것으로_보지_않고_검사_불능이다():
    api = FakeApi(files={205: [_file("docs/ssot/SRS.md", "modified")]}, pulls=[_pull(205)], texts={"b205": "버전: 0.2\n"})
    data = collect(api.get_json, api.get_text, "o/r", 205)
    assert data["status"] == "ok"  # not_needed 가 아니다
    assert data["prs"][0]["srs_error"]
    assert check_version_overlap(data, 205)["status"] == CANNOT_CHECK


def test_바뀐_SRS에_버전_줄이_없으면_검사_불능이다():
    api = FakeApi(
        files={**_SRS_SELF, 200: [_file("docs/ssot/SRS.md", "modified")]},
        pulls=[_pull(200), _pull(205)],
        texts={"h205": "버전: 0.3\n", "b205": "버전: 0.2\n", "h200": "# SRS\n본문만\n", "b200": "버전: 0.2\n"},
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    by = {p["number"]: p for p in data["prs"]}
    assert "버전:" in by[200]["srs_error"]
    assert check_version_overlap(data, 205)["status"] == CANNOT_CHECK


def test_base에_SRS가_아직_없으면_정상이다():
    api = FakeApi(
        files={**_SRS_SELF, 200: []},
        pulls=[_pull(200), _pull(205)],
        texts={"h205": "버전: 0.1\n"},  # b205 없음 -> None
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    mine = next(p for p in data["prs"] if p["number"] == 205)
    assert mine["srs_error"] is None and mine["srs_version"] == "0.1" and mine["srs_base_version"] is None


def test_base_브랜치가_다른_PR은_비교에서_빼고_초안은_넣는다():
    api = FakeApi(
        files={205: [_file(BACKLOG)], 200: [_file(BACKLOG)], 201: [_file(BACKLOG)], 202: [_file(BACKLOG)]},
        pulls=[_pull(200, base_ref="release"), _pull(201, draft=True), _pull(202), _pull(205)],
        texts={},
    )
    data = collect(api.get_json, api.get_text, "o/r", 205)
    assert sorted(p["number"] for p in data["prs"]) == [201, 202, 205]
    assert not any("/pulls/200/" in c for c in api.calls)  # 뺀 PR 은 파일 목록도 부르지 않는다


def test_시간_예산을_넘으면_검사_불능이다():
    api = FakeApi(files={205: [_file(BACKLOG)], 200: [_file(BACKLOG)]}, pulls=[_pull(200), _pull(205)], texts={})
    ticks = iter([0.0, 500.0, 500.0, 500.0])
    data = collect(api.get_json, api.get_text, "o/r", 205, budget=120, clock=lambda: next(ticks))
    assert data["status"] == "cannot_check" and "시간 예산" in data["message"]


def test_쪽수_상한을_넘으면_검사_불능이다():
    with pytest.raises(FetchError):
        paged(lambda path: [{}] * 100, "/x")


# --- 제목 이스케이프 ---------------------------------------------------------

def test_다른_PR_제목의_멘션과_마크다운은_코드_조각으로_감싼다():
    title = "@octocat 확인 `x` [링크](http://e) | 표\n둘째 줄 " + "가" * 80
    r = check_version_overlap(_ok(_pr(205, added=[BACKLOG]), _pr(200, title, added=[BACKLOG])), 205)
    msg = r["warnings"][0]["message"]
    assert "(`@octocat 확인 'x' [링크](http://e) | 표 둘째 줄" in msg  # 백틱으로 감싸 멘션·링크가 동작하지 않는다
    assert "\n" not in msg and "…`)" in msg  # 한 줄, 60자로 잘림


# --- check_changed 통합 -----------------------------------------------------

def _run(tmp, monkeypatch, capsys, open_prs, changed="docs/srs/BW_Backlog List_v0.3.xlsx\n", env=True, number="205",
         pattern=".*"):
    (tmp / "templates").mkdir(exist_ok=True)
    (tmp / "rules").mkdir(exist_ok=True)
    (tmp / "rules" / "메모.yaml").write_text(
        f'관할: "memo/**"\n규칙:\n  - 종류: filename\n    패턴: "{pattern}"\n', encoding="utf-8"
    )
    (tmp / "docs" / "srs").mkdir(parents=True, exist_ok=True)
    (tmp / BACKLOG).write_bytes(b"x")
    names = [n for n in changed.splitlines() if n]
    for n in names:
        (tmp / n).parent.mkdir(parents=True, exist_ok=True)
        if not (tmp / n).exists():
            (tmp / n).write_text("버전: 0.3\n", encoding="utf-8")
    (tmp / "changed.txt").write_text(changed, encoding="utf-8")
    if open_prs is not None:
        (tmp / "open-prs.json").write_text(json.dumps(open_prs, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp)
    if env:
        monkeypatch.setenv("DOC_GUARD_OPEN_PRS", "open-prs.json")
        monkeypatch.setenv("DOC_GUARD_PR_NUMBER", number)
    else:
        monkeypatch.delenv("DOC_GUARD_OPEN_PRS", raising=False)
        monkeypatch.delenv("DOC_GUARD_PR_NUMBER", raising=False)
    code = main_entry(["changed.txt"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip().startswith("{") else None


def _switch(tmp: Path, text: str) -> None:
    path = tmp / "rules" / "cross-checks" / "switches.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_겹치면_리포트에_합쳐지고_통과다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, _ok(_pr(205, added=[BACKLOG]), _pr(200, "수불부", added=[BACKLOG])))
    assert code == EXIT_PASS
    assert len(report["version_overlap"]["warnings"]) == 1
    text = render(report, code)
    assert "## 판 번호 겹침" in text and "#200(`수불부`)" in text and "sync 뒤 0.4" in text


def test_겹침이_없으면_없다고_쓴다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, _ok(_pr(205, added=[BACKLOG]), _pr(200)))
    assert code == EXIT_PASS and report["version_overlap"]["warnings"] == []
    assert "판 번호가 겹치는 곳이 없습니다" in render(report, code)


def test_열린_PR을_못_읽으면_종료코드_2다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, {"status": "cannot_check", "message": "열린 PR 목록을 읽지 못했습니다: 403"})
    assert code == EXIT_CONFIG_ERROR
    assert report["version_overlap"]["status"] == CANNOT_CHECK
    text = render(report, code)
    assert "## 판 번호 겹침" in text and "검사 불능" in text and "403" in text


def test_열린_PR_정보_파일이_없으면_검사_불능이다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, None)
    assert code == EXIT_CONFIG_ERROR and report["version_overlap"]["status"] == CANNOT_CHECK


def test_열린_PR_정보가_깨졌으면_검사_불능이다(tmp_path, monkeypatch, capsys):
    (tmp_path / "open-prs.json").write_text("{깨짐", encoding="utf-8")
    code, report = _run(tmp_path, monkeypatch, capsys, None)
    assert code == EXIT_CONFIG_ERROR and report["version_overlap"]["status"] == CANNOT_CHECK


def test_이_PR이_판을_안_건드려_읽지_않았으면_키가_없다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, {"status": "not_needed"})
    assert code == EXIT_PASS
    assert report is None or "version_overlap" not in report


def test_환경변수가_없으면_돌리지_않는다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, _ok(_pr(205, added=[BACKLOG]), _pr(200, added=[BACKLOG])), env=False)
    assert code == EXIT_PASS
    assert report is None or "version_overlap" not in report


def test_판_번호와_상관없는_파일만_바뀌면_돌리지_않는다(tmp_path, monkeypatch, capsys):
    code, report = _run(tmp_path, monkeypatch, capsys, {"status": "cannot_check", "message": "x"}, changed="README.md\n")
    assert code == EXIT_PASS
    assert report is None or "version_overlap" not in report


def test_SRS가_바뀌면_돈다(tmp_path, monkeypatch, capsys):
    code, report = _run(
        tmp_path, monkeypatch, capsys, _ok(_pr(205, srs="0.3"), _pr(200, srs="0.3")), changed="docs/ssot/SRS.md\n"
    )
    assert code == EXIT_PASS and report["version_overlap"]["warnings"][0]["kind"] == "srs"


def test_스위치를_끄면_돌리지_않고_꺼짐을_표시한다(tmp_path, monkeypatch, capsys):
    _switch(tmp_path, "판_겹침: false\n")
    code, report = _run(tmp_path, monkeypatch, capsys, {"status": "cannot_check", "message": "x"})
    assert code == EXIT_PASS and report["version_overlap"] == {"status": "disabled"}
    text = render(report, code)
    assert "판 번호 겹침: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음" in text


def test_다른_스위치만_꺼도_판_겹침은_돈다(tmp_path, monkeypatch, capsys):
    _switch(tmp_path, "객체_겹침: false\n")
    _, report = _run(tmp_path, monkeypatch, capsys, _ok(_pr(205, added=[BACKLOG]), _pr(200, added=[BACKLOG])))
    assert report["version_overlap"]["warnings"]


def test_잘못된_스위치면_검사_불능이다(tmp_path, monkeypatch, capsys):
    _switch(tmp_path, "판_겹침: 아니오\n")
    code, report = _run(tmp_path, monkeypatch, capsys, _ok(_pr(205, added=[BACKLOG]), _pr(200)))
    assert code == EXIT_CONFIG_ERROR and report["cross_checks"]["status"] == CANNOT_CHECK


# --- 워크플로 ---------------------------------------------------------------

def test_재사용_워크플로가_PR에서_열린_PR을_읽어_검사에_넘긴다():
    import yaml

    # #420 부터 doc-guard 는 pr-checks.yml 의 한 단계다(옛 doc-guard.yml 은 #452 에서 지웠다).
    wf = yaml.safe_load((Path(__file__).resolve().parents[2] / ".github" / "workflows" / "pr-checks.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["check"]["steps"] if s.get("id") == "doc-guard")
    run = step["run"]
    assert "fetch_open_prs.py" in run and "DOC_GUARD_OPEN_PRS=open-prs.json" in run
    assert run.index("fetch_open_prs.py") < run.index("check_changed.py")
    assert step["env"]["GITHUB_TOKEN"] and step["env"]["DOC_GUARD_PR_NUMBER"]
    assert "--exit2-cause" in run and "retry" in run


# --- 문서 위반과 읽기 실패가 함께 --------------------------------------------

def test_문서_위반과_읽기_실패가_함께면_종료코드_2이고_위반_표도_보인다(tmp_path, monkeypatch, capsys):
    from render_report import exit2_cause

    code, report = _run(
        tmp_path, monkeypatch, capsys,
        {"status": "cannot_check", "message": "GitHub API 503"},
        changed="docs/srs/BW_Backlog List_v0.3.xlsx\nmemo/bad.md\n", pattern="^ok_.*",
    )
    assert code == EXIT_CONFIG_ERROR
    assert report["summary"]["violations"] == 1
    assert report["version_overlap"]["read_failure"] is True
    text = render(report, code)
    assert "템플릿 위반" in text and "memo/bad.md" in text  # 위반 표 그대로
    assert "다시 돌려 보십시오" in text and "규칙·설정을 고쳐야" not in text
    assert exit2_cause(report) == "retry"


def test_읽기_실패_말고_다른_검사_불능이_섞이면_설정_문제로_본다():
    from render_report import exit2_cause

    base = {"summary": {"violations": 0}, "version_overlap": {"status": "cannot_check", "read_failure": True}}
    assert exit2_cause(base) == "retry"
    assert exit2_cause({**base, "cross_checks": {"status": "cannot_check"}}) == "config"
    assert exit2_cause({**base, "pairing": {"status": "cannot_check"}}) == "config"
    assert exit2_cause({**base, "code_rules": {"report": {}, "exit": 2}}) == "config"
    assert exit2_cause({"message": "x"}) == "config"
    assert exit2_cause({"summary": {}, "version_overlap": {"status": "cannot_check"}}) == "config"
