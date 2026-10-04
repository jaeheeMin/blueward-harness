"""MCP 가드의 테넌트별 쓰기 차단과 데이터 추출 되묻기(#148) 테스트.

`plugins/harness/hooks/adt_tiers.py`(순수 판정 함수)를 직접 부르는 단위 테스트와,
`mcp_source_guard.py` 를 설치본처럼 복사해 띄우는 훅 테스트, `hooks.json` 매처 테스트,
`session-start-sync.sh` 안내 테스트로 이루어진다. 테넌트 판정은 엔진(uvx)을 부르기 전에
끝나므로 거절·되묻기 테스트는 엔진 없이 돈다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, PLUGIN_ROOT

HOOKS_DIR = PLUGIN_ROOT / "hooks"
ENGINE_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(HOOKS_DIR))
import adt_tiers  # noqa: E402

TIERS_YAML = """\
# 예시
system: Z5U

servers:
  abap-adt-z5u:
    client: "100"
    role: customizing          # 커스터마이징
    host: my406600.s4hana.cloud.sap
    proxy_port: 3299
    tier: read-only
    writes_allowed: false
    login_skill: /c100

  abap-adt-z5u-dev:
    client: "080"
    role: development
    writes_allowed: true
    login_skill: /c080

write_tools:
  - setObjectSource
  - createObject
  - deleteObject
  - activateObjects
  - runClass            # 코드를 실행하므로 쓰기로 취급한다

data_tools:
  - tableContents
  - runQuery
