# #619 웹 콘솔 세션 화면의 차례 제목·만든 문서·승인 명령 표시

## 한 일

- `console/store.py`: `report_asks`(마지막 결과 보고의 끝 줄이 물음표로 끝나는지)와 세션 모델 필드 `askedInText`. 턴이 끝났고 승인·질문 대기가 없을 때만 참이고 `group` 은 `todo`. `touchedFiles`(이 세션이 만든·바꾼 파일, 커밋해도 안 지움)와 `remember_touched` 추가.
- `static/app.js`·`flow-logic.js`·`flow-ui.js`: `askedInText` 이면 큰 제목 "내 답을 기다려요.", 상태 "내 답을 기다리는 중(추정)", 홈 카드 "내 답을 기다려요", 할 일 동사 "답하기". 세션 화면에 추정임을 알리는 한 줄과 git 짐작 차례 참고 한 줄. 판정은 서버 한 곳, 화면은 읽기만.
- 만든 문서: 목록 항목이 `kit.baseName(path)` 로 이름만 보이던 것을 상대 경로 전체로. `server.py` 의 `refresh_git`·`a_session_files` 와 `hooks_api.py` 가 `touchedFiles` 를 쌓고 목록은 이를 함께 본다.
- 승인 화면: Bash "명령" 칸을 `dd.scroll`(pre-wrap, 긴 줄 접힘, 높이 스크롤)로.
- `docs/design/web-console.md` §7·§7b·§8·§9, `docs/guide/harness-guide.html` 웹 콘솔 탭, plugin.json 0.10.161.
- 시험: `test_web_console.py` 에 질문 판정·`askedInText`·커밋 뒤 목록 유지 추가.

## 검토 뒤 고친 것

- `askedInText` 는 이번 턴에 받은 보고(`reportFresh`)에만 반응한다. 새 턴(UserPromptSubmit, 콘솔 메시지)에서 끄고 Stop 훅·콘솔 `result` 에서 켠다. `managed.py` 의 `not s["report"]` 조건은 첫 턴 보고가 고정되는 문제가 있어 `not reportFresh` 로 바꿨다(이후 턴 결과도 반영).
- 추정 표시를 큰 제목·홈 카드·할 일 동사에도 붙였다.
- `touchedFiles`: 세션을 처음 본 때 바뀌어 있던 파일(`baselineFiles`)은 `git status` 쪽에서 뺀다(훅의 Edit·Write 경로는 그대로). 같은 폴더 다른 세션의 변경은 구분 못 해 화면·설계 문서에 한계로 적었다. 항목의 `changed` 는 지금 `git status` 에 있는 것만 참이고 화면이 "아직 커밋 안 됨"/"바뀐 것 없음(커밋됨)" 으로 보인다.
- 500개 상한에 닿으면 `truncated` 로 화면에 알리고, 건너뛰는 폴더(SKIP_DIRS) 경로는 쌓지 않는다.
- `refresh_git` 의 `status_paths` 실패를 삼키지 않고 `touchedGap` 으로 남겨 목록에 `unknown`(그 사이 커밋된 문서가 빠졌을 수 있음)을 낸다.
- 버전: main 0.10.159, 열린 PR #617 이 0.10.160 이라 이 PR 은 0.10.161.

## 2번 원인

`refresh_git` 이 `git status` 결과로 `s["changedFiles"]` 를 통째로 덮어썼다. 만든 문서 목록은 이 값과 지금의 `git status` 만 합쳤으므로, 커밋하면 둘 다 비어 목록이 줄었다(32개 → 커밋 안 된 CLAUDE.md 1개). 파일 이름만 보이게 한 것은 화면(`flow-ui.js`)이었다.

## 알아 둘 것

- 질문 판정은 "끝 줄이 물음표로 끝남" 이라는 추정이다. 물음표 없는 부탁은 못 잡고, 물음표로 끝나는 인용은 잘못 잡을 수 있다.
- 기준선(`baselineFiles`): 첫 `refresh_git` 성공 때 한 번 적는다. 늦게 잡혀도 세션 시작 뒤에 마지막으로 바뀐 파일(mtime ≥ `startedAt`)은 기준선에 넣지 않아 첫 턴에 만든 파일이 빠지지 않는다. 대신 시작 뒤에 다른 세션·사람이 바꾼 파일은 섞일 수 있다(같은 폴더 다른 세션은 구분 못 함, 화면에 안내). 기준선 전에 목록을 먼저 부르면 그때 바뀌어 있던 파일이 들어간다.
- git 저장소가 아닌 폴더는 커밋 여부를 모른다고 `unknown` 으로 알린다. `.gitignore` 로 `git status` 에 안 나오는 파일을 "커밋됨" 이라 하지 않도록 문구는 "지금 바뀐 것 없음(git 기준)".
- `touchedGap` 은 `{reason, at}` 이고 30분 동안만 알린다(영구 경고 없음). `a_session_files` 안의 실패도 같은 방식이다. 경로 중복은 구분자·대소문자를 같게 보고, 작업 폴더 밖 경로는 쌓지 않는다.
- 실제 claude 세션 브라우저 확인은 코디네이터가 했다(질문 대기 제목·이유 줄, 경로 + "아직 커밋 안 됨", 여러 줄 명령).
- 길잡이 아티팩트는 병합 뒤 다시 올려야 한다(`docs/guide/README.md`).
