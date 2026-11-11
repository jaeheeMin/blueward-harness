# #862 웹 콘솔 '이 요청 이전으로 되돌리기' (2026-11-10)

## 배경

데스크톱 앱의 되돌리기(/rewind)가 콘솔에 없었다. `claude -p` stream-json 에서 되는지 실측한 결과 되고, 환경변수 하나로 켠다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `console/managed.py` | 세션을 띄울 때 `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING=1` 을 환경에 더함. 보내는 user 메시지마다 uuid 를 붙이고 대화의 내 말 항목에 `uuid` 로 남김. `Manager.rewind()`(control_request `rewind_files`) |
| `console/server.py` | `POST /api/sessions/:id/rewind` `{uuid, dryRun?}` |
| `static/app.js`, `app.css` | 내 말 아래 단추 → 확인 카드(파일 목록·줄 수·한계 문구·[되돌리기]/[취소]) → 결과 한 줄. 터미널 세션·uuid 없는 옛 말엔 단추 없음, AI 가 일하는 중·끝난 세션이면 막음 |
| `whats_new.json`, `plugin.json`(0.10.261), 길잡이, `docs/design/web-console.md` | 설명·판 |
| `checker/tests/` | 가짜 claude 가 `rewind_files` 를 흉내(환경변수 없으면 canRewind:false, 모르는 uuid, 실제 되돌리기 오류) · 서버 시험 6개 · 화면 시험 3개 |

## 공식 문서 근거 (2026-11-10 조회)

- Claude Code `checkpointing`: Bash 명령으로만 바뀐 파일은 추적하지 않음(이미 Edit 등으로 고친 파일에 나중에 Bash 가 한 변경은 되돌림), 서브에이전트 편집 대부분 복원 안 됨, 외부 변경 추적 안 됨, 심볼릭·하드 링크는 건너뜀, git 대체 아님.
- Agent SDK `file-checkpointing`: Write·Edit·NotebookEdit 만 추적, 되돌리기는 파일만(대화 그대로), 맨 CLI 는 `CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING` 을 직접 켜야 함, 모르는 uuid 는 `No file checkpoint found for this message`, 같은 세션에 묶임, 디렉터리 생성·이동·삭제는 안 돌아감. 문서는 uuid 를 `--replay-user-messages` 로 받으라고 하지만, 실측으로 우리가 user 메시지에 직접 붙인 `uuid` 가 지점으로 쓰임을 확인했다.

## 실측 (콘솔 서버 임시 포트, 실제 claude, pexp/repo 안에서만)

`--model haiku`, `--permission-mode acceptEdits`, managed.py 와 같은 인자, 플러그인은 빈 플러그인(`emptyplug`).

| 단계 | 결과 |
|---|---|
| 1턴: b.txt 를 changed-b 로 | b.txt = changed-b |
| 2턴(콘솔 `/messages`): a.txt 를 changed-a 로 | a.txt = changed-a |
| 2번째 말 uuid 로 dry_run | `canRewind:true`, filesChanged [a.txt 절대경로], +1/-1 |
| 2번째 말로 실제 되돌리기 | a.txt = original, b.txt = changed-b 그대로 |
| 1번째 말로 dry_run → 실제 | b.txt 만 filesChanged, 실제 뒤 b.txt = original |

- 앞선 한 번의 시도에서는 2번째 턴이 파일을 안 고쳤고, 그 말의 uuid 로 dry_run/실제가 `canRewind:false, "No file checkpoint found for this message."` 였다. 즉 파일을 고치지 않은 요청은 지점이 없을 수 있고, 카드는 그 이유를 그대로 보인다(통과로 뭉개지 않음).
- filesChanged 는 절대 경로로 온다. 화면은 세션 작업 폴더 밑이면 상대 경로로 줄여 보인다.
- 실측 뒤 pexp/repo 의 a.txt·b.txt 는 original 로 되돌렸고, 내가 띄운 claude 프로세스는 남지 않았다.

## 11-11 main 위로 옮기며 고친 것(558 세션 점검)

- 첨부(#860)와 합치며 `user_message(text, attachments=None, msg_uuid=None)` 로 둘 다 받는다(첨부 content 배열에도 uuid).
- AI 가 일하는 중이면 내 말마다 "일하는 중엔 되돌릴 수 없어" 와 잠긴 단추가 붙었다(시안 G-18 에 없음) → 일하는 중·끝난 세션은 단추를 그리지 않는다.
- 되돌린 결과가 화면 변수·로그에만 있어 새로 고치면 사라졌다 → 대화에 note 한 줄(ok·bad·warn).
- 확인 카드 문구를 콘솔 기본인 반말로.

## 확인 못 함 / 남은 것

- 이어서 띄운(`--resume`) 세션에서 이전 프로세스에서 만든 지점이 되는지: 안 돌림. 안 되면 `No file checkpoint` 이유가 그대로 보인다.
- 서브에이전트가 고친 파일·Bash 로만 바꾼 파일은 실측 안 함(문서 근거만).
- 브라우저로 실제 화면은 못 봄(가짜 DOM 시험만).
- 보내는 중 새 말이 큐잉(AI 가 일하는 중 보낸 말)되는 경우 그 말의 지점은 문서상 체크포인트가 없을 수 있다(`No code restore`). 단추는 일하는 중엔 막지만, 큐에 들어간 말은 별도 확인 안 함.
