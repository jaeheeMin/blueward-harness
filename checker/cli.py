"""엔진의 유일한 공개 인터페이스.

플러그인 훅과 GitHub Actions 가 둘 다 이 명령 하나를 부른다. 두 호출 지점이 이 계약만
붙들고 있으므로 계약이 곧 인터페이스다.

종료코드
    0  통과. 검사한 것이 하나도 없는 경우(전부 관할 밖)도 여기 든다. README 만 고친 PR 이
       CI 를 깨뜨리면 안 되기 때문이다. 구분은 종료코드가 아니라 리포트의 `scoped` 가 싣는다.
    1  문서 위반.
    2  설정 오류. 규칙 파일이 깨졌거나 관할이 겹친 경우.
    3 이상은 비워 둔다. 나중에 "검사한 것이 없으면 실패로 쳐라" 가 필요해지면 기본값을
    건드리지 않는 선택 플래그로 붙인다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from checker.engine import OUT_OF_SCOPE, check, summarize
from checker.loader import load
from checker.locate import group_by_standards_root
from checker.model import ConfigError

EXIT_PASS = 0
EXIT_VIOLATION = 1
EXIT_CONFIG_ERROR = 2


def _relative(path: Path, root: Path) -> str:
    """기준 경로 아래로의 상대경로를 낸다.

    기준 아래에 있지 않으면 관할 glob 이 매치될 수가 없어 `out_of_scope` 로 빠진다.
    그런데 그것은 "검사 대상이 아니다" 가 아니라 "기준점을 잘못 줘서 이 문서가 어디
    있는지 판단하지 못했다" 이다. 판단 실패를 관할 밖으로 위장하지 않도록 여기서
    설정 오류로 끊는다(#13).
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        raise ConfigError(
            f"{resolved} 이 기준 경로 {root} 아래에 있지 않습니다. "
            "--root 를 이 문서가 속한 폴더로 맞춰 주십시오."
        ) from None


def _force_utf8() -> None:
    """출력을 UTF-8 로 못 박는다.

    이것이 없으면 Windows 에서 CLI 가 죽는다. 콘솔 기본 인코딩이 cp949 나 cp1252 라서
    한글이 담긴 위반 메시지를 JSON 으로 내보내는 순간 UnicodeEncodeError 가 난다.
    팀원 PC 가 정확히 그 환경이고, 이 도구의 출력은 거의 항상 한글이다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="doc-guard",
        description="문서가 고객사 템플릿을 따르는지 검사한다.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="검사하지 않고 외부 흔적을 걷어낸 새 파일을 만든다. 원본은 덮지 않는다",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="--clean 의 결과를 둘 곳"
    )
    parser.add_argument("paths", nargs="*", type=Path, help="검사할 문서")
    parser.add_argument(
        "--rules", type=Path, help="규칙 파일 하나 또는 규칙 폴더"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="파일마다 기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더)를 스스로 "
        "찾아 그 rules/ 를 쓴다. 기준 폴더가 여러 개인 문서를 한 번에 검사할 때 쓴다",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="관할 glob 을 맞춰 볼 기준 경로. 기본은 rules/ 의 한 단계 위(기준 폴더)",
    )
    args = parser.parse_args(argv)

    if args.clean:
        return _clean(args.paths, args.out_dir)

    if args.auto == bool(args.rules):
        parser.error("--rules 와 --auto 중 정확히 하나를 주십시오")

    try:
        if args.auto:
            report = _check_auto(args.paths)
        else:
            report = _check_with_rules(args.rules, args.root, args.paths)
    except ConfigError as exc:
        json.dump(
            {"status": "config_error", "message": str(exc)},
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return EXIT_CONFIG_ERROR

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return EXIT_VIOLATION if report["summary"]["violations"] else EXIT_PASS


def _clean(paths: list[Path], out_dir: Path | None) -> int:
    """외부 흔적을 걷어낸 새 파일을 만든다. 사람이 직접 부르는 길이다."""
    from checker.cleaner import clean, default_output

    if not paths:
        print("걷어낼 파일을 지정하십시오.", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    for path in paths:
        target = (out_dir / path.name) if out_dir else default_output(path)
        try:
            print(clean(path, target).summary())
        except (ValueError, OSError) as exc:
            print(f"{path.name}: {exc}", file=sys.stderr)
            return EXIT_CONFIG_ERROR
    return EXIT_PASS


def _check_with_rules(rules: Path, root_arg: Path | None, paths: list[Path]) -> dict:
    rules_path = rules.resolve()
    types = load(rules_path)
    # 관할 glob 은 기준 폴더를 기준으로 쓴다(`docs/제안서/**`). 규칙은 그 아래
    # `rules/` 에 있으므로 한 단계 위가 기준이 된다.
    rules_dir = rules_path if rules_path.is_dir() else rules_path.parent
    root = (root_arg or rules_dir.parent).resolve()
    return check([(p, _relative(p, root)) for p in paths], types)


def _check_auto(paths: list[Path]) -> dict:
    """파일마다 기준 폴더를 찾아 그 규칙으로 검사하고 하나로 합친다.

    보통 Project Repository 에는 기준 폴더가 하나지만, 한 저장소에 여럿 두면 한 PR 이
    두 기준 폴더를 건드릴 수 있다. 기준 폴더마다 규칙이 다르니 묶어서 각각 돌린 뒤
    결과를 합친다.
    """
    grouped, orphans = group_by_standards_root(paths)

    files = []
    for root, members in sorted(grouped.items()):
        types = load(root / "rules")
        part = check([(p, _relative(p, root)) for p in members], types)
        files.extend(part["files"])

    # 기준 폴더 바깥의 파일은 대조할 기준이 없다. 검사한 적이 없으므로 통과라고
    # 답하지 않는다.
    for p in orphans:
        files.append(
            {"file": p.as_posix(), "type": None, "template": None,
             "status": OUT_OF_SCOPE, "violations": []}
        )

    return {"summary": summarize(files), "files": files}


if __name__ == "__main__":
    raise SystemExit(main())
