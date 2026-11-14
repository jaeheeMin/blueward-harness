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
    패턴: '^SRS\.md$'
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
    assert "다음:" in reason  # #113(Hook 거부 메시지에 원인과 다음 할 일 함께 안내)


def test_거부_문구에_설치_명령과_이슈_저장소가_적혀_있다():
    """#113(Hook 거부 메시지에 원인과 다음 할 일 함께 안내): uv 가 없을 때 사람이
    할 일이 명령 그대로 적혀 있어야 한다."""
    hooks_dir = PLUGIN_SRC / "hooks"
    for name in ("pre_write_guard.py", "mcp_source_guard.py"):
        text = (hooks_dir / name).read_text(encoding="utf-8")
        assert "winget install --id astral-sh.uv -e" in text
        assert "jaeheeMin/blueward-harness" in text
        assert "관리하는 담당자에게 알리십시오" not in text


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
    assert "rules/" in reason and "다음:" in reason

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
    target = ssot_standards_root / "docs" / "ssot" / "SRS_v2.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# SRS\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    assert "파일 이름이 정해진 형식과 다르다" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_한글이_겹친_경로에서도_설치본이_규칙에_맞는_파일은_통과시킨다(installed_hook, ssot_standards_root):
    target = ssot_standards_root / "docs" / "ssot" / "SRS.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# SRS\n"), str(ENGINE_ROOT)
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
    target = tmp_path / "��" / "docs" / "SRS.md"
    code, out = run_hook_bytes(
        installed_hook, _write_payload(target, "# SRS\n"), str(ENGINE_ROOT)
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


_AUTH_POOL = (
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


def test_CR_009_경고는_막지_않고_알림으로_보여_준다(installed_hook, tmp_path):
    target = tmp_path / "zbp_x.clas.locals_imp.abap"
    code, out = run_hook(installed_hook, _write_payload(target, _AUTH_POOL), str(ENGINE_ROOT))
    assert code == 0 and out is not None
    assert "permissionDecision" not in out["hookSpecificOutput"]
    notice = out["hookSpecificOutput"]["additionalContext"]
    assert "CR-009" in notice and "막지 않음" in notice and "get_global_authorizations" in notice


def test_CR_009_경고가_있어도_위반이_있으면_막고_경고도_같이_보여_준다(installed_hook, tmp_path):
    target = tmp_path / "zbp_x.clas.locals_imp.abap"
    code, out = run_hook(
        installed_hook, _write_payload(target, _AUTH_POOL + "DATA 주문번호 TYPE vbeln.\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CR-001" in reason and "CR-009" in reason


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
    # 필드 목록을 써서 CR-002(반복문 안 SELECT) 만 걸리게 한다 — `*` 를 쓰면 CR-003
    # (SELECT *) 도 함께 걸려 harness:allow 가 CR-002 하나만 예외 처리했을 때
    # 통과하는지를 보려는 이 테스트의 의도가 흐려진다.
    text = (
        "LOOP AT lt_order INTO ls_order.\n"
        '  SELECT SINGLE vbeln FROM vbak INTO ls_vbak-vbeln WHERE vbeln = ls_order-vbeln. "#harness:allow CR-002 이유\n'
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


# --- 규칙 설정이 깨졌을 때 설정 파일 수정은 허용한다(#209) ---------------------------

MISSING_TEMPLATE_RULES = """템플릿: ../templates/없는템플릿.md
관할: "docs/제안서/**"

규칙:
  - 종류: required_sections
"""


@pytest.fixture()
def missing_template_root(tmp_path) -> Path:
    """규칙이 없는 템플릿을 가리키는 기준 폴더 — PRD→SRS 이름 변경 도중의 상태."""
    root = tmp_path / "회사3"
    _write(root / "templates" / "제안서.md", PROPOSAL_TEMPLATE)
    _write(root / "rules" / "ssot.yaml", MISSING_TEMPLATE_RULES)
    (root / "docs" / "제안서").mkdir(parents=True)
    return root


def _decision(out: dict | None) -> str | None:
    """알림만 있는 응답(permissionDecision 없음)도 읽는다."""
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def _notice(out: dict | None) -> str:
    assert out is not None and "permissionDecision" not in out["hookSpecificOutput"]
    return out["hookSpecificOutput"]["additionalContext"]


def test_설정_오류면_규칙_파일_수정은_허용하고_알린다(installed_hook, missing_template_root):
    target = missing_template_root / "rules" / "ssot.yaml"
    code, out = run_hook(
        installed_hook, _write_payload(target, PROPOSAL_RULES), str(ENGINE_ROOT)
    )
    assert code == 0
    notice = _notice(out)
    assert "규칙 설정에 오류가 있어 문서 검사를 못 하는 상태" in notice
    assert "설정 파일 수정이라 허용" in notice and "사유:" in notice


def test_설정_오류면_templates_아래_쓰기는_허용하고_알린다(installed_hook, missing_template_root):
    target = missing_template_root / "templates" / "SRS.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, "# SRS\n"), str(ENGINE_ROOT)
    )
    assert code == 0
    assert "설정 파일 수정이라 허용" in _notice(out)


def test_설정_오류면_일반_문서_쓰기는_여전히_거절한다(installed_hook, missing_template_root):
    target = missing_template_root / "docs" / "제안서" / "SRS.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, "# SRS\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"
    assert "문서의 문제가 아닙니다" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_설정_오류면_상위_경로_우회로_일반_문서를_쓰는_것은_거절한다(installed_hook, missing_template_root):
    target = missing_template_root / "rules" / ".." / "docs" / "제안서" / "x.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, "# x\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"


def test_설정_오류면_rules_아래여도_yaml_이_아니면_거절한다(installed_hook, missing_template_root):
    target = missing_template_root / "rules" / "메모.md"
    code, out = run_hook(
        installed_hook, _write_payload(target, "# 메모\n"), str(ENGINE_ROOT)
    )
    assert decision(out) == "deny"


def test_설정이_정상이면_규칙_파일_수정도_알림_없이_평소대로_검사한다(installed_hook, standards_root):
    target = standards_root / "rules" / "제안서.yaml"
    code, out = run_hook(
        installed_hook, _write_payload(target, PROPOSAL_RULES), str(ENGINE_ROOT)
    )
    assert code == 0 and out is None


# --- CAP·UI5 개발 표준(#944): 바뀌는 줄에만 적용 ------------------------------------

UI5_VIEW = "app/webapp/view/Main.view.xml"
UI5_JS = "app/webapp/controller/Main.controller.js"  # webapp 아래 JS 만 UI5 검사 대상이다
UI5_I18N = "app/webapp/i18n/i18n.properties"
VIEW_OPEN = '<mvc:View xmlns="sap.m" xmlns:mvc="sap.ui.core.mvc">\n'


@pytest.fixture()
def ui5_project(tmp_path) -> Path:
    root = tmp_path / "ui5-project"
    (root / ".git").mkdir(parents=True)
    _write(root / "conventions" / "cap-ui5.yaml", "")
    return root


def _edit_payload(path: Path, old: str, new: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}


def _decision(out: dict | None) -> str | None:
    """알림만 있는 응답(permissionDecision 없음)도 읽는다."""
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def _notice(out: dict | None) -> str:
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def test_ui5_새_화면_XML_의_위반은_막고_규칙과_고치는_법을_알린다(installed_hook, ui5_project):
    target = ui5_project / UI5_VIEW
    content = VIEW_OPEN + '\t<Button id="list-btn-search" text="저장"/>\n</mvc:View>\n'
    code, out = run_hook(installed_hook, _write_payload(target, content), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "UI5-003" in reason and "UI5-004" in reason and "고치기:" in reason and "다음:" in reason
    assert str(target) in reason  # 임시 경로가 아니라 저장하려던 경로


def test_ui5_표준에_맞는_파일은_조용히_통과한다(installed_hook, ui5_project):
    target = ui5_project / UI5_VIEW
    content = VIEW_OPEN + '\t<Button id="listBtnSearch" text="{i18n>main.button.search}"/>\n</mvc:View>\n'
    code, out = run_hook(installed_hook, _write_payload(target, content), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_ui5_설정_파일이_없으면_검사하지_않는다(installed_hook, tmp_path):
    root = tmp_path / "no-config"
    (root / ".git").mkdir(parents=True)
    target = root / UI5_VIEW
    code, out = run_hook(installed_hook, _write_payload(target, VIEW_OPEN + '<Button id="a-b"/>\n</mvc:View>\n'), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_ui5_기존_파일의_옛_위반은_편집을_막지_않고_새로_생긴_위반만_막는다(installed_hook, ui5_project):
    target = ui5_project / UI5_JS
    _write(target, "var a = 1;\nconsole.log('old');\nvar sB = 2;\n")
    ok = run_hook(installed_hook, _edit_payload(target, "var sB = 2;", "var sB = 3;"), str(ENGINE_ROOT))[1]
    assert _decision(ok) is None and "UI5-001" not in _notice(ok)  # 옛 console.log 는 이 편집이 바꾸지 않았다
    bad = run_hook(installed_hook, _edit_payload(target, "var sB = 2;", "console.log(2);"), str(ENGINE_ROOT))[1]
    assert decision(bad) == "deny"
    assert "UI5-001" in bad["hookSpecificOutput"]["permissionDecisionReason"]
    assert ":4:" not in bad["hookSpecificOutput"]["permissionDecisionReason"]  # 바뀐 줄은 3번째 줄
    assert ":3:" in bad["hookSpecificOutput"]["permissionDecisionReason"]


def test_ui5_Write_로_덮어써도_바뀌지_않은_옛_줄은_안_본다(installed_hook, ui5_project):
    target = ui5_project / UI5_JS
    _write(target, "console.log('old');\nvar sA = 1;\n")
    code, out = run_hook(installed_hook, _write_payload(target, "console.log('old');\nvar sA = 2;\n"), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_ui5_경고는_막지_않고_알림으로_남긴다(installed_hook, ui5_project):
    target = ui5_project / UI5_JS
    code, out = run_hook(installed_hook, _write_payload(target, "var name = 'x';\n"), str(ENGINE_ROOT))
    assert code == 0 and _decision(out) is None
    assert "UI5-106" in _notice(out) and "막지 않음" in _notice(out)


def test_ui5_코드_규칙과_UI5_경고를_함께_알린다(installed_hook, ui5_project):
    target = ui5_project / UI5_JS
    # CR-001(한글 이름)은 막고, UI5 경고는 그 거절 안에 같이 실린다
    code, out = run_hook(installed_hook, _write_payload(target, "var 이름 = 1;\nvar name = 2;\n"), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    assert "CR-001" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_ui5_properties_의_경고는_알림이다(installed_hook, ui5_project):
    target = ui5_project / UI5_I18N
    code, out = run_hook(installed_hook, _write_payload(target, "main.button.save=저장\n"), str(ENGINE_ROOT))
    assert code == 0 and _decision(out) is None and "UI5-109" in _notice(out)


def test_ui5_설정이_깨졌으면_통과가_아니라_거절한다(installed_hook, tmp_path):
    root = tmp_path / "broken-config"
    (root / ".git").mkdir(parents=True)
    _write(root / "conventions" / "cap-ui5.yaml", "모르는키: 1\n")
    code, out = run_hook(installed_hook, _write_payload(root / UI5_VIEW, VIEW_OPEN + "</mvc:View>\n"), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "검사 불능" in reason and "확인되지 않는 상태로 통과시키지 않습니다" in reason and "다음:" in reason


def test_ui5_XML_이_깨졌으면_통과가_아니라_거절한다(installed_hook, ui5_project):
    code, out = run_hook(installed_hook, _write_payload(ui5_project / UI5_VIEW, "<mvc:View><Button></mvc:View>\n"), str(ENGINE_ROOT))
    assert decision(out) == "deny"
    assert "검사 불능" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_ui5_엔진을_받을_수_없으면_거절한다(installed_hook, ui5_project, tmp_path):
    code, out = run_hook(installed_hook, _write_payload(ui5_project / UI5_VIEW, VIEW_OPEN + "</mvc:View>\n"), str(tmp_path / "없는-경로"))
    assert decision(out) == "deny"
    assert "확인되지 않는 상태로 통과시키지 않습니다" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("name", ["src/zcl_order.clas.xml", "src/package.devc.xml", "srv/service.js", "config/app.properties"])
def test_ui5_대상이_아닌_파일은_설정이_있어도_통과한다(installed_hook, ui5_project, name):
    content = '<abapGit id="a-b" x="한글"/>\n' if name.endswith(".xml") else "console.log(1);\n"
    code, out = run_hook(installed_hook, _write_payload(ui5_project / name, content), str(ENGINE_ROOT))
    assert code == 0 and out is None


def test_ui5_바뀌는_줄이_없으면_엔진을_부르지_않고_통과한다(installed_hook, ui5_project, tmp_path):
    target = ui5_project / UI5_I18N
    _write(target, "main.button.save=저장\n")
    # 엔진을 받을 수 없는 경로를 줘도 바뀌는 줄이 없으면 부르지 않으므로 거절하지 않는다
    code, out = run_hook(installed_hook, _write_payload(target, "main.button.save=저장\n"), str(tmp_path / "없는-경로"))
    assert code == 0 and out is None


def test_ui5_훅의_대상_판정은_엔진과_같다():
    import importlib.util

    from checker import ui5_rules

    spec = importlib.util.spec_from_file_location("pre_write_guard_ui5_probe", PLUGIN_SRC / "hooks" / "pre_write_guard.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PLUGIN_SRC / "hooks"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PLUGIN_SRC / "hooks"))
    for name in (
        "app/webapp/controller/A.controller.js", "webapp/Component.js", "app/webapp/view/A.view.xml",
        "app/webapp/x/B.fragment.xml", "app/webapp/i18n/i18n_ko.properties", "srv/service.js",
        "src/zcl_a.clas.xml", "src/package.devc.xml", "config/app.properties", "webapp/lib/v.min.js",
        "docs/a.md", "src/zcl_a.clas.abap", "APP/WEBAPP/VIEW/A.VIEW.XML",
    ):
        assert module._ui5_target(Path(name)) is bool(ui5_rules.target_kind(name)), name
