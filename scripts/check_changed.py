"""바뀐 파일 목록을 받아 검사한다. GitHub Actions 워크플로가 부른다.

`doc-guard --auto` 를 그대로 쓰지 않고 한 겹 두는 이유는, Actions 가 넘기는 목록을
먼저 걸러야 하기 때문이다. 존재하지 않는 경로를 엔진에 넘기면 리더가 오류를 내는데
그것은 규칙 파일이 깨진 것과 구분되지 않는다.

**검사할 수 없는 상태를 통과로 답하지 않는다.** 목록에 이름이 있는데 그 경로가 실제
파일이 아니면 무언가 어긋난 것이다. 지워진 파일은 워크플로가 `--diff-filter=d` 로 이미
빼고 넘기므로 정상 상황이 아니다. 실제로 이 자리에서 한 번 당했다. git 이 한글 경로를
따옴표와 8진수로 감싸 내놓는 바람에 모든 경로가 깨졌는데, 그때 이 스크립트가 말없이
"검사 대상 없음" 으로 넘겨 위반 문서가 있는 PR 이 초록불로 통과했다.

같은 이유로 목록 파일 자체가 없는 것과 목록이 비어 있는 것도 구분한다. 목록이 비어
있으면 "바뀐 것이 없다" 는 뜻이라 통과(0)가 맞지만, 목록 파일을 읽지 못하면 무엇이
바뀌었는지조차 알아내지 못한 것이므로 검사 불능(2)이다.

기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더)가 저장소 안에 하나도 없어도
지금까지는 조용히 통과했다. 관할 glob 이 아무 것도 매치하지 못해 모든 문서가
out_of_scope 로 빠지기 때문이다. 이 워크플로를 부르는 저장소는 검사받을 뜻으로 부른
것이므로, 기준 폴더가 아예 없는 것은 관할 밖이 아니라 설정을 빠뜨린 것이다(#24). 바뀐
파일이 있는데 기준 폴더가 하나도 없으면 검사 불능으로 끝낸다. 바뀐 파일이 없을 때는 이
검사를 하지 않는다 — 그것은 정당한 통과이지 설정 오류가 아니다.

**공통 개발 규칙(CR-001, CR-002, CR-003, CR-007, #54, #81)은 문서 검사와 소관이 갈린다.** `checker.code_rules`
가 아는 확장자(`.abap`, `.js`/`.ts`, `.cds` 등)는 doc-guard 의 `--auto` 로 보내지 않고
따로 검사한다 — 기준 폴더를 요구하지 않으므로, 바뀐 파일이 전부 코드뿐이면 기준 폴더가
하나도 없어도(#24 가드) 검사 불능으로 끝내지 않는다. 그 가드는 문서에만 해당한다. 두
검사의 리포트는 하나의 JSON 에 함께 담되(`code_rules` 키), 종료코드는 둘 중 더 나쁜
쪽을 따른다 — 검사 불능(2) > 위반(1) > 통과(0).

**SRS·Spec·원장 번호 짝 검사(#284)**: 바뀐 파일에 `docs/ssot/SRS.md`, `docs/spec/`,
`audit/ledger/` 경로가 하나라도 있으면 `checker.pairing` 을 돌려 리포트에 `pairing` 키로 합친다.
같은 우선순위로 종료코드에 반영한다. `audit/ledger/` 가 없는 저장소는 대상이 아니라 키도 만들지
않고 동작도 바뀌지 않는다.

**Spec 간 객체 겹침 검사(#292)**: 바뀐 파일에 `docs/spec/` 경로가 있으면 `checker.overlap` 을 돌려
`overlap` 키로 합친다. 경고만 하므로 위반은 없고 읽지 못한 Spec 이 있으면 검사 불능(2)이다.
두 교차 검사는 `rules/cross-checks/switches.yaml`(`checker.cross_switches`)로 각각 끌 수 있고,
파일이 없으면 둘 다 켠다. 그 파일이 잘못되면 `cross_checks` 키에 검사 불능을 싣고 종료코드 2 다.

**열린 PR 끼리 판 번호 겹침(#315)**: 환경변수 `DOC_GUARD_OPEN_PRS`(PR 이벤트에서 워크플로가
`scripts/fetch_open_prs.py` 의 결과 JSON 경로로 채움)가 있고, 바뀐 파일에 SRS 나 `_v<판>` 산출 파일이 있으면
`checker.version_overlap` 을 돌려 `version_overlap` 키로 합친다. 경고만 하고 위반은 없다. 열린 PR 정보를 못
읽었으면(파일 없음·깨짐·API 실패) 검사 불능(2)이다. 환경변수가 없으면(push, 로컬) 대상이 아니라 키도 없다.
스위치 `판_겹침` 으로 끌 수 있다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, _check_auto, main
from checker.code_rules import EXIT_CANNOT_CHECK as CODE_EXIT_CANNOT_CHECK
from checker.code_rules import build_report as _build_code_report
from checker.code_rules import exit_code_for as _code_exit_code
from checker.code_rules import language_for_suffix
from checker.model import ConfigError
from checker.cross_switches import DISABLED, SwitchError, load_switches
from checker.overlap import check_overlap
from checker.pairing import CANNOT_CHECK, LEDGER_DIR, SKIPPED, SPEC_DIR, SRS_PATH, check_pairing
from checker.pairing import exit_code_for as _pairing_exit_code
from checker.version_overlap import NOT_NEEDED, check_version_overlap, touches_version

OPEN_PRS_ENV = "DOC_GUARD_OPEN_PRS"  # 열린 PR 정보 JSON 경로(PR 이벤트에서만 워크플로가 채움)
PR_NUMBER_ENV = "DOC_GUARD_PR_NUMBER"

EMPTY_REPORT = (
    '{"summary": {"scoped": 0, "passed": 0, "violations": 0, "skipped": 0,'
    ' "out_of_scope": 0}, "files": []}'
)


def split_by_language(found: list[str]) -> tuple[list[str], list[str]]:
    """doc-guard 가 볼 파일과 `checker.code_rules` 가 볼 파일을 가른다.

    `checker.code_rules` 가 아는 언어(확장자)면 코드 쪽으로 보낸다. doc-guard 는 그런
    확장자를 관할하는 규칙이 없으므로, 보내 봤자 매번 out_of_scope 로 떨어져 리포트만
    어지럽힌다.
    """
    doc_files, code_files = [], []
    for name in found:
        (code_files if language_for_suffix(Path(name)) else doc_files).append(name)
    return doc_files, code_files


def touches_pairing_files(found: list[str]) -> bool:
    """바뀐 파일에 SRS·Spec·원장 경로가 하나라도 있는지(번호 짝 검사를 돌릴 조건)."""
    for name in found:
        p = Path(name).as_posix()
        if p == SRS_PATH or p.startswith((SPEC_DIR + "/", LEDGER_DIR + "/")):
            return True
    return False


def touches_spec_files(found: list[str]) -> bool:
    """바뀐 파일에 Spec 경로가 있는지(객체 겹침 검사를 돌릴 조건)."""
    return any(Path(name).as_posix().startswith(SPEC_DIR + "/") for name in found)


def _check_version_overlap(path: Path) -> dict | None:
    """열린 PR 정보 파일(`fetch_open_prs.py` 가 씀)로 판 번호 겹침(#315)을 본다. 읽을 일이 없었으면 None.

    파일이 없거나 깨졌거나 이 PR 번호를 모르면 검사 불능이다 — 조용히 넘어가지 않는다.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"status": CANNOT_CHECK, "warnings": [], "message": f"열린 PR 정보 {path} 를 읽지 못했습니다: {exc}"}
    if not isinstance(data, dict):
        return {"status": CANNOT_CHECK, "warnings": [], "message": f"열린 PR 정보 {path} 의 모양이 사전이 아닙니다"}
    if data.get("status") == NOT_NEEDED:
        return None
    number = os.environ.get(PR_NUMBER_ENV, "")
    if not number.isdigit():
        return {"status": CANNOT_CHECK, "warnings": [], "message": f"이 PR 번호({PR_NUMBER_ENV})를 알 수 없습니다"}
    return check_version_overlap(data, int(number))


