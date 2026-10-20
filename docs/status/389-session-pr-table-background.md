# #389 세션 시작 PR 표를 뒤에서 만들고 첫 프롬프트에 끼우기 (2026-10-20)

SessionStart 훅이 `checker.pr_queue --mine` 을 `timeout 20` 으로 불렀다. 새 엔진 판을 처음 받는 세션은 받기·설치만으로 20초를 넘겨 표 없이 "건너뜀" 한 줄만 나왔고, 성공해도 세션 시작이 최대 20초 늦었다. 0.10.95(0.10.94 는 같은 시각에 열린 #392 가 먼저 잡아 한 칸 비켰다).

## 결정

- **엔진은 뒤에서 돌린다.** 조건(fetch 성공, origin 이 github, uvx·gh 있음, 엔진 판 결정)은 전과 같이 세션 시작에서 본다. 결정되면 엔진을 detached 서브셸(`( … ) </dev/null >/dev/null 2>&1 &`)에서 돌리고 바로 넘어간다. 세션 시작 출력은 "내 PR 상태를 뒤에서 확인하는 중" 한 줄이다(없음·문제없음으로 읽히는 말은 쓰지 않는다).
- **결과는 세션별 파일.** `<git-dir>/harness-pr-table.<session_id>`. 첫 줄 `rc=<종료코드>`, 나머지는 엔진 stdout. `.tmp` 로 쓰고 `mv` 로 최종 이름을 붙여 "다 썼다" 를 원자적으로 알린다. session_id 는 훅 stdin JSON 에서 읽고 영문·숫자·`_`·`-` 만 남긴다(없으면 PID). 다른 세션의 파일은 읽지 않는다. 시작 때 같은 폴더의 1일(`-mmin +1440`) 넘은 `harness-pr-table.*` 를 지운다.
- **첫 프롬프트에 끼운다.** `UserPromptSubmit` 에 새 훅 `pr_table_notice.py`(update_notice 와 별개 항목). 최종 파일이 있으면 한 번 내고 지운다. `.tmp` 만 있으면 아직 진행 중이라 아무것도 안 내고 다음 프롬프트에 다시 본다. rc=0·본문 비면 내 PR 없음이라 조용히 지운다. rc=0·본문 있으면 표 + `/harness:prs` 안내. rc=2 면 엔진이 낸 첫 줄 + 다시 확인 안내. 그 밖(124 시간 초과 포함)은 "PR 상태 확인 불능(…)". 어느 쪽도 "문제없음" 으로 뭉개지 않는다(원칙 7).
- **출력 채널.** `update_notice.py` 와 같은 `hookSpecificOutput.additionalContext`. 이 이벤트의 출력은 사용자 화면이 아니라 Claude 컨텍스트로 가므로 "첫머리에 그대로 보여 줘라" 고 시킨다. `async` 는 쓰지 않는다 — update_notice 가 async 인 것은 `git ls-remote`(최대 5초)가 프롬프트를 늦추지 않게 하려는 것이고 그 대가로 안내가 다음 턴에 간다. 이 훅은 파일 하나를 읽을 뿐이라 빠르고, async 면 첫 프롬프트에 표가 안 들어갈 수 있다. 실패는 모두 exit 0.
- **시간 제한.** 기본 300초, `HARNESS_PR_TIMEOUT` 로 바꾼다 — 영원히 안 끝나는 것만 막는다. 시간 초과는 rc=124 로 기록돼 "확인 불능" 으로 나온다. `timeout` 명령이 없으면 한계 없이 돌리지 않고 뒤 실행 없이 "PR 상태 확인 불능(timeout 명령이 없어 시간을 제한할 수 없음)" 을 바로 낸다. 옛 "건너뜀 + 엔진 예열" 은 없앴다: 뒤 실행이 곧 받기·설치라 예열이 필요 없다.
- **session_id 가 없으면** (없거나 허용 글자를 거른 뒤 비면) 첫 프롬프트 훅이 파일을 찾을 방법이 없으므로 PID 로 대신하지 않고, 뒤 실행 없이 "PR 상태 확인 불능(세션 ID 를 받지 못함)" 을 바로 낸다.
- **첫 프롬프트 훅의 순서.** 출력을 먼저 내보내고(flush) 그다음 파일을 지운다. 지우기에 실패하면 다음 프롬프트에 한 번 더 나올 수 있다(표를 잃는 것보다 낫다). 결과 파일을 읽지 못하면 "내 PR 없음" 으로 뭉개지 않고 "PR 상태 확인 불능(결과 파일을 읽지 못함)" 을 내고 삭제를 시도한다. 저장소가 아니면 아무것도 안 낸다. timeout 10초.
- `nohup` 이 있으면 엔진 명령에 붙인다. `setsid` 는 쓰지 않는다(`setsid` 는 프로세스 그룹 리더이면 자식을 기다리지 않고 바로 돌아와 종료코드를 잃는다).

## 바꾼 파일

- `plugins/harness/hooks/session-start-sync.sh`: PR 절을 뒤 실행으로.
- `plugins/harness/hooks/pr_table_notice.py`(새), `hooks/hooks.json`: UserPromptSubmit 항목 추가.
- `plugins/harness/.claude-plugin/plugin.json`: 0.10.95.
- `checker/tests/test_session_pr_block.py`(세션 시작 쪽을 새 동작으로), `test_pr_table_notice.py`(새), `test_plugin_layout.py`(훅 목록).
- `docs/guide/harness-guide.html`: "내 PR 확인하기" 탭.

## 한계

- 엔진이 첫 프롬프트까지 안 끝나면 그 프롬프트에는 표가 없고, 끝난 뒤 다음 프롬프트에 나온다.
- 세션 중에 다른 worktree 로 옮기면 git 폴더가 달라 파일을 못 찾는다(표가 안 보이고, 파일은 하루 뒤 지워진다).
- Windows Git Bash 에서 훅을 직접 돌려(stdin JSON 으로 session_id·cwd 전달) 훅이 7초에 끝나고 6초 뒤 결과 파일이 생기며, 첫 프롬프트 훅이 표를 한 번 내고 지우는 것까지 봤다. Claude Code 의 훅 실행기가 돌릴 때도 같은지는 병합 뒤 다음 판 세션에서 확인한다.

## 확인

`uv run pytest checker/tests/test_session_pr_block.py checker/tests/test_pr_table_notice.py checker/tests/test_plugin_layout.py -q`. 실제로는 새 엔진 판이 캐시에 없는 상태에서 세션을 열어, 시작이 바로 끝나고 첫 프롬프트에 표가 나오는지 본다.
