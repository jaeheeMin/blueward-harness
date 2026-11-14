"""CAP·UI5 개발 표준 검사(#944): 엔진 모듈, CLI, PR 검사(check_changed) 연결. 바뀐 줄만 보는지를 함께 확인한다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from checker import ui5_rules as ur

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from check_changed import EXIT_CONFIG_ERROR, EXIT_PASS, EXIT_VIOLATION, main_entry  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JS = "src/ui5/zppu0010/webapp/controller/Main.controller.js"
VIEW = "src/ui5/zppu0010/webapp/view/Main.view.xml"
FRAGMENT = "src/ui5/zppu0010/webapp/fragment/Dialog.fragment.xml"
I18N = "src/ui5/zppu0010/webapp/i18n/i18n.properties"


def _cfg(text: str = "") -> ur.Ui5Config:
    return ur.parse_config(text, Path("conventions/cap-ui5.yaml"))


def _rules(kind: str, text: str, cfg_text: str = "", lines: set[int] | None = None) -> list[str]:
    return [f["rule"] for f in ur.check_text(kind, text, "x", _cfg(cfg_text), lines)]


def _findings(kind: str, text: str, cfg_text: str = "", lines: set[int] | None = None) -> list[dict]:
    return ur.check_text(kind, text, "x", _cfg(cfg_text), lines)


def _project(tmp_path: Path, config: str | None = "") -> Path:
    (tmp_path / ".git").mkdir()
    if config is not None:
        (tmp_path / "conventions").mkdir()
        (tmp_path / "conventions" / "cap-ui5.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def _put(root: Path, rel: str, text: str) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


# --- 엔진 규칙 목록 ------------------------------------------------------------


def test_엔진_규칙_목록은_코드가_구현한_규칙과_같다():
    assert set(ur.load_engine_rules()) == ur.IMPLEMENTED_RULES


def test_엔진_규칙_파일은_배포_대상으로_묶여_있다():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "checker/ui5_checks.yaml" in text


def test_막는_규칙은_네_개이고_나머지는_경고다():
    rules = ur.load_engine_rules()
    assert {r for r, i in rules.items() if i["level"] == "violation"} == {"UI5-001", "UI5-002", "UI5-003", "UI5-004"}


# --- 대상 파일 판정 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path, kind",
    [
        ("app/x/webapp/controller/A.controller.js", "js"),
        ("webapp/Component.js", "js"),
        ("src/ui5/zppu0010/webapp/view/A.view.xml", "xml"),
        ("webapp/ext/B.fragment.xml", "xml"),
        ("webapp/i18n/i18n_ko.properties", "properties"),
    ],
)
def test_대상_파일은_종류를_돌려준다(path, kind):
    assert ur.target_kind(path) == kind


@pytest.mark.parametrize(
    "path",
    [
        "srv/service.js",  # CAP 서비스 JS 는 대상이 아니다
        "src/zcl_order.clas.xml",  # abapGit 메타
        "src/zcl_order.clas.abap",
        "src/package.devc.xml",
        "src/zsd_x.view.xml.bak",
        "webapp/manifest.json",
        "config/application.properties",  # i18n 폴더가 아니다
        "webapp/lib/vendor.min.js",
        "docs/spec.md",
    ],
)
def test_대상이_아닌_파일은_걸리지_않는다(path):
    assert ur.target_kind(path) is None


def test_abapGit_메타_xml_은_파일_목록에서_통째로_건너뛴다(tmp_path):
    root = _project(tmp_path)
    _put(root, "src/zcl_order.clas.xml", '<?xml version="1.0"?><abapGit id="a-b" x="한글"/>\n')
    result = ur.evaluate_files(["src/zcl_order.clas.xml"], root)
    assert result["status"] == "pass" and result["checked"] == 0 and result["findings"] == []


# --- JS 규칙 ----------------------------------------------------------------------


def test_001_console_호출은_위반이다():
    f = _findings("js", "sap.ui.define([], function () {\n\tconsole.log('x');\n});\n")
    assert [(x["rule"], x["level"], x["line"]) for x in f] == [("UI5-001", "violation", 2)]


def test_001_주석_문자열_템플릿_정규식_안의_console_은_세지_않는다():
    text = (
        "// console.log('a')\n"
        "/* console.error(1) */\n"
        "var s = 'console.log(1)';\n"
        "var t = `console.${x}.log`;\n"
        "var r = /console\\.log/;\n"
        "var u = 'a == b';\n"
    )
    assert "UI5-001" not in _rules("js", text)
    assert "UI5-002" not in _rules("js", text)


def test_001_window_console_도_잡고_다른_객체의_console_멤버는_안_잡는다():
    assert _rules("js", "window.console.warn(1);\n") == ["UI5-001"]
    assert "UI5-001" not in _rules("js", "oLogger.console.log(1);\n")


def test_002_느슨한_비교는_위반이고_엄격한_비교는_통과다():
    assert _rules("js", "if (a == b) {}\n") == ["UI5-002"]
    assert _rules("js", "if (a != b) {}\n") == ["UI5-002"]
    assert _rules("js", "if (a === b || a !== c || a >= b || a <= b) { x = (y = z); }\n") == []
    assert _rules("js", "const f = (a) => a;\n") == []


def test_103_DOM_직접_접근은_경고이고_jQuery_로_감싼_것은_통과다():
    assert _rules("js", "var o = document.getElementById('a');\n") == ["UI5-103"]
    assert _rules("js", "var o = document.querySelectorAll('.a');\n") == ["UI5-103"]
    assert "UI5-103" not in _rules("js", "var oEl = jQuery(window.document.getElementById(sId));\n")
    assert "UI5-103" not in _rules("js", "var oEl = $(document.getElementById(sId));\n")


def test_104_UI5_private_멤버_접근은_경고이고_자기_것은_통과다():
    assert _rules("js", "oControl._getFoo();\n") == ["UI5-104"]
    assert _rules("js", "oControl.__bar = 1;\n") == ["UI5-104"]
    assert _rules("js", "this._bReady = false;\nthat._foo();\nself._bar = 1;\n") == []
    own = "_reRender: function () {},\nvar o = oOther._reRender();\n"
    assert "UI5-104" not in _rules("js", own)
    assert "UI5-104" not in _rules("js", "var x = _.map(a);\n")


def test_105_공백_들여쓰기는_경고이고_파일_기존_방식이_공백이면_안_낸다():
    tabbed = "function a() {\n\treturn 1;\n}\nfunction b() {\n    return 2;\n}\n"
    f = _findings("js", tabbed)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-105", 5)]
    # 파일의 기존 줄 대부분이 공백이면(전체 줄 검사가 아니라 일부 줄만 볼 때) 그 방식을 따른다.
    spaced = "function a() {\n    return 1;\n}\nfunction b() {\n    return 2;\n}\nfunction c() {\n    return 3;\n}\n"
    assert _rules("js", spaced, lines={8}) == []
    # 새 파일이면 전체 줄이 대상이고 한 건으로 묶어 건수를 알린다.
    f = _findings("js", spaced)
    assert [x["rule"] for x in f] == ["UI5-105"] and "3개" in f[0]["message"]


def test_105_주석_안과_탭_뒤_정렬_공백은_안_센다():
    text = "/**\n * 설명\n */\nfunction a() {\n\t\t foo(1,\n\t\t     2);\n\tvar s = `\n   줄\n`;\n}\n"
    assert "UI5-105" not in _rules("js", text)


@pytest.mark.parametrize(
    "decl, ok",
    [
        ("var sId = '';", True), ("const oData = {};", True), ("let aRows = [];", True),
        ("var $dom = $('#a');", True), ("let iCount = 0;", True), ("var mMap = {};", True),
        ("var dToday = new Date();", True), ("var fRate = 1.5;", True), ("var bOn = true;", True),
        ("var rRe = /a/;", True), ("var fnCb = function () {};", True), ("var vAny;", True),
        ("var pLoad = load();", True),
        ("var that = this;", True), ("var self = this;", True), ("for (let i = 0;;) {}", True),
        ("const MAX_COUNT = 5;", True), ("const CONST_LIMIT = 5;", True),
        ("const { a, b } = obj;", True), ("var _oCache = null;", True),
        ("const Formatter = {};", True),  # 모듈·클래스 이름
        ("const _searchList = function () {};", True), ("const _calc = (a) => a;", True),
        ("var name = 'x';", False), ("let rows = [];", False), ("const data = {};", False),
        ("var count = 0;", False), ("var salary = 1;", False),  # s 로 시작하지만 접두어 + 대문자가 아니다
    ],
)
def test_106_지역변수_접두어(decl, ok):
    assert (_rules("js", decl + "\n") == []) is ok


# --- XML 규칙 ---------------------------------------------------------------------

VIEW_HEAD = '<mvc:View xmlns="sap.m" xmlns:mvc="sap.ui.core.mvc">\n'


def test_003_ID_의_하이픈은_위반이고_바인딩_ID_는_통과다():
    f = _findings("xml", VIEW_HEAD + '\t<Button id="list-btn-search"/>\n\t<Button id="goodsNameInput"/>\n\t<Button id="{=${x}}-a"/>\n</mvc:View>\n')
    assert [(x["rule"], x["level"], x["line"]) for x in f] == [("UI5-003", "violation", 2)]


def test_003_html_요소의_id_는_안_본다():
    text = '<mvc:View xmlns:html="http://www.w3.org/1999/xhtml" xmlns="sap.m" xmlns:mvc="sap.ui.core.mvc">\n<html:div id="a-b"/>\n</mvc:View>\n'
    assert _rules("xml", text) == []


def test_004_속성의_한글은_위반이고_바인딩과_주석과_본문은_통과다():
    text = (
        VIEW_HEAD
        + '\t<!-- 저장 단추 -->\n'
        + '\t<Button text="저장"/>\n'
        + '\t<Button text="{i18n>main.button.save}"/>\n'
        + '\t<Button text="{= ${a} ? \'예\' : \'아니오\' }"/>\n'
        + '\t<Text>한글 본문</Text>\n'
        + '</mvc:View>\n'
    )
    f = _findings("xml", text)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-004", 3)]


def test_004_여러_줄_태그는_속성이_있는_줄로_알린다():
    text = VIEW_HEAD + '\t<Button\n\t\tid="a"\n\t\ttext="저장"\n\t\tpress="onPress"/>\n</mvc:View>\n'
    f = _findings("xml", text)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-004", 4)]


@pytest.mark.parametrize(
    "attr, flagged",
    [
        ('icon="accept"', True), ('icon="sap-icon://accept"', False), ('icon="{view>/icon}"', False),
        ('icon="{= ${a} ? \'sap-icon://add\' : \'sap-icon://edit\' }"', False),
        ('icon="img/logo.png"', False), ('icon="./img/a.svg"', False), ('icon="/assets/a.jpg"', False),
        ('icon="https://x/a"', False), ('icon=""', False), ('activeIcon="accept"', False),
    ],
)
def test_101_icon_속성(attr, flagged):
    rules = _rules("xml", VIEW_HEAD + f"\t<Button {attr}/>\n</mvc:View>\n")
    assert (rules == ["UI5-101"]) is flagged


def test_101_src_는_Icon_요소만_본다():
    assert _rules("xml", VIEW_HEAD + '\t<Icon src="accept"/>\n</mvc:View>\n') == ["UI5-101"]
    assert _rules("xml", VIEW_HEAD + '\t<Icon src="sap-icon://accept"/>\n</mvc:View>\n') == []
    assert _rules("xml", VIEW_HEAD + '\t<Image src="logo"/>\n</mvc:View>\n') == []


def test_102_자기_닫힘_앞_공백은_경고이고_줄바꿈_뒤_닫힘은_통과다():
    assert _rules("xml", VIEW_HEAD + '\t<Button id="a" />\n</mvc:View>\n') == ["UI5-102"]
    assert _rules("xml", VIEW_HEAD + '\t<Button id="a"/>\n</mvc:View>\n') == []
    assert _rules("xml", VIEW_HEAD + '\t<Button\n\t\tid="a"\n\t/>\n</mvc:View>\n') == []
    assert _rules("xml", VIEW_HEAD + '\t<Button id="a"></Button>\n</mvc:View>\n') == []


def test_XML_이_깨졌으면_검사_불능이다(tmp_path):
    root = _project(tmp_path)
    _put(root, VIEW, "<mvc:View><Button></mvc:View>\n")
    result = ur.evaluate_files([VIEW], root)
    assert result["status"] == "cannot_check" and VIEW in result["message"]
    assert ur.exit_code_for(result) == ur.EXIT_CANNOT_CHECK


# --- properties 규칙 ---------------------------------------------------------------


def test_108_키_형식():
    text = (
        "#XBUT\nmain.button.save=저장\n"
        "#XTIT\nappTitle=앱\n"
        "#XFLD\nMain.label.x=a\n"
        "#XFLD\nlabel.x=a\n"
        "#XFLD\nmain.label.empNm.extra=a\n"
    )
    f = _findings("properties", text)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-108", 6), ("UI5-108", 8), ("UI5-108", 10)]


def test_108_제외_키를_설정으로_바꿀_수_있다():
    text = "#XTIT\nappTitle=앱\n#XTIT\nmyKey=앱\n"
    assert _rules("properties", text) == ["UI5-108"]  # appTitle 은 기본 제외, myKey 는 아니다
    assert _rules("properties", text, "i18n_제외_키: [myKey]\n") == ["UI5-108"]  # 기본 목록을 대체한다


def test_109_문구_윗줄에_종류_주석이_없으면_경고다():
    text = "#XBUT,20: 저장 버튼\nmain.button.save=저장\nmain.button.edit=수정\n#XMSG\nmain.message.a=a\n\nmain.message.b=b\n"
    f = _findings("properties", text)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-109", 3), ("UI5-109", 7)]


def test_110_한글_메시지_끝맺음():
    text = (
        "#XMSG\nmain.message.a=입력하세요.\n"
        "#XMSG\nmain.message.b=선택해 주시오.\n"
        "#XMSG\nmain.message.c=입력하십시오.\n"
        "#XMSG\nmain.message.d=Please enter\n"
        "#XMSG\nmain.message.e=\\uC785\\uB825\\uD558\\uC138\\uC694.\n"
    )
    f = _findings("properties", text)
    assert [(x["rule"], x["line"]) for x in f] == [("UI5-110", 2), ("UI5-110", 4), ("UI5-110", 10)]


def test_properties_이어쓰기와_주석_느낌표_줄은_키로_안_센다():
    text = "#XTXT\nmain.text.a=첫째 \\\n   둘째\n! 주석\n#XTXT\nmain.text.b: 값\n"
    assert _rules("properties", text) == []


# --- 추가된 줄만 보기 ----------------------------------------------------------------


def test_줄_집합_밖의_위반은_내지_않는다():
    text = "console.log(1);\nconsole.log(2);\nconsole.log(3);\n"
    f = _findings("js", text, lines={2})
    assert [x["line"] for x in f] == [2]
    assert _findings("js", text, lines=set()) == []


def test_diff_에서_추가된_줄_번호를_뽑는다():
    diff = (
        "diff --git a/webapp/A.js b/webapp/A.js\n--- a/webapp/A.js\n+++ b/webapp/A.js\n"
        "@@ -2,0 +3,2 @@ x\n+a\n+b\n@@ -9 +11 @@\n-old\n+new\n"
        "diff --git a/webapp/B.js b/webapp/B.js\nnew file mode 100644\n--- /dev/null\n+++ b/webapp/B.js\n"
        "@@ -0,0 +1,2 @@\n++ 두번째는 ++ 로 시작하는 내용\n+c\n"
        "diff --git a/webapp/C.js b/webapp/C.js\ndeleted file mode 100644\n--- a/webapp/C.js\n+++ /dev/null\n"
        "@@ -1 +0,0 @@\n-x\n"
    )
    assert ur.diff_added_lines(diff) == {"webapp/A.js": {3, 4, 11}, "webapp/B.js": {1, 2}}


# --- 설정 ---------------------------------------------------------------------------


def test_설정으로_규칙_심각도를_바꾸거나_끈다():
    text = "console.log(1);\nvar x = 1; if (a == b) {}\n"
    assert _rules("js", text, "규칙: {UI5-001: warn}\n") == ["UI5-001", "UI5-002"]
    f = _findings("js", text, "규칙: {UI5-001: warn}\n")
    assert [x["level"] for x in f] == ["warn", "violation"]
    assert _rules("js", text, "규칙: {UI5-001: off, UI5-002: off}\n") == []
    f = _findings("js", "var name = 1;\n", "규칙: {UI5-106: violation}\n")
    assert f[0]["level"] == "violation"


@pytest.mark.parametrize(
    "text",
    [
        "모르는키: 1\n",
        "규칙: {UI5-999: warn}\n",
        "규칙: {UI5-001: 제발}\n",
        "규칙: [UI5-001]\n",
        "예외: 1\n",
        "i18n_제외_키: appTitle\n",
        "- 목록\n",
        "규칙: {\n",
    ],
)
def test_설정_오류는_검사_불능이다(tmp_path, text):
    root = _project(tmp_path, text)
    _put(root, JS, "console.log(1);\n")
    result = ur.evaluate_files([JS], root)
    assert result["status"] == "cannot_check" and result["message"]
    assert ur.exit_code_for(result) == ur.EXIT_CANNOT_CHECK


def test_설정_파일이_없으면_검사하지_않는다(tmp_path):
    root = _project(tmp_path, None)
    _put(root, JS, "console.log(1);\n")
    assert ur.evaluate_files([JS], root) == {"status": "not_applicable"}


def test_예외_경로의_파일은_건너뛴다(tmp_path):
    root = _project(tmp_path, "예외: ['src/ui5/legacy*/**', 'src/ui5/zppu0010/webapp/view/Old.view.xml']\n")
    _put(root, "src/ui5/legacyApp/webapp/A.js", "console.log(1);\n")
    _put(root, "src/ui5/zppu0010/webapp/view/Old.view.xml", '<mvc:View id="a-b"/>\n')
    _put(root, JS, "console.log(1);\n")
    result = ur.evaluate_files(["src/ui5/legacyApp/webapp/A.js", "src/ui5/zppu0010/webapp/view/Old.view.xml", JS], root)
    assert [f["file"] for f in result["findings"]] == [JS]
    assert result["checked"] == 1


def test_위반이_있으면_1_경고만_있으면_0이다(tmp_path):
    root = _project(tmp_path)
    _put(root, JS, "var name = 1;\n")
    result = ur.evaluate_files([JS], root)
    assert result["status"] == "pass" and result["findings"][0]["level"] == "warn"
    assert ur.exit_code_for(result) == 0
    _put(root, JS, "console.log(1);\n")
    result = ur.evaluate_files([JS], root)
    assert result["status"] == "violation" and ur.exit_code_for(result) == 1


def test_읽을_수_없는_파일은_검사_불능이다(tmp_path):
    root = _project(tmp_path)
    (root / JS).parent.mkdir(parents=True)
    (root / JS).write_bytes(b"\xff\xfe\x00bad")
    result = ur.evaluate_files([JS], root)
    assert result["status"] == "cannot_check" and result["unchecked"][0]["file"] == JS


# --- CLI -----------------------------------------------------------------------------


def test_cli_files_는_diff_의_추가_줄만_본다(tmp_path, capsys):
    root = _project(tmp_path)
    _put(root, JS, "console.log(1);\nconsole.log(2);\n")
    (root / "list.txt").write_text(JS + "\n", encoding="utf-8")
    diff = f"diff --git a/{JS} b/{JS}\n--- a/{JS}\n+++ b/{JS}\n@@ -1,0 +2 @@\n+console.log(2);\n"
    (root / "d.diff").write_text(diff, encoding="utf-8")
    assert ur.main(["files", str(root / "list.txt"), "--diff", str(root / "d.diff"), "--root", str(root), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert [f["line"] for f in result["findings"]] == [2]
    # diff 가 없으면 전체 줄(새 파일처럼)
    assert ur.main(["files", str(root / "list.txt"), "--root", str(root)]) == 1
    assert [f["line"] for f in json.loads(capsys.readouterr().out)["findings"]] == [1, 2]


def test_cli_files_는_diff_를_못_읽으면_전체_검사로_넘어가지_않고_검사_불능이다(tmp_path, capsys):
    root = _project(tmp_path)
    _put(root, JS, "console.log(1);\n")
    (root / "list.txt").write_text(JS + "\n", encoding="utf-8")
    assert ur.main(["files", str(root / "list.txt"), "--diff", str(root / "없는.diff"), "--root", str(root)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "cannot_check" and result["findings"] == []


def test_cli_check_는_줄과_원래_경로를_받는다(tmp_path, capsys):
    root = _project(tmp_path)
    staged = tmp_path / "임시" / "Main.controller.js"
    staged.parent.mkdir()
    staged.write_text("console.log(1);\nconsole.log(2);\n", encoding="utf-8")
    real = (root / JS).as_posix()
    args = ["check", str(staged), "--as", real, "--root", str((root / JS).parent), "--lines", "2"]
    assert ur.main(args) == 1
    result = json.loads(capsys.readouterr().out)
    assert [(f["file"], f["line"]) for f in result["findings"]] == [(real, 2)]
    assert ur.main(args[:-2] + ["--lines", "1-0"]) == 0  # 빈 줄 집합이면 볼 것이 없다
    capsys.readouterr()


def test_cli_check_는_대상이_아니거나_설정이_없으면_0이다(tmp_path, capsys):
    root = _project(tmp_path)
    other = tmp_path / "srv" / "service.js"
    other.parent.mkdir()
    other.write_text("console.log(1);\n", encoding="utf-8")
    assert ur.main(["check", str(other), "--root", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "not_applicable"}
    bare = _project(tmp_path / "b", None) if (tmp_path / "b").mkdir() is None else None
    f = bare / JS
    f.parent.mkdir(parents=True)
    f.write_text("console.log(1);\n", encoding="utf-8")
    assert ur.main(["check", str(f), "--root", str(bare)]) == 0


def test_cli_check_는_설정_오류를_2로_답한다(tmp_path, capsys):
    root = _project(tmp_path, "모르는키: 1\n")
    f = root / JS
    f.parent.mkdir(parents=True)
    f.write_text("console.log(1);\n", encoding="utf-8")
    assert ur.main(["check", str(f), "--root", str(root)]) == 2


# --- check_changed 연결: 바뀐 줄만 본다 -------------------------------------------------


def _pr(tmp_path: Path, monkeypatch, files: dict[str, str], diff: str | None, config: str | None = ""):
    root = _project(tmp_path, config)
    for name, text in files.items():
        _put(root, name, text)
    (root / "changed.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
    if diff is not None:
        (root / "diff.txt").write_text(diff, encoding="utf-8")
        monkeypatch.setenv("DOC_GUARD_DIFF_FILE", "diff.txt")
    monkeypatch.chdir(root)
    return root


def _diff_for(name: str, line_spec: str, body: list[str]) -> str:
    return f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -0,0 {line_spec} @@\n" + "".join(f"+{b}\n" for b in body)


def test_추가된_줄의_위반은_종료코드_1이고_기존_줄은_안_본다(tmp_path, monkeypatch, capsys):
    diff = _diff_for(JS, "+3", ["console.log(3);"])
    _pr(tmp_path, monkeypatch, {JS: "console.log(1);\nconsole.log(2);\nconsole.log(3);\n"}, diff)
    assert main_entry(["changed.txt"]) == EXIT_VIOLATION
    out = json.loads(capsys.readouterr().out)
    assert out["ui5"]["status"] == "violation"
    assert [f["line"] for f in out["ui5"]["findings"]] == [3]


def test_옛_위반만_있는_파일을_고쳐도_통과한다(tmp_path, monkeypatch, capsys):
    diff = _diff_for(JS, "+3", ["var sOk = 1;"])
    _pr(tmp_path, monkeypatch, {JS: "console.log(1);\nconsole.log(2);\nvar sOk = 1;\n"}, diff)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    out = json.loads(capsys.readouterr().out)
    assert out["ui5"]["status"] == "pass" and out["ui5"]["findings"] == []


def test_경고만_있으면_종료코드는_0이고_결과에_남는다(tmp_path, monkeypatch, capsys):
    diff = _diff_for(JS, "+1", ["var name = 1;"])
    _pr(tmp_path, monkeypatch, {JS: "var name = 1;\n"}, diff)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    out = json.loads(capsys.readouterr().out)
    assert [f["rule"] for f in out["ui5"]["findings"]] == ["UI5-106"]


def test_새_XML_과_properties_도_본다(tmp_path, monkeypatch, capsys):
    view = '<mvc:View xmlns="sap.m" xmlns:mvc="sap.ui.core.mvc">\n<Button id="a-b" text="저장"/>\n</mvc:View>\n'
    diff = _diff_for(VIEW, "+1,3", view.splitlines()) + _diff_for(I18N, "+1,2", ["main.button.a=a"])
    _pr(tmp_path, monkeypatch, {VIEW: view, I18N: "main.button.a=a\n"}, diff)
    assert main_entry(["changed.txt"]) == EXIT_VIOLATION
    rules = [f["rule"] for f in json.loads(capsys.readouterr().out)["ui5"]["findings"]]
    assert "UI5-003" in rules and "UI5-004" in rules and "UI5-109" in rules


def test_설정이_없으면_ui5_키가_없다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {JS: "console.log(1);\n"}, _diff_for(JS, "+1", ["x"]), config=None)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert "ui5" not in json.loads(capsys.readouterr().out)


def test_환경변수가_없으면_ui5_검사를_하지_않는다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {JS: "console.log(1);\n"}, None)
    monkeypatch.delenv("DOC_GUARD_DIFF_FILE", raising=False)
    main_entry(["changed.txt"])
    assert "ui5" not in json.loads(capsys.readouterr().out)


def test_UI5_파일이_안_바뀌었으면_ui5_키가_없다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {"srv/service.js": "console.log(1);\n"}, _diff_for("srv/service.js", "+1", ["x"]))
    main_entry(["changed.txt"])
    assert "ui5" not in json.loads(capsys.readouterr().out)


def test_설정이_깨졌으면_검사_불능이다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {JS: "var sOk = 1;\n"}, _diff_for(JS, "+1", ["x"]), config="모르는키: 1\n")
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR
    assert json.loads(capsys.readouterr().out)["ui5"]["status"] == "cannot_check"


def test_diff_를_못_읽으면_파일_전체로_넘어가지_않고_검사_불능이다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {JS: "console.log(1);\n"}, None)
    monkeypatch.setenv("DOC_GUARD_DIFF_FILE", "없는파일.txt")
    assert main_entry(["changed.txt"]) == EXIT_CONFIG_ERROR
    out = json.loads(capsys.readouterr().out)
    assert out["ui5"]["status"] == "cannot_check" and out["ui5"]["findings"] == []


def test_예시_설정_파일은_엔진이_읽을_수_있다():
    text = (ROOT / "plugins" / "harness" / "conventions" / "cap-ui5.example.yaml").read_text(encoding="utf-8")
    cfg = ur.parse_config(text, Path("cap-ui5.yaml"))
    assert set(cfg.levels) == ur.IMPLEMENTED_RULES
    assert yaml.safe_load(text) is not None


def test_화면_XML_만_바뀌고_설정이_없으면_기준_폴더가_없어도_막지_않는다(tmp_path, monkeypatch, capsys):
    _pr(tmp_path, monkeypatch, {VIEW: '<mvc:View id="a-b"/>\n'}, _diff_for(VIEW, "+1", ["x"]), config=None)
    assert main_entry(["changed.txt"]) == EXIT_PASS
    assert "ui5" not in json.loads(capsys.readouterr().out)
