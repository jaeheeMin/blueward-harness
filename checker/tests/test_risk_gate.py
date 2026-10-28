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


def test_ai_review_paths_기본은_빈_목록이고_설정이_덮는다():
    assert rg.load_config(None)["ai_review_paths"] == []
    assert rg.load_config("ai_review_paths:\n  - src/\n")["ai_review_paths"] == ["src/"]
    assert rg.load_config("ai_review_paths:\n")["ai_review_paths"] == []  # 값 없음 = 빈 목록


def test_size_warn_only_paths_기본은_빈_목록이고_설정이_덮는다():
    assert rg.load_config(None)["size_warn_only_paths"] == []
    assert rg.load_config("size_warn_only_paths:\n  - src/\n")["size_warn_only_paths"] == ["src/"]
    assert rg.load_config("size_warn_only_paths:\n")["size_warn_only_paths"] == []


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
        "ai_review_paths: src/\n",  # 목록이 아니면 오류
        "ai_review_paths: [1]\n",
        "ai_review_path: [src/]\n",  # 키 오타는 모르는 키 오류
        "size_warn_only_paths: src/\n",  # 목록이 아니면 오류(#436)
        "size_warn_only_paths: [1]\n",
        "size_warn_only_path: [src/]\n",  # 키 오타
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
    reasons = rg.path_reasons(["src/a.py", "docs/ssot/SRS.md"], ["docs/ssot/"])
    assert reasons == ["위험 경로를 바꿈: docs/ssot/SRS.md"]


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


def test_병합_순서_status_와_pr_queue_job_은_세지_않는다():
    runs = [
        _run("merge-order", conclusion="failure"),
        _run("merge-order", status="in_progress", conclusion=None),  # 앞 PR 대기 pending(#401)
        _run("pr-queue / queue", conclusion="cancelled"),
        _run("pr-queue / queue", status="in_progress", conclusion=None),
    ]
    assert rg.checks_reasons(runs) == ([], [])


def test_합친_job_pr_checks_pr_review_main_checks_는_세지_않는다():
    # 합친 job 안에서 risk-gate 가 돌므로 세면 자기가 끝나길 기다리는 교착이 된다(#417, #419).
    runs = [
        _run("pr-checks / check", conclusion="failure"),
        _run("pr-checks / check", status="in_progress", conclusion=None),
        _run("pr-review / review", status="in_progress", conclusion=None),
        _run("main-checks / check", conclusion="cancelled"),
    ]
    assert rg.checks_reasons(runs) == ([], [])


def test_옛_이름_commit_status_는_실패로_센다():
    # pr-checks 단계가 옛 이름으로 단 status(StatusContext: context/state)는 지금처럼 센다.
    statuses = [
        {"context": "doc-guard", "state": "failure"},
        {"context": "gitleaks", "state": "error"},  # 검사 불능(error)도 실패로 센다
        {"context": "ssot-approval", "state": "failure"},  # 제외 대상은 그대로 뺀다
    ]
    runs = [r for r in rg.fetch_check_runs(_client(statuses=statuses), "o/r", HEAD)]
    failed, waiting = rg.checks_reasons(runs)
    assert "doc-guard" in failed[0] and "gitleaks" in failed[0] and "ssot-approval" not in failed[0]
    assert waiting == []


def test_옛_이름_commit_status_가_진행_중이면_기다린다():
    runs = rg.fetch_check_runs(_client(statuses=[{"context": "doc-guard", "state": "pending"}]), "o/r", HEAD)
    assert rg.checks_reasons(runs)[1]


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


BOT = {"login": "github-actions[bot]", "type": "Bot"}


def _ai_comment(status, sha=None, **extra):
    marker = {"sha": sha or HEAD, "status": status, "serious": 0, "findings": [], "unreviewed": 0, **extra}
    body = "<!-- ai-review -->\n## ai-review\n\n**x**\n\n<!-- ai-review-result " + json.dumps(marker) + " -->\n"
    return {"body": body, "user": BOT}


def _reasons(conclusion, comments=None, status="completed"):
    return rg.ai_review_reasons([_run("ai-review", status=status, conclusion=conclusion)], lambda: comments or [], HEAD)


def test_ai_review_failure_는_표식으로_심각한_지적을_가른다():
    findings = [{"file": f"f{i}.py", "line": i, "summary": f"문제 {i}"} for i in range(1, 6)]
    flagged, waiting = _reasons("failure", [_ai_comment("fail", serious=5, findings=findings)])
    assert waiting == [] and len(flagged) == 1
    assert flagged[0].startswith("AI 리뷰 심각한 지적 5건: f1.py:1 문제 1; f2.py:2 문제 2; f3.py:3 문제 3 등")
    assert "f4.py" not in flagged[0]


def test_ai_review_심각한_지적_요약은_길면_자른다():
    findings = [{"file": "a.py", "line": 1, "summary": "가" * 500}]
    flagged, _ = _reasons("failure", [_ai_comment("fail", serious=1, findings=findings)])
    assert len(flagged[0]) < 200 and flagged[0].endswith("...")


def test_ai_review_failure_일부만_봄과_검사_불능():
    flagged, _ = _reasons("failure", [_ai_comment("partial", unreviewed=7)])
    assert flagged == ["AI 리뷰가 일부만 봄(못 본 파일 7개) — 승인자가 나머지를 확인"]
    flagged, _ = _reasons("failure", [_ai_comment("unavailable")])
    assert flagged[0].startswith("AI 리뷰 검사 불능 —")


def test_ai_review_failure_비밀값_의심으로_건너뛴_표식():
    flagged, waiting = _reasons("failure", [_ai_comment("secret")])
    assert waiting == [] and len(flagged) == 1
    assert "비밀값 의심이라 AI 리뷰를 돌리지 않음" in flagged[0] and "승인자가 직접 확인" in flagged[0]


def test_ai_review_failure_표식이_없거나_sha_가_다르면_일반_문구():
    for comments in ([], [{"body": "그냥 코멘트"}], [_ai_comment("fail", sha="b" * 40, serious=1)],
                     [{"body": "<!-- ai-review -->\n<!-- ai-review-result {깨짐 -->"}]):
        flagged, _ = _reasons("failure", comments)
        assert flagged == [rg._AI_GENERIC_FAIL]


def test_ai_review_코멘트_조회가_실패해도_일반_문구로_둔다():
    def boom():
        raise GhError("권한 없음")

    flagged, waiting = rg.ai_review_reasons([_run("ai-review", conclusion="failure")], boom, HEAD)
    assert flagged == [rg._AI_GENERIC_FAIL] and waiting == []


def test_ai_review_여러_코멘트면_마지막_표식을_쓴다():
    flagged, _ = _reasons("failure", [_ai_comment("unavailable"), _ai_comment("partial", unreviewed=2)])
    assert "일부만 봄" in flagged[0]


