"""`/scaffold` 가 부르는 `scaffold.py` 를 검증한다.

`scaffold.py` 는 `checker` 패키지 밖, `plugins/harness/skills/scaffold/` 에
산다 — 플러그인 훅과 마찬가지로 엔진과는 별도로 설치되는 자리이기 때문이다.
그래서 평범한 `import` 대신 파일 경로로 직접 불러온다.

여기서 만든 구조가 검사 엔진과 실제로 맞물리는지까지 함께 확인한다. 구조만
맞고 검사기가 그 구조를 읽지 못하면 스캐폴딩은 겉모습만 흉내 낸 것이다.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main

SCAFFOLD_PY = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "harness"
    / "skills"
    / "scaffold"
    / "scaffold.py"
)


def _load_scaffold_module():
    spec = importlib.util.spec_from_file_location("doc_guard_scaffold", SCAFFOLD_PY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


scaffold_mod = _load_scaffold_module()
scaffold = scaffold_mod.scaffold

# 스켈레톤의 치환 자리표시자. 워크플로의 `${{ ... }}` 표현식은 자리표시자가 아니다.
_PLACEHOLDER = re.compile(r"(?<!\$)\{\{")

EXPECTED_FILES = {
    "CLAUDE.md",
    "docs/ssot/PRD.md",
    "docs/spec/.gitkeep",
    "templates/README.md",
    "templates/harness/PRD.md",
    "templates/harness/spec.md",
    "templates/harness/audit-change.md",
    "templates/harness/audit-ledger.md",
    "rules/README.md",
    "rules/ssot.yaml",
    "rules/spec.yaml",
    "rules/audit-changes.yaml",
    "rules/audit-ledger.yaml",
    "conventions/README.md",
    "audit/README.md",
    "audit/changes/.gitkeep",
    "audit/ledger/.gitkeep",
    "env/README.md",
    ".github/workflows/doc-guard.yml",
    ".github/workflows/ssot-approval.yml",
    ".github/ssot-approvers",
    ".github/risk-gate.yaml",
    ".github/workflows/risk-gate.yml",
    ".github/workflows/ai-review.yml",
    ".claude/settings.json",
}


def test_예상하는_파일을_모두_만들고_치환한다(tmp_path: Path):
    result = scaffold(tmp_path, "블루워드", "테스트프로젝트", False)

    assert set(result["created"]) == EXPECTED_FILES
    assert result["skipped"] == []
    assert result["dry_run"] is False

    # dot-github 는 실제로 만들 때 .github 로 바뀐다.
    assert (tmp_path / ".github" / "workflows" / "doc-guard.yml").is_file()
    assert not (tmp_path / "dot-github").exists()

    for rel in EXPECTED_FILES:
        path = tmp_path / rel
        assert path.is_file(), f"{rel} 이 만들어지지 않았다"
        text = path.read_text(encoding="utf-8")
        assert not _PLACEHOLDER.search(text), f"{rel} 에 치환되지 않은 자리표시자가 남아 있다"

    claude_md = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "블루워드 테스트프로젝트" in claude_md
    prd = (tmp_path / "docs" / "ssot" / "PRD.md").read_text(encoding="utf-8")
    assert "테스트프로젝트 PRD" in prd

    settings_path = tmp_path / ".claude" / "settings.json"
    settings_text = settings_path.read_text(encoding="utf-8")
    assert json.loads(settings_text) == {
        "enabledPlugins": {"harness@blueward-harness": True},
        "extraKnownMarketplaces": {
            "blueward-harness": {
                "source": {"source": "github", "repo": "jaeheeMin/blueward-harness"},
                "autoUpdate": True,
            }
        },
    }
    # BOM 없이, 끝 줄바꿈이 있게 쓴다.
    assert not settings_text.startswith("﻿")
    assert settings_text.endswith("\n")


def test_승인자를_주면_ssot_approvers_파일에_한_줄씩_적는다(tmp_path: Path):
    result = scaffold(tmp_path, "고객사", "프로젝트", False, ["alice", "@bob"])

    assert set(result["created"]) == EXPECTED_FILES
    text = (tmp_path / ".github" / "ssot-approvers").read_text(encoding="utf-8")
    assert "alice" in text
    assert "@bob" in text
    assert "{{" not in text


def test_위험도_게이트_기준_파일과_워크플로를_만든다(tmp_path: Path):
    """#102: 새 Project Repository 에 위험도 게이트가 기본으로 들어간다."""
    from checker.risk_gate import DEFAULT_CONFIG, OWN_CHECK_NAME, load_config

    scaffold(tmp_path, "고객사", "프로젝트", False)

    # 기준 파일은 엔진이 그대로 읽히고, 값은 엔진 기본값과 같다(스켈레톤과 엔진이 어긋나지 않게).
    text = (tmp_path / ".github" / "risk-gate.yaml").read_text(encoding="utf-8")
    assert "{{" not in text
    assert load_config(text) == DEFAULT_CONFIG

    # 호출 워크플로의 job id 는 게이트가 자기 check run 을 알아보는 이름과 같아야 교착이 없다.
    workflow = (tmp_path / ".github" / "workflows" / "risk-gate.yml").read_text(encoding="utf-8")
    assert f"\n  {OWN_CHECK_NAME}:\n    uses: jaeheeMin/blueward-harness/.github/workflows/risk-gate.yml@main" in workflow
    for trigger in ("pull_request:", "pull_request_review:", "push:"):
        assert trigger in workflow
    for permission in ("contents: read", "pull-requests: write", "issues: write", "checks: read", "statuses: read"):
        assert permission in workflow


