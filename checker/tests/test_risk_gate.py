"""`checker.risk_gate`(PR 위험도에 따른 승인 요구, #102)를 검증한다.

순수 함수(기준별 판정)는 `gh` 없이, `decide_*` 는 가짜 클라이언트로, CLI 는 종료코드로 본다.
비밀값 모양 문자열은 이 파일 자체가 비밀값 탐지에 걸리지 않게 조각을 이어 붙여 만든다.
"""
from __future__ import annotations

import base64
import json

import pytest

from checker import risk_gate as rg
from checker.ssot_approval import GhError

# --- 비밀값 시료(조각을 이어 붙여 만든다) ---------------------------------------

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GH_TOKEN = "ghp" + "_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
GH_PAT = "github" + "_pat_" + "11ABCDEFG0abcdefghijkl"
ANTHROPIC = "sk" + "-ant-" + "api03-abcdefghijklmnop"
SLACK = "xox" + "b-" + "1234567890-abcdefghij"
PRIVATE_KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
GENERIC = 'api_key = "' + "abcd1234efgh" + '"'
TEAMS = "https://prod-12.koreacentral." + "logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke?api-version=2016&sig=" + "Zx9_QrstUvw"
PP_URL = "https://abc.12.environment." + "api.powerplatform.com/powerautomate/automations/direct/workflows/x/triggers/manual/paths/invoke?api-version=1&sp=%2F&sig=" + "Abc123_-xyz"


def _file(name, additions=1, deletions=0, patch="@@ -0,0 +1 @@\n+x"):
    entry = {"filename": name, "additions": additions, "deletions": deletions}
    if patch is not None:
        entry["patch"] = patch
    return entry


def _patch(*added):
    body = "\n".join("+" + a for a in added)
    return f"@@ -1,1 +1,{len(added) + 1} @@\n keep\n{body}"


CFG = rg.load_config(None)


# --- 설정 ---------------------------------------------------------------------


def test_설정이_비어_있으면_기본값이다():
    assert rg.load_config("") == rg.DEFAULT_CONFIG
    assert rg.load_config("# 주석뿐\n") == rg.DEFAULT_CONFIG
    cfg = rg.load_config(None)
    assert cfg["max_changed_lines"] == 300 and cfg["max_changed_files"] == 10
    assert cfg["secret_scan"] is True and cfg["require_checks_green"] is True
    assert cfg["ai_review"] is False
    assert cfg["approvers_file"] == ".github/ssot-approvers"
    assert "docs/ssot/" in cfg["high_risk_paths"] and "CLAUDE.md" in cfg["high_risk_paths"]


def test_설정에_적은_값이_기본값을_덮는다_나머지는_기본값():
    cfg = rg.load_config("max_changed_lines: 50\nsecret_scan: false\nhigh_risk_paths:\n  - src/\n")
    assert cfg["max_changed_lines"] == 50
    assert cfg["secret_scan"] is False
    assert cfg["high_risk_paths"] == ["src/"]
    assert cfg["max_changed_files"] == 10


def test_기본값_목록을_바꿔도_다음_설정에_새지_않는다():
    cfg = rg.load_config(None)
    cfg["high_risk_paths"].append("zzz/")
    assert "zzz/" not in rg.load_config(None)["high_risk_paths"]


@pytest.mark.parametrize(
    "text",
    [
        "max_changed_lines: many\n",
        "max_changed_lines: -1\n",
        "secret_scan: 'yes'\n",
        "high_risk_paths: docs/\n",
        "secret_scna: false\n",  # 오타는 조용히 넘기지 않는다
        "- a\n- b\n",
        "a: [unclosed\n",
        "approvers_file: ''\n",
    ],
)
def test_잘못된_설정은_ConfigError(text):
    with pytest.raises(rg.ConfigError):
        rg.load_config(text)


# --- 크기 ---------------------------------------------------------------------


def test_크기_기준_이하면_사유가_없다():
    files = [_file("a", 150, 150)]
    assert rg.size_reasons(files, CFG) == []


def test_바뀐_줄이_기준을_넘으면_사유():
    reasons = rg.size_reasons([_file("a", 200, 101)], CFG)
    assert len(reasons) == 1 and "301줄" in reasons[0]


def test_바뀐_파일이_기준을_넘으면_사유():
    reasons = rg.size_reasons([_file(f"f{i}", 1, 0) for i in range(11)], CFG)
    assert len(reasons) == 1 and "11개" in reasons[0]


