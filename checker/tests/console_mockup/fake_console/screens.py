"""화면마다 시험 콘솔 상태를 만든다. build(api) 는 서버를 띄운 뒤 부르고, 브라우저가 열 경로(/s/g09 등)를 돌려준다.
상태 만드는 방법은 화면 번호(시안 G-xx)와 같은 이름의 함수 g04·g05 … 로 둔다. 새 화면을 더하려면 함수를 만들고 BUILDERS 에 올린다."""
from __future__ import annotations

import json
import subprocess
import sys
import time

from .lib import (HERE, LOGIN, RUN, ANALYSIS, add_req_row, hook_flow_session, make_project, make_xlsx, pr, set_gh, start_server, transcript, write,
                  wait_for)


def srs_analysis(unsure: bool = False) -> None:
    flow = ({"id": "fix", "reason": "작은 수정 같기도 하고 새 요구사항 같기도 하다", "confident": False, "alternativeId": "srs"} if unsure
            else {"id": "srs", "reason": "요구사항정의서(SRS)에 새 요구사항을 더하는 일이다", "confident": True})
    ANALYSIS.write_text(json.dumps({
        "understood": "구매오더를 조회하는 앱의 요구사항을 SRS 에 한 줄 더하려는 요청으로 이해했어요.",
        "candidates": [{"path": "docs/ssot/SRS.md", "reason": "요구사항이 적히는 표가 있어요"},
                       {"path": "templates/README.md", "reason": "양식 설명이 있어요"}],
        "extraQuestions": [{"question": "요구사항의 다음 단계는 어떻게 할까요?", "options": ["개발", "설정", "아직 정하지 않음"]}],
        "flow": flow}, ensure_ascii=False), encoding="utf-8")


def _job_done(api, jid):
    return wait_for(lambda: (lambda j: j if j and j["status"] != "running" else None)(api.get(f"/api/new/{jid}")[1]), 30)


def managed_session(api, cwd, text, flow=None):
    """/api/new -> 분석(가짜) -> /start. 콘솔이 띄운(managed) 가짜 claude 세션 id 를 돌려준다."""
    st, d = api.post("/api/new", {"text": text, "cwd": str(cwd)})
    assert st == 202, (st, d)
    jid = d["id"]
    job = _job_done(api, jid)
    assert job and job["status"] == "done", job
    body = {"picked": ["docs/ssot/SRS.md"], "extraAnswers": {}, "note": ""}
    if flow:
        body["flow"] = flow
    st, d = api.post(f"/api/new/{jid}/start", body)
    assert st == 202, (st, d)
    return jid, d["id"]


def sess(api, sid):
    return api.get(f"/api/sessions/{sid}")[1]


def _ready_home(api):
    root = make_project("proj-ready", None)
    api.post("/api/folders/last", {"path": str(root)})
    api.get("/api/folders/recent")  # 판정은 백그라운드로 읽는다: 한 번 부르고 기다렸다가
    wait_for(lambda: (lambda r: r if r and not r[0]["checking"] and r[0]["formsMissing"] != "unknown" else None)(api.get("/api/folders/recent")[1]), 15)
    return root


def g04(api):
    _ready_home(api)
    return "/"


def g05(api):
    _ready_home(api)
    return "/new"


def g06(api):
    root = make_project("proj-g06", "main", push=True)
    srs_analysis()
    api.post("/api/folders/last", {"path": str(root)})
    st, d = api.post("/api/new", {"text": "구매오더 조회 앱 요구사항을 SRS 에 추가해 줘", "cwd": str(root)})
    assert st == 202, (st, d)
    job = _job_done(api, d["id"])
    assert job and job["status"] == "done", job
    return f"/new?id={d['id']}"


def _srs_repo(name, branch, prs):
    root = make_project(name, branch)
    add_req_row(root)
    set_gh(prs)
    return root


def g09(api):
    root = _srs_repo("proj-g09", "docs/4-srs-purchase-order", [])
    # 시안 G-09 오른쪽 목록은 두 줄(요구사항정의서, 변경 기록 - 둘 다 안 올림)이라 세션이 미커밋 파일 둘을 쓴 상태로 만든다.
    write(root / "audit" / "changes" / "REQ-001.md", "# 변경 기록\n\n- REQ-001 구매오더 조회 앱 추가\n")
    hook_flow_session(api, "g09", root, "구매오더 조회 앱 요구사항을 SRS 에 추가해 줘", "srs", "srs", "docs/ssot/SRS.md",
                      "SRS 에 REQ-001 을 더했어요. 올릴까요?", extra_files=["audit/changes/REQ-001.md"])
    return "/s/g09"


