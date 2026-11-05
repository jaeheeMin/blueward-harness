# 690 서브에이전트 점검: 시작 기록 없는 에이전트 경고 묶기

## 조사 (공식 문서)

출처: https://code.claude.com/docs/en/hooks (SubagentStart, SubagentStop 절)

- SubagentStart 는 Agent 도구로 띄운 서브에이전트, 재개된 서브에이전트, in-process 팀원의 새 메시지에서 난다.
  입력은 `agent_id`, `agent_type`.
- SubagentStop 은 `agent_id`, `agent_type`, `agent_transcript_path`(`subagents/` 아래), `last_assistant_message` 등을 받는다.
- 문서에 있는 근거: SubagentStop 은 Claude Code 내부 에이전트(프롬프트 제안, `/btw` 곁질문)에서도 난다.
  이때 `agent_type` 은 세션의 `--agent`/`agent` 설정 이름이고, 없으면 빈 문자열이다.
- 문서에 없음: 이 내부 에이전트가 SubagentStart 를 내지 않는다는 명시. 그 밖에 어떤 에이전트가
  Stop 만 내는지도 문서에 없다. (내부 에이전트 Stop 의 페이로드에 `agent_id` 가 들어 있는지도 문서에 없다.)

## 실데이터

- 이 worktree 상태 폴더(`harness-subagent-guard/`)에는 이슈의 agent_id(a56848a…, a32db31…, aca15b5…)가 없다.
  transcript 에서도 이 id 가 나오는 곳은 이번 작업 지시문뿐이었다. 정체(내부 에이전트인지)는 확인하지 못했다.
- 훅은 Stop 페이로드를 따로 남기지 않아 실제 `agent_type` 값을 과거 데이터로는 알 수 없다.

## 고침

- `agent_type == ""` 이고 시작 기록이 없으면 조용히 넘긴다(문서가 내부 에이전트라고 한 경우만).
  `--agent` 를 쓰는 세션은 내부 에이전트도 이름이 있어 가릴 수 없다.
- 그 밖에 시작 기록이 없으면 사용자 화면 `systemMessage` 는 그대로 두고, 메인 모델에는
  `pending-no-start` 에 (세션, id) 한 줄씩 중복 없이 남겨 `do_inject` 가 "시작 기록이 없는 서브에이전트 N개
  (Edit/Write 밖 수정 확인 못 함)" 한 줄로 합쳐 준다.
- 시작 기록이 있는 에이전트의 경고(Edit/Write 밖 수정 등)는 그대로 한 줄씩.
