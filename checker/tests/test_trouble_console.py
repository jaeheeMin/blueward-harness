"""웹 콘솔 문제·해결 기록(#733, trouble.py·static/trouble.js) 시험. gh 는 상태를 가진 흉내로 바꿔 끼운다. 진짜 GitHub 는 부르지 않는다."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

from checker.tests.test_web_console import Console

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "plugins" / "harness" / "console"
STATIC = CONSOLE / "static"
sys.path.insert(0, str(CONSOLE))

import trouble  # noqa: E402

SLUG = "o/proj"


def issue(n, title, state="OPEN", pr=812, stage="SAP 운송", author="sora", symptom="ATC 금지된 API 사용", solution="", comments=(), label=True):
    return {"number": n, "title": "[기록] " + title, "state": state, "author": {"login": author}, "createdAt": "2026-11-05T05:00:00Z",
            "url": f"https://github.com/{SLUG}/issues/{n}", "labels": [{"name": "type:trouble"}] if label else [],
            "body": trouble.build_body(pr, stage, symptom, "", solution),
            "comments": [{"id": f"IC{n}-{i}", "author": {"login": a}, "body": b, "createdAt": "2026-11-06T05:00:00Z"} for i, (a, b) in enumerate(comments, 1)]}


class FakeGh:
    """gh issue/label/pr/repo 흉내. calls 에 명령을 모으고 쓰기는 issues 에 반영한다."""

    def __init__(self, fail: str | None = None, labels=("type:trouble",)):
        self.issues = [issue(842, "ATC 검사에서 운송이 막힘", comments=[("sora", "시도·안 됨: 재시도"), ("minjae", "해결 후보: XCO 로 바꾸기")]),
                       issue(837, "doc-guard 가 열 이름을 거절", state="CLOSED", pr=None, stage="문서 검사", solution="양식 v0.2"),
                       issue(500, "라벨 없는 이슈", label=False)]
        self.prs = [{"number": 812, "title": "판매오더 조회 앱", "state": "OPEN", "url": "u", "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "FAILURE"}]}]
        self.fail, self.labels, self.calls = fail, list(labels), []
        self.list_fail = False      # issue list 만 실패(저장소는 읽힘)
        self.write_timeout = False  # 쓰기 명령이 시간 초과(127, 출력 없음)

    def opt(self, a, name):
        return a[a.index(name) + 1] if name in a else None

    def __call__(self, args, cwd):
        a = args[1:]
        self.calls.append(" ".join(a[:2]))
        if args[0] != "gh":
            return (0, f"https://github.com/{SLUG}.git\n") if args[:3] == ["git", "config", "--get"] else (127, "")
        if self.write_timeout and a[:2] in (["issue", "create"], ["issue", "comment"], ["issue", "close"], ["issue", "edit"]):
            return 127, ""
        if self.fail:
            return 1, self.fail
        if a[:2] == ["repo", "view"]:
            return 0, json.dumps({"nameWithOwner": SLUG})
        if a[:2] == ["issue", "list"]:
            if self.list_fail:
                return 1, "HTTP 502 bad gateway"
            return 0, json.dumps([i for i in self.issues if i["labels"]])
        if a[:2] == ["pr", "list"]:
            return 0, json.dumps(self.prs)
        if a[:2] == ["pr", "view"]:
            hit = next((p for p in self.prs if str(p["number"]) == a[2]), None)
            return (0, json.dumps(hit)) if hit else (1, "GraphQL: Could not resolve to a PullRequest with the number of " + a[2])
        if a[:2] == ["label", "list"]:
            return 0, json.dumps([{"name": n} for n in self.labels])
        if a[:2] == ["issue", "create"]:
            n = 900 + len(self.issues)
            self.issues.append({"number": n, "title": self.opt(a, "--title"), "state": "OPEN", "author": {"login": "me"}, "createdAt": "2026-11-07T00:00:00Z",
                                "url": f"https://github.com/{SLUG}/issues/{n}", "labels": [{"name": self.opt(a, "--label")}], "body": self.opt(a, "--body"), "comments": []})
            return 0, f"https://github.com/{SLUG}/issues/{n}\n"
        hit = next((i for i in self.issues if str(i["number"]) == a[2]), None) if len(a) > 2 else None
        if a[:2] in (["issue", "view"], ["issue", "comment"], ["issue", "close"], ["issue", "edit"]):
            if hit is None:
                return 1, "GraphQL: Could not resolve to an Issue with the number of " + a[2]
            if a[1] == "comment":
                hit["comments"].append({"id": f"IC{hit['number']}-{len(hit['comments']) + 1}", "author": {"login": "me"}, "body": self.opt(a, "--body"), "createdAt": "x"})
            elif a[1] == "close":
                hit["state"] = "CLOSED"
            elif a[1] == "edit":
                hit["body"] = self.opt(a, "--body")
            return 0, json.dumps(hit) if a[1] == "view" else "ok\n"
        return 127, ""


def trouble_console(tmp_path, monkeypatch, gh):
    c = Console(tmp_path, monkeypatch, run=gh)
    c.login()
    c.event("t1", "SessionStart")
    return c


def test_list_reads_issues_filters_and_counts(tmp_path, monkeypatch):
    gh = FakeGh()
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        status, body, _ = c.call("GET", "/api/trouble")
        assert status == 200 and not body["loading"]
        assert [i["number"] for i in body["items"]] == [842, 837]  # 라벨 없는 이슈는 안 나온다
        first = body["items"][0]
        assert first["title"] == "ATC 검사에서 운송이 막힘" and first["pr"] == 812 and first["prTitle"] == "판매오더 조회 앱"
        assert (first["tries"], first["candidates"], first["solved"], first["stage"]) == (1, 1, False, "SAP 운송")
        assert body["stats"]["open"] == 1 and body["stats"]["solved"] == 1 and body["projects"][0]["ok"]
        assert [i["number"] for i in c.call("GET", "/api/trouble?status=solved")[1]["items"]] == [837]
        assert [i["number"] for i in c.call("GET", "/api/trouble?status=open")[1]["items"]] == [842]
        assert [i["number"] for i in c.call("GET", "/api/trouble?stage=" + urllib.parse.quote("문서 검사"))[1]["items"]] == [837]
        assert [i["number"] for i in c.call("GET", "/api/trouble?q=" + urllib.parse.quote("막힘"))[1]["items"]] == [842]
        n = len(gh.calls)
        c.call("GET", "/api/trouble")
        assert len(gh.calls) == n  # 60초 안에는 gh 를 다시 부르지 않는다
    finally:
        c.close()


def test_gh_failure_is_unknown_not_empty(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh(fail="gh auth login required (not logged in)"))
    try:
        body = c.call("GET", "/api/trouble")[1]
        assert body["items"] == [] and body["projects"] and not body["projects"][0]["ok"]
        assert "로그인" in body["projects"][0]["reason"]
        assert c.call("GET", "/api/trouble/item?repo=o/proj&number=842")[0] == 403  # 저장소를 못 읽으면 아는 저장소로 치지 않는다
    finally:
        c.close()


def test_item_parses_form_history_pr_and_similar(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh())
    try:
        status, d, _ = c.call("GET", "/api/trouble/item?repo=o/proj&number=842")
        assert status == 200 and d["symptom"] == "ATC 금지된 API 사용" and d["stage"] == "SAP 운송" and d["prNumber"] == 812
        assert [h["kind"] for h in d["history"]] == ["open", "try", "candidate"] and d["history"][2]["text"] == "XCO 로 바꾸기"
        assert d["pr"]["state"] == "ok" and d["pr"]["label"] == "고쳐야 함" and d["pr"]["failed"] == 1
        assert c.call("GET", "/api/trouble/item?repo=o/proj&number=500")[0] == 404  # 기록 라벨이 없으면 기록이 아니다
        assert c.call("GET", "/api/trouble/item?repo=o/proj&number=1")[0] in (404, 502)
        assert c.call("GET", "/api/trouble/item?repo=x/other&number=842")[0] == 403
        assert c.call("GET", "/api/trouble/pr?repo=o/proj&number=99")[1]["state"] == "missing"
        assert c.call("GET", "/api/trouble/pr?repo=o/proj&number=812")[1]["state"] == "ok"
        sim = c.call("GET", "/api/trouble/similar?repo=o/proj&q=" + urllib.parse.quote("ATC 검사에서 운송이 막힘 금지된 API"))[1]["items"]
        assert sim and sim[0]["number"] == 842
    finally:
        c.close()


def create_body(**over):
    return dict({"repo": SLUG, "pr": "#812", "stage": "SAP 운송", "title": "ATC 막힘", "symptom": "오류 문구\n둘째 줄", "cause": "", "solution": "", "solved": False}, **over)


def test_create_checks_label_secret_and_writes_form(tmp_path, monkeypatch):
    gh = FakeGh(labels=())
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        status, body, _ = c.call("POST", "/api/trouble", create_body())
        assert status == 409 and "type:trouble" in body["error"] and "issue create" not in gh.calls  # 라벨 없이 올리지 않는다
        gh.labels = ["type:trouble"]
        status, body, _ = c.call("POST", "/api/trouble", create_body(symptom="x\nclient_secret=Ab12cd34ef"))
        assert status == 422 and "issue create" not in gh.calls  # 비밀처럼 보이면 올리지 않는다
        assert c.call("POST", "/api/trouble", create_body(stage="없는 단계"))[0] == 400
        assert c.call("POST", "/api/trouble", create_body(repo="x/other"))[0] == 403
        assert c.call("POST", "/api/trouble", create_body(solved=True))[0] == 400  # 해결됐다면 방법이 있어야
        assert c.call("POST", "/api/trouble", create_body(), json_type=False, raw=b"{}")[0] == 415  # JSON 이 아닌 쓰기는 거절(기존 관례)
        status, body, _ = c.call("POST", "/api/trouble", create_body(solution="XCO 로 바꾸기"))
        assert status == 200 and body["number"] == 900 + 3 and not body["warnings"]
        made = gh.issues[-1]
        assert made["title"] == "[기록] ATC 막힘" and made["labels"] == [{"name": "type:trouble"}]
        parsed = trouble.parse_body(made["body"])
        assert parsed["pr"] == 812 and parsed["stage"] == "SAP 운송" and parsed["symptom"] == "오류 문구\n둘째 줄" and parsed["solution"] == ""
        assert [x["body"] for x in made["comments"]] == ["해결 후보: XCO 로 바꾸기"] and made["state"] == "OPEN"
        status, body, _ = c.call("POST", "/api/trouble", create_body(solved=True, solution="고침", title="[기록] 풀린 것"))
        made = gh.issues[-1]
        assert status == 200 and made["state"] == "CLOSED" and made["title"] == "[기록] 풀린 것" and made["comments"][0]["body"] == "해결: 고침"
        assert trouble.parse_body(made["body"])["solution"] == "고침"
        assert 903 in [i["number"] for i in c.call("GET", "/api/trouble")[1]["items"]]  # 올린 뒤 목록 기억이 새로고침된다
    finally:
        c.close()


def test_comment_and_resolve_write_marks_edit_body_and_close(tmp_path, monkeypatch):
    gh = FakeGh()
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        assert c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 842, "kind": "try", "text": "다시 해 봄"})[0] == 200
        assert gh.issues[0]["comments"][-1]["body"] == "시도·안 됨: 다시 해 봄" and gh.issues[0]["state"] == "OPEN"
        assert c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 842, "kind": "bad", "text": "x"})[0] == 400
        assert c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 842, "kind": "try", "text": "token=Zz9Yy8Xx7W"})[0] == 422
        assert c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 500, "kind": "try", "text": "x"})[0] == 404  # 기록이 아닌 이슈엔 못 쓴다
        assert c.call("POST", "/api/trouble/resolve", {"repo": SLUG, "number": 842, "commentId": "IC842-1"})[0] == 400  # 후보 댓글만
        status, body, _ = c.call("POST", "/api/trouble/resolve", {"repo": SLUG, "number": 842, "commentId": "IC842-2"})
        assert status == 200 and not body["warnings"]
        done = gh.issues[0]
        assert done["state"] == "CLOSED" and trouble.parse_body(done["body"])["solution"] == "XCO 로 바꾸기" and done["comments"][-1]["body"] == "해결: XCO 로 바꾸기"
        assert trouble.parse_body(done["body"])["symptom"] == "ATC 금지된 API 사용"  # 다른 칸은 그대로
        assert c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 837, "kind": "solved", "text": "다시 확인"})[0] == 200
    finally:
        c.close()


def test_check_and_draft_endpoints(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh())
    try:
        hits = c.call("POST", "/api/trouble/check", {"fields": {"symptom": "a\nclient_secret=Ab12cd34ef", "cause": "정상 글"}})[1]["hits"]
        assert hits == [{"field": "symptom", "line": 2, "label": "client_secret=…"}]
        did = c.call("POST", "/api/trouble/draft", {"repo": SLUG, "title": "초안", "source": {"title": "세션 이름"}})[1]["id"]
        got = c.call("GET", "/api/trouble/draft?id=" + did)[1]
        assert got["title"] == "초안" and got["source"]["title"] == "세션 이름"
        assert c.call("GET", "/api/trouble/draft?id=nope")[0] == 404
        assert c.call("GET", "/api/trouble")[0] == 200 and c.call("GET", "/troubles/o/proj/842", cookie=False, binary=True)[0] == 200  # 화면 주소는 index.html
    finally:
        c.close()


def test_api_needs_login(tmp_path, monkeypatch):
    c = Console(tmp_path, monkeypatch, run=FakeGh())
    try:
        assert c.call("GET", "/api/trouble", cookie=False)[0] == 401
        assert c.call("POST", "/api/trouble", create_body(), cookie=False)[0] == 401
    finally:
        c.close()


# ---- 순수 함수 ----
def test_pure_helpers():
    assert trouble.classify("시도·안 됨: 안 됐어") == ("try", "안 됐어") and trouble.classify("해결 후보:  A") == ("candidate", "A")
    assert trouble.classify("해결: B") == ("solved", "B") and trouble.classify("그냥 댓글")[0] == "note"
    assert trouble.classify("해결 후보: C")[0] == "candidate"  # '해결:' 보다 먼저 가려진다
    body = trouble.build_body(None, "배포", "증상", "", "")
    assert trouble.parse_body(body) == {"pr": None, "stage": "배포", "symptom": "증상", "cause": "", "solution": ""}
    assert "### 해결 방법\n\n새 방법" in trouble.replace_solution(body, "새 방법") and trouble.replace_solution("본문만", "x").endswith("### 해결 방법\n\nx\n")
    assert trouble.scan_secrets({"a": "password: required\nauthorization: Bearer abcdefghijklmnopqrstu\nsecret=<값>"})[0]["line"] == 1
    assert not trouble.scan_secrets({"a": "client_secret=••••••••\npassword: <값>\npassword: (생략)"})  # 가린 값은 걸지 않는다
    assert trouble.scan_secrets({"a": "ghp_" + "a" * 30})[0]["label"].startswith("GitHub")
    assert trouble.clean_title("[기록] 제목") == "제목" and trouble.clean_title("제목") == "제목"


# ---- 화면 로직(node) ----
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_trouble_js_helpers_and_screens_build_without_error():
    script = r"""
