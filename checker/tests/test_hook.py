"""설치된 플러그인 레이아웃에서 훅이 실제로 동작하는지 확인한다.

`test_shims.py` 는 이 저장소 안에서 훅 스크립트를 직접 부른다. 그것만으로는 #12 가
잡은 결함 — 마켓플레이스로 설치된 캐시에는 `plugins/harness/` 만 들어가고
`checker/` 나 `pyproject.toml` 은 따라오지 않는다 — 를 재현하지 못한다. 저장소
안에서 돌리면 옛 코드도 `sys.path` 트릭으로 `checker` 를 찾아버려 통과해 버린다.

그래서 여기서는 `plugins/harness/` 를 저장소 **바깥** 임시 폴더로 복사해 설치본을
흉내 내고, 그 전제(엔진이 따라오지 않았다)를 스스로 확인한 뒤 그 복사본의 훅을
서브프로세스로 부른다.

엔진은 실제로 GitHub 에서 받지 않는다. `DOC_GUARD_ENGINE` 을 이 워크트리로 지정해
`uvx` 가 로컬 소스로 설치하게 한다 — 네트워크 없이 빠르고, uv 캐시도 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = ENGINE_ROOT / "plugins" / "harness"

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv 가 없으면 엔진을 받아 실행할 수 없다"
)

PROPOSAL_RULES = """템플릿: ../templates/제안서.md
관할: "docs/제안서/**"

규칙:
  - 종류: required_sections
"""

PROPOSAL_TEMPLATE = "# 제안서\n\n## 개요\n\n## 일정\n"

BROKEN_RULES = "이것은: [부서진, yaml\n"

# 한글이 겹으로 섞인 경로(#14)를 재현할 때 쓰는 최소 규칙. 템플릿을 읽는 규칙이
# 아니므로(filename) '템플릿' 없이도 성립한다.
SSOT_RULES = r"""관할: "docs/ssot/**"

규칙:
  - 종류: filename
    패턴: '^PRD\.md$'
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def installed_hook(tmp_path_factory) -> Path:
    """`plugins/harness/` 를 저장소 밖으로 복사해 설치본을 흉내 낸다."""
    dest_parent = tmp_path_factory.mktemp("harness-installed")
    dest = dest_parent / "harness"
    shutil.copytree(PLUGIN_SRC, dest)

    # 설치본의 전제를 스스로 확인한다 — 엔진(checker)도 pyproject.toml 도 따라오지
    # 않았다. 이것이 어긋나면 이 테스트는 옛 결함을 재현하지 못하고 통과해 버린다.
    assert not (dest / "checker").exists()
    assert not (dest_parent / "pyproject.toml").exists()
    assert not (dest_parent.parent / "pyproject.toml").exists()

    return dest / "hooks" / "pre_write_guard.py"


@pytest.fixture()
def standards_root(tmp_path) -> Path:
    """`templates/` 와 `rules/` 와 `docs/` 를 든 가짜 기준 폴더."""
    root = tmp_path / "회사"
    _write(root / "templates" / "제안서.md", PROPOSAL_TEMPLATE)
    _write(root / "rules" / "제안서.yaml", PROPOSAL_RULES)
    (root / "docs" / "제안서").mkdir(parents=True)
    return root


@pytest.fixture()
def ssot_standards_root(tmp_path) -> Path:
    """`고객사/프로젝트` 처럼 한글 폴더가 겹으로 이어지는 기준 폴더(#14).

    `standards_root` 픽스처는 기준 폴더 이름 하나만 한글이다. 여기서는 그 위
    폴더도 한글로 두어, 실제 프로젝트 저장소에서 흔한 모양을 흉내 낸다.
    """
    root = tmp_path / "고객사" / "프로젝트"
    (root / "templates").mkdir(parents=True)
    _write(root / "rules" / "ssot.yaml", SSOT_RULES)
    (root / "docs" / "ssot").mkdir(parents=True)
    return root


def run_hook(hook: Path, payload: dict, engine: str) -> tuple[int, dict | None]:
    env = {**os.environ, "DOC_GUARD_ENGINE": engine}
    done = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=180,
    )
    if not done.stdout.strip():
        return done.returncode, None
    return done.returncode, json.loads(done.stdout)


