# #683 웹 콘솔 세션 이름이 첫 줄 그대로 나오던 문제 (2026-11-04)

## 배경

세션 이름을 첫 요청의 첫 줄로 정해서 "[Image #26]", "<cross-session-message from=...", "<task-notification>", "/harness:scaffold" 같은 글이 이름으로 보였다.

## 바꾼 것

| 곳 | 내용 |
|---|---|
| `plugins/harness/console/store.py` | `prompt_title(text)` 추가 — 프롬프트 전체에서 시스템 블록(`system-reminder`·`task-notification`·`local-command-*`, 닫는 태그가 없으면 끝까지)과 이미지·붙여넣기 자리표시를 지우고, `<command-*>` 블록이나 `/` 로 시작하는 줄이면 빈 문자열, `cross-session-message` 는 태그만 걷고 `다른 세션: ` 을 붙인다. `display_title(s)` 추가 — 요청 글 이름(title_rank 2 이상)이 없으면 브랜치(`#683 console session names`) > 스킬의 쉬운 말(`요구사항 문서 · <폴더>`, `SKILL_TITLES` 는 `static/app.js` 의 `SKILL_LABELS` 와 같게) > `이름 없는 세션 · <폴더>` 순. 옛 판이 60자로 잘라 저장해 여는 태그의 `>` 가 없는 `<cross-session-message …` 도 걷는다. 세션 요약의 `title` 에만 쓰고 저장값은 그대로. `load()` 는 title_rank 2 인 옛 저장 제목을 `prompt_title` 로 다시 정리한다. 비어도 rank 는 2 로 둔다 — 처음엔 0 으로 내렸더니 대화 중간 말("응 계속 진행해")이 이름이 됐다(크롬 확인). 이제 브랜치 등 대체 이름으로 보인다. Linux 에서 Windows 경로의 폴더 이름이 통째로 나오던 것도 고쳤다(Actions ubuntu 실패) |
| `plugins/harness/console/hooks_api.py` | UserPromptSubmit 이 `prompt_title(전체 글)` 을 쓴다. 빈 결과면 이름을 정하지 않는다(다음 진짜 요청이 이름이 된다) |
| `plugins/harness/console/managed.py` | `launch` 의 제목, `send` 가 같은 방식. `send` 가 `/` 를 떼고 슬래시 명령을 이름으로 쓰던 것을 없앴다 |
| `plugins/harness/console/server.py` | 승인·질문 요청의 `sessionTitle`, 전체 다시 불러오기 결과의 `title` 도 `display_title` 로 |
| `checker/tests/test_web_console.py` | `prompt_title` 경우별, 훅 경유, 이미지만 보낸 뒤 다음 요청, `display_title` 순서, `load` 정리 시험. 기존 첫 이벤트 시험의 기대값만 폴더 이름 `work` → `이름 없는 세션 · work` 로 |

## 시험

`uv run pytest -q -p no:cacheprovider checker/tests/test_web_console.py checker/tests/test_web_console_ui.py`

실제 콘솔 저장값(`~/.claude/harness-console/sessions.json`, 세션 26개)에 대입: `[Image #n]` 8개·`<task-notification>`·`/harness:scaffold`·잘린 `<cross-session-message` 2개가 모두 `#657 capture wide table`, `작업 시작 · plugin-work` 처럼 바뀌었다. 크롬으로 홈 화면 확인.

## 남은 것

- 세션 이름을 사용자가 직접 바꾸는 기능은 이번에 넣지 않았다(이슈의 "더 좋다" 항목).