def test_ai_review_봇이_아닌_작성자의_표식은_무시한다():
    for user in ({"login": "someone", "type": "User"}, {"login": "github-actions[bot]", "type": "User"},
                 {"login": "evil-app[bot]", "type": "Bot"}, None):
        c = _ai_comment("partial", unreviewed=2)
        c["user"] = user
        assert rg.parse_ai_review_marker([c], HEAD) is None
        flagged, _ = _reasons("failure", [c])
        assert flagged == [rg._AI_GENERIC_FAIL]
    c = _ai_comment("pass")
    c["user"] = {"login": "someone", "type": "User"}
    assert _reasons("success", [c]) == ([], [])
    # 사람의 가짜 표식이 뒤에 있어도 봇의 표식이 남는다.
    fake = _ai_comment("pass")
    fake["user"] = {"login": "someone", "type": "User"}
    assert rg.parse_ai_review_marker([_ai_comment("partial", unreviewed=2), fake], HEAD)["status"] == "partial"


def test_ai_review_한_코멘트에_표식이_여럿이면_마지막을_쓴다():
    fake = '<!-- ai-review-result {"sha": "%s", "status": "pass"} -->\n' % HEAD
    real = _ai_comment("fail", serious=1, findings=[{"file": "a.py", "line": 1, "summary": "x"}])
    real["body"] = real["body"].replace("**x**", "**x**\n" + fake)
    assert rg.parse_ai_review_marker([real], HEAD)["status"] == "fail"


def test_ai_review_사유의_파일_이름과_요약은_멘션을_무력화하고_길이를_자른다():
    findings = [{"file": "@octo/" + "d" * 500 + ".py", "line": 1, "summary": "@someone 확인"}]
    flagged, _ = _reasons("failure", [_ai_comment("fail", serious=1, findings=findings)])
    assert "@octo" not in flagged[0] and "@someone" not in flagged[0]
    assert "@​octo/" in flagged[0] and "@​someone" in flagged[0]
    assert len(flagged[0]) < 400


@pytest.mark.parametrize(
    "conclusion, expected",
    [
        ("cancelled", "AI 리뷰가 취소돼 검사하지 못함 — ai-review 를 다시 실행"),
        ("timed_out", "AI 리뷰가 시간 초과로 검사하지 못함 — 다시 실행"),
        ("skipped", "AI 리뷰가 돌지 않음(결론 skipped) — 검사하지 못함"),
        ("neutral", "AI 리뷰가 돌지 않음(결론 neutral) — 검사하지 못함"),
    ],
)
def test_ai_review_취소_시간_초과_돌지_않음은_통과가_아니다(conclusion, expected):
    flagged, waiting = _reasons(conclusion)
    assert flagged == [expected] and waiting == []


def test_ai_review_그_밖의_결론은_결론_이름을_넣은_검사_불능():
    flagged, _ = _reasons("action_required")
    assert len(flagged) == 1 and "검사 불능" in flagged[0] and "action_required" in flagged[0]


def test_ai_review_success_에_같은_sha_의_다른_표식이_있으면_보수적으로_사유를_올린다():
    flagged, _ = _reasons("success", [_ai_comment("partial", unreviewed=3)])
    assert len(flagged) == 1 and "일부만 봄" in flagged[0] and "success" in flagged[0]
    flagged, _ = _reasons("success", [_ai_comment("fail", serious=1, findings=[{"file": "a", "line": 1, "summary": "x"}])])
    assert "심각한 지적 1건" in flagged[0]


def test_ai_review_success_는_표식이_pass_이거나_없거나_낡았으면_통과():
    assert _reasons("success", [_ai_comment("pass")]) == ([], [])
    assert _reasons("success", []) == ([], [])
    assert _reasons("success", [_ai_comment("partial", sha="b" * 40)]) == ([], [])


def test_ai_review_다른_검사의_run_state_는_그대로다():
    # cancelled·skipped 를 다르게 읽는 것은 ai-review 뿐이다.
    assert rg._run_state(_run("x", conclusion="skipped")) == "pass"
    assert rg._run_state(_run("x", conclusion="cancelled")) == "fail"


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
    comments=None,
):
    r = {
        "repos/o/r/pulls/5": {"user": {"login": author}, "base": {"ref": base}, "head": {"sha": head}},
        "repos/o/r/pulls/5/files": files if files is not None else [_file("src/a.py")],
        "repos/o/r/pulls/5/reviews": reviews or [],
        f"repos/o/r/commits/{head}/check-runs*": {"check_runs": check_runs or []},
        f"repos/o/r/commits/{head}/status*": {"statuses": statuses or []},
    }
    if comments is not None:
        r["repos/o/r/issues/5/comments"] = comments
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
    client = _client(config=None, files=[_file("docs/ssot/SRS.md", 9999)])
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
    assert result["next"].startswith("다음: 🚨 직접 해 주세요: 승인자(.github/ssot-approvers 에서 이 PR 작성자에게 정해진 사람, 작성자 제외)")
    assert "PR 을 나눠" in result["next"]
    assert rg._exit_for(result) == 1


SRC_ONLY = "size_warn_only_paths:\n  - src/\n"


