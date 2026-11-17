# #1067 산출물 탭에 고객 양식으로 뽑은 파일만 보이기 (2026-11-17)

## 결정
산출물 탭(`/docs`, Sauce·Post 공통 `docsPage`)의 목록에도 세션 칸(#1037·#1048)과 같은 기준을 쓴다. 고객 양식으로 뽑은 파일(xlsx·pptx·docx, `flow-logic.js` `isFormOutput`)만 보이고 md·작업본·pdf·기록 폴더 파일은 목록에서 뺀다. 하나도 없으면 "아직 양식으로 뽑은 산출물이 없어."

## 한 것
| 파일 | 내용 |
|---|---|
| `static/flow-ui.js` | `docsPage` 가 세션마다 받은 `/files` 를 `.filter(L.isFormOutput)` 으로 거른다(`#1037` 의 `docsPanel` 과 같은 함수). 빈 안내 문구 변경 |
| `checker/tests/test_web_console_ui.py` | 목록 시험을 양식 파일만 보이게 고치고, 양식이 하나도 없는 시험 추가 |
| `docs/guide/harness-guide.html`, `whats_new.json`, `plugin.json` | 설명·판 0.10.324 |

## 판단
- 거르는 자리는 서버가 아니라 화면 쪽(`load()`)이다. 서버 `docfiles.collect` 는 그대로 둔다.
- 거른 뒤 미리보기·결과 화면 흐름(가장 최근이 양식 xlsx 면 결과 화면)은 그대로 둔다. md 전용 분기(`xlsx로 뽑기`, 고쳐 달라고 하기)는 목록에 md 가 없어 닿지 않는다.

- 홈 `recentCard`(Sauce 홈 `homeView` 와 Post 홈 `HK.recentCard` 가 같이 부른다)도 `.filter(L.isFormOutput)` 으로 걸러 "이번 주 산출물" 숫자와 "최근 산출물" 목록이 탭과 같은 기준이다. 빈 문구는 "아직 양식으로 뽑은 산출물이 없어."
- 닿지 않게 된 md 전용 코드 중 `docsPage` 의 `exportBtn`·`canExport`·첫 미리보기를 md 로 고르던 줄은 지웠다(다른 화면에서 쓰지 않는다).

## 남은 것(범위 밖)
- `docsPage` `previewBox` 의 양식이 아닌 파일 분기(열기·폴더에서 보기 단추, 고쳐 달라고 하기 입력칸)는 두었다. `docsPage` 에서는 닿지 않지만 지워도 되는지는 따로 정한다.
- `docs/design/web-console.md` 의 산출물(`/docs`) 설명(요구사항·설계 / 고객 양식 / 기록 묶음, md 에 `xlsx로 뽑기`)과 홈 설명은 옛 동작 그대로다.