def test_ai_review_호출_워크플로를_만들고_기본은_꺼져_있다(tmp_path: Path):
    """#125: job id 는 ai-review(risk gate 가 읽는 이름), 시크릿을 넘기고, 기준 파일은 꺼진 채다."""
    import yaml

    from checker.risk_gate import AI_REVIEW_CHECK_NAME, load_config

    scaffold(tmp_path, "고객사", "프로젝트", False)

    text = (tmp_path / ".github" / "workflows" / "ai-review.yml").read_text(encoding="utf-8")
    assert not _PLACEHOLDER.search(text)
    data = yaml.safe_load(text)
    on = data.get("on", data.get(True))
    assert set(on["pull_request"]["types"]) == {"opened", "synchronize", "reopened", "ready_for_review"}
    assert list(data["jobs"]) == [AI_REVIEW_CHECK_NAME]
    job = data["jobs"][AI_REVIEW_CHECK_NAME]
    assert job["uses"] == "jaeheeMin/blueward-harness/.github/workflows/ai-review.yml@main"
    assert job["secrets"] == {"CLAUDE_CODE_OAUTH_TOKEN": "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"}
    assert job["permissions"] == {
        "contents": "read", "pull-requests": "write", "issues": "read", "id-token": "write"}

    risk = (tmp_path / ".github" / "risk-gate.yaml").read_text(encoding="utf-8")
    assert load_config(risk)["ai_review"] is False
    assert "gh secret set CLAUDE_CODE_OAUTH_TOKEN" in risk and "claude setup-token" in risk


def test_승인자를_안_주면_ssot_approvers_는_주석만_남는다(tmp_path: Path):
    scaffold(tmp_path, "고객사", "프로젝트", False)

    text = (tmp_path / ".github" / "ssot-approvers").read_text(encoding="utf-8")
    assert "{{" not in text
    non_comment_lines = [
        line for line in text.splitlines() if line.strip() and not line.strip().startswith("#")
    ]
    assert non_comment_lines == []


def test_두번째_실행은_아무것도_만들지_않고_기존_파일을_보존한다(tmp_path: Path):
    first = scaffold(tmp_path, "고객사A", "프로젝트A", False)
    assert first["created"]

    # 사람이 이미 손댄 것처럼 하나를 고쳐 둔다.
    claude_md = tmp_path / "CLAUDE.md"
    edited = "# 사람이 직접 고친 내용\n"
    claude_md.write_text(edited, encoding="utf-8")

    second = scaffold(tmp_path, "고객사B", "프로젝트B", False)

    assert second["created"] == []
    assert set(second["skipped"]) == EXPECTED_FILES
    # 덮어쓰지 않았어야 한다.
    assert claude_md.read_text(encoding="utf-8") == edited


def test_dry_run은_아무것도_만들지_않는다(tmp_path: Path):
    result = scaffold(tmp_path, "고객사", "프로젝트", True)

    assert set(result["created"]) == EXPECTED_FILES
    assert result["dry_run"] is True
    # 폴더 자체가 생기지 않아야 한다.
    assert list(tmp_path.iterdir()) == []


# --- .claude/settings.json 병합 ---------------------------------------------

EXPECTED_ENABLED_PLUGINS = {"harness@blueward-harness": True}
EXPECTED_MARKETPLACES = {
    "blueward-harness": {
        "source": {"source": "github", "repo": "jaeheeMin/blueward-harness"},
        "autoUpdate": True,
    }
}
OLD_MARKETPLACE_ENTRY = {"source": {"source": "github", "repo": "jaeheeMin/blueward-harness"}}


def _write_settings(tmp_path: Path, data: dict | str) -> Path:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        settings_path.write_text(data, encoding="utf-8")
    else:
        settings_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return settings_path


def test_기존_settings_json에_다른_키가_있으면_보존하며_두_키만_추가한다(tmp_path: Path):
    existing = {"otherKey": "손대면 안 된다", "permissions": {"allow": ["Bash(git:*)"]}}
    settings_path = _write_settings(tmp_path, existing)

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == [".claude/settings.json"]
    assert result["warnings"] == []
    assert ".claude/settings.json" not in result["created"]

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["otherKey"] == "손대면 안 된다"
    assert data["permissions"] == {"allow": ["Bash(git:*)"]}
    assert data["enabledPlugins"] == EXPECTED_ENABLED_PLUGINS
    assert data["extraKnownMarketplaces"] == EXPECTED_MARKETPLACES
    # 기존 키 순서가 그대로 유지되고 새 키는 끝에 붙는다.
    assert list(data.keys())[:2] == ["otherKey", "permissions"]


