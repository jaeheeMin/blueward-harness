"""사람이 양식 pptx 에 써서 올린 매뉴얼을 작업본(md)으로 읽어 들이는 `checker.import_pptx` 를 검증한다(이슈 #742).

실제 사람이 쓴 pptx 샘플이 없다. 양식 모양 pptx 를 `test_export_pptx` 의 시험 양식으로 산출한 뒤, 사람이 손댈 만한 경우(칸 조금 옮김,
메모 글상자 추가, 칸 지움, 여러 줄, 쪽 넘김, 다른 파일)를 python-pptx 로 일부러 만들어 읽는다.
"""
from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Pt

from checker import export, import_pptx
from checker.tests.test_export_pptx import MAP, RULES, _make_template, _png

LOB = "Production(생산)"
TITLE = "생산계획 보드"
PPTX_NAME = f"M_{LOB}_{TITLE}_v0.1.pptx"
IMG = "docs/manual/img/out"  # 그림 위치는 캡처 도구(manual_capture.image_rel)와 같다: docs/manual/img/<작업본 폴더 이름>/
PNG_A = _png((0, 150, 0), (320, 200))
PNG_B = _png((150, 0, 150), (100, 200))

BOOT = """\
| DEV | 제목 |
|---|---|
| 미정 | 미정 |
"""


def _screen(title, desc, notes, work="계획 관리", img=None):
    return {"title": title, "work": work, "desc": desc, "notes": notes, "img": img or f"{IMG}/{title.replace('/', '_')}_v0.1.png"}


def _canon(screens, lob=LOB, title=TITLE, toc_lob=None) -> str:
    """import 가 쓰는 작업본 모양(정본)을 시험에서 따로 적은 것."""
    out = [f"# {title}", "", "버전: 0.1", "", "## 묶은 개발 건", "", BOOT, "## 양식 항목", "",
           "### 시험매뉴얼 · 표지", "", "| 항목 | 값 |", "|---|---|", f"| LoB | {lob} |", f"| 제목 | {title} |", "",
           "### 시험매뉴얼 · 목차", "", "| 항목 | 값 |", "|---|---|", f"| LoB | {toc_lob or lob} |", ""]
    for s in screens:
        multi = "\n" in s["desc"]
        out += [f"### 시험매뉴얼 · 본문 · {s['title']}", "", "| 항목 | 값 |", "|---|---|", f"| 업무명 | {s['work']} |",
                f"| 화면 제목 | {s['title']} |"]
        if not multi:
            out.append(f"| 기능 설명 | {s['desc']} |")
        out.append("")
        if multi:
            out += ["#### 기능 설명", "", s["desc"], ""]
        out += ["#### 그림", "", s["img"], "", "#### 번호 설명", ""]
        for n, t in enumerate(s["notes"], 1):
            out.append(f"{n}. " + t.replace("\n", "\n   "))
        out.append("")
    out += ["### 시험매뉴얼 · 끝", "", "해당 없음"]
    return "\n".join(out) + "\n"


SCREENS = [
    _screen("첫째 제목", "첫째 화면 설명입니다.", ["하나", "둘"]),
    _screen("둘째 제목", "둘째 화면 설명입니다.", ["메뉴 경로를 따라 들어간다.\n다음 줄이다.", "둘", "셋", "넷", "다섯", "여섯", "일곱"]),
]


IMP_MAP = MAP.replace("  파일명:", "  작업본_자리: 제목\n  파일명:", 1)  # 폴더에 자리가 없는 시험 지도라 작업본 이름 자리를 지도에 적는다


def _project(root: Path, map_text: str = IMP_MAP) -> Path:
    (root / "templates" / "forms").mkdir(parents=True)
    (root / "rules").mkdir()
    (root / "templates" / "forms" / "시험매뉴얼.yaml").write_text(map_text, encoding="utf-8")
    (root / "rules" / "test.yaml").write_text(RULES, encoding="utf-8")
    _make_template(root / "templates" / "시험.pptx")
    return root


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    return _project(tmp_path / "p1")


