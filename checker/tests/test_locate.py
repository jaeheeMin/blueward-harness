"""기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더) 찾기와 --auto 모드.

훅과 GitHub Actions 가 둘 다 이 판단을 하므로 한 벌만 두고 양쪽이 쓴다.
"""
from __future__ import annotations

from pathlib import Path

from checker.locate import find_standards_root, group_by_standards_root


def _standards_root(base: Path, name: str) -> Path:
    root = base / name
    (root / "templates").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / "docs").mkdir()
    return root


def test_templates_와_rules_를_함께_가진_폴더를_찾는다(tmp_path):
    root = _standards_root(tmp_path, "hanbit")
    doc = root / "docs" / "가" / "나.md"
    doc.parent.mkdir(parents=True)
    doc.touch()
    assert find_standards_root(doc) == root.resolve()


def test_둘_중_하나만_있으면_기준_폴더가_아니다(tmp_path):
    """templates 만 있고 rules 가 없으면 대조는 되지만 강제할 규칙이 없다."""
    half = tmp_path / "반쪽"
    (half / "templates").mkdir(parents=True)
    doc = half / "문서.md"
    doc.touch()
    assert find_standards_root(doc) is None


def test_기준_폴더_밖이면_없다(tmp_path):
    doc = tmp_path / "README.md"
    doc.touch()
    assert find_standards_root(doc) is None


def test_가장_가까운_기준_폴더를_고른다(tmp_path):
    """저장소 루트에도 templates/rules 가 있고 기준 폴더에도 있으면 가까운 쪽이다."""
    outer = _standards_root(tmp_path, "바깥")
    inner = _standards_root(outer, "안쪽")
    doc = inner / "docs" / "문서.md"
    doc.touch()
    assert find_standards_root(doc) == inner.resolve()


def test_기준_폴더별로_묶는다(tmp_path):
    a = _standards_root(tmp_path, "가회사")
    b = _standards_root(tmp_path, "나회사")
    da, db = a / "docs" / "1.md", b / "docs" / "2.md"
    orphan = tmp_path / "README.md"
    for f in (da, db, orphan):
        f.touch()

    grouped, orphans = group_by_standards_root([da, db, orphan])
    assert set(grouped) == {a.resolve(), b.resolve()}
    assert grouped[a.resolve()] == [da]
    assert orphans == [orphan]
