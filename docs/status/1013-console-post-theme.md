# #1013 웹 콘솔 설정에 테마 고르기 + 두 번째 테마 Post(우체국) (2026-11-16)

## 배경
콘솔은 디자인 "Sauce" 한 벌뿐이었다(테마 고르기 없음). 콘솔 시안의 두 번째 테마 Post(우체국)를 색·모양과 라인아트 장면(움직이는 SVG 부품)까지 옮긴다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/static/post/` | 시안의 우체국 부품(manifest.js + SVG 134개)을 그대로 복사 |
| `plugins/harness/console/server.py` | `/static/post/...` 하위 폴더(최대 3단계)의 `.svg`·`.js` 를 낸다(`POST_ASSET`). 글꼴 폴더 규칙과 `is_within` 검사는 그대로 |
| `plugins/harness/console/static/theme.js` | `bh-theme`(sauce 기본 · post) 저장·적용, `BH.THEMES/getTheme/setTheme`. `html[data-theme]` 으로 걸고 `bh-theme` 이벤트를 쏜다. 모르는 값은 sauce |
| `plugins/harness/console/static/theme-post.css` | `:root[data-theme="post"]` 아래에만: 변수 덮기 + 변수로 안 되는 자리 보정 + 장면 스타일 |
| `plugins/harness/console/static/theme-post.js` | 시안 `postMap` 을 콘솔용으로 옮긴 장면. DOM 으로만 만든다(innerHTML 없음) |
| `plugins/harness/console/static/app.js` | 설정 "테마" 구역, 홈 위 장면 띠(`sceneList` 가 실제 세션을 손님으로 바꾼다) |
| `plugins/harness/console/static/app.css` | 머리 주석 정정, 새 클래스(`.theme-grid`·`.theme-card`)만 끝에 추가. 기존 규칙은 그대로 |
| `plugins/harness/console/static/index.html` | theme-post.css·theme-post.js 연결(theme.js 는 head 동기 그대로) |
| `plugins/harness/console/whats_new.json`, `.claude-plugin/plugin.json` | 0.10.299 → 0.10.303(main 0.10.300, 열린 PR 이 0.10.301·0.10.302 를 쓰고 있다) |
| `docs/guide/harness-guide.html` | 웹 콘솔 "화면 모양"·"산출물·설정" 에 테마 고르기 설명 |
| `checker/tests/test_web_console.py`, `test_web_console_ui.py` | 테마 저장·적용, static 하위 폴더 제공, Sauce 규칙 보호 시험 |

## 판단
- **Post 는 밝게 한 벌만 넣었다.** 시안의 어둡게·테마 기본/밝게/어둡게 고르기는 넣지 않았다(범위). 어둡게는 `:root[data-theme="post"][data-mode=...]` 변수 한 벌과 고르기 칸을 더하면 된다.
- **장면은 실제 세션에 연결했다.** 상태는 사이드 목록과 같은 기준(막힘·확인 못 함 > 내 차례 > 일하는 중 > 승인 기다림 > 끝), 창구는 갈래의 지금 단계(srs→요구사항, spec→개발 Spec, deliver·merge·승인 기다림→검토, 끝→합쳐짐, 그 밖·갈래 없음→개발). 끝난(ended) 세션은 그리지 않고, 손님은 최대 14명.
- 강조색은 시안의 #D9483B 대신 #C73E31 로 약간 진하게 했다(흰 글자 대비 확보).
- 장면은 `role="img"` + 요약 `aria-label`, 손님 링크는 `tabindex=-1`(같은 내용이 세션 목록에 있다). 움직임 줄이기면 멈춘 한 장면.

## 남은 한계
- 시험은 구조·저장·서버 제공만 본다. 모양은 시험 콘솔을 헤드리스 Chrome 으로 띄워 홈·설정 화면(1440px)만 눈으로 봤다. 세션 화면·새 작업 등 나머지 화면의 Post 색과 좁은 너비는 못 봤다.
- 화면 대조(`CONSOLE_MOCKUP_CHECK=1`)는 이 변경 전 HEAD 에서도 G-02·G-20·G-22~24 가 실패하고 돌 때마다 실패 화면이 달라, Sauce 가 그대로인지의 근거로는 약하다.
- 부품 SVG 는 시안 그대로라 다크 배경 대응이 없다.
- 시험 실행: `uv run pytest checker/tests -k "console or theme or static" -q -rs` → 1479 통과, 3 건너뜀, 0 실패.
- 검토(별도 서브에이전트)에서 고친 것: 판 겹침(0.10.302 → 0.10.303), 저장이 막힌 창에서 장면·설정 표시가 Sauce 로 보이던 것(`getTheme` 이 화면에 건 테마를 먼저 본다), 한 창구 5명째부터 겹치던 자리, 14명 넘게 잘릴 때 aria-label 에 알림.
- 검토에서 남긴 것: 장면(`role="img"`) 안 손님 링크는 보조기기·키보드로 닿지 않는다(같은 내용이 세션 목록에 있어 그대로 둠). 테마 칸은 화살표 키 이동이 없다(글자 크기 고르기와 같은 방식). 장면이 켜진 동안 매 프레임 이미지 opacity 를 다시 쓴다(측정 안 함).