def test_소스만_바꾼_큰_PR_은_크기가_승인_사유가_아니라_참고다():
    client = _client(config=SRC_ONLY, files=[_file("src/a.py", 400, 0), _file("src/b.py", 10, 0)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "low" and result["requires_approval"] is False
    assert result["reasons"] == [] and result["approved"] is None and result["next"] == ""
    assert len(result["notes"]) == 1
    assert "410줄" in result["notes"][0] and "승인은 필요 없음(경고)" in result["notes"][0]
    assert rg._exit_for(result) == 0


def test_소스와_Spec_을_함께_바꾼_큰_PR_은_위험():
    client = _client(config=SRC_ONLY, files=[_file("src/a.py", 400, 0), _file("docs/spec/DEV-001.md", 3, 0)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["risk"] == "high" and result["requires_approval"] is True
    assert any("바뀐 줄이 403줄" in r for r in result["reasons"])
    assert result["notes"] == []
    assert rg._exit_for(result) == 1


def test_소스_밖_일반_파일이_하나라도_끼면_크기는_승인_사유():
    client = _client(config=SRC_ONLY, files=[_file("src/a.py", 400, 0), _file("ops/run.sh", 1, 0)])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["requires_approval"] is True and result["notes"] == []
    assert "401줄" in result["reasons"][0]


def test_size_warn_only_paths_가_비면_소스만이어도_전과_같이_위험():
    result = rg.decide_pr(_client(files=[_file("src/a.py", 400, 0)]), "o/r", 5)
    assert result["risk"] == "high" and "400줄" in result["reasons"][0]
    assert result["notes"] == []
    result = rg.decide_pr(_client(config="size_warn_only_paths: []\n", files=[_file("src/a.py", 400, 0)]), "o/r", 5)
    assert result["requires_approval"] is True


def test_소스만_바꿔도_크기_기준을_넘지_않으면_참고도_없다():
    result = rg.decide_pr(_client(config=SRC_ONLY, files=[_file("src/a.py", 10, 0)]), "o/r", 5)
    assert result["requires_approval"] is False and result["notes"] == []


def test_소스만_바꿔도_비밀값_모양이_있으면_위험이고_참고는_그대로_남는다():
    client = _client(config=SRC_ONLY, files=[_file("src/a.py", 400, 0, patch=_patch(f"KEY = '{AWS_KEY}'"))])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["requires_approval"] is True
    assert any("비밀값" in r for r in result["reasons"]) and not any("줄로 기준" in r for r in result["reasons"])
    assert len(result["notes"]) == 1
    assert AWS_KEY not in json.dumps(result, ensure_ascii=False)


def test_소스만_바꿔도_다른_검사가_실패하면_위험():
    client = _client(config=SRC_ONLY, files=[_file("src/a.py", 400, 0)], check_runs=[_run("test", conclusion="failure")])
    result = rg.decide_pr(client, "o/r", 5)
    assert result["requires_approval"] is True and "다른 검사가 실패함" in result["reasons"][0]
    assert len(result["notes"]) == 1


def test_precheck_는_참고를_위험으로_세지_않는다():
    client = _client(config="ai_review: true\nsize_warn_only_paths:\n  - src/\n", files=[_file("src/a.py", 400, 0)])
    result = rg.precheck_pr(client, "o/r", 5)
    assert result["risky"] is False and result["reasons"] == [] and result["criteria"] == []
    assert len(result["notes"]) == 1


def test_size_기준의_참고_Finding_은_note_표시가_붙는다():
    ctx = rg.Context(cfg=rg.load_config(SRC_ONLY), files=[_file("src/a.py", 400, 0)], prefixes=[],
                     load_check_runs=lambda: [])
    findings = [f for f in rg.evaluate(ctx) if f.criterion == "size"]
    assert [f.note for f in findings] == [True]


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


_USER_FORMAT = "# 형식: <PR 작성자>: <승인자> <승인자> ...\njaeheeMin: CSH-DOT123 Blueward-Huiseong\n*: jaeheeMin\n"


def _gate(author, approvers, reviewer=None, **kw):
    reviews = [_review(reviewer, "APPROVED", HEAD)] if reviewer else []
    client = _client(files=[_file("rules/a.yaml")], approvers=approvers, author=author, reviews=reviews, **kw)
    return rg.decide_pr(client, "o/r", 5)


@pytest.mark.parametrize("reviewer, ok", [
    ("csh-dot123", True),
    ("Blueward-Huiseong", True),
    ("someone", False),
])
def test_작성자_전용_줄의_승인자만_인정한다(reviewer, ok):
    assert _gate("jaeheeMin", _USER_FORMAT, reviewer)["approved"] is ok


def test_다른_작성자는_별표_줄을_따르고_전용_줄_사람은_승인할_수_없다():
    assert _gate("CSH-DOT123", _USER_FORMAT, "Blueward-Huiseong")["approved"] is False
    assert _gate("CSH-DOT123", _USER_FORMAT, "jaeheeMin")["approved"] is True


def test_전용_줄이_있으면_별표_줄과_옛_형식_줄은_무시한다():
    text = "alice: bob\n*: carol\ndana\n"
    assert _gate("alice", text, "carol")["approved"] is False
    assert _gate("alice", text, "bob")["approved"] is True
    assert _gate("eve", text, "carol")["approved"] is True
    assert _gate("eve", text, "dana")["approved"] is True
    assert _gate("eve", text, "bob")["approved"] is False


def test_이_작성자를_승인할_사람이_없으면_no_approvers():
    # carol 의 전용 줄은 본인뿐이고, 다른 작성자 줄이 있어도 carol 에겐 소용없다.
    result = _gate("carol", "carol: carol\n*: alice\n", "alice")
    assert result["approved"] is False
    assert "승인자의 GitHub 아이디를 추가" in result["next"]
    # 내용이 있는데 이 작성자 몫이 없다.
    result = _gate("zed", "alice: bob\n", "bob")
    assert result["approved"] is False
    assert "승인자의 GitHub 아이디를 추가" in result["next"]


def test_옛_형식_파일은_예전과_같이_동작한다():
    assert _gate("bob", "alice\n@Carol # 주석\n", "carol")["approved"] is True
    assert _gate("bob", "alice\n@Carol # 주석\n", "dana")["approved"] is False


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


def test_decide_pr_는_ai_review_표식으로_사유를_가른다():
    cfg = "ai_review: true\n"
    comments = [_ai_comment("fail", serious=1, findings=[{"file": "a.py", "line": 3, "summary": "널 참조"}])]
    result = rg.decide_pr(_client(config=cfg, check_runs=[_run("ai-review", conclusion="failure")],
                                  comments=comments), "o/r", 5)
    assert result["reasons"] == ["AI 리뷰 심각한 지적 1건: a.py:3 널 참조"]
    assert "일부만 봤으면" in result["next"] and "취소" in result["next"]
    cancelled = rg.decide_pr(_client(config=cfg, check_runs=[_run("ai-review", conclusion="cancelled")]), "o/r", 5)
    assert cancelled["reasons"] == ["AI 리뷰가 취소돼 검사하지 못함 — ai-review 를 다시 실행"]
    # 위험 PR 도 마찬가지로 AI 지적이 사유에 붙고 승인자가 필요하다.
    risky = rg.decide_pr(_client(config=cfg, files=[_file("rules/a.yaml")],
                                 check_runs=[_run("ai-review", conclusion="failure")], comments=comments), "o/r", 5)
    assert any("AI 리뷰 심각한 지적 1건" in r for r in risky["reasons"]) and risky["requires_approval"] is True


def test_decide_pr_코멘트_조회가_실패해도_판정_불능이_되지_않는다():
    # FakeClient 는 모르는 경로에 KeyError 를 던진다 — 코멘트를 못 읽는 경우와 같다.
    result = rg.decide_pr(_client(config="ai_review: true\n", check_runs=[_run("ai-review", conclusion="failure")]),
                          "o/r", 5)
    assert result["reasons"] == [rg._AI_GENERIC_FAIL]


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


_NOSLEEP = lambda s: None  # noqa: E731 - 재조회 간격을 건너뛴다


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
    client = _commit_client(prs=[], files=[_file("docs/ssot/SRS.md")])
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert result["approved"] is False and "PR 없이" in result["reasons"][0]
    assert rg._exit_for(result) == 1


def test_PR_없이_들어온_안전한_변경은_통과():
    client = _commit_client(prs=[], files=[_file("src/a.py")])
    assert rg._exit_for(rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)) == 0


def test_PR_없이_들어온_커밋도_설정이_없으면_통과():
    client = _commit_client(prs=[], config=None, files=[_file("docs/ssot/SRS.md")])
    assert rg._exit_for(rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)) == 0


# --- decide_commit: 연결 지연·진행 중 검사 (#130) -----------------------------------


class _SeqClient(FakeClient):
    """`commits/m1/pulls` 를 부를 때마다 `pulls_seq` 의 다음 응답을 돌려준다(마지막은 반복)."""

    def __init__(self, responses, pulls_seq):
        super().__init__(responses)
        self.pulls_seq = list(pulls_seq)
        self.pull_calls = 0

    def _lookup(self, path):
        if path == "repos/o/r/commits/m1/pulls":
            self.asked.append(path)
            i = min(self.pull_calls, len(self.pulls_seq) - 1)
            self.pull_calls += 1
            value = self.pulls_seq[i]
            if isinstance(value, Exception):
                raise value
            return value
        return super()._lookup(path)


def _late_client(pulls_seq, *, title="feat: x (#5)", files=None, pr_info=None, check_runs=None, config=""):
    base = _commit_client(prs=[], files=files if files is not None else [_file("src/a.py")], config=config)
    r = dict(base.responses)
    r["repos/o/r/commits/m1"] = dict(r["repos/o/r/commits/m1"], commit={"message": title + "\n\n본문"})
    if pr_info is not None:
        r["repos/o/r/pulls/5"] = dict(r["repos/o/r/pulls/5"], **pr_info)
    if check_runs is not None:
        r["repos/o/r/commits/m1/check-runs*"] = {"check_runs": check_runs}
    return _SeqClient(r, pulls_seq)


_MERGED_PR = {"number": 5, "merged_at": "2026-01-01", "html_url": "u"}
_MERGED_INFO = {"merged_at": "2026-01-01", "merge_commit_sha": "m1", "html_url": "https://x/5", "number": 5}


def test_연결이_늦게_잡혀도_재조회로_PR_을_찾는다():
    sleeps = []
    client = _late_client([[], [], [_MERGED_PR]], files=[_file("rules/a.yaml")])
    result = rg.decide_commit(client, "o/r", "m1", sleep=sleeps.append, retry_interval=2)
    assert client.pull_calls == 3 and sleeps == [2, 2]
    assert result["prs"][0]["pr"] == 5 and not any("PR 없이" in r for r in result["reasons"])


def test_재조회에도_비면_커밋_제목의_PR_번호로_찾는다():
    client = _late_client([[]], pr_info=_MERGED_INFO, files=[_file("rules/a.yaml")])
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert client.pull_calls == rg.LINK_RETRIES
    assert result["prs"][0]["pr"] == 5 and not any("PR 없이" in r for r in result["reasons"])
    assert rg._exit_for(result) == 1  # 위험한 PR 을 승인 없이 병합 — PR 경로로 판정됨


def test_제목의_PR_번호로_찾은_승인된_PR_은_통과():
    client = _late_client([[]], pr_info=_MERGED_INFO, files=[_file("rules/a.yaml")])
    client.responses["repos/o/r/pulls/5/reviews"] = [_review("alice", "APPROVED", HEAD)]
    assert rg._exit_for(rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)) == 0


def test_제목_PR_번호의_merge_commit_sha_가_다르면_직접_push_로_본다():
    info = dict(_MERGED_INFO, merge_commit_sha="other")
    client = _late_client([[]], pr_info=info, files=[_file("docs/ssot/SRS.md")])
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert "PR 없이" in result["reasons"][0] and rg._exit_for(result) == 1


def test_제목_PR_번호의_PR_이_병합되지_않았으면_직접_push_로_본다():
    info = {"merged_at": None, "merge_commit_sha": "m1", "number": 5}
    client = _late_client([[]], pr_info=info, files=[_file("docs/ssot/SRS.md")])
    assert "PR 없이" in rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)["reasons"][0]