@pytest.fixture
def proj2(tmp_path: Path) -> Path:
    return _project(tmp_path / "p2")


def _exported(proj: Path, capsys, spec: str, pics: dict[str, bytes] | None = None, name: str = "생산계획 보드.md") -> Path:
    """작업본을 쓰고 export 로 pptx 를 만든다. 돌려주는 것은 산출 pptx 경로."""
    for rel, data in (pics or {f"{IMG}/첫째 제목_v0.1.png": PNG_A, f"{IMG}/둘째 제목_v0.1.png": PNG_B}).items():
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_bytes(data)
    p = proj / "docs" / "out" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(spec, encoding="utf-8", newline="\n")
    code = export.main(["--spec", str(p), "--root", str(proj)])
    rep = json.loads(capsys.readouterr().out)
    assert code == 3 and rep["status"] == "warning", rep
    return proj / rep["files"][0]


def _upload(tmp_path: Path, src: Path, mutate=None, name: str | None = None) -> Path:
    """산출 pptx 를 고쳐(사람이 손댄 것처럼) 다른 폴더에 올린 파일로 저장한다."""
    prs = Presentation(str(src))
    if mutate:
        mutate(prs)
    dst = tmp_path / "upload" / (name or src.name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(dst))
    return dst


def _imp(proj: Path, pptx: Path, capsys, *extra: str):
    code = import_pptx.main(["--pptx", str(pptx), "--root", str(proj), *extra])
    out = capsys.readouterr().out
    assert out.count("\n") == 1, "stdout 은 JSON 한 줄이어야 한다"
    return code, json.loads(out)


def _find(slide, prefix: str):
    hits = [s for s in slide.shapes if s.has_text_frame and s.text_frame.text.startswith(prefix)]
    assert len(hits) == 1, (prefix, [s.text_frame.text for s in slide.shapes if s.has_text_frame])
    return hits[0]


def _body(prs) -> list:
    return list(prs.slides)[2:-1]


def _deck(prs) -> list[list[str]]:
    return [sorted(export.norm(s.text_frame.text) for s in sl.shapes if s.has_text_frame and s.text_frame.text.strip()) for sl in prs.slides]


def _written(proj: Path) -> list[str]:
    return sorted(p.relative_to(proj).as_posix() for p in (proj / "docs").rglob("*") if p.is_file()) if (proj / "docs").exists() else []


# ---------------------------------------------------------------- 왕복

def test_왕복_작업본과_그림이_원래와_같다(proj, proj2, tmp_path, capsys):
    spec = _canon(SCREENS)
    pptx = _exported(proj, capsys, spec)
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0 and rep["status"] == "ok", json.dumps(rep, ensure_ascii=False)  # 실패하면 보고서 전체를 한글 그대로 본다
    assert rep["missing"] == [] and rep["unmapped"] == []
    assert (proj2 / "docs" / "out" / "생산계획 보드.md").read_bytes() == spec.encode("utf-8")
    assert (proj2 / f"{IMG}/첫째 제목_v0.1.png").read_bytes() == PNG_A
    assert (proj2 / f"{IMG}/둘째 제목_v0.1.png").read_bytes() == PNG_B
    assert rep["spec"] == "docs/out/생산계획 보드.md" and rep["version"] == "0.1"
    assert sorted(rep["files"]) == sorted(["docs/out/생산계획 보드.md", f"{IMG}/첫째 제목_v0.1.png", f"{IMG}/둘째 제목_v0.1.png"])


