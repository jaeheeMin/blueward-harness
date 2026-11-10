# #861 웹 콘솔 계획 모드의 계획 보기와 승인 화면

판 0.10.257. 브랜치 `feat/861-console-plan-approval`.

## 바꾼 것

- 계획 모드의 `ExitPlanMode` 승인 요청을 전용 "계획" 카드로 그린다(`static/app.js` `drawPlan`). 본문은 AI 말과 같은 마크다운 렌더러를 쓰고, 길면(28줄·2,200자 넘음) 접어 두고 `계획 전체 보기` 로 연다. 도구 입력 원문은 `자세히` 안에만 있다.
- 단추: `이 계획대로 진행`(allow) / `고쳐 달라고 하기`(사유 입력칸이 열리고, 적어서 보내면 deny + reason). 사유가 비면 보내기를 막는다.
- `toolInput.plan` 이 없거나 글이 아니거나 비었으면(코디네이터 실측: 계획 파일을 안 쓰면 `ExitPlanMode` input 이 `{}`) 카드 본문 자리에 "계획 본문이 없어" 를 사실대로 적고 단추는 그대로 둔다. `planFilePath` 가 오면 위치만 적는다. 서버가 그 파일을 읽어 보여 주는 것은 임의 경로 읽기라 하지 않았다(필요하면 별도 이슈로 검토).
- 홈·사이드·세션 화면의 문구: 계획 확인 요청이 기다리면 "승인하기" 대신 "계획 확인하기", 홈 카드 단추 "가서 계획 보기", 표의 상태 칩 title "계획 확인 기다림", 눈썹 "내 계획 확인을 기다리는 중". 요청 제목은 서버가 "계획 확인" 으로 준다(`store.request_title`), 처리 결과 줄도 "이 계획대로 진행하기로 함" · "고쳐 달라고 함".
- 권한 모드 표시: `system/status permissionMode` 를 화면에 이미 반영하고 있었다. 계획을 승인해 모드가 기본으로 돌아오면 고른 값(`permissionChoice`)도 `plan` 에서 비운다(`managed.py`). 안 비우면 권한 모드 고르개가 계속 "계획만 세우기" 로 보이고, 이어 띄울 때 다시 계획 모드로 간다.
- 서버 답: 허락은 기존 그대로(`updatedInput` = input 그대로, 훅은 `{behavior: allow}`). 거절 사유가 비면 "계획을 고쳐 달라고 했어.".

## 실측

pexp/repo(스크래치패드의 임시 git 저장소) 안에서만, 모델 `claude-haiku-5-5`, `managed.py` 와 같은 인자(`-p --input-format stream-json --output-format stream-json --verbose --permission-prompt-tool stdio --model … --permission-mode plan`)로 `Manager.launch` 를 거쳐 콘솔 서버(임시 포트 55426, 4873·4874 아님)에 실제 HTTP 로 답했다. `--plugin-dir` 은 훅이 없는 빈 플러그인으로 두어 사용자 콘솔에 신호가 가지 않게 했다(훅 경로는 이 시험에 없다).

1. 계획 모드에서 haiku 가 `Write`(계획 파일 쓰기, 작업 폴더 밖 홈 폴더) 승인을 두 번 요청 → 일반 승인 카드로 온다(범위 밖, 아래 "남은 것").
2. `ExitPlanMode` control_request 도착. `GET /api/requests/:rid` 가 `toolName: ExitPlanMode`, `toolInput.plan`(851자), `planFilePath` 를 그대로 준다.
3. `고쳐 달라고 하기` 경로: `POST answer {decision: deny, reason: "copy.txt 맨 위에 '# copied' 한 줄도 …"}` → AI 가 "ExitPlanMode가 피드백을 돌려줬습니다: … 계획 파일을 고치고 다시 승인을 요청하겠습니다" 라고 하고 계획을 고쳐 `ExitPlanMode` 를 다시 요청(두 번째 계획에 `# copied` 반영).
4. `이 계획대로 진행` 경로: `POST answer {decision: allow}` → 같은 세션에서 `permissionMode` 가 `plan` → `default`, `permissionChoice` 가 `plan` → `""`, 세션 기록에 "계획 승인: 권한 모드가 계획만 세우기에서 기본(으)로 바뀜". AI 가 "계획이 승인되었으니 실행합니다" 하고 `PowerShell` 승인을 요청(권한 모드가 기본이라 이제 일반 승인) → 허락 → `copy.txt` 생성, 첫 줄 `# copied` + 원본 `hi`.
5. 실측에서 알아낸 것: Windows 에서 계획 글(`plan`) 맨 앞에 BOM(U+FEFF)이 붙어 온다. 그대로 마크다운에 넣으면 첫 `# 제목` 이 제목으로 안 그려져서 화면에서 앞 BOM 을 떼고 그린다(시험 포함).

## 시험

- `checker/tests/test_web_console.py`: 훅 경로(요청 모양 그대로 전달, allow/deny/사유 비움 응답, 제목·결과 줄), 콘솔 세션 control_request(허락의 `updatedInput` 이 input 그대로, 거절 message, status `default` 가 오면 화면 값·고른 값이 기본으로).
- `checker/tests/test_web_console_ui.py`: 계획 카드(마크다운 제목, BOM, 두 단추, 사유칸 열림, allow/deny POST 본문, 결과 문구, plan 이 없을 때 "계획 본문이 없어", 긴 계획 접기), 세션·홈 문구.

## 남은 것 · 확인 못 한 것

- 터미널 세션의 `PermissionRequest` 훅이 `ExitPlanMode` 에도 뜨는지는 못 쟀다. 뜬다면 같은 카드가 그려지고(요청 모양이 같다) 응답은 `{behavior: allow|deny, message}` 다. 터미널에서 이 카드를 쓴 기록은 없다.
- 실측 1: 계획 모드의 계획 파일 쓰기(`Write`, `~/.claude/.../plans/*.md`)가 작업 폴더 밖이라 `risk.classify` 가 되돌릴 수 없는 일로 보고 묻는다(실제 로그의 `risk` 값은 확인하지 않았다). 계획을 쓸 때마다 카드가 두 번 뜬다. 이 범위 밖이라 건드리지 않았다. 별도 이슈 #878 로 남겼다.
- 이미 처리된 계획 요청을 새로고침해 다시 열면 결과 문구가 "닫힌 요청" 으로 나올 수 있다(일반 승인도 같은 기존 동작: 서버 outcome "허용함" 이 화면의 코드 매칭에 안 걸린다). 처리 직후 화면과 대화 줄의 결과는 정상이다.
- 홈 표의 "계획 확인 기다림" 은 칩의 title(마우스를 올리면 보이는 글)이라 시험은 글자 검사 대신 코드 경로로만 봤다.