def run_hook_bytes(hook: Path, payload: dict, engine: str) -> tuple[int, dict | None]:
    """`run_hook` 과 같지만 stdin 을 UTF-8 바이트로 그대로 보내고, 파이썬이 스스로
    UTF-8 을 강제하는 환경변수 없이 부른다(#14).

    Windows 콘솔 기본 코드페이지(cp949)에서 한글 경로가 깨지는 상황을 그대로
    재현하려면 두 조건이 함께 있어야 한다 — PYTHONUTF8 · PYTHONIOENCODING ·
    PYTHONLEGACYWINDOWSSTDIO 가 없어 파이썬이 로캘 기본 인코딩을 쓰고, 그런데도
    보내는 표준입력은 실제 팀원 PC 처럼 진짜 UTF-8 바이트여야 한다. `ensure_ascii`
    를 꺼서 한글이 `\\uXXXX` 로 도망가지 않고 원래 바이트 그대로 나가게 한다.
    """
    env = os.environ.copy()
    for key in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO"):
        env.pop(key, None)
    env["DOC_GUARD_ENGINE"] = engine
    done = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True, env=env, timeout=180,
    )
    stdout = done.stdout.decode("utf-8", errors="replace")
    if not stdout.strip():
        return done.returncode, None
    return done.returncode, json.loads(stdout)


def decision(out: dict | None) -> str | None:
    if out is None:
        return None
    return out["hookSpecificOutput"]["permissionDecision"]


