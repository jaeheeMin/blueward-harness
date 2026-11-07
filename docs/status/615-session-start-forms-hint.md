# #615 세션 시작 훅의 고객 양식 안내 (콘솔과 같은 기준)

## 전에는

- `hooks/session-start-sync.sh` 는 기준 폴더(`templates/` 와 `rules/` 를 함께 가진 폴더, 꼭대기에서 깊이 3)가 하나도 없을 때만 `/harness:scaffold` 를 안내했다. 구조가 있으면 `templates/` 가 비어 있어도 말이 없었다.
- 콘솔은 PR #719 부터 "준비됨인데 고객 양식 원본이 없다" 를 따로 안내했다(`docs/status/615-skill-guide-workflow-sync.md` 의 5번). 훅은 그 기준을 몰랐다.

## 바꾼 것

- 판정을 한 벌로: `console/server.py` 의 `PRUNE_DIRS`·`standard_folders`·`has_standard_folder`·`FORM_*`·`customer_forms` 를 새 모듈 `console/standards_scan.py` 로 옮겼다(stdlib 만 씀). 서버는 거기서 import 하므로 이름과 동작은 그대로다. 같은 파일을 `python standards_scan.py <저장소 꼭대기>` 로 부르면 `has`/`none`/`unknown` 한 줄을 낸다.
- 훅: 기준 폴더가 있을 때 `uv run --no-project python console/standards_scan.py` 를 불러 `none` 이면 한 줄을 더한다.
  - 전: (출력 없음)
  - 후: `구조는 만들어졌지만 templates/ 에 고객 양식 파일(엑셀·파워포인트 등)이 아직 없습니다. 다음: 고객사 양식 원본을 templates/ 에 넣으십시오(양식 없이 md 로만 쓰는 프로젝트면 무시해도 됩니다).`
- 안내하지 않는 경우(콘솔과 같다): 고객 양식 있음, 기준 폴더 없음(그땐 scaffold 안내만), 플러그인 저장소(`.claude-plugin/marketplace.json`), `HARNESS_NO_SCAFFOLD_HINT=1`, 목록을 읽지 못함·uv 나 python 이 없음·스크립트가 없음("확인 못 함" 을 "없음" 으로 말하지 않는다).
- 시험 `checker/tests/test_session_scaffold_hint.py` 에 4개 더: 없음 안내(기본 틀 `templates/harness/`·`~$` 임시 파일은 안 셈), 있음, 환경 변수·플러그인 저장소, 스크립트 없음.
- 길잡이 scaffold 탭, `whats_new.json`, 판 0.10.193.

## 남은 일

- 훅과 콘솔의 확장자·건너뛰는 폴더는 이제 같은 코드다. 훅의 기준 폴더 찾기(`find`, 깊이 4)는 그대로 shell 이라 모듈의 `standard_folders`(깊이 3)와 같은 뜻이지만 코드는 둘이다.