def test_제목_번호가_PR_이_아니어서_404_면_직접_push_로_본다():
    client = _late_client([[]], files=[_file("docs/ssot/SRS.md")])
    client.responses["repos/o/r/pulls/5"] = GhError("gh: Not Found (HTTP 404)", status=404)
    assert "PR 없이" in rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)["reasons"][0]


def test_PR_번호_근거도_연결도_없는_진짜_직접_push_는_잡힌다():
    client = _late_client([[]], title="chore: 직접 수정", files=[_file("docs/ssot/SRS.md")])
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert client.pull_calls == rg.LINK_RETRIES
    assert "PR 없이" in result["reasons"][0] and rg._exit_for(result) == 1


def test_직접_push_에서_진행_중인_검사만_있으면_위험이_아니다():
    runs = [{"name": "ci / test", "status": "in_progress", "conclusion": None}]
    client = _late_client([[]], title="chore: x", check_runs=runs, config="require_checks_green: true\n")
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert result["risk"] == "low" and rg._exit_for(result) == 0


def test_직접_push_에서_실패한_검사는_위험이다():
    runs = [
        {"name": "ci / test", "status": "completed", "conclusion": "failure"},
        {"name": "ci / lint", "status": "in_progress", "conclusion": None},
    ]
    client = _late_client([[]], title="chore: x", check_runs=runs, config="require_checks_green: true\n")
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert rg._exit_for(result) == 1
    assert any("실패" in r for r in result["reasons"]) and not any("끝나지 않음" in r for r in result["reasons"])


def test_연결_조회가_실패하면_판정_불가_2(monkeypatch):
    client = _late_client([GhError("boom")], title="chore: x")
    monkeypatch.setattr(rg, "GhClient", lambda: client)
    monkeypatch.setattr(rg.time, "sleep", _NOSLEEP)
    assert rg.cmd_check_commit(_Args()) == 2


def test_제목_번호_조회가_실패하면_판정_불가_2(monkeypatch):
    client = _late_client([[]], pr_info=None)
    client.responses["repos/o/r/pulls/5"] = GhError("timeout")
    monkeypatch.setattr(rg, "GhClient", lambda: client)
    monkeypatch.setattr(rg.time, "sleep", _NOSLEEP)
    assert rg.cmd_check_commit(_Args()) == 2


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
    assert names == ["size", "paths", "secret", "split_hint", "write_auth", "checks", "ai_review"]
    assert len(names) == len(set(names))


# --- write_auth: 쓰기 앱인데 권한 검사 없음(#361) ----------------------------------------

POOL_PATH = "src/zbp_x.clas.locals_imp.abap"
POOL_ALLOW_ALL = (
    "CLASS lhc DEFINITION INHERITING FROM cl_abap_behavior_handler.\n"
    "  PRIVATE SECTION.\n"
    "    METHODS get_global_authorizations FOR GLOBAL AUTHORIZATION\n"
    "      IMPORTING REQUEST requested_authorizations FOR Upload RESULT result.\n"
    "ENDCLASS.\n"
    "CLASS lhc IMPLEMENTATION.\n"
    "  METHOD get_global_authorizations.\n"
    "    result-%create = if_abap_behv=>auth-allowed.\n"
    "  ENDMETHOD.\n"
    "ENDCLASS.\n"
)
POOL_WITH_CHECK = POOL_ALLOW_ALL.replace(
    "    result-%create = if_abap_behv=>auth-allowed.\n",
    "    AUTHORITY-CHECK OBJECT 'ZPLANT' ID 'ACTVT' FIELD '02'.\n"
    "    IF sy-subrc = 0.\n      result-%create = if_abap_behv=>auth-allowed.\n    ENDIF.\n",
)


def _pool_client(text, *, config="", status="modified", path=POOL_PATH):
    f = _file(path)
    f["status"] = status
    client = _client(config=config, files=[f])
    if text is not None:
        client.responses[f"repos/o/r/contents/{path}?ref={HEAD}"] = _b64(text)
    return client


def _auth_reasons(result):
    return [r for r in result["reasons"] if "권한" in r]


def test_권한_전부_허용만_하는_behavior_pool_은_위험으로_판정한다():
    result = rg.decide_pr(_pool_client(POOL_ALLOW_ALL), "o/r", 5)
    assert result["requires_approval"] is True
    assert _auth_reasons(result) == [f"쓰기 앱인데 권한 검사 없음: {POOL_PATH}"]
    assert "AUTHORITY-CHECK" in result["next"]


def test_AUTHORITY_CHECK_가_있으면_사유_없음():
    result = rg.decide_pr(_pool_client(POOL_WITH_CHECK), "o/r", 5)
    assert _auth_reasons(result) == [] and result["requires_approval"] is False


