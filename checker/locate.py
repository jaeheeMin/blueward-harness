"""문서가 속한 기준 폴더를 찾는다.

기준 폴더란 `templates/` 와 `rules/` 를 함께 가진 폴더, 즉 Project Repository 의
꼭대기를 말한다. 훅과 GitHub Actions 가 둘 다 "이 파일은 어느 기준 폴더 것인가 →
그 기준을 쓴다" 를 판단해야 한다. 한 벌만 두고 양쪽이 쓴다.

이것은 `engine.py` 가 아니라 껍데기를 향한 층에 둔다. 엔진은 관할 glob 과 규칙만 알고
폴더 규약은 모른다. 규약을 아는 것은 호출부의 몫이고, `cli.py` 가 그 호출부를 위한
얇은 편의를 제공하는 자리다.
"""
from __future__ import annotations

from pathlib import Path

# 기준 폴더는 이 둘을 함께 가진 디렉터리다. 기준(templates)과 규칙(rules)이 한 자리에
# 있다는 것이 곧 "이 아래가 doc-guard 의 소관" 이라는 뜻이다.
MARKERS = ("templates", "rules")


def find_standards_root(path: Path) -> Path | None:
    """문서에서 위로 올라가며 기준 폴더를 찾는다. 없으면 None.

    없다는 것은 대조할 기준이 없다는 뜻이므로 검사 대상이 아니다. 이 판단에 엔진이
    필요 없다는 점이 중요하다. 대부분의 파일은 여기서 걸러지므로, 파일 하나를 볼 때마다
    규칙을 읽어 들이지 않는다.
    """
    try:
        start = path.resolve()
    except OSError:
        start = path
    for parent in [start.parent, *start.parent.parents]:
        if all((parent / marker).is_dir() for marker in MARKERS):
            return parent
    return None


def group_by_standards_root(paths: list[Path]) -> tuple[dict[Path, list[Path]], list[Path]]:
    """파일들을 기준 폴더별로 묶는다. 어디에도 속하지 않는 것은 따로 돌려준다."""
    grouped: dict[Path, list[Path]] = {}
    orphans: list[Path] = []
    for p in paths:
        root = find_standards_root(p)
        if root is None:
            orphans.append(p)
        else:
            grouped.setdefault(root, []).append(p)
    return grouped, orphans