def test_읽어_들인_작업본을_다시_산출하면_글자가_같은_pptx(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    assert _imp(proj2, _upload(tmp_path, pptx), capsys)[0] == 0
    again = _exported(proj2, capsys, (proj2 / "docs" / "out" / "생산계획 보드.md").read_text(encoding="utf-8"), pics={})
    assert _deck(Presentation(str(again))) == _deck(Presentation(str(pptx)))


def test_쪽당_최대를_넘어_세_쪽이_된_화면은_한_소절로_합쳐지고_번호가_이어진다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    assert len(list(Presentation(str(pptx)).slides)) == 7  # 표지·목차·첫째 1쪽·둘째 3쪽·끝
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0
    text = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert text.count("### 시험매뉴얼 · 본문 · 둘째 제목") == 1
    assert "7. 일곱" in text and "4. 넷" in text
    assert [p["page"] for p in rep["pages"]] == ["표지", "목차", "본문", "본문", "본문", "본문", "끝"]


def test_쪽_번호_필드_도형은_번호_설명으로_읽히지_않는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})
    flds = [s for s in _body(Presentation(str(pptx)))[0].shapes if s.has_text_frame and s.left >= 7000000
            and s._element.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}fld") is not None]
    assert flds, "시험 전제: 쪽 번호 필드 도형이 오른쪽에 있다"
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    text = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert code == 0 and rep["unmapped"] == []
    assert "1. 하나\n2. 둘\n" in text and "3. " not in text


