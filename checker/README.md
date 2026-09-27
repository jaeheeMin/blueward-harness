# checker — 검사 엔진

문서를 읽어 고객사별 규칙과 대조하고 위반 목록을 내는 엔진이다.

```
checker/
  cli.py            check <파일...> --rules <규칙 파일 또는 폴더> 진입점
  loader.py         규칙 파일을 평면 목록으로 펼치고 템플릿에서 기대값을 뽑는다
  engine.py         관할을 판정하고 규칙을 돌려 위반을 모은다
  model.py          Violation, Rule, DocType, ConfigError
  rules/            규칙 종류별 모듈 (하나가 한 종류를 담당)
    filename.py           파일명 형식
    location.py           파일이 있어야 할 경로
    required_sections.py  필수 절 (md, docx)
    required_sheets.py    필수 시트 (xlsx)
    table_headers.py      표 헤더 (xlsx)
    slide_layouts.py      공식 템플릿에서 시작했는지 (pptx)
    external_traces.py    다른 거래처 흔적이 남아 있는지 (오피스 전체)
  ooxml.py          오피스 파일의 본문이 아닌 자리를 읽는다
  cleaner.py        흔적을 걷어낸 새 파일을 만든다 (사람이 직접 부른다)
  ssot_approval.py  PRD(docs/ssot/) 변경 PR 의 승인 여부를 판정한다(#49).
                    Actions(`scripts/ssot_approval.py` 가 감싼다)와 harness
                    훅(`uvx` 로 `python -m checker.ssot_approval` 을 부른다)이
                    같은 판정 로직을 쓴다
  code_rules.py     공통 개발 규칙 CR-001(한글 이름), CR-002(반복문 안 DB
                    조회)를 코드(ABAP, JS/TS, CDS, BDEF)에서 검사한다(#54,
                    #72). BDEF 는 반복문이 없어 CR-001 만 적용한다. 문서
                    검사(engine.py)와 관할이 다르다 — 기준 폴더(`templates/`
                    와 `rules/` 를 함께 가진 폴더)를 요구하지 않고 모듈
                    하나에 CLI 까지 담는다.
                    `pre_write_guard.py` 훅과 `scripts/check_changed.py` 가
                    같은 함수(`build_report`)를 쓴다
  code_checks.yaml  code_rules.py 의 설정. 언어별 확장자와, 그 언어에 어느
                    CR 을 적용할지가 데이터로 있다
  readers/          형식별 본문 추출 (md, docx, xlsx, pptx)
  tests/
    make_fixtures.py  픽스처 생성. 결과물은 커밋하지 않는다
```

## 왜 플러그인 밖에 있나

같은 엔진을 두 곳에서 부르기 때문이다.

| 진입점 | 도는 곳 | 엔진을 어떻게 얻나 |
|---|---|---|
| `plugins/harness/` 훅 | 팀원 PC 의 Claude | 마켓플레이스에서 설치 |
| GitHub Actions | GitHub 서버 | 대상 저장소에 번들로 들어가야 함 |

Actions 는 팀원 PC 에 설치된 플러그인을 쓸 수 없다. 엔진을 `plugins/` 안으로
옮기면 Actions 경로가 끊긴다.

**엔진은 자기 저장소를 검사하지 않는다.** 고객사별 Project Repository 가 이것을
가져다 쓴다.

```
<Project Repository>/
  templates/    기준 문서. 원본 형식 그대로 둔다
  rules/        이 저장소의 규칙
  docs/         검사 대상
```

```
doc-guard --rules <Project Repository>/rules/ <Project Repository>/docs/*.md
```

기준 폴더가 여러 개면 `--auto` 로 파일마다 기준 폴더를 스스로 찾게 한다. 한 PR 이 두
기준 폴더를 건드릴 수 있으므로 GitHub Actions 쪽이 이것을 쓴다.

```
doc-guard --auto <바뀐 파일들>
```

기준 폴더는 `templates/` 와 `rules/` 를 함께 가진 디렉터리다. 이 판단은 `locate.py` 에
한 벌만 두고 플러그인 훅과 Actions 가 함께 쓴다. `engine.py` 는 폴더 규약을 모른다.

## 설계 원칙

