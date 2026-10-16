"""원본 md 의 열·소제목이 고객사 양식 지도 밖이면 거절한다(#316).

산출물은 고객사 양식을 따른다. 양식 지도(`templates/forms/<양식>.yaml`)에 없는 열이나 소제목이
원본(SRS.md, Spec 의 `## 양식 항목`)에 들어오면 엑셀로 나갈 자리가 없다. 이 규칙은 그걸 저장(훅)과
PR(doc-guard)에서 막는다. 산출(`checker.export`)도 같은 목록으로 멈춘다 — 두 곳이 같은 함수
(`srs_allowed`, `srs_offenders`, `spec_offenders`)를 쓴다.

params (한글 키, 영문 키도 받는다):
  원본 / source         `SRS` 또는 `작업본` (필수)
  지도_폴더 / maps      양식 지도 폴더. 규칙 파일이 있는 폴더 기준. 기본 `../templates/forms`
  양식 / form           (SRS) 지도가 둘 이상일 때 쓸 지도 이름(파일 이름의 stem)
  기본_소제목 / details (SRS) 양식 지도가 없는 저장소에서 상세 절에 허용할 소제목 (예: 설명, 완료 조건)

`원본: SRS` — `## 요구사항` 표 머리글과 `### REQ-n` 아래 `#### <소제목>` 을 본다.
- 허용 표 열 = `ID` + 지도 `열` + 지도 `md_전용` + 엔진 기본 md 전용 `다음 단계`.
- 허용 소제목 = 지도 `열`(번호 열 제외) + md 전용.
- 지도 열이 표에 빠진 것은 허용이다(#243). 모르는 열만 위반이다.
- `원본: SRS` 지도가 없는 저장소는 SRS 틀(템플릿)의 요구사항 표 열 + `다음 단계` 가 허용 열이고,
  소제목은 틀의 열 + `기본_소제목` 이다.

`원본: 작업본` — Spec 의 `## 양식 항목` 아래 `### <양식> · <시트>` 를 본다. 양식 지도가 없거나, 시트·칸·
`#### <표·서술>`·표 열이 지도에 없으면 위반이다. `## 양식 항목` 절이 없는 Spec 은 통과한다(양식을 안 쓰는 건).

판단:
- 지도 폴더가 있는데 지도를 못 읽는다(깨진 yaml, 필수 키 없음) → ConfigError(종료코드 2, 검사 불능).
  통과도 위반도 아니다. 원본 파일을 못 읽는 것도 같다.
- SRS 에 `## 요구사항` 절이나 표가 없다 → 이 규칙은 말하지 않는다(필수 절은 `required_sections` 가 본다).
- 표·소절 구조가 깨져 열을 읽을 수 없다 → 위반(문서를 고쳐야 한다. 산출도 같은 이유로 거부한다).
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from checker import blank_template, export
from checker.model import ConfigError, Violation
from checker.rules import prepare, rule
from checker.rules.md_table import read_section_table

_ALLOWED = {
    "원본", "source", "지도_폴더", "maps", "양식", "form", "기본_소제목", "details",
}
DEFAULT_MAPS = "../templates/forms"
NEXT_FIX_TEMPLATE = (
    "다음: 틀(templates/harness/SRS.md)에 있는 열 이름으로 고치거나, 정말 필요한 열이면 "
    "고객사 양식 지도(templates/forms/)를 먼저 만든다."
)


def _get(params: dict, *names: str):
    for n in names:
        if params.get(n) is not None:
            return params[n]
    return None


def _source(params: dict) -> str:
    raw = str(_get(params, "원본", "source") or "").strip()
    if raw.upper() == "SRS":
        return "SRS"
    if raw in ("작업본", "spec", "Spec", "SPEC"):
        return "작업본"
    raise ConfigError("form_columns 규칙의 '원본' 은 SRS 또는 작업본이어야 한다")


def _check_keys(params: dict) -> None:
    stray = [k for k in params if k not in _ALLOWED and not str(k).startswith("_")]
    if stray:
        raise ConfigError(
            f"form_columns 규칙에 모르는 키가 있다: {', '.join(map(str, stray))} "
            f"(쓸 수 있는 키: 원본, 지도_폴더, 양식, 기본_소제목)"
        )


@prepare("form_columns")
def from_template(params: dict, template: Path | None) -> dict:
    """`원본: SRS` 면 템플릿(SRS 틀)의 요구사항 표 열을 기본 열로 뽑아 둔다."""
    params = dict(params)
    _check_keys(params)
    if _source(params) != "SRS":
        return params
    if template is None:
        raise ConfigError("form_columns 규칙(원본: SRS)은 SRS 틀을 템플릿으로 읽는다 — '템플릿' 이 있어야 한다")
    text = template.read_text(encoding="utf-8-sig")
    found, table = read_section_table(text, "요구사항")
    if not found or table is None:
        raise ConfigError(f"템플릿 {template.name} 에 `## 요구사항` 표가 없어 기본 열을 읽을 수 없다")
    params["_기본_열"] = [export.norm(h) for h in table[0]]
    return params


def _read_yaml(path: Path, what: str):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"{what} {path.name} 를 읽지 못해 양식 밖 열을 검사할 수 없다: {exc}") from exc


def _valid_map(data, path: Path) -> dict:
    """검사가 읽는 모양(시트·칸·표·서술·열)이 맞는지 본다. 틀리면 검사 불능이다(traceback 으로 죽지 않는다)."""
    def bad(what: str):
        raise ConfigError(f"양식 지도 {path.name} 의 {what} 모양이 틀려 양식 밖 열을 검사할 수 없다")

    if not isinstance(data, dict) or not isinstance(data.get("시트"), list):
        raise ConfigError(f"양식 지도 {path.name} 에 `시트` 목록이 없어 양식 밖 열을 검사할 수 없다")
    for s in data["시트"]:
        if not isinstance(s, dict) or "이름" not in s:
            bad("시트(`이름` 없음)")
        for key, name_key in (("칸", "항목"), ("표", "이름"), ("서술", "이름")):
            items = s.get(key)
            if items is None:
                continue
            if not isinstance(items, list):
                bad(f"시트 {s['이름']!r} 의 `{key}`(목록이어야 한다)")
            for it in items:
                if not isinstance(it, dict) or name_key not in it:
                    bad(f"시트 {s['이름']!r} 의 `{key}`(`{name_key}` 없음)")
        for t in s.get("표") or []:
            if t.get("열") is not None and not isinstance(t["열"], dict):
                bad(f"표 {t['이름']!r} 의 `열`(이름: 열 문자 사전이어야 한다)")
            if t.get("md_전용") is not None and not isinstance(t["md_전용"], list):
                bad(f"표 {t['이름']!r} 의 `md_전용`(목록이어야 한다)")
    # 새 키(`비우기`·`그림_지우기`·`유지`·`외부_참조_지우기`·`견본_검사`·서술 `열`)는 산출과 같은 검증으로 본다.
    problems = blank_template.map_problems(data)
    if problems:
        raise ConfigError(
            f"양식 지도 {path.name} 가 틀려 양식 밖 열을 검사할 수 없다: " + "; ".join(m for _, m in problems)
        )
    return data


def _maps_folder(params: dict) -> Path:
    rules_dir = params.get("_rules_dir")
    if not rules_dir:
        raise ConfigError("form_columns 규칙이 규칙 파일 위치를 몰라 양식 지도 폴더를 찾을 수 없다")
    explicit = _get(params, "지도_폴더", "maps")
    folder = (Path(rules_dir) / str(explicit or DEFAULT_MAPS)).resolve()
    # 명시한 폴더가 없으면 오타일 수 있다. 조용히 틀 기준으로 갈아타면 멀쩡한 문서가 위반이 된다.
    if explicit and not folder.is_dir():
        raise ConfigError(f"form_columns 규칙의 지도_폴더 '{explicit}' 가 없어 양식 밖 열을 검사할 수 없다({folder})")
    return folder


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path.name} 를 읽지 못해 양식 밖 열을 검사할 수 없다: {exc}") from exc


def _v(expected, actual, message: str) -> Violation:
    return Violation(rule="form_columns", expected=expected, actual=actual, message=message)


@rule("form_columns")
def check(path: Path, params: dict) -> list[Violation]:
    _check_keys(params)
    text = _read_text(path)
    if _source(params) == "SRS":
        return _check_srs(text, params)
    return _check_spec(text, params)


# ---------------------------------------------------------------- SRS

def _srs_tables(params: dict) -> tuple[str, list[dict]] | None:
    """(지도 이름, 지도의 `원본: SRS` 표들). `원본: SRS` 지도가 없으면 None(기본 SRS 틀 기준)."""
    folder = _maps_folder(params)
    if not folder.is_dir():
        return None
    found: dict[str, dict] = {}
    for f in sorted(folder.glob("*.yaml")):
        data = _valid_map(_read_yaml(f, "양식 지도"), f)
        if export.is_srs_map(data):
            found[f.stem] = data
    want = _get(params, "양식", "form")
    if want is not None:
        if want not in found:
            raise ConfigError(f"form_columns 규칙이 가리킨 양식 지도 '{want}' 가 {folder} 에 없거나 원본이 SRS 가 아니다")
        found = {want: found[want]}
    if not found:
        return None
    if len(found) > 1:
        raise ConfigError(
            f"원본이 SRS 인 양식 지도가 여럿이라({', '.join(found)}) 어느 것이 기준인지 알 수 없다 — "
            f"rules 의 form_columns 에 '양식: <지도 이름>' 을 적는다"
        )
    name, data = next(iter(found.items()))
    tabs = [
        t for s in data["시트"] for t in (s.get("표") or [])
        if export.norm(str(t.get("원본", ""))).upper() == "SRS"
    ]
    return name, tabs


def _check_srs(text: str, params: dict) -> list[Violation]:
    try:
        srs = export.parse_srs(text)
    except export.ExportError as exc:
        if isinstance(exc, export.SrsPartMissing):
            return []  # 필수 절은 required_sections 소관이다
        return [_v(None, None, f"SRS 표·상세 절 구조가 깨져 열을 검사하지 못했다: {exc.reason}")]

    mapped = _srs_tables(params)
    if mapped is not None:
        name, tabs = mapped
        targets = []
        for t in tabs:
            try:
                header_ok, detail_ok = export.srs_allowed(t)
            except (TypeError, AttributeError, KeyError, ValueError) as exc:
                raise ConfigError(f"양식 지도 {name} 의 SRS 표 정의를 읽지 못해 양식 밖 열을 검사할 수 없다: {exc}") from exc
            targets.append((f"양식 지도 {name}", header_ok, detail_ok, export.NEXT_FIX_MAP))
    else:
        base = params.get("_기본_열")
        if not base:
            raise ConfigError("form_columns 규칙이 SRS 틀의 기본 열을 읽지 못했다 — 템플릿을 확인한다")
        cols = [c for c in base if c != "ID"]
        extra = [export.SRS_NEXT_STEP_COL] if export.SRS_NEXT_STEP_COL not in cols else []
        details = [export.norm(x) for x in (_get(params, "기본_소제목", "details") or [])]
        targets = [(
            "SRS 틀(양식 지도 없음)",
            ["ID"] + cols + extra,
            list(dict.fromkeys(cols + details + [export.SRS_NEXT_STEP_COL])),
            NEXT_FIX_TEMPLATE,
        )]

    out: list[Violation] = []
    for label, header_ok, detail_ok, nxt in targets:
        bad_header, bad_detail = export.srs_offenders(srs, header_ok, detail_ok)
        if bad_header:
            out.append(_v(
                ", ".join(header_ok), ", ".join(bad_header),
                f"양식 밖 열: {', '.join(bad_header)}. 허용({label}): {', '.join(header_ok)}. {nxt}",
            ))
        for rid, bad in bad_detail.items():
            names = ", ".join(f"`#### {x}`" for x in bad)
            out.append(_v(
                ", ".join(detail_ok), ", ".join(bad),
                f"양식 밖 소제목: {names} ({rid} 상세 절). 허용({label}): {', '.join(detail_ok)}. {nxt}",
            ))
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------- 작업본(Spec)

def _check_spec(text: str, params: dict) -> list[Violation]:
    if not re.search(r"^##\s+양식 항목\s*$", text, re.M):
        return []  # 양식을 쓰지 않는 Spec
    try:
        forms = export.parse_spec(text)
    except export.ExportError as exc:
        return [_v(None, None, f"`## 양식 항목` 구조가 깨져 열을 검사하지 못했다: {exc.reason}")]

    folder = _maps_folder(params)
    if not folder.is_dir():
        raise ConfigError(f"양식 지도 폴더 {folder} 가 없어 Spec 의 `## 양식 항목` 을 검사할 수 없다")
    out: list[Violation] = []
    for form, sheets in forms.items():
        where = f"`### {form} · …`"
        try:
            export._check_form_name(form)
        except export.ExportError as exc:
            out.append(_v(None, form, f"{where}: {exc.reason}"))
            continue
        map_path = folder / f"{form}.yaml"
        if not map_path.is_file():
            out.append(_v(
                "양식 지도(templates/forms/<양식>.yaml)가 있는 양식", form,
                f"양식 밖 양식: {form}. 양식 지도 {map_path.name} 가 {folder.name}/ 에 없다. "
                f"다음: 지도가 있는 양식 이름으로 고치거나, 지도를 먼저 만든다.",
            ))
            continue
        fmap = _valid_map(_read_yaml(map_path, "양식 지도"), map_path)
        if export.is_srs_map(fmap):
            out.append(_v("원본이 Spec 인 양식", form,
                          f"양식 밖 양식: {form} 은 원본이 SRS 인 지도라 Spec 의 `## 양식 항목` 에 쓸 수 없다. "
                          f"다음: SRS 요구사항 표로 옮긴다."))
            continue
        map_sheets = {export.norm(s["이름"]): s for s in fmap["시트"]}
        for sname, (sec, subs) in sheets.items():
            smap = map_sheets.get(sname)
            if smap is None:
                out.append(_v(", ".join(map_sheets), sname,
                              f"양식 밖 시트: {form} · {sname}. 허용: {', '.join(map_sheets)}. {export.NEXT_FIX_MAP}"))
                continue
            try:
                off = export.spec_offenders(sec, subs, smap)
            except (KeyError, TypeError, AttributeError, ValueError) as exc:
                raise ConfigError(f"양식 지도 {map_path.name} 의 시트 {sname!r} 정의를 읽지 못해 검사할 수 없다: {exc!r}") from exc
            except export.ExportError as exc:
                out.append(_v(None, None, f"{form} · {sname}: 표 구조가 깨져 열을 검사하지 못했다: {exc.reason}"))
                continue
            for kind, name, ok in off:
                out.append(_v(", ".join(ok), name,
                              f"양식 밖 {kind}: {name}({form} · {sname}). 허용: {', '.join(ok) or '(없음)'}. {export.NEXT_FIX_MAP}"))
    return list(dict.fromkeys(out))
