"""Project Repository 표준 구조를 만든다.

`/harness:scaffold` Skill 이 이 스크립트를 부른다. 스킬이 아니라 스크립트로 둔 이유는
결정론적인 파일 복사·치환에는 모델 판단이 필요 없고, 테스트(`checker/tests/
test_scaffold.py`)가 사람 손 없이 반복 실행할 수 있어야 하기 때문이다.

만드는 자리는 `skeleton/` 아래를 그대로 옮긴 것이다. `templates/` 와 `rules/`
를 프로젝트 저장소 루트에 두면, `checker.locate.find_standards_root` 가 이
루트를 기준 폴더로 찾아내고 `관할` glob 도 이 루트를 기준으로 맞아떨어진다.
CLAUDE.md 의 "지금 어디까지 왔나" 가 이 전제를 설명한다.

이미 있는 파일은 절대 덮어쓰지 않는다. 두 번째 실행에서도 사람이 이미 채워
넣은 내용을 잃지 않아야 한다. 유일한 예외는 `.claude/settings.json` 이다 —
harness Plugin 자동 설치에 쓰는 두 항목이 없을 때만 그 항목만 채워 넣고,
나머지 내용과 값이 다른 경우는 역시 건드리지 않는다(`_plan_claude_settings_merge`).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SKELETON = Path(__file__).resolve().parent / "skeleton"

# 스켈레톤 안에서는 `dot-github`, `dot-claude` 라는 이름으로 둔다. 이 폴더가
# `.github`·`.claude` 그대로면 이 스킬이 사는 blueward-harness 저장소 자신의
# 워크플로·설정과 뒤섞여 보이고, 일부 도구는 점으로 시작하는 폴더를 조용히
# 건너뛴다. 실제로 만들 때만 원래 이름으로 되돌린다.
RENAME = {"dot-github": ".github", "dot-claude": ".claude"}

# 새 저장소를 여는 팀원이 harness Plugin 설치를 자동으로 안내받도록 넣는 값.
# 이미 있는 `.claude/settings.json` 은 절대 통째로 덮어쓰지 않고, 이 두 키가
# 없을 때만 채워 넣는다(_plan_claude_settings_merge).
CLAUDE_SETTINGS_REL = Path(".claude") / "settings.json"
EXPECTED_ENABLED_PLUGIN = ("harness@blueward-harness", True)
EXPECTED_MARKETPLACE = (
    "blueward-harness",
    {"source": {"source": "github", "repo": "jaeheeMin/blueward-harness"}, "autoUpdate": True},
)
# 외부 마켓플레이스는 Plugin 자동 업데이트가 기본으로 꺼져 있다. 저장소 설정에
# 이 값을 두면 그 저장소를 여는 팀원 모두 새 버전을 자동으로 받고 알림을 본다
# (https://code.claude.com/docs/en/plugins/loading "Which marketplaces and
# plugins auto-update"). 예전 scaffold 가 만든 설정에는 이 키가 없으므로, source 가
# 같고 이 키만 없으면 채워 넣는다(#99).
AUTO_UPDATE_KEY = "autoUpdate"


def _plan_claude_settings_merge(existing_text: str) -> dict:
    """기존 `.claude/settings.json` 을 두 키(enabledPlugins·extraKnownMarketplaces
    안의 harness 항목)만 채워 합칠 계획을 세운다. 이 함수는 읽기만 하고 아무
    파일도 쓰지 않는다 — `--dry-run` 에서도 그대로 판정을 미리 보여줄 수 있게.

    돌려주는 사전의 `status` 는 넷 중 하나다.
    - "unchanged": 이미 같은 값이 있다. 아무것도 바꾸지 않는다.
    - "merged": 두 항목 중 하나 이상이 없어 채워 넣었다. `text` 에 새 내용이 있다.
    - "conflict": 같은 키가 다른 값으로 이미 있다. 무엇이 다른지 `message` 에 담는다.
    - "invalid_json": JSON 으로 못 읽는다(파싱 실패 또는 최상위가 객체가 아님).

    "conflict" 와 "invalid_json" 은 이 파일을 건드리지 않는다는 뜻이다 — 검사를
    못 했다고 통과로 뭉개지 않는 것과 같은 원칙으로, 자동으로 못 합칠 값을
    통과(조용히 스킵)로도, 임의로 덮어써 위반(값 파괴)으로도 만들지 않는다.
    """
    try:
        data = json.loads(existing_text)
    except json.JSONDecodeError as exc:
        return {
            "status": "invalid_json",
            "message": f".claude/settings.json 이 올바른 JSON 이 아니라 건드리지 않았다({exc}). 두 키를 손으로 넣어야 한다.",
            "text": None,
        }
    if not isinstance(data, dict):
        return {
            "status": "invalid_json",
            "message": ".claude/settings.json 의 최상위가 객체(object)가 아니라 건드리지 않았다.",
            "text": None,
        }

    changed = False
    conflicts: list[str] = []

    enabled_key, enabled_value = EXPECTED_ENABLED_PLUGIN
    enabled_plugins = data.get("enabledPlugins")
    if enabled_plugins is None:
        data["enabledPlugins"] = {enabled_key: enabled_value}
        changed = True
    elif isinstance(enabled_plugins, dict):
        if enabled_key not in enabled_plugins:
            enabled_plugins[enabled_key] = enabled_value
            changed = True
        elif enabled_plugins[enabled_key] is not enabled_value:
            conflicts.append(
                f'enabledPlugins["{enabled_key}"] 가 이미 {enabled_plugins[enabled_key]!r} 로 설정돼 있다'
            )
    else:
        conflicts.append("enabledPlugins 가 객체(object)가 아니다")

    market_key, market_value = EXPECTED_MARKETPLACE
    marketplaces = data.get("extraKnownMarketplaces")
    if marketplaces is None:
        data["extraKnownMarketplaces"] = {market_key: market_value}
        changed = True
    elif isinstance(marketplaces, dict):
        entry = marketplaces.get(market_key)
        if entry is None:
            marketplaces[market_key] = dict(market_value)
            changed = True
        elif not isinstance(entry, dict) or entry.get("source") != market_value["source"]:
            conflicts.append(
                f'extraKnownMarketplaces["{market_key}"] 가 이미 다른 값으로 설정돼 있다'
            )
        elif AUTO_UPDATE_KEY not in entry:
            entry[AUTO_UPDATE_KEY] = True
            changed = True
        elif entry[AUTO_UPDATE_KEY] is not True:
            conflicts.append(
                f'extraKnownMarketplaces["{market_key}"].autoUpdate 가 이미 '
                f'{entry[AUTO_UPDATE_KEY]!r} 로 설정돼 있다(자동 업데이트를 끈 것이면 그대로 둔다)'
            )
    else:
        conflicts.append("extraKnownMarketplaces 가 객체(object)가 아니다")

    if conflicts:
        return {
            "status": "conflict",
            "message": ".claude/settings.json 의 기존 값과 달라 건드리지 않았다: "
            + "; ".join(conflicts),
            "text": None,
        }

    if not changed:
        return {"status": "unchanged", "message": None, "text": None}

    # 들여쓰기 2칸, UTF-8, BOM 없음, 끝 줄바꿈. 기존 키 순서는 dict 삽입 순서로
    # 그대로 유지되고, 새로 채운 키만 끝에 붙는다.
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return {"status": "merged", "message": None, "text": text}


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

    기존 파일은 건드리지 않는다. 다만 `.claude/settings.json` 만은 예외로,
    이미 있으면 `enabledPlugins`·`extraKnownMarketplaces` 안의 harness 항목
    두 개가 없을 때만 그 항목만 채워 넣고 나머지는 그대로 둔다(`merged`).
    이미 같은 값이면 손대지 않고(`skipped`), 다른 값이 있거나 JSON 을 못
    읽으면 역시 손대지 않고 무엇이 걸렸는지 `warnings` 에 담는다 — 검사를
    못 한 것을 통과로도, 위반(덮어쓰기)으로도 만들지 않는다.

    `dry_run` 이면 만들 목록만 셈하고 아무것도 쓰지 않는다. `ssot_approvers`
    는 `.github/ssot-approvers` 에 한 줄씩 적어 넣을 GitHub 아이디 목록이다
    — 비워 두면(기본값) 그 파일은 누구든 승인할 수 있다는 뜻으로 남는다.
    """
    today = date.today().isoformat()
    approvers = list(ssot_approvers or [])
    created: list[str] = []
    skipped: list[str] = []
    merged: list[str] = []
    warnings: list[dict] = []

    for src in sorted(SKELETON.rglob("*")):
        if src.is_dir():
            continue
        rel = _dest_relative(src.relative_to(SKELETON))
        rel_posix = rel.as_posix()
        dest = root / rel

        if dest.exists():
            if rel == CLAUDE_SETTINGS_REL:
                # utf-8-sig: Windows PowerShell 이 쓴 파일은 BOM 이 붙어 있을 수 있다.
                plan = _plan_claude_settings_merge(dest.read_text(encoding="utf-8-sig"))
                if plan["status"] == "merged":
                    if not dry_run:
                        dest.write_text(plan["text"], encoding="utf-8", newline="\n")
                    merged.append(rel_posix)
                elif plan["status"] == "unchanged":
                    skipped.append(rel_posix)
                else:  # "conflict" 또는 "invalid_json" — 손대지 않고 알린다.
                    skipped.append(rel_posix)
                    warnings.append({"path": rel_posix, "message": plan["message"]})
                continue
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
        "merged": merged,
        "warnings": warnings,
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
    for warning in result["warnings"]:
        print(f"경고: {warning['path']} — {warning['message']}", file=sys.stderr)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
