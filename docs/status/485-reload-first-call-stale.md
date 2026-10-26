# #485 /reload-plugins 직후 첫 스킬 호출이 옛 판으로 보여 /harness:update 가 확인 불능으로 멈추는 문제

## 현상

- 1회차(0.10.115 → 0.10.117): reload 직후 `/harness:version` 의 base dir 가 0.10.115 였고, 다음 호출은 0.10.117 이었다.
- 2회차(0.10.117 → 0.10.119): update 뒤 reload 하고 곧바로 `/harness:update` 를 불렀다. loaded 0.10.117, latest 0.10.119, same_repo_entries 는 0.10.119, state 는 stale 이라 "갱신 확인 불능 → 새 세션" 으로 멈췄다.
- 두 번 모두 `${CLAUDE_PLUGIN_ROOT}` 치환이 reload 뒤 첫 호출에서만 옛 판 경로였다.

## 판단

- reload 직후 첫 호출의 치환이 한 번 늦는 것으로 보인다. 한 번 더 부르면 풀릴 가능성이 크다. 원인은 추정이다.
- 그래서 reload 뒤 첫 stale 은 확인 불능이 아니라 "한 번만 더" 안내 대상이다. 두 번째에도 stale 이면 그때 확인 불능이다.

## 결정

- update 스킬 1단계: reload 안내 뒤 첫 stale 이면 "한 번만 더" 를 안내하고 멈춘다(갱신 명령은 다시 실행하지 않는다). 안내를 이미 했으면 5단계로 간다. 횟수는 대화 기록으로 판단한다.
- 4단계에서 미리 "한 번 더 불러야 할 수 있다" 고 말하고, 5단계는 두 번째 확인에서만 쓴다.
- version 스킬: 갱신 있음 안내에 한 줄 추가. 렌더 출력(`installed_version.py`)은 바꾸지 않아 테스트 변경은 없다.
- 길잡이의 `/harness:update`·`/harness:version` 설명을 고쳤다. sync 스킬의 버전 확인 안내는 다른 방식이라 건드리지 않았다.
- plugin version 0.10.122.

## 남은 일

- Claude Code 공식 문서에 reload 직후 스킬 치환이 한 번 늦는다는 내용이 있는지는 확인하지 못했다. 없으면 피드백 초안을 쓸지 사용자에게 묻는다.
- 병합 뒤 길잡이 아티팩트에 다시 올린다.
