"""`checker.risk_gate` 의 `remembered` 기준(#1004)을 검증한다.

한 번 위험 판정(AI 리뷰 심각 지적·위험 경로·비밀정보)을 받은 PR 은 이후 커밋에서 사유가 사라져도, 작성자가 아닌
승인자가 마지막 커밋에 Approve 할 때까지 승인을 요구한다. 근거는 이전 SHA 에 봇이 단 `risk-gate` failure status 다.
"""
from __future__ import annotations

import base64
import json
from argparse import Namespace

import pytest

from checker import risk_gate as rg
from checker.ssot_approval import GhError

# conftest 의 "이전 위험 기록 없음" 대체를 끈다(이 모듈은 실제 경로를 시험한다).
REAL_RISK_HISTORY = True

REPO = "o/r"
BRANCH = "fix/745-stock"
CREATED = "2026-11-16T04:40:00Z"
OLD = "c" * 40  # 위험 판정을 받은 첫 커밋(강제 푸시로 덮임)
MID = "d" * 40
HEAD = "e" * 40
BOT = "github-actions[bot]"
RISKY_DESC = "[위험: ai_review] 이 PR 은 위험도가 높아 승인자의 Approve 가 필요하다."


def _b64(text):
    return {"content": base64.b64encode(text.encode("utf-8")).decode("ascii")}


def _status(state="failure", desc=RISKY_DESC, login=BOT, context="risk-gate"):
    return {"context": context, "state": state, "description": desc, "creator": {"login": login}}


class Fake:
    def __init__(self, responses):
        self.r = responses

    def _get(self, path):
        if path in self.r:
            v = self.r[path]
            if isinstance(v, Exception):
                raise v
            return v
        for key, v in self.r.items():
            if key.endswith("*") and path.startswith(key[:-1]):
                if isinstance(v, Exception):
                    raise v
                return v
        raise KeyError(path)

    get_json = get_all = lambda self, path, per_page=100: self._get(path)

    def get_json_or_none_404(self, path):
        try:
            return self._get(path)
        except KeyError:
            if "/contents/" in path:
                return None
            raise


def _client(*, commits=(HEAD,), activity=(), statuses=None, reviews=(), head_repo=REPO, author="bob", files=None,
            extra=None):
    r = {
        "repos/o/r/collaborators/*": {"permission": "write"},
        f"repos/o/r/pulls/5": {
            "user": {"login": author}, "base": {"ref": "main"}, "created_at": CREATED,
            "head": {"sha": HEAD, "ref": BRANCH, "repo": {"full_name": head_repo}},
        },
        "repos/o/r/pulls/5/files": files or [{"filename": "src/a.py", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+x"}],
        "repos/o/r/pulls/5/reviews": list(reviews),
        "repos/o/r/pulls/5/commits": [{"sha": c} for c in commits],
        f"repos/o/r/activity?ref=refs/heads/{BRANCH}&per_page=100": list(activity),
        f"repos/o/r/commits/{HEAD}/check-runs*": {"check_runs": []},
        f"repos/o/r/commits/{HEAD}/status?*": {"statuses": []},
        "repos/o/r/contents/.github/risk-gate.yaml?ref=main": _b64(""),
        "repos/o/r/contents/.github/ssot-approvers?ref=main": _b64("alice\n"),
    }
    for sha in {OLD, MID, HEAD, *commits}:
        r.setdefault(f"repos/o/r/commits/{sha}/statuses", [])
    for sha, items in (statuses or {}).items():
        r[f"repos/o/r/commits/{sha}/statuses"] = items
    r.update(extra or {})
    return Fake(r)


def _review(login, state, commit):
    return {"user": {"login": login}, "state": state, "commit_id": commit, "submitted_at": "2026-11-16T06:00:00Z"}


def _force_push(before, after, at="2026-11-16T05:01:23Z"):
    return {"activity_type": "force_push", "before": before, "after": after, "timestamp": at}


def _decide(client, **kw):
    return rg.decide_pr(client, REPO, 5, **kw)


# 사례 #745: 첫 커밋이 위험 판정(ai_review) → 강제 푸시로 덮음 → 새 head 는 사유 없음
def _case_745(**kw):
    return _client(
        commits=(HEAD,), activity=[_force_push(OLD, HEAD)], statuses={OLD: [_status()]}, **kw
    )


def test_옛_커밋의_위험_판정을_기억해_사유가_없어도_승인을_요구한다():
    result = _decide(_case_745())
    assert result["risk"] == "high" and result["requires_approval"] is True and result["approved"] is False
    assert "이전 커밋 ccccccc" in result["reasons"][0] and "AI 리뷰 심각 지적" in result["reasons"][0]
    assert "승인자가 마지막 커밋에서 봐야 한다" in result["reasons"][0]
    assert rg._exit_for(result) == 1
    assert "Approve 하십시오" in result["next"]


def test_승인자가_마지막_커밋에_approve_하면_통과한다():
    result = _decide(_case_745(reviews=[_review("alice", "APPROVED", HEAD)]))
    assert result["requires_approval"] is True and result["approved"] is True
    assert rg._exit_for(result) == 0


def test_작성자의_approve_는_여전히_요구한다():
    result = _decide(_case_745(reviews=[_review("bob", "APPROVED", HEAD)]))
    assert result["approved"] is False and rg._exit_for(result) == 1


def test_승인_뒤_새_커밋이_올라오면_다시_요구한다():
    client = _client(
        commits=(MID, HEAD), activity=[_force_push(OLD, MID)], statuses={OLD: [_status()]},
        reviews=[_review("alice", "APPROVED", MID)],
    )
    result = _decide(client)
    assert result["approved"] is False and result["stale_approvers"] == ["alice"]
    assert rg._exit_for(result) == 1


def test_PR_커밋_목록에_있는_이전_커밋의_기록도_본다():
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: [_status()]}))
    assert result["requires_approval"] is True and "이전 커밋 ccccccc" in result["reasons"][0]


