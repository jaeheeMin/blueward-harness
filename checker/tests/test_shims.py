"""훅과 GitHub Actions 두 껍데기가 쓰는 부분.

둘이 하는 일은 같다 — 기준 폴더를 찾고, 엔진을 부르고, 종료코드로 분기한다. 끝만 다르다.
훅은 저장을 막고 Actions 는 PR 을 실패시킨다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main

HOOK = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "hooks" / "pre_write_guard.py"


# --- --auto ---------------------------------------------------------------

def test_auto_는_기준_폴더를_스스로_찾는다(capsys, sample):
    code = main(["--auto", str(sample / "docs/제안서/제안서최종.md")])
    out = json.loads(capsys.readouterr().out)
    assert code == EXIT_VIOLATION
    assert out["files"][0]["type"] == "제안서"


def test_auto_는_기준_폴더_밖을_관할_밖으로_둔다(capsys, sample, tmp_path):
    outside = tmp_path / "아무데나.md"
    outside.write_text("# 제목\n", encoding="utf-8")
    code = main(["--auto", str(outside)])
    out = json.loads(capsys.readouterr().out)
    assert code == EXIT_PASS
    assert out["summary"]["out_of_scope"] == 1


def test_rules_와_auto_를_둘_다_주면_거부한다(sample):
    with pytest.raises(SystemExit):
        main(["--auto", "--rules", "x", str(sample / "README.md")])


def test_둘_다_안_주어도_거부한다():
    with pytest.raises(SystemExit):
        main([])


# --- PR 코멘트 렌더링 -----------------------------------------------------

def _render(report: dict, code: int) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from render_report import render

    return render(report, code)


def test_위반이_있으면_템플릿_경로가_코멘트에_나온다():
    report = {
        "summary": {"scoped": 1, "passed": 0, "violations": 1, "out_of_scope": 0},
        "files": [{
            "file": "docs/제안서/틀림.md", "type": "제안서",
            "template": "../templates/제안서.md", "status": "violation",
            "violations": [{"rule": "filename", "expected": "^x$",
                            "actual": "틀림.md", "message": "파일 이름이 다르다"}],
        }],
    }
    text = _render(report, EXIT_VIOLATION)
    assert "파일 이름이 다르다" in text
    assert "../templates/제안서.md" in text


def test_설정_오류는_문서_문제가_아니라고_말한다():
    """받는 사람이 다르다. 문서를 올린 팀원은 규칙 파일을 고칠 수 없다."""
    text = _render({"status": "config_error", "message": "관할이 겹친다"}, EXIT_CONFIG_ERROR)
    assert "문서의 문제가 아닙니다" in text
    assert "관할이 겹친다" in text


def test_검사할_것이_없으면_그렇게_말한다():
    text = _render({"summary": {"scoped": 0, "passed": 0, "violations": 0, "out_of_scope": 3},
                    "files": []}, EXIT_PASS)
    assert "관할 밖" in text


# --- 훅 -------------------------------------------------------------------

# 훅은 기본으로 엔진을 GitHub 에서 uvx 로 받아 온다(#12). 이 저장소 자체를 검사하는
# 테스트가 매번 네트워크를 타면 느리고 오프라인에서 깨지므로, 이 워크트리를 엔진으로
# 쓰도록 DOC_GUARD_ENGINE 을 지정한다 — uvx 가 로컬 경로를 그대로 --from 에 받는다.
ENGINE_ROOT = Path(__file__).resolve().parents[2]


def run_hook(payload: dict) -> tuple[int, dict | None]:
    env = {**os.environ, "DOC_GUARD_ENGINE": str(ENGINE_ROOT)}
    done = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", env=env,
    )
    if not done.stdout.strip():
        return done.returncode, None
    return done.returncode, json.loads(done.stdout)


def decision(out: dict | None) -> str | None:
    if out is None:
        return None
    return out["hookSpecificOutput"]["permissionDecision"]


def test_훅이_템플릿을_벗어난_문서를_막는다(sample):
    """저장 전에 가로채 거절하고, 무엇을 어겼는지와 쓸 템플릿을 보여준다."""
    target = sample / "docs/제안서/20260921_새_제안서.md"
    _, out = run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": "# 새 제안서\n\n## 개요\n내용\n"},
    })
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "일정" in reason          # 빠진 절을 짚는다
    assert "제안서.md" in reason      # 쓸 템플릿을 알려준다


def test_훅이_규칙에_맞는_문서는_통과시킨다(sample):
    template = (sample / "templates/제안서.md").read_text(encoding="utf-8")
    target = sample / "docs/제안서/20260921_새_제안서.md"
    code, out = run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": str(target), "content": template},
    })
    assert code == 0
    assert out is None  # 아무 말도 하지 않는 것이 통과다


def test_훅이_관할_밖_파일에는_관여하지_않는다(sample):
    code, out = run_hook({
        "tool_name": "Write",
        "tool_input": {"file_path": str(sample / "README.md"), "content": "아무거나"},
    })
    assert code == 0 and out is None


def test_훅이_Edit_의_최종_모습을_만들어_검사한다(sample):
    """Edit 은 바꿀 조각만 오므로 디스크 내용에 치환을 적용해 결과를 얻는다.

    이것이 없으면 Edit 으로 고친 문서는 검사되지 않는 구멍이 생긴다.
    """
    target = sample / "docs/제안서/20260921_로그인_제안서.md"
    code, out = run_hook({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target), "old_string": "## 일정", "new_string": "## 일자"},
    })
    assert decision(out) == "deny"
    assert "일정" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_훅이_다른_도구에는_관여하지_않는다(sample):
    code, out = run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert code == 0 and out is None
