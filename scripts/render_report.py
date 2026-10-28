"""검사 리포트를 PR 코멘트용 마크다운으로 바꾼다.

사람이 읽는 화면이다. 위반한 규칙 이름만 나열하면 무엇을 어떻게 고쳐야 하는지 알 수
없으므로, 기대값과 실제값과 **쓸 템플릿 경로**를 함께 보여준다. 이 제품의 본질이
거절만 하는 것이 아니라 대신 무엇을 쓸지 알려주는 것이기 때문이다.

종료코드 1(문서 위반)과 그 밖의 모든 경우(설정 오류, 검사기 출력을 해석하지 못함,
예상치 못한 코드 — 통틀어 "검사 불능")는 받는 사람이 다르므로 글도 다르다. 문서를
올린 팀원은 규칙 파일을 고칠 권한도 지식도 없다. 자기 문서를 들여다보며 헤매게 두면
안 되고, 반대로 검사 불능을 조용히 통과로 뭉개도 안 된다(CLAUDE.md 원칙 7).

**공통 개발 규칙(CR-001, CR-002, #54)은 별도 절로 붙는다.** `scripts/check_changed.py`
가 코드 파일이 있으면 리포트에 `code_rules` 키(`{"report": ..., "exit": ...}`)를
더해 준다. 이 문서 쪽 렌더링(`_render_doc`)은 그 키를 모른 채로 그대로 두고,
`render()` 가 있으면 이어서 붙인다 — 그래서 doc-guard 부분의 판정은 바깥에서 받은
`code` 인자가 아니라 `report` 자체의 모양(`summary` 유무)으로 정한다. 둘을 하나의
종료코드로 합치면(check_changed.py 가 이미 그렇게 한다) 코드만 위반이어도 `code`
가 1 이 되어, 그 값만으로는 "문서는 괜찮은데 코드가 위반했다" 를 구분할 수 없기
때문이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MARKER = "<!-- doc-guard -->"


def render(report: dict, code: int) -> str:
    """전체 코멘트를 만든다. doc-guard 절과, 있으면 공통 개발 규칙 절을 잇는다."""
    text = _render_doc(report, code)
    code_rules = report.get("code_rules")
    if code_rules:
        text += "\n" + "\n".join(_render_code_rules(code_rules))
    pairing = report.get("pairing")
    if pairing:
        text += "\n" + "\n".join(
            _render_disabled("번호 짝") if pairing.get("status") == "disabled" else _render_pairing(pairing)
        )
    overlap = report.get("overlap")
    if overlap:
        text += "\n" + "\n".join(
            _render_disabled("객체 겹침") if overlap.get("status") == "disabled" else _render_overlap(overlap)
        )
    version = report.get("version_overlap")
    if version:
        text += "\n" + "\n".join(
            _render_disabled("판 번호 겹침") if version.get("status") == "disabled" else _render_version_overlap(version)
        )
    cross = report.get("cross_checks")
    if cross:
        text += "\n" + "\n".join(_render_cross_checks(cross))
    return text


def _render_disabled(name: str) -> list[str]:
    """스위치로 꺼진 교차 검사. 조용히 빠지지 않게 한 줄을 남긴다."""
    return ["", f"{name}: 이 저장소 설정(rules/cross-checks/switches.yaml)으로 꺼져 있음"]


def _render_overlap(result: dict) -> list[str]:
    """Spec 간 SAP 객체 겹침 절(#292). 경고만 하므로 위반 표는 없다."""
    out = ["", "---", "", "## 객체 겹침", ""]
    warnings = result.get("warnings") or []
    cannot = result.get("cannot_check") or []
    config_error = result.get("config_error")

    if config_error:
        out += [
            "### ⚠️ 검사 불능", "",
            f"- {config_error}", "",
            "공용 객체 종류 설정을 읽지 못해 겹침을 확인하지 못했습니다. 통과도 위반도 아닙니다. "
            "`rules/cross-checks/shared-objects.yaml` 의 `공용_종류` 가 문자열 목록인지 확인하십시오.",
            "",
        ]

    if cannot:
        out += ["### ⚠️ 검사 불능", ""]
        for item in cannot:
            out.append(f"- `{item.get('file')}` — {item.get('message')}")
        out += [
            "",
            "위 Spec 의 `## 사용 객체` 표를 읽지 못해 이 Spec 은 겹침을 확인하지 못했습니다. "
            "통과도 위반도 아닙니다. 표 머리(종류 | 이름 | 작업 | 비고)와 작업 값(생성·수정·참조)을 확인하십시오.",
            "",
        ]

    if warnings:
        out += [
            "### 참고 — 같은 객체를 둘 이상의 Spec 이 만들거나 고침 (통과에는 영향 없음)",
            "",
            f"**{len(warnings)}건**입니다. 이 PR 이 바꾼 Spec 이 다른 Spec 과 같은 객체를 만들거나 고칩니다. "
            "한 개발이 DEV 둘로 나뉜 것은 아닌지 확인하십시오. 따로 할 일이 맞으면 그대로 두어도 됩니다.",
            "",
            "| 종류 | 이름 | Spec (작업) |",
            "|---|---|---|",
        ]
        for w in warnings:
            specs = ", ".join(f"`{s.get('file')}` ({s.get('work')})" for s in w.get("specs") or [])
            out.append(f"| {_cell(w.get('kind'))} | `{_cell(w.get('name'))}` | {specs} |")
        out.append("")
    elif not cannot and not config_error:
        out += ["이 PR 이 바꾼 Spec 이 다른 Spec 과 같은 객체를 만들거나 고치는 곳이 없습니다.", ""]

    skipped = []
    if result.get("unrelated"):
        skipped.append(f"이 PR 과 무관한 기존 겹침 {result['unrelated']}건")
    if result.get("shared"):
        kinds = ", ".join(result.get("shared_kinds") or [])
        skipped.append(f"공용 객체({kinds}) 겹침 {result['shared']}건")
    if skipped:
        out += [", ".join(skipped) + "은 경고하지 않았습니다.", ""]

    if result.get("no_table"):
        out.append(f"`## 사용 객체` 표가 없는 Spec **{result['no_table']}건**은 비교에서 뺐습니다.")
    if result.get("name_tbd"):
        out.append(f"이름 미정 **{result['name_tbd']}건**(이름이 비었거나 영문자로 시작하지 않는 행)은 비교에서 뺐습니다.")
    return out


def _render_version_overlap(result: dict) -> list[str]:
    """열린 PR 끼리 문서 판 번호 겹침 절(#315). 경고만 하므로 위반 표는 없다."""
    out = ["", "---", "", "## 판 번호 겹침", ""]
    if result.get("status") == "cannot_check":
        out += [
            "### ⚠️ 검사 불능", "",
            "```", str(result.get("message") or "열린 PR 을 읽지 못했습니다.").strip(), "```", "",
            "다른 열린 PR 과 판 번호가 겹치는지 확인하지 못했습니다. 통과도 위반도 아닙니다. "
            "**문서의 문제가 아닙니다.** 위 문서 검사 결과는 그대로 유효합니다. "
            + ("이 실행을 다시 돌려 보십시오(Re-run). 계속 같으면 저장소 담당자에게 알리십시오."
               if result.get("read_failure") else "저장소 담당자에게 알리십시오."),
        ]
        return out
    warnings = result.get("warnings") or []
    if not warnings:
        out.append(f"열린 PR {result.get('compared', 0)}건과 견주어 보았고 판 번호가 겹치는 곳이 없습니다.")
        return out
    out += [
        "### 참고 — 같은 판 번호를 다른 열린 PR 도 씀 (통과에는 영향 없음)", "",
        f"**{len(warnings)}건**입니다. 먼저 병합되는 쪽이 그 판을 갖습니다.", "",
    ]
    for w in warnings:
        out.append(f"- {_cell(w.get('message'))}")
    return out


def _render_cross_checks(result: dict) -> list[str]:
    """교차 검사 스위치 파일(`rules/cross-checks/switches.yaml`)을 읽지 못한 경우."""
    return [
        "", "---", "", "## 교차 검사 설정", "",
        "### ⚠️ 검사 불능", "",
        "```", str(result.get("message") or "스위치 파일을 읽지 못했습니다.").strip(), "```", "",
        "번호 짝·객체 겹침·판 번호 겹침을 돌릴지 알 수 없어 이 검사들을 하지 않았습니다. 통과도 위반도 아닙니다. "
        "설정 파일을 관리하는 담당자가 고쳐야 합니다.",
    ]


def _render_pairing(result: dict) -> list[str]:
    """SRS·Spec·원장 번호 짝 절(#284). `result` 는 `checker.pairing.check_pairing` 의 결과다."""
    out = ["", "---", "", "## 번호 짝", ""]
    status = result.get("status")
    violations = result.get("violations") or []
    warnings = result.get("warnings") or []

    if status == "cannot_check":
        out += [
            "### ⚠️ 검사 불능",
            "",
            "```",
            str(result.get("message") or "번호 짝을 맞춰 보지 못했습니다.").strip(),
            "```",
            "",
            "SRS·Spec·원장을 읽지 못해 번호가 맞는지 확인하지 못했습니다. 통과도 위반도 아닙니다. "
            "표 머리나 파일 형태를 고치거나, 문서 틀이 맞다면 검사 엔진 담당자에게 알리십시오.",
        ]
        return out

    if violations:
        out += [
            "### ❌ 번호 짝이 어긋남",
            "",
            f"SRS·Spec·원장의 번호가 서로 맞지 않는 곳 **{len(violations)}건**입니다. **문서를 고쳐야 합니다.**",
            "",
            "| 파일 | 내용 |",
            "|---|---|",
        ]
        for item in violations:
            out.append(f"| `{item.get('file')}` | {_cell(item.get('message'))} |")
        out.append("")
    else:
        out += ["SRS·Spec·원장의 번호가 서로 맞습니다.", ""]

    if warnings:
        out += ["### 참고 (통과에는 영향 없음)", "", "아직 작성 중이라 그럴 수 있는 것들입니다.", ""]
        for item in warnings:
            out.append(f"- `{item.get('file')}` — {item.get('message')}")
    return out


def _cell(text: object) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _render_doc(report: dict, code: int) -> str:
    out = [MARKER, "## doc-guard", ""]

    if "summary" not in report:
        # doc-guard 자체가 리포트를 내지 못한 경우다 — 설정 오류든, 검사기 출력을 아예
        # 해석하지 못한 경우든, 예상치 못한 종료코드든 전부 여기로 모은다. 받는 사람이
        # 위반과 다르다: 문서를 올린 팀원이 아니라 규칙·설정을 관리하는 담당자다.
        #
        # `code` 가 아니라 리포트 모양으로 판단한다 — 코드 파일 검사가 실패해도 바깥
        # 종료코드(check_changed.py 가 둘을 합친 것)가 1 이나 2 가 될 수 있는데, 그때
        # doc-guard 자신은 정상적으로 `summary` 를 냈을 수 있기 때문이다.
        out += [
            "### ⚠️ 검사 불능",
            "",
            "```",
            str(report.get("message") or f"검사기가 예상치 못한 코드 {code} 로 끝났습니다.").strip(),
            "```",
            "",
            "**이것은 문서의 문제가 아닙니다.** 규칙 파일이나 설정을 관리하는 담당자가 고쳐야 합니다.",
        ]
        return "\n".join(out)

    summary = report.get("summary", {})
    scoped = summary.get("scoped", 0)
    violations = summary.get("violations", 0)
    skipped = summary.get("skipped", 0)
    skipped_files = [f for f in report.get("files", []) if f.get("status") == "skipped"]

    if scoped == 0:
        if skipped:
            # 관할 안에 자리표시·시스템 파일만 있었다. 대조할 문서는 없지만, 그것을
            # "관할 밖" 이라 하면 왜 아무것도 안 걸렸는지 알 수 없다.
            out += [f"검사할 문서는 없고, 건너뛴 파일 {skipped}건이 있습니다."]
            out += _render_skipped(skipped_files)
        else:
            out += ["검사 대상 문서가 없습니다. doc-guard 관할 밖의 변경입니다."]
        return "\n".join(out)

    if violations == 0:
        line = f"문서 {scoped}건을 검사했고 모두 템플릿을 따릅니다."
        if skipped:
            line += f" / 건너뛴 파일 {skipped}건"
        out += [line]
        out += _render_skipped(skipped_files)
        return "\n".join(out)

    out += [
        "### ❌ 템플릿 위반",
        "",
        f"문서 {scoped}건 중 **{violations}건**이 템플릿을 따르지 않습니다. **문서를 고쳐야 합니다.**",
        "",
    ]
    for entry in report.get("files", []):
        if entry.get("status") != "violation":
            continue
        out += [f"### `{entry.get('file')}`", "", f"유형: **{entry.get('type')}**", ""]
        for v in entry.get("violations", []):
            out.append(f"- {v.get('message')}")
            expected, actual = v.get("expected"), v.get("actual")
            if expected not in (None, ""):
                out.append(f"  - 기대: `{expected}`")
            if actual not in (None, ""):
                out.append(f"  - 실제: `{actual}`")
        template = entry.get("template")
        if template:
            out += ["", f"쓸 템플릿: `{template}`"]
        out.append("")

    out += _render_skipped(skipped_files)
    out += ["---", "", "위 템플릿을 보고 문서를 고친 뒤 다시 올리십시오."]
    return "\n".join(out)


def _render_skipped(skipped_files: list[dict]) -> list[str]:
    """건너뛴 파일을 짧게 알린다.

    통과와 위반 코멘트 둘 다에서 부른다. 조용히 건너뛰면 "왜 이 파일은 검사 결과에
    안 보이지" 라는 의문이 남으므로, 위반이 없어도 이유와 함께 적어 둔다.
    """
    if not skipped_files:
        return []
    lines = ["", "### 건너뛴 파일", ""]
    for f in skipped_files:
        lines.append(f"- `{f.get('file')}` — {f.get('reason', '')}")
    return lines


def _render_code_rules(section: dict) -> list[str]:
    """공통 개발 규칙(CR-001, CR-002) 절을 만든다.

    `section` 은 `{"report": <checker.code_rules 의 리포트>, "exit": <그 자신의 종료코드>}`
    모양이다. doc-guard 절과 마찬가지로, 검사기가 위반과 검사 불능 중 어느 쪽으로
    끝났는지는 이 절 자신의 데이터로 정하고 바깥 종료코드에 기대지 않는다.
    """
    inner = section.get("report") or {}
    exit_code = section.get("exit")
    out = ["", "---", "", "## 공통 개발 규칙", ""]

    if "summary" not in inner or exit_code not in (0, 1):
        out += [
            "### ⚠️ 검사 불능",
            "",
            "```",
            str(inner.get("message") or f"검사기가 예상치 못한 코드 {exit_code} 로 끝났습니다.").strip(),
            "```",
            "",
            "**이것은 코드의 문제가 아닙니다.** 검사 엔진이나 설정을 관리하는 담당자가 고쳐야 합니다.",
        ]
        return out

    summary = inner.get("summary", {})
    checked = summary.get("checked", 0)
    violations = summary.get("violations", 0)
    allowed = summary.get("allowed", 0)

    warn_lines = _render_code_warnings(inner)

    if violations == 0:
        line = f"코드 {checked}건을 검사했고 모두 공통 개발 규칙(CR-001, CR-002)을 지켰습니다."
        if allowed:
            line += f" / 예외로 인정된 발견 {allowed}건"
        out += [line]
        out += warn_lines
        return out

    out += [
        "### ❌ 공통 개발 규칙 위반",
        "",
        f"코드 {checked}건 중 **{violations}건**이 공통 개발 규칙을 어겼습니다. "
        "**코드를 고쳐야 합니다.**",
        "",
    ]
    for entry in inner.get("files", []):
        if entry.get("status") != "violation":
            continue
        out += [f"### `{entry.get('file')}`", ""]
        for f in entry.get("findings", []):
            if f.get("allowed") or f.get("level") == "warn":  # 경고는 아래 경고 절에 따로 나온다
                continue
            out.append(f"- [{f.get('rule')}] {f.get('line')}:{f.get('col')} {f.get('message')}")
            fix = f.get("fix")
            if fix:
                out.append(f"  - 고치기: {fix}")
            note = f.get("note")
            if note:
                out.append(f"  - 참고: {note}")
        out.append("")

    out += [
        "---",
        "",
        "정말 예외라면 같은 줄이나 바로 위 줄에 `harness:allow CR-00N <이유>` 주석을 "
        "남기고 다시 올리십시오(이유는 반드시 적어야 합니다).",
    ]
    out += warn_lines
    return out


def _render_code_warnings(inner: dict) -> list[str]:
    """`level: warn` 인 발견(CR-009)을 위반과 따로 보인다. 종료코드와 병합을 막지 않는다."""
    items = []
    for entry in inner.get("files", []):
        for f in entry.get("findings", []):
            if f.get("allowed") or f.get("level") != "warn":
                continue
            items.append((entry.get("file"), f))
    if not items:
        return []
    out = [
        "",
        "### ⚠️ 경고 (병합을 막지는 않습니다)",
        "",
        f"공통 개발 규칙 경고 **{len(items)}건**입니다. 의도한 것이면 `harness:allow` 로 이유를 남기고, "
        "아니면 고치십시오.",
        "",
    ]
    for file, f in items:
        out.append(f"- [{f.get('rule')}] `{file}` {f.get('line')}:{f.get('col')} {f.get('message')}")
        fix = f.get("fix")
        if fix:
            out.append(f"  - 고치기: {fix}")
        note = f.get("note")
        if note:
            out.append(f"  - 참고: {note}")
    return out


def exit2_cause(report: dict) -> str:
    """종료코드 2 의 원인이 "다시 돌리면 풀리는 읽기 실패" 뿐이면 `retry`, 아니면 `config`(규칙·설정·엔진).

    판정 스텝이 안내 문구를 가르는 데 쓴다. `retry` 는 열린 PR 을 읽지 못해 판 번호 겹침만 확인하지 못한
    경우다(`version_overlap.read_failure`). 다른 검사 불능이 하나라도 섞여 있으면 `config` 다.
    """
    version = report.get("version_overlap") or {}
    if "summary" not in report or not (version.get("status") == "cannot_check" and version.get("read_failure")):
        return "config"
    code_rules = report.get("code_rules")
    if code_rules and code_rules.get("exit") not in (0, 1):
        return "config"
    for key in ("pairing", "overlap"):
        if (report.get(key) or {}).get("status") == "cannot_check":
            return "config"
    return "config" if report.get("cross_checks") else "retry"


def main() -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    if len(sys.argv) == 3 and sys.argv[1] == "--exit2-cause":
        try:
            print(exit2_cause(json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            print("config")
        return 0

    if len(sys.argv) < 3:
        print("사용법: render_report.py <리포트 json> <종료코드>", file=sys.stderr)
        return 2

    report_path = Path(sys.argv[1])
    code = int(sys.argv[2])

    try:
        raw = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        # 리포트 파일 자체를 못 읽었다. 검사를 통과한 것으로 보이면 안 되므로 검사
        # 불능으로 렌더링한다(#13).
        print(render({"message": f"{report_path} 를 읽지 못했습니다: {exc}"}, 2))
        return 0

    try:
        report = json.loads(raw)
    except json.JSONDecodeError:
        # 검사기 출력을 해석하지 못했다. 종료코드가 무엇이었든 이것도 검사 불능이다 —
        # 무엇을 검사했는지조차 알 수 없는 상태를 통과나 위반으로 뭉개면 안 된다.
        snippet = raw.strip()[:1000]
        print(render({"message": "검사기의 출력을 해석하지 못했습니다.\n\n" + snippet}, 2))
        return 0

    print(render(report, code))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