def test_덧써서_통과가_된_커밋도_이력에_failure_가_남아_있으면_기억한다():
    # statuses 목록은 최신순 이력이다 — 같은 커밋에서 승인 뒤 success 로 덮어도 failure 가 남는다.
    history = [_status(state="success", desc="통과"), _status()]
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: history}))
    assert result["requires_approval"] is True


def test_같은_커밋에서_검사를_다시_돌려_지적을_지워도_기억한다():
    result = _decide(_client(commits=(HEAD,), statuses={HEAD: [_status(state="success", desc="통과"), _status()]}))
    assert "같은 커밋의 이전 검사" in result["reasons"][0]
    assert result["approved"] is False


def test_검사_진행_중이어서_난_failure_는_기억하지_않는다():
    desc = "이 PR 은 위험도가 높아 승인자의 Approve 가 필요하다. 이유와 다음 할 일은 PR 코멘트와 job 요약에 있다."
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: [_status(desc=desc)]}))
    assert result["risk"] == "low" and result["reasons"] == [] and rg._exit_for(result) == 0


def test_사유_코드가_없는_옛_failure_는_기억하지_않는다():
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: [_status(desc="")]}))
    assert result["risk"] == "low"


def test_기억_대상이_아닌_코드나_다른_context_는_기억하지_않는다():
    statuses = [
        _status(desc="[위험: checks] x"),
        _status(desc="[위험: size] x"),
        _status(context="ssot-approval"),
        _status(state="success"),
        _status(state="error"),
    ]
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: statuses}))
    assert result["risk"] == "low"


def test_봇이_아닌_계정이_단_failure_는_무시한다():
    result = _decide(_client(commits=(OLD, HEAD), statuses={OLD: [_status(login="bob")]}))
    assert result["risk"] == "low"


def test_PR_생성_전의_같은_브랜치_이름_이력은_무시한다():
    stale = "a" * 40
    activity = [_force_push(stale, HEAD, at="2026-11-10T00:00:00Z")]
    result = _decide(_client(activity=activity, statuses={stale: [_status()]}))
    assert result["risk"] == "low"


def test_생성_뒤_강제_푸시의_before_는_기억한다():
    result = _decide(_client(activity=[_force_push(OLD, HEAD, at=CREATED)], statuses={OLD: [_status(desc="[위험: paths,secret] x")]}))
    assert result["requires_approval"] is True
    assert "위험 경로 변경, 비밀정보" in result["reasons"][0]