def test_settings_json에_BOM이_있어도_합친다(tmp_path: Path):
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"otherKey": 1}), encoding="utf-8-sig")

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == [".claude/settings.json"]
    assert result["warnings"] == []
    raw = settings_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert data["otherKey"] == 1
    assert data["enabledPlugins"] == EXPECTED_ENABLED_PLUGINS


def test_settings_json에_이미_같은_값이_있으면_아무것도_안_바꾼다(tmp_path: Path):
    existing = {
        "enabledPlugins": EXPECTED_ENABLED_PLUGINS,
        "extraKnownMarketplaces": EXPECTED_MARKETPLACES,
    }
    settings_path = _write_settings(tmp_path, existing)
    original_text = settings_path.read_text(encoding="utf-8")

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == []
    assert result["warnings"] == []
    assert ".claude/settings.json" in result["skipped"]
    assert settings_path.read_text(encoding="utf-8") == original_text


def test_settings_json이_충돌하는_값이면_안_바꾸고_경고한다(tmp_path: Path):
    existing = {"enabledPlugins": {"harness@blueward-harness": False}}
    settings_path = _write_settings(tmp_path, existing)
    original_text = settings_path.read_text(encoding="utf-8")

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == []
    assert ".claude/settings.json" in result["skipped"]
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["path"] == ".claude/settings.json"
    assert "harness@blueward-harness" in result["warnings"][0]["message"]
    # 손대지 않았어야 한다.
    assert settings_path.read_text(encoding="utf-8") == original_text


def test_예전_scaffold_설정에는_autoUpdate만_채운다(tmp_path: Path):
    existing = {
        "enabledPlugins": {"harness@blueward-harness": True},
        "extraKnownMarketplaces": {"blueward-harness": dict(OLD_MARKETPLACE_ENTRY)},
    }
    settings_path = _write_settings(tmp_path, existing)

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == [".claude/settings.json"]
    assert result["warnings"] == []
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert data["extraKnownMarketplaces"] == EXPECTED_MARKETPLACES


def test_autoUpdate를_false로_둔_설정은_안_바꾸고_경고한다(tmp_path: Path):
    entry = dict(OLD_MARKETPLACE_ENTRY, autoUpdate=False)
    existing = {
        "enabledPlugins": {"harness@blueward-harness": True},
        "extraKnownMarketplaces": {"blueward-harness": entry},
    }
    settings_path = _write_settings(tmp_path, existing)
    original_text = settings_path.read_text(encoding="utf-8")

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == []
    assert len(result["warnings"]) == 1
    assert "autoUpdate" in result["warnings"][0]["message"]
    assert settings_path.read_text(encoding="utf-8") == original_text


def test_settings_json이_깨진_json이면_안_바꾸고_경고한다(tmp_path: Path):
    settings_path = _write_settings(tmp_path, "{ 이건 JSON 이 아니다")
    original_text = settings_path.read_text(encoding="utf-8")

    result = scaffold(tmp_path, "고객사", "프로젝트", False)

    assert result["merged"] == []
    assert ".claude/settings.json" in result["skipped"]
    assert len(result["warnings"]) == 1
    assert result["warnings"][0]["path"] == ".claude/settings.json"
    assert settings_path.read_text(encoding="utf-8") == original_text


# --- 검사 엔진과의 통합 -----------------------------------------------------

def _run_auto(capsys, *paths: Path) -> tuple[int, dict]:
    import json

    code = main(["--auto", *[str(p) for p in paths]])
    return code, json.loads(capsys.readouterr().out)


def test_스캐폴딩한_구조를_검사기가_그대로_읽는다(tmp_path: Path, capsys):
    scaffold(tmp_path, "고객사", "프로젝트", False)
    prd = tmp_path / "docs" / "ssot" / "PRD.md"

    code, out = _run_auto(capsys, prd)
    assert code == EXIT_PASS
    assert out["summary"]["scoped"] == 1
    assert out["summary"]["passed"] == 1
    assert out["summary"]["violations"] == 0

    # 이름을 바꾼 버전은 rules/ssot.yaml 의 filename 규칙을 어긴다.
    prd_v2 = prd.parent / "PRD_v2.md"
    prd_v2.write_text(prd.read_text(encoding="utf-8"), encoding="utf-8")

    code, out = _run_auto(capsys, prd_v2)
    assert code == EXIT_VIOLATION
    assert out["summary"]["violations"] == 1
    assert out["files"][0]["violations"][0]["rule"] == "filename"

    # audit/README.md 처럼 어떤 관할에도 안 걸리는 파일은 관할 밖으로 조용히
    # 지나가야 한다. 죽지 않는다.
    audit_readme = tmp_path / "audit" / "README.md"
    code, out = _run_auto(capsys, audit_readme)
    assert code == EXIT_PASS
    assert out["summary"]["out_of_scope"] == 1
    assert out["summary"]["scoped"] == 0