def test_harness_allow_CR_009_가_있으면_사유_없음():
    text = POOL_ALLOW_ALL.replace(
        "  METHOD get_global_authorizations.\n",
        '  " harness:allow CR-009 표준 BO 가 검사한다(홍길동 2026-10-19)\n  METHOD get_global_authorizations.\n',
    )
    assert _auth_reasons(rg.decide_pr(_pool_client(text), "o/r", 5)) == []


def test_지워진_파일과_abap_가_아닌_파일은_읽지_않는다():
    client = _pool_client(None, status="removed")
    assert _auth_reasons(rg.decide_pr(client, "o/r", 5)) == []
    client = _pool_client(None, path="src/a.py")
    assert _auth_reasons(rg.decide_pr(client, "o/r", 5)) == []
    assert not any("contents/src" in p for p in client.asked)


def test_abap_파일을_읽지_못하면_판정_불능_사유():
    result = rg.decide_pr(_pool_client(None), "o/r", 5)
    (reason,) = _auth_reasons(result)
    assert "확인하지 못함" in reason and POOL_PATH in reason
    assert result["requires_approval"] is True


def test_권한_기준에_새_설정_키가_필요하지_않다():
    # 옛 risk-gate.yaml 도 그대로 읽힌다: 모르는 키가 없어 판정 불능이 되지 않는다.
    assert "write_auth" not in rg.DEFAULT_CONFIG
    rg.decide_pr(_pool_client(POOL_ALLOW_ALL, config="max_changed_lines: 300\n"), "o/r", 5)


def test_병합_뒤_감지의_사유에도_권한_줄이_찍힌다():
    client = _commit_client(
        prs=[{"number": 5, "merged_at": "2026-01-01", "html_url": "u"}],
        files=[{**_file(POOL_PATH), "status": "modified"}],
    )
    client.responses[f"repos/o/r/contents/{POOL_PATH}?ref={HEAD}"] = _b64(POOL_ALLOW_ALL)
    result = rg.decide_commit(client, "o/r", "m1")
    assert result["approved"] is False
    assert f"쓰기 앱인데 권한 검사 없음: {POOL_PATH}" in result["reasons"]


def test_PR_없이_main_에_들어온_pool_도_권한_줄이_찍힌다():
    client = _commit_client(prs=[], files=[{**_file(POOL_PATH), "status": "modified"}])
    client.responses[f"repos/o/r/contents/{POOL_PATH}?ref=m1"] = _b64(POOL_ALLOW_ALL)
    result = rg.decide_commit(client, "o/r", "m1", sleep=_NOSLEEP)
    assert f"쓰기 앱인데 권한 검사 없음: {POOL_PATH}" in result["reasons"]


# --- AI 리뷰 대상 경로(#411) ---------------------------------------------------------------


def test_ai_review_target_목록이_비면_모든_PR_이_대상():
    assert rg.ai_review_target(["docs/a.md"], []) is True
    assert rg.ai_review_target([], []) is True


def test_ai_review_target_접두어_아래_파일이_하나라도_있어야_대상():
    assert rg.ai_review_target(["docs/a.md", "src/app/a.ts"], ["src/"]) is True
    assert rg.ai_review_target(["docs/a.md", "rules/x.yaml"], ["src/"]) is False
    assert rg.ai_review_target([], ["src/"]) is False
    assert rg.ai_review_target(["srcx/a.ts"], ["src/"]) is False  # 접두어 매칭이지 부분 문자열이 아니다


def test_ai_review_대상_아닌_PR_은_결과가_없어도_대기하지_않는다():
    cfg = "ai_review: true\nai_review_paths:\n  - src/\n"
    docs_only = rg.decide_pr(_client(config=cfg, files=[_file("docs/a.md")]), "o/r", 5)
    assert docs_only["risk"] == "low" and not docs_only.get("waiting_on_checks")
    # 코드를 바꾼 PR 은 전과 같이 결과를 기다린다.
    code = rg.decide_pr(_client(config=cfg, files=[_file("src/a.ts")]), "o/r", 5)
    assert code["risk"] == "high" and code["waiting_on_checks"] is True


def test_ai_review_paths_가_비어_있으면_문서만_바꾼_PR_도_전과_같이_기다린다():
    result = rg.decide_pr(_client(config="ai_review: true\n", files=[_file("docs/a.md")]), "o/r", 5)
    assert result["risk"] == "high" and result["waiting_on_checks"] is True


def test_대상_아닌_PR_이어도_위험_사유는_그대로다():
    cfg = "ai_review: true\nai_review_paths:\n  - src/\n"
    result = rg.decide_pr(_client(config=cfg, files=[_file("rules/a.yaml")]), "o/r", 5)
    assert result["risk"] == "high" and any("위험 경로" in r for r in result["reasons"])
    assert not any("AI 리뷰" in r for r in result["reasons"])


def test_precheck_대상_아니면_돌리지_않는다():
    cfg = "ai_review: true\nai_review_paths:\n  - src/\n"
    result = rg.precheck_pr(_client(config=cfg, files=[_file("docs/a.md")]), "o/r", 5)
    assert result["enabled"] is False and result["risky"] is False
    assert "AI 리뷰 대상 아님" in result["reasons"][0]
    on = rg.precheck_pr(_client(config=cfg, files=[_file("src/a.ts")]), "o/r", 5)
    assert on["enabled"] is True


# --- precheck-pr(#125) ---------------------------------------------------------------


def test_precheck_설정이_없으면_돌리지_않는다():
    assert rg.precheck_pr(_client(config=None), "o/r", 5) == {
        "enabled": False, "gate": False, "risky": False, "reasons": ["risk-gate 설정 없음"]}


def test_precheck_ai_review_가_꺼져_있으면_돌리지_않는다():
    result = rg.precheck_pr(_client(config="ai_review: false\n"), "o/r", 5)
    assert result["enabled"] is False and result["gate"] is True and result["risky"] is False


def test_precheck_위험하지_않으면_돌려도_된다():
    result = rg.precheck_pr(_client(config="ai_review: true\n"), "o/r", 5)
    assert result == {"enabled": True, "gate": True, "risky": False, "reasons": [], "notes": [], "criteria": [],
                      "secret_found": False, "secret_patterns": []}


@pytest.mark.parametrize(
    "files, criteria",
    [
        ([_file("src/a.py", 500, 0)], ["size"]),
        ([_file("rules/a.yaml")], ["paths"]),
        ([_file("a.py", 1, 0, patch=_patch(AWS_KEY))], ["secret"]),
    ],
)
def test_precheck_크기_경로_비밀값이_위험이어도_enabled_는_true(files, criteria):
    result = rg.precheck_pr(_client(config="ai_review: true\n", files=files), "o/r", 5)
    # 위험 여부와 사유는 코멘트 안내용으로 남기되 enabled 는 true 다(#360). 기준 이름도 출력한다.
    assert result["enabled"] is True and result["risky"] is True and result["reasons"]
    assert result["criteria"] == criteria


def test_precheck_새_줄에_비밀값_패턴이_보이면_secret_found_와_패턴_이름만_낸다():
    files = [_file("a.py", 1, 0, patch=_patch(AWS_KEY))]
    result = rg.precheck_pr(_client(config="ai_review: true\n", files=files), "o/r", 5)
    assert result["secret_found"] is True and result["secret_patterns"] == ["AWS 액세스 키 ID"]
    assert AWS_KEY not in json.dumps(result, ensure_ascii=False)  # 값은 어디에도 남지 않는다


