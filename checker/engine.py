"""평면 규칙을 돌려 위반을 모은다.

여기는 문서 유형도 템플릿도 모른다. 로더가 이미 유형 묶음을 펼치고 템플릿에서 기대값을
뽑아 두었으므로, 엔진이 하는 일은 '이 파일이 어느 관할에 드는가' 와 '거기 달린 규칙들을
돌린다' 둘뿐이다. 규칙 종류가 늘어도 이 파일은 바뀌지 않는다.
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from checker import rules as rule_registry
from checker.model import ConfigError, DocType, Violation

OUT_OF_SCOPE = "out_of_scope"
PASS = "pass"
VIOLATION = "violation"
SKIPPED = "skipped"

# 관할 안에 있어도 문서로 보지 않는 자리표시·시스템 파일. 회사가 만드는 것이 아니라
# 도구(git, 탐색기, macOS)가 자동으로 흘려 두는 것들이라 목록을 짧게 못 박는다.
# 늘어나지 않는다는 확신이 있는 이 목록만 예외로 두고, 그 밖의 읽지 못하는 형식은
# (`.hwp`, `.pdf` 등) 여전히 검사 불능이다 — 검사가 필요한 진짜 산출물을 이 예외로
# 슬쩍 통과시키면 안 되기 때문이다("검사 불능을 통과로 뭉개지 않는다" 원칙).
SKIPPED_BASENAMES = frozenset({
    ".gitkeep", ".keep", ".gitignore", ".ds_store", "thumbs.db", "desktop.ini",
})
SKIPPED_REASON = "자리표시·시스템 파일이라 문서로 보지 않는다"


def _matches(relative: str, pattern: str) -> bool:
    """glob 하나를 경로에 맞춰 본다.

    구분자를 `/` 로 맞춘 뒤 본다. 훅은 Windows 에서, Actions 는 Linux 에서 도는데 같은
    규칙 파일이 양쪽에서 같게 동작해야 한다. `**` 는 fnmatch 가 `*` 와 구분하지 않으므로
    여러 단계를 건너뛰는 뜻으로 그대로 쓴다.
    """
    path = relative.replace("\\", "/")
    pattern = pattern.replace("\\", "/")
    if fnmatch(path, pattern):
        return True
    # `docs/**` 처럼 끝이 열린 꼴은 그 아래 전부를 뜻하게 한다.
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3].rstrip("/") + "/")
    return False


def resolve(relative: str, types: list[DocType]) -> DocType | None:
    """파일이 어느 문서 유형의 관할에 드는지 정한다.

    둘 이상에 걸리면 고르지 않고 설정 오류로 끊는다. 이 제품의 출력은 "이 템플릿을 쓰세요"
    라서, 조용히 한쪽을 고르면 틀렸을 때 사람을 엉뚱한 템플릿으로 안내한다. 아무 신호 없이
    틀린 답을 주느니 시끄럽게 실패하는 편이 낫다.
    """
    hits = [t for t in types if _matches(relative, t.jurisdiction)]
    if not hits:
        return None
    if len(hits) > 1:
        names = ", ".join(f"'{t.name}'({t.jurisdiction})" for t in hits)
        raise ConfigError(f"{relative} 이 여러 유형의 관할에 든다 — {names}")
    return hits[0]


def check_file(path: Path, relative: str, types: list[DocType]) -> dict:
    doc_type = resolve(relative, types)
    if doc_type is None:
        return {
            "file": relative,
            "type": None,
            "template": None,
            "status": OUT_OF_SCOPE,
            "violations": [],
        }

    if Path(relative).name.lower() in SKIPPED_BASENAMES:
        # 관할 판정 뒤에 본다. 관할 밖의 `.gitkeep` 은 여전히 out_of_scope 다 — 대조할
        # 기준 자체가 없기 때문이고, 그 의미를 이 예외로 바꾸지 않는다.
        return {
            "file": relative,
            "type": doc_type.name,
            "template": doc_type.template or None,
            "status": SKIPPED,
            "reason": SKIPPED_REASON,
            "violations": [],
        }

    violations: list[Violation] = []
    for r in doc_type.rules:
        fn = rule_registry.get(r.kind)
        params = dict(r.params)
        params["_relative"] = relative
        violations.extend(fn(path, params))

    return {
        "file": relative,
        "type": doc_type.name,
        # 위반이 없어도 유형과 템플릿을 싣는다. 문서를 올리는 사람은 위반을 알기 전에
        # "뭘 보고 쓰지" 부터 궁금하기 때문이다. 템플릿을 쓰지 않는 유형도 있으므로
        # (템플릿 자체를 검사하는 경우) 없으면 null 이다.
        "template": doc_type.template or None,
        "status": VIOLATION if violations else PASS,
        "violations": [v.to_json() for v in violations],
    }


def summarize(files: list[dict]) -> dict:
    """상태 목록에서 요약을 낸다.

    `check()` 와, 기준 폴더별로 나눠 돌린 뒤 합치는 `cli._check_auto` 가 같은 계산을 쓰도록
    한 곳에 둔다. `skipped` 는 관할 안에 있었지만 자리표시·시스템 파일이라 문서로 보지
    않은 것이다 — 검사한 것(`scoped`)으로도, 관할 밖으로도 세면 이중으로 뭉개진다.
    """

    def count(status: str) -> int:
        return sum(1 for f in files if f["status"] == status)

    return {
        "scoped": count(PASS) + count(VIOLATION),
        "passed": count(PASS),
        "violations": count(VIOLATION),
        "skipped": count(SKIPPED),
        "out_of_scope": count(OUT_OF_SCOPE),
    }


def check(paths: list[tuple[Path, str]], types: list[DocType]) -> dict:
    files = [check_file(p, rel, types) for p, rel in paths]
    return {"summary": summarize(files), "files": files}
