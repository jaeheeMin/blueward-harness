# #878 웹 콘솔 계획 모드에서 계획 파일 쓰기 승인이 두 번 더 뜸 (0.10.266)

## 원인

계획 모드(`--permission-mode plan`)에서 AI 는 계획을 `<설정 폴더>/plans/<이름>.md` 에 `Write`(가끔 `Edit` 도) 한다. claude -p 는 이것을 `can_use_tool` 로 묻는다(#861 실측 lB1:15). 콘솔의 묻지 않고 허용 판정(#649, `risk.classify`)은 작업 폴더 안 쓰기만 safe 로 보고, 작업 폴더 밖 쓰기는 "되돌릴 수 없어" 카드로 묻는다. 그래서 계획 확인(`ExitPlanMode`) 카드 앞에 승인 카드가 더 떴다.

## 바꾼 것

- `console/risk.py`: `classify(…, plan_dir="")`, `plan_dir_of(설정 폴더)`, `_is_plan_file`. plan_dir 를 받으면 그 폴더 **바로 아래**의 `.md` 파일 쓰기만 safe("계획 모드에서 계획 파일을 쓸 뿐이야"). 하위 폴더·다른 확장자·폴더 자체·`..`·글자만 같은 다른 `plans` 는 아니다. realpath 로 본다(이 PC 의 plans 는 심볼릭 링크였다).
- `console/safe_tools.json`: `plan_dir_name: "plans"`, `plan_file_suffixes: [".md"]`(코드에 이름을 박지 않는다).
- `console/hooks_api.py` `decide`: 세션 `permissionMode` 가 `plan` 일 때만 plan_dir 를 넘긴다. 설정 폴더는 `session_alive.config_dir(transcriptPath)`(대화 기록 경로 → 없으면 `CLAUDE_CONFIG_DIR` → `~/.claude`). 콘솔 세션과 브라우저가 열린 터미널 세션(훅) 모두 이 판정을 쓴다.
- 시험: `test_risk_plan_file_is_safe_only_with_plan_dir_and_only_direct_md`, `test_managed_bridge_auto_allows_plan_file_only_in_plan_mode`(고치기 전 코드로 실패 확인).
- 길잡이 웹 콘솔 탭 '답하는 것', `docs/design/web-console.md`, whats_new 0.10.266.

## 결정

- 계획 모드일 때만 허용한다. 평소 모드에서 AI 가 설정 폴더 plans/ 에 쓰는 일은 흔하지 않고, 쓰면 묻는 게 맞다.
- 질문 수준이 "모든 명령마다 묻기(all)" 면 그대로 묻는다(다른 safe 판정과 같다).

## 실측 (11-12, claude 2.1.321, haiku, 실험 저장소 pexp/repo, 빈 플러그인)

콘솔 `Manager` 와 `Hooks` 를 그대로 붙여 계획 모드로 "plan878.txt 에 hello 쓰는 계획" 을 시켰다.

- 로그: `자동 허용: Write: <설정 폴더>\plans\plan878-txt-hello-line… (계획 모드에서 계획 파일을 쓸 뿐이야)` 뒤 `승인 요청: ExitPlanMode`
- 사람에게 묻는 요청 1개(`ExitPlanMode`). 실측으로 생긴 계획 파일은 지웠다.

## 확인 못 한 것

- 데스크톱 앱이 계획 파일 쓰기를 묻지 않는지는 공식 문서로 확인하지 않았다(콘솔 동작만 바꿨다).
- 이번 실측에서는 `Edit` 로 계획 파일을 고치는 경우가 나오지 않았다(시험으로만).
