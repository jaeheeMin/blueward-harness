# #904 웹 콘솔 산출물 미리보기 표가 글자 단위로 쪼개짐 (0.10.267)

## 원인

`.md { overflow-wrap: anywhere }` 를 표 칸(`th`·`td`)이 물려받았다. 오른쪽 산출물 칸(약 300px)에서 표는 칸 너비 안에 맞추려고 각 칸을 한 글자 폭까지 줄였고, `REQ-001` 이 R / E / Q / … 로 세로로 쪼개졌다. `.md-table` 가로 스크롤은 있었지만 칸이 줄어들 수 있어 넘치지 않았다.

## 바꾼 것

- `static/app.css`: `.md th, .md td { overflow-wrap: normal; word-break: keep-all; }`(낱말 단위로만 줄바꿈), `.md td:first-child { white-space: nowrap; }`(첫 열 ID 한 줄). 넘치는 열은 기존 `.md-table { overflow-x: auto }` 로 표 안에서 옆으로 넘긴다.
- 시험 `test_markdown_table_cells_do_not_break_per_letter`(규칙과 순서).
- #858 의 "G-09 미리보기 표 ID 칸 줄바꿈" 도 이것으로 해결. #858 의 나머지(진행 중 세션의 다음 갈래 표시)는 남는다.
- 길잡이 웹 콘솔 '작업 화면', whats_new 0.10.267.

## 확인

- 헤드리스 크롬으로 G-09 화면에서 SRS.md 를 눌러 1440·1280 을 찍음: 첫 칸 `REQ-001` 한 줄(칸 79px), 제목 "구매오더 / 조회 앱" 은 낱말 단위 두 줄, 표(292px)가 칸(206px)보다 넓어 표 안에서 가로 스크롤, 페이지 가로 넘침 없음.
- 시안 자동 검사 G-09·G-14 통과.