const path = require('path'); const assert = require('assert');
function El(t){this.tag=t;this.children=[];this.attrs={};this.listeners={};this.style={};this._t=null;this.parentNode=null;}
El.prototype={nodeType:1,appendChild(c){c.parentNode=this;this.children.push(c);return c;},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(n,f){(this.listeners[n]=this.listeners[n]||[]).push(f);},
 set textContent(v){this.children=[];this._t=String(v);},get textContent(){return this._t!==null?this._t:this.children.map(c=>c.nodeType===3?c.text:c.textContent).join('');},
 set className(v){this.attrs['class']=v;},get className(){return this.attrs['class']||'';},get firstChild(){return this.children[0]||null;},removeChild(c){this.children.splice(this.children.indexOf(c),1);},get scrollHeight(){return 0;},get clientHeight(){return 0;}};
global.document={createElement:t=>new El(t),createTextNode:s=>({nodeType:3,text:String(s)})};
global.window={}; require(path.join(process.argv[1],'trouble.js'));
const T=window.BHTrouble;
assert.strictEqual(T.itemHref('o/proj',7),'/troubles/o/proj/7');
assert.strictEqual(T.counts({tries:2,candidates:1,solvedNotes:0}),'시도 2 · 후보 1'); assert.strictEqual(T.counts({}),'');
assert.strictEqual(T.dateText('2026-11-05T05:00:00Z').length,5);
function h(tag,props){const el=new El(tag);Object.keys(props||{}).forEach(k=>{const v=props[k];if(v==null||v===false)return;if(k==='class')el.attrs['class']=v;else if(k==='text')el.textContent=v;else if(k.slice(0,2)==='on'&&typeof v==='function')el.addEventListener(k.slice(2).toLowerCase(),v);else el[k]=v;});
 const add=c=>{if(c==null||c===false)return;if(Array.isArray(c))return c.forEach(add);el.appendChild(typeof c==='object'?c:document.createTextNode(c));};for(let i=2;i<arguments.length;i++)add(arguments[i]);return el;}