**규칙은 코드가 아니라 데이터다.** 규칙 자체는 고객사별 규칙 파일에 적고, `rules/`
아래 모듈은 규칙 *종류* 를 구현한다. 새 규칙 종류를 더할 때는 `rules/` 에 파일을
하나 넣고 `@rule("이름")` 을 붙이면 되고, `engine.py` 는 건드리지 않는다. 이것은
`tests/test_registry.py` 가 지킨다 — 엔진 소스에 규칙 종류 이름이나 확장자가
박혀 있으면 테스트가 실패한다.

**기대값은 템플릿에서 읽는다. 다만 어디를 볼지는 규칙이 지정한다.** 절 목록이나 표
헤더를 규칙 파일에 받아적으면 기준이 두 벌이 되고, 누가 템플릿을 고치고 규칙을 안
고치면 철 지난 목록으로 검사하면서 아무 경고도 하지 않는다. 그래서 값은 템플릿에서
읽는다. 다만 실제 고객사 템플릿은 어느 시트가 필수인지, 몇 행이 헤더인지를 스스로
말해 주지 않으므로, 그 *위치* 는 규칙 파일이 지정한다.

**관할은 느슨하게, 검사는 엄격하게.** 유형을 판정하는 glob 과 filename 규칙의 패턴을
같게 두면 순환이 생긴다. 이름을 틀린 파일이 어느 유형에도 걸리지 않아 조용히 무시되고,
정작 filename 규칙이 잡아야 할 파일을 놓친다.

**템플릿은 원본 형식 그대로 둔다.** 엑셀 템플릿을 md 로 바꿔 보관하지 않는다. 사본이
원본과 어긋나고, 무엇보다 검사하려던 구조(시트 이름, 헤더 행, 슬라이드 레이아웃)가
변환 과정에서 사라진다.

## 출력

stdout 에 JSON 리포트를 낸다. 플러그인 훅 출력과 PR 코멘트가 같은 내용을 쓴다.

```json
{
  "summary": {"scoped": 1, "passed": 0, "violations": 1, "skipped": 1, "out_of_scope": 0},
  "files": [
    {
      "file": "docs/제안서/제안서최종.md",
      "type": "제안서",
      "template": "../templates/제안서.md",
      "status": "violation",
      "violations": [
        {"rule": "filename", "expected": "^\d{8}_.+_제안서\.md$",
         "actual": "제안서최종.md", "message": "파일 이름이 정해진 형식과 다르다"}
      ]
    },
    {
      "file": "docs/제안서/.gitkeep",
      "type": "제안서",
      "template": "../templates/제안서.md",
      "status": "skipped",
      "reason": "자리표시·시스템 파일이라 문서로 보지 않는다",
      "violations": []
    }
  ]
}
```

상태는 넷이다. `out_of_scope` 는 대조할 템플릿이 없어 검사하지 않았다는 뜻이고,
`pass` 와 구분된다. 검사한 적 없는 파일에 "통과" 라고 답하면 거짓말이다.

`skipped` 는 관할 안에 있었지만 `.gitkeep` 처럼 자리표시·시스템 파일이라 애초에
문서로 보지 않은 것이다. 위반으로도, `scoped`(검사한 문서 수)로도 세지 않고
`reason` 과 함께 따로 센다. 목록은 `engine.py`의 `SKIPPED_BASENAMES` 한 곳에만
둔다 — 늘리면 진짜 산출물이 검사 없이 통과할 위험이 커지므로, 도구가 자동으로
남기는 것이 확실한 이름만 짧게 유지한다. 그 밖에 읽을 리더가 없는 형식(`.hwp`,
`.pdf` 등)은 이 예외를 타지 않고 여전히 설정 오류(검사 불능)로 끊는다.

위반이 없어도 판정된 유형과 템플릿 경로를 싣는다. 문서를 올리는 사람은 위반을 알기
전에 "뭘 보고 쓰지" 부터 궁금하기 때문이다.

## 종료코드

| 코드 | 뜻 |
|---|---|
| 0 | 통과. 전부 관할 밖이라 검사한 것이 없는 경우도 여기 든다 |
| 1 | 문서 위반 |
| 2 | 설정 오류. 규칙 파일이 깨졌거나 관할이 겹쳤다 |

