# #400 Agent 호출 훅으로 서브에이전트 위임 규칙 강제 (2026-10-28)

## 배경

- `rules/delegation.md` 는 서브에이전트 모델 고정과 정의된 에이전트 사용을 문서와 `agents/` 정의 파일에만 맡기고 "반복해서 지켜지지 않으면 훅을 검토한다" 고 미뤄 뒀다(#139).
- 지켜지지 않은 사례: 2026-10-10 revfactory/harness 비교 회고 세션, 그리고 **2026-10-27~28 에 메인 세션이 모든 Agent 호출에 `model: "sonnet"` 을 넘겼다**. 결과가 같은 sonnet 이라 피해는 없었지만, 넘긴 model 이 정의 파일보다 우선하므로 정의 파일의 고정이 우회된다. 문서만으로는 반복해서 지켜지지 않는 것이 확인됐다.

## 결정

- `hooks/agent_delegation_guard.py` 를 `hooks.json` 의 `PreToolUse` 매처 `Agent|Task` 에 등록했다. 공식 문서(hooks, PreToolUse input)의 도구 이름은 `Agent` 이고, 옛 이름 `Task` 는 문서에서 확인하지 못해 방어로 함께 맞춘다.
- 입력 필드(공식 문서 `##### Agent`): `prompt`, `description`, `subagent_type`("Type of specialized agent to use"), `model`("Optional model alias to override the default"). 표는 `model` 만 Optional 로 적고 `subagent_type` 의 필수 여부는 적지 않는다 — 그래서 없으면 거절한다.
- 거절 조건: `model` 이 비어 있지 않음 / `subagent_type` 이 없음·비었음·`general-purpose`·`claude` / 입력 해석 불가(`tool_input` 이 객체가 아님 포함)는 검사 불능(원칙 7).
- **거절 목록 방식(허용 목록 아님).** 허용 목록이면 `fork`, `web-fetch`, `claude-code-guide`, `Explore`, `Plan`, `statusline-setup`, 다른 플러그인의 에이전트가 막힌다. 대가: 새 기본형 에이전트 이름이 생기면 `CATCH_ALL_TYPES` 에 넣기 전까지 통과한다.
- 적용 범위: 메인 세션과 서브에이전트 안 호출 모두(구분하지 않는다, 단순함 우선).
- 훅 스크립트는 stdlib 만 쓰고 `uv run --no-project` 로 돈다(기존 훅과 같다). uv 가 없으면 hooks.json 의 `|| exit 2` 로 막는다.

## 시험

- `checker/tests/test_agent_delegation_guard.py`: model 있음 거절, 빈 model 통과, 기본 에이전트(대소문자 포함) 거절과 안내문, subagent_type 없음·빈 값·비문자열 거절, harness 에이전트·fork·web-fetch 등 통과, 입력 해석 불가 8종 검사 불능 거절.
- `test_plugin_layout.py` 의 훅 목록·매처 기대값에 새 훅을 추가했다.

## 바꾼 문서

- `plugins/harness/rules/delegation.md` "이 규칙의 강제 방식": "그때 훅을 검토한다" 문장을 빼고 훅과 거절 목록 결정을 적었다.
- `plugins/harness/README.md` 훅 표, `docs/guide/harness-guide.html` 의 "Claude 와 일하는 방식" 박스.

## 남은 일

- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- 새 기본형 에이전트 이름이 생기면 `CATCH_ALL_TYPES` 를 넓힌다.
- plugin version 0.10.135 (main 0.10.133, 0.10.134 는 열린 PR #525 가 쓴다).