def split_listing(text: str) -> tuple[list[str], list[str]]:
    """목록을 실제 파일과 그렇지 않은 것으로 가른다."""
    found, missing = [], []
    for line in text.splitlines():
        name = line.strip()
        if not name:
            continue
        (found if Path(name).is_file() else missing).append(name)
    return found, missing


def has_standards_root(root: Path, depth: int = 2) -> bool:
    """기준 폴더가 하나라도 있는지 본다.

    `templates/` 와 `rules/` 를 함께 둔 폴더가 기준 폴더다. `checker.locate` 의
    `find_standards_root` 는 문서 하나에서 위로 올라가며 찾지만, 여기서는 저장소 전체에
    그런 폴더가 정말 하나도 없는지를 위에서 아래로 훑어 확인한다.
    """
    for level in range(depth + 1):
        pattern = "/".join(["*"] * level + ["templates"])
        for templates in root.glob(pattern):
            if templates.is_dir() and (templates.parent / "rules").is_dir():
                return True
    return False


def config_error(message: str) -> int:
    """검사할 수 없는 상태를 알린다. 통과라고도 위반이라고도 답하지 않는다."""
    print(json.dumps({"status": "config_error", "message": message}, ensure_ascii=False))
    print(message, file=sys.stderr)
    return EXIT_CONFIG_ERROR


