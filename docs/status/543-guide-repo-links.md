# #543 길잡이 관리자 문구 수정과 두 저장소 연결 탭 (2026-10-29)

- **운영 파일 대신 올리기**: GitHub 관리자 탭(#531)의 운영 파일 항목이 관리자가 `git am` 을 직접 치는 것처럼 읽혀, 팀원 · 관리자가 Claude 에게 무엇이라고 말하는지("이 변경 patch 로 이슈에 올려 줘" / "이슈 #n 의 patch 로 PR 열어 줘")로 바꾸고 명령은 Claude 가 실행한다고 적었다. #532 병합 직후라 이 PR 로 따로 올렸다.
- **두 저장소의 연결**(`links`, "시작 전에" 묶음, 한눈에 보기 다음): blueward-harness(Plugin Repository)와 public-cloud(Project Repository)를 연결하는 다섯 가지 — `.claude/settings.json` 의 Plugin 설치, Hook 이 받는 엔진 `v{판}` 태그, caller workflow 5개의 `@stable` 호출, `release-tag` 의 태그 이동, 엔진이 읽는 기준 파일 — 를 HTML 도식과 표로 넣었다. 하네스 소개 아티팩트의 "연결 고리" 장표와 같은 내용이다. 좁은 화면에서는 세로로 쌓인다.
- 이전 · 다음 순서: 한눈에 보기 → 두 저장소의 연결 → 처음 준비하기.
- 확인: 로컬 Chrome 에서 새 탭을 글꼴 7종 × 넓은 화면 · 400px 폭으로 넘침이 없음을 재고, 이전 · 다음 이동을 눌러 확인했다.