def test_precheck_크기만_커서_비밀값_검사를_못_한_파일은_secret_found_가_아니다():
    # patch 가 없는 큰 파일: `_crit_secret` 은 "검사 못 함" 사유를 내지만 비밀값이 보인 것은 아니다 — 리뷰는 계속 돈다.
    files = [_file("big.py", 5000, 0, patch=None)]
    result = rg.precheck_pr(_client(config="ai_review: true\n", files=files), "o/r", 5)
    assert result["risky"] is True and "secret" in result["criteria"]
    assert result["secret_found"] is False and result["secret_patterns"] == []


def test_precheck_secret_scan_이_꺼져_있으면_secret_found_가_아니다():
    files = [_file("a.py", 1, 0, patch=_patch(AWS_KEY))]
    result = rg.precheck_pr(_client(config="ai_review: true\nsecret_scan: false\n", files=files), "o/r", 5)
    assert result["secret_found"] is False


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
        ({"enabled": True, "gate": True, "risky": True, "reasons": ["x"]}, 0),
        ({"enabled": False, "gate": True, "risky": False, "reasons": ["꺼짐"]}, 3),
        ({"enabled": False, "gate": False, "risky": False, "reasons": ["없음"]}, 3),
        ({"enabled": True, "gate": True, "risky": True, "reasons": ["x"], "secret_found": True,
          "secret_patterns": ["AWS 액세스 키 ID"]}, 4),
        ({"enabled": True, "gate": True, "risky": True, "reasons": ["x"], "secret_found": False,
          "secret_patterns": []}, 0),
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


# --- SRS 쪼개짐 의심(#278) ----------------------------------------------------------

SRS_BASE = """# SRS

## 범위

- 하는 것:
  - 판매오더 조회 (REQ-002)
- 하지 않는 것:
  - 판매오더 생성·변경·삭제 (조회 전용)
  - Fiori Launchpad 노출(IAM App, Business Catalog, Role)과 외부 소비용 API 서비스
  - 개발사양서 xlsx 작성

## 요구사항

| ID | Title | Status |
|---|---|---|
| REQ-001 | 회계전표 Excel 업로드 일괄 전기 | New |
| REQ-002 | 판매오더 조회 앱 | In Process |

### REQ-002 판매오더 조회 앱

#### Short Description

조회 전용 앱.
"""

REQ3_ROW = "| REQ-003 | 판매오더 조회 앱 Fiori Launchpad 타일 노출 | New |"
SRS_HEAD_INCIDENT = (
    SRS_BASE.replace(
        "  - Fiori Launchpad 노출(IAM App, Business Catalog, Role)과 외부 소비용 API 서비스",
        "  - Fiori Launchpad 노출은 REQ-003 으로 따로 다룬다. 외부 소비용 API 서비스는 하지 않는다",
    ).replace("| REQ-002 | 판매오더 조회 앱 | In Process |", "| REQ-002 | 판매오더 조회 앱 | In Process |\n" + REQ3_ROW)
    + "\n### REQ-003 판매오더 조회 앱 Fiori Launchpad 타일 노출\n\n#### Short Description\n\n"
    "판매오더 조회 앱(REQ-002)을 타일로 연다. DEV-002 개발 중 범위 밖으로 둔 항목.\n"
)
SRS_HEAD_SEPARATE = (
    SRS_BASE.replace("| REQ-002 | 판매오더 조회 앱 | In Process |", "| REQ-002 | 판매오더 조회 앱 | In Process |\n| REQ-003 | 재고 이동 일괄 등록 | New |")
    + "\n### REQ-003 재고 이동 일괄 등록\n\n#### Short Description\n\n창고 간 재고 이동을 엑셀로 올린다.\n"
)
SRS_HEAD_EDIT_ONLY = SRS_BASE.replace("조회 전용 앱.", "조회 전용 앱. 필터는 자재코드·수량·금액.").replace(
    "| REQ-002 | 판매오더 조회 앱 | In Process |", "| REQ-002 | 판매오더 조회 앱 | Done |"
)


MERGE_BASE = "mmmmmmm0000"


def _srs_client(head_text, *, patch_row=REQ3_ROW, config="", base_text=SRS_BASE, srs_status="modified", patch=True):
    files = [_file("docs/ssot/SRS.md", 20, 1, patch=_patch(patch_row) if patch else None)]
    files[0]["status"] = srs_status
    client = _client(config=config, files=files)
    client.responses[f"repos/o/r/compare/main...{HEAD}?per_page=1"] = {"merge_base_commit": {"sha": MERGE_BASE}}
    if base_text is not None:
        client.responses[f"repos/o/r/contents/docs/ssot/SRS.md?ref={MERGE_BASE}"] = _b64(base_text)
    client.responses[f"repos/o/r/contents/docs/ssot/SRS.md?ref={HEAD}"] = _b64(head_text)
    return client


def _hint_reasons(result):
    return [r for r in result["reasons"] if "SRS 새 요구사항" in r]


def test_split_hint_는_기본으로_켜져_있다():
    assert rg.load_config("")["srs_split_hint"] is True
    assert rg.load_config("srs_split_hint: false")["srs_split_hint"] is False
    with pytest.raises(rg.ConfigError):
        rg.load_config("srs_split_hint: 1")


def test_사건_재현_세_근거가_모두_나온다():
    result = rg.decide_pr(_srs_client(SRS_HEAD_INCIDENT), "o/r", 5)
    (reason,) = _hint_reasons(result)
    assert "REQ-003" in reason and "확장 의심" in reason
    assert "(a)" in reason and "REQ-002(판매오더 조회 앱), DEV-002(판매오더 조회 앱)" in reason
    assert "(b)" in reason and "Fiori Launchpad 노출(IAM App" in reason
    assert "(c)" in reason and "REQ-002(판매오더 조회 앱)" in reason
    assert "승인자가 SRS diff" in result["next"]


def test_기존_REQ_내용만_고치면_사유_없음():
    result = rg.decide_pr(_srs_client(SRS_HEAD_EDIT_ONLY, patch_row="| REQ-002 | 판매오더 조회 앱 | Done |"), "o/r", 5)
    assert _hint_reasons(result) == []


def test_완전히_별개인_새_REQ_는_사유_없음():
    result = rg.decide_pr(_srs_client(SRS_HEAD_SEPARATE, patch_row="| REQ-003 | 재고 이동 일괄 등록 | New |"), "o/r", 5)
    assert _hint_reasons(result) == []


def test_설정을_끄면_사유_없음():
    result = rg.decide_pr(_srs_client(SRS_HEAD_INCIDENT, config="srs_split_hint: false\n"), "o/r", 5)
    assert _hint_reasons(result) == []


def test_SRS_patch_가_없으면_검사_불능_사유():
    result = rg.decide_pr(_srs_client(SRS_HEAD_INCIDENT, patch=False), "o/r", 5)
    (reason,) = _hint_reasons(result)
    assert "검사 불능" in reason and "너무 커서" in reason


def test_SRS_를_읽지_못하면_검사_불능_사유():
    result = rg.decide_pr(_srs_client(SRS_HEAD_INCIDENT, base_text=None), "o/r", 5)
    (reason,) = _hint_reasons(result)
    assert "검사 불능" in reason and "갈라진 지점" in reason


