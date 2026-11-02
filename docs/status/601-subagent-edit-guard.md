# 601 서브에이전트 Edit/Write 밖 수정 막기

이슈 #601. 서브에이전트가 python heredoc 등으로 파일을 고치면 Write/Edit 훅이 안 돈다.
지시문으로는 지켜지지 않아(2026-11-02 세 번, #600 구현 서브에이전트) 훅으로 막는다.

## 공식 문서 근거 (https://code.claude.com/docs/en/hooks)

- 서브에이전트 안의 PostToolUse 입력에 `agent_id`, `agent_type` 공통 필드가 실린다
  ("tool events such as PreToolUse and PostToolUse fire the same configured hooks as in the main
  conversation, and the input carries the agent_id and agent_type").
- PostToolUse 입력: `session_id`, `transcript_path`, `cwd`, `tool_name`, `tool_input`(Write: `file_path`,
  `content` / Edit: `file_path`, `old_string`, `new_string`, `replace_all`), `tool_response`, `tool_use_id`.
  파일 도구 경로는 항상 절대 경로이고 플랫폼 구분자를 쓴다. NotebookEdit 의 경로 키는 문서 발췌에 없어
  `notebook_path` 도 함께 읽는다(실측 필요).
- SubagentStart 입력: `session_id`, `transcript_path`, `cwd`, `agent_id`, `agent_type`. 막을 수 없고
  `additionalContext` 만 낸다.
- SubagentStop 입력: 위 + `stop_hook_active`, `agent_transcript_path`, `last_assistant_message`.
  `decision: "block"` + `reason` 이면 서브에이전트가 계속 돌고 `reason` 이 다음 지시로 전달된다.
  종료 코드 2 도 같다(그래서 이 훅은 오류에도 0 으로 끝낸다).

## 설계

`plugins/harness/hooks/subagent_edit_guard.py` (stdlib 만, `record`·`start`·`stop` 모드), 상태는
`<git 디렉터리>/harness-subagent-guard/` (git 이 추적하지 않고 worktree 별).

- 기준: SubagentStart 에서 `git status --porcelain -z -uall` 의 경로와 각 파일 sha1.
- 기록: PostToolUse 에서 고친 파일의 상대 경로와 고친 직후 sha1 을 행위자별 jsonl 에 덧붙인다
  (병렬 호출이 같은 파일에 써도 줄 단위 append 라 깨지지 않는다).
- 판정: SubagentStop 에서 (지금 status 경로 ∪ 기준 경로) 의 해시를 다시 구해, 기준과 같으면 시작 전부터 있던
  변경이라 통과, 현재 해시가 Edit/Write 기록 중 하나와 같으면 설명된 변경, 둘 다 아니면 막는다.
  Edit 뒤에 스크립트로 덮어쓴 파일은 해시가 기록과 달라 잡힌다. 되돌리기(`git checkout`)나 삭제도 잡힌다.
- 반복 한도: 같은 `agent_id` 가 2번 막힌 뒤에는 통과 + `systemMessage`(와 stderr)로 메인에 경고.
- 검사 불능: git 아님, 기준 없음, git·파일 읽기 실패, 입력 깨짐 -> 막지 않고 "확인 못 함" 경고. 어떤 경우에도 종료 코드 0.
- hooks.json: uv 를 못 띄우면 `systemMessage` 로 "확인 못 함" 을 낸다(exit 2 로 가두지 않는다).

### 동시 서브에이전트·메인 편집 오탐 줄이기

- 모든 행위자(메인 포함, 모든 세션)의 Edit/Write 기록을 한 데 모아 대조한다. 다른 서브에이전트나 메인이
  Edit/Write 로 고친 파일은 "설명된 변경" 이라 막지 않는다.
- 시작 전부터 있던 변경은 기준 해시로 제외한다.
- 겹쳐 도는 다른 서브에이전트가 있으면 막는 사유에 "네가 고친 파일이 아니면 건드리지 말고 그렇다고 답하라" 를 덧붙인다.

### 검토 지적 반영 (2차)

- 경고를 메인 모델에게도: `systemMessage` 는 사용자 화면 전용이라 경고(한도 초과·확인 못 함·HEAD 변경)를
  `pending-warnings` 에도 적고, 메인 쪽 `PostToolUse(Agent|Task)` 의 `inject` 모드가
  `hookSpecificOutput.hookEventName="PostToolUse"` + `additionalContext`(문서의 PostToolUse 출력 형식)로 한 번 주입하고
  비운다. 서브에이전트 안의 호출(`agent_id` 있음)에서는 건드리지 않는다. `systemMessage` 도 그대로 낸다.
- 기록 대조는 서브에이전트 시작 시각 이후 행(`t >= started`)만 쓴다. 시작 이후 쓰이지 않은 기록 파일은 열지도 않는다.
- 사슬 검증: PreToolUse 훅이 편집 직전 해시(pre)와 "그 파일이 이미 git 상태에 변경으로 잡혀 있었나(d)" 를
  `pre.<tool_use_id>.json` 에 적고, PostToolUse 가 합쳐 `{p, pre, h, t, w, d}` 행으로 남긴다. 파일마다
  기준 해시 -> pre -> post -> ... -> 현재 내용이 이어져야 설명된 변경이다. 기준에 없던(HEAD 와 같던) 파일은 첫 편집 직전에
  이미 변경이면 끊긴 것으로 본다. Write(전체 덮어쓰기)와 막힌 뒤의 재편집은 사슬을 다시 시작시킨다(안 그러면 한 번 막힌 파일을
  Edit 으로 고쳐도 영원히 풀리지 않는다). pre 가 없는 행은 그 고리를 확인하지 않는다(판정 불능을 위반으로 만들지 않음).
  정상 흐름(연속 Edit, 시작 전부터 변경된 파일, Write 로 새 파일 만든 뒤 Edit)이 막히지 않는 것을 시험으로 확인.
- SubagentStart 에서 `git rev-parse HEAD` 를 저장하고 Stop 에서 달라졌으면 block 대신 경고(커밋으로 점검 밖에 뺀 경우).
- 끝났다는 기록 없이 1시간 넘은 서브에이전트는 겹침 판정에서 뺀다. 겹침 문구는 "다른 에이전트가 고쳤다면 파일 이름과 근거를
  적어라" 로 바꿨다.
- prune 을 Stop 에서도 돌린다(`pending-warnings` 는 지우지 않는다).

### 한계

- 메인 세션이 도중에 Bash 로 고친 파일, 동시에 도는 다른 서브에이전트가 Bash 로 고친 파일은 누가 했는지
  가릴 수 없어 잘못 막을 수 있다(2번까지 막고 풀린다).
- `.gitignore` 대상 파일은 `git status` 에 안 나와 점검 밖이다. 저장소 밖 경로 수정도 점검 밖이다.
- 서브에이전트의 `cwd` 가 시작 때와 끝날 때 다른 저장소면 기준을 못 찾아 "확인 못 함" 이 된다.
- 같은 파일에 Edit 으로 같은 내용을 먼저 쓰고 스크립트로 같은 내용을 다시 쓰는 경우는 구별할 수 없다.
- 포맷터 훅이 Edit 뒤에 파일을 다시 쓰면 현재 내용이 마지막 post 해시와 달라져 잘못 막힌다(설계는 유지, 2번까지 막고 풀린다).
- 같은 파일을 여러 행위자가 거의 동시에 Edit 하면 pre/post 가 시간순으로 엇갈려 사슬이 끊길 수 있다.
- 백그라운드 서브에이전트의 경고는 메인이 `Agent` 를 다시 부를 때까지 주입되지 않는다. git 저장소가 아니면 경고는 사용자 화면에만 뜬다.
- 실제 claude 확인(완료 조건 3번)은 메인 세션이 haiku 로 했다: Bash 쓰기 -> 1번 block -> Write 로 다시 씀 -> 통과. 2차 변경(pre 훅·inject)은
  실제 claude 로 다시 확인하지 못했다.
- 큰 저장소에서 `git status`/해시가 느리면 SubagentStart 20초·Stop 40초 제한에 걸려 "확인 못 함" 이 된다.

## 시험

`checker/tests/test_subagent_edit_guard.py` (임시 git 저장소, 훅을 subprocess 로 실행): Edit 만 -> 통과,
스크립트로 씀(수정·신규·Edit 뒤 덮어쓰기) -> block, 읽기만 -> 통과, 시작 전 변경 -> 통과, 한도 -> 통과+경고,
git 아님·기준 없음·깨진 입력 -> 통과+경고, 메인 편집·동시 서브에이전트 -> 통과, hooks.json 등록.

plugin.json version 0.10.156.
