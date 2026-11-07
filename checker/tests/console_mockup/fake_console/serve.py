"""시험 콘솔 launcher. 저장소의 console 코드를 읽기만 하고, App 에 gh·claude 흉내를 끼워 넣어 띄운다.
- run: git 은 진짜로, gh 는 gh_state.json 을 읽어 흉내 낸다.
- claude_cmd: fake_claude_dispatch.py (분석은 analysis.json, 세션은 checker/tests/fake_claude.py)
- browser_open: 로그인 주소를 auth_url.txt 에 적는다(브라우저를 띄우지 않는다).
환경변수 HARNESS_CONSOLE_PORT·CLAUDE_PLUGIN_DATA·CONSOLE_CHECK_RUN·CONSOLE_CHECK_REPO 를 lib.start_server 가 넣어 준다."""
import json
import os
import signal
import sys
import threading
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
RUN = Path(os.environ["CONSOLE_CHECK_RUN"])
CONSOLE = Path(os.environ["CONSOLE_CHECK_REPO"]) / "plugins/harness/console"
sys.path.insert(0, str(CONSOLE))

import gitstate  # noqa: E402
import server  # noqa: E402

PORT = int(os.environ["HARNESS_CONSOLE_PORT"])
STATE = Path(os.environ["CLAUDE_PLUGIN_DATA"])


def gh_state() -> dict:
    try:
        return json.loads((RUN / "gh_state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"login": "jaeheemin", "prs": []}


def opt(a, name):
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else None


def fake_gh(args, cwd):
    st, a = gh_state(), args[1:]
    if a[:2] == ["api", "user"]:
        return 0, st["login"] + "\n"
    if a[:2] == ["repo", "view"]:
        return 0, "ADMIN\n"
    prs = st["prs"]
    if a[:2] == ["pr", "view"]:
        hit = next((p for p in prs if str(p["number"]) == a[2]), None)
        return (0, json.dumps(hit)) if hit else (1, "no pull requests found")
    if a[:2] == ["pr", "list"]:
        head, state = opt(a, "--head"), opt(a, "--state") or "open"
        out = [p for p in prs if (head is None or p["headRefName"] == head) and (state == "all" or p["state"].lower() == state)]
        return 0, json.dumps(out, ensure_ascii=False)
    return 1, "fake gh: 지원하지 않는 명령"


def fake_run(args, cwd):
    if args and args[0] == "gh":
        return fake_gh(args, cwd)
    return gitstate.run_command(args, cwd, 25.0)


def browser_open(url):
    (RUN / "auth_url.txt").write_text(url, encoding="utf-8")
    return True


def main():
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or CONSOLE.parent)
    app = server.App(PORT, STATE, plugin_root, browser_open=browser_open,
                     claude_cmd=lambda: [sys.executable, "-B", str(HERE / "fake_claude_dispatch.py")],
                     run=fake_run, git_inspect=lambda cwd: gitstate.inspect(cwd, run=fake_run))
    app.remote_latest = lambda: app.version  # 원격(ls-remote)을 부르지 않는다: "최신" 으로 본다
    srv = server.make_server(app)
    STATE.mkdir(parents=True, exist_ok=True)
    (RUN / "serve.pid").write_text(f"{os.getpid()}\n{PORT}\n")

    def stop(*_):
        threading.Thread(target=srv.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        srv.serve_forever()
    finally:
        app.shutdown()
        (RUN / "serve.pid").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
