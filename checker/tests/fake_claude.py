"""콘솔 시험용 가짜 `claude`. 실제 claude 를 부르지 않고 stream-json 입출력과 훅 호출만 흉내 낸다(#558).

stdin 의 user 메시지 내용에 따라 움직인다.
  ask      /hooks/question 에 AskUserQuestion 을 보내고 답이 올 때까지 기다린다
  perm     /hooks/permission 에 Bash 승인을 보내고 답이 올 때까지 기다린다
  control_request(set_permission_mode)  모드를 바꾸고 success 와 status 를 낸다. 모르는 값은 error
  control_request(reload_plugins)  plugins[{name,path,source,version}]·error_count 로 success. FAKE_NO_RELOAD_CONTROL 이면 error
  /reload-plugins  합성 응답 "Reloaded: 2 plugins · 0 errors". FAKE_NO_RELOAD_MESSAGE 이면 echo(미지원 흉내)
  /harness:handoff  코드 블록이 든 인계 글로 답한다. FAKE_HANDOFF=none 이면 코드 블록 없이, long 이면 4001자 코드 블록으로 답한다
  slow     FAKE_GATE 파일이 생길 때까지(최대 30초) 턴을 끝내지 않는다
  garbage  stdout 에 깨진 줄을 섞는다
  그 밖    echo 로 답한다
각 턴이 끝날 때 /hooks/stop 도 부른다(진짜 Stop 훅처럼).
"""
import http.client
import json
import os
import sys
import time
import uuid

sys.stdin.reconfigure(encoding="utf-8")  # Windows 기본(cp949)이면 한글이 깨진다
sys.stdout.reconfigure(encoding="utf-8")

args = sys.argv[1:]
sid = args[args.index("--resume") + 1] if "--resume" in args else "fake-" + uuid.uuid4().hex[:8]
port = int(os.environ["HARNESS_CONSOLE_PORT"])
cwd = os.getcwd()


def out(obj):
    sys.stdout.write((obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)) + "\n")
    sys.stdout.flush()


def hook(path, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    conn.request("POST", "/hooks/" + path, body=json.dumps(dict(body, session_id=sid, cwd=cwd)),
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return json.loads(raw) if raw else None


out({"type": "system", "subtype": "hook_started", "session_id": sid})
model = args[args.index("--model") + 1] if "--model" in args else "fake-default-model"  # 진짜 init 처럼 실제 모델 이름을 싣는다
mode = args[args.index("--permission-mode") + 1] if "--permission-mode" in args else "default"
plugin_dir = args[args.index("--plugin-dir") + 1] if "--plugin-dir" in args else ""
mcp = json.loads(os.environ["FAKE_MCP"]) if os.environ.get("FAKE_MCP") else None  # [{name,status,error?}]
init = {"type": "system", "subtype": "init", "session_id": sid, "model": model, "permissionMode": mode, "args": args,
        "plugins": [{"name": "harness", "path": plugin_dir, "source": "inline"}]}
if mcp is not None:  # 진짜 init 은 이름·상태·source 만 싣는다(실패 사유는 mcp_status 로만)
    init["mcp_servers"] = [{"name": m["name"], "status": m["status"], "source": "user"} for m in mcp]
out(init)
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("type") == "control_request":
        request = msg.get("request") or {}
        if request.get("subtype") == "set_permission_mode":  # 진짜 claude 처럼 허용 값이면 success·status, 아니면 error 로 답한다
            wanted = request.get("mode")
            if wanted in ("acceptEdits", "auto", "bypassPermissions", "default", "dontAsk", "plan"):
                mode = wanted
                out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"], "response": {"mode": mode}}})
                out({"type": "system", "subtype": "status", "status": None, "permissionMode": mode, "session_id": sid})
            else:
                out({"type": "control_response", "response": {"subtype": "error", "request_id": msg["request_id"],
                                                                "error": "Cannot set permission mode", "error_code": "invalid_mode"}})
            continue
        if request.get("subtype") == "reload_plugins":
            if os.environ.get("FAKE_NO_RELOAD_CONTROL"):
                out({"type": "control_response", "response": {"subtype": "error", "request_id": msg["request_id"], "error": "Unsupported control request"}})
            else:
                out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"], "response": {
                    "commands": [], "agents": [], "plugins": [
                        {"name": "harness", "path": plugin_dir, "source": "inline", "version": "1.2.3"},
                        {"name": "other", "path": "/x", "source": "market", "version": "0.4"}], "error_count": 0}}})
            continue
        if request.get("subtype") == "mcp_status":
            out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"], "response": {
                "mcpServers": [dict(m, config={}, transport="stdio", scope="user", source="user", tools=[]) for m in (mcp or [])]}}})
            continue
        if request.get("subtype") == "mcp_reconnect":
            target = [m for m in (mcp or []) if m["name"] == request.get("serverName")]
            if os.environ.get("FAKE_MCP_RECONNECT_FAIL") or not target:
                out({"type": "control_response", "response": {"subtype": "error", "request_id": msg["request_id"], "error": "Server not found or failed"}})
            else:
                target[0].update(status="connected")
                target[0].pop("error", None)
                out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"], "response": {}}})
            continue
        out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"]}})
        continue
    text = msg["message"]["content"]
    if isinstance(text, list):  # 첨부가 있는 메시지(content 블록 배열). 시험이 받은 블록을 읽을 수 있게 파일에 남긴다
        if os.environ.get("FAKE_CONTENT_LOG"):
            with open(os.environ["FAKE_CONTENT_LOG"], "a", encoding="utf-8") as f:
                f.write(json.dumps(text, ensure_ascii=False) + "\n")
        text = "".join(b.get("text", "") for b in text if b.get("type") == "text") or "첨부만"
    hook("event", {"hook_event_name": "UserPromptSubmit", "prompt": text})
    reply = "echo: " + text
    if text.startswith("ask"):
        q = [{"question": "색은?", "header": "색", "multiSelect": False, "options": [{"label": "Red", "description": ""}]}]
        r = hook("question", {"tool_name": "AskUserQuestion", "tool_input": {"questions": q}})
        reply = "answer: " + json.dumps(r["hookSpecificOutput"]["updatedInput"]["answers"], ensure_ascii=False) if r else "answer: none"
    elif text.startswith("perm"):
        r = hook("permission", {"tool_name": "Bash", "tool_input": {"command": "touch x"}})
        reply = "decision: " + (r["hookSpecificOutput"]["decision"]["behavior"] if r else "none")
    elif text.startswith("/reload-plugins") and not os.environ.get("FAKE_NO_RELOAD_MESSAGE"):
        reply = "Reloaded: 2 plugins · 0 errors"
    elif text.startswith("/harness:handoff"):
        reply = "인계 파일을 저장했습니다."
        if os.environ.get("FAKE_HANDOFF") == "long":
            reply += "\n\n```\n" + "가" * 4001 + "\n```"
        elif os.environ.get("FAKE_HANDOFF") != "none":
            reply += "\n\n새 세션에 붙여 넣을 프롬프트:\n\n```\n앞선 작업: SRS 를 끝냈다. 이어서 Spec 을 만든다.\n```"
    elif text.startswith("slow"):
        gate = os.environ.get("FAKE_GATE", "")
        for _ in range(300):
            if gate and os.path.exists(gate):
                break
            time.sleep(0.1)
    elif text.startswith("garbage"):
        out("{not json")
        out("")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    hook("stop", {"hook_event_name": "Stop", "last_assistant_message": reply})
    out({"type": "result", "subtype": "success", "session_id": sid, "result": reply, "is_error": False})