"""

DEFAULTS = adt_tiers.load_default_data_tools()


def _tiers(text: str = TIERS_YAML) -> adt_tiers.Tiers:
    return adt_tiers.parse_tiers(text)


# --- 서버 이름 파싱 -----------------------------------------------------------

@pytest.mark.parametrize(
    "name,expected",
    [
        ("mcp__abap-adt-z5u__setObjectSource", ("abap-adt-z5u", "setObjectSource")),
        ("mcp__abap_adt__runQuery", ("abap_adt", "runQuery")),
        # 서버 이름에 `__` 가 있어도 마지막 `__` 기준이라 도구가 맞게 나뉜다.
        ("mcp__my__server__createObject", ("my__server", "createObject")),
        ("mcp__plugin_foo_db__query", ("plugin_foo_db", "query")),
    ],
)
def test_도구_이름에서_서버와_도구를_뽑는다(name, expected):
    assert adt_tiers.split_mcp_tool_name(name) == expected


@pytest.mark.parametrize("name", ["Write", "mcp__only", "mcp____tool", "mcp__server__", "", None])
def test_mcp_도구_이름이_아니면_none(name):
    assert adt_tiers.split_mcp_tool_name(name) is None


# --- 판정(순수 함수) -----------------------------------------------------------

def test_쓰기_금지_서버의_쓰기_도구는_거절하고_허용_서버를_안내한다():
    d = adt_tiers.decide("mcp__abap-adt-z5u__deleteObject", {}, _tiers(), DEFAULTS)
    assert d.kind == "deny"
    assert "writes_allowed: false" in d.reason
    assert "abap-adt-z5u-dev" in d.reason  # 파일에서 읽은 허용 서버
    assert "다음:" in d.reason


def test_허용_서버의_쓰기_도구는_테넌트_판정을_통과한다():
    d = adt_tiers.decide("mcp__abap-adt-z5u-dev__deleteObject", {}, _tiers(), DEFAULTS)
    assert d.kind == "pass"


def test_모르는_서버의_쓰기_도구는_거절한다():
    d = adt_tiers.decide("mcp__other-server__setObjectSource", {}, _tiers(), DEFAULTS)
    assert d.kind == "deny"
    assert "other-server" in d.reason
    assert "abap-adt-z5u-dev" in d.reason


def test_쓰기_금지_서버라도_쓰기_목록에_없는_조회_도구는_통과한다():
    d = adt_tiers.decide("mcp__abap-adt-z5u__getObjectSource", {}, _tiers(), DEFAULTS)
    assert d.kind == "pass"


@pytest.mark.parametrize("server", ["abap-adt-z5u", "abap-adt-z5u-dev", "other-server"])
@pytest.mark.parametrize("tool", ["tableContents", "runQuery"])
def test_데이터_도구는_어느_서버든_되묻는다(server, tool):
    d = adt_tiers.decide(f"mcp__{server}__{tool}", {"ddicEntityName": "T000"}, _tiers(), DEFAULTS)
    assert d.kind == "ask"
    assert "CR-003" not in d.reason


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM t000",
        "select   *   from t000",
        "SELECT\n  *\nFROM t000",
        "SELECT SINGLE * FROM t000",
        "SELECT FROM t000 FIELDS * ORDER BY mandt",
        "select from t000 fields *",
    ],
)
@pytest.mark.parametrize("field", ["sqlQuery", "query", "sql"])  # 칸 이름이 무엇이든 본다
def test_select_star_쿼리면_사유에_cr003을_적는다(query, field):
    d = adt_tiers.decide("mcp__abap-adt-z5u__runQuery", {field: query, "rowNumber": 10}, _tiers(), DEFAULTS)
    assert d.kind == "ask"
    assert "CR-003" in d.reason


@pytest.mark.parametrize(
    "query",
    ["SELECT mandt, mtext FROM t000", "SELECT FROM t000 FIELDS mandt, mtext", "SELECT COUNT( * ) FROM t000"],
)
def test_필드를_고른_쿼리는_cr003을_적지_않는다(query):
    d = adt_tiers.decide("mcp__abap-adt-z5u__runQuery", {"sqlQuery": query}, _tiers(), DEFAULTS)
    assert d.kind == "ask"
    assert "CR-003" not in d.reason


def test_파일이_없으면_쓰기_도구는_테넌트_판정에서_통과한다():
    d = adt_tiers.decide("mcp__abap-adt-z5u__deleteObject", {}, None, DEFAULTS)
    assert d.kind == "pass"


def test_파일이_없어도_데이터_도구는_되묻는다():
    d = adt_tiers.decide("mcp__abap-adt-z5u__tableContents", {"ddicEntityName": "T000"}, None, DEFAULTS)
    assert d.kind == "ask"
    assert "env/adt-tiers.yaml" in d.reason


def test_파일의_data_tools_는_기본_목록에_더해진다():
    tiers = _tiers(TIERS_YAML.replace("  - runQuery\n", "  - runQuery\n  - extraTool\n"))
    assert adt_tiers.decide("mcp__s__extraTool", {}, tiers, DEFAULTS).kind == "ask"
    # 파일이 data_tools 를 아예 안 적어도 기본 목록은 유지된다.
    no_data = TIERS_YAML.split("data_tools:")[0]
    assert adt_tiers.decide("mcp__s__runQuery", {}, _tiers(no_data), DEFAULTS).kind == "ask"


def test_mcp_도구가_아니면_통과한다():
    assert adt_tiers.decide("Write", {}, _tiers(), DEFAULTS).kind == "pass"


# --- 파일 해석 ----------------------------------------------------------------

def test_public_cloud_형식을_그대로_읽는다():
    t = _tiers()
    assert t.system == "Z5U"
    assert t.servers["abap-adt-z5u"]["writes_allowed"] is False
    assert t.servers["abap-adt-z5u"]["client"] == "100"
    assert t.servers["abap-adt-z5u-dev"]["writes_allowed"] is True
    assert "runClass" in t.write_tools and len(t.write_tools) == 5
    assert t.data_tools == {"tableContents", "runQuery"}


def test_한_줄_목록과_따옴표도_읽는다():
    t = _tiers(
        'servers:\n  "a-b":\n    writes_allowed: true\nwrite_tools: [setObjectSource, "createObject"]\n'
    )
    assert t.write_tools == {"setObjectSource", "createObject"}
    assert "a-b" in t.servers


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# 주석뿐\n",
        "servers: [a, b\nwrite_tools: []\n",                      # 닫히지 않은 목록
        "servers:\n  a:\n    writes_allowed: yes\nwrite_tools: [x]\n",  # bool 아님
        "servers:\n  a:\n    client: x\nwrite_tools: [x]\n",       # writes_allowed 없음
        "write_tools: [x]\n",                                       # servers 없음
        "servers:\n  a:\n    writes_allowed: true\n",              # write_tools 없음
        "servers:\n  a:\n    writes_allowed: true\nwrite_tools: x\n",  # 목록 아님
        "servers:\n  a:\n    writes_allowed: true\nwrite_tools:\n  - 1\n",  # 글자 아님
        "servers:\n\ta:\n\t\twrites_allowed: true\nwrite_tools: [x]\n",  # 탭
        "servers:\n  a: &anchor\n    writes_allowed: true\nwrite_tools: [x]\n",  # 앵커
        "- 목록이 최상위\n",
        "servers: true\nwrite_tools: [x]\n",
        "not yaml at all\n",
    ],
)
def test_깨졌거나_필수_키가_없으면_tierserror(text):
    with pytest.raises(adt_tiers.TiersError):
        adt_tiers.parse_tiers(text)


def test_루트_찾기는_저장소_루트까지만_올라간다(tmp_path):
    repo = tmp_path / "repo"
    (repo / "env").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "env" / "adt-tiers.yaml").write_text(TIERS_YAML, encoding="utf-8")
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert adt_tiers.find_tiers_file(str(sub)) == (repo / "env" / "adt-tiers.yaml").resolve()

    # 저장소 루트(.git)에서 멈추므로, 위쪽 폴더의 파일은 쓰지 않는다.
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "adt-tiers.yaml").write_text(TIERS_YAML, encoding="utf-8")
    other = tmp_path / "other"
    (other / ".git").mkdir(parents=True)
    assert adt_tiers.find_tiers_file(str(other)) is None


# --- 훅(설치본) ---------------------------------------------------------------

@pytest.fixture(scope="module")
def hook(tmp_path_factory) -> Path:
    dest = tmp_path_factory.mktemp("harness-installed-tiers") / "harness"
    shutil.copytree(PLUGIN_ROOT, dest)
    return dest / "hooks" / "mcp_source_guard.py"


def _project(tmp_path: Path, yaml_text: str | None) -> Path:
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True)
    if yaml_text is not None:
        (repo / "env").mkdir()
        (repo / "env" / "adt-tiers.yaml").write_text(yaml_text, encoding="utf-8")
    return repo


def _run(hook: Path, repo: Path, tool: str, tool_input: dict, engine: str | None = None):
    # 기본 엔진은 일부러 존재하지 않는 곳 — 테넌트 판정이 엔진보다 먼저 끝나는지 본다.
    env = {**os.environ, "DOC_GUARD_ENGINE": engine or str(repo / "no-such-engine")}
    done = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}),
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=180,
    )
    out = json.loads(done.stdout) if done.stdout.strip() else None
    return done.returncode, out


def _decision(out):
    return None if out is None else out["hookSpecificOutput"]["permissionDecision"]


def _reason(out):
    return out["hookSpecificOutput"]["permissionDecisionReason"]


def test_훅_쓰기_금지_서버의_쓰기는_엔진을_부르기_전에_거절한다(hook, tmp_path):
    repo = _project(tmp_path, TIERS_YAML)
    code, out = _run(hook, repo, "mcp__abap-adt-z5u__setObjectSource",
                     {"objectSourceUrl": "/sap/bc/adt/oo/classes/zcl_x/source/main", "source": "x"})
    assert code == 0 and _decision(out) == "deny"
    assert "writes_allowed: false" in _reason(out)
    assert "abap-adt-z5u-dev" in _reason(out)


@pytest.mark.parametrize("tool", ["deleteObject", "activateObjects", "runClass", "createObject"])
def test_훅_쓰기_금지_서버의_쓰기_도구들을_거절한다(hook, tmp_path, tool):
    repo = _project(tmp_path, TIERS_YAML)
    _, out = _run(hook, repo, f"mcp__abap-adt-z5u__{tool}", {"name": "zcl_x"})
    assert _decision(out) == "deny"


def test_훅_모르는_서버의_쓰기는_거절한다(hook, tmp_path):
    repo = _project(tmp_path, TIERS_YAML)
    _, out = _run(hook, repo, "mcp__brand-new__deleteObject", {})
    assert _decision(out) == "deny"
    assert "brand-new" in _reason(out)


@pytest.mark.parametrize("has_file", [True, False])
def test_훅_데이터_도구는_파일_유무와_무관하게_되묻는다(hook, tmp_path, has_file):
    repo = _project(tmp_path, TIERS_YAML if has_file else None)
    code, out = _run(hook, repo, "mcp__abap-adt-z5u-dev__tableContents", {"ddicEntityName": "T000"})
    assert code == 0 and _decision(out) == "ask"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_훅_runquery_select_star_는_사유에_cr003을_적는다(hook, tmp_path):
    repo = _project(tmp_path, None)
    _, out = _run(hook, repo, "mcp__abap-adt-z5u__runQuery", {"sqlQuery": "SELECT * FROM t000"})
    assert _decision(out) == "ask" and "CR-003" in _reason(out)


def test_훅_파일이_없으면_쓰기_금지_후보도_테넌트로는_막지_않는다(hook, tmp_path):
    """파일 없음 + 쓰기 도구는 기존 동작이다. deleteObject 는 기존 CR 검사 대상이 아니라 통과."""
    repo = _project(tmp_path, None)
    code, out = _run(hook, repo, "mcp__abap-adt-z5u__deleteObject", {"objectUri": "/x"})
    assert code == 0 and out is None


def test_훅_파일이_없으면_기존_cr_검사는_그대로_돈다(hook, tmp_path):
    """파일 없음 + setObjectSource: 엔진을 못 받으면 기존 검사 불능 거절이 나온다."""
    repo = _project(tmp_path, None)
    _, out = _run(hook, repo, "mcp__abap-adt-z5u__setObjectSource",
                  {"objectSourceUrl": "/sap/bc/adt/oo/classes/zcl_x/source/main", "source": "DATA a TYPE i.\n"})
    assert _decision(out) == "deny"
    assert "엔진" in _reason(out) or "검사기" in _reason(out)


@pytest.mark.parametrize(
    "text",
    ["servers: [\n", "# 비었음\n", "servers:\n  a:\n    client: x\nwrite_tools: [x]\n"],
)
@pytest.mark.parametrize("tool", ["deleteObject", "tableContents"])
def test_훅_파일이_깨졌으면_거절한다(hook, tmp_path, text, tool):
    repo = _project(tmp_path, text)
    _, out = _run(hook, repo, f"mcp__abap-adt-z5u-dev__{tool}", {})
    assert _decision(out) == "deny"
    assert "다음:" in _reason(out) and "adt-tiers.yaml" in _reason(out)


def test_훅_관계없는_mcp_도구는_통과한다(hook, tmp_path):
    repo = _project(tmp_path, TIERS_YAML)
    code, out = _run(hook, repo, "mcp__abap-adt-z5u__getObjectSource", {})
    assert code == 0 and out is None


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 가 없으면 엔진을 받을 수 없다")
def test_훅_허용_서버의_쓰기는_기존_cr_검사가_이어진다(hook, tmp_path):
    repo = _project(tmp_path, TIERS_YAML)
    url = "/sap/bc/adt/oo/classes/zcl_x/source/main"
    engine = str(ENGINE_ROOT)
    code, out = _run(hook, repo, "mcp__abap-adt-z5u-dev__setObjectSource",
                     {"objectSourceUrl": url, "source": "DATA 주문번호 TYPE vbeln.\n"}, engine)
    assert _decision(out) == "deny" and "CR-001" in _reason(out)

    code, out = _run(hook, repo, "mcp__abap-adt-z5u-dev__setObjectSource",
                     {"objectSourceUrl": url, "source": "DATA lv_order TYPE vbeln.\n"}, engine)
    assert code == 0 and out is None


# --- hooks.json 매처 ----------------------------------------------------------

_WRITE_TOOLS = [
    "setObjectSource", "createObject", "deleteObject", "activateObjects", "activateByName",
    "renameExecute", "extractMethodExecute", "createTransport", "transportRelease",
    "transportDelete", "publishServiceBinding", "unPublishServiceBinding", "runClass",
    "gitPullRepo", "pushRepo",
]


def _matcher() -> str:
    hooks_json = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
    found = [
        e["matcher"] for e in hooks_json["hooks"]["PreToolUse"]
        for h in e["hooks"] if "mcp_source_guard.py" in h["command"]
    ]
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("server", ["abap-adt", "abap-adt-z5u", "abap-adt-z5u-dev"])
@pytest.mark.parametrize("tool", _WRITE_TOOLS + ["tableContents", "runQuery"])
def test_매처가_public_cloud_의_쓰기_15개와_데이터_2개를_잡는다(server, tool):
    assert re.fullmatch(_matcher(), f"mcp__{server}__{tool}")


@pytest.mark.parametrize("tool", ["getObjectSource", "searchObject", "unitTestRun", "login", "healthcheck"])
def test_매처는_조회_도구와_관계없는_mcp_도구를_잡지_않는다(tool):
    assert not re.fullmatch(_matcher(), f"mcp__abap-adt-z5u__{tool}")
    assert not re.fullmatch(_matcher(), f"mcp__github__{tool}")


def test_기본_데이터_도구는_모두_매처에_있다():
    for tool in DEFAULTS:
        assert re.fullmatch(_matcher(), f"mcp__x__{tool}")


# --- 세션 시작 안내 -----------------------------------------------------------

@pytest.fixture(scope="module")
def session_plugin_root(tmp_path_factory) -> Path:
    """ensure-tools.sh(winget 설치를 시도한다)와 conventions 가 없는 최소 플러그인 루트."""
    root = tmp_path_factory.mktemp("session-root") / "harness"
    (root / "hooks").mkdir(parents=True)
    shutil.copy(HOOKS_DIR / "session-start-sync.sh", root / "hooks" / "session-start-sync.sh")
    return root


def _session_output(root: Path, repo: Path) -> str:
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)}
    env.pop("CLAUDE_PROJECT_DIR", None)
    done = subprocess.run(
        [_BASH, str(root / "hooks" / "session-start-sync.sh")],
        input=json.dumps({"cwd": str(repo)}), capture_output=True, text=True, encoding="utf-8",
        env=env, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


NOTICE = "env/adt-tiers.yaml 이 없어 테넌트별 쓰기 차단이 꺼져 있습니다"


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")
def test_세션_시작_mcp_json_이_있고_파일이_없으면_안내한다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".mcp.json").write_text("{}", encoding="utf-8")
    out = _session_output(session_plugin_root, repo)
    assert NOTICE in out
    assert "다음:" in out.split(NOTICE, 1)[1].splitlines()[0]


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")
def test_세션_시작_파일이_있으면_안내하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / ".mcp.json").write_text("{}", encoding="utf-8")
    (repo / "env").mkdir()
    (repo / "env" / "adt-tiers.yaml").write_text(TIERS_YAML, encoding="utf-8")
    assert NOTICE not in _session_output(session_plugin_root, repo)


@pytest.mark.skipif(not _HAS_BASH, reason="bash 가 없으면 스크립트를 실행해 볼 수 없다")
def test_세션_시작_mcp_json_이_없는_저장소는_말하지_않는다(session_plugin_root, tmp_path):
    repo = _git_repo(tmp_path)
    assert "adt-tiers" not in _session_output(session_plugin_root, repo)