def test_여러_줄_기능_설명은_본문_형태로_쓰고_왕복이_같다(proj, proj2, tmp_path, capsys):
    screens = [_screen("첫째 제목", "첫 줄이다.\n둘째 줄이다.", ["하나"], img=f"{IMG}/첫째 제목_v0.1.png")]
    spec = _canon(screens)
    pptx = _exported(proj, capsys, spec, pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0, rep
    got = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert "#### 기능 설명\n\n첫 줄이다.\n둘째 줄이다.\n" in got
    assert got == spec


def test_표_칸_값의_세로줄은_이스케이프한다(proj, proj2, tmp_path, capsys):
    screens = [_screen("첫째 제목", "A \\| B 를 쓴다.", ["하나"], img=f"{IMG}/첫째 제목_v0.1.png")]
    spec = _canon(screens)
    pptx = _exported(proj, capsys, spec, pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0 and (proj2 / rep["spec"]).read_text(encoding="utf-8") == spec


def test_화면_제목에_슬래시가_있으면_그림_파일_이름에서_바꾼다(proj, proj2, tmp_path, capsys):
    screens = [_screen("입력/조회", "설명이다.", ["하나"])]
    pptx = _exported(proj, capsys, _canon(screens), pics={f"{IMG}/입력_조회_v0.1.png": PNG_A})
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0, rep
    text = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert "### 시험매뉴얼 · 본문 · 입력/조회" in text and f"{IMG}/입력_조회_v0.1.png" in text
    assert (proj2 / f"{IMG}/입력_조회_v0.1.png").read_bytes() == PNG_A


# ---------------------------------------------------------------- 사람이 손댄 경우

def test_칸을_조금_옮겨도_그대로_읽는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        for sl in _body(prs):
            s = _find(sl, "첫째 화면") if any(x.has_text_frame and x.text_frame.text.startswith("첫째 화면") for x in sl.shapes) else None
            if s is not None:
                s.left, s.top = Emu(s.left + 30000), Emu(s.top - 25000)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 0 and rep["missing"] == [], rep
    assert "| 기능 설명 | 첫째 화면 설명입니다. |" in (proj2 / rep["spec"]).read_text(encoding="utf-8")


def test_칸을_크게_옮기면_missing_이고_글은_unmapped_로_남는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        s = _find(_body(prs)[0], "첫째 화면")
        s.top = Emu(s.top + 900000)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and rep["status"] == "incomplete"
    assert [m["item"] for m in rep["missing"]] == ["기능 설명"] and "첫째 제목" in rep["missing"][0]["sheet"]
    assert any(u["text"] == "첫째 화면 설명입니다." for u in rep["unmapped"])  # 글은 버리지 않고 알린다
    assert "| 기능 설명 | 미정 |" in (proj2 / rep["spec"]).read_text(encoding="utf-8")


def test_메모_글상자를_붙이면_unmapped_이고_종료_1(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        body = _body(prs)[0]
        box = body.shapes.add_textbox(Emu(3000000), Emu(5500000), Emu(2000000), Emu(300000))
        box.text_frame.text = "담당자 확인 필요"
        cover = list(prs.slides)[0].shapes.add_textbox(Emu(6000000), Emu(100000), Emu(2000000), Emu(300000))
        cover.text_frame.text = "표지 메모"

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and rep["status"] == "incomplete" and rep["missing"] == []
    got = {u["text"]: u for u in rep["unmapped"]}
    assert set(got) == {"담당자 확인 필요", "표지 메모"}
    assert got["표지 메모"]["sheet"] == "표지" and got["담당자 확인 필요"]["slide"] == 3
    assert (proj2 / rep["spec"]).exists(), "작업본은 쓴다(incomplete)"


def test_기능_설명_도형을_지우면_missing_이고_작업본에_미정(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        s = _find(_body(prs)[0], "첫째 화면")
        s._element.getparent().remove(s._element)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1
    assert [(m["item"]) for m in rep["missing"]] == ["기능 설명"]
    text = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert "| 기능 설명 | 미정 |" in text and "| 기능 설명 | 둘째 화면 설명입니다. |" in text


def test_번호_도형만_있고_글상자가_없으면_그_번호만_missing(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})

    def mutate(prs):
        s = _find(_body(prs)[0], "둘")
        s._element.getparent().remove(s._element)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and [m["item"] for m in rep["missing"]] == ["번호 설명 2"]
    assert "2. 미정" in (proj2 / rep["spec"]).read_text(encoding="utf-8")


def test_견본의_예시_글이_그대로_남은_칸은_missing(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})

    def mutate(prs):
        s = _find(_body(prs)[0], "첫째 화면")
        s.text_frame.paragraphs[0].runs[0].text = "견본_기능설명 한두 문장"

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and rep["missing"][0]["item"] == "기능 설명" and "예시 글" in rep["missing"][0]["reason"]


def test_견본_그림_그대로면_그림_missing(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})
    tpl = Presentation(str(proj / "templates" / "시험.pptx"))
    sample = [s for s in list(tpl.slides)[2].shapes if s.shape_type == 13][0]

    def mutate(prs):
        body = _body(prs)[0]
        old = [s for s in body.shapes if s.shape_type == 13][0]
        box = (old.left, old.top, old.width, old.height)
        old._element.getparent().remove(old._element)
        body.shapes.add_picture(io.BytesIO(sample.image.blob), *map(Emu, box))

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and [m["item"] for m in rep["missing"]] == ["그림"]
    assert "#### 그림\n\n미정\n" in (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert not (proj2 / f"{IMG}/첫째 제목_v0.1.png").exists()


def test_견본에_없는_표를_고치면_unmapped(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})

    def mutate(prs):
        tbl = [s for s in _body(prs)[0].shapes if s.has_table][0]
        tbl.table.cell(0, 0).text = "표에 쓴 글"

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and any(u["kind"] == "표" and "표에 쓴 글" in u["text"] for u in rep["unmapped"])


def test_PNG_가_아닌_그림은_알리고_다시_산출은_받는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})
    buf = io.BytesIO()
    Image.new("RGB", (320, 200), (200, 100, 0)).save(buf, "JPEG")

    def mutate(prs):
        body = _body(prs)[0]
        old = [s for s in body.shapes if s.shape_type == 13][0]
        box = (old.left, old.top, old.width, old.height)
        old._element.getparent().remove(old._element)
        body.shapes.add_picture(io.BytesIO(buf.getvalue()), *map(Emu, box))

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 0, rep
    assert any(w["type"] == "image-not-png" for w in rep["warnings"])
    assert (proj2 / f"{IMG}/첫째 제목_v0.1.jpg").exists()
    text = (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert f"{IMG}/첫째 제목_v0.1.jpg" in text
    # 산출은 PNG 가 아니어도 받는다
    p = proj2 / rep["spec"]
    c = export.main(["--spec", str(p), "--root", str(proj2), "--check"])
    out = json.loads(capsys.readouterr().out)
    assert c == 3 and out["problems"] == [], out


# ---------------------------------------------------------------- 읽지 못함(종료 2)

def test_쪽_크기가_다르면_종료_2이고_아무것도_쓰지_않는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        prs.slide_width = Emu(9144000)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 2 and rep["status"] == "error" and "쪽 크기" in rep["problems"][0]["reason"]
    assert _written(proj2) == []


def test_칸이_안_맞는_다른_pptx_는_종료_2이고_아무것도_쓰지_않는다(proj2, tmp_path, capsys):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    for t in ("안녕", "다른 글", "또 다른 글"):
        s = prs.slides.add_slide(prs.slide_layouts[6])
        s.shapes.add_textbox(Emu(4000000), Emu(3000000), Emu(2000000), Emu(300000)).text_frame.text = t
    dst = tmp_path / "upload" / PPTX_NAME
    dst.parent.mkdir()
    prs.save(str(dst))
    code, rep = _imp(proj2, dst, capsys)
    assert code == 2 and "정할 수 없다" in rep["problems"][0]["reason"]
    assert _written(proj2) == []


def test_파일_이름에서_값을_못_읽으면_종료_2(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    code, rep = _imp(proj2, _upload(tmp_path, pptx, name="내가 만든 매뉴얼.pptx"), capsys)
    assert code == 2 and rep["problems"][0]["item"] == "파일명" and _written(proj2) == []


def test_같은_작업본이_이미_있으면_종료_2이고_덮어쓰지_않는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    old = proj2 / "docs" / "out" / "생산계획 보드.md"
    old.parent.mkdir(parents=True)
    old.write_text("먼저 있던 글\n", encoding="utf-8")
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 2 and "이미 있다" in rep["problems"][0]["reason"]
    assert old.read_text(encoding="utf-8") == "먼저 있던 글\n" and _written(proj2) == ["docs/out/생산계획 보드.md"]


def test_같은_그림이_이미_있으면_종료_2이고_작업본도_쓰지_않는다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    img = proj2 / f"{IMG}/첫째 제목_v0.1.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"old")
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 2 and "그림" in rep["problems"][0]["reason"]
    assert img.read_bytes() == b"old" and not (proj2 / "docs" / "out" / "생산계획 보드.md").exists()


def test_pptx_지도가_여럿이면_양식을_고르게_한다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    (proj2 / "templates" / "forms" / "다른매뉴얼.yaml").write_text(MAP.replace("시험매뉴얼", "다른매뉴얼"), encoding="utf-8")
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 2 and "--form" in rep["problems"][0]["reason"] and "다른매뉴얼" in rep["problems"][0]["reason"]
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys, "--form", "시험매뉴얼")
    assert code == 0


def test_양식_지도가_없으면_종료_2(proj2, proj, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    (proj2 / "templates" / "forms" / "시험매뉴얼.yaml").unlink()
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 2 and "지도가 없다" in rep["problems"][0]["reason"]


# ---------------------------------------------------------------- --check, 문서 검사

def test_check_는_아무것도_쓰지_않고_계획만_낸다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys, "--check")
    assert code == 0 and rep["dry_run"] is True and rep["files"] == []
    assert "docs/out/생산계획 보드.md" in rep["planned"] and len(rep["planned"]) == 3
    assert _written(proj2) == []


def test_check_도_옮기지_못한_글은_알리고_종료_1(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        list(prs.slides)[0].shapes.add_textbox(Emu(6000000), Emu(100000), Emu(2000000), Emu(300000)).text_frame.text = "메모"

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys, "--check")
    assert code == 1 and rep["unmapped"][0]["text"] == "메모" and _written(proj2) == []


def test_규칙_폴더가_없으면_문서_검사는_검사_불능으로_알린다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    shutil.rmtree(proj2 / "rules")
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0 and rep["doc_guard"]["status"] == "unavailable" and "검사 불능" in rep["doc_guard"]["reason"]


MANUAL_DIR = Path(__file__).resolve().parents[2] / "plugins" / "harness" / "skills" / "manual"


def test_매뉴얼_규칙으로_문서_검사하면_묶은_개발_건_미정이_위반으로_나온다(tmp_path, capsys):
    """pptx 에 DEV 정보가 없어 `미정` 으로 쓴 표를 rules/manual.yaml 이 어떻게 보는지 — 위반으로 나오고, 채우면 통과한다."""
    lob, title = "Production", "1.생산계획 보드"
    map_text = MAP.replace("폴더: docs/out", "폴더: docs/manual/{LoB}")
    p1, p2 = _project(tmp_path / "a", map_text), _project(tmp_path / "b", map_text)
    for p in (p1, p2):
        shutil.copy(MANUAL_DIR / "manual.yaml", p / "rules" / "manual.yaml")
        (p / "templates" / "harness").mkdir(parents=True)
        shutil.copy(MANUAL_DIR / "manual-template.md", p / "templates" / "harness" / "manual.md")
    img = f"docs/manual/img/{lob}"
    spec = _canon([_screen("첫째 제목", "설명이다.", ["하나"], img=f"{img}/첫째 제목_v0.1.png")], lob=lob, title=title)
    src = p1 / "docs" / "manual" / lob / f"{title}.md"
    src.parent.mkdir(parents=True)
    src.write_text(spec, encoding="utf-8", newline="\n")
    (p1 / img).mkdir(parents=True)
    (p1 / img / "첫째 제목_v0.1.png").write_bytes(PNG_A)
    assert export.main(["--spec", str(src), "--root", str(p1)]) == 3
    out = json.loads(capsys.readouterr().out)
    code, rep = _imp(p2, _upload(tmp_path, p1 / out["files"][0]), capsys)
    assert code == 0 and rep["spec"] == f"docs/manual/{lob}/{title}.md", rep
    g = rep["doc_guard"]
    assert g["status"] == "violation", g
    assert any("DEV" in json.dumps(v, ensure_ascii=False) for v in g["violations"]), g
    assert not any("form_columns" in v["rule"] for v in g["violations"]), "양식 항목은 지도와 맞다"
    # 채우면 통과한다
    fixed = (p2 / rep["spec"]).read_text(encoding="utf-8").replace("| 미정 | 미정 |", "| DEV-012 | 생산계획 보드 |")
    assert import_pptx._guard(p2, rep["spec"], fixed)["status"] == "pass"


def test_dev_를_주면_묶은_개발_건을_채워_문서_검사를_통과하고_형식이_틀리면_종료_2(tmp_path, capsys):
    lob, title = "Production", "1.생산계획 보드"
    map_text = MAP.replace("폴더: docs/out", "폴더: docs/manual/{LoB}")
    p1 = _project(tmp_path / "a", map_text)
    shutil.copy(MANUAL_DIR / "manual.yaml", p1 / "rules" / "manual.yaml")
    (p1 / "templates" / "harness").mkdir(parents=True)
    shutil.copy(MANUAL_DIR / "manual-template.md", p1 / "templates" / "harness" / "manual.md")
    img = f"docs/manual/img/{lob}"
    src = p1 / "docs" / "manual" / lob / f"{title}.md"
    src.parent.mkdir(parents=True)
    src.write_text(_canon([_screen("첫째 제목", "설명이다.", ["하나"], img=f"{img}/첫째 제목_v0.1.png")], lob=lob, title=title),
                   encoding="utf-8", newline="\n")
    (p1 / img).mkdir(parents=True)
    (p1 / img / "첫째 제목_v0.1.png").write_bytes(PNG_A)
    assert export.main(["--spec", str(src), "--root", str(p1)]) == 3
    up = _upload(tmp_path, p1 / json.loads(capsys.readouterr().out)["files"][0])
    for bad in ("DEV-12", "dev-012", "DEV-012,", "DEV-012,DEV-012", ""):
        p = _project(tmp_path / f"bad{abs(hash(bad))}", map_text)
        code, rep = _imp(p, up, capsys, "--dev", bad)
        assert code == 2 and rep["problems"][0]["item"] == "--dev", bad
        assert _written(p) == []
    p2 = _project(tmp_path / "ok", map_text)
    shutil.copy(MANUAL_DIR / "manual.yaml", p2 / "rules" / "manual.yaml")
    (p2 / "templates" / "harness").mkdir(parents=True)
    shutil.copy(MANUAL_DIR / "manual-template.md", p2 / "templates" / "harness" / "manual.md")
    code, rep = _imp(p2, up, capsys, "--dev", "DEV-012,DEV-013")
    assert code == 0 and rep["doc_guard"]["status"] == "pass", rep["doc_guard"]
    text = (p2 / rep["spec"]).read_text(encoding="utf-8")
    assert "| DEV-012 |  |\n| DEV-013 |  |" in text and "미정" not in text


def test_작업본_이름_자리는_지도에서_정하고_못_정하면_종료_2():
    out = {"폴더": "docs/manual/{LoB}", "파일명": "사용자매뉴얼_{LoB}_{제목}_v{버전}.pptx", "자리": {"버전": {"메타": "버전"}}}
    assert import_pptx._doc_name_slot(out, "f") == "제목"  # 폴더·메타가 아닌 자리가 하나
    assert import_pptx._doc_name_slot({**out, "작업본_자리": "LoB"}, "f") == "LoB"  # 지도가 지정
    for bad in ({**out, "폴더": "docs/out"},  # 후보가 LoB·제목 둘
                {**out, "파일명": "x_{LoB}_v{버전}.pptx"},  # 후보 없음
                {**out, "작업본_자리": "없는자리"}):
        with pytest.raises(export.ExportError) as e:
            import_pptx._doc_name_slot(bad, "f")
        assert "작업본_자리" in e.value.reason or "자리" in e.value.reason


def test_지도에서_작업본_이름을_못_정하면_아무것도_쓰지_않고_종료_2(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    (proj2 / "templates" / "forms" / "시험매뉴얼.yaml").write_text(MAP, encoding="utf-8")  # 작업본_자리 없음, 폴더에도 자리 없음
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 2 and rep["problems"][0]["item"] == "산출.작업본_자리" and "지도에서" in rep["problems"][0]["reason"]
    assert _written(proj2) == []


@pytest.mark.parametrize("name, item", [
    ("M_CON_생산계획 보드_v0.1.pptx", "LoB"),  # Windows 예약 이름
    ("M_Production(생산)_NUL.txt_v0.1.pptx", "제목"),
    ("M_Production(생산)_.._v0.1.pptx", "제목"),  # 점만
    ("M_Production(생산)_끝이점._v0.1.pptx", "제목"),  # 끝의 점
])
def test_파일_이름에서_읽은_값이_폴더_이름으로_못_쓰면_종료_2(proj, proj2, tmp_path, capsys, name, item):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    code, rep = _imp(proj2, _upload(tmp_path, pptx, name=name), capsys)
    assert code == 2 and rep["problems"][0]["item"] == item, rep["problems"]
    assert _written(proj2) == []


def test_자리_값을_나누는_방법이_둘_이상이면_모호함으로_종료_2(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    code, rep = _imp(proj2, _upload(tmp_path, pptx, name="M_Production_a_b_v0.1.pptx"), capsys)  # LoB=Production, 제목=a_b / LoB=Production_a, 제목=b
    assert code == 2 and "가지라 하나로 정할 수 없다" in rep["problems"][0]["reason"] and _written(proj2) == []
    fmap = {"산출": {"파일명": "{A}-{B}.pptx"}}
    with pytest.raises(export.ExportError, match="2가지"):
        import_pptx._read_filename(fmap, "x-y-z.pptx", "f")
    assert import_pptx._read_filename(fmap, "x-y.pptx", "f") == {"A": "x", "B": "y"}


@pytest.mark.parametrize("which, prefixes", [
    (0, ("계획 관리", "첫째 제목", "01", "첫째 화면")),  # 앞뒤가 본문이라 후보는 본문뿐
    (-1, ("계획 관리", "둘째 제목", "02", "둘째 화면")),  # 뒤가 끝 쪽이라 끝 쪽도 후보 — 그래도 끝으로 추측하지 않는다
])
def test_칸을_전부_지운_본문_쪽은_끝_쪽으로_추측하지_않고_종료_2(proj, proj2, tmp_path, capsys, which, prefixes):
    pptx = _exported(proj, capsys, _canon(SCREENS))

    def mutate(prs):
        sl = _body(prs)[which]
        for prefix in prefixes:
            s = _find(sl, prefix)
            s._element.getparent().remove(s._element)

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 2 and "정할 수 없다" in rep["problems"][0]["reason"] and "본문" in rep["problems"][0]["reason"]
    assert _written(proj2) == []


def test_견본의_고정_글은_번호_설명_후보가_아니다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})

    def add_static(slide):  # 번호 1 의 설명 글상자보다 번호에 더 가까운 고정 글(양식에 원래 있는 글)
        box = slide.shapes.add_textbox(Emu(7480000), Emu(2900000), Emu(80000), Emu(260000))
        box.text_frame.text = "고정 안내"

    tpl = Presentation(str(proj2 / "templates" / "시험.pptx"))
    add_static(list(tpl.slides)[2])  # 견본 본문 쪽에 같은 자리 같은 글
    tpl.save(str(proj2 / "templates" / "시험.pptx"))
    code, rep = _imp(proj2, _upload(tmp_path, pptx, lambda prs: add_static(_body(prs)[0])), capsys)
    assert code == 0 and rep["unmapped"] == [], rep
    assert "1. 하나\n2. 둘\n" in (proj2 / rep["spec"]).read_text(encoding="utf-8")


def test_PIL_이_못_읽는_그림은_파일을_쓰지_않고_그림을_미정으로(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS[:1]), pics={f"{IMG}/첫째 제목_v0.1.png": PNG_A})

    def mutate(prs):
        pic = [s for s in _body(prs)[0].shapes if s.shape_type == 13][0]
        _body(prs)[0].part.related_part(pic._element.blip_rId)._blob = b"not an image"

    code, rep = _imp(proj2, _upload(tmp_path, pptx, mutate), capsys)
    assert code == 1 and [m["item"] for m in rep["missing"]] == ["그림"] and "읽지 못해" in rep["missing"][0]["reason"]
    assert "#### 그림\n\n미정\n" in (proj2 / rep["spec"]).read_text(encoding="utf-8")
    assert [f for f in rep["files"] if f.endswith(".png")] == [] and not (proj2 / f"{IMG}/첫째 제목_v0.1.png").exists()


def test_종료_0_이어도_문서_검사가_pass_가_아니면_통과가_아니라고_알린다(proj, proj2, tmp_path, capsys):
    pptx = _exported(proj, capsys, _canon(SCREENS))
    code, rep = _imp(proj2, _upload(tmp_path, pptx), capsys)
    assert code == 0 and rep["doc_guard"]["status"] != "pass"
    assert "통과한 것이 아니다" in rep["next"] and rep["doc_guard"]["status"] in rep["next"]


def test_파일명_틀을_거꾸로_읽는다():
    fmap = {"산출": {"파일명": "사용자매뉴얼_{LoB}_{제목}_v{버전}.pptx", "자리": {"버전": {"메타": "버전"}}}}
    got = import_pptx._read_filename(fmap, "사용자매뉴얼_Production_1.생산실적 모니터링_v0.2.pptx", "f")
    assert got == {"LoB": "Production", "제목": "1.생산실적 모니터링", "버전": "0.2"}
