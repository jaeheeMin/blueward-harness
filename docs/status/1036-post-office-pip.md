# #1036 Post 사무실 장면 작은 창(PiP) (2026-11-17)

## 배경
#1033 의 사무실 장면 번들이 Document Picture-in-Picture 를 지원하도록 바뀌었다(ai-office-iso 7eee0da). `documentPictureInPicture` 가 있으면 장면 오른쪽 아래에 반투명 아이콘("작은 창으로 보기")이 뜨고, 누르면 600×250 창으로 장면이 옮겨 간다. 패널엔 "작은 창에서 보는 중 · 여기로 돌려놓기" 한 줄. `destroy()`(홈 떠남) 때 장면이 PiP 에 있으면 PiP 는 살아 1초마다 `list()` 로 스스로 갱신하고, 다시 attach 하면 한 줄만 보인다. 사람 클릭은 처음 받은 `onNavigate` 로 간다.

## 한 것
| 파일 | 내용 |
|---|---|
| `plugins/harness/console/static/post/office/office-post.js` | 새 번들로 교체(ai-office-iso 7eee0da, cmp 같음. innerHTML·eval·new Function 0) |
| `plugins/harness/console/static/theme-post.js` | 테마를 Sauce 로 바꾸거나 차분이면(`sync` 의 drop 분기) `closePip()` 으로 PiP 도 닫는다. 홈을 떠날 때(`destroy`)와 효과 강도 변경(`onMotion`)은 닫지 않는다 |
| `plugins/harness/.claude-plugin/plugin.json`, `console/whats_new.json` | 0.10.309 → 0.10.313(열린 PR #1040=0.10.310·#1046=0.10.311·#1050=0.10.312 와 겹치지 않게) |
| `docs/guide/harness-guide.html` | 웹 콘솔 탭 "화면 모양" 사무실 설명에 PiP 문장 |
| `checker/tests/test_web_console_ui.py` | 번들에 documentPictureInPicture·"작은 창으로 보기" 있고 innerHTML 계열 없음, theme-post.js 가 PiP 를 닫음 |

## 판단
- 번들이 돌려주는 객체는 `{update, destroy, _moveTo}` 뿐이라 PiP 닫기 API 가 없다. 브라우저의 `documentPictureInPicture.window.close()` 로 닫는다(창이 닫히면 번들의 `pagehide` 처리가 정리한다). PiP 를 쓰는 곳은 이 장면뿐이다.
- 사람 클릭: 번들이 PiP 안 클릭도 처음 받은 `onNavigate` 로 보낸다. app.js 의 `onNavigate` 는 `go(href)` 로 본 창의 라우트를 바꾸고 `go` 는 본 창 `history` 를 쓰므로 PiP 안 클릭도 본 창을 옮긴다(코드로 확인).
- CSP(`script-src 'self'`, `style-src 'self' 'unsafe-inline'`, `font-src 'self'`): 번들은 스크립트를 PiP 로 싣지 않고(본 창 JS 가 PiP 문서를 조작) 스타일은 본 창 스타일 규칙을 style 요소로 복사하므로 `unsafe-inline` 안이다. 외부 주소 없음.
- 못 한 것: 실제 PiP 창은 사용자 제스처가 필요해 헤드리스로 열지 못했다(아이콘 표시만 확인).
