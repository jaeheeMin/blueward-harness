"""훅 요청 하나를 보내고 답이 올 때까지 연결을 붙든다(질문·승인 카드가 화면에 남도록). 서버가 꺼지면 끝난다.
사용법: python hold_hook.py <question|permission> <본문.json>"""
import http.client
import json
import os
import sys

name, path = sys.argv[1], sys.argv[2]
body = open(path, encoding="utf-8").read().encode("utf-8")
port = int(os.environ.get("CONSOLE_CHECK_PORT", "4881"))
c = http.client.HTTPConnection("127.0.0.1", port, timeout=86400)
c.request("POST", f"/hooks/{name}", body=body, headers={"Content-Type": "application/json", "Host": f"127.0.0.1:{port}"})
try:
    r = c.getresponse()
    print(r.status, r.read()[:300])
except OSError as e:
    print("끊김", e)
