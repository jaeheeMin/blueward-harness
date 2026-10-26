"""열린 PR 끼리 plugin.json version 겹침 검사(#324, 경고에서 실패로 #470)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import check_plugin_version_overlap as script  # noqa: E402
import fetch_open_prs  # noqa: E402
from fetch_open_prs import FetchError  # noqa: E402

import checker.plugin_version_overlap as overlap  # noqa: E402
from checker.pairing import CANNOT_CHECK, PASS, VIOLATION  # noqa: E402
from checker.plugin_version import PLUGIN_JSON  # noqa: E402
from checker.plugin_version_overlap import NOT_NEEDED, check_plugin_version_overlap, next_patch  # noqa: E402


def _info(mine="0.10.83", main="0.10.82", *prs):
    return {"status": "ok", "main_version": main, "my_version": mine, "prs": list(prs)}


def _p(number, version, title="제목"):
    return {"number": number, "title": title, "version": version}


def _bad(number, title="포크"):
    return {"number": number, "title": title, "version": None, "error": "404"}


# --- 판정 -------------------------------------------------------------------

def test_같은_version_을_쓰는_PR_이_있으면_위반이다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.83", "다른 작업")), 12)
    assert r["status"] == VIOLATION and r["warnings"] == []
    (v,) = r["violations"]
    assert v["version"] == "0.10.83" and [p["number"] for p in v["prs"]] == [10]
    assert v["message"] == (
        "이 PR 의 version 0.10.83 을 열린 PR #10(`다른 작업`) 이 이미 씁니다. 이 PR 의 version 을 0.10.84 로 올려 다시 푸시하세요"
        "(먼저 병합되는 쪽만 v0.10.83 태그를 받아 배포됩니다)."
    )


def test_올릴_다음_값은_열린_PR_의_version_도_넘는다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.83"), _p(11, "0.10.86")), 12)
    assert r["status"] == VIOLATION and r["violations"][0]["next"] == "0.10.87"
    assert "0.10.87 로 올려" in r["violations"][0]["message"]


def test_다른_PR_이_version_을_안_바꿨으면_무시한다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.82")), 12)
    assert r["status"] == PASS and r["warnings"] == []


def test_겹침이_없으면_경고가_없다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.84"), _p(11, "0.10.81")), 12)
    assert r["status"] == PASS and r["warnings"] == [] and r["compared"] == 2 and r["unchecked"] == []
    assert "겹침 없음" in script.render(r)


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
    assert "`@someone 확인`" in r["violations"][0]["message"]


def test_다음_patch():
    assert next_patch("0.10.83") == "0.10.84" and next_patch("0.10.9") == "0.10.10"
    assert next_patch("0.10.x") is None and next_patch("") is None


def test_version_은_정수_튜플로_비교한다():
    # 앞의 0 은 같은 값이다(문자열 비교였다면 겹침을 놓친다).
    r = check_plugin_version_overlap(_info("0.10.17", "0.10.9", _p(10, "0.10.017")), 12)
    assert r["status"] == VIOLATION


def test_이_PR_의_version_이_형식_밖이면_검사_불능이다():
    r = check_plugin_version_overlap(_info("0.10.x", "0.10.82", _p(10, "0.10.x")), 12)
    assert r["status"] == CANNOT_CHECK


def test_다음_patch_를_못_구하면_문구를_대체한다(monkeypatch):
    monkeypatch.setattr(overlap, "next_patch", lambda v: None)
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _p(10, "0.10.83")), 12)
    msg = r["violations"][0]["message"]
    assert "한 칸 더 올려" in msg and "None" not in msg


def test_다른_PR_한_건을_못_읽으면_그_PR_만_빼고_비교한다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _bad(11), _p(10, "0.10.83")), 12)
    assert r["status"] == VIOLATION and len(r["violations"]) == 1
    assert r["compared"] == 1 and [u["number"] for u in r["unchecked"]] == [11]


def test_읽지_못한_PR_뿐이면_겹침_없음이라고_하지_않는다():
    r = check_plugin_version_overlap(_info("0.10.83", "0.10.82", _bad(11)), 12)
    assert r["status"] == PASS and r["warnings"] == [] and r["unchecked"]
    text = script.render(r)
    assert "겹침 없음" not in text and "확인 못 함" in text
    assert "1건 중 1건(#11)" in script.unchecked_message(r)


# --- 읽기(가짜 API) ---------------------------------------------------------

def _plugin(version):
    return json.dumps({"name": "harness", "version": version})


class FakeApi:
    def __init__(self, pulls, texts, fail=None):
        self.pulls, self.texts, self.fail = pulls, texts, fail
        self.calls = []

    def get_json(self, path):
        self.calls.append(path)
        if self.fail:
            raise FetchError(self.fail)
        return self.pulls

    def get_text(self, ref_path, ref):
        self.calls.append(ref)
        if self.fail:
            raise FetchError(self.fail)
        assert ref_path == PLUGIN_JSON
        return self.texts.get(ref)


def _pull(n, base="main", title="t", draft=False):
    return {"number": n, "title": title, "draft": draft, "head": {"sha": f"h{n}abcdef"}, "base": {"ref": base}}


def _collect(api, mine="0.10.83", main="0.10.82", **kw):
    return script.collect(api.get_json, api.get_text, "o/r", 12, "main", main, mine, **kw)


def test_읽기는_같은_base_의_다른_PR_version_을_모은다_초안도_포함한다():
    api = FakeApi(
        pulls=[_pull(10, draft=True), _pull(11), _pull(12), _pull(13, base="other")],
        texts={"h10abcdef": _plugin("0.10.83"), "h11abcdef": _plugin("0.10.82"), "h13abcdef": _plugin("0.10.83")},
    )
    info = _collect(api)
    assert info["status"] == "ok" and info["main_version"] == "0.10.82"
    assert {p["number"]: p["version"] for p in info["prs"]} == {10: "0.10.83", 11: "0.10.82"}  # 13(다른 base)·12(자기) 제외
    assert "h13abcdef" not in api.calls and "h12abcdef" not in api.calls
    assert check_plugin_version_overlap(info, 12)["status"] == VIOLATION


def test_이_PR_이_version_을_안_올렸으면_네트워크를_쓰지_않는다():
    api = FakeApi(pulls=[_pull(10)], texts={})
    assert _collect(api, mine="0.10.82") == {"status": NOT_NEEDED}
    assert api.calls == []


def test_목록을_못_읽으면_검사_불능이다():
    api = FakeApi(pulls=[], texts={}, fail="GitHub API 503")
    info = _collect(api)
    assert info["status"] == CANNOT_CHECK and "503" in info["message"]
    assert check_plugin_version_overlap(info, 12)["status"] == CANNOT_CHECK


def test_다른_PR_head_를_못_읽으면_그_PR_만_오류로_남긴다():
    api = FakeApi(pulls=[_pull(10), _pull(11)], texts={"h11abcdef": _plugin("0.10.83")})  # h10 은 404
    info = _collect(api)
    assert info["status"] == "ok"
    by = {p["number"]: p for p in info["prs"]}
    assert by[10]["version"] is None and "#10" in by[10]["error"] and by[11]["version"] == "0.10.83"
    r = check_plugin_version_overlap(info, 12)
    assert r["status"] == VIOLATION and len(r["violations"]) == 1 and [u["number"] for u in r["unchecked"]] == [10]


def test_깨진_plugin_json_도_그_PR_만_오류다():
    api = FakeApi(pulls=[_pull(10)], texts={"h10abcdef": "{깨짐"})
    info = _collect(api)
    assert info["status"] == "ok" and info["prs"][0]["version"] is None and info["prs"][0]["error"]


def test_시간_예산을_넘으면_검사_불능이다():
    api = FakeApi(pulls=[_pull(10)], texts={"h10abcdef": _plugin("0.10.83")})
    ticks = iter([0.0, 999.0, 999.0])
    info = _collect(api, budget=1.0, clock=lambda: next(ticks))
    assert info["status"] == CANNOT_CHECK and "시간 예산" in info["message"]


# --- 재시도·레이트 리밋 -----------------------------------------------------

class _Resp:
    def __init__(self, body=b"[]"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _http_error(code, headers=None):
    import email.message
    import urllib.error

    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("http://x", code, "reason", msg, None)


def _client(outcomes, sleeps):
    seq = iter(outcomes)

    def opener(req, timeout):
        o = next(seq)
        if isinstance(o, BaseException):
            raise o
        return o

    return fetch_open_prs._http("t", "http://api", opener=opener, sleep=sleeps.append)[0]


def test_5xx_와_네트워크_오류는_재시도한다():
    import urllib.error

    sleeps = []
    get_json = _client([_http_error(503), urllib.error.URLError("끊김"), _Resp(b"[1]")], sleeps)
    assert get_json("/x") == [1] and len(sleeps) == 2


def test_재시도를_다_써도_실패면_FetchError다():
    sleeps = []
    get_json = _client([_http_error(502)] * 3, sleeps)
    with pytest.raises(FetchError, match="502"):
        get_json("/x")
    assert len(sleeps) == 2


def test_권한_오류는_재시도하지_않는다():
    sleeps = []
    with pytest.raises(FetchError, match="pull-requests 읽기 권한"):
        _client([_http_error(403)], sleeps)("/x")
    assert sleeps == []


def test_레이트_리밋은_권한_문제와_다른_안내를_낸다():
    with pytest.raises(FetchError) as e:
        _client([_http_error(403, {"X-RateLimit-Remaining": "0"})], [])("/x")
    assert "호출 한도" in str(e.value) and "권한" not in str(e.value)


# --- 진입점·워크플로 --------------------------------------------------------

def _env(monkeypatch, tmp_path, token=True, mine="0.10.83", main="0.10.82"):
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    if token:
        monkeypatch.setenv("GITHUB_TOKEN", "t")
    else:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(script, "git_version", lambda rev: main)
    monkeypatch.setattr(script.Path, "read_text", lambda self, encoding=None: _plugin(mine))
    return summary


def _fake_collect(monkeypatch, result):
    monkeypatch.setattr(script, "_http", lambda token, url: (None, None))
    monkeypatch.setattr(script, "collect", lambda *a, **k: result)


def test_version_을_안_올렸으면_네트워크도_토큰도_없이_끝나고_요약을_쓰지_않는다(monkeypatch, capsys, tmp_path):
    summary = _env(monkeypatch, tmp_path, token=False, mine="0.10.82")

    def boom(*a, **k):
        raise AssertionError("네트워크를 쓰면 안 된다")

    monkeypatch.setattr(script, "_http", boom)
    assert script.main(["12", "sha", "main"]) == 0
    assert "확인하지 않는다" in capsys.readouterr().out
    assert not summary.exists()


def test_토큰이_없으면_종료코드_2다(monkeypatch, capsys, tmp_path):
    _env(monkeypatch, tmp_path, token=False)
    assert script.main(["12", "sha", "main"]) == 2
    assert "검사 불능" in capsys.readouterr().err


def test_읽기_실패는_종료코드_2이고_다시_돌리라고_안내한다(monkeypatch, capsys, tmp_path):
    _env(monkeypatch, tmp_path)
    _fake_collect(monkeypatch, {"status": CANNOT_CHECK, "message": "GitHub API 503"})
    assert script.main(["12", "sha", "main"]) == 2
    err = capsys.readouterr().err
    assert "503" in err and "다시 돌리십시오" in err


def test_base_version_을_git_에서_못_읽으면_검사_불능이다(monkeypatch, capsys, tmp_path):
    _env(monkeypatch, tmp_path)

    def fail(rev):
        raise FetchError("git show 실패")

    monkeypatch.setattr(script, "git_version", fail)
    assert script.main(["12", "sha", "main"]) == 2


def test_겹침은_종료코드_1이고_error_주석과_요약에_보인다_제목의_특수문자는_이스케이프된다(monkeypatch, capsys, tmp_path):
    summary = _env(monkeypatch, tmp_path)
    _fake_collect(monkeypatch, _info("0.10.83", "0.10.82", _p(10, "0.10.83", "100% %0A :: 끝")))
    assert script.main(["12", "sha", "main"]) == 1
    out = capsys.readouterr().out
    assert "::warning" not in out
    ann = next(line for line in out.splitlines() if line.startswith("::error title=plugin version 겹침::"))
    assert "100%25 %250A ::" in ann  # 제목의 % 는 %25 로, 리터럴 %0A 는 %250A 로
    assert "\n" not in ann
    assert "#10" in open(summary, encoding="utf-8").read()


def test_겹침이_없으면_종료코드_0이다(monkeypatch, capsys, tmp_path):
    _env(monkeypatch, tmp_path)
    _fake_collect(monkeypatch, _info("0.10.83", "0.10.82", _p(10, "0.10.84")))
    assert script.main(["12", "sha", "main"]) == 0
    out = capsys.readouterr().out
    assert "겹침 없음" in out and "::error" not in out and "::warning" not in out


def test_일부_PR_을_못_읽으면_경고와_요약에_남기고_종료코드_0이다(monkeypatch, capsys, tmp_path):
    summary = _env(monkeypatch, tmp_path)
    _fake_collect(monkeypatch, _info("0.10.83", "0.10.82", _bad(11), _p(10, "0.10.84")))
    assert script.main(["12", "sha", "main"]) == 0
    out = capsys.readouterr().out
    assert "::warning title=plugin version 겹침 일부 확인 못 함::" in out and "겹침 없음" not in out
    assert "2건 중 1건(#11)" in out
    assert "확인하지 못했습니다" in open(summary, encoding="utf-8").read()


def test_escape_annotation():
    assert script.escape_annotation("a%b\r\nc") == "a%25b%0D%0Ac"


def test_checker_워크플로는_PR_에서_ubuntu_에서만_겹침을_확인한다():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "checker.yml").read_text(encoding="utf-8"))
    step = next(s for s in wf["jobs"]["test"]["steps"] if "plugin version 겹침" in s.get("name", ""))
    assert "pull_request" in step["if"] and "ubuntu" in step["if"]
    assert "check_plugin_version_overlap.py" in step["run"] and step["env"]["GITHUB_TOKEN"]
    assert "pull_request.base.sha" in step["run"] and "pull_request.base.ref" in step["run"]
    assert wf["permissions"]["pull-requests"] == "read"
    assert "workflow_call" not in str(wf.get("on") or wf.get(True))  # 재사용 워크플로가 아니다 = 고객사 PR 에 닿지 않는다
