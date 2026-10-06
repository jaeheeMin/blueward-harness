"""080 에 쓴 ABAP 오브젝트의 활성화 성공 확인 관문(#190)을 확인한다.

`mcp_activation_tracker.py`(PostToolUse)에 payload 를 stdin 으로 넣어 기록을 만들고,
`activation_gate.py check` 와 `pre-bash-git-guard.sh`(푸시), `pre_write_guard.py`(src/ 쓰기)가
그 기록으로 막는지 본다. 설치본을 흉내 내려고 `plugins/harness/` 를 저장소 밖으로 복사한다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from checker.tests.test_plugin_layout import _BASH, _HAS_BASH, _HAS_JQ

ENGINE_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = ENGINE_ROOT / "plugins" / "harness"
SERVER = "abap-adt"
CLASS_URL = "/sap/bc/adt/oo/classes/zcl_x/source/main"
DDLS_URL = "/sap/bc/adt/ddic/ddl/sources/zi_x/source/main"
BDEF_URL = "/sap/bc/adt/bo/behaviordefinitions/zi_x/source/main"


@pytest.fixture(scope="module")
def hooks(tmp_path_factory) -> Path:
    dest = tmp_path_factory.mktemp("harness-installed-activation") / "harness"
    shutil.copytree(PLUGIN_SRC, dest)
    return dest / "hooks"


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    return r


def _record(repo: Path) -> Path:
    gd = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout.strip()
    return Path(gd) / "harness-adt-activation.json"


def _post(hooks, repo, tool, tool_input, response="ok", server=SERVER, rc=0):
    payload = {
        "session_id": "s1", "cwd": str(repo), "tool_name": f"mcp__{server}__{tool}",
        "tool_input": tool_input, "tool_response": response,
    }
    done = subprocess.run(
        [sys.executable, str(hooks / "mcp_activation_tracker.py")],
        input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert done.returncode == rc, done.stderr
    return done


def _gate(hooks, repo) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, str(hooks / "activation_gate.py"), "check", str(repo)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    return done.returncode, done.stdout


def _write(hooks, repo, url=CLASS_URL):
    return _post(hooks, repo, "setObjectSource", {"objectSourceUrl": url, "source": "x"})


def _result(success, messages=(), inactive=()):
    return json.dumps({
        "success": success,
        "messages": [{"type": "E", "shortText": m, "line": 3} for m in messages],
        "inactive": list(inactive),
    })


def test_쓰고_활성화하지_않으면_막는다(hooks, repo):
    done = _write(hooks, repo)
    code, out = _gate(hooks, repo)
    assert code == 1
    assert "CLAS:ZCL_X" in out and "다음:" in out
    # 남은 목록을 Claude 에게도 알린다.
    ctx = json.loads(done.stdout)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse" and "CLAS:ZCL_X" in ctx["additionalContext"]


def test_기록이_없으면_통과한다(hooks, repo):
    assert _gate(hooks, repo)[0] == 0


def test_활성화_실패는_메시지와_함께_막는다(hooks, repo):
    _write(hooks, repo)
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"},
          _result(False, ["Syntax error in line 3"]))
    code, out = _gate(hooks, repo)
    assert code == 1
    assert "failed" in out and "Syntax error in line 3" in out


def test_활성화_성공이면_통과한다(hooks, repo):
    _write(hooks, repo)
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"},
          _result(True))
    assert _gate(hooks, repo)[0] == 0


def test_activateObjects_성공도_통과한다(hooks, repo):
    _write(hooks, repo)
    objs = json.dumps([{"adtcore:uri": "/sap/bc/adt/oo/classes/zcl_x", "adtcore:type": "CLAS/OC",
                        "adtcore:name": "ZCL_X", "adtcore:parentUri": "/sap/bc/adt/packages/zpk"}])
    _post(hooks, repo, "activateObjects", {"objects": objs}, _result(True))
    assert _gate(hooks, repo)[0] == 0


def test_응답을_해석하지_못하면_unknown_으로_막는다(hooks, repo):
    _write(hooks, repo)
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"},
          "이건 JSON 이 아니다")
    code, out = _gate(hooks, repo)
    assert code == 1 and "unknown" in out


def test_inactiveObjects_에_없으면_active_로_복구한다(hooks, repo):
    _write(hooks, repo)
    _post(hooks, repo, "inactiveObjects", {}, "[]")
    assert _gate(hooks, repo)[0] == 0


def test_inactiveObjects_에_있으면_그대로_막는다(hooks, repo):
    _write(hooks, repo)
    rec = [{"object": {"adtcore:uri": "/sap/bc/adt/oo/classes/zcl_x", "adtcore:type": "CLAS/OC",
                       "adtcore:name": "ZCL_X"}}]
    _post(hooks, repo, "inactiveObjects", {}, json.dumps(rec))
    assert _gate(hooks, repo)[0] == 1


def test_inactiveObjects_응답이_깨졌으면_기록을_바꾸지_않는다(hooks, repo):
    _write(hooks, repo)
    _post(hooks, repo, "inactiveObjects", {}, "Error: session expired")
    assert _gate(hooks, repo)[0] == 1


def test_같은_이름의_DDLS_와_BDEF_는_따로_추적한다(hooks, repo):
    _write(hooks, repo, DDLS_URL)
    _write(hooks, repo, BDEF_URL)
    entries = json.loads(_record(repo).read_text(encoding="utf-8"))["entries"]
    assert {e["type"] + ":" + e["name"] for e in entries.values()} == {"DDLS:ZI_X", "BDEF:ZI_X"}
    # DDLS 만 활성화하면 BDEF 가 남는다.
    _post(hooks, repo, "activateByName", {"objectName": "ZI_X", "objectUrl": "/sap/bc/adt/ddic/ddl/sources/zi_x"},
          _result(True))
    code, out = _gate(hooks, repo)
    assert code == 1 and "BDEF:ZI_X" in out and "DDLS:ZI_X" not in out


def test_createObject_는_written_이고_deleteObject_는_지운다(hooks, repo):
    _post(hooks, repo, "createObject", {"objtype": "CLAS/OC", "name": "zcl_y", "parentName": "ZPK"})
    code, out = _gate(hooks, repo)
    assert code == 1 and "CLAS:ZCL_Y" in out
    _post(hooks, repo, "deleteObject", {"objectUrl": "/sap/bc/adt/oo/classes/zcl_y", "lockHandle": "h"})
    assert _gate(hooks, repo)[0] == 0


def test_깨진_기록은_검사_불능으로_막는다(hooks, repo):
    _record(repo).write_text("{ 깨진", encoding="utf-8")
    code, out = _gate(hooks, repo)
    assert code == 1 and "검사 불능" in out


@pytest.mark.parametrize("shape", ["str", "blocks", "dict"])
def test_tool_response_세_모양을_모두_처리한다(hooks, repo, shape):
    _write(hooks, repo)
    text = _result(True)
    resp = {"str": text, "blocks": [{"type": "text", "text": text[:10]}, {"type": "text", "text": text[10:]}],
            "dict": {"content": [{"type": "text", "text": text}]}}[shape]
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"}, resp)
    assert _gate(hooks, repo)[0] == 0


def test_서버가_다르면_따로_추적한다(hooks, repo):
    _post(hooks, repo, "setObjectSource", {"objectSourceUrl": CLASS_URL}, server="abap-adt-z5u")
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"},
          _result(True), server="abap-adt")
    assert _gate(hooks, repo)[0] == 1


def test_git_저장소가_아니면_기록하지_않는다(hooks, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    _write(hooks, plain)
    assert _gate(hooks, plain)[0] == 0


# --- 푸시·src 쓰기 가드 ---------------------------------------------------------

def _guard(hooks, command, repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    done = subprocess.run(
        [_BASH, str(hooks / "pre-bash-git-guard.sh")], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    return json.loads(done.stdout) if done.stdout.strip() else None


@pytest.mark.skipif(not _HAS_BASH or not _HAS_JQ or shutil.which("uv") is None, reason="bash·jq·uv 필요")
def test_DELIVER_푸시도_미활성_오브젝트가_있으면_거절한다(hooks, repo):
    assert _guard(hooks, "DELIVER=1 git push -u origin HEAD", repo) is None  # 기록 없음 -> 기존대로 통과
    _write(hooks, repo)
    out = _guard(hooks, "DELIVER=1 git push -u origin HEAD", repo)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CLAS:ZCL_X" in reason and "다음:" in reason
    # 활성화하면 다시 통과
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_X", "objectUrl": "/sap/bc/adt/oo/classes/zcl_x"},
          _result(True))
    assert _guard(hooks, "DELIVER=1 git push -u origin HEAD", repo) is None


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv 필요")
def test_src_쓰기는_미활성_오브젝트가_있으면_거절한다(hooks, repo):
    def write_guard(rel):
        payload = {"tool_name": "Write", "cwd": str(repo),
                   "tool_input": {"file_path": str(repo / rel), "content": "x"}}
        done = subprocess.run(
            [sys.executable, str(hooks / "pre_write_guard.py")], input=json.dumps(payload),
            capture_output=True, text=True, encoding="utf-8", timeout=180,
        )
        return json.loads(done.stdout) if done.stdout.strip() else None

    (repo / "src").mkdir()
    assert write_guard("src/a.txt") is None
    _write(hooks, repo)
    out = write_guard("src/a.txt")
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "CLAS:ZCL_X" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert write_guard("notes/a.txt") is None  # src/ 밖은 영향 없다


# --- 080 실측 응답(abap-adt-z5u-dev) -------------------------------------------

REAL_OK = '{"messages":[],"success":true,"inactive":[]}'
REAL_FAIL = (
    '{"messages":[{"objDescr":"클래스 ZCL_MJH_MRP_REFRESH, 메소드 IF_OO_ADT_CLASSRUN~MAIN","type":"E","line":1,'
    '"href":"/sap/bc/adt/oo/classes/zcl_mjh_mrp_refresh/source/main#start=18,4;end=18,24",'
    '"code":"MESSAGE(GTU)","forceSupported":true,'
    '"shortText":"Field \\"LV_HARNESS_GATE_TEST\\" is unknown."}],"success":false,"inactive":[]}'
)
MRP_URL = "/sap/bc/adt/oo/classes/zcl_mjh_mrp_refresh"
REAL_INACTIVE = json.dumps([
    {"object": {
        "adtcore:uri": MRP_URL + "/source/main#type=CLAS%2FOM;name=IF_OO_ADT_CLASSRUN%7eMAIN",
        "adtcore:type": "CLAS/OM/public",
        "adtcore:name": "ZCL_MJH_MRP_REFRESH           IF_OO_ADT_CLASSRUN~MAIN",
        "adtcore:parentUri": MRP_URL,
    }},
    {"object": {"adtcore:uri": "/sap/bc/adt/oo/classes/zcl_other_user", "adtcore:type": "CLAS/OC",
                "adtcore:name": "ZCL_OTHER_USER"}},
])


def _mrp_write(hooks, repo):
    _post(hooks, repo, "setObjectSource", {"objectSourceUrl": MRP_URL + "/source/main"}, server="abap-adt-z5u-dev")


def _mrp_activate(hooks, repo, response):
    _post(hooks, repo, "activateByName", {"objectName": "ZCL_MJH_MRP_REFRESH", "objectUrl": MRP_URL},
          response, server="abap-adt-z5u-dev")


def test_실측_성공_응답은_통과한다(hooks, repo):
    _mrp_write(hooks, repo)
    _mrp_activate(hooks, repo, REAL_OK)
    assert _gate(hooks, repo)[0] == 0


def test_실측_실패_응답은_href_의_줄_번호와_함께_막는다(hooks, repo):
    _mrp_write(hooks, repo)
    _mrp_activate(hooks, repo, REAL_FAIL)  # inactive 가 빈 배열이어도 대상은 failed
    code, out = _gate(hooks, repo)
    assert code == 1 and "failed" in out
    assert "LV_HARNESS_GATE_TEST" in out and "줄 18" in out and "줄 1)" not in out
    assert "login_skill" in out


def test_실측_inactiveObjects_하위_항목은_부모가_비활성이라는_뜻이다(hooks, repo):
    _mrp_write(hooks, repo)
    _post(hooks, repo, "inactiveObjects", {}, REAL_INACTIVE, server="abap-adt-z5u-dev")
    code, out = _gate(hooks, repo)
    assert code == 1 and "CLAS:ZCL_MJH_MRP_REFRESH" in out
    assert "ZCL_OTHER_USER" not in out  # 기록 밖 오브젝트는 새로 만들지 않는다
    # 하위 항목이 사라지면(활성화됨) 복구된다.
    _post(hooks, repo, "inactiveObjects", {}, json.dumps(json.loads(REAL_INACTIVE)[1:]), server="abap-adt-z5u-dev")
    assert _gate(hooks, repo)[0] == 0


def test_표에_없는_URL_도_루트_URL_로_맞춘다(hooks, repo):
    url = "/sap/bc/adt/zzz/newkinds/zobj_a"
    _post(hooks, repo, "setObjectSource", {"objectSourceUrl": url + "/source/main"})
    rec = [{"object": {"adtcore:uri": url, "adtcore:type": "ZZZZ/XX", "adtcore:name": "ZOBJ_A"}}]
    _post(hooks, repo, "inactiveObjects", {}, json.dumps(rec))
    assert _gate(hooks, repo)[0] == 1  # 거짓 active 가 아니다
    _post(hooks, repo, "activateByName", {"objectName": "ZOBJ_A", "objectUrl": url}, _result(True))
    assert _gate(hooks, repo)[0] == 0


def test_activateByName_은_이름만으로_맞추지_않는다(hooks, repo):
    _write(hooks, repo, DDLS_URL)
    _write(hooks, repo, BDEF_URL)
    # objectUrl 이 없으면 대상을 알 수 없으니 아무것도 active 로 바꾸지 않는다.
    _post(hooks, repo, "activateByName", {"objectName": "ZI_X"}, _result(True))
    code, out = _gate(hooks, repo)
    assert code == 1 and "DDLS:ZI_X" in out and "BDEF:ZI_X" in out


# --- 잠금·실패 표식 ------------------------------------------------------------

def test_오래된_잠금은_깨고_진행한다(hooks, repo):
    lock = _record(repo).with_name("harness-adt-activation.json.lock")
    lock.write_text("", encoding="utf-8")
    old = lock.stat().st_mtime - 120
    os.utime(lock, (old, old))
    _write(hooks, repo)
    assert not lock.exists()
    assert _gate(hooks, repo)[0] == 1


def test_기록에_실패하면_표식과_exit_2_로_알리고_관문이_막는다(hooks, repo):
    _record(repo).write_text("{ 깨진", encoding="utf-8")  # 읽기-수정-쓰기가 실패한다
    done = _post(hooks, repo, "setObjectSource", {"objectSourceUrl": CLASS_URL}, rc=2)
    assert "inactiveObjects" in done.stderr and "다음:" in done.stderr
    marker = _record(repo).with_name("harness-adt-activation.error")
    assert marker.is_file() and "setObjectSource" in marker.read_text(encoding="utf-8")
    _record(repo).unlink()
    code, out = _gate(hooks, repo)  # 기록은 없어도 표식이 있으면 검사 불능
    assert code == 1 and "검사 불능" in out and str(marker) in out
    marker.unlink()
    assert _gate(hooks, repo)[0] == 0
