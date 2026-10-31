"""분석(`claude -p --output-format json`)을 흉내 내는 가짜 실행 파일(#558). stdin 을 읽고 고정 JSON 을 낸다."""
import json
import sys

sys.stdin.read()
print(json.dumps({"type": "result", "is_error": False, "structured_output": {
    "understood": "이해함",
    "candidates": [{"path": "a.md", "reason": "관련"}, {"path": "../secret", "reason": "탈출"}],
    "extraQuestions": [{"question": "범위는?", "options": ["전체", "일부"]}]}}))