def _force_utf8() -> None:
    """한글 메시지가 Windows 콘솔 코드페이지에서 깨지지 않게 한다.

    이것이 없으면 Windows 콘솔 기본 인코딩(cp949 등)에서 한글이 담긴 출력이
    UnicodeEncodeError 를 낸다. 이 스크립트의 출력은 거의 항상 한글이다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main_entry(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("사용법: check_changed.py <바뀐 파일 목록 파일>", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    listing_path = Path(args[0])
    try:
        listing_text = listing_path.read_text(encoding="utf-8")
    except OSError as exc:
        # 목록 파일 자체가 없다. 목록이 비어 있는 것과는 다르다 — 비어 있으면 "바뀐 것이
        # 없다" 지만, 파일이 없으면 무엇이 바뀌었는지조차 알아낼 수 없었다는 뜻이다.
        return config_error(f"바뀐 파일 목록 {listing_path} 를 읽지 못했습니다: {exc}")

    found, missing = split_listing(listing_text)

    if missing:
        print(
            f"목록에 있으나 실제 파일이 아닌 경로 {len(missing)}건: "
            + ", ".join(missing[:5])
            + ("..." if len(missing) > 5 else ""),
            file=sys.stderr,
        )

    if missing and not found:
        # 전부 깨졌다. 통과라고 답하면 보호가 필요한 순간에 보호가 사라진다.
        return config_error(
            "바뀐 파일 목록의 경로가 하나도 실제 파일이 아닙니다. "
            "경로가 이스케이프되었거나 작업 디렉터리가 어긋났을 수 있습니다."
        )

    if not found:
        # 애초에 목록이 비어 있었다. 검사할 것이 없고 그 사실은 리포트가 싣는다. 기준
        # 폴더 유무도 따지지 않는다 — 바뀐 것이 없다는 정당한 통과이지 설정 오류가
        # 아니다.
        print(EMPTY_REPORT)
        return EXIT_PASS

    doc_files, code_files = split_by_language(found)

    if doc_files and not has_standards_root(Path.cwd()):
        # 바뀐 문서가 있는데 대조할 기준 폴더가 하나도 없다. 지금까지는 모든 문서가
        # out_of_scope 로 빠져 조용히 통과했다(#24) — 기준 폴더를 만드는 것을 잊은
        # Project Repository 가 정확히 이 모양이 된다. 코드만 바뀐 경우는 이 가드를
        # 타지 않는다 — CR-001/CR-002 는 기준 폴더가 있든 없든 항상 적용된다.
        return config_error(
            "이 저장소에서 `templates/` 와 `rules/` 를 함께 가진 폴더를 찾지 못해 "
            "검사할 수 없습니다. doc-guard 를 쓰는 Project Repository 라면 "
            "`/scaffold` 로 구조를 만드십시오."
        )

    pairing_result = None
    overlap_result = None
    version_result = None
    switch_error = None
    wants_pairing = touches_pairing_files(found + missing)  # 지워진 경로도 트리거(목록에 들어온다면)
    wants_overlap = touches_spec_files(found + missing)
    open_prs_path = os.environ.get(OPEN_PRS_ENV)  # PR 이벤트에서만 워크플로가 채운다. 없으면 이 검사는 대상이 아니다.
    wants_version = bool(open_prs_path) and any(touches_version(n) for n in found + missing)
    if wants_pairing or wants_overlap or wants_version:
        try:
            switches = load_switches(Path.cwd())
        except SwitchError as exc:
            # 스위치를 읽지 못하면 켜진 건지 꺼진 건지 모른다. 돌리지도 건너뛰지도 않고 검사 불능.
            switch_error = {"status": CANNOT_CHECK, "message": str(exc)}
            switches = {}
        if wants_pairing and switches.get("번호_짝") is False:
            pairing_result = {"status": DISABLED}
        elif wants_pairing and switches.get("번호_짝"):
            # SRS·Spec·원장 중 하나라도 바뀌었다. 번호 짝(#284)은 저장소 전체를 보므로 바뀐
            # 파일과 무관한 기존 어긋남도 나온다. 원장이 없는 저장소는 skipped 라 건너뛴다.
            result = check_pairing(Path.cwd())
            if result["status"] != SKIPPED:
                pairing_result = result
        if wants_overlap and switches.get("객체_겹침") is False:
            overlap_result = {"status": DISABLED}
        elif wants_overlap and switches.get("객체_겹침"):
            # Spec 이 바뀌었다. 객체 겹침(#292)도 Spec 전체를 본다. 경고만 하고 위반은 없다.
            result = check_overlap(Path.cwd())
            if result["status"] != SKIPPED:
                overlap_result = result
        if wants_version and switches.get("판_겹침") is False:
            version_result = {"status": DISABLED}
        elif wants_version and switches.get("판_겹침"):
            version_result = _check_version_overlap(Path(open_prs_path))

    extras = [r for r in (pairing_result, overlap_result, version_result, switch_error) if r is not None]
    if not code_files and not extras:
        # 코드 파일도 교차 검사 대상도 없다. doc-guard 만 있던 예전 그대로 동작한다.
        return main(["--auto", *doc_files])

    try:
        doc_report = (
            _check_auto([Path(f) for f in doc_files])
            if doc_files
            else {
                "summary": {"scoped": 0, "passed": 0, "violations": 0, "skipped": 0, "out_of_scope": 0},
                "files": [],
            }
        )
    except ConfigError as exc:
        return config_error(str(exc))

    combined = dict(doc_report)
    code_exit = EXIT_PASS
    if code_files:
        code_report = _build_code_report([Path(f) for f in code_files])
        code_exit = _code_exit_code(code_report)
        combined["code_rules"] = {"report": code_report, "exit": code_exit}
    if pairing_result:
        combined["pairing"] = pairing_result
    if overlap_result:
        combined["overlap"] = overlap_result
    if version_result:
        combined["version_overlap"] = version_result
    if switch_error:
        combined["cross_checks"] = switch_error
    extra_exits = [_pairing_exit_code(r) for r in extras]  # 겹침은 위반이 없어 0 또는 2
    print(json.dumps(combined, ensure_ascii=False))

    if code_exit == CODE_EXIT_CANNOT_CHECK or EXIT_CONFIG_ERROR in extra_exits:
        return EXIT_CONFIG_ERROR
    if doc_report["summary"]["violations"] or code_exit == EXIT_VIOLATION or EXIT_VIOLATION in extra_exits:
        return EXIT_VIOLATION
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main_entry())