def test_줄과_파일이_모두_넘으면_사유가_둘():
    files = [_file(f"f{i}", 40, 0) for i in range(11)]
    assert len(rg.size_reasons(files, CFG)) == 2


# --- 위험 경로 ------------------------------------------------------------------


def test_위험_경로_아래를_바꾸면_사유():
    reasons = rg.path_reasons(["src/a.py", "docs/ssot/PRD.md"], ["docs/ssot/"])
    assert reasons == ["위험 경로를 바꿈: docs/ssot/PRD.md"]


def test_위험_경로가_아니면_사유가_없다():
    assert rg.path_reasons(["src/a.py", "README.md"], ["docs/ssot/", "CLAUDE.md"]) == []


def test_위험_경로는_역슬래시와_앞_슬래시를_정규화한다():
    assert rg.path_reasons(["\\.github\\workflows\\x.yml"], ["/.github/"])


def test_위험_경로_사유는_다섯_개까지만_나열한다():
    reasons = rg.path_reasons([f"rules/{i}.yaml" for i in range(8)], ["rules/"])
    assert "등 8개" in reasons[0]
    assert "rules/4.yaml" in reasons[0] and "rules/5.yaml" not in reasons[0]


# --- 비밀값 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, secret",
    [
        ("비공개 키 블록", PRIVATE_KEY),
        ("AWS 액세스 키 ID", AWS_KEY),
        ("GitHub 토큰", GH_TOKEN),
        ("GitHub 토큰", GH_PAT),
        ("Anthropic 키", ANTHROPIC),
        ("Slack 토큰", SLACK),
        ("비밀번호·토큰 대입", GENERIC),
        ("비밀번호·토큰 대입", 'PASSWORD: "hunter2hunter2"'),
        ("비밀번호·토큰 대입", "token='abcdefgh12345'"),
        ("Teams·Power Automate 웹훅 주소", TEAMS),
        ("Teams·Power Automate 웹훅 주소", PP_URL),
    ],
)
def test_비밀값_모양을_찾고_값은_사유에_담지_않는다(label, secret):
    reasons = rg.secret_reasons([("conf/a.txt", 7, f"x = {secret}  # note")])
    assert len(reasons) == 1
    assert label in reasons[0]
    assert "conf/a.txt:7" in reasons[0]
    # 값 자체(또는 그 일부)가 사유에 나오면 안 된다.
    for piece in (secret, secret[-8:], secret[10:20]):
        assert piece not in reasons[0]


@pytest.mark.parametrize(
    "line",
    [
        "password = get_password()",
        'token = ""',
        'api_key = "short"',  # 8자 미만
        "AKIA is a prefix",
        "ghp_ is mentioned in docs",
        "https://logic.azure.com/docs",  # sig 없는 일반 주소
        "see https://example.com/invoke?sig=abc",  # 웹훅 도메인이 아님
        "sk-learn is a library",
        "# BEGIN PRIVATE KEY 설명",
    ],
)
def test_비밀값이_아닌_줄은_걸리지_않는다(line):
    assert rg.secret_reasons([("a.md", 1, line)]) == []


def test_같은_패턴이_여러_곳이면_한_사유로_모으고_줄_번호를_나열한다():
    lines = [("a.py", 3, AWS_KEY), ("b.py", 9, AWS_KEY)]
    reasons = rg.secret_reasons(lines)
    assert len(reasons) == 1 and "a.py:3" in reasons[0] and "b.py:9" in reasons[0]


def test_added_lines_는_patch_에서_추가된_줄과_새_파일_줄번호를_뽑는다():
    patch = "@@ -10,3 +20,4 @@ def f():\n ctx\n-removed\n+added1\n+added2\n ctx2\n@@ -50 +60,2 @@\n+later\n\\ No newline at end of file"
    got = rg.added_lines([{"filename": "x.py", "patch": patch}])
    assert got == [("x.py", 21, "added1"), ("x.py", 22, "added2"), ("x.py", 60, "later")]


def test_patch_가_없는_파일은_건너뛴다():
    assert rg.added_lines([{"filename": "img.png"}]) == []


def test_patch_가_없는데_바뀐_줄이_있으면_검사_못_한_파일로_본다():
    files = [_file("big.sql", 900, 0, patch=None), _file("img.png", 0, 0, patch=None)]
    assert rg.unscanned_files(files) == ["big.sql"]


