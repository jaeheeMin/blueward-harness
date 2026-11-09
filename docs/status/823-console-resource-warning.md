# #823 웹 콘솔 세션 파이프를 닫지 않는 ResourceWarning

## 재현
`uv run pytest -q -p no:cacheprovider -W always -rw` 로
`test_managed_stop_reservation_applies`, `test_reload_fails_with_502_when_neither_way_works` 를 돌리면
`ResourceWarning: unclosed file <_io.FileIO ... mode='rb'>` 와 `unclosed file <_io.TextIOWrapper ...>` 가 뜬다.

## 원인
`python -X tracemalloc=20` 으로 연 자리를 찾았다. `plugins/harness/console/managed.py` 의 `Manager._launch`
(`self.popen(..., stdin=PIPE, stdout=PIPE)`)가 만든 자식의 stdout 파이프(`subprocess.py` 의 `io.open(c2pread, 'rb')` 와
`io.TextIOWrapper`)였다. 읽기 스레드 `Proc._read` 는 EOF 까지 읽고 `on_exit` 만 부르고 파이프를 닫지 않았다.
시험 fixture 가 아니라 실제 콘솔 코드의 누수라서, 오래 켜 둔 콘솔에서 세션이 끝날 때마다 핸들이 쌓였다.

## 고친 것
`Proc._read` 끝에서 stdout·stdin 을 닫는다. 닫기가 실패하면 `manager.log` 로 남긴다(삼키지 않음).
닫기는 `write()` 와 같은 `write_lock` 안에서 한다(닫는 중에 세션으로 글을 쓰는 일과 겹치지 않게, 닫힌 뒤 `write()` 는 False).
시험의 가짜 프로세스는 stdout 이 줄 목록(`close` 없음)이라 `close` 가 있을 때만 부른다 — 처음 판은 여기서 읽기 스레드가
AttributeError 로 죽어 `PytestUnhandledThreadExceptionWarning` 이 났다(메인이 전체 시험에서 찾음).

## 확인
- `-W error::ResourceWarning` 으로 두 시험 통과(2 passed).
- `-k "managed or reload or stop"` 44 passed. 경고 1건은 `test_open_starts_detached_server_and_stop` 의
  `subprocess ... is still running` 으로 이 건과 다른 원인(떼어 띄운 콘솔 서버) — #836 으로 남겼다.
- `-W always -rw checker/tests/test_web_console.py` 전체: 남은 경고는 #836 의 1건뿐(아래 PR 본문에 결과).