def test_SRS_를_새로_만드는_PR_은_기준_SRS_없이도_본다():
    head = SRS_HEAD_INCIDENT
    result = rg.decide_pr(_srs_client(head, base_text=None, srs_status="added"), "o/r", 5)
    reasons = _hint_reasons(result)
    assert reasons and all("검사 불능" not in r for r in reasons)


def test_SRS_가_안_바뀌면_SRS_를_읽지도_않는다():
    client = _client(files=[_file("src/a.py")])
    rg.decide_pr(client, "o/r", 5)
    assert not any("SRS.md" in p for p in client.asked)


def test_하지_않는_것_목록은_머리말_아래_들여쓴_줄까지다():
    lines = rg.scope_exclusions(SRS_BASE)
    assert lines[0].startswith("- 하지 않는 것") and len(lines) == 4
    assert rg.scope_exclusions("## 범위\n\n- 하지 않는 것: 일부러 뺀다\n- 다른 목록\n") == ["- 하지 않는 것: 일부러 뺀다"]


def _scope_srs(scope_line):
    return SRS_BASE.replace(
        "- 하지 않는 것:\n  - 판매오더 생성·변경·삭제 (조회 전용)\n"
        "  - Fiori Launchpad 노출(IAM App, Business Catalog, Role)과 외부 소비용 API 서비스\n"
        "  - 개발사양서 xlsx 작성\n",
        scope_line + "\n",
    )


SEP_ROW = "| REQ-003 | 재고 이동 일괄 등록 | New |"


def _with_sep_req(text):
    return text.replace(
        "| REQ-002 | 판매오더 조회 앱 | In Process |", "| REQ-002 | 판매오더 조회 앱 | In Process |\n" + SEP_ROW
    )


def test_main_이_앞서가도_갈라진_지점_기준이라_오탐이_없다():
    base = _with_sep_req(SRS_BASE)  # 분기 시점의 SRS 는 head 와 같은 하지 않는 것 목록
    client = _srs_client(_with_sep_req(SRS_BASE), base_text=SRS_BASE, patch_row=SEP_ROW)
    # main 의 끝은 그 뒤 다른 PR 이 "하지 않는 것" 줄을 지우고 REQ 를 넣은 상태다. 읽으면 오탐이 난다.
    client.responses["repos/o/r/contents/docs/ssot/SRS.md?ref=main"] = _b64(
        _scope_srs("- 하지 않는 것: 없음").replace("| REQ-002 | 판매오더 조회 앱 | In Process |", "| REQ-002 | 판매오더 조회 앱 | In Process |\n" + SEP_ROW)
    )
    result = rg.decide_pr(client, "o/r", 5)
    assert _hint_reasons(result) == []
    assert "repos/o/r/contents/docs/ssot/SRS.md?ref=main" not in client.asked
    assert f"repos/o/r/contents/docs/ssot/SRS.md?ref={MERGE_BASE}" in client.asked
    assert base != SRS_BASE


def test_갈라진_지점을_못_구하면_검사_불능():
    client = _srs_client(SRS_HEAD_INCIDENT)
    client.responses[f"repos/o/r/compare/main...{HEAD}?per_page=1"] = {}
    (reason,) = _hint_reasons(rg.decide_pr(client, "o/r", 5))
    assert "검사 불능" in reason and "merge-base" in reason


def test_한_줄_형태에_항목을_덧붙이거나_문장부호만_고치면_사유_없음():
    base = _scope_srs("- 하지 않는 것: 판매오더 생성, 변경, 삭제")
    for scope in (
        "- 하지 않는 것: 판매오더 생성, 변경, 삭제, 이관",
        "- 하지 않는 것: 판매오더 생성; 변경 、 삭제.",
        "- 하지 않는 것: 판매오더 생성 · 변경 · 삭제",
    ):
        client = _srs_client(_with_sep_req(_scope_srs(scope)), base_text=base, patch_row=SEP_ROW)
        assert _hint_reasons(rg.decide_pr(client, "o/r", 5)) == [], scope


def test_한_줄_형태에서_항목을_지우면_바뀐_항목만_근거로_든다():
    base = _scope_srs("- 하지 않는 것: 판매오더 생성, 변경, 삭제")
    head = _with_sep_req(_scope_srs("- 하지 않는 것: 판매오더 생성, 삭제, 이관"))
    (reason,) = _hint_reasons(rg.decide_pr(_srs_client(head, base_text=base, patch_row=SEP_ROW), "o/r", 5))
    assert "(b)" in reason and '"변경"' in reason and "생성" not in reason and "이관" not in reason


def test_괄호_안_쉼표는_항목을_쪼개지_않는다():
    items = rg.scope_items("- 하지 않는 것: 노출(IAM App, Role), 외부 API")
    assert list(items.values()) == ["노출(IAM App, Role)", "외부 API"]


def test_번호만_바뀐_REQ_는_새_REQ_가_아니다():
    base = _with_sep_req(SRS_BASE)
    head = base.replace("REQ-003", "REQ-004")
    client = _srs_client(head, base_text=base, patch_row="| REQ-004 | 재고 이동 일괄 등록 | New |")
    assert _hint_reasons(rg.decide_pr(client, "o/r", 5)) == []


@pytest.mark.parametrize("content", [{"content": ""}, {"content": "!!!"}, {"content": "//79"}])
def test_head_SRS_가_비었거나_디코딩_실패면_검사_불능(content):
    client = _srs_client(SRS_HEAD_INCIDENT)
    client.responses[f"repos/o/r/contents/docs/ssot/SRS.md?ref={HEAD}"] = content
    (reason,) = _hint_reasons(rg.decide_pr(client, "o/r", 5))
    assert "검사 불능" in reason and "PR 의 SRS" in reason


def test_SRS_경로가_디렉터리_응답이면_검사_불능():
    client = _srs_client(SRS_HEAD_INCIDENT)
    client.responses[f"repos/o/r/contents/docs/ssot/SRS.md?ref={HEAD}"] = [{"name": "x"}]
    (reason,) = _hint_reasons(rg.decide_pr(client, "o/r", 5))
    assert "검사 불능" in reason


def test_decide_pr_는_읽는_함수와_ref_를_Context_에_넘긴다(monkeypatch):
    seen = {}

    def fake_evaluate(ctx):
        seen["ctx"] = ctx
        return []

    monkeypatch.setattr(rg, "evaluate", fake_evaluate)
    client = _srs_client(SRS_HEAD_INCIDENT)
    rg.decide_pr(client, "o/r", 5)
    ctx = seen["ctx"]
    assert ctx.head_ref == HEAD and ctx.base_ref == "main"
    assert ctx.merge_base() == MERGE_BASE
    assert ctx.read_text(HEAD, "docs/ssot/SRS.md") == SRS_HEAD_INCIDENT
    assert ctx.read_text("nope", "docs/ssot/SRS.md") is None


def test_config_ref_로_부르면_그_ref_와_head_의_갈라진_지점을_쓴다(monkeypatch):
    seen = {}
    monkeypatch.setattr(rg, "evaluate", lambda ctx: seen.setdefault("ctx", ctx) and [])
    client = _srs_client(SRS_HEAD_INCIDENT, config="")
    client.responses["repos/o/r/contents/.github/risk-gate.yaml?ref=parent1"] = _b64("")
    client.responses["repos/o/r/contents/.github/human-merge-paths?ref=parent1"] = _b64("")
    client.responses[f"repos/o/r/compare/parent1...{HEAD}?per_page=1"] = {"merge_base_commit": {"sha": "mb2"}}
    rg.decide_pr(client, "o/r", 5, config_ref="parent1")
    assert seen["ctx"].base_ref == "parent1" and seen["ctx"].merge_base() == "mb2"


