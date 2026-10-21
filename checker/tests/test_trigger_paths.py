"""호출 워크플로의 트리거 `paths` 와 PR 검사 concurrency 를 검증한다(#411).

Actions 분을 아끼려고 PR 내용과 무관하게 매번 돌던 검사를 파일 범위로 좁혔다. 좁힌 범위에서 검사 대상이
빠지면 검사가 안 돌고 통과처럼 보이므로(원칙 7), doc-guard 의 paths 가 엔진이 실제로 보는 범위를 덮는지 본다.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REUSABLE = ROOT / ".github" / "workflows"
CALLERS = ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton" / "dot-github" / "workflows"
SKELETON = ROOT / "plugins" / "harness" / "skills" / "scaffold" / "skeleton"


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if True in data:  # YAML 1.1 에서 `on` 은 True 로 읽힌다.
        data["on"] = data.pop(True)
    return data


def _matches(pattern: str, path: str) -> bool:
    """GitHub paths glob 의 필요한 부분만: `**/` 는 0개 이상의 폴더, `**` 는 뒤 전부, `*` 는 `/` 를 넘지 않는다."""
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            regex += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


def _triggered(paths: list[str], path: str) -> bool:
    return any(_matches(p, path) for p in paths)


# --- ssot-approval ------------------------------------------------------------


def test_ssot_approval_caller_는_SRS_를_바꾼_PR_에만_뜨고_리뷰와_push_는_그대로():
    on = _load(CALLERS / "ssot-approval.yml")["on"]
    assert on["pull_request"]["paths"] == ["docs/ssot/**"]
    assert "paths" not in on["pull_request_review"]
    assert on["push"] == {"branches": ["main"]}
    assert _triggered(on["pull_request"]["paths"], "docs/ssot/SRS.md")
    assert not _triggered(on["pull_request"]["paths"], "docs/spec/DEV-001-a.md")


# --- doc-guard ----------------------------------------------------------------


def test_doc_guard_paths_는_PR_과_push_가_같다():
    on = _load(CALLERS / "doc-guard.yml")["on"]
    assert on["pull_request"]["paths"] == on["push"]["paths"]
    assert on["push"]["branches"] == ["main"]


def test_doc_guard_paths_는_엔진이_보는_파일을_덮는다():
    paths = _load(CALLERS / "doc-guard.yml")["on"]["pull_request"]["paths"]
    # 문서·양식·규칙·진행 원장·교차 검사
    for f in (
        "docs/ssot/SRS.md", "docs/spec/DEV-001-a.md", "templates/forms/개발사양서.xlsx",
        "rules/spec.yaml", "rules/cross-checks/switches.yaml", "audit/ledger/ZPROG.md", "audit/changes/20261021-a.md",
    ):
        assert _triggered(paths, f), f
    # 판 있는 산출 파일(판 번호 겹침 검사)은 폴더와 무관
    for f in ("out/개발사양서_v0.1.xlsx", "개발사양서_v0.2.docx", "a/b/발표_v0.3.pptx"):
        assert _triggered(paths, f), f
    # 코드 규칙(CR-001~)이 보는 확장자는 폴더와 무관하게 root 파일까지 덮는다
    code_checks = yaml.safe_load((ROOT / "checker" / "code_checks.yaml").read_text(encoding="utf-8"))
    for lang, info in code_checks["languages"].items():
        for suffix in info["suffixes"]:
            for f in (f"src/a/b{suffix}", f"x{suffix}", f"abap/zcl_a{suffix}"):
                assert _triggered(paths, f), (lang, f)


def test_doc_guard_paths_는_검사_대상이_아닌_파일만_바뀐_PR_에서는_안_뜬다():
    paths = _load(CALLERS / "doc-guard.yml")["on"]["pull_request"]["paths"]
    for f in ("README.md", ".github/risk-gate.yaml", "package.json", "src/logo.png", "env/README.md"):
        assert not _triggered(paths, f), f


def test_skeleton_rules_의_관할은_doc_guard_paths_안에_있다():
    paths = _load(CALLERS / "doc-guard.yml")["on"]["pull_request"]["paths"]
    for rule in (SKELETON / "rules").glob("*.yaml"):
        data = yaml.safe_load(rule.read_text(encoding="utf-8"))
        scope = data.get("관할")
        assert scope, rule.name
        sample = scope.replace("**", "x.md").replace("*", "x")
        assert _triggered(paths, sample), (rule.name, scope)


# --- ai-review ----------------------------------------------------------------


def test_ai_review_caller_paths_와_risk_gate_yaml_의_ai_review_paths_는_같은_뜻():
    caller = _load(CALLERS / "ai-review.yml")["on"]["pull_request"]
    assert caller["paths"] == ["src/**"]
    cfg = yaml.safe_load((SKELETON / "dot-github" / "risk-gate.yaml").read_text(encoding="utf-8"))
    assert cfg["ai_review_paths"] == ["src/"]
    # 같은 뜻: caller 의 `X/**` 는 설정의 `X/` 접두어다.
    assert [p[: -len("**")] for p in caller["paths"]] == cfg["ai_review_paths"]


def test_scaffold_risk_gate_yaml_은_엔진이_읽을_수_있다():
    from checker import risk_gate

    text = (SKELETON / "dot-github" / "risk-gate.yaml").read_text(encoding="utf-8")
    assert risk_gate.load_config(text)["ai_review_paths"] == ["src/"]


# --- concurrency --------------------------------------------------------------


def test_PR_검사는_PR_번호_단위로_앞_실행을_취소한다():
    ssot = _load(REUSABLE / "ssot-approval.yml")["jobs"]["check"]
    assert ssot["concurrency"] == {
        "group": "ssot-approval-${{ github.event.pull_request.number }}", "cancel-in-progress": True}
    # push(after-merge) 에는 concurrency 를 두지 않는다 — 병합 뒤 감시는 취소되면 안 된다.
    assert "concurrency" not in _load(REUSABLE / "ssot-approval.yml")["jobs"]["after-merge"]


def test_PR_과_push_를_같이_받는_검사는_push_를_취소하지_않는다():
    for name, job_id in (("doc-guard", "check"), ("gitleaks", "gitleaks")):
        job = _load(REUSABLE / f"{name}.yml")["jobs"][job_id]
        assert job["concurrency"] == {
            "group": f"{name}-${{{{ github.event.pull_request.number || github.sha }}}}",
            "cancel-in-progress": "${{ github.event_name == 'pull_request' }}",
        }
