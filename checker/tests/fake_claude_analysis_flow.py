"""갈래 분류가 든 분석(`claude -p --output-format json`)을 흉내 내는 가짜 실행 파일(#558).
stdin 을 읽어 FAKE_PROMPT_FILE 에 저장하고, 요청 글의 낱말로 분류를 고른다."""
import json
import os
import sys

prompt = sys.stdin.buffer.read().decode("utf-8")  # 부른 쪽이 UTF-8 로 보낸다(Windows 기본 코드 페이지로 읽지 않는다)
if os.environ.get("FAKE_PROMPT_FILE"):
    with open(os.environ["FAKE_PROMPT_FILE"], "w", encoding="utf-8") as fh:
        fh.write(prompt + "\n" + json.dumps(sys.argv[1:], ensure_ascii=False))
request = prompt.split("요청 글:\n", 1)[-1]
if "헷갈" in request:
    flow = {"id": "fix", "reason": "작은 수정 같기도 하다", "confident": False, "alternativeId": "dev"}
elif "엉뚱" in request:
    flow = {"id": "nonexistent", "reason": "목록에 없는 갈래"}
else:
    flow = {"id": "srs", "reason": "요구사항을 바꾸는 일이다", "confident": True}
print(json.dumps({"type": "result", "is_error": False, "structured_output": {
    "understood": "이해함", "candidates": [], "extraQuestions": [], "flow": flow}}))