# --- 다른 검사 -------------------------------------------------------------------


def _run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_검사가_모두_통과면_사유가_없다():
    assert rg.checks_reasons([_run("test"), _run("lint", conclusion="skipped"), _run("x", conclusion="neutral")]) == ([], [])


def test_실패한_검사와_진행_중인_검사를_가른다():
    runs = [_run("test", conclusion="failure"), _run("doc-guard", status="in_progress", conclusion=None),
            _run("t2", conclusion="cancelled"), _run("t3", status="queued", conclusion=None)]
    failed, waiting = rg.checks_reasons(runs)
    assert "2개" in failed[0] and "test" in failed[0] and "t2" in failed[0]
    assert "2개" in waiting[0] and "doc-guard" in waiting[0] and "t3" in waiting[0]


def test_게이트_자신과_보조_검사는_세지_않는다():
    runs = [
        _run("risk-gate / check", status="in_progress", conclusion=None),
        _run("risk-gate", status="in_progress", conclusion=None),
        _run("ssot-approval / check", conclusion="failure"),
        _run("alert", conclusion="failure"),
    ]
    assert rg.checks_reasons(runs) == ([], [])


def test_이름이_비슷할_뿐인_검사는_세지_않는_것이_아니다():
    assert rg.checks_reasons([_run("risk-gate-docs", conclusion="failure")])[0]
    assert rg.checks_reasons([_run("alerting", conclusion="failure")])[0]


def test_ai_review_가_켜져_있으면_일반_검사에서_빼고_따로_읽는다():
    runs = [_run("ai-review", conclusion="failure")]
    assert rg.checks_reasons(runs, skip_ai_review=True) == ([], [])
    assert rg.checks_reasons(runs)[0]  # 꺼져 있으면 보통 검사다


def test_ai_review_성공_실패_대기_없음():
    assert rg.ai_review_reasons([_run("ai-review")]) == ([], [])
    flagged, waiting = rg.ai_review_reasons([_run("ai-review", conclusion="failure")])
    assert len(flagged) == 1 and "AI 리뷰 검사가 실패함" in flagged[0] and "검사 불능" in flagged[0] and waiting == []
    flagged, waiting = rg.ai_review_reasons([_run("ai-review", status="in_progress", conclusion=None)])
    assert flagged == [] and "끝나지 않음" in waiting[0]
    flagged, waiting = rg.ai_review_reasons([_run("test")])
    assert flagged == [] and "아직 없음" in waiting[0]


# --- decide_pr (가짜 클라이언트) ----------------------------------------------------


def _b64(text: str) -> dict:
    return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii")}


HEAD = "bbbbbbb1111"


class FakeClient:
    """경로 -> 응답 사전. 없는 `contents/` 경로는 404 처럼 None."""

    def __init__(self, responses):
        self.responses = responses
        self.asked: list[str] = []

    def _lookup(self, path):
        self.asked.append(path)
        if path in self.responses:
            value = self.responses[path]
            if isinstance(value, Exception):
                raise value
            return value
        for key, value in self.responses.items():
            if key.endswith("*") and path.startswith(key[:-1]):
                return value
        raise KeyError(path)

    def get_json(self, path):
        return self._lookup(path)

    def get_all(self, path, per_page=100):
        return self._lookup(path)

    def get_json_or_none_404(self, path):
        try:
            return self._lookup(path)
        except KeyError:
            if "/contents/" in path:
                return None
            raise


def _client(
    *,
    config="",
    files=None,
    check_runs=None,
    statuses=None,
    reviews=None,
    approvers="alice\n",
    human_paths=None,
    author="bob",
    base="main",
    head=HEAD,
):
    r = {
        "repos/o/r/pulls/5": {"user": {"login": author}, "base": {"ref": base}, "head": {"sha": head}},
        "repos/o/r/pulls/5/files": files if files is not None else [_file("src/a.py")],
        "repos/o/r/pulls/5/reviews": reviews or [],
        f"repos/o/r/commits/{head}/check-runs*": {"check_runs": check_runs or []},
        f"repos/o/r/commits/{head}/status*": {"statuses": statuses or []},
    }
    if config is not None:
        r[f"repos/o/r/contents/.github/risk-gate.yaml?ref={base}"] = _b64(config)
    if approvers is not None:
        r[f"repos/o/r/contents/.github/ssot-approvers?ref={base}"] = _b64(approvers)
    if human_paths is not None:
        r[f"repos/o/r/contents/.github/human-merge-paths?ref={base}"] = _b64(human_paths)
    return FakeClient(r)


