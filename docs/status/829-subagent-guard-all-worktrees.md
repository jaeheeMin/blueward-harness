# 829 서브에이전트 수정 점검을 모든 worktree 로

이슈 #829. #601 의 `subagent_edit_guard.py` 는 세션이 열린 폴더의 작업 트리만 기준·비교해서, 같은 저장소의
다른 worktree 를 python 스크립트로 고쳐도 못 막았다(2026-11-09 #827 작업: 기록 `baseline` 빈 값, `blocks: 0`).
메인 세션은 작업을 나눌 때 worktree 를 따로 만드는 게 기본이라 가드가 거의 늘 비어 있었다.

## 바꾼 것 (`plugins/harness/hooks/subagent_edit_guard.py`)

- `start`: `git worktree list --porcelain` 의 모든 worktree(디렉터리가 사라진 prunable·bare 제외)마다
  `git status` 경로·해시·HEAD 를 찍어 에이전트 기록의 `trees` 에 담는다. 세션 폴더는 항상 들어간다.
- `stop`: 작업 트리마다 지금 상태를 기준과 비교한다. Edit/Write 기록은 `(작업 트리, 경로)` 로 대조한다.
  다른 worktree 의 파일은 막는 사유에 절대 경로로 나온다. HEAD 가 바뀐 작업 트리는 그 트리만 건너뛰고 경고한다
  (예전엔 전체를 건너뛰었다).
- `pre`/`record`: 고친 파일이 속한 작업 트리(`top_of`: 파일 쪽 폴더에서 `rev-parse --show-toplevel`)를 기준으로
  해시·상대 경로를 맞춘다. 행에 작업 트리 키 `r` 를 넣는다. 기록 파일은 세션 폴더의 상태 폴더 한 곳에 모은다.
  `r` 가 없는 옛 행과 `trees` 가 없는 옛 에이전트 기록은 세션 폴더로 읽는다.
- 다른 저장소 처리: 시작 때 기준이 없던 작업 트리(다른 저장소, 시작 뒤 생긴 worktree)를 서브에이전트가 처음
  Edit/Write 하려는 순간(`pre`) 그 트리의 기준을 더한다. 그 뒤 그 저장소 안에서 스크립트로 고친 파일은 잡힌다.
- 확인 못 함(통과로 뭉개지 않음): worktree 목록을 시작·종료 때 못 읽음, 어떤 트리의 기준·현재 상태를 못 읽음,
  시작 뒤 생긴 worktree. 막을 파일이 있으면 막는 사유에, 없으면 `systemMessage` + 메인 모델 주입 경고에 적는다.

## 2차: 막는 대상을 이 서브에이전트와 연결된 작업 트리로 좁힘

같은 저장소에서 다른 Claude 세션 10여 개가 각자 worktree 에서 일하므로, 모든 worktree 를 막는 대상으로 삼으면
그 세션들의 Edit/Write(기록은 각자 자기 git 디렉터리), 시험 산출물, IDE 수정이 내 서브에이전트 탓이 된다.
기준(baseline)은 시작 때 전부 찍어 두되, stop 의 판정은 연결된 트리에만 한다.

연결 규칙(경로 비교는 `nk`(구분자·대소문자) + realpath, Git Bash `/c/…` 는 `c:/…` 로 읽고, 앞뒤가 영숫자·`_.-` 인
부분 일치는 제외해 `558` 이 `558-827` 에 걸리지 않게 한다):
- 세션 폴더 트리(항상).
- 이 세션이 Agent 도구로 넘긴 프롬프트에 경로가 나온 worktree: `PreToolUse(Agent|Task)` 의 `prompt` 모드가
  세션 기록 폴더 `prompts.<세션>.jsonl` 에 시각과 함께 남기고, stop 이 서브에이전트 시작 15분 전(`PROMPT_WINDOW_SECONDS`)
  이후 것을 합친다. 동시에 띄운 다른 서브에이전트의 프롬프트도 합쳐지지만 이 세션 것뿐이다.
- 이 서브에이전트가 Bash·PowerShell 로 실행한 명령과 작업 폴더에 경로(또는 `../이름`)가 나온 worktree:
  `PreToolUse(Bash|PowerShell)` 의 `bash` 모드가 그 에이전트 기록의 `linked` 에 더한다.
- 이 서브에이전트가 Edit/Write 한 작업 트리(`pre` 가 `linked` 에 더한다).
- 시작 뒤 생겨 기준이 없는 트리가 연결되면 그 직전 상태를 기준으로 더한다(Bash 는 명령 실행 전, 즉 만든 다음 명령부터).

연결된 다른 worktree 는 그 트리의 `<git 디렉터리>/harness-subagent-guard/` 의 Edit/Write 기록도 읽어 합친다(다른 세션이
거기서 정상으로 고친 것은 설명된 변경). 연결 안 된 트리의 변경은 막지도 경고하지도 않는다 — 누가 했는지 가릴 수 없고,
경고하면 다른 세션 때문에 늘 시끄럽다. hooks.json 에 `PreToolUse` `Bash|PowerShell`·`Agent|Task` 항목을 더했다(각 10초, `|| true`).

## 시험 (`checker/tests/test_subagent_edit_guard.py`)

다른 worktree 스크립트 수정 -> 막힘 / Edit·Write -> 통과 / Edit 뒤 스크립트 덮어쓰기 -> 막힘 / 시작 전 변경 -> 통과 /
다른 저장소 Edit 뒤 스크립트 -> 막힘 / 시작 뒤 생긴 worktree -> 확인 못 함 / worktree 목록 못 읽음 -> 확인 못 함 +
세션 폴더는 그대로 점검.

2차 시험: 연결 안 된 worktree 변경은 안 막음 / 프롬프트에 나온 worktree 스크립트 수정은 막음(11-09 사고 재현, 구분자·대소문자
다른 표기 포함, 접두사만 같은 이름은 연결 안 됨, 15분 넘은 프롬프트는 제외) / Bash 명령에 나온 worktree 는 막음 / 에이전트가
만든 worktree 는 다음 명령부터 막음 / 연결된 트리에서 다른 세션 기록이 있는 변경은 통과.

## 한계

- 연결은 경로 문자열로 판단한다. 지시문·명령에 경로가 한 번도 안 나온 worktree(상대 경로 `cd ..` 이동 뒤 `cd 이름`, 변수로 조립한
  경로 등)를 스크립트로 고치면 못 막는다. 연결 판단이 틀려 연결 안 된 트리를 고친 경우도 점검 밖이다.
- 같은 명령 안에서 worktree 를 만들고 바로 고치면(그 명령 실행 전엔 경로가 없다) 그 수정은 못 본다.

- 다른 저장소(시작 때 모르던 곳)는 서브에이전트가 거기를 Edit/Write 하기 전에 스크립트로 고친 것은 못 본다.
  Edit/Write 없이 스크립트로만 다른 저장소를 고치는 경우도 못 본다(어느 저장소인지 알 길이 없다).
- 시작 뒤 만든 worktree 의 스크립트 수정은 막지 못하고 "확인 못 함" 으로만 알린다.
- 그 밖의 한계는 #601 기록과 같다(`.gitignore` 대상, 포맷터 훅, 동시 편집 등). worktree 가 많으면 시작·종료의
  `git status` 가 늘어 시간 제한(20초 단위 git 호출)에 걸려 "확인 못 함" 이 될 수 있다.

plugin.json version 0.10.239.
