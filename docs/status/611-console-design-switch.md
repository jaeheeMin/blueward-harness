# #611 웹 콘솔 디자인 A·B·C 바꿔 보기와 글꼴 내장

## 한 일

- `static/theme.js`: 디자인(기존 `base` / `a` / `b` / `c`)을 `bh-design` 으로 이 PC 에 저장하고 `<html data-design>` 에 적용한다. 모르는 값은 `base`. A·B·C 에서는 테마가 넣은 인라인 색을 비워 스타일시트가 색을 정하게 한다.
- `static/app.js`: 위쪽 줄(`topline`)에 빠른 전환 버튼 4개(`aria-pressed`), 설정 화면에 "디자인" 칸. 둘은 `data-design-id` 로 같은 값을 맞춘다.
- `static/app.css`: `@font-face`(Pretendard 45~920, JetBrains Mono, swap)와 `--font`·`--mono` 맨 앞 글꼴, 끝에 `:root[data-design="a"|"b"|"c"]` 범위의 색·카드·상태 표시. 기존 디자인 규칙은 건드리지 않았다.
- `console/server.py`: `.woff2` → `font/woff2`, `fonts/` 한 단계 하위만 서빙. CSP `font-src 'self'` 는 그대로 충분하다.
- `static/index.html`: CSP 가 막던 Google Fonts `<link>` 3줄 제거.
- 시험: `test_web_console_ui.py`(저장·적용·기본값·대비 4.5:1·중립색·범위·모양 표시), `test_web_console.py`(woff2 MIME·경로 제한).

## 색 기준

Blueward 파랑 `#004696` 은 로고·지금 단계·주 버튼에만. 바탕·면·글자 회색은 파란 기가 없는 중립색(A 회색, B 차콜, C 미색). 초록 계열 없음.

## 알아 둘 것

- 플러그인 크기가 글꼴 약 2MB(Pretendard 2.06MB) 늘었다.
- 서버가 정적 파일에 `Cache-Control: no-store` 를 붙여 글꼴도 화면을 열 때마다 내려받는다(로컬이라 빠르다). 필요하면 글꼴만 캐시를 허용하도록 따로 고친다.
- B 의 "순서·지금 할 일을 위 상자에 모음" 은 DOM 순서를 바꾸지 않고 갈래 칸을 큰 상자로 꾸미는 것으로 했다.
- 길잡이 아티팩트는 병합 뒤 다시 올려야 한다(`docs/guide/README.md`).
