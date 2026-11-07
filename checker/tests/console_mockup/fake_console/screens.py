"""화면마다 시험 콘솔 상태를 만든다. build(api) 는 서버를 띄운 뒤 부르고, 브라우저가 열 경로(/s/g09 등)를 돌려준다.
상태 만드는 방법은 화면 번호(시안 G-xx)와 같은 이름의 함수 g04·g05 … 로 둔다. 새 화면을 더하려면 함수를 만들고 BUILDERS 에 올린다."""
from __future__ import annotations

import json
import subprocess
import sys
import time

from .lib import (HERE, LOGIN, RUN, ANALYSIS, add_req_row, git, hook_flow_session, make_project, make_xlsx, pr, set_gh, start_server, transcript, write,
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


SLUG = "example/public-cloud"


def _issue(number, title, state, author, day, stage, pr_no, symptom, cause="", solution="", comments=()):
    """type:trouble 이슈 하나(gh issue list/view 가 돌려주는 모양). comments 는 (종류 글머리, 쓴 사람, 날짜, 글)."""
    none = "_No response_"  # 본문은 .github/ISSUE_TEMPLATE/trouble.yml 이 만드는 모양(### 칸이름 아래 값)
    body = "\n\n".join(["### 관련 PR", f"#{pr_no}" if pr_no else none, "### 단계", stage, "### 증상", "```text\n" + symptom + "\n```",
                        "### 원인", cause or none, "### 해결 방법", solution or none]) + "\n"
    return {"number": number, "title": "[기록] " + title, "state": state, "author": {"login": author}, "body": body,
            "createdAt": f"2026-{day}T03:00:00Z", "url": f"https://github.com/{SLUG}/issues/{number}",
            "comments": [{"id": f"c{number}-{i}", "author": {"login": who}, "createdAt": f"2026-{d}T03:00:00Z", "body": text}
                         for i, (who, d, text) in enumerate(comments)]}


def _list_issues():
    """시안 G-20 목록의 여덟 줄."""
    t, c, s = "시도·안 됨: x", "해결 후보: x", "해결: x"
    return [
        _issue(842, "ATC 검사에서 운송이 막힘(금지 API)", "OPEN", "sora", "11-05", "SAP 운송", 812, "ATC 우선순위 1: 금지된 API 사용\nCL_ABAP_RANDOM 는 ABAP Cloud 에서 쓸 수 없어(ZCL_SO_QUERY 라인 48)",
               "공개 API 로 공개되지 않은 클래스를 호출했어. 운송 릴리스 전 ATC 검사가 이걸 막아.", "",
               [("sora", "11-05", "시도·안 됨: \"릴리스 다시 시도\" 했는데 같은 ATC 지적으로 또 막혔어."),
                ("minjae", "11-06", "해결 후보: CL_ABAP_RANDOM 대신 공개 API XCO_.. 로 바꾸기"),
                ("hyun", "11-06", "시도·안 됨: ATC 예외 신청을 해 봤는데 운송 담당자가 반려했어.")]),
        _issue(841, "doc-guard 가 Spec 양식 열 이름을 거절", "CLOSED", "hyun", "11-04", "문서 검사", 798, "doc-guard: 열 이름이 양식과 다름", "", "양식 열 이름을 맞춤",
               [("hyun", "11-04", t), ("hyun", "11-04", s)]),
        _issue(840, "트랜스포트 릴리스 때 잠금 오류", "OPEN", "minjae", "11-03", "SAP 운송", 806, "릴리스 중 객체 잠금 오류", "", "", [("minjae", "11-03", t)] * 3),
        _issue(839, "SRS 승인 검사가 승인자를 못 찾음", "CLOSED", "hyun", "11-02", "문서 검사", 781, "ssot-approval: 승인자 없음", "", "승인자 파일을 고침",
               [("hyun", "11-02", t), ("hyun", "11-02", s)]),
        _issue(838, "uvx 엔진 받기 시간 초과", "OPEN", "sora", "11-01", "개발", None, "uvx: 시간 초과", "", "", [("sora", "11-01", t), ("minjae", "11-01", c), ("hyun", "11-01", c)]),
        _issue(837, "pptx 매뉴얼 캡처 첫 로드 실패", "CLOSED", "minjae", "10-30", "개발", 790, "캡처 첫 로드 실패", "", "다시 열기", [("minjae", "10-30", t), ("minjae", "10-30", s)]),
        _issue(836, "Role 매핑 xlsx 에 사람 행이 채워져 나옴", "CLOSED", "hyun", "10-28", "문서 검사", 775, "Role xlsx 사람 행 채워짐", "", "사람 행을 비움",
               [("hyun", "10-28", t), ("hyun", "10-28", s)]),
        _issue(835, "병합 뒤 stable 태그가 안 붙음", "CLOSED", "sora", "10-27", "배포", None, "stable 태그 없음", "", "Actions 재실행", [("sora", "10-27", t), ("sora", "10-27", s), ("sora", "10-27", t)][:3]),
    ]


def _trouble_world(name, extra_issues=()):
    """기록 화면 공통 상태: 저장소 둘(public-cloud 는 읽힘, cloud-b 는 gh 로그인 필요로 못 읽음), 세션 셋(왼쪽 목록), gh 흉내."""
    br = "docs/812-so-query"
    root = make_project(name, br)
    git(root, "remote", "set-url", "origin", f"https://github.com/{SLUG}.git")
    other = make_project(name + "-b", "docs/13-manual")
    git(other, "remote", "set-url", "origin", "https://github.com/example/cloud-b.git")
    (RUN / "trouble_state.json").write_text(json.dumps({
        "repos": {root.name: {"slug": SLUG}, other.name: {"error": "To get started with GitHub CLI, please run: gh auth login"}},
        "issues": {SLUG: _list_issues() + list(extra_issues)}, "labels": ["type:trouble"]}, ensure_ascii=False), encoding="utf-8")
    set_gh([pr(812, br, "OPEN", "판매오더 조회 앱", LOGIN, ["docs/ssot/SRS.md"], "fail")])
    return root, other


def _trouble_sessions(api, root, other):
    """시안의 왼쪽 세션 셋: 판매오더 조회 앱(기억 60%, PR #812 고쳐야 함) · 구매오더 매뉴얼(81%) · CTS 관리대장 11월(15%). 목록은 새 세션이 위."""
    api.post("/api/folders/last", {"path": str(other)})
    api.post("/api/folders/last", {"path": str(root)})
    hook_flow_session(api, "t3", other, "CTS 관리대장 11월", "srs", "srs", None, "작업 중", tokens=150_000, stop=False)
    hook_flow_session(api, "t2", other, "구매오더 매뉴얼", "srs", "srs", None, "작업 중", tokens=810_000, stop=False)
    hook_flow_session(api, "t1", root, "판매오더 조회 앱", "srs", "srs", "docs/ssot/SRS.md", "작업 중", tokens=600_000, stop=True)


def _trouble_ready(api, path):
    """목록 읽기는 60초 기억 + 백그라운드라 한 번 읽어 데워 둔다(못 읽은 저장소 줄도 나오도록)."""
    wait_for(lambda: (lambda d: d if d and not d["loading"] and len(d["projects"]) >= 2 else None)(api.get("/api/trouble")[1]), 30)
    return path


def g20(api):
    _trouble_sessions(api, *_trouble_world("proj-g20"))
    return _trouble_ready(api, "/troubles")


def g21(api):
    similar = [_issue(733, "ATC 금지 API 를 공개 API 로 바꿈", "CLOSED", "hyun", "10-20", "SAP 운송", None, "ATC 우선순위 1: 금지된 API 사용", "", "공개 API 로 바꿈"),
               _issue(771, "ATC 우선순위 2 지적 정리", "CLOSED", "sora", "10-25", "SAP 운송", None, "ATC 금지된 API 사용 지적", "", "정리함")]
    _trouble_sessions(api, *_trouble_world("proj-g21", similar))
    return _trouble_ready(api, f"/troubles/{SLUG}/842")


def g22(api):
    similar = [_issue(842, "ATC 검사에서 운송이 막힘", "OPEN", "sora", "11-05", "SAP 운송", 812, "ATC 우선순위 1: 금지된 API 사용")]
    root, other = _trouble_world("proj-g22")
    ts = json.loads((RUN / "trouble_state.json").read_text(encoding="utf-8"))
    ts["issues"][SLUG] = [i for i in ts["issues"][SLUG] if i["number"] != 842] + similar
    (RUN / "trouble_state.json").write_text(json.dumps(ts, ensure_ascii=False), encoding="utf-8")
    _trouble_sessions(api, root, other)
    _trouble_ready(api, "")
    st, d = api.post("/api/trouble/draft", {
        "repo": SLUG, "pr": "812", "stage": "SAP 운송", "title": "ATC 검사에서 운송이 막힘(금지 API)",
        "symptom": "ATC 우선순위 1: 금지된 API 사용\nCL_ABAP_RANDOM 는 ABAP Cloud 에서 쓸 수 없어\nclient_secret=abcd1234efgh", "cause": "공개 API 가 아닌 클래스를 호출함",
        "solution": "CL_ABAP_RANDOM 대신 XCO_.. 로 바꾸기", "solved": False, "source": {"title": "판매오더 조회 앱"}})
    assert st == 200, (st, d)
    return "/troubles/new?draft=" + d["id"]


# 시안 화면 번호 -> 상태 만드는 함수. 상태 만들기가 준비되면 여기에 더한다.
BUILDERS = {"G-04": g04, "G-05": g05, "G-06": g06, "G-09": g09, "G-10": g10, "G-12": g12, "G-13": g13, "G-15": g15,
            "G-20": g20, "G-21": g21, "G-22": g22}
