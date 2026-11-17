# #1037 세션 산출물 칸에 양식으로 뽑은 파일만 보이기 (2026-11-17)

## 결정
세션 화면 오른쪽 "산출물" 탭의 "만든 산출물"에는 md 작업본에서 고객 양식으로 뽑은 파일(xlsx·pptx·docx, `flow-logic.js` `isFormOutput`)만 보인다. md·그 밖의 파일은 목록에서 뺀다. 양식 파일이 없으면 "아직 양식으로 뽑은 산출물이 없어".

## 한 것
| 파일 | 내용 |
|---|---|
| `static/flow-logic.js` | `isFormOutput` 이 `\` 를 `/` 로 맞춘 뒤 폴더·확장자를 판정(Windows 경로도 같다) |
| `static/flow-ui.js` | `docsPanel` 이 `/files` 응답을 `isFormOutput` 으로 거른다. 첫 미리보기는 가장 최근 양식 파일. 빈 안내 문구 변경. 산출물 전용 화면(`docsPage`)은 그대로 |
| `static/app.js` | Post: "바뀐 파일" 목록(`regions.files`)을 산출물 탭에서 기술 탭으로 옮김, 빈 안내 문구. Sauce 배치는 그대로("자세히" 접힘) |
| `static/app.css` | `.sess-side .docs-pane` 미리보기 글자 13px(제목 14px, 표 12px) |
| `checker/tests/test_web_console_ui.py` | 새 시험 |
| `docs/guide/harness-guide.html`, `whats_new.json`, `plugin.json` | 설명·판 0.10.314(열린 PR #1040·#1046·#1050·#1044 가 0.10.310~313 이라 그 다음, #1044 뒤에 병합) |

## 판단
- 서버 `docfiles.collect` 는 `docsPage` 도 쓰므로 거르지 않고 클라이언트(`docsPanel`)에서 거른다. 서버는 경로를 `/` 로 맞춰 주지만 클라이언트 판정도 `\` 에 견디게 했다.
