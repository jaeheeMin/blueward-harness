"""열린 PR 끼리 plugin.json version 겹침 경고(#324)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_plugin_version_overlap as script  # noqa: E402
from fetch_open_prs import FetchError  # noqa: E402

from checker.pairing import CANNOT_CHECK, PASS  # noqa: E402
from checker.plugin_version import PLUGIN_JSON  # noqa: E402
from checker.plugin_version_overlap import NOT_NEEDED, check_plugin_version_overlap, next_patch  # noqa: E402


def _info(mine="0.10.83", main="0.10.82", *prs):
    return {"status": "ok", "main_version": main, "my_version": mine, "prs": list(prs)}


def _p(number, version, title="제목"):
    return {"number": number, "title": title, "version": version}


# --- 판정 -------------------------------------------------------------------

def test_같은_version_을_쓰는_PR_이_있으면_경고한다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.83", "다른 작업"), _p(11, "0.10.84")), 12)
    assert r["status"] == PASS
    (w,) = r["warnings"]
    assert w["version"] == "0.10.83" and [p["number"] for p in w["prs"]] == [10]
    assert "#10(`다른 작업`)" in w["message"]
    assert "v0.10.83 태그" in w["message"] and "0.10.84" in w["message"]


def test_다른_PR_이_version_을_안_바꿨으면_무시한다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.82")), 12)
    assert r["status"] == PASS and r["warnings"] == []


def test_겹침이_없으면_경고가_없다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.84"), _p(11, "0.10.81")), 12)
    assert r["status"] == PASS and r["warnings"] == [] and r["compared"] == 2


def test_자기_PR_은_제외한다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(12, "0.10.83")), 12)
    assert r["warnings"] == []


def test_이_PR_이_version_을_안_올렸으면_대상이_아니다():
    r = check_plugin_version_overlap(_info("0.10.82", "0.10.82", _p(10, "0.10.82")), 12)
    assert r["status"] == NOT_NEEDED and r["warnings"] == []


def test_읽기_실패는_검사_불능이다():
    r = check_plugin_version_overlap({"status": CANNOT_CHECK, "message": "GitHub API 503"}, 12)
    assert r["status"] == CANNOT_CHECK and r["read_failure"] and "503" in r["message"] and "다시 돌리십시오" in r["message"]


def test_모르는_모양이거나_version_이_없으면_검사_불능이다():
    assert check_plugin_version_overlap({"status": "ok"}, 12)["status"] == CANNOT_CHECK
    assert check_plugin_version_overlap({"status": "ok", "prs": [], "my_version": "0.1.1"}, 12)["status"] == CANNOT_CHECK


def test_제목의_멘션은_코드_조각으로_감싼다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.83", "@someone 확인")), 12)
    assert "`@someone 확인`" in r["warnings"][0]["message"]


def test_다음_patch():
    assert next_patch("0.10.83") == "0.10.84" and next_patch("0.10.9") == "0.10.10"


# --- 읽기(가짜 API) ---------------------------------------------------------

def _plugin(version):
    return json.dumps({"name": "harness", "version": version})


class FakeApi:
    def __init__(self, pulls, texts, me_base="main", fail=None):
        self.pulls, self.texts, self.me_base, self.fail = pulls, texts, me_base, fail
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        if self.fail:
            raise FetchError(self.fail)
        base = path.split("?")[0]
        if base.endswith("/pulls"):
            return self.pulls
        return {"number": 12, "base": {"ref": self.me_base}}

    def get_text(self, ref_path, ref):
        if self.fail:
            raise FetchError(self.fail)
        assert ref_path == PLUGIN_JSON
        return self.texts.get(ref)


def _pull(n, base="main", title="t"):
    return {"number": n, "title": title, "head": {"sha": f"h{n}abcdef"}, "base": {"ref": base}}


def test_읽기는_같은_base_의_다른_PR_version_을_모은다():
    api = FakeApi(
        pulls=[_pull(10), _pull(11), _pull(12), _pull(13, base="other")],
        texts={"main": _plugin("0.10.82"), "h10abcdef": _plugin("0.10.83"), "h11abcdef": _plugin("0.10.82"),
               "h13abcdef": _plugin("0.10.83")},
    )
    info = script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.83")
    assert info["status"] == "ok" and info["main_version"] == "0.10.82"
    assert {p["number"]: p["version"] for p in info["prs"]} == {10: "0.10.83", 11: "0.10.82"}
    assert check_plugin_version_overlap(info, 12)["warnings"]


def test_이_PR_이_version_을_안_올렸으면_열린_PR_을_읽지_않는다():
    api = FakeApi(pulls=[_pull(10)], texts={"main": _plugin("0.10.82")})
    info = script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.82")
    assert info == {"status": NOT_NEEDED}
    assert not any(c.split("?")[0].endswith("/pulls") for c in api.calls)


def test_API_가_실패하면_검사_불능이다():
    api = FakeApi(pulls=[], texts={}, fail="GitHub API 503")
    info = script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.83")
    assert info["status"] == CANNOT_CHECK and "503" in info["message"]
    assert check_plugin_version_overlap(info, 12)["status"] == CANNOT_CHECK


def test_다른_PR_head_의_plugin_json_을_못_읽으면_검사_불능이다():
    api = FakeApi(pulls=[_pull(10)], texts={"main": _plugin("0.10.82")})  # h10abcdef 없음 -> 404
    info = script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.83")
    assert info["status"] == CANNOT_CHECK and "#10" in info["message"]


def test_plugin_json_이_깨졌으면_검사_불능이다():
    api = FakeApi(pulls=[_pull(10)], texts={"main": _plugin("0.10.82"), "h10abcdef": "{깨짐"})
    assert script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.83")["status"] == CANNOT_CHECK


def test_시간_예산을_넘으면_검사_불능이다():
    api = FakeApi(pulls=[_pull(10)], texts={"main": _plugin("0.10.82"), "h10abcdef": _plugin("0.10.83")})
    ticks = iter([0.0, 999.0, 999.0])
    info = script.collect(api.get_json, api.get_text, "o/r", 12, "0.10.83", budget=1.0, clock=lambda: next(ticks))
    assert info["status"] == CANNOT_CHECK and "시간 예산" in info["message"]


# --- 진입점·워크플로 --------------------------------------------------------

def test_토큰이_없으면_종료코드_2다(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert script.main(["12"]) == 2
    assert "검사 불능" in capsys.readouterr().err


def test_겹침은_종료코드_0이고_주석과_요약에_보인다(monkeypatch, capsys, tmp_path):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(script, "_http", lambda token, url: (None, None))
    monkeypatch.setattr(script, "collect", lambda *a, **k: _info("0.10.83", "0.10.82", _p(10, "0.10.83", "다른 작업")))
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(script, "PLUGIN_JSON", PLUGIN_JSON)
    assert script.main(["12"]) == 0
    out = capsys.readouterr().out
    assert "::warning" in out and "#10" in out
    assert "#10" in summary.read_text(encoding="utf-8")


def test_checker_워크플로는_PR_에서_ubuntu_에서만_겹침을_확인한다():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "checker.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["test"]["steps"] if "plugin version 겹침" in s.get("name", ""))
    assert "pull_request" in step["if"] and "ubuntu" in step["if"]
    assert "check_plugin_version_overlap.py" in step["run"] and step["env"]["GITHUB_TOKEN"]
    assert wf["permissions"]["pull-requests"] == "read"
    assert "workflow_call" not in str(wf.get("on") or wf.get(True))  # 재사용 워크플로가 아니다 = 고객사 PR 에 닿지 않는다
