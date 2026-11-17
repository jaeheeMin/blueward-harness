# #1038 새 작업 화면: 작업 폴더 목록 고치기와 그림·PDF 첨부 (2026-11-17)

판 0.10.316(열린 PR #1046 이 0.10.315 를 가져가 그 다음).

## 원인(A)

클립 버튼은 입력칸에 `@` 를 넣어 작업 폴더 목록(@ 자동완성)을 띄운다. 다음 때문에 목록이 안 보이거나 `@` 만 남았다.

- Sauce 는 응답이 오기 전에 팝업을 숨겼다. `/api/files` 는 읽기(GET) 동시 3개 제한 줄에 서서 폴더 점검 GET 뒤에 늦게 나갔다.
- Post 는 팝업이 버튼을 덮어, 다시 누르면 입력칸 초점이 빠져 팝업만 닫히고 `@` 가 남았다.
- 준비 상태 응답 등으로 화면이 다시 그려지면 입력칸이 새로 만들어져 열린 팝업이 사라졌다.

## 한 일

| 곳 | 내용 |
|---|---|
| `console/static/app.js` | `/api/files` 는 GET 줄을 거치지 않는다. `withAssist` 에 `filePopup`(두 테마 모두 제목·찾는 중·빈 폴더·폴더 먼저 고르기 안내)·`inline`(입력칸 아래 제자리, 버튼·카드를 안 덮음), `toggleFiles`(누르면 열고 다시 누르면 닫으며 단독 `@` 를 지움)·`refresh`. 클립 버튼은 mousedown 에서 초점을 안 뺏고, 글은 "작업 폴더에서 고르기". 다시 그려도 열려 있던 목록을 이어 보인다. 새 작업 입력칸을 `BHAttach.composer`(plain)로 바꾸고 첨부 칩·고르기 단추·안내·끌어 놓기, `begin`/`start` 는 첨부를 읽는 중이면 막고 안내, `start` 는 `attachments` 를 보낸다. 확인 화면에 첨부 칩 |
| `console/static/attach.js` | composer 옵션 `cls`·`rows`·`plain`(높이 자동·Enter 보내기 없음), `restore` 에 안내 글 이어받기 |
| `console/static/app.css` | 인라인 팝업·제목·안내·첨부 줄 |
| `console/server.py` | `a_start` 가 `attachments.parse` 로 검사(400·413, 세션 띄우기 전)해 `manager.launch(attachments=)` 로 넘김. `ATTACH_PATH` 가 `/api/new/<id>/start` 도 잡아 이 경로도 본문 32MB |
| `docs/guide/harness-guide.html` | 새 일 맡기기 설명 |

## 판단

- 첨부는 분석(읽기 전용 AI)에는 보내지 않고 시작할 때만 보낸다(분석 단계는 글·폴더만 읽는다).
- 한도는 이어서 요청과 같다(attachments.py). 이름은 서버가 경로 부분을 떼어 내고(`\` 도 `/` 로 본다) 내용은 매직 바이트로 검사하므로 OS 에 따라 갈리지 않는다.
- 인라인 팝업은 목록이 열리면 아래 단추가 밀린다(덮는 것보다 낫다고 봤다).