const list={loading:false,roots:1,projects:[{slug:'o/p',name:'p',ok:true},{slug:null,name:'b',ok:false,reason:'GitHub 로그인이 필요해'}],authors:['sora'],stats:{total:1,month:1,open:1,solved:0,topStage:'SAP 운송'},matched:1,
 items:[{repo:'o/p',project:'p',number:1,title:'막힘',solved:false,author:'sora',createdAt:'2026-11-05T05:00:00Z',stage:'SAP 운송',pr:812,prTitle:'앱',tries:2,candidates:1,solvedNotes:0}]};
const kit={h,clear:el=>{el.children=[];el._t=null;return el;},qs:o=>'',link:(href,p,...r)=>h('a',Object.assign({href},p),...r),go(){},safeHttp:u=>u,loadingBox:()=>h('div'),
 api:(m,u)=>Promise.resolve(u.indexOf('/api/trouble')===0?list:{})};
const tb=T.create(kit); const root=h('div'); const v=tb.listView(root);
setTimeout(()=>{const t=root.textContent; assert.ok(t.includes('팀이 겪은 문제와 푼 방법')&&t.includes('아직 안 풀림')&&t.includes('시도 2 · 후보 1'),t);
 assert.ok(t.includes('? 확인 못 함')&&t.includes('GitHub 로그인이 필요해')&&t.includes('프로젝트 1곳'),t); v.destroy();
 /* 새 기록: 단계는 처음부터 골라져 있고, 올리기가 잠긴 이유를 단추 옆에 말한다 */
 const nroot=h('div'); const nv=tb.newView(nroot,{});
 setTimeout(()=>{const nt=nroot.textContent;
  assert.ok(nt.includes('아직 못 올려. 비어 있는 칸: 제목, 증상')&&!nt.includes('비어 있는 칸: 단계'),nt); nv.destroy();
  /* 한 건: 번호는 이름을 붙여 쓰고, 댓글 종류 기본값을 올리기 옆에서 말한다 */
  const iroot=h('div'); const iapi=Object.assign({},kit,{api:(m,u)=>Promise.resolve({number:15,title:'막힘',project:'PROJ',solved:false,author:'sora',createdAt:'2026-11-05T05:00:00Z',stage:'개발',symptom:'x',history:[],similar:[]})});
  const iv=T.create(iapi).itemView(iroot,'o/p',15);
  setTimeout(()=>{const it=iroot.textContent; assert.ok(it.includes('기록 번호 #15 · 프로젝트 PROJ')&&it.includes("'해결 후보' 로 올라가. 다르면 위에서 골라 줘."),it); iv.destroy(); console.log('ok');},50);
 },50);},50);
