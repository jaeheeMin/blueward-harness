# #944 CAP·UI5 개발 표준 기계 검사 (0.10.289)

## 배경
`conventions/cap-ui5.md` 의 규칙 중 기계로 판정되는 것을 하네스가 검사한다. 규칙은 데이터라는 원칙대로 엔진 기본 목록은 `checker/ui5_checks.yaml`, 프로젝트 설정은 `conventions/cap-ui5.yaml`(있을 때만 켜짐)이다.

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/ui5_rules.py`, `checker/ui5_checks.yaml` | 대상 판정(이름 끝만)·설정·13개 규칙·CLI `files`/`check`. 종료코드 0/1/2 |
| `scripts/check_changed.py`, `scripts/render_report.py` | 환경변수 `DOC_GUARD_DIFF_FILE` 의 diff 로 추가 줄만 검사, 리포트 `ui5` 키와 PR 코멘트 절 |
| `.github/workflows/pr-checks.yml`, `main-checks.yml` | `git diff -U0 --no-renames` 로 `diff.txt` 생성, `DOC_GUARD_PATHS` 에 view/fragment/i18n 추가 |
| `plugins/harness/hooks/pre_write_guard.py` | 저장 직전 디스크와 최종 내용의 줄 차이만 엔진에 넘김. violation 은 deny, warn 은 알림 |
| `cap-ui5.md`, `cap-ui5.example.yaml`, `common.md`, `README.md`, 길잡이 | 규칙 id 표, 구현하지 않은 `[경고]` 는 `[리뷰]` 로 |

## 규칙
막기: UI5-001 console, 002 `==`, 003 ID 하이픈, 004 XML 한글. 경고: 101 icon, 102 `/>` 공백, 103 DOM, 104 private 멤버, 105 공백 들여쓰기, 106 변수 접두어, 108 i18n 키, 109 i18n 주석, 110 메시지 끝맺음.

## 결정
- UI5-107(메서드 이름 `fn`+대문자)은 구현하지 않았다. 문서가 `fn` 을 함수를 담는 변수의 접두어라고 정리해 근거가 없다.
- 전역변수·세미콜론·공백·빈 줄·이벤트 핸들러/상수/CDS 이름 등 판정이 애매하거나 만들지 않은 `[경고]` 는 `[리뷰]` 로 바꿨다.
- 새 파일은 전체 줄이 대상. UI5-105 는 파일 기존 줄 다수가 공백이면 내지 않고, 여러 줄이면 한 건으로 묶는다.
- `*.min.js` 는 제외. 화면 XML·properties 는 doc-guard 대상에서 뺐다(out_of_scope 소음과 기준 폴더 없는 저장소의 검사 불능 방지).
