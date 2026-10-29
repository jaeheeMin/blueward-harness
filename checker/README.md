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
    req_cross_reference.py  SRS 상세 절이 다른 REQ·DEV 번호를 말하면 관계 줄을 요구 (md, #261)
    md_table.py     md 절 아래 표의 열 이름·열별 허용 값·값 패턴 (Spec `## 사용 객체`, #287).
                    절 제목·열·값은 규칙 yaml 의 데이터이고 절이 없으면 통과(`필수: true` 로 바꿈).
                    `조건_필수`(엔진 v0.10.85 이상)는 다른 열이 어떤 값(`""` 는 빈 칸)일 때 이 열을 채우게 한다
                    (Spec `## 권한` 의 비고, #361)
    form_columns.py 원본 md(SRS, Spec `## 양식 항목`)의 열·소제목이 양식 지도 밖이면 거절 (#316)
  ooxml.py          오피스 파일의 본문이 아닌 자리를 읽는다
  cleaner.py        흔적을 걷어낸 새 파일을 만든다 (사람이 직접 부른다)
  ssot_approval.py  SRS(docs/ssot/) 변경 PR 의 승인 여부를 판정한다(#49).
                    Actions(`scripts/ssot_approval.py` 가 감싼다)와 harness
                    훅(`uvx` 로 `python -m checker.ssot_approval` 을 부른다)이
                    같은 판정 로직을 쓴다
  code_rules.py     공통 개발 규칙 CR-001(한글 이름), CR-002(반복문 안 DB
                    조회), CR-003, CR-007, CR-009(권한 전부 허용, 경고)를
                    코드(ABAP, JS/TS, CDS, BDEF)에서 검사한다(#54,
                    #72, #361). BDEF 는 반복문이 없어 CR-001 만 적용한다. 문서
                    검사(engine.py)와 관할이 다르다 — 기준 폴더(`templates/`
                    와 `rules/` 를 함께 가진 폴더)를 요구하지 않고 모듈
                    하나에 CLI 까지 담는다.
                    `pre_write_guard.py` 훅과 `scripts/check_changed.py` 가
                    같은 함수(`build_report`)를 쓴다
  code_checks.yaml  code_rules.py 의 설정. 언어별 확장자와, 그 언어에 어느
                    CR 을 적용할지, 그 CR 이 위반(`violation`)인지 경고(`warn`)인지(`level`)가 데이터로 있다
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

## `req_cross_reference` — 한 개발이 REQ 둘로 쪼개지는 것을 막는다(#261)

SRS 요구사항 상세 절(`### REQ-n` 제목부터 다음 `##`·`###` 전까지)이 다른 번호(`REQ-m`, `DEV-m`, m≠n)를
말하면, 같은 절에 `관계: 별개 — <이유>` 줄이 있어야 통과한다. 자기 번호는 세지 않고, 번호 바로 앞에
`제외_패턴`(기본 `옛\s*$`, 즉 `옛 REQ-003`)이 붙은 옛 표기와 코드 펜스 안, 상세 절 밖(범위·요구사항 표 등)의
언급은 보지 않는다. 위반 메시지는 어느 REQ 가 어떤 번호를 말했는지와 할 일(같은 개발이면 그 REQ 의 범위를
넓히고, 별개면 관계 줄)을 알려 준다.

관계 줄은 `### REQ-n` 제목 아래, 첫 `####` 소제목 앞에 둔다. `export.py` 는 `####` 소제목 아래 본문만 엑셀
칸으로 읽고 그 앞의 줄은 읽지 않으므로 산출과 겹치지 않는다(`tests/test_req_cross_reference.py` 가 보장).
소제목 아래의 관계 줄은 엑셀 칸으로 섞여 나가므로 인정하지 않는다. 인용 블록(`> 관계: …`)도 인정하지 않는다 —
관계 줄은 인용·소제목 아래가 아니라 제목 바로 아래 일반 줄이다. 이유가 비어 있으면(`관계:` 만 있거나 구분
기호뿐) 관계 줄이 없는 것과 같다. `별개 —` 는 권장 표기일 뿐이고, 접두어 `관계:` 뒤에 이유가 있으면 통과한다.

상세 절은 `##` 나 `#` 제목에서도 닫히고, 코드 펜스는 ``` 와 `~~~` 를 모두 인식한다. 번호는 ASCII 영숫자
경계로 찾으므로 `REQ-001의` 처럼 조사가 붙어도 잡히고 `XREQ-001`·`REQ-0012` 는 `REQ-001` 로 보지 않는다.

**배포 순서.** 이 규칙 종류는 엔진이 배포된 뒤에만 Project Repository `rules/ssot.yaml` 에 켠다. 배포는
main 병합이 아니라 태그 기준이다 — 병합 뒤 `release-tag` 가 엔진 판 태그 `v{version}` 과 `stable` 을 옮겨야
(Actions 의 caller 는 `@stable`, 팀원 PC 훅은 `v{version}`) 그 엔진이 퍼진다. `git ls-remote --tags origin` 으로
`stable` 이 새 커밋을 가리키는지 확인한 뒤 켠다. 먼저 켜면 엔진이 `'req_cross_reference' 는 모르는 규칙 종류다` 라는 `config_error` JSON 을 내고
종료코드 2(검사 불능)로 끝난다 — 통과도 위반도 아니다.

규칙 파일에서 켜고 값은 데이터로 둔다(스켈레톤 `rules/ssot.yaml`).

```yaml
  - 종류: req_cross_reference
    관계_접두어: "관계:"      # 생략하면 이 값
    제외_패턴: ['옛\s*$']     # 번호 앞 문맥에 이 정규식이 걸리면 건너뜀. 생략하면 이 값
```

## `form_columns` — 양식 밖 열·소제목이 원본에 들어오지 못하게 한다(#316)

산출물은 고객사 양식(`templates/forms/<양식>.yaml`)을 따른다. 양식 지도에 없는 열이 원본 md 에 들어오면 엑셀로 갈
자리가 없는데, 이 규칙이 없을 땐 srs·spec 스킬 문서에만 적혀 있어 저장(훅)·PR 이 통과시켰다. 이제 훅(저장)과
PR(doc-guard)이 같은 규칙으로 막고, 산출(`export.py`)은 같은 목록(`srs_allowed`·`srs_offenders`·`spec_offenders`)으로 멈춘다.

- `원본: SRS` — `docs/ssot/SRS.md` 의 `## 요구사항` 표 머리글과 `#### <소제목>` 을 본다. 허용 표 열은 `ID` + 지도
  `열` + 지도 `md_전용` + 엔진 기본 `다음 단계`, 허용 소제목은 지도 `열`(번호 열 제외) + md 전용이다. 지도 열이 표에
  빠진 것은 허용한다(#243). 이름은 export 와 같은 정규화(`export.norm`)로 비교한다. `원본: SRS` 지도가 없는 저장소는
  SRS 틀(규칙 파일의 `템플릿`)의 요구사항 표 열 + `다음 단계` 가 허용 열이고 소제목은 틀의 열 + `기본_소제목`(규칙 데이터)이다.
- `원본: 작업본` — Spec 의 `## 양식 항목` 아래 `### <양식> · <시트>` 의 양식(지도 파일 유무)·시트·칸·`#### <표·서술>`·표 열을 본다.
  `## 양식 항목` 절이 없으면 통과한다.
- 지도는 규칙 파일 폴더 기준 `지도_폴더`(기본 `../templates/forms`)에서 읽는다(로더가 params 에 `_rules_dir` 를 넣어 준다 —
  훅은 문서만 임시 폴더로 옮기므로 문서 경로로는 기준 폴더를 알 수 없다). 지도를 못 읽거나, 원본이 SRS 인 지도가 둘 이상인데
  `양식:` 으로 고르지 않았으면 ConfigError(종료코드 2, 검사 불능)다. 통과도 위반도 아니다.
- 메시지는 `양식 밖 열: X. 허용(양식 지도 Backlog): …. 다음: 양식 지도에 있는 열 이름으로 고치거나, 지도에 정말 필요한 열이면 양식 지도를 먼저 고친다.` 꼴이다.

**배포 순서.** 새 규칙 종류라 `req_cross_reference` 와 같다. 엔진 태그(이 규칙이 든 `v{version}`, `stable`)가 퍼진 뒤에 각
Project Repository `rules/ssot.yaml`·`rules/spec.yaml` 에 켠다. 먼저 켜면 `'form_columns' 는 모르는 규칙 종류다`(검사 불능).

```yaml
  - 종류: form_columns          # rules/ssot.yaml
    원본: SRS
    기본_소제목: [설명, 완료 조건]   # 지도가 없는 저장소의 상세 절 소제목
  - 종류: form_columns          # rules/spec.yaml
    원본: 작업본
```

## `pairing` — SRS·Spec·원장 번호 짝 맞추기(#284)

규칙 종류가 아니라 저장소 전체를 보는 별도 검사다(`checker/pairing.py`). 개발 번호는 SRS 요구사항 표
(`ID`·`다음 단계`·`Development RICEFW ID`), `docs/spec/DEV-n-*.md`(파일명과 `## 근거 요구사항`), 진행 원장
`audit/ledger/*.md` 의 `## 개발 건` 표에 나뉘어 적히므로 셋을 숫자로 정규화해(`REQ-3` == `DEV-003`) 맞춰 본다.
`scripts/check_changed.py` 가 바뀐 파일에 SRS·`docs/spec/`·`audit/ledger/` 가 있을 때만 돌려 리포트의 `pairing`
키로 합치고, `audit/ledger/` 가 없는 저장소는 대상이 아니다.

- 위반(종료코드 1): `개발` REQ 의 RICEFW ID 가 `DEV-<같은 번호>` 가 아님(열이 없거나 값이 비면 건너뜀), `설정`·`미정`
  인데 RICEFW ID 가 있음, 같은 DEV 가 원장 여러 줄, 원장 Spec 칸 링크 대상 파일 없음 또는 다른 번호 파일, Spec 의
  근거 REQ 번호 ≠ 파일명 DEV 번호.
- 경고(통과 유지): 진행 중인 `개발` REQ 의 원장 줄·Spec 없음, `설정` REQ 의 원장 줄 없음, `개발` 인데 원장 Spec 칸이
  `설정`, SRS 에 없는 원장 DEV·Spec. Status 가 On Hold·Dropped·Duplicate 면 대조하지 않는다. 원장 Spec 칸 `-` 는 "작성 전".
- 검사 불능(종료코드 2): 읽지 못하는 파일, SRS `## 요구사항` 절이나 표의 `ID` 열이 없음, 원장 `## 개발 건` 표 머리가
  없음. SRS 파일이 없거나 요구사항 표가 아직 없으면 SRS 대조만 건너뛴다.
- `다음 단계` 열이 없는 SRS(Backlog 양식)는 spec 스킬과 같이 모든 REQ 를 `개발` 로 보고 대조하며 참고에 한 줄을 남긴다.
  Spec 의 근거 REQ 는 `## 근거 요구사항` 첫 문단에서만 읽고 `REQ-001~013` 같은 범위 표기는 번호로 세지 않는다.
  원장 Spec 칸의 외부 링크(`https://…`)는 파일 검사 없이 참고로만 남긴다.

## `overlap` — Spec 간 SAP 객체 겹침 경고(#292)

규칙 종류가 아닌 별도 검사다(`checker/overlap.py`). `docs/spec/*.md` 마다 `## 사용 객체` 표(`종류 | 이름 | 작업 | 비고`)를
읽어, 작업이 `생성`·`수정` 인 행의 `(종류, 이름 대문자)` 가 Spec 둘 이상에 나오면 경고한다. `참조` 행은 비교하지 않는다.
`scripts/check_changed.py` 가 바뀐 파일에 `docs/spec/` 가 있을 때 돌려 리포트의 `overlap` 키로 합친다.

- 경고만 한다(통과 유지, 위반 없음). 코멘트의 "객체 겹침" 절에 표로 나온다. 목적은 한 개발이 DEV 둘로 쪼개진 것은
  아닌지 확인하게 하는 것이다(#503).
- 이 PR 이 바꾼 Spec(`check_overlap(root, changed_specs)`, `check_changed.py` 가 바뀐 파일 중 `docs/spec/` 경로를 넘김)이
  낀 겹침만 경고한다. 바뀐 Spec 이 안 낀 기존 겹침은 `unrelated` 개수로만 남는다. 목록이 없으면(None) 전부 본다.
- 공용 객체 종류는 겹쳐도 경고하지 않고 `shared` 개수와 `shared_kinds` 로 남긴다. 종류는
  `rules/cross-checks/shared-objects.yaml` 의 `공용_종류`(문자열 목록)로 정한다. 파일이나 키가 없으면 기본값
  `["Message Class"]`, `[]` 이면 제외 없음. 종류 비교는 앞뒤 공백·대소문자를 무시한다. 모르는 키, 목록이 아닌 값,
  문자열이 아닌 항목, 깨진 YAML 은 검사 불능(종료코드 2, 사유에 파일 경로). 이 폴더는 규칙 로더가 읽지 않는다.
- 표 절이 없는 Spec 은 비교에서 빼고 "표 없음 n건" 으로만 적는다. 이름이 비었거나 영문자(또는 `/`)로 시작하지 않는 행
  (`미정`, `-`)도 빼고 "이름 미정 n건" 으로 적는다. 대상은 `DEV-` 로 시작하는 Spec 만이다.
- 검사 불능(종료코드 2): Spec 을 읽지 못함, 절은 있는데 표가 없음, 표 머리·칸 수·작업 값이 틀려 읽을 수 없음.
- `docs/spec/` 가 없는 저장소는 대상이 아니다(skipped).

## `version_overlap` — 열린 PR 끼리 문서 판 번호 겹침 경고(#315)

규칙 종류가 아닌 별도 검사다(`checker/version_overlap.py`). 이 PR 이 **추가한** `_v<판>` 산출 파일(`…_v0.3.xlsx` 등,
`templates/` 제외)의 경로가 다른 열린 PR 의 추가 파일과 같거나, 이 PR 이 `docs/ssot/SRS.md` 의 `버전:` 을 base 와 다른
값으로 바꿨는데 다른 열린 PR 도 같은 값으로 바꿨으면 경고한다. 이미 있던 파일을 고친 것은 대상이 아니다.

- 엔진은 네트워크를 쓰지 않는다. 워크플로가 `scripts/fetch_open_prs.py` 로 열린 PR 의 파일 목록과(SRS 를 바꾼 PR 만)
  SRS 의 head·base `버전:` 을 GitHub API 로 읽어 `open-prs.json` 에 저장하고, `scripts/check_changed.py` 가 환경변수
  `DOC_GUARD_OPEN_PRS`(그 경로)와 `DOC_GUARD_PR_NUMBER` 로 받아 리포트 키 `version_overlap` 에 합친다. 두 환경변수가 없으면
  (push, 로컬 훅) 대상이 아니다. 이 PR 이 판 번호를 건드리지 않으면 다른 PR 을 읽지 않는다(`not_needed`).
- 경고만 한다(통과 유지). 코멘트의 "판 번호 겹침" 절에 "먼저 병합되는 쪽이 v0.3 을 갖고, 다른 쪽은 sync 뒤 0.4 로 다시
  산출해야 합니다" 로 나온다.
- 검사 불능(종료코드 2): 열린 PR 목록을 못 읽음(권한·네트워크·API 오류·너무 많음), `open-prs.json` 이 없거나 깨짐, 이 PR 이
  목록에 없음, 겹침 판정에 필요한 SRS 버전을 못 읽음(바뀐 SRS 의 head 가 404 이거나 `버전:` 줄이 없음. base 에 SRS 가
  아직 없는 것만 정상), 120초 시간 예산 초과. 이 검사 불능은 `read_failure` 표시가 붙어 "규칙·설정 문제" 가 아니라 "다시
  돌리십시오(Re-run)" 로 안내하고, 문서 위반과 함께 나와도 위반 표는 그대로다(종료코드는 2).
- 이 PR 과 base 브랜치가 다른 열린 PR 은 비교에서 빼고, 초안 PR 은 넣는다. 다른 PR 제목은 백틱으로 감싸 60자로 자른다.
- 스위치 `판_겹침` 으로 끈다.

### 교차 검사 스위치

`pairing`·`overlap`·`version_overlap` 은 Project Repository 의 `rules/cross-checks/switches.yaml` 로 각각 끈다(`checker/cross_switches.py`).

```yaml
번호_짝: true      # false 면 번호 짝 검사를 돌리지 않는다
객체_겹침: true    # false 면 객체 겹침 검사를 돌리지 않는다
판_겹침: true      # false 면 열린 PR 끼리 판 번호 겹침 검사를 돌리지 않는다
```

꺼져 있으면 리포트에 `{"status": "disabled"}` 를 싣고 코멘트에 "꺼져 있음" 한 줄이 남는다(종료코드 0). 파일이나 키가 없으면 켠다. 모르는 키나 불린이 아닌 값은 검사 불능(종료코드 2, 리포트 키 `cross_checks`)이다. 엔진 로더가
`rules/` 최상위 `*.yaml` 을 모두 문서 규칙으로 읽기 때문에 하위 폴더 `cross-checks/` 에 둔다.

## `risk_gate` 의 `split_hint` — SRS 쪼개짐 의심을 승인자에게 보여 준다(#278)

`req_cross_reference` 는 문서 규칙이라 PR 화면에 단서를 남기지 않는다. risk-gate 의 `split_hint` 기준이
이를 보완한다. SRS(`docs/ssot/SRS.md`) 요구사항 표에 base 에 없던 REQ 가 생겼으면, 새 REQ 마다 아래를 본다.

- (a) head 의 그 REQ 상세 절이 다른 REQ·DEV 번호를 말한다(`req_cross_reference` 의 `parse_sections`·`collect_mentions`
  를 그대로 쓴다. 관계 줄이 있어도 근거로 보여 준다).
- (b) 같은 PR 에서 base 범위 절의 "하지 않는 것" 목록(머리말 `SCOPE_EXCLUDED_MARKER` 줄과 그 아래로 더 들여쓴 줄)에서
  항목이 지워지거나 바뀌었다. 항목 단위로 비교한다 — 한 줄 형태(`- 하지 않는 것: A, B`)는 `,`·`、`·`;`·` · `
  (괄호 밖)로 쪼개고, 들여쓴 목록은 줄마다 항목이다. 공백·끝 문장부호를 정리하고 대소문자를 무시한다. base 항목 중
  head 에 없는 것만 근거이고(사유에는 그 항목만 짧게), 덧붙인 항목이나 문장부호만 고친 것은 근거가 아니다.
- (c) 새 제목이 base 의 기존 REQ 제목을 포함하거나 그 반대다(공백·대소문자 정리, 양쪽 4자 이상 — `reserve_number.py` 와 같은 기준).

하나라도 걸리면 "SRS 새 요구사항 REQ-n 이 기존 요구사항을 넓힌 것일 수 있음(확장 의심, 승인자가 확인)" 사유에 걸린 근거를
붙인다. 막지 않는다 — `high_risk_paths` 에 `docs/ssot/` 가 있으면 SRS 변경은 이미 위험 경로라 승인 대상이고, 사유
문구만 늘어난다(없는 설정이면 이 기준이 새 사유를 만든다). 새 REQ 가 없거나 근거가 없으면 사유가 없다. head 에서
사라진 base REQ 번호와 제목이 같은 새 번호는 번호만 바뀐 것이라 새 REQ 로 보지 않는다.

base 는 기준 브랜치의 지금 끝이 아니라 PR 이 갈라진 지점(compare API 의 `merge_base_commit`)이다 — main 이 앞서가도
PR 이 건드리지 않은 줄이 지워진 것으로 잡히지 않는다. 병합 뒤 감지(`config_ref` = 병합 직전 main)는 그 ref 와 PR head 의
merge-base 를 쓴다. 갈라진 지점을 못 구하거나, SRS 의 patch 가 없어(너무 큰 diff) 읽지 못하거나, base·head SRS 를
못 읽거나(없음·비어 옴·디코딩 실패·1MB 초과·디렉터리 응답) head 에 요구사항 표가 안 보이면 통과도 위반도 아닌
"검사 불능" 사유로 낸다. (a) 는 관계 줄 접두어·제외 패턴의 기본값(`DEFAULT_PREFIX`, `DEFAULT_EXCLUDE`)을 쓴다 — 고객사가
`rules/ssot.yaml` 에서 바꿨다면 `req_cross_reference` 와 어긋날 수 있다. `.github/risk-gate.yaml` 의 `srs_split_hint: false` 로 끈다(기본 켬).
Project Repository 는 엔진이 배포된 뒤(`stable` 태그가 옮겨진 뒤) 이 키를 쓸 수 있다 — 모르는 키는 설정 오류다.

## CR-009 와 `risk_gate` 의 `write_auth` — 데이터를 바꾸는 앱의 권한 검사(#361)

RAP behavior pool 의 `FOR GLOBAL AUTHORIZATION`/`FOR INSTANCE AUTHORIZATION` 메서드가 `auth-allowed` 만 대입하고(`auth-unauthorized`
없음) 같은 파일에 `AUTHORITY-CHECK` 가 없으면 `code_rules.py` 가 CR-009 로 경고한다(`_scan_abap_cr009`, 마스킹된 소스를 봐서 주석·
문자열 속 AUTHORITY-CHECK 는 세지 않는다). 심각도는 `code_checks.yaml` 규칙 항목의 `level` 이 데이터로 정한다 — `violation`(기본,
종료코드 1) 또는 `warn`(리포트에는 나오지만 종료코드·`status` 를 바꾸지 않는다). CR-009 는 `warn` 이다. 발견마다 `level` 이 붙고
요약에 `warnings` 가 더해진다. 그 밖의 `level` 값은 설정 오류라 그 파일이 `error`(검사 불능, 종료코드 2)다. `level` 은 같은
`code_checks.yaml` 과 같은 엔진 판에서만 읽는다 — 옛 엔진(0.10.84 이하)은 `level` 키를 보지 않고 CR-009 도 모르므로, 새 yaml 은
새 엔진과 함께 배포되는 이 저장소 파일이라 어긋나지 않는다. 훅은 `warn` 발견으로 막지 않고 `allow_with_notice`(`additionalContext`)로 경고를 알려 주며(위반이 있어 막을 때는 거절 사유에 같이 붙인다),
PR 코멘트(`scripts/render_report.py`)는 위반과 따로 "경고" 절에 나열한다. CR-009 는 권한 메서드의 `auth-allowed` 대입만 있거나 본문이 빈 경우를
그 클래스 구현 범위의 `AUTHORITY-CHECK` 유무로 가른다(`METHODS:` 체인 선언 포함).

risk-gate 의 `write_auth` 기준은 PR 이 바꾼(삭제 제외) `.abap` 파일의 head 내용에 CR-009 경고(예외 처리된 것 제외)가 있으면
"쓰기 앱인데 권한 검사 없음: <파일>" 사유를 낸다. 설정 키가 없다 — 게이트가 켜져 있으면(`.github/risk-gate.yaml` 이 있으면) 항상 본다.
옛 설정 파일이 모르는 키 때문에 검사 불능이 되지 않게 하려는 것이다. 파일을 못 읽거나(없음·비어 옴·1MB 초과) 코드 검사 설정이 잘못되면
통과로 보지 않고 "확인하지 못함" 사유를 낸다. `decide_pr` 의 사유 목록을 그대로 쓰므로 병합 뒤 감지(`after-merge`)와 알림 이슈에도
같은 줄이 찍힌다. `precheck-pr` 은 `PRECHECK_CRITERIA` 밖이라 이 기준을 보지 않는다.

`write_auth` 는 head 내용만 보므로 같은 PR 에서 예외 주석을 넣으면 사유가 사라진다. 그래서 `allow` 기준(#545)이 따로
PR 이 바꾼 `.abap` 파일의 diff 추가 줄에 `harness:allow CR-0NN` 이 있으면 "코드 예외 주석(harness:allow CR-0NN)을 넣거나 바꿈: <파일>"
사유를 낸다. base 와 같은 주석과 지운 주석은 사유가 아니고, 이유만 바꾸거나 옮긴 주석은 사유다. patch 가 없을 만큼 큰 diff 면
"확인하지 못함" 사유를 낸다. 이 기준도 설정 키가 없다.

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
| GitHub Actions | 커밋해서 올릴 때 | 모든 형식 | `.github/workflows/pr-checks.yml`(PR)·`main-checks.yml`(main push)의 doc-guard 단계 |

둘이 하는 일은 같다 — 기준 폴더를 찾고, 엔진을 부르고, 종료코드로 분기한다. 끝만 다르다.
훅은 저장을 막고 Actions 는 job 을 실패시키며 PR 에 결과를 남긴다.

오피스 문서(docx·xlsx·pptx)는 훅으로 잡을 수 없다. 팀원이 엑셀이나 파워포인트에서 작업해
폴더에 넣으므로 Claude 를 거치지 않아 훅이 불리지 않는다. 그쪽은 Actions 가 맡는다.

## 양식 파일 산출(`checker.export`)

검사가 아니라 쓰기 도구다. 작업본 md 의 `## 양식 항목` 을 양식 지도
(`templates/forms/<양식>.yaml`, 형식은 `plugins/harness/skills/spec/form-map.md`)가
가리키는 xlsx 템플릿 복사본에 채워 `산출.폴더` 에 쓴다(#192).

```bash
python -m checker.export --spec docs/spec/DEV-001-요약.md --root <Project Repository 루트> [--form <양식>]
```

stdout 에 JSON 한 줄 `{"status": "ok|rejected|error", "files": [...], "problems": [{"form", "sheet", "item", "reason"}], "warnings": [...], "next": "..."}`
을 낸다. 종료코드는 0 산출함, 1 거부(필수 `미정`·`최대_행` 초과·짝 행 수 불일치·같은 이름 파일 존재
등, 아무것도 쓰지 않음), 2 읽지 못함(작업본·지도·템플릿 못 읽음, 지도에 없는 항목, 경로가 루트 밖,
예상하지 못한 예외)이다. 산출물은 임시 파일로 먼저 쓴 뒤 한꺼번에 최종 이름으로 바꾸며, 실패하면
이번 실행이 만든 파일을 모두 지운다. `warnings` 는 지운 제어 문자와, 해당 없음 시트에 남은 템플릿
샘플(그림·셀)을 알린다.

쓰기는 openpyxl 을 쓰지 않는다. load→save 는 도형·그림·인쇄 설정·calcChain 을 잃기 때문에, zip 수준에서
바뀐 시트 XML 만 고치고 나머지 항목은 같은 순서로 그대로 복사한다. 문자열은 `inlineStr`, 셀 서식은 유지한다.
수식이 있는 통합문서는 `fullCalcOnLoad` 를 켠다.

화면 캡처(#348, `checker/screen_capture.py`). 지도 시트의 `화면:` 항목에 `캡처: {영역, 설명}` 이 있으면 작업본 `#### <화면> 캡처`(그림 한 줄 `![…](저장소 루트 기준 경로.png)` + `| 번호 | 설명 |` 표)의
PNG 를 영역에 비율을 지켜 맞춰 넣고(늘리지 않는다, 원본의 `MIN_SCALE`=50% 미만으로 줄여야 하면 멈춤) 번호별 설명을 `설명` 범위 첫 열에 `① 설명` 으로 쓴다.
drawing·media·관계·`[Content_Types].xml` 은 남은 견본 검사 뒤 zip 조립 단계에서 새 번호로 붙인다(openpyxl 을 쓰지 않고, PNG 크기는 IHDR 만 읽는다). 그림 파일이 없거나
PNG 가 아니거나, 파일 이름의 `_v<판>` 이 없거나 산출 파일 이름의 판과 다르거나, 같은 화면의 `그림` 영역과 겹치거나, 설명 행이 모자라거나, 시트에 이미 drawing 이 있으면 거부(1)하고
형식 위반(그림 둘 이상·png 아님·번호 불연속 등)은 `form_columns` 와 같은 `spec_offenders` 로 "양식 밖"(저장 훅·PR) 이다. 크기 계산(열 너비 7px/문자, 96dpi)은 어림값이다.

SRS 원본 산출(#228). 지도 표에 `원본: SRS` 가 있으면 작업본이 아니라 `docs/ssot/SRS.md` 의 `## 요구사항` 표
(요구사항 1건 = 1줄)와 `### REQ-xxx` 상세 절을 읽어 시트의 여러 행에 쓴다(`--form <지도>` 필요, `--spec` 은
SRS.md). `REQ-003` 은 숫자 3 으로 쓰고, 지도에 없는 열은 `md_전용` 에 적은 것만 허용한다(`ID` 와 `다음 단계` 는 지도에 안 적어도 되는 엔진 기본
md 전용 열이다 — 엑셀로 쓰지 않고 값(`개발`/`설정`/`미정`)도 export 가 검사하지 않는다, #255. 지도 `열` 에 같은 이름이
있어도 엑셀로 쓰지 않으므로, 고객 양식에 `다음 단계` 열이 생기면 SRS 쪽 열 이름을 바꿔야 한다). 표 값은 템플릿 데이터
유효성(표준·x14 확장·정의 이름·다른 시트 범위)에서 읽은 드롭다운 허용 값과 대조해, 목록 밖이면 파일은 쓰되
종료코드 3(`status: warning`, `warnings[].type == "dropdown"` 에 행·열·값·허용 값)으로 알린다. 허용 값을 읽지 못한
칸(`dropdown-unchecked`)도 종료코드 3 이고 `next` 가 "검사하지 못한 열" 로 구분한다. 목록이 실제로 비어 있으면
`dropdown-empty` 알림만 내고 종료코드는 그대로다. 엑셀이 목록 밖 값을 받는 유효성(오류 메시지 꺼짐·정보/경고 스타일)은
검사하지 않는다. `--check` 는 파일을 쓰지 않고 같은 보고만 낸다.
`--root R --form <지도> --list-values` 는 지도 열 이름별 허용 값을 JSON 으로 낸다. 쓰는 행의 `hidden` 은
풀고 고정 줄 높이도 지우고, 자동 필터(`autoFilter`·`_xlnm._FilterDatabase`)는 쓴 행이 그 범위를 넘을 때만 늘린다.

## 개발

```bash
uv sync
uv run pytest
uv run python checker/tests/make_fixtures.py   # 픽스처 생성
```

픽스처는 커밋하지 않는다. docx·xlsx·pptx 는 바이너리라 리뷰에서 diff 를 볼 수 없고,
"이 픽스처가 정말 의도한 위반을 담고 있나" 를 아무도 확인할 수 없다. 생성 스크립트로
두면 무엇이 들어 있는지가 코드로 읽히고 고칠 때 diff 가 남는다.