def _review(login, state, commit, at="2026-01-01T00:00:00Z"):
    return {"user": {"login": login}, "state": state, "commit_id": commit, "submitted_at": at}


def test_설정_파일이_없으면_게이트가_꺼진_것이라_통과():
    client = _client(config=None, files=[_file("docs/ssot/PRD.md", 9999)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["enabled"] is False and result["risk"] == "low"
    assert result["reasons"] == ["risk-gate 설정 없음"]
    assert rg._exit_for(result) == 0
    # 설정은 base 브랜치에서 읽는다.
    assert any("risk-gate.yaml?ref=main" in p for p in client.asked)


def test_작고_안전하고_검사_통과면_승인_없이_통과():
    client = _client(check_runs=[_run("test")])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["enabled"] is True and result["risk"] == "low"
    assert result["reasons"] == [] and result["requires_approval"] is False
    assert result["approved"] is None and result["next"] == ""
    assert rg._exit_for(result) == 0


def test_크기가_크면_위험하고_승인이_없으면_1():
    client = _client(files=[_file("src/a.py", 500, 0)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "high" and result["requires_approval"] is True
    assert result["approved"] is False
    assert "500줄" in result["reasons"][0]
    assert result["next"].startswith("다음: 사람이 할 일 - 승인자(.github/ssot-approvers 의 사람, 작성자 제외)")
    assert "PR 을 나눠" in result["next"]
    assert rg._exit_for(result) == 1


def test_위험_경로를_바꾸면_위험():
    result = rg.decide_pr(_client(files=[_file("rules/ssot.yaml")]), "o/r", 5)
    assert result["risk"] == "high" and "rules/ssot.yaml" in result["reasons"][0]


def test_human_merge_paths_의_경로도_위험_경로다():
    client = _client(files=[_file("plugins/x.sh")], human_paths="plugins/\n")
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "high" and "plugins/x.sh" in result["reasons"][0]
    assert any("human-merge-paths?ref=main" in p for p in client.asked)


def test_비밀값이_추가되면_위험이고_다음_할_일은_지우고_폐기하는_것이다():
    client = _client(files=[_file("app/cfg.py", 1, 0, patch=_patch(f"KEY = '{AWS_KEY}'"))])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "high"
    assert "app/cfg.py:2" in result["reasons"][0] and "AWS" in result["reasons"][0]
    assert AWS_KEY not in json.dumps(result, ensure_ascii=False)
    assert "폐기" in result["next"] and result["next"].count("다음:") == 1


def test_secret_scan_을_끄면_비밀값을_보지_않는다():
    client = _client(config="secret_scan: false\n", files=[_file("a.py", 1, 0, patch=_patch(AWS_KEY))])
    assert rg.decide_pr(client, "o/r", 5)["risk"] == "low"


def test_다른_검사가_실패했으면_위험():
    result = rg.decide_pr(_client(check_runs=[_run("test", conclusion="failure")]), "o/r", 5)
    assert result["risk"] == "high" and "다른 검사가 실패함" in result["reasons"][0]
    assert result["waiting_on_checks"] is False


def test_commit_status_도_검사로_센다():
    result = rg.decide_pr(_client(statuses=[{"context": "ci/legacy", "state": "failure"}]), "o/r", 5)
    assert result["risk"] == "high" and "ci/legacy" in result["reasons"][0]


def test_진행_중인_검사만_있으면_위험이고_기다릴_수_있다고_표시한다():
    runs = [_run("doc-guard", status="in_progress", conclusion=None)]
    result = rg.decide_pr(_client(check_runs=runs), "o/r", 5)
    assert result["risk"] == "high" and result["waiting_on_checks"] is True
    assert "끝난 뒤" in result["next"]


def test_자기_자신과_보조_검사는_진행_중이어도_위험으로_세지_않는다():
    runs = [
        _run("risk-gate / check", status="in_progress", conclusion=None),
        _run("ssot-approval / check", status="in_progress", conclusion=None),
        _run("alert", status="queued", conclusion=None),
        _run("test"),
    ]
    assert rg.decide_pr(_client(check_runs=runs), "o/r", 5)["risk"] == "low"


def test_require_checks_green_을_끄면_검사_결과를_보지_않는다():
    client = _client(config="require_checks_green: false\n", check_runs=[_run("t", conclusion="failure")])
    assert rg.decide_pr(client, "o/r", 5)["risk"] == "low"
    assert not any("check-runs" in p for p in client.asked)


def test_위험해도_작성자가_아닌_승인자가_최신_커밋에_승인하면_통과():
    client = _client(files=[_file("rules/a.yaml")], reviews=[_review("alice", "APPROVED", HEAD)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "high" and result["approved"] is True
    assert result["next"] == "" and rg._exit_for(result) == 0


def test_옛_커밋에_한_승인은_낡아서_미승인이다():
    client = _client(files=[_file("rules/a.yaml")], reviews=[_review("alice", "APPROVED", "aaaaaaa0000")])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["approved"] is False and result["stale_approvers"] == ["alice"]
    assert "다시 Approve" in result["next"] and result["next"].count("다음:") == 1
    assert rg._exit_for(result) == 1


def test_승인자_목록에_없는_사람의_승인은_인정하지_않는다():
    client = _client(files=[_file("rules/a.yaml")], reviews=[_review("carol", "APPROVED", HEAD)])
    assert rg.decide_pr(client, "o/r", 5)["approved"] is False


def test_작성자_자신의_승인은_인정하지_않는다():
    client = _client(files=[_file("rules/a.yaml")], approvers="alice\nbob\n", author="bob",
                     reviews=[_review("bob", "APPROVED", HEAD)])
    assert rg.decide_pr(client, "o/r", 5)["approved"] is False


@pytest.mark.parametrize("approvers", [None, "", "# 주석뿐\n", "bob\n"])
def test_승인자_목록이_비었거나_작성자뿐이면_승인으로_풀_수_없다고_밝힌다(approvers):
    client = _client(files=[_file("rules/a.yaml")], approvers=approvers,
                     reviews=[_review("alice", "APPROVED", HEAD)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["approved"] is False
    assert "비어 있" in result["approval_note"]
    assert "승인자의 GitHub 아이디를 추가" in result["next"]
    assert rg._exit_for(result) == 1


def test_approvers_file_설정을_따른다():
    client = _client(config="approvers_file: .github/other\n", files=[_file("rules/a.yaml")], approvers=None,
                     reviews=[_review("dana", "APPROVED", HEAD)])
    client.responses["repos/o/r/contents/.github/other?ref=main"] = _b64("dana\n")
    assert rg.decide_pr(client, "o/r", 5)["approved"] is True


def test_ai_review_가_꺼져_있으면_ai_review_검사를_요구하지_않는다():
    assert rg.decide_pr(_client(), "o/r", 5)["risk"] == "low"


def test_ai_review_를_켜면_결과를_읽는다():
    cfg = "ai_review: true\n"
    ok = rg.decide_pr(_client(config=cfg, check_runs=[_run("ai-review")]), "o/r", 5)
    assert ok["risk"] == "low"
    bad = rg.decide_pr(_client(config=cfg, check_runs=[_run("ai-review", conclusion="failure")]), "o/r", 5)
    assert bad["risk"] == "high" and "AI 리뷰 검사가 실패함" in bad["reasons"][0]
    assert "ai-review 결과 코멘트" in bad["next"] and "검사 불능" in bad["next"]
    pending = rg.decide_pr(_client(config=cfg), "o/r", 5)
    assert pending["risk"] == "high" and pending["waiting_on_checks"] is True


def test_head_를_모르면_통과시키지_않고_판정_불가():
    client = _client()
    client.responses["repos/o/r/pulls/5"] = {"user": {"login": "bob"}, "base": {"ref": "main"}}
    with pytest.raises(GhError):
        rg.decide_pr(client, "o/r", 5)


def test_설정이_잘못되면_ConfigError_로_판정_불가():
    with pytest.raises(rg.ConfigError):
        rg.decide_pr(_client(config="max_changed_lines: x\n"), "o/r", 5)


def test_여러_사유를_번호를_붙여_하나의_다음_안내로_합친다():
    client = _client(files=[_file("rules/a.yaml", 1, 0, patch=_patch(AWS_KEY))],
                     check_runs=[_run("t", conclusion="failure")])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["next"].count("다음:") == 1
    assert "(1)" in result["next"] and "(2)" in result["next"]
    assert "폐기" in result["next"] and "실패한 검사" in result["next"] and "Approve" in result["next"]


# --- 기다리기 ---------------------------------------------------------------------


def test_진행_중_검사만_사유면_끝날_때까지_기다렸다가_다시_판정한다(monkeypatch):
    answers = iter([
        {"waiting_on_checks": True, "reasons": ["다른 검사가 아직 끝나지 않음(1개): x"]},
        {"waiting_on_checks": True, "reasons": ["다른 검사가 아직 끝나지 않음(1개): x"]},
        {"waiting_on_checks": False, "reasons": [], "risk": "low"},
    ])
    monkeypatch.setattr(rg, "decide_pr", lambda c, r, p: next(answers))
    ticks = {"t": 0.0, "slept": []}
    result = rg.decide_pr_waiting(
        None, "o/r", 5, wait_seconds=100, interval=10,
        sleep=lambda s: (ticks["slept"].append(s), ticks.__setitem__("t", ticks["t"] + s)),
        clock=lambda: ticks["t"],
    )
    assert result["risk"] == "low" and ticks["slept"] == [10, 10]


def test_기다리는_시간이_다하면_마지막_판정을_그대로_돌려준다(monkeypatch):
    monkeypatch.setattr(rg, "decide_pr", lambda c, r, p: {"waiting_on_checks": True, "reasons": ["x"]})
    ticks = {"t": 0.0}

    def _sleep(s):
        ticks["t"] += s

    result = rg.decide_pr_waiting(None, "o/r", 5, wait_seconds=25, interval=10, sleep=_sleep, clock=lambda: ticks["t"])
    assert result["waiting_on_checks"] is True and ticks["t"] == 20


def test_기다리라고_하지_않으면_바로_돌려준다(monkeypatch):
    monkeypatch.setattr(rg, "decide_pr", lambda c, r, p: {"waiting_on_checks": True, "reasons": ["x"]})
    slept = []
    rg.decide_pr_waiting(None, "o/r", 5, wait_seconds=0, sleep=slept.append)
    assert slept == []


# --- decide_commit ----------------------------------------------------------------


def _commit_client(*, prs, config="", files=None, parent="parent0", author="bob", approved=False):
    r = {
        "repos/o/r/commits/m1": {"parents": [{"sha": parent}], "author": {"login": author},
                                  "files": files if files is not None else [_file("src/a.py")]},
        "repos/o/r/commits/m1/pulls": prs,
        "repos/o/r/commits/m1/check-runs*": {"check_runs": []},
        "repos/o/r/commits/m1/status*": {"statuses": []},
        "repos/o/r/pulls/5": {"user": {"login": "bob"}, "base": {"ref": "main"}, "head": {"sha": HEAD}},
        "repos/o/r/pulls/5/files": files if files is not None else [_file("rules/a.yaml")],
        "repos/o/r/pulls/5/reviews": [_review("alice", "APPROVED", HEAD)] if approved else [],
        f"repos/o/r/commits/{HEAD}/check-runs*": {"check_runs": []},
        f"repos/o/r/commits/{HEAD}/status*": {"statuses": []},
        f"repos/o/r/contents/.github/ssot-approvers?ref={parent}": _b64("alice\n"),
    }
    if config is not None:
        r[f"repos/o/r/contents/.github/risk-gate.yaml?ref={parent}"] = _b64(config)
    return FakeClient(r)


def test_병합_뒤_감지는_병합_직전_main_에서_기준을_읽는다():
    client = _commit_client(prs=[{"number": 5, "merged_at": "2026-01-01", "html_url": "u"}])
    rg.decide_commit(client, "o/r", "m1")
    assert any("risk-gate.yaml?ref=parent0" in p for p in client.asked)
    assert not any("risk-gate.yaml?ref=main" in p for p in client.asked)


def test_승인_없이_병합된_위험한_PR_은_1_이다():
    client = _commit_client(prs=[{"number": 5, "merged_at": "2026-01-01", "html_url": "https://x/5"}])
    result = rg.decide_commit(client, "o/r", "m1")
    assert result["approved"] is False and result["risk"] == "high"
    assert result["prs"][0]["pr"] == 5 and "rules/a.yaml" in result["reasons"][0]
    assert rg._exit_for(result) == 1


def test_승인받고_병합된_위험한_PR_은_통과():
    client = _commit_client(prs=[{"number": 5, "merged_at": "2026-01-01"}], approved=True)
    result = rg.decide_commit(client, "o/r", "m1")
    assert result["approved"] is True and rg._exit_for(result) == 0


def test_게이트가_꺼져_있으면_병합_뒤에도_통과():
    client = _commit_client(prs=[{"number": 5, "merged_at": "2026-01-01"}], config=None)
    result = rg.decide_commit(client, "o/r", "m1")
    assert result["enabled"] is False and rg._exit_for(result) == 0


def test_PR_없이_main_에_직접_들어온_위험한_변경은_1():
    client = _commit_client(prs=[], files=[_file("docs/ssot/PRD.md")])
    result = rg.decide_commit(client, "o/r", "m1")
    assert result["approved"] is False and "PR 없이" in result["reasons"][0]
    assert rg._exit_for(result) == 1


def test_PR_없이_들어온_안전한_변경은_통과():
    client = _commit_client(prs=[], files=[_file("src/a.py")])
    assert rg._exit_for(rg.decide_commit(client, "o/r", "m1")) == 0


def test_PR_없이_들어온_커밋도_설정이_없으면_통과():
    client = _commit_client(prs=[], config=None, files=[_file("docs/ssot/PRD.md")])
    assert rg._exit_for(rg.decide_commit(client, "o/r", "m1")) == 0


# --- CLI 종료코드 -----------------------------------------------------------------


class _Args:
    def __init__(self, **kw):
        self.repo, self.pr, self.sha = "o/r", 5, "m1"
        self.wait_checks, self.wait_interval = 0, 20
        self.__dict__.update(kw)


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1])


def test_check_pr_종료코드(monkeypatch, capsys):
    def _answer(**kw):
        base = {"enabled": True, "risk": "low", "reasons": [], "requires_approval": False, "approved": None,
                "stale_approvers": [], "waiting_on_checks": False, "approval_note": "", "next": ""}
        return {**base, **kw}

    for result, code in [
        (_answer(enabled=False), 0),
        (_answer(), 0),
        (_answer(risk="high", requires_approval=True, approved=True), 0),
        (_answer(risk="high", requires_approval=True, approved=False), 1),
    ]:
        monkeypatch.setattr(rg, "decide_pr_waiting", lambda *a, _r=result, **k: _r)
        assert rg.cmd_check_pr(_Args()) == code
        assert _last_json(capsys)["risk"] == result["risk"]


@pytest.mark.parametrize("exc", [GhError("네트워크가 없다"), rg.ConfigError("설정이 잘못됐다")])
def test_check_pr_는_판정_불가를_통과로_뭉개지_않고_2(monkeypatch, capsys, exc):
    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(rg, "decide_pr_waiting", _raise)
    assert rg.cmd_check_pr(_Args()) == 2
    out = _last_json(capsys)
    assert out["requires_approval"] is None and out["approved"] is None
    assert "판정 불가" in out["reasons"][0]


@pytest.mark.parametrize("exc", [RuntimeError("뜻밖"), TypeError("섞인 키"), AttributeError("list")])
def test_check_pr_는_예상_못_한_예외도_승인_필요가_아니라_2(monkeypatch, capsys, exc):
    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(rg, "decide_pr_waiting", _raise)
    assert rg.cmd_check_pr(_Args()) == 2
    out = _last_json(capsys)
    assert out["requires_approval"] is None and out["approved"] is None
    assert "판정 불가" in out["reasons"][0]
    assert type(exc).__name__ in out["reasons"][0] and str(exc) in out["reasons"][0]


@pytest.mark.parametrize("exc", [RuntimeError("뜻밖"), TypeError("섞인 키")])
def test_check_commit_은_예상_못_한_예외도_2(monkeypatch, capsys, exc):
    def _raise(c, r, s):
        raise exc

    monkeypatch.setattr(rg, "decide_commit", _raise)
    assert rg.cmd_check_commit(_Args()) == 2
    out = _last_json(capsys)
    assert out["prs"] == []
    assert type(exc).__name__ in out["reasons"][0] and str(exc) in out["reasons"][0]


def test_check_commit_종료코드(monkeypatch, capsys):
    monkeypatch.setattr(rg, "decide_commit", lambda c, r, s: rg._commit_result(True, "low", True, [], [], ""))
    assert rg.cmd_check_commit(_Args()) == 0
    monkeypatch.setattr(rg, "decide_commit", lambda c, r, s: rg._commit_result(True, "high", False, ["x"], [], "다음: y"))
    assert rg.cmd_check_commit(_Args()) == 1
    capsys.readouterr()

    def _raise(c, r, s):
        raise GhError("실패")

    monkeypatch.setattr(rg, "decide_commit", _raise)
    assert rg.cmd_check_commit(_Args()) == 2
    assert _last_json(capsys)["prs"] == []


def test_main_인자를_해석한다(monkeypatch):
    monkeypatch.setattr(rg, "decide_pr_waiting", lambda c, r, p, w, i: rg._disabled_result())
    assert rg.main(["check-pr", "--repo", "o/r", "--pr", "5", "--wait-checks", "30"]) == 0


def test_기준_등록부는_이름이_겹치지_않는다():
    names = [n for n, _ in rg.CRITERIA]
    assert names == ["size", "paths", "secret", "checks", "ai_review"]
    assert len(names) == len(set(names))


# --- precheck-pr(#125) ---------------------------------------------------------------


def test_precheck_설정이_없으면_돌리지_않는다():
    assert rg.precheck_pr(_client(config=None), "o/r", 5) == {
        "enabled": False, "gate": False, "risky": False, "reasons": ["risk-gate 설정 없음"]}


def test_precheck_ai_review_가_꺼져_있으면_돌리지_않는다():
    result = rg.precheck_pr(_client(config="ai_review: false\n"), "o/r", 5)
    assert result["enabled"] is False and result["gate"] is True and result["risky"] is False


def test_precheck_위험하지_않으면_돌려도_된다():
    result = rg.precheck_pr(_client(config="ai_review: true\n"), "o/r", 5)
    assert result == {"enabled": True, "gate": True, "risky": False, "reasons": []}


@pytest.mark.parametrize(
    "files",
    [
        [_file("src/a.py", 500, 0)],
        [_file("rules/a.yaml")],
        [_file("a.py", 1, 0, patch=_patch(AWS_KEY))],
    ],
)
def test_precheck_크기_경로_비밀값이_위험이면_돌리지_않는다(files):
    result = rg.precheck_pr(_client(config="ai_review: true\n", files=files), "o/r", 5)
    assert result["enabled"] is True and result["risky"] is True and result["reasons"]


def test_precheck_는_checks_와_ai_review_기준을_평가하지_않는다():
    runs = [_run("test", conclusion="failure"), _run("ai-review", conclusion="failure"),
            _run("slow", status="in_progress", conclusion=None)]
    client = _client(config="ai_review: true\n", check_runs=runs)
    result = rg.precheck_pr(client, "o/r", 5)
    assert result["risky"] is False
    assert not any("check-runs" in path or "/status" in path for path in client.asked)


class _PreArgs:
    repo, pr = "o/r", 5


def test_cmd_precheck_pr_종료코드(monkeypatch, capsys):
    for result, code in [
        ({"enabled": True, "gate": True, "risky": False, "reasons": []}, 0),
        ({"enabled": True, "gate": True, "risky": True, "reasons": ["x"]}, 3),
        ({"enabled": False, "gate": True, "risky": False, "reasons": ["꺼짐"]}, 3),
        ({"enabled": False, "gate": False, "risky": False, "reasons": ["없음"]}, 3),
    ]:
        monkeypatch.setattr(rg, "precheck_pr", lambda *a, _r=result: _r)
        assert rg.cmd_precheck_pr(_PreArgs()) == code
        assert _last_json(capsys) == result


@pytest.mark.parametrize("exc", [GhError("네트워크"), rg.ConfigError("설정"), RuntimeError("뜻밖"), TypeError("x")])
def test_cmd_precheck_pr_판정_불가는_2(monkeypatch, capsys, exc):
    def _raise(*a, **k):
        raise exc

    monkeypatch.setattr(rg, "precheck_pr", _raise)
    assert rg.cmd_precheck_pr(_PreArgs()) == 2
    out = _last_json(capsys)
    assert out["enabled"] is None and out["risky"] is None and "판정 불가" in out["reasons"][0]


def test_main_precheck_pr_인자를_해석한다(monkeypatch):
    monkeypatch.setattr(rg, "precheck_pr", lambda c, r, p: {"enabled": True, "gate": True, "risky": False, "reasons": []})
    assert rg.main(["precheck-pr", "--repo", "o/r", "--pr", "5"]) == 0
