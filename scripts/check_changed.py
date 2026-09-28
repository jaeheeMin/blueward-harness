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
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from checker.cli import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, _check_auto, main
from checker.code_rules import EXIT_CANNOT_CHECK as CODE_EXIT_CANNOT_CHECK
from checker.code_rules import build_report as _build_code_report
from checker.code_rules import exit_code_for as _code_exit_code
from checker.code_rules import language_for_suffix
from checker.model import ConfigError

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

    if not code_files:
        # 코드 파일이 없다. doc-guard 만 있던 예전 그대로 동작한다.
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

    code_report = _build_code_report([Path(f) for f in code_files])
    code_exit = _code_exit_code(code_report)

    combined = dict(doc_report)
    combined["code_rules"] = {"report": code_report, "exit": code_exit}
    print(json.dumps(combined, ensure_ascii=False))

    if code_exit == CODE_EXIT_CANNOT_CHECK:
        return EXIT_CONFIG_ERROR
    if doc_report["summary"]["violations"] or code_exit == EXIT_VIOLATION:
        return EXIT_VIOLATION
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main_entry())