def test_before_sha_인자도_본다():
    client = _client(statuses={OLD: [_status()]})
    assert _decide(client)["risk"] == "low"
    assert _decide(client, extra_shas=(OLD,))["requires_approval"] is True


def test_0으로_찬_before_sha_와_엉뚱한_값은_무시한다():
    client = _client()
    assert _decide(client, extra_shas=("0" * 40, "zzz", ""))["risk"] == "low"


def test_activity_조회가_실패하면_통과가_아니라_검사_불능():
    client = _client(extra={f"repos/o/r/activity?ref=refs/heads/{BRANCH}&per_page=100": GhError("boom")})
    with pytest.raises(GhError):
        _decide(client)


def test_statuses_조회가_실패하면_검사_불능():
    client = _client(commits=(OLD, HEAD), extra={f"repos/o/r/commits/{OLD}/statuses": GhError("boom")})
    with pytest.raises(GhError):
        _decide(client)


def test_commits_조회가_실패하면_검사_불능():
    with pytest.raises(GhError):
        _decide(_client(extra={"repos/o/r/pulls/5/commits": GhError("boom")}))


def test_SHA_가_상한을_넘으면_검사_불능():
    many = tuple(f"{i:040x}" for i in range(1, rg.MAX_HISTORY_SHAS + 2))
    with pytest.raises(GhError, match="상한"):
        _decide(_client(commits=many))


def test_SHA_가_상한_이하면_읽는다():
    many = tuple(f"{i:040x}" for i in range(1, rg.MAX_HISTORY_SHAS + 1))
    assert _decide(_client(commits=many))["risk"] == "low"


def test_activity_가_한_쪽을_꽉_채우면_다_못_읽었으니_검사_불능():
    activity = [_force_push(OLD, HEAD)] * 100
    with pytest.raises(GhError):
        _decide(_client(activity=activity))


def test_다른_저장소_head_는_강제_푸시_기록을_못_읽으니_검사_불능():
    with pytest.raises(GhError, match="다른 저장소"):
        _decide(_client(head_repo="fork/r"))


def test_종료코드는_판정_불가_2():
    client = _client(extra={"repos/o/r/pulls/5/commits": GhError("boom")})
    args = Namespace(repo=REPO, pr=5, wait_checks=0, wait_interval=20, before_sha="")
    import checker.risk_gate as mod

    original = mod.GhClient
    mod.GhClient = lambda: client
    try:
        assert mod.cmd_check_pr(args) == mod.EXIT_UNKNOWN
    finally:
        mod.GhClient = original


def test_위험_판정_결과가_기억_대상_사유_코드를_낸다():
    config = "max_changed_lines: 5\nsize_gate: true\n"
    risky = _client(
        files=[{"filename": "docs/ssot/SRS.md", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+x"}],
        extra={"repos/o/r/contents/.github/risk-gate.yaml?ref=main": _b64(config)},
    )
    result = _decide(risky)
    assert result["risk"] == "high" and result["risk_codes"] == ["paths"]
    # 기억 사유 자체와 참고·진행 중 대기는 코드가 아니다.
    assert rg.risk_codes([rg.Finding("remembered", "x"), rg.Finding("ai_review", "w", waiting=True),
                          rg.Finding("checks", "c"), rg.Finding("secret", "s", note=True)]) == []
    assert rg.risk_codes([rg.Finding("ai_review", "a"), rg.Finding("ai_review", "b"), rg.Finding("secret", "s")]) == [
        "ai_review", "secret",
    ]


def test_description_의_사유_코드를_읽는다():
    assert rg.parse_risk_codes("[위험: ai_review,paths] 이 PR 은") == ["ai_review", "paths"]
    assert rg.parse_risk_codes("[위험: unknown,secret] x") == ["secret"]
    assert rg.parse_risk_codes("앞에 글자 [위험: paths]") == []
    assert rg.parse_risk_codes("") == [] and rg.parse_risk_codes(None) == []


def test_위험_결과_json_에_risk_codes_가_직렬화된다():
    assert json.dumps(_decide(_case_745()), ensure_ascii=False)