def _write_payload(path: Path, content: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def test_설치본에서도_위반_문서를_막는다(installed_hook, standards_root):
    target = standards_root / "docs" / "제안서" / "위반.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, "# 제안서\n\n## 개요\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    assert "일정" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_설치본에서도_규칙에_맞는_문서는_통과시킨다(installed_hook, standards_root):
    target = standards_root / "docs" / "제안서" / "통과.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, PROPOSAL_TEMPLATE), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_기준_폴더_밖의_파일은_관할_밖이라_통과시킨다(installed_hook, tmp_path):
    outside = tmp_path / "아무데나.md"
    code, out = run_hook(installed_hook, _write_payload(outside, "아무거나"), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_텍스트가_아닌_확장자는_관여하지_않는다(installed_hook, standards_root):
    target = standards_root / "docs" / "제안서" / "파일.docx"
    code, out = run_hook(installed_hook, _write_payload(target, "아무거나"), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_엔진을_받을_수_없으면_통과가_아니라_거절한다(installed_hook, standards_root, tmp_path):
    """CLAUDE.md 원칙 7: '검사를 못 했다' 를 '통과' 로 뭉개지 않는다."""
    target = standards_root / "docs" / "제안서" / "아무.md"
    missing_engine = str(tmp_path / "존재하지-않는-경로")
    code, out = run_hook(installed_hook, _write_payload(target, "아무거나"), missing_engine)
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason


def test_규칙_설정_오류면_거절하고_담당자에게_알리라고_한다(installed_hook, tmp_path):
    root = tmp_path / "회사2"
    _write(root / "templates" / "제안서.md", PROPOSAL_TEMPLATE)
    _write(root / "rules" / "제안서.yaml", BROKEN_RULES)
    (root / "docs" / "제안서").mkdir(parents=True)
    target = root / "docs" / "제안서" / "아무.md"

    code, out = run_hook(installed_hook, _write_payload(target, "아무거나"), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "문서의 문제가 아닙니다" in reason

def test_입력을_해석하지_못하면_통과시키지_않는다(installed_hook):
    # 입력을 못 읽으면 소관인지조차 모른다. 모른다는 것을 통과로 바꾸지 않는다(원칙 7).
    done = subprocess.run(
        [sys.executable, str(installed_hook)],
        input='{"tool_name": "Write", 깨진', capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )
    assert done.returncode == 0
    assert decision(json.loads(done.stdout)) == "deny"


# --- 한글 경로(#14) --------------------------------------------------------
#
# 아래 테스트들은 `run_hook_bytes` 로 UTF-8 바이트를 곧장 흘려보내고, 파이썬이
# 스스로 UTF-8 을 강제하는 환경변수를 걷어낸 채로 훅을 부른다. `_force_utf8_io()`
# 가 stdin 을 못 박지 않으면 Windows 로캘 기본 코드페이지(cp949)가 한글 경로를
# 깨뜨려, 아래 단언 중 적어도 하나는 실패한다 — 그것이 이 테스트의 존재 이유다.


def test_한글이_겹친_경로에서도_설치본이_파일명_위반을_막는다(installed_hook, ssot_standards_root):
    target = ssot_standards_root / "docs" / "ssot" / "PRD_v2.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# PRD\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    assert "파일 이름이 정해진 형식과 다르다" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_한글이_겹친_경로에서도_설치본이_규칙에_맞는_파일은_통과시킨다(installed_hook, ssot_standards_root):
    target = ssot_standards_root / "docs" / "ssot" / "PRD.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# PRD\n"), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_한글_파일명도_설치본이_위반으로_잡는다(installed_hook, ssot_standards_root):
    target = ssot_standards_root / "docs" / "ssot" / "요구사항.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# 요구사항\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    assert "파일 이름이 정해진 형식과 다르다" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_경로가_깨져_들어오면_검사_불능으로_거절한다(installed_hook, tmp_path):
    """경로 문자열에 U+FFFD 가 섞여 있으면 관할 판단 자체가 불가능하다(#14).

    진짜 관할 밖(기준 폴더가 없는 경우, 위 테스트들에도 있다)과는 받는 처분이
    달라야 한다 — 이쪽은 allow 가 아니라 deny 다(CLAUDE.md 원칙 7).
    """
    target = tmp_path / "��" / "docs" / "PRD.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# PRD\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "문서 경로가 깨져 들어와" in reason
    assert "doc-guard 소관인지" in reason


# --- 공통 개발 규칙(CR-001, CR-002, #54) -----------------------------------
#
# 문서 검사와 소관이 다르다 — 기준 폴더(`templates`/`rules`)를 요구하지 않는다.
# 그래서 아래 테스트는 `standards_root` 픽스처 없이 아무 임시 폴더에서나 확인한다.


def test_설치본에서도_코드의_한글_이름을_막는다(installed_hook, tmp_path):
    target = tmp_path / "z_report.abap"
    code, out = run_hook(
        installed_hook, _write_payload(target, "DATA 주문번호 TYPE vbeln.\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert "주문번호" in reason


def test_설치본에서도_반복문_안의_select를_막는다(installed_hook, tmp_path):
    target = tmp_path / "z_report.abap"
    code, out = run_hook(
        installed_hook,
        _write_payload(
            target,
            "LOOP AT lt_order INTO ls_order.\n"
            "  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln.\n"
            "ENDLOOP.\n",
        ),
        str(ENGINE_ROOT),
    )
    assert decision(out) == "deny"
    assert "CR-002" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_설치본에서도_규칙을_지킨_코드는_통과시킨다(installed_hook, tmp_path):
    target = tmp_path / "z_report.abap"
    code, out = run_hook(
        installed_hook, _write_payload(target, "DATA lv_order TYPE vbeln.\n"), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_기준_폴더가_없어도_공통_개발_규칙은_적용된다(installed_hook, tmp_path):
    """CR-001/CR-002 는 doc-guard 와 달리 `templates`/`rules` 를 요구하지 않는다.

    `tmp_path` 는 어느 기준 폴더에도 속하지 않지만(standards_root 픽스처를 쓰지 않았다),
    그래도 위반이 막혀야 이 규칙이 문서 검사와 소관이 다르다는 설계가 지켜진다.
    """
    target = tmp_path / "아무데나" / "z_report.abap"
    code, out = run_hook(
        installed_hook, _write_payload(target, "DATA 주문번호 TYPE vbeln.\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"


def test_harness_allow_주석이_있는_코드는_통과시킨다(installed_hook, tmp_path):
    target = tmp_path / "z_report.abap"
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE * FROM vbak INTO ls_vbak WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002 이유\n'
        "ENDLOOP.\n"
    )
    code, out = run_hook(installed_hook, _write_payload(target, text), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_모르는_확장자의_코드_비슷한_파일은_관여하지_않는다(installed_hook, tmp_path):
    target = tmp_path / "아무거나.txt"
    code, out = run_hook(
        installed_hook, _write_payload(target, "주문번호"), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_설치본에서도_bdef_한글_이름을_막는다(installed_hook, tmp_path):
    """BDEF(abapGit 확장자 `.bdef.asbdef`, #72)도 CR-001 로 검사한다."""
    target = tmp_path / "zbnh2_i_course.bdef.asbdef"
    code, out = run_hook(
        installed_hook, _write_payload(target, "action 승인하기;\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason
    assert "승인하기" in reason


def test_설치본에서도_규칙을_지킨_bdef는_통과시킨다(installed_hook, tmp_path):
    target = tmp_path / "zbnh2_i_course.bdef.asbdef"
    code, out = run_hook(
        installed_hook, _write_payload(target, "action approve;\n"), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


def test_코드_엔진을_받을_수_없으면_통과가_아니라_거절한다(installed_hook, tmp_path):
    """CLAUDE.md 원칙 7: '검사를 못 했다' 를 '통과' 로 뭉개지 않는다."""
    target = tmp_path / "z_report.abap"
    missing_engine = str(tmp_path / "존재하지-않는-경로")
    code, out = run_hook(
        installed_hook, _write_payload(target, "DATA lv_x TYPE vbeln.\n"), missing_engine
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "확인되지 않는 상태로 통과시키지 않습니다" in reason