def g10(api):
    br = "docs/12-srs-purchase-order"
    root = make_project("proj-g10", br)
    add_req_row(root)
    set_gh([pr(7, br, "OPEN", "SRS: 구매오더 조회 앱 요구사항", LOGIN, ["docs/ssot/SRS.md"], "pending"),
            pr(9, "docs/9-other", "OPEN", "SRS: 승인 요청 시험 PR", "teammate", ["docs/ssot/SRS.md"], "pass")])
    hook_flow_session(api, "g10", root, "구매오더 조회 앱 요구사항을 SRS 에 추가해 줘", "srs", "srs", "docs/ssot/SRS.md",
                      "SRS 를 올렸어요. 승인을 기다리는 중이에요.")
    return "/s/g10"


def g12(api):
    br = "docs/13-srs-merged"
    root = make_project("proj-g12", br)
    add_req_row(root)
    set_gh([pr(8, br, "MERGED", "SRS: 구매오더 조회 앱 요구사항", LOGIN, ["docs/ssot/SRS.md"], "pass")])
    hook_flow_session(api, "g12", root, "구매오더 조회 앱 요구사항을 SRS 에 추가해 줘", "srs", "srs", "docs/ssot/SRS.md",
                      "SRS 를 올렸고 병합까지 끝났어요.")
    return "/s/g12"


def g13(api):
    root = make_project("proj-g13", "main")
    srs_analysis()
    api.post("/api/folders/last", {"path": str(root)})
    _jid, sid = managed_session(api, root, "구매오더 조회 앱의 개발 Spec 을 만들어 줘", "spec")
    wait_for(lambda: sess(api, sid).get("report", "").startswith("echo"), 20)
    real = sess(api, sid)["id"]
    c = str(root)
    api.event(real, c, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:sync"})  # 점검 중 sync 만 했음으로
    api.event(real, c, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:spec"})
    qs = [{"question": "개발 Spec 을 어느 요구사항부터 만들까요?", "header": "범위", "multiSelect": False,
           "options": [{"label": "REQ-001 구매오더 조회", "description": "먼저 만들어 볼 요구사항"},
                       {"label": "SRS 의 개발 건 전부", "description": "한 번에 만들기"}]}]
    body_file = RUN / "q_g13.json"
    body_file.write_text(json.dumps({"session_id": real, "cwd": c, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                     "tool_input": {"questions": qs}}, ensure_ascii=False), encoding="utf-8")
    # 질문 카드가 남도록 연결을 붙드는 별도 프로세스로 보낸다(연결이 끊기면 서버가 요청을 닫는다). 서버를 끄면 같이 끝난다.
    detach = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-B", str(HERE / "hold_hook.py"), "question", str(body_file)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, **detach)
    wait_for(lambda: ((api.get(f"/api/sessions/{real}")[1] or {}).get("pendingRequestIds") or [None])[0], 10)
    return f"/s/{real}"


def g15(api):
    root = make_project("proj-g15", "docs/15-backlog")
    add_req_row(root)
    make_xlsx(root / "BW_Backlog List_v0.1.xlsx", "Backlog", ["ID", "Title", "Status", "다음 단계"],
              [["REQ-001", "구매오더 조회 앱", "Open", "개발"], ["REQ-002", "구매오더 변경 이력", "Open", "설정"]])
    set_gh([])
    hook_flow_session(api, "g15", root, "SRS 를 Backlog 양식으로 뽑아 줘", "srs", "srs", "BW_Backlog List_v0.1.xlsx",
                      "BW_Backlog List_v0.1.xlsx 를 만들었어요.", stop=True)
    return "/docs"


# 시안 화면 번호 -> 상태 만드는 함수. 상태 만들기가 준비되면 여기에 더한다.
BUILDERS = {"G-04": g04, "G-05": g05, "G-06": g06, "G-09": g09, "G-10": g10, "G-12": g12, "G-13": g13, "G-15": g15}
