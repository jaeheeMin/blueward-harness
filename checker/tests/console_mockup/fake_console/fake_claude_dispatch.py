"""가짜 claude 하나로 세 가지를 맡는다.
- `auth status --json`: 로그인됨
- `--input-format stream-json`(콘솔 세션): checker/tests/fake_claude.py 를 그대로 실행
- 그 밖(`-p` 분석): analysis.json 의 structured_output 을 낸다"""
import json
import os
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FAKE = HERE.parents[1] / "fake_claude.py"
RUN = Path(os.environ["CONSOLE_CHECK_RUN"])
args = sys.argv[1:]

if args[:1] == ["auth"]:
    print(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
elif "--input-format" in args:
    sys.argv = [str(FAKE)] + args
    runpy.run_path(str(FAKE), run_name="__main__")
else:
    sys.stdin.buffer.read()
    try:
        data = json.loads((RUN / "analysis.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"understood": "analysis.json 이 없어요", "candidates": [], "extraQuestions": []}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"type": "result", "is_error": False, "structured_output": data}, ensure_ascii=False))
