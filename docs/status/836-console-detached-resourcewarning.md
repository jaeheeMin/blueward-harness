# #836 웹 콘솔 시험에서 떼어 띄운 콘솔 서버의 ResourceWarning

## 원인 (2026-11-13 확인)
`-X tracemalloc=20 -W always -rw` 로 `test_open_starts_detached_server_and_stop` 만 돌려 자리를 확정했다.
경고 `subprocess NNNN is still running` 의 Popen 은 `open.py` `ensure_server` → `start_server` → `launch_server` 에서 만들어진다.
`start_server` 가 떼어 띄운 서버의 Popen 을 받자마자 버려서, 서버가 살아 있는 채로 Popen 이 정리되며 경고가 났다.
시험이 아니라 open.py 쪽이다.

## 고친 것 (0.10.276)
- `open.py`: 띄운 서버의 Popen 을 모듈 목록 `_launched` 에 들고 있다. 같은 프로세스에서 `stop_server` 로 끄고 포트가 풀리면
  `reap_launched(STOP_REAP_WAIT=5초)` 로 끝난 프로세스를 거둔다(wait). 시간 안에 안 끝난 것은 그대로 둔다.
  떼어 띄운 서버를 기다리지 않는 동작(`/harness:open` 이 바로 끝남)은 그대로다.
- pid 로 짝짓지 않는 이유: Windows venv 의 `pythonw.exe` 는 실제 서버를 자식으로 띄우는 런처라 Popen pid 와 `server.pid` 가 다를 수 있다.
  런처는 서버가 끝나면 함께 끝나므로 wait 로 거둘 수 있다.
- 띄우기에 실패하면(포트를 다른 프로그램이 씀·서버가 원인을 남김·시간 초과) `reap_launched(FAIL_REAP_WAIT=2초)` 로 끝난 서버를 그 자리에서 거둔다.
  처음 판은 끌 때만 거둬서, 전체 시험에서 앞선 `test_open_reports_port_bind_failure_reason` 이 남긴 실패한 서버의 Popen 이 목록에 쌓여 있었다.
- 경고 끄는 설정(filterwarnings)은 쓰지 않았다.

## 시험
- `test_open_starts_detached_server_and_stop`: `warnings.catch_warnings(record=True)` + `gc.collect()` 로 subprocess ResourceWarning 이 없음과
  `_launched` 가 띄운 뒤 1개·끈 뒤 비었음을 확인한다. 고치기 전 open.py 로는 실패한다.
- `test_open_reports_port_bind_failure_reason`: 못 뜬 서버의 Popen 이 남지 않음을 확인한다.
- 고치기 전: 같은 시험 `-W always -rw` 에 경고 1건. 고친 뒤: 완료 조건 명령
  `uv run pytest -q -W always -rw checker/tests/test_web_console.py` 가 1118 passed·4 skipped, 경고 0건.
- 한 번 `test_api_shutdown_stops_serve_forever` 에서 `PytestUnhandledThreadExceptionWarning`(serve_forever 스레드 예외)이 나왔다가 다시 돌리니 안 났다. ResourceWarning 이 아니고 이번 변경과 무관해 그대로 둔다.