def test_다음_안내에_split_hint_문구가_들어간다():
    findings = [rg.Finding("split_hint", "x")]
    nxt = rg.build_next(findings, "missing", ".github/ssot-approvers")
    assert "SRS diff" in nxt and "기존 REQ 의 범위를 넓히" in nxt


# --- "하지 않는 것" 항목 꼬리표 `(REQ-xxx)` (#304) -----------------------------------------

@pytest.mark.parametrize("raw, body, reqs", [
    ("판매오더 생성 (REQ-002)", "판매오더 생성", ["REQ-002"]),
    ("승인 워크플로 (REQ-001, REQ-003)", "승인 워크플로", ["REQ-001", "REQ-003"]),
    ("승인 워크플로(REQ-001,REQ-003)", "승인 워크플로", ["REQ-001", "REQ-003"]),
    ("승인 워크플로（REQ-001）", "승인 워크플로", ["REQ-001"]),
    ("판매오더 생성 (조회 전용)", "판매오더 생성 (조회 전용)", []),  # REQ 번호가 아닌 괄호는 꼬리표가 아니다
    ("REQ-002 로 따로 다룬다", "REQ-002 로 따로 다룬다", []),  # 항목 끝의 괄호만 꼬리표다
    ("판매오더 생성 (REQ-002) 제외", "판매오더 생성 (REQ-002) 제외", []),
])
def test_꼬리표를_항목_끝에서_떼어_번호_목록으로_낸다(raw, body, reqs):
    assert rg.split_excluded_tag(raw) == (body, reqs)


def test_scope_items_는_꼬리표를_뗀_항목을_낸다():
    items = rg.scope_items("- 하지 않는 것: 노출(IAM App, Role) (REQ-002), 외부 API\n  - 역분개·취소. (REQ-001)\n")
    assert list(items.values()) == ["노출(IAM App, Role)", "외부 API", "역분개·취소"]


def _tag_scope(*lines):
    return _scope_srs("- 하지 않는 것:\n" + "\n".join(f"  - {ln}" for ln in lines))


def test_꼬리표만_붙이거나_떼거나_바꾼_변경은_근거가_아니다():
    plain = _tag_scope("판매오더 생성·변경·삭제", "개발사양서 xlsx 작성")
    tagged = _tag_scope("판매오더 생성·변경·삭제 (REQ-002)", "개발사양서 xlsx 작성")
    retagged = _tag_scope("판매오더 생성·변경·삭제 (REQ-002, REQ-005)", "개발사양서 xlsx 작성")
    for base, head in ((plain, tagged), (tagged, plain), (tagged, retagged)):
        client = _srs_client(_with_sep_req(head), base_text=base, patch_row=SEP_ROW)
        assert _hint_reasons(rg.decide_pr(client, "o/r", 5)) == [], (base, head)


def test_꼬리표_있는_항목을_지우면_어느_REQ_의_항목인지_적는다():
    base = _tag_scope("판매오더 생성·변경·삭제 (REQ-002)", "개발사양서 xlsx 작성")
    head = _with_sep_req(_tag_scope("개발사양서 xlsx 작성"))
    (reason,) = _hint_reasons(rg.decide_pr(_srs_client(head, base_text=base, patch_row=SEP_ROW), "o/r", 5))
    assert '(b)' in reason and '"판매오더 생성·변경·삭제" (REQ-002(판매오더 조회 앱) 의 하지 않는 것)' in reason
    assert "(REQ-002)\"" not in reason


def test_꼬리표_번호가_여럿이면_모두_적고_없는_항목은_표시를_안_붙인다():
    base = _tag_scope("승인 워크플로 (REQ-001, REQ-002)", "외부 API 서비스")
    head = _with_sep_req(_tag_scope("개발사양서 xlsx 작성"))
    (reason,) = _hint_reasons(rg.decide_pr(_srs_client(head, base_text=base, patch_row=SEP_ROW), "o/r", 5))
    assert '"승인 워크플로" (REQ-001(회계전표 Excel 업로드 일괄 전기), REQ-002(판매오더 조회 앱) 의 하지 않는 것)' in reason
    assert '"외부 API 서비스"' in reason
    assert '"외부 API 서비스" (' not in reason


def test_꼬리표_없는_항목을_바꾸면_예전처럼_표시_없이_근거로_든다():
    base = _tag_scope("판매오더 생성·변경·삭제", "개발사양서 xlsx 작성")
    head = _with_sep_req(_tag_scope("개발사양서 xlsx 작성"))
    (reason,) = _hint_reasons(rg.decide_pr(_srs_client(head, base_text=base, patch_row=SEP_ROW), "o/r", 5))
    assert '"판매오더 생성·변경·삭제"' in reason and "의 하지 않는 것" not in reason


def test_엑셀_산출은_범위_절의_꼬리표를_내보내지_않는다():
    from checker import export

    text = (
        "# SRS\n\n버전: 0.1\n\n## 범위\n\n- 하지 않는 것:\n  - 회계전표 역분개 (REQ-001)\n\n"
        "## 요구사항\n\n| ID | Title | Status |\n|---|---|---|\n| REQ-001 | 회계전표 업로드 | New |\n\n"
        "### REQ-001 회계전표 업로드\n\n#### Short Description\n\n요약\n"
    )
    doc = export.parse_srs(text)
    flat = [c for row in doc.rows for c in row] + [v for d in doc.details.values() for v in d.values()]
    assert doc.rows == [["REQ-001", "회계전표 업로드", "New"]]
    assert not any("역분개" in c or "(REQ-001)" in c for c in flat)


def test_같은_본문이_다른_꼬리표로_두_번_나오면_번호를_합친다():
    entries = rg._scope_entries("- 하지 않는 것:\n  - 승인 워크플로 (REQ-001)\n  - 승인 워크플로 (REQ-002, REQ-001)\n")
    assert list(entries.values()) == [("승인 워크플로", ["REQ-001", "REQ-002"])]


def test_titled_id_제목_있음_다른_표에서_찾음_둘_다_없음(tmp_path):
    # 첫 표에 없으면 다음 표에서 찾고, DEV 번호는 같은 숫자의 REQ 제목을 쓴다
    assert rg.titled_id("REQ-002", {"REQ-002": "판매오더 조회 앱"}) == "REQ-002(판매오더 조회 앱)"
    assert rg.titled_id("REQ-2", {}, {"REQ-002": "판매오더 조회 앱"}) == "REQ-2(판매오더 조회 앱)"
    assert rg.titled_id("DEV-002", {"REQ-002": "판매오더 조회 앱"}) == "DEV-002(판매오더 조회 앱)"
    # 어느 표에도 없거나 제목이 비면 추측하지 않는다
    assert rg.titled_id("REQ-009", {"REQ-002": "판매오더 조회 앱"}) == "REQ-009(제목 미확인)"
    assert rg.titled_id("REQ-002", {"REQ-002": ""}) == "REQ-002(제목 미확인)"