`1` 과 `2` 를 나누는 이유는 받는 사람이 다르기 때문이다. 문서를 올린 팀원은 규칙 파일을
고칠 권한도 지식도 없으므로, 훅은 두 경우에 다른 안내를 해야 한다.

전부 관할 밖인 경우를 0 으로 묶는 이유는 README 만 고친 PR 이 CI 를 깨뜨리면 안 되기
때문이다. 그 사실은 종료코드가 아니라 리포트의 `scoped` 가 싣는다. `3` 이상은 비워 둔다.

## 내보내도 되는 파일인가

규칙 종류 하나(`external_traces`)만 묻는 것이 다르다. 나머지는 "이 회사 템플릿과 룰대로
썼나" 를 보지만 이것은 "이거 내보내도 되나" 를 본다. 서로 독립이라 템플릿을 완벽히 따른
문서에도 흔적이 있을 수 있다.

실제 템플릿에서 발견한 것들이다. 화면에는 보이지 않는다.

| 자리 | 무엇이 |
|---|---|
| `xl/styles.xml` | 복붙으로 쌓인 명명 스타일. 이름이 곧 거래처와 사업명이다 |
| `customXml/` | SharePoint 가 남긴 사용자 이름과 소속 |
| `docProps/` | 작성자, 최종 수정자, 회사, 관리자 |
| `comments*.xml` | 주석 작성자 실명 |

**거래처 이름 목록을 맞춰 보지 않는다.** 목록은 계속 관리해야 하고 목록에 없는 새
거래처는 영영 못 잡는다. 대신 "정상적인 파일이라면 이런 모양이 아니다" 를 본다. 깨끗한
엑셀의 명명 스타일은 기본 몇 개뿐인데 문제의 파일은 54,653개였다.

걷어내는 것은 사람이 부른다. 엔진의 다른 부분은 전부 읽고 판정만 하고, 여기만 쓴다.

```
doc-guard --clean <파일...> [--out-dir <곳>]
```

원본을 덮지 않고 새 파일을 낸다. 남의 산출물을 도구가 말없이 바꾸면 안 되고, 오피스
파일은 잘못 건드리면 이미지와 서식이 날아가므로 사람이 결과를 보고 정해야 한다.

`openpyxl` 이나 `python-docx` 로 열어 저장하지 않는다. 그 라이브러리들은 자기가 모르는
부분을 버리는데, 실제로 openpyxl 은 이미지를 버린다. zip 항목을 그대로 다뤄 손대지 않은
항목은 바이트 그대로 옮긴다. 실제 파일에서 619KB 가 201KB 로 줄었고 시트와 이미지와
서식은 그대로였다.

## 두 껍데기

엔진은 판정만 한다. 막는 것은 껍데기의 일이고 둘이 있다.

| 껍데기 | 언제 | 무엇을 막나 | 어디에 |
|---|---|---|---|
| 플러그인 훅 | 팀원 PC 에서 문서를 저장할 때 | 텍스트 문서 | `plugins/harness/hooks/` |
| GitHub Actions | 커밋해서 올릴 때 | 모든 형식 | `.github/workflows/doc-guard.yml` |

둘이 하는 일은 같다 — 기준 폴더를 찾고, 엔진을 부르고, 종료코드로 분기한다. 끝만 다르다.
훅은 저장을 막고 Actions 는 job 을 실패시키며 PR 에 결과를 남긴다.

오피스 문서(docx·xlsx·pptx)는 훅으로 잡을 수 없다. 팀원이 엑셀이나 파워포인트에서 작업해
폴더에 넣으므로 Claude 를 거치지 않아 훅이 불리지 않는다. 그쪽은 Actions 가 맡는다.

## 개발

```bash
uv sync
uv run pytest
uv run python checker/tests/make_fixtures.py   # 픽스처 생성
```

픽스처는 커밋하지 않는다. docx·xlsx·pptx 는 바이너리라 리뷰에서 diff 를 볼 수 없고,
"이 픽스처가 정말 의도한 위반을 담고 있나" 를 아무도 확인할 수 없다. 생성 스크립트로
두면 무엇이 들어 있는지가 코드로 읽히고 고칠 때 diff 가 남는다.
