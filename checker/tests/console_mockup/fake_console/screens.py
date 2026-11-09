"""화면마다 시험 콘솔 상태를 만든다. build(api) 는 서버를 띄운 뒤 부르고, 브라우저가 열 경로(/s/g09 등)를 돌려준다.
상태 만드는 방법은 화면 번호(시안 G-xx)와 같은 이름의 함수 g04·g05 … 로 둔다. 새 화면을 더하려면 함수를 만들고 BUILDERS 에 올린다."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse

from .lib import (HERE, LOGIN, RUN, WORK, ANALYSIS, rmtree, add_req_row, git, hook_flow_session, make_project, make_xlsx, pr, set_gh, start_server, transcript, write,
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


def _checks_ready(api):
    """첫 화면의 시작 점검(GitHub·하네스 판·Claude Code)은 백그라운드 + 60초 기억이라 한 번 읽어 데워 둔다."""
    wait_for(lambda: (lambda d: d if d and not d.get("loading") and d.get("checks") else None)(api.get("/api/start-checks")[1]), 30)


def g01(api):
    """시안 G-01: 첫 실행 환영 화면(점검 셋). 첫 실행은 check_console 이 화면 설정 first_run 으로 만든다."""
    _checks_ready(api)
    return "/"


def _pick_world(api):
    """시안 G-02 의 최근 폴더 둘: harness-console-sandbox(하네스 구조 없음 = 준비 필요), public-cloud(준비됨 · 세션 2)."""
    box = WORK / "harness-console-sandbox"
    rmtree(box)
    box.mkdir(parents=True)
    git(box, "init", "-q", "-b", "main")
    write(box / "README.md", "# sandbox\n")
    git(box, "add", "-A")
    git(box, "commit", "-q", "-m", "init")
    root = make_project("public-cloud", "main")
    hook_flow_session(api, "p1", root, "구매오더 매뉴얼", "srs", "srs", None, "작업 중", stop=False)
    hook_flow_session(api, "p2", root, "CTS 관리대장 11월", "srs", "srs", None, "작업 중", stop=False)
    api.post("/api/folders/last", {"path": str(root)})
    api.post("/api/folders/last", {"path": str(box)})  # 나중에 쓴 것이 위(시안은 sandbox 가 첫 줄)
    api.get("/api/folders/recent")  # 준비 판정은 백그라운드: 한 번 불러 두고 끝날 때까지
    wait_for(lambda: (lambda r: r if r and len(r) >= 2 and not any(x["checking"] for x in r) else None)(api.get("/api/folders/recent")[1]), 30)
    _checks_ready(api)


def g02(api):
    """시안 G-02: 첫 화면 둘째 쪽(프로젝트 고르기). 화면 설정 clicks 가 '시작하기' 와 첫 폴더 고르기를 누른다."""
    _pick_world(api)
    return "/"


def g03(api):
    """시안 G-03: 준비 안 된 폴더를 골라 '이 프로젝트로' 를 누르면 가는 새 작업 화면의 표준 구조 만들기 안내."""
    _pick_world(api)
    return "/"


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
    _hold_request(api, real, "question", "g13", {"session_id": real, "cwd": c, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                                 "tool_input": {"questions": qs}})
    return f"/s/{real}"


def _hold_request(api, real, kind, tag, body):
    """질문(question)·승인(permission) 요청을 훅이 보낸 것처럼 쌓고, 화면에 카드가 남도록 연결을 붙든다. 요청 번호를 돌려준다."""
    body_file = RUN / f"{kind}_{tag}.json"
    body_file.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    # 연결을 붙드는 별도 프로세스로 보낸다(연결이 끊기면 서버가 요청을 닫는다). 서버를 끄면 같이 끝난다.
    detach = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}
    subprocess.Popen([sys.executable, "-B", str(HERE / "hold_hook.py"), kind, str(body_file)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, close_fds=True, **detach)
    return wait_for(lambda: ((api.get(f"/api/sessions/{real}")[1] or {}).get("pendingRequestIds") or [None])[0], 10)


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


def _my_prs_ready(api, root):
    """내 PR 목록 읽기도 백그라운드(처음엔 loading)라 한 번 읽어 데워 둔다(홈의 '고쳐야 할 내 PR' 줄이 처음 그릴 때 보이도록)."""
    q = urllib.parse.quote(str(root))
    wait_for(lambda: (lambda d: d if d and not d.get("loading") else None)(api.get("/api/my-prs?cwd=" + q)[1]), 30)


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


def g23(api):
    """시안 G-23: 막힘 카드 + 비슷한 기록 줄 + 풀린 뒤 '기록해 둘까?' 카드. 막힘은 훅이 보낸 것처럼 /hooks/blocked 로 쌓는다."""
    similar = [_issue(790, "deliver 가 git 명령 검사에 막힘", "CLOSED", "hyun", "10-30", "개발", None, "하네스 검사가 막았어: git 명령 검사 그냥 git push 는 쓸 수 없어", "", "올리기 단계로 푸시함"),
               _issue(655, "맨손 git push 가 거절됨", "CLOSED", "sora", "10-12", "개발", None, "하네스 검사가 막았어: git 명령 검사 그냥 git push 는 쓸 수 없어", "", "올리기 단계로 푸시함")]
    root, other = _trouble_world("proj-g23", similar)
    api.post("/api/folders/last", {"path": str(other)})
    api.post("/api/folders/last", {"path": str(root)})
    c = str(root)
    hook_flow_session(api, "t3", other, "CTS 관리대장 11월", "srs", "srs", None, "작업 중", tokens=150_000, stop=False)
    hook_flow_session(api, "t2", other, "구매오더 매뉴얼", "srs", "srs", None, "작업 중", tokens=810_000, stop=False)
    # 막힘 카드의 [그렇게 고쳐 줘] 는 보낼 수 있는 세션(콘솔이 띄운 것)에만 나온다: 콘솔이 띄운 가짜 claude 세션에 막힘을 쌓는다.
    srs_analysis()
    _jid, sid = managed_session(api, root, "판매오더 조회 앱")
    wait_for(lambda: sess(api, sid).get("report", "").startswith("echo"), 20)
    real = sess(api, sid)["id"]
    api.stop(real, c, "푸시하려고 git 명령을 썼는데 하네스 검사가 막았어.")
    st, d = api.hook("blocked", {"session_id": real, "cwd": c, "hook": "pre-bash-git-guard", "tool_name": "Bash",
                                 "reason": "그냥 git push 는 쓸 수 없어. 푸시는 올리기 단계로만 할 수 있어.\n다음: 올리기 단계로 푸시하면 돼."})
    assert st == 200, (st, d)
    api.event(real, c, "UserPromptSubmit", prompt="그렇게 고쳐 줘")
    api.stop(real, c, "올리기 단계로 다시 푸시했고, 검사 다시 돌렸고 통과했어.")
    _trouble_ready(api, "")
    return f"/s/{real}"


def g24(api):
    """시안 G-24: 홈에 '고쳐야 할 내 PR' 줄과 '팀 기록 · 아직 안 풀린 문제' 타일(세션 셋·PR #812 검사 실패·열린 기록 3건)."""
    root, other = _trouble_world("proj-g24")
    add_req_row(root)  # SRS 에 요구사항을 더한 근거(g10 과 같다): 쓰기 단계가 끝나야 콘솔이 PR 을 세션과 연결한다
    # 시안 G-24 의 첫 세션: SRS 를 올려 PR #812 가 열렸고 검사가 실패한 상태(G-10 과 같은 순서로 쓰기 -> 멈춤). 콘솔이 PR 을 세션과 연결해야 "고쳐야 함" 이 된다.
    api.post("/api/folders/last", {"path": str(other)})
    api.post("/api/folders/last", {"path": str(root)})
    hook_flow_session(api, "t3", other, "CTS 관리대장 11월", "srs", "srs", None, "작업 중", tokens=150_000, stop=False)
    hook_flow_session(api, "t2", other, "구매오더 매뉴얼", "srs", "srs", None, "작업 중", tokens=810_000, stop=False)
    hook_flow_session(api, "t1", root, "판매오더 조회 앱", "srs", "srs", "docs/ssot/SRS.md", "SRS 를 올렸어요. 검사가 실패했어요.", tokens=600_000, stop=True)
    _my_prs_ready(api, root)
    return _trouble_ready(api, "/")


def _managed_srs(api, name, text, tokens=None, branch="main", req=False):
    """콘솔이 띄운(managed) 가짜 claude 세션 하나(SRS 갈래). (작업 폴더, 세션 id) 를 돌려준다. tokens 를 주면 기억 사용량도 그만큼으로 하고,
    req 면 세션을 띄우기 전에 SRS 에 요구사항 줄을 더해 둔다(바뀐 파일은 처음 읽을 때 정해진다)."""
    root = make_project(name, branch)
    if req:
        add_req_row(root)
    srs_analysis()
    api.post("/api/folders/last", {"path": str(root)})
    _jid, sid = managed_session(api, root, text)
    wait_for(lambda: sess(api, sid).get("report", "").startswith("echo"), 20)
    real = sess(api, sid)["id"]
    for chk in ("sync", "version"):  # 시작 점검(최신 내용 받기 · 하네스 판)을 끝낸 것으로: 안 끝나면 오른쪽 칸이 숨는다
        api.event(real, str(root), "PreToolUse", tool_name="Skill", tool_input={"skill": f"harness:{chk}"})
    if tokens:
        api.event(real, str(root), "SessionStart", model="claude-opus-4-7", transcript_path=transcript(real, tokens))
    return root, real


def _hub_world(api, tag, mine=True):
    """시안 G-11·14·16~19 의 왼쪽 세션 셋 중 다른 둘: 구매오더 매뉴얼(81%, 일하는 중) · CTS 관리대장 11월(15%, PR #3 승인 기다림).
    mine 이면 첫째 세션 '구매오더 요구사항'(42%, 내 차례 · 올리기)도 만든다. 첫째 세션의 작업 폴더를 돌려준다."""
    cts_br, man_br = "docs/3-cts-ledger", "docs/7-manual"
    cts, man = make_project(f"proj-{tag}-cts", cts_br), make_project(f"proj-{tag}-man", man_br)
    add_req_row(cts)
    set_gh([pr(3, cts_br, "OPEN", "CTS 관리대장 11월", LOGIN, ["docs/ssot/SRS.md"], "pending"),
            pr(9, "docs/9-other", "OPEN", "SRS: 승인 요청 시험 PR", "teammate", ["docs/ssot/SRS.md"], "pass")])  # 둘째는 내 승인을 기다리는 남의 PR(홈 '승인 기다리는 PR' 칸)
    api.post("/api/folders/last", {"path": str(cts)})
    api.post("/api/folders/last", {"path": str(man)})
    hook_flow_session(api, "h3", cts, "CTS 관리대장 11월", "srs", "srs", "docs/ssot/SRS.md", "CTS 관리대장을 올렸어요. 승인을 기다리는 중이에요.", tokens=150_000)
    hook_flow_session(api, "h2", man, "구매오더 매뉴얼", "srs", "srs", None, "작업 중", tokens=810_000, stop=False)
    root = None
    if mine:
        root = make_project(f"proj-{tag}", "docs/4-srs-purchase-order")
        write(root / "audit" / "changes" / "REQ-001.md", "# 변경 기록\n\n- REQ-001 구매오더 조회 앱 추가\n")
        time.sleep(0.05)
        add_req_row(root)  # SRS 가 더 나중에 바뀐 파일이라 산출물 화면에서 고른 문서가 된다
        api.post("/api/folders/last", {"path": str(root)})
        hook_flow_session(api, "h1", root, "구매오더 조회 앱 요구사항", "srs", "srs", "audit/changes/REQ-001.md",
                          "SRS 에 REQ-001 을 더했어요.", tokens=420_000, extra_files=["docs/ssot/SRS.md"])  # SRS 를 나중에 써야 산출물 화면에서 SRS 가 고른 문서다
    return root


def g07(api):
    """시안 G-07: AI 의 질문 둘(우선순위 · 요청 출처)을 한 번에 묻는 카드. 세션 하나, 기억 12%."""
    root, real = _managed_srs(api, "proj-g07", "구매오더 조회 앱 요구사항", tokens=120_000)
    c = str(root)
    api.event(real, c, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:srs"})
    qs = [{"question": "이 앱은 얼마나 급해?", "header": "우선순위", "multiSelect": False,
           "options": [{"label": "반드시 필요", "description": "없으면 업무가 멈춰"}, {"label": "중요", "description": "빨리 필요해"},
                       {"label": "있으면 좋음", "description": "여유가 있을 때"}, {"label": "아직 모름", "description": "나중에 정해"}]},
          {"question": "누가 언제 요청했어?", "header": "요청 출처", "multiSelect": False,
           "options": [{"label": "모름 · 나중에 확인", "description": "비워 두고 이어서 써"}, {"label": "직접 적기", "description": "아래 칸에 적어"}]}]
    _hold_request(api, real, "question", "g07", {"session_id": real, "cwd": c, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                                                 "tool_input": {"questions": qs}})
    return f"/s/{real}"


def g08(api):
    """시안 G-08: AI 가 일하는 중(순서 체크리스트 · 오른쪽에 쓰는 중인 문서). 세션 하나, 기억 12%."""
    root, real = _managed_srs(api, "proj-g08", "구매오더 조회 앱 요구사항", tokens=120_000, branch="docs/4-srs-purchase-order", req=True)  # 콘솔이 띄운 세션이라 [작업 멈추기] 가 나온다
    c = str(root)
    api.event(real, c, "UserPromptSubmit", prompt="구매오더 조회 앱 요구사항")
    api.event(real, c, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:srs"})
    fp = str(root / "docs" / "ssot" / "SRS.md")
    api.event(real, c, "PreToolUse", tool_name="Write", tool_input={"file_path": fp, "content": "x"})
    api.event(real, c, "PostToolUse", tool_name="Write", tool_input={"file_path": fp, "content": "x"}, tool_response="ok")
    api.event(real, c, "PreToolUse", tool_name="Read", tool_input={"file_path": fp})  # 마지막 이벤트가 도구 호출이라 일하는 중으로 남는다
    wait_for(lambda: api.get(f"/api/sessions/{real}")[1].get("branch"), 15)  # git 정보는 백그라운드로 읽힌다(훅 세션은 hook_flow_session 이 기다린다)
    return f"/s/{real}"


def g11(api):
    """시안 G-11: 홈(오늘 내 일) - 세션 셋, 내 차례 1건(구매오더 요구사항 올리기), 승인 기다리는 PR 1건."""
    root = _hub_world(api, "g11")
    # 팀 기록 타일(시안 G-24 에서 생긴 다섯째 칸)은 기록을 읽을 수 있어야 한 줄 모양이다(못 읽으면 보라 점선 안내로 더 길어진다).
    git(root, "remote", "set-url", "origin", f"https://github.com/{SLUG}.git")
    (RUN / "trouble_state.json").write_text(json.dumps({"repos": {root.name: {"slug": SLUG}}, "issues": {SLUG: _list_issues()}, "labels": ["type:trouble"]},
                                                       ensure_ascii=False), encoding="utf-8")
    wait_for(lambda: (lambda d: d if d and not d["loading"] and d["projects"] else None)(api.get("/api/trouble")[1]), 30)
    _my_prs_ready(api, root)
    return "/"


def g14(api):
    """시안 G-14: 산출물(내가 만든 문서) - 세션 셋, 요구사항정의서 v0.1 안 올림이 고른 문서."""
    _hub_world(api, "g14")
    return "/docs"


def g16(api):
    """시안 G-16: 막힘(✕) 카드 + 확인 못 함(?) 카드. 막힘은 Spec 세션(기억 23%), 확인 못 함은 다른 세션(CTS)에서 난 것으로 쌓는다."""
    _hub_world(api, "g16", mine=False)
    root, real = _managed_srs(api, "proj-g16", "구매오더 조회 앱 개발 Spec 쓰기", tokens=230_000)
    c = str(root)
    cannot = "AI 리뷰를 확인하지 못했어. 검토 도구에 접속하지 못했어(인증 오류).\n다음: 검사를 다시 돌려 봐."
    # 시안의 ? 확인 못 함은 다른 세션(CTS) 일이라 그 세션에 쌓는다(맨 위 띠·사이드바). 이 세션 대화에도 한 장 둔다: 그 뒤에 내 말·AI 말이 이어지면
    # 풀린 것으로 보므로, 이 세션이 막힘으로 남도록 마지막은 막힘 카드다.
    api.hook("blocked", {"session_id": "h3", "cwd": str(WORK / "proj-g16-cts"), "hook": "pre_write_guard", "tool_name": "Write", "reason": cannot})
    api.hook("blocked", {"session_id": real, "cwd": c, "hook": "pre_write_guard", "tool_name": "Write", "reason": cannot})
    api.event(real, c, "UserPromptSubmit", prompt="다시 돌려 줘")
    api.stop(real, c, "다시 돌려 봤는데 이번에는 Spec 저장이 막혔어.")
    st, d = api.hook("blocked", {"session_id": real, "cwd": c, "hook": "pre_write_guard", "tool_name": "Write",
                                 "reason": "저장 안 됨 — 양식에 없는 칸이 있어. Spec 화면 표에 '비고2' 칸이 들어갔는데 고객 양식에는 없어.\n다음: '비고2' 내용을 '비고' 칸으로 옮기면 돼."})
    assert st == 200, (st, d)
    return f"/s/{real}"


def g17(api):
    """시안 G-17: 되돌릴 수 없는 일(작업 폴더 밖 파일 지우기)을 묻는 확인 카드. 세션 기억 55%."""
    _hub_world(api, "g17", mine=False)
    root, real = _managed_srs(api, "proj-g17", "구매오더 조회 앱 개발 Spec 쓰기", tokens=550_000)
    c = str(root)
    api.event(real, c, "PreToolUse", tool_name="Skill", tool_input={"skill": "harness:spec"})
    target = str(WORK.parent / "Desktop" / "구매오더_Spec_초안_old.xlsx")  # 작업 폴더 밖
    rid = _hold_request(api, real, "permission", "g17", {
        "session_id": real, "cwd": c, "hook_event_name": "PermissionRequest", "tool_name": "Bash",
        "tool_input": {"command": f'rm "{target}"', "description": "이전 Spec 초안 파일 지우기"}})
    assert rid, "승인 요청이 안 쌓였다"
    return f"/r/{rid}"


def g18(api):
    """시안 G-18: 기억 92% - 맨 위 노란 배너(새 세션으로 넘기기 · 계속하기). 일하는 중인 매뉴얼 세션."""
    _hub_world(api, "g18", mine=False)
    root, real = _managed_srs(api, "proj-g18", "구매오더 조회 사용자 매뉴얼", tokens=920_000)
    c = str(root)
    api.event(real, c, "UserPromptSubmit", prompt="구매오더 조회 사용자 매뉴얼", model="claude-opus-4-7", transcript_path=transcript(real, 920_000))
    return f"/s/{real}"


def g19(api):
    """시안 G-19: 설정(보기와 알림). 세션 셋은 G-11 과 같다."""
    _hub_world(api, "g19")
    return "/settings"


# 시안 화면 번호 -> 상태 만드는 함수. 상태 만들기가 준비되면 여기에 더한다.
BUILDERS = {"G-01": g01, "G-02": g02, "G-03": g03, "G-04": g04, "G-05": g05, "G-06": g06, "G-07": g07, "G-08": g08, "G-09": g09, "G-10": g10,
            "G-11": g11, "G-12": g12, "G-13": g13, "G-14": g14, "G-15": g15, "G-16": g16, "G-17": g17, "G-18": g18, "G-19": g19,
            "G-20": g20, "G-21": g21, "G-22": g22, "G-23": g23, "G-24": g24}