"""
    out = subprocess.run([NODE, "-e", script, "--", str(STATIC)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr + out.stdout


def test_index_and_menu_wire_trouble_screens():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index('src="/trouble.js"') < html.index('src="/app.js"') and 'href="/trouble.css"' in html
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "link('/troubles', { text: '기록'" in app and "troubleItem" in app and "troubleNew" in app
    from server import SPA_PATHS
    assert all(SPA_PATHS.match(p) for p in ("/troubles", "/troubles/new", "/troubles/o/proj/842")) and not SPA_PATHS.match("/troubles/x")
    assert re.search(r"font-size:\s*(\d+)px", (STATIC / "trouble.css").read_text(encoding="utf-8")) is None or max(
        int(n) for n in re.findall(r"font-size:\s*(\d+)px", (STATIC / "trouble.css").read_text(encoding="utf-8"))) <= 22


# ---- 리뷰 지적 보강 ----
@pytest.mark.parametrize("text", [
    '{"password": "abc123XYZ"}', "'api_key': 'sk-abcdefghijklmnopqrstuvwx'", "sk-proj-abcdefghijklmnopqrstuvwx", "ghp_" + "a" * 30,
    "AKIA" + "ABCDEFGHIJKLMNOP", "password: letmein", 'password: "my secret pass"', "PASSWORD=Zz9", "client_secret = 'a b c'",
    "github_pat_" + "A" * 30, "xoxb-1234567890-abcdef", "db_password: hunter2 연결 실패"])
def test_secret_scan_catches_each_form(text):
    hits = trouble.scan_secrets({"symptom": "앞 줄\n" + text})
    assert hits and hits[0]["line"] == 2, text


def test_secret_refusal_names_fields_in_plain_words():
    with pytest.raises(trouble.HttpError) as e:
        trouble.refuse_secrets({"text": "앞 줄\npassword: letmein"})
    assert "댓글 2번째 줄" in e.value.message and "text " not in e.value.message


def test_secret_labels_never_echo_the_value():
    hit = trouble.scan_secrets({"a": 'password: "my secret pass"'})[0]
    assert "secret pass" not in hit["label"] and hit["label"].endswith("=…")


def test_symptom_with_headings_and_fences_does_not_break_form_fields():
    symptom = "오류\n### 원인\n가짜 원인\n```\n코드\n### 해결 방법\n가짜 해결\n```\n끝"
    body = trouble.build_body(7, "배포", symptom, "진짜 원인", "")
    parsed = trouble.parse_body(body)
    assert parsed["symptom"] == symptom and parsed["cause"] == "진짜 원인" and parsed["solution"] == ""
    after = trouble.parse_body(trouble.replace_solution(body, "진짜 해결"))
    assert after["symptom"] == symptom and after["cause"] == "진짜 원인" and after["solution"] == "진짜 해결"
    # GitHub 양식이 만든 본문(펜스 세 개)에 ### 줄이 든 경우도 칸이 안 깨진다
    form = "### 관련 PR\n\n#1\n\n### 단계\n\n개발\n\n### 증상\n\n```text\na\n### 해결 방법\nx\n```\n\n### 원인\n\n_No response_\n\n### 해결 방법\n\n_No response_\n"
    got = trouble.parse_body(trouble.replace_solution(form, "고침"))
    assert got["symptom"] == "a\n### 해결 방법\nx" and got["solution"] == "고침"


def test_resolve_keeps_symptom_with_headings(tmp_path, monkeypatch):
    gh = FakeGh()
    gh.issues[0]["body"] = trouble.build_body(812, "SAP 운송", "줄\n### 해결 방법\n가짜\n```\n", "", "")
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        assert c.call("POST", "/api/trouble/resolve", {"repo": SLUG, "number": 842, "commentId": "IC842-2"})[0] == 200
        parsed = trouble.parse_body(gh.issues[0]["body"])
        assert parsed["symptom"] == "줄\n### 해결 방법\n가짜\n```" and parsed["solution"] == "XCO 로 바꾸기"
    finally:
        c.close()


def test_write_timeout_is_reported_as_unknown_outcome_not_failure(tmp_path, monkeypatch):
    gh = FakeGh()
    gh.write_timeout = True
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        status, body, _ = c.call("POST", "/api/trouble", create_body())
        assert status == 504 and "올렸는지 확인 못 함" in body["error"] and "같은 제목" in body["error"] and "못 했어" not in body["error"]
        status, body, _ = c.call("POST", "/api/trouble/comment", {"repo": SLUG, "number": 842, "kind": "try", "text": "x"})
        assert status == 504 and "목록을 새로고침" in body["error"]
        assert c.call("POST", "/api/trouble/resolve", {"repo": SLUG, "number": 842, "commentId": "IC842-2"})[0] == 504
        gh.write_timeout = False
        gh.issues.append(issue(950, "응답 없던 기록"))
        assert 950 in [i["number"] for i in c.call("GET", "/api/trouble")[1]["items"]]  # 시간 초과 뒤엔 목록 기억을 비워 새로 읽는다
    finally:
        c.close()


def test_item_says_unknown_when_similar_list_unreadable_and_pr_missing(tmp_path, monkeypatch):
    gh = FakeGh()
    gh.issues[0]["body"] = trouble.build_body(99, "SAP 운송", "x", "", "")
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        d = c.call("GET", "/api/trouble/item?repo=o/proj&number=842")[1]
        assert d["similarOk"] is True and d["pr"]["state"] == "missing"
        assert c.call("GET", "/api/trouble/similar?repo=o/proj&q=abc")[1]["ok"] is True
        gh.list_fail = True
        c.call("GET", "/api/trouble?refresh=1")
        d = c.call("GET", "/api/trouble/item?repo=o/proj&number=842")[1]
        assert d["similarOk"] is False and d["similar"] == []  # 목록을 못 읽었으면 "없음" 이 아니다
        assert c.call("GET", "/api/trouble/similar?repo=o/proj&q=abc")[1]["ok"] is False
    finally:
        c.close()


def test_list_marks_truncation_at_the_limit(tmp_path, monkeypatch):
    gh = FakeGh()
    gh.issues = [issue(1000 + n, f"기록 {n}") for n in range(trouble.LIST_LIMIT)]
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        body = c.call("GET", "/api/trouble")[1]
        assert body["stats"]["truncated"] == ["proj"] and body["stats"]["limit"] == 100 and body["projects"][0]["truncated"] is True
        gh.issues = gh.issues[:3]
        c.call("GET", "/api/trouble?refresh=1")
        assert c.call("GET", "/api/trouble")[1]["stats"]["truncated"] == []
    finally:
        c.close()


def test_worktrees_of_one_repo_cost_one_gh_read_and_failures_are_not_kept(tmp_path, monkeypatch):
    gh = FakeGh(fail="gh auth login required")
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        other = tmp_path / "work2"
        other.mkdir()
        c.hook("event", {"session_id": "t2", "cwd": str(other), "hook_event_name": "SessionStart"})
        body = c.call("GET", "/api/trouble")[1]
        assert len([p for p in body["projects"] if not p["ok"]]) == 1  # 같은 origin 의 폴더 둘이 하나로
        assert gh.calls.count("repo view") == 1
        gh.fail = None
        assert c.call("GET", "/api/trouble")[1]["projects"][0]["ok"] is False  # 실패는 아주 잠깐은 그대로
        c.clock.t += trouble.FAIL_TTL + 1
        body = c.call("GET", "/api/trouble")[1]
        assert body["projects"][0]["ok"] is True and len(body["items"]) == 2  # 곧 다시 읽어 회복한다(60초를 기다리지 않는다)
        assert gh.calls.count("repo view") == 2
    finally:
        c.close()


def test_draft_ids_are_unique_and_unguessable(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh())
    try:
        ids = {c.call("POST", "/api/trouble/draft", {"repo": SLUG, "title": f"초안 {n}"})[1]["id"] for n in range(30)}
        assert len(ids) == 30 and all(re.fullmatch(r"d-[0-9a-f]{12}", i) for i in ids)
        assert len(c.app.trouble_drafts) == trouble.DRAFT_MAX  # 오래된 것부터 밀려난다
    finally:
        c.close()


# ---- 세션 화면에서 만나는 곳(#734, 시안 G-23) ----
def draft_out(**over):
    data = dict({"title": "맨손 git push 가 막힘", "stage": "개발", "symptom": "그냥 git push 는 쓸 수 없어", "cause": "deliver 를 안 거침", "solution": "deliver 로 푸시", "solved": True}, **over)
    return json.dumps({"type": "result", "is_error": False, "structured_output": data}, ensure_ascii=False)


def session_with_chat(c, *chat):
    c.event("s1", "SessionStart")
    s = c.app.store.get("s1")
    for role, text in chat:
        c.app.store.add_chat(s, role, text)
    return s


def test_ai_draft_is_written_from_session_chat_with_secrets_hidden(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh())
    seen = {}
    try:
        session_with_chat(c, ("me", "푸시해 줘"), ("block", "그냥 git push 는 쓸 수 없어.\nclient_secret=Ab12cd34ef56"), ("ai", "deliver 로 다시 푸시했어"))

        def fake(app, prompt, cwd):
            seen["prompt"] = prompt
            return draft_out(solution="deliver 로 푸시\npassword: hunter2hunter2")
        c.app.trouble_claude = fake
        status, body, _ = c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})
        assert status == 200 and body["hidden"] == 2
        assert "client_secret=Ab12cd34ef56" not in seen["prompt"] and trouble.HIDDEN_LINE in seen["prompt"] and "푸시해 줘" in seen["prompt"]  # 모델에 보내기 전에 가린다
        d = c.call("GET", "/api/trouble/draft?id=" + body["id"])[1]
        assert d["repo"] == SLUG and d["stage"] == "개발" and d["title"] == "맨손 git push 가 막힘" and d["solved"] is True and d["hidden"] == 2
        assert "hunter2" not in d["solution"] and trouble.HIDDEN_LINE in d["solution"]  # 모델이 쓴 글도 가린다
        assert not trouble.scan_secrets({k: d[k] for k in ("title", "symptom", "cause", "solution")})
    finally:
        c.close()


def test_ai_draft_failures_are_reported_not_faked(tmp_path, monkeypatch):
    c = trouble_console(tmp_path, monkeypatch, FakeGh())
    try:
        assert c.call("POST", "/api/trouble/ai-draft", {"sessionId": "nope"})[0] == 404
        assert c.call("POST", "/api/trouble/ai-draft", {})[0] == 400
        session_with_chat(c)
        assert c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})[0] == 422  # 대화가 없으면 초안을 지어내지 않는다
        session_with_chat(c, ("ai", "막혔어"))
        c.app.trouble_claude = lambda app, prompt, cwd: "not json"
        status, body, _ = c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})
        assert status == 502 and "초안을 못 만들었어" in body["error"]
        c.app.trouble_claude = lambda app, prompt, cwd: draft_out(symptom="")
        assert c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})[0] == 502
        def boom(app, prompt, cwd):
            raise trouble.HttpError(504, "초안을 못 만들었어 · 시간 안에 끝나지 않았어")
        c.app.trouble_claude = boom
        assert c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})[0] == 504
        assert not c.app.__dict__.get("trouble_drafts")  # 실패하면 초안이 남지 않는다
        c.app.analyses.claude_cmd = lambda: None
        del c.app.trouble_claude
        assert c.call("POST", "/api/trouble/ai-draft", {"sessionId": "s1"})[0] == 503
    finally:
        c.close()


def test_similar_by_session_folder_and_unknown_when_unreadable(tmp_path, monkeypatch):
    gh = FakeGh()
    c = trouble_console(tmp_path, monkeypatch, gh)
    try:
        q = urllib.parse.quote("ATC 검사에서 운송이 막힘 금지된 API")
        status, body, _ = c.call("GET", f"/api/trouble/similar?cwd={urllib.parse.quote(str(c.work))}&q={q}")
        assert status == 200 and body["ok"] and body["slug"] == SLUG and body["items"] and body["items"][0]["number"] == 842
        (tmp_path / "b").mkdir()
        bad = trouble_console(tmp_path / "b", monkeypatch, FakeGh(fail="gh auth login required (not logged in)"))
        try:
            body = bad.call("GET", f"/api/trouble/similar?cwd={urllib.parse.quote(str(bad.work))}&q={q}")[1]
            assert body["ok"] is False and body["items"] == [] and "로그인" in body["reason"]  # 없음이 아니라 확인 못 함
        finally:
            bad.close()
    finally:
        c.close()


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_suggest_conditions_and_session_cards():
    script = r"""
