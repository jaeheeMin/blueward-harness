"""Project Repository 표준 구조를 만든다.

`/harness:scaffold` Skill 이 이 스크립트를 부른다. 스킬이 아니라 스크립트로 둔 이유는
결정론적인 파일 복사·치환에는 모델 판단이 필요 없고, 테스트(`checker/tests/
test_scaffold.py`)가 사람 손 없이 반복 실행할 수 있어야 하기 때문이다.

만드는 자리는 `skeleton/` 아래를 그대로 옮긴 것이다. `templates/` 와 `rules/`
를 프로젝트 저장소 루트에 두면, `checker.locate.find_standards_root` 가 이
루트를 기준 폴더로 찾아내고 `관할` glob 도 이 루트를 기준으로 맞아떨어진다.
CLAUDE.md 의 "지금 어디까지 왔나" 가 이 전제를 설명한다.

이미 있는 파일은 절대 덮어쓰지 않는다. 두 번째 실행에서도 사람이 이미 채워
넣은 내용을 잃지 않아야 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SKELETON = Path(__file__).resolve().parent / "skeleton"

# 스켈레톤 안에서는 `dot-github` 라는 이름으로 둔다. 이 폴더가 `.github` 그대로면
# 이 스킬이 사는 blueward-harness 저장소 자신의 워크플로와 뒤섞여 보이고, 일부
# 도구는 점으로 시작하는 폴더를 조용히 건너뛴다. 실제로 만들 때만 `.github` 로
# 되돌린다.
RENAME = {"dot-github": ".github"}


def _dest_relative(src_relative: Path) -> Path:
    parts = [RENAME.get(part, part) for part in src_relative.parts]
    return Path(*parts)


def _render(text: str, client: str, project: str, today: str, ssot_approvers: list[str]) -> str:
    # 승인자가 없으면 빈 문자열로 치환한다 — `.github/ssot-approvers` 는 그러면
    # 주석과 빈 줄만 남고, 그것을 `checker.ssot_approval.load_approvers` 가
    # "누구든 승인할 수 있다" 로 읽는다.
    approvers_block = "\n".join(ssot_approvers)
    return (
        text.replace("{{client}}", client)
        .replace("{{project}}", project)
        .replace("{{date}}", today)
        .replace("{{ssot_approvers}}", approvers_block)
    )


def scaffold(
    root: Path,
    client: str,
    project: str,
    dry_run: bool,
    ssot_approvers: list[str] | None = None,
) -> dict:
    """`root` 아래에 표준 구조를 만들고 결과를 사전으로 돌려준다.

    기존 파일은 건드리지 않는다. `dry_run` 이면 만들 목록만 셈하고 아무것도
    쓰지 않는다. `ssot_approvers` 는 `.github/ssot-approvers` 에 한 줄씩
    적어 넣을 GitHub 아이디 목록이다 — 비워 두면(기본값) 그 파일은 누구든
    승인할 수 있다는 뜻으로 남는다.
    """
    today = date.today().isoformat()
    approvers = list(ssot_approvers or [])
    created: list[str] = []
    skipped: list[str] = []

    for src in sorted(SKELETON.rglob("*")):
        if src.is_dir():
            continue
        rel = _dest_relative(src.relative_to(SKELETON))
        rel_posix = rel.as_posix()
        dest = root / rel

        if dest.exists():
            skipped.append(rel_posix)
            continue

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            text = _render(text, client, project, today, approvers)
            # newline="\n" 으로 못 박는다. Windows 에서 텍스트 모드로 그냥 쓰면
            # LF 가 CRLF 로 바뀌어, 같은 스켈레톤인데 플랫폼마다 다른 바이트가
            # 나온다.
            dest.write_text(text, encoding="utf-8", newline="\n")
        created.append(rel_posix)

    return {
        "root": root.as_posix(),
        "created": created,
        "skipped": skipped,
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔 기본 인코딩(cp949 등)으로는 한글 경로가 그대로 안 나온다.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        prog="scaffold",
        description="Project Repository 표준 구조(templates/, rules/, docs/ssot/ 등)를 만든다.",
    )
    parser.add_argument("--client", required=True, help="고객사 이름")
    parser.add_argument("--project", required=True, help="프로젝트 이름")
    parser.add_argument(
        "--root", type=Path, default=None, help="Project Repository 루트. 기본은 현재 디렉터리"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="만들 목록만 보여주고 실제로 쓰지 않는다"
    )
    parser.add_argument(
        "--ssot-approver",
        action="append",
        dest="ssot_approvers",
        default=None,
        metavar="GITHUB_ID",
        help="docs/ssot(PRD) 변경 PR 을 승인할 수 있는 GitHub 아이디. 여러 번 줄 수 있다. "
        "생략하면 .github/ssot-approvers 를 비워 두고, 그러면 작성자가 아닌 누구의 "
        "승인이든 인정한다",
    )
    args = parser.parse_args(argv)

    root = (args.root or Path(".")).resolve()
    if not root.is_dir():
        print(f"{root} 는 디렉터리가 아니다", file=sys.stderr)
        return 2

    result = scaffold(root, args.client, args.project, args.dry_run, args.ssot_approvers)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
