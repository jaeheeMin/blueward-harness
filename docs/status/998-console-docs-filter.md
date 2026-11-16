# #998 콘솔 '내가 만든 문서' 에서 AI 지시 파일 빼기, 첨부는 이름만 넣고 빼게 (2026-11-16)

## 배경
`/docs` 화면과 세션 화면 산출물 칸은 세션이 만든·고친 파일을 모두 보여 줘서 `CLAUDE.md`·`SKILL.md`·`rules/` 같은 AI 지시 파일이 SRS·Spec 과 섞였다. 콘솔 입력칸 첨부(이미지·PDF)는 대화 기록에 이름·형식·크기만 남고 어디에도 저장되지 않는다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/docfiles.py` | `is_ai_instruction(rel)` 한 곳에서 판정, 목록은 상수(`AI_FILE_NAMES`·`AI_DIR_NAMES`·`PLUGIN_DIR_NAMES`·`PROJECT_RULE_DIR`). `_rel_key` 가 걸러 `collect` 목록에서 빠진다 |
| `plugins/harness/console/attachments.py` | `meta` 에 첨부 id 를 더하고, `listed(chat, picks)` 가 대화 기록의 이름·형식·크기로 첨부 목록을 만든다 |
| `plugins/harness/console/server.py` | `/files` 응답에 `attachments`, `POST /api/sessions/<id>/attachments/pick {id, listed}` 로 넣고 빼기(기존 API 의 쿠키·Origin·JSON 검사 그대로). 고른 값은 세션 데이터 `attachPicks` |
| `static/flow-ui.js`, `static/app.css` | `attachBlock`: 산출물 화면·세션 산출물 칸에 "첨부한 파일" 줄(이름·형식·크기, 빼기). 뺀 것은 "뺀 첨부 n개" 접힘 안에서 넣기. 열기·내려받기 없음 |
| `checker/tests/test_web_console.py`, `test_web_console_ui.py` | 새 시험, `CLAUDE.md` 를 쓰던 옛 시험은 `NOTES.md` 로 |
| `docs/guide/harness-guide.html` | 만든 문서 설명에 두 문장 |

## 제외 규칙(작업 폴더 기준 상대 경로)
- 이름이 `CLAUDE.md`·`AGENTS.md`·`SKILL.md`(대소문자 무시)인 파일, 어느 폴더든.
- `.claude/` 아래 전부(어느 깊이든).
- `plugins/<이름>/` 바로 아래 `rules/`·`skills/`·`agents/`·`hooks/`. 스캐폴드 뼈대(`skeleton/rules`, `dot-claude`)도 이 안이다.
- 저장소 루트의 `rules/`(Project Repository 검사 규칙, scaffold 구조). `docs/rules/` 같은 다른 자리는 산출물일 수 있어 빼지 않는다.
- Claude 메모리: 경로에 `projects/…/memory/` 가 있는 파일(작업 폴더 안에 있을 때만 목록에 오르므로).
- 안 빼는 것: `docs/ssot/`(SRS·Spec), `templates/`(양식), `env/`, 그 밖의 md·xlsx·pptx.

## 첨부 기본값
첨부 직후 목록에 **넣은 채**로 둔다. 근거: 사용자가 방금 올린 자기 자료라 "내가 다룬 문서" 에서 안 보이면 오히려 찾게 되고, 빼는 것은 한 번 눌러 되돌릴 수 있다. 고르지 않은 항목만 기본값이고 고른 값은 `attachPicks` 로 저장된다. id 가 없는 옛 대화 기록의 첨부는 가리킬 수 없어 보이지 않는다.

## 원본 미저장
저장하는 것은 id·이름·형식·크기뿐이다. 시험이 sessions.json 에 base64 가 없음을 확인한다.

## 판 번호
plugin.json 0.10.296 → 0.10.298(#999 가 0.10.297).
