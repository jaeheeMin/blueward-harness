"""콘솔 시험용 가짜 `claude`. 실제 claude 를 부르지 않고 stream-json 입출력과 훅 호출만 흉내 낸다(#558).

stdin 의 user 메시지 내용에 따라 움직인다.
  ask      /hooks/question 에 AskUserQuestion 을 보내고 답이 올 때까지 기다린다
  perm     /hooks/permission 에 Bash 승인을 보내고 답이 올 때까지 기다린다
  garbage  stdout 에 깨진 줄을 섞는다
  그 밖    echo 로 답한다
각 턴이 끝날 때 /hooks/stop 도 부른다(진짜 Stop 훅처럼).
"""
import http.client
import json
import os
import sys
import uuid

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
out({"type": "system", "subtype": "init", "session_id": sid, "permissionMode": "default", "args": args})
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("type") == "control_request":
        out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"]}})
        continue
    text = msg["message"]["content"]
    hook("event", {"hook_event_name": "UserPromptSubmit", "prompt": text})
    reply = "echo: " + text
    if text.startswith("ask"):
        q = [{"question": "색은?", "header": "색", "multiSelect": False, "options": [{"label": "Red", "description": ""}]}]
        r = hook("question", {"tool_name": "AskUserQuestion", "tool_input": {"questions": q}})
        reply = "answer: " + json.dumps(r["hookSpecificOutput"]["updatedInput"]["answers"], ensure_ascii=False) if r else "answer: none"
    elif text.startswith("perm"):
        r = hook("permission", {"tool_name": "Bash", "tool_input": {"command": "touch x"}})
        reply = "decision: " + (r["hookSpecificOutput"]["decision"]["behavior"] if r else "none")
    elif text.startswith("garbage"):
        out("{not json")
        out("")
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
    hook("stop", {"hook_event_name": "Stop", "last_assistant_message": reply})
    out({"type": "result", "subtype": "success", "session_id": sid, "result": reply, "is_error": False})
