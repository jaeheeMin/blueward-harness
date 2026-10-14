# #314 작업 중간에 플러그인이 옛 판이면 알려 주는 훅 (2026-10-14)

열려 있는 세션은 처음 받은 판을 계속 쓰고, Claude Code 자동 업데이트 알림은 첫 메시지 뒤 한 번뿐이라 그 뒤에 나온 판은 모른다. `UserPromptSubmit` 훅 `plugins/harness/hooks/update_notice.py` 를 더했다.

- 현재 판은 `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`, 최신 판은 `git ls-remote --tags <원격> 'v*'`(5초 제한)의 가장 큰 `vX.Y.Z`(`^{}` 제외, 숫자 비교). 결과는 실패(None) 포함해 `${CLAUDE_PLUGIN_DATA}/update-notice.json` 에 10분 캐시한다. `CLAUDE_PLUGIN_DATA` 가 없으면 임시 폴더 `harness-update-notice/` 를 쓴다.
- 뒤처졌으면 `additionalContext` 로 Claude 에게 "첫 줄에 한 번 알려라" 고 시킨다. 사용자 화면에 직접 띄우는 방법은 이 이벤트에서 문서로 확인되지 않았다. 갱신은 사용자가 하고 Claude 는 대신 실행하지 않는다.
- 안내는 `${CLAUDE_PLUGIN_ROOT}` 의 부모(`.../harness/`)에 최신 판 폴더가 있으면 `/reload-plugins`, 없으면 `claude plugin marketplace update blueward-harness` + `claude plugin update harness@blueward-harness --scope project` 후 `/reload-plugins`.
- 같은 세션(`session_id`)·같은 최신 판은 한 번만(상태 파일에 세션별로 최근 20개 기억). 더 새 판이 나오면 다시 알린다.
- 실패(네트워크·git 없음·파싱·권한)는 전부 출력 없이 exit 0. hooks.json 은 timeout 10 과 `|| exit 0`(uv 없음 포함)로 프롬프트를 막지 않는다. 검사가 아니라 안내라 "검사 불능" 표시도 하지 않는다.
- 훅은 `"async": true` 로 등록해 프롬프트를 늦추지 않는다. async 라 **알림은 다음 메시지 때 나온다**(공식 문서 hooks "Run hooks in the background": 백그라운드 훅이 끝난 뒤 `additionalContext` 를 다음 대화 턴에 Claude 에게 전달, 세션이 놀고 있으면 다음 사용자 입력까지 대기). UserPromptSubmit 에서의 async 지원은 문서에 직접 적혀 있지 않고 타임아웃 설명에서 읽히는 정도다.
- 원격 조회가 반쯤 죽은 네트워크에서 Windows 21.9초 걸린 문제: 조회 전에 `checked_at` 을 먼저 저장하고, `git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=4 ls-remote` 로 git 이 스스로 끝나게 하며, Popen + communicate(timeout) 초과 시 프로세스 트리를 죽이고(Windows `taskkill /T /F`, 그 외 프로세스 그룹 SIGKILL) 파이프를 다시 기다리지 않는다.
- 이미 받은 경우 안내에 "`/reload-plugins` 뒤에도 판이 그대로면 업데이트 명령" 을 덧붙였다.
- 끄기: 플러그인 저장소 자신(cwd 에서 위로 올라가 git 꼭대기까지 `.claude-plugin/marketplace.json` 이 있으면)과 `HARNESS_NO_UPDATE_NOTICE=1`.

판단: 원격 URL 은 `engine_spec.REPO_URL` 이 `git+https://…` 형식이라 그대로 못 써서 훅 안에 상수로 뒀다(import 하지 않아 훅이 독립). 앞섬(개발 중 로컬 판이 원격보다 높음)은 말하지 않는다.

테스트: `checker/tests/test_update_notice.py`(뒤처짐 받음/안 받음, 최신, 앞섬, 원격 실패, 캐시, 세션별 1회, 저장소·환경변수 끄기, git 없는 PATH 에서 exit 0), `test_plugin_layout.py` 훅 목록·UserPromptSubmit 등록 갱신.

길잡이: "처음 준비하기" 의 두 박스에 한 줄씩, 레일 harness 0.10.68. Plugin version 0.10.67 → 0.10.68. 병합 뒤 아티팩트에 다시 올려야 한다.
