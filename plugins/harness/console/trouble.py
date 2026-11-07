"""문제·해결 기록(#733): 프로젝트 저장소의 `type:trouble` 이슈를 gh 로 읽고 쓴다.

읽기는 목록 60초 기억(App.cached), 한 건은 그때그때 읽는다. 쓰기는 사람이 단추를 눌렀을 때만, 이슈 만들기·댓글·해결 닫기(본문 해결 방법 갱신 + 닫기)뿐이다.
저장소는 콘솔이 아는 작업 폴더(known_roots)의 것만 쓴다. gh 가 실패하면 "기록 없음" 이 아니라 확인 못 함 + 사유로 돌려준다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone

import gitstate


class HttpError(Exception):
    """server.py 가 HttpError 로 바꿔 응답한다(순환 import 를 피하려고 여기서 따로 둔다)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message

LABEL = "type:trouble"
PREFIX = "[기록] "
STAGES = ["개발", "문서 검사", "SAP 운송", "배포", "기타"]
KIND_MARK = {"try": "시도·안 됨:", "candidate": "해결 후보:", "solved": "해결:"}
KIND_RE = [("try", re.compile(r"^\s*시도\s*[·.]?\s*안\s*됨\s*[:：]\s*")), ("candidate", re.compile(r"^\s*해결\s*후보\s*[:：]\s*")),
           ("solved", re.compile(r"^\s*해결\s*[:：]\s*"))]
NO_RESPONSE = "_No response_"
FIELD_MAX = 8000
TITLE_MAX = 200
LIST_LIMIT = 100
FAIL_TTL = 10.0  # 못 읽은 결과는 이 시간 뒤 다시 읽는다(60초 기억에 실패를 가두지 않는다)
DRAFT_MAX = 20
LOGIN_WORDS = ("gh auth login", "not logged in", "authentication", "bad credentials", "401", "no oauth token")
NOT_GITHUB = ("none of the git remotes", "not a git repository", "no git remotes", "could not determine")
SLUG = re.compile(r"[\w.-]+/[\w.-]+")

