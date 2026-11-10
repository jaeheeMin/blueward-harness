# #860 웹 콘솔 이미지·PDF 첨부와 여러 줄 입력 (2026-11-10)

세션 화면의 이어서 요청 칸을 여러 줄 textarea 로 바꾸고, 이미지·PDF 첨부를 stream-json user 메시지의 content 블록으로 보낸다. 판 0.10.256.

## 한 일

| 곳 | 내용 |
|---|---|
| `console/static/attach.js`(새) | `BHAttach.composer` — textarea(Enter 보내기·Shift+Enter 줄바꿈·`isComposing`/229 는 안 보냄·자동완성이 열려 있으면 안 보냄), 높이는 내용만큼 늘다 132px(6줄)에서 스크롤, 붙여 넣기·끌어 놓기·파일 고르기, 칩(이미지 작은 그림·PDF 이름·크기·×), 한도 초과는 한 줄 안내. `chatChips` 는 대화 판용. `attach.css`(새) |
| `console/static/app.js` | 이어서 요청 칸을 `composer` 로 교체, `sendFollow` 가 첨부를 같이 보냄, 대화 판 내 말에 첨부 칩, `canAttach` 가 거짓이면 첨부 단추 숨김. 질문·승인 화면의 "AI에게 말하기" 칸은 범위 밖이라 그대로 |
| `console/attachments.py`(새) | 서버 검사(형식 화이트리스트·base64·매직 바이트·크기·개수·합계)와 content 블록 만들기, 기록용 메타 |
| `console/managed.py` | `user_message(text, attachments)`, `send`/`send_or_resume`/`resume`/`launch` 가 첨부를 받음. 쉬는 세션을 `--resume` 으로 띄울 때도 첨부가 첫 메시지로 간다 |
| `console/server.py` | `a_message` 가 첨부를 검사(400·413), 터미널 세션은 409. 이 경로만 본문 상한 32MB |
| `console/store.py` | 대화 항목에 `attachments` 메타(첨부가 있으면 같은 글 연속 중복 제거를 건너뜀), 세션 모델에 `canAttach` |

## 한도와 근거

| 한도 | 값 | 근거 |
|---|---|---|
| 이미지 한 장 | 5MB | Claude API 가 이미지 한 장을 5MB 까지 받는다(이 한도를 넘으면 API 가 거절하므로 미리 막는다) |
| PDF 한 개 | 20MB | 요청 본문 상한 안에 들면서 일반 문서에 넉넉한 값(사용자 지시). API 의 PDF 요청 한도(32MB)보다 작다 |
| 개수 | 5개 | 한 요청에 너무 많이 실으면 느려지고 base64 가 커진다. 화면 칩 한 줄에 보이는 수 |
| 합계 | 20MB(원본) | base64 로 4/3 배 ≈ 26.7MB → 본문 상한 32MB(`HOOK_BODY_LIMIT` 와 같은 값) 안 |
| 본문 상한 | 이 경로만 32MB | 기존 API 1MB 는 첨부에 모자란다. 다른 경로는 그대로 |

## 실측(완료 조건)

stream-json 첨부 모양은 이전 실험(`pexp/l1.txt`·`l1b.txt`)에서 이미지·PDF 모두 확인했다. 이번에는 구현한 코드 그대로 확인했다.

- 작업 폴더는 실험용 `pexp/repo`(사용자 저장소 아님). 인자는 `managed.Manager(...).command()` 가 만든 것 그대로: `claude -p --input-format stream-json --output-format stream-json --verbose --permission-prompt-tool stdio --plugin-dir <빈 플러그인> --model haiku`. 메시지는 `managed.user_message(글, attachments.parse([...]))`.
- 보낸 것: 왼쪽 절반 빨강·오른쪽 절반 파랑인 128x64 PNG + "왼쪽 절반과 오른쪽 절반은 각각 무슨 색이야?".
- 받은 답(haiku, `claude-haiku-5-5`): **"왼쪽 절반은 빨간색이고, 오른쪽 절반은 파란색입니다."** (`result.subtype=success`, `is_error=false`)
- 참고: 그 답 뒤에 이 PC 에 설치된 harness 플러그인의 Stop 훅이 "커밋되지 않은 변경이 있다, /harness:deliver 를 실행하라" 는 피드백을 넣어 `result` 는 그 두 번째 턴 글이다. 첨부와 무관한 환경 영향이다(실험 폴더 `repo` 가 git 저장소이고 추적 안 된 파일이 있음). 로그: `pexp/attach_live.log`, 스크립트 `pexp/attach_live.py`.

## 시험

- `test_web_console.py`: 형식·매직 바이트·base64·크기·개수·합계 거절, `user_message` content 모양(실측과 같음), 첨부 메시지가 가짜 claude 에 content 배열로 가는 것과 기록에 원본이 없는 것(`sessions.json` 포함), 글 없이 첨부만, HTTP 400·413, 터미널 세션 409·`canAttach`. `fake_claude.py` 가 content 배열을 받아 파일에 남긴다.
- `test_web_console_ui.py`: textarea 키 동작, 칩·한도 안내·빼기, 붙여 넣기·끌어 놓기·파일 단추, 터미널 세션 비활성. `console_ui_smoke.js` 의 스크립트 목록에 `attach.js` 추가.

## 남은 것·알아 둘 것

- 화면 모양(높이·칩 크기)은 시안 대조를 하지 않았다. 자동 시험은 DOM 구조만 본다. 입력칸 높이·`.comp` 의 `:has()` 정렬은 실제 브라우저로 확인이 필요하다.
- 새로 고침하면 미리보기 그림은 사라지고 이름 칩만 남는다(원본을 기록에 안 남기는 선택).
- 질문·승인 화면의 "AI에게 말하기" 칸은 아직 한 줄·첨부 없음.
- 터미널에서 연 세션은 Stop 훅 예약 방식이라 첨부를 실을 수 없다.