const path = require('path'); const assert = require('assert');
global.window = {}; global.document = {}; require(path.join(process.argv[1], 'trouble.js'));
const S = window.BHTrouble.suggestFor;
const chat = (...r) => r.map((role, i) => ({ t: i + 1, role, kind: role === 'block' ? 'blocked' : undefined }));
assert.strictEqual(S({ status: 'idle', chat: chat('ai', 'block', 'me', 'ai') }).key, 'b2');  // 막힘 뒤 AI 말 + 쉬는 중
assert.strictEqual(S({ status: 'idle', chat: chat('ai', 'block') }), null);                  // 아직 풀리지 않음
assert.strictEqual(S({ status: 'running', chat: chat('block', 'ai') }), null);                // 일하는 중엔 권하지 않는다
assert.strictEqual(S({ status: 'idle', pendingRequestIds: ['r'], chat: chat('block', 'ai') }), null);
assert.strictEqual(S({ status: 'idle', chat: [{ t: 1, role: 'block', kind: 'cannot_check' }, { t: 2, role: 'ai' }] }), null);  // 확인 못 함은 풀렸는지 모른다
assert.strictEqual(S({ status: 'idle', chat: chat('block', 'ai', 'block') }), null);          // 새 막힘이 풀리기 전
assert.strictEqual(S({ status: 'idle', chat: [], flowPr: { number: 7, checks: 'pass' } }, 7).key, 'pr7');  // 실패로 본 PR 이 통과
assert.strictEqual(S({ status: 'idle', chat: [], flowPr: { number: 7, checks: 'pass' } }, undefined), null);
assert.strictEqual(S({ status: 'idle', chat: [], flowPr: { number: 7, checks: 'pass' } }, 8), null);
assert.strictEqual(S({ status: 'idle', chat: [], flowPr: { number: 7, checks: 'fail' } }, 7), null);
console.log('ok');
"""
    out = subprocess.run([NODE, "-e", script, "--", str(STATIC)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr + out.stdout


# ---- 비밀 값 가리기(#827): 서버 mask_secrets 와 화면 BHLogic.maskSecrets 가 같은 결과 ----
_MASK_SAMPLES = [
    "client_secret=abcd1234efgh", '{"password": "abc123XYZ"}', "'api_key': 'sk-abcdefghijklmnopqrstuvwx'",
    "sk-proj-abcdefghijklmnopqrstuvwx", "ghp_" + "a" * 30, "AKIA" + "ABCDEFGHIJKLMNOP", "password: letmein",
    'password: "my secret pass"', "PASSWORD=Zz9", "client_secret = 'a b c'", "github_pat_" + "A" * 30,
    "xoxb-1234567890-abcdef", "db_password: hunter2 연결 실패", "Authorization: Bearer abcdefghijklmnopqrstuvwx",
    "https://user:pa55word@example.com/repo.git", "ATC 우선순위 1: 금지된 API 사용\nclient_secret=abcd1234efgh\n끝",
    # 가리면 안 되는 글
    "password 정책을 바꿨다", "토큰 만료 시간이 짧다", "token: ••••••••", "api_key=<키>", "secret=(생략)", "일반 문장이야.",
]


@pytest.mark.skipif(not NODE, reason="node 없음")
def test_mask_secrets_same_on_server_and_screen_and_masked_text_is_not_a_secret():
    script = r"""
const path = require('path');
const L = require(path.join(process.argv[1], 'flow-logic.js'));
const samples = JSON.parse(require('fs').readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(samples.map(L.maskSecrets)));
"""
    out = subprocess.run([NODE, "-e", script, str(STATIC)], input=json.dumps(_MASK_SAMPLES), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    screen = json.loads(out.stdout)
    server = [trouble.mask_secrets(s) for s in _MASK_SAMPLES]
    assert screen == server  # 두 쪽 규칙이 어긋나지 않는다
    for raw, masked in zip(_MASK_SAMPLES, server):
        assert not trouble.scan_secrets({"symptom": masked}), (raw, masked)  # 가린 글은 저장할 수 있다
    assert server[0] == "client_secret=" + trouble.MASK and "abcd1234efgh" not in server[15] and "pa55word" not in server[14]
    for keep in _MASK_SAMPLES[16:]:
        assert trouble.mask_secrets(keep) == keep, keep  # 값이 없는 말·이미 가린 값·자리표시는 그대로