SECRET_NAME = r"[\w.-]*(?:secret|password|passwd|pwd|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|credential)[\w.-]*"
# 이름 뒤에 따옴표가 와도 되고(JSON·딕셔너리), 값이 따옴표로 싸이면 따옴표 안 전체를 값으로 본다.
SECRET_ASSIGN = re.compile(r"(?i)\b(" + SECRET_NAME + r")[\"']?\s*[:=]\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\"']{3,}))")
SECRET_OTHER = [(re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "GitHub 토큰"), (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "GitHub 토큰"),
                (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS 키"), (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "API 키"),
                (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "Slack 토큰"),
                (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "개인 키"),
                (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "JWT"),
                (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{16,}"), "Bearer 토큰"), (re.compile(r"://[^/\s:@]+:[^/\s@]{3,}@"), "주소에 든 비밀번호")]
PLACEHOLDER = re.compile(r"^[•*x.\-_<>…()\[\]{}#]+$|^<.*>$|^\(생략\)$", re.I)


# ---- 순수 함수 ----
def scan_secrets(fields: dict) -> list[dict]:
    """비밀번호·키처럼 보이는 줄. 값은 돌려주지 않고 `이름=…` 꼴 표시만 준다."""
    hits = []
    for field, text in fields.items():
        for no, line in enumerate(str(text or "").splitlines(), 1):
            label = None
            for m in SECRET_ASSIGN.finditer(line):
                value = m.group(2) or m.group(3) or m.group(4) or ""
                if PLACEHOLDER.match(value.strip()):
                    continue
                label = m.group(1) + "=…"
                break
            if label is None:
                for rx, name in SECRET_OTHER:
                    if rx.search(line):
                        label = name + "…"
                        break
            if label:
                hits.append({"field": field, "line": no, "label": label})
    return hits


def fence_len(line: str) -> int:
    m = re.match(r" {0,3}(`{3,})", line)
    return len(m.group(1)) if m else 0


def sections(text: str) -> list[tuple[str, int, int, str]]:
    """`### 칸이름` 으로 나눈다. 코드 펜스 안의 `### ` 는 칸 머리로 보지 않는다. [(이름, 시작, 끝, 값)] (시작·끝은 text 안 글자 위치)."""
    out, name, start, body_from, pos, fence = [], None, 0, 0, 0, 0
    for line in text.split("\n"):
        n = fence_len(line)
        if fence:
            if n >= fence and not line.strip().strip("`"):
                fence = 0
        elif n:
            fence = n
        elif line.startswith("### "):
            if name is not None:
                out.append((name, start, pos, text[body_from:pos]))
            name, start, body_from = line[4:].strip(), pos, pos + len(line) + 1
        pos += len(line) + 1
    if name is not None:
        out.append((name, start, len(text), text[body_from:]))
    return out


def parse_body(body: str) -> dict:
    """이슈 양식(`### 칸이름` 아래 값)에서 칸을 읽는다. 값이 `_No response_` 거나 없으면 빈 글."""
    found = {n: v for n, _, _, v in sections(str(body or "").replace("\r\n", "\n"))}

    def val(key):
        text = found.get(key, "").strip()
        m = re.fullmatch(r"(`{3,})[^\n]*\n(.*?)\n?\1", text, re.S)
        text = m.group(2) if m else text
        return "" if text.strip() == NO_RESPONSE else text.strip("\n")

    pr = re.search(r"(\d+)", val("관련 PR"))
    stage = val("단계")
    return {"pr": int(pr.group(1)) if pr else None, "stage": stage if stage in STAGES else (stage or ""),
            "symptom": val("증상"), "cause": val("원인"), "solution": val("해결 방법")}


def build_body(pr, stage: str, symptom: str, cause: str, solution: str) -> str:
    def part(text):
        return text.strip() or NO_RESPONSE
    sym = symptom.strip()
    fence = "`" * max(3, max((len(r) for r in re.findall(r"`+", sym)), default=0) + 1)  # 증상 안의 ``` 보다 긴 펜스로 감싼다
    return "\n\n".join(["### 관련 PR", f"#{pr}" if pr else NO_RESPONSE, "### 단계", stage, "### 증상", f"{fence}text\n{sym}\n{fence}",
                        "### 원인", part(cause), "### 해결 방법", part(solution)]) + "\n"


def replace_solution(body: str, solution: str) -> str:
    """본문의 `### 해결 방법` 칸을 바꾼다. 칸이 없으면 끝에 더한다. 다른 칸(증상 안의 ### 줄 포함)은 그대로 둔다."""
    text = str(body or "").replace("\r\n", "\n")
    new = "### 해결 방법\n\n" + solution.strip() + "\n"
    for name, start, end, _ in sections(text):
        if name == "해결 방법":
            return text[:start] + new + text[end:]
    return text.rstrip("\n") + "\n\n" + new


def classify(text: str) -> tuple[str, str]:
    for kind, rx in KIND_RE:
        m = rx.match(text or "")
        if m:
            return kind, text[m.end():].strip()
    return "note", (text or "").strip()


def clean_title(title: str) -> str:
    t = str(title or "").strip()
    return t[len(PREFIX.strip()):].strip() if t.startswith(PREFIX.strip()) else t


def grams(text: str) -> set:
    t = "".join(ch for ch in str(text).lower() if ch.isalnum())
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similar(items: list[dict], text: str, skip=None, limit: int = 3) -> list[dict]:
    mine = grams(text)
    scored = []
    for it in items:
        if skip and (it["repo"], it["number"]) == skip:
            continue
        other = grams(it["title"] + " " + it["symptomLine"])
        if mine and other:
            score = 2 * len(mine & other) / (len(mine) + len(other))
            if score >= 0.3:
                scored.append((score, it))
    scored.sort(key=lambda p: -p[0])
    return [dict(number=i["number"], repo=i["repo"], project=i["project"], title=i["title"], solved=i["solved"], author=i["author"],
                 createdAt=i["createdAt"]) for _, i in scored[:limit]]


def parse_time(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def why(rc: int, out: str, what: str = "gh 로 읽지 못했어") -> str:
    low = (out or "").lower()
    if rc == gitstate.GIT_UNAVAILABLE and not low:
        return "gh(GitHub CLI)를 실행하지 못했어(없거나 시간 초과)"
    if any(k in low for k in LOGIN_WORDS):
        return "GitHub 로그인이 필요해"
    return what + (" · " + gitstate.summarize_error(out)[-120:] if (out or "").strip() else "")


def _json(out):
    try:
        return json.loads(out)
    except (ValueError, TypeError):
        return None


def summarize_issue(slug: str, root: str, issue: dict, pr_titles: dict) -> dict:
    parsed = parse_body(issue.get("body"))
    kinds = Counter(classify(c.get("body"))[0] for c in issue.get("comments") or [] if isinstance(c, dict))
    pr = parsed["pr"]
    return {"repo": slug, "project": slug.split("/")[-1], "root": root, "number": issue.get("number"),
            "title": clean_title(issue.get("title")), "solved": str(issue.get("state")).upper() == "CLOSED",
            "author": (issue.get("author") or {}).get("login", ""), "createdAt": issue.get("createdAt", ""), "url": issue.get("url", ""),
            "stage": parsed["stage"], "pr": pr, "prTitle": pr_titles.get(pr, "") if pr else "", "tries": kinds["try"],
            "candidates": kinds["candidate"], "solvedNotes": kinds["solved"], "symptomLine": (parsed["symptom"].splitlines() or [""])[0][:120],
            "_text": "\n".join([clean_title(issue.get("title")), parsed["symptom"], parsed["cause"], parsed["solution"]]).lower()}


# ---- gh 읽기·쓰기 ----
def read_repo(app, root: str) -> dict:
    rc, out = app.check_run(["gh", "repo", "view", "--json", "nameWithOwner"], root)
    data = _json(out) if rc == 0 else None
    slug = data.get("nameWithOwner") if isinstance(data, dict) else None
    if slug and SLUG.fullmatch(slug):
        return {"state": "yes", "result": {"ok": True, "slug": slug, "at": app.clock()}}
    if rc != 0 and any(k in (out or "").lower() for k in NOT_GITHUB):
        return {"state": "yes", "result": {"ok": True, "slug": None, "at": app.clock()}}  # GitHub 저장소가 아닌 폴더는 기록 대상이 아니다
    return {"state": "yes", "result": {"ok": False, "reason": why(rc, out, "저장소 주소를 읽지 못했어"), "at": app.clock()}}


def read_issues(app, slug: str, root: str) -> dict:
    rc, out = app.check_run(["gh", "issue", "list", "-R", slug, "--label", LABEL, "--state", "all", "--limit", str(LIST_LIMIT), "--json",
                             "number,title,state,author,createdAt,url,body,comments"], root)
    data = _json(out) if rc == 0 else None
    if not isinstance(data, list):
        return {"state": "yes", "result": {"ok": False, "reason": why(rc, out), "at": app.clock()}}
    pr_titles = {}
    if any(parse_body(i.get("body"))["pr"] for i in data if isinstance(i, dict)):  # PR 이름은 있으면 좋은 정도라 못 읽어도 목록은 그대로
        rc2, out2 = app.check_run(["gh", "pr", "list", "-R", slug, "--state", "all", "--limit", "100", "--json", "number,title"], root)
        prs = _json(out2) if rc2 == 0 else None
        pr_titles = {p["number"]: p.get("title", "") for p in prs if isinstance(p, dict) and "number" in p} if isinstance(prs, list) else {}
    return {"state": "yes", "result": {"ok": True, "at": app.clock(), "truncated": len(data) >= LIST_LIMIT,
                                                 "items": [summarize_issue(slug, root, i, pr_titles) for i in data if isinstance(i, dict)]}}


def key_of(kind: str, arg: str):
    return ("trouble-" + kind, os.path.normcase(arg))


def origin_of(app, root: str) -> str:
    """같은 저장소의 worktree 들은 origin 주소가 같다. 그걸로 묶어 gh 를 폴더마다 부르지 않는다(주소를 못 읽으면 폴더 자신)."""
    def read():
        rc, out = app.run(["git", "config", "--get", "remote.origin.url"], root)
        url = out.strip().lower() if rc == 0 else ""
        return {"state": "yes", "result": re.sub(r"\.git$", "", url) or os.path.normcase(root)}
    return app.cached(key_of("origin", root), read, wait=True).get("result") or os.path.normcase(root)


def fresh(app, key, fn, wait: bool):
    """app.cached 인데, 못 읽은 결과는 FAIL_TTL 이 지나면 60초를 기다리지 않고 다시 읽는다."""
    got = app.cached(key, fn, wait=wait)
    res = got.get("result")
    if res is not None and not res["ok"] and not got.get("loading") and app.clock() - res.get("at", 0) > FAIL_TTL:
        with app.lock:
            app.cache.pop(key, None)
        got = app.cached(key, fn, wait=wait)
    return got


def collect(app, wait: bool = False, refresh: bool = False) -> dict:
    """콘솔이 아는 폴더들의 저장소와 기록. {"loading", "projects": [{slug,name,root,ok,reason,truncated}], "items": [...]}"""
    roots, seen_origin = [], set()
    for r in app.known_roots():  # 같은 폴더·같은 저장소의 다른 worktree 는 한 번만
        o = origin_of(app, r)
        if o not in seen_origin:
            seen_origin.add(o)
            roots.append(r)
    if refresh:
        with app.lock:
            for k in [k for k in app.cache if isinstance(k, tuple) and k and str(k[0]).startswith("trouble-") and k[0] != "trouble-origin"]:
                app.cache.pop(k, None)
    loading, projects, seen, items = False, [], {}, []
    for root in roots:
        got = fresh(app, key_of("repo", root), lambda r=root: read_repo(app, r), wait)
        res = got.get("result")
        if res is None:
            loading = True
            continue
        if got.get("loading"):
            loading = True
        if not res["ok"]:
            projects.append({"slug": None, "name": os.path.basename(root.rstrip("/\\")), "root": root, "ok": False, "reason": res["reason"]})
        elif res["slug"] and res["slug"] not in seen:
            seen[res["slug"]] = root
    for slug, root in seen.items():
        got = fresh(app, key_of("list", slug), lambda s=slug, r=root: read_issues(app, s, r), wait)
        res = got.get("result")
        if got.get("loading"):
            loading = True
        if res is None:
            continue
        if res["ok"]:
            projects.append({"slug": slug, "name": slug.split("/")[-1], "root": root, "ok": True, "reason": "", "count": len(res["items"]),
                             "truncated": res.get("truncated", False)})
            items.extend(res["items"])
        else:
            projects.append({"slug": slug, "name": slug.split("/")[-1], "root": root, "ok": False, "reason": res["reason"]})
    items.sort(key=lambda i: i["createdAt"], reverse=True)
    return {"loading": loading, "roots": len(roots), "projects": projects, "items": items}


def repo_root(app, slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise HttpError(400, "repo 가 올바르지 않습니다.")
    for p in collect(app, wait=True)["projects"]:
        if p["slug"] == slug:
            return p["root"]
    raise HttpError(403, "콘솔이 아는 프로젝트의 저장소가 아닙니다.")


def public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_") and k not in ("root", "symptomLine")} | {"symptom": item["symptomLine"]}


# ---- API (server.ROUTES 가 부른다) ----
def a_list(app, g, q, b):
    def one(name, default=""):
        return (q.get(name) or [default])[0].strip()
    data = collect(app, wait=False, refresh=one("refresh") == "1")
    items = data["items"]
    now = datetime.fromtimestamp(app.clock(), tz=timezone.utc).astimezone()
    month = sum(1 for i in items if (t := parse_time(i["createdAt"])) and now and (t.year, t.month) == (now.year, now.month))
    stages = Counter(i["stage"] for i in items if i["stage"])
    top = max(STAGES + [s for s in stages if s not in STAGES], key=lambda s: (stages[s], -STAGES.index(s) if s in STAGES else -99)) if stages else ""
    status, stage, text, project, author = one("status", "all"), one("stage"), one("q").lower(), one("project"), one("author")
    shown = [i for i in items if (status == "all" or (status == "open") != i["solved"])
             and (not stage or i["stage"] == stage) and (not project or i["repo"] == project) and (not author or i["author"] == author)
             and (not text or text in i["_text"] or text in i["author"].lower() or text == str(i["pr"] or ""))]
    limit = min(max(int(one("limit", "50") or 50), 1), 200) if one("limit", "50").isdigit() else 50
    return 200, {"loading": data["loading"], "roots": data["roots"], "projects": data["projects"],
                 "authors": sorted({i["author"] for i in items if i["author"]}),
                 "stats": {"total": len(items), "month": month, "open": sum(1 for i in items if not i["solved"]),
                           "solved": sum(1 for i in items if i["solved"]), "topStage": top,
                           "truncated": [p["name"] for p in data["projects"] if p.get("truncated")], "limit": LIST_LIMIT},
                 "matched": len(shown), "items": [public(i) for i in shown[:limit]]}


def view_issue(app, slug: str, root: str, number: int) -> dict:
    rc, out = app.check_run(["gh", "issue", "view", str(number), "-R", slug, "--json",
                             "number,title,state,author,createdAt,url,body,comments,labels"], root)
    data = _json(out) if rc == 0 else None
    if not isinstance(data, dict):
        if rc != 0 and "could not resolve" in (out or "").lower():
            raise HttpError(404, "이 기록을 찾지 못했어.")
        raise HttpError(502, "확인 못 함 · " + why(rc, out))
    if LABEL not in [l.get("name") for l in data.get("labels") or [] if isinstance(l, dict)]:
        raise HttpError(404, "문제·해결 기록 이슈가 아니야.")
    return data


def pr_info(app, slug: str, root: str, number: int) -> dict:
    rc, out = app.check_run(["gh", "pr", "view", str(number), "-R", slug, "--json", "number,title,state,url,statusCheckRollup,isDraft"], root)
    data = _json(out) if rc == 0 else None
    if isinstance(data, dict):
        state, checks = str(data.get("state") or "").upper(), gitstate.summarize_checks(data.get("statusCheckRollup"))
        label = ("합쳐짐" if state == "MERGED" else "닫힘" if state == "CLOSED" else "고쳐야 함" if checks == "fail"
                 else "검사 중" if checks == "pending" else "열려 있음")
        failed = sum(1 for c in data.get("statusCheckRollup") or [] if isinstance(c, dict)
                     and str(c.get("conclusion") or c.get("state") or "").upper() in gitstate.FAILED_CONCLUSIONS)
        return {"state": "ok", "number": number, "title": data.get("title", ""), "url": data.get("url", ""), "label": label,
                "prState": state, "checks": checks, "failed": failed}
    low = (out or "").lower()
    if rc != 0 and ("could not resolve" in low or "no pull requests found" in low):
        return {"state": "missing", "number": number, "reason": f"PR #{number} 를 이 저장소에서 찾지 못했어"}
    return {"state": "unknown", "number": number, "reason": why(rc, out, f"PR #{number} 를 읽지 못했어")}


def int_arg(q, name="number") -> int:
    v = (q.get(name) or [""])[0]
    if not v.isdigit():
        raise HttpError(400, f"{name} 가 필요합니다.")
    return int(v)


def a_item(app, g, q, b):
    slug = (q.get("repo") or [""])[0]
    number = int_arg(q)
    root = repo_root(app, slug)
    data = view_issue(app, slug, root, number)
    parsed = parse_body(data.get("body"))
    history = [{"id": "open", "kind": "open", "author": (data.get("author") or {}).get("login", ""), "createdAt": data.get("createdAt", ""),
                "text": "문제를 등록했어"}]
    for c in data.get("comments") or []:
        if isinstance(c, dict):
            kind, text = classify(c.get("body"))
            history.append({"id": c.get("id", ""), "kind": kind, "author": (c.get("author") or {}).get("login", ""),
                            "createdAt": c.get("createdAt", ""), "text": text})
    pr = pr_info(app, slug, root, parsed["pr"]) if parsed["pr"] else None
    got = collect(app, wait=True)
    listed = got["items"]
    similar_ok = any(p["slug"] == slug and p["ok"] for p in got["projects"])  # 목록을 못 읽었으면 "없음" 이 아니라 확인 못 함
    me = next((i for i in listed if i["repo"] == slug and i["number"] == number), None)
    sim = similar(listed, clean_title(data.get("title")) + " " + (parsed["symptom"].splitlines() or [""])[0], skip=(slug, number))
    return 200, {"repo": slug, "project": slug.split("/")[-1], "number": number, "title": clean_title(data.get("title")),
                 "solved": str(data.get("state")).upper() == "CLOSED", "url": data.get("url", ""), "author": history[0]["author"],
                 "createdAt": data.get("createdAt", ""), "stage": parsed["stage"], "prNumber": parsed["pr"],
                 "prTitle": (me or {}).get("prTitle") or (pr or {}).get("title", ""), "symptom": parsed["symptom"], "cause": parsed["cause"],
                 "solution": parsed["solution"], "history": history, "pr": pr, "similar": sim, "similarOk": similar_ok}


def a_pr(app, g, q, b):
    slug = (q.get("repo") or [""])[0]
    return 200, pr_info(app, slug, repo_root(app, slug), int_arg(q))


def a_similar(app, g, q, b):
    slug = (q.get("repo") or [""])[0]
    text = (q.get("q") or [""])[0][:500]
    got = collect(app, wait=True)
    ok = any(p["ok"] and (not slug or p["slug"] == slug) for p in got["projects"])
    return 200, {"ok": ok, "items": similar([i for i in got["items"] if not slug or i["repo"] == slug], text)}


def a_check(app, g, q, b):
    fields = b.get("fields")
    if not isinstance(fields, dict):
        raise HttpError(400, "fields 가 필요합니다.")
    return 200, {"hits": scan_secrets({str(k): v for k, v in fields.items() if isinstance(v, str)})}


def text_arg(b: dict, name: str, required: bool = False, limit: int = FIELD_MAX) -> str:
    v = b.get(name, "")
    if not isinstance(v, str):
        raise HttpError(400, f"{name} 는 글이어야 합니다.")
    v = v.replace("\r\n", "\n").strip()
    if required and not v:
        raise HttpError(400, f"{name} 가 비었습니다.")
    if len(v) > limit:
        raise HttpError(413, f"{name} 가 너무 깁니다.")
    return v


def refuse_secrets(fields: dict) -> None:
    hits = scan_secrets(fields)
    if hits:
        raise HttpError(422, "비밀번호·키처럼 보이는 글이 있어 올리지 않았어. 지우고 다시 올려 줘. (" + ", ".join(
            f"{h['field']} {h['line']}번째 줄 {h['label']}" for h in hits[:3]) + ")")


def invalidate(app, slug: str) -> None:
    with app.lock:
        app.cache.pop(key_of("list", slug), None)
        app.last.pop(key_of("list", slug), None)


UNSURE = "올렸는지 확인 못 함 — gh 가 제때 답하지 않았어. 목록을 새로고침해서 확인해 줘."


def gh_write(app, args: list[str], root: str, what: str, slug: str = "", create: bool = False) -> str:
    """쓰기. gh 가 실행 불능·시간 초과(127, 출력 없음)면 "못 했다" 가 아니라 결과를 모른다고 알린다(504)."""
    rc, out = app.check_run(args, root)
    if rc == gitstate.GIT_UNAVAILABLE and not (out or "").strip():
        if slug:
            invalidate(app, slug)
        raise HttpError(504, UNSURE + (" 같은 제목의 기록이 방금 생겼는지 목록에서 먼저 보고, 없을 때만 다시 눌러 줘." if create else ""))
    if rc != 0:
        raise HttpError(502, f"{what} 못 했어 · " + why(rc, out, "gh 가 실패했어"))
    return out


def has_label(app, slug: str, root: str) -> None:
    rc, out = app.check_run(["gh", "label", "list", "-R", slug, "--search", "trouble", "--json", "name", "--limit", "100"], root)
    data = _json(out) if rc == 0 else None
    if not isinstance(data, list):
        raise HttpError(502, "확인 못 함 · 라벨을 읽지 못해서 올리지 않았어 · " + why(rc, out))
    if LABEL not in [l.get("name") for l in data if isinstance(l, dict)]:
        raise HttpError(409, f"{slug} 에 {LABEL} 라벨이 없어 올리지 않았어. 터미널에서 `gh label create {LABEL} -R {slug}` 로 만든 뒤 다시 눌러 줘.")


def a_create(app, g, q, b):
    slug = text_arg(b, "repo", True, 200)
    root = repo_root(app, slug)
    title = clean_title(text_arg(b, "title", True, TITLE_MAX))
    stage = text_arg(b, "stage", True, 20)
    if stage not in STAGES:
        raise HttpError(400, "단계가 올바르지 않습니다.")
    pr_raw = text_arg(b, "pr", False, 20).lstrip("#")
    if pr_raw and not pr_raw.isdigit():
        raise HttpError(400, "PR 번호는 숫자여야 합니다.")
    symptom, cause, solution = text_arg(b, "symptom", True), text_arg(b, "cause"), text_arg(b, "solution")
    solved = b.get("solved") is True
    if solved and not solution:
        raise HttpError(400, "해결됐다면 해결 방법을 적어 주세요.")
    refuse_secrets({"title": title, "symptom": symptom, "cause": cause, "solution": solution})
    has_label(app, slug, root)
    body = build_body(int(pr_raw) if pr_raw else None, stage, symptom, cause, solved and solution or "")
    out = gh_write(app, ["gh", "issue", "create", "-R", slug, "--title", PREFIX + title, "--body", body, "--label", LABEL], root, "기록을 올리지", slug, create=True)
    m = re.search(r"/issues/(\d+)", out)
    invalidate(app, slug)
    if not m:
        raise HttpError(502, "올렸는지 확인 못 함 · gh 가 이슈 주소를 알려 주지 않았어. GitHub 에서 확인해 줘.")
    number, warnings = int(m.group(1)), []
    if solution:
        try:
            gh_write(app, ["gh", "issue", "comment", str(number), "-R", slug, "--body", KIND_MARK["solved" if solved else "candidate"] + " " + solution],
                     root, "이력 댓글을 더하지", slug)
            if solved:
                gh_write(app, ["gh", "issue", "close", str(number), "-R", slug], root, "기록을 닫지", slug)
        except HttpError as e:
            warnings.append("기록은 올렸는데 " + e.message)
        invalidate(app, slug)
    return 200, {"ok": True, "repo": slug, "number": number, "url": out.strip().splitlines()[-1], "warnings": warnings}


def resolve(app, slug: str, root: str, number: int, data: dict, text: str) -> list[str]:
    """해결: 본문 해결 방법 갱신 → 댓글 → 닫기. 앞 단계가 실패하면 멈추고, 실패한 곳을 알린다."""
    gh_write(app, ["gh", "issue", "edit", str(number), "-R", slug, "--body", replace_solution(data.get("body"), text)], root, "본문 해결 방법을 고치지", slug)
    warnings = []
    try:
        gh_write(app, ["gh", "issue", "comment", str(number), "-R", slug, "--body", KIND_MARK["solved"] + " " + text], root, "이력 댓글을 더하지", slug)
        if str(data.get("state")).upper() != "CLOSED":
            gh_write(app, ["gh", "issue", "close", str(number), "-R", slug], root, "기록을 닫지", slug)
    except HttpError as e:
        warnings.append("본문은 고쳤는데 " + e.message)
    invalidate(app, slug)
    return warnings


def a_comment(app, g, q, b):
    slug = text_arg(b, "repo", True, 200)
    root = repo_root(app, slug)
    number = b.get("number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise HttpError(400, "number 가 필요합니다.")
    kind = b.get("kind")
    if kind not in KIND_MARK:
        raise HttpError(400, "kind 는 try / candidate / solved 중 하나여야 합니다.")
    text = text_arg(b, "text", True)
    refuse_secrets({"text": text})
    data = view_issue(app, slug, root, number)
    if kind == "solved":
        return 200, {"ok": True, "warnings": resolve(app, slug, root, number, data, text)}
    gh_write(app, ["gh", "issue", "comment", str(number), "-R", slug, "--body", KIND_MARK[kind] + " " + text], root, "이력 댓글을 더하지", slug)
    invalidate(app, slug)
    return 200, {"ok": True, "warnings": []}


def a_resolve(app, g, q, b):
    """"이걸로 해결": 해결 후보 댓글 하나의 내용을 해결 방법으로 삼는다."""
    slug = text_arg(b, "repo", True, 200)
    root = repo_root(app, slug)
    number, cid = b.get("number"), b.get("commentId")
    if not isinstance(number, int) or isinstance(number, bool) or not isinstance(cid, str) or not cid:
        raise HttpError(400, "number 와 commentId 가 필요합니다.")
    data = view_issue(app, slug, root, number)
    for c in data.get("comments") or []:
        if isinstance(c, dict) and c.get("id") == cid:
            kind, text = classify(c.get("body"))
            if kind != "candidate" or not text:
                raise HttpError(400, "해결 후보 댓글이 아닙니다.")
            return 200, {"ok": True, "warnings": resolve(app, slug, root, number, data, text)}
    raise HttpError(404, "그 댓글을 찾지 못했어.")


def drafts(app) -> dict:
    with app.__dict__.setdefault("trouble_lock", threading.Lock()):
        return app.__dict__.setdefault("trouble_drafts", {})


def a_draft_put(app, g, q, b):
    """AI 초안(세션 화면에서 '기록하기' 가 채워 둔다 #734). 메모리에만 두고 최근 DRAFT_MAX 개만 남긴다."""
    fields = {k: text_arg(b, k) for k in ("repo", "pr", "stage", "title", "symptom", "cause", "solution")}
    src = b.get("source") if isinstance(b.get("source"), dict) else {}
    store = drafts(app)
    did = "d-" + uuid.uuid4().hex[:12]
    with app.__dict__.setdefault("trouble_lock", threading.Lock()):
        store[did] = dict(fields, solved=b.get("solved") is True, source={"title": str(src.get("title") or "")[:100]})
        for old in list(store)[:-DRAFT_MAX]:
            store.pop(old)
    return 200, {"id": did}


def a_draft_get(app, g, q, b):
    d = drafts(app).get((q.get("id") or [""])[0])
    if d is None:
        raise HttpError(404, "없는 초안입니다.")
    return 200, d
