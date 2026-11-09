---
name: unittest
description: LoB 별 단위테스트 List(고객 양식 xlsx) 작업본을 쓰고 산출할 때 쓴다. SAP Best Practices 공식 테스트 스크립트(스코프 아이템별)를 근거로 Test Case 와 단계 초안을 만들고, 컨설턴트가 고친 작업본을 고객 양식 xlsx 로 산출한다. 사용자가 "단위테스트 만들어줘", "단위테스트 List", "테스트 시나리오 만들어줘", "LoB 테스트 케이스", "단위테스트 엑셀로 뽑아줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — 개발 건(DEV) 하나의 테스트는 이 스킬이 하지 않는다(LoB 단위 시나리오만). 테스트 실행·결과 입력, 담당자·일정·상태 같은 사람 칸 채우기도 하지 않는다. 개발 Spec 이나 사용자 매뉴얼이면 spec·manual 스킬로.
---

# /harness:unittest

`docs/unittest/` 의 단위테스트 List 작업본(md)에 LoB(업무 영역) 별 Test Case 와 단계를 쓰고, 고객 양식 xlsx 로 산출하는 입구다. 작업본은
**LoB 마다 파일 하나**(`docs/unittest/<LoB>.md`)이고 개발 건(DEV) 단위가 아니다. 양식은 Project Repository 의 `templates/` 에 있고 양식 지도는
`templates/forms/단위테스트 List.yaml` 이다. 시트·표·열 이름은 항상 지도에서 읽는다 — 이 스킬에 양식 고유 글자를 지어 적지 않는다(아래 예의
이름은 public-cloud 지도 기준이고, 지도가 다르면 지도를 따른다). `<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는 경로다.

**사람 정보는 이 저장소에 두지 않는다.** 담당자(KU·컨설턴트·연계 담당자)·Test 담당자(PI)·예정일·완료일·상태·Test 결과·이슈·처리방안·Status,
Document Control 의 작성자·결재(승인)는 사람이 엑셀에서 채우는 칸이라 작업본에 두지 않고 비워 산출한다. 사용자가 이름이나 일정을 알려 줘도
작업본에 적지 않는다. 작업본에 들어가는 것은 시나리오(계층·Test Case·단계)뿐이다. 연계 모듈/타 시스템 칸에는 **시스템 이름만** 적는다(사람 아님).

## SAP 에 관한 근거

SAP 에 관한 판단은 SAP 공식 문서(help.sap.com, ABAP Keyword Documentation, SAP Best Practices Explorer)와 실제 테넌트 조회만 근거로 한다. 블로그와
기억은 근거가 아니다. 이 스킬의 시나리오 초안은 **SAP Best Practices 의 스코프 아이템별 공식 테스트 스크립트**에서만 만든다. 공식 문서에서 확인하지
못한 단계·앱·입력·출력은 지어내지 않는다. 그 칸은 **비워 두고** 작업본 `근거` 열에 `확인 필요: <무엇>` 으로 적는다. 문서를 읽지 못했으면
(접근 불가, 로그인 필요 등) 읽지 못했다고 알린다 — 통과도 근거 없음도 아니라 확인 불능이다.

## 작업본 형식

위치와 이름: `docs/unittest/<LoB>.md` (예: `docs/unittest/Production.md`). 폴더는 지도 `산출.폴더` 이고, 산출 xlsx
`BW_단위테스트 List_<LoB>_v{버전}.xlsx` 와 같은 폴더에 나란히 놓인다. 파일 이름이 산출 xlsx 이름에 들어가므로 `\ / : * ? " < > |` 는 쓸 수 없다
(`rules/unittest.yaml` 이 강제한다).

```markdown
# 단위테스트 List Production

버전: 0.1
LoB: Production

## 양식 항목

### 단위테스트 List · Document Control

#### 개정 이력

| Version | 개정일자 | 개정사유 |
|---|---|---|
| v0.1 | 2026-11-09 | 초안작성 |

### 단위테스트 List · 단위테스트 List

#### 단위테스트 List

| Mega No | Mega Name | Process No | Process Name | Sub Process No | Sub Process Name | Task No | Task Name | Task Variant No | Task Variant Name | App(T-code) | Test Case ID | Test Case 명 | Description | 연계 모듈/타 시스템 | 근거 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <값> | <값> | <값> | <값> | <값> | <값> | <값> | <값> | <값> | <값> | <값> | <ID> | <값> | <값> | | <스코프 아이템 ID · 문서 출처> |

### 단위테스트 List · TC.견본 · <ID>

| 항목 | 값 |
|---|---|
| Test Case 명 | <값> |

#### 단계

| 모듈 | 순서 | 수행업무 (Step) | App(T-Code) | Input | Output | 주요 점검 Point | Test 대상 여부 | 근거 |
|---|---|---|---|---|---|---|---|---|
| <모듈> | 01 | <값> | <값> | <값> | <값> | <값> | Yes | <문서 출처 또는 확인 필요: …> |
```

(시트·표·열 이름은 **지도에서 읽은 것**이다. 지도에 없는 시트·표·열은 쓰지 않는다 — 저장할 때(훅)와 PR(doc-guard `form_columns`)이 "양식 밖" 으로
거절하고 산출도 멈춘다. `<값>` 자리는 실제 값으로 채운다.)

- **머리.** 첫 `##` 앞의 `버전: 0.1`·`LoB: <LoB>` 줄이 산출 파일명의 `v0.1`·`<LoB>` 가 된다. 처음은 0.1, 올릴 때 0.1 씩이다. 두 줄 중 하나가 없거나 `버전` 이
  `x.y` 모양이 아니면 산출이 거부한다.
- **Document Control.** `개정 이력` 표의 `Version`(`v0.1`)·`개정일자`(`YYYY-MM-DD`)·`개정사유` 만 쓴다. 작성자·결재(승인)는 양식에서 비워 둔다. 판을 올릴 때
  한 줄 더한다.
- **단위테스트 List.** 행 하나가 Test Case 하나(Task 레벨이면 Task 행, Task Variant 레벨이면 Variant 행)다. 계층 칸(Mega~Task Variant)은 **처음 한 번만 적고
  이어지는 줄은 비운다** — 양식 1행의 `SUBTOTAL` 이 비어 있지 않은 칸을 세어 Task·Task Variant·Test Case 개수로 쓰기 때문이다. 번호 체계는 이미 있는 작업본·사용자가
  정한 것을 따른다. 정해진 것이 없으면 안을 보이고 확인받는다 — 지어내서 확정하지 않는다.
- **Test Case ID.** 양식의 체계는 `<모듈>.<NN>.<NN>.<NN>`(Task 레벨, 예 `FI.01.03.01`)이고 Task Variant 레벨이면 한 자리 더(`FI.01.03.02.02`)다. 모듈은 대문자
  2~3자, 번호는 두 자리다. 규칙(`ID_패턴`)이 이 형식과 다른 ID 를 거절한다. ID 는 그 계층 칸의 마지막 번호(Task 번호나 Task Variant 번호)와 같다.
- **Test Case 시트.** Test Case 마다 `### 단위테스트 List · TC.견본 · <ID>` 소절 하나이고, 산출하면 시트 이름이 `<ID>` 인 시트가 하나씩 만들어진다(엔진 #830, 지도
  시트 `반복`). 시트 이름은 31자 이하이고 `\ / ? * [ ] :` 를 쓸 수 없다. `모듈` 은 ID 의 첫 토큰이고 `순서` 는 `01` 부터 두 자리 글자다.
  `Test 대상 여부` 는 `Yes`/`No` 드롭다운이다. 단위테스트 List 표의 `Test Case ID` 마다 이 소절이 있어야 하고 그 반대도 같다 — **어느 검사도 이 짝을 보지 않으므로**
  산출하기 전에 사람이 챙긴다(아래 "산출").
- **`근거` 열.** List 표와 단계 표에 있는 작업본 전용 열이다(지도 `md_전용`). 엑셀에 쓰지 않는다. 스코프 아이템 ID·문서 이름·판·출처 위치, 확인하지 못한 것을 적는다.
- **사람 칸.** 위 열(담당자·일정·상태·Test 결과 등)은 작업본 표에 열 자체가 없다. 산출된 엑셀에서 사람이 채운다.

## 0단계: 브랜치 확인

작업본을 쓰기 전에, 지금 브랜치가 이번 단위테스트 작업에 맞는지 확인한다. 확인은 `<이 스킬의 base directory>/../start/SKILL.md` 의 "다른 스킬이 부르는 브랜치 확인"
을 그대로 따른다 — 미커밋 변경, main 이면 start 절차, 다른 작업 브랜치면 같은 일인지 판단·질문, 판정 불능이 거기 있다. start 를 따로 부르라고 하지 않는다.
이 스킬에서 정하는 것은 아래뿐이다.

- **이번 작업 설명**은 "단위테스트 List — <LoB> <요약>" 한 줄이다. 작업 내용(LoB, 스코프 아이템 범위)을 받은 뒤에 브랜치를 비교한다(그 전에는 읽기만 하고 파일을
  쓰지 않는다).
- **같은 일의 판단 기준.** 브랜치 이슈 제목·본문이 단위테스트 List 작업이고 같은 LoB 면 같은 일이다. 다른 LoB 거나 다른 일이면 묻는다.
- **main 이면 번호 없는 작업 이슈를 만든다.** start 절차를 `docs` 작업으로 수행한다 — 제목은 `단위테스트 List — <LoB> <요약>`, 브랜치는 `docs/{이슈번호}-…`.
  DEV 번호는 받지 않는다(LoB 단위 시나리오는 개발 건이 아니다).

`git rev-parse --show-toplevel` 로 Project Repository 루트를 확인한다.

## 시나리오 초안 (SAP Best Practices 근거)

1. **지도와 규칙을 읽는다.** `templates/forms/단위테스트 List.yaml` 의 시트·표·열 이름을 읽어 둔다.
   - 지도가 없으면 **멈추고** 지도가 없다고 알린다. 지도를 추측해 만들지 않는다(`<이 스킬의 base directory>/../spec/form-map.md`).
   - `rules/unittest.yaml`·`rules/unittest-output.yaml`·`templates/harness/unittest.md` 가 없으면 아래 "규칙 설치" 로 안내한다.
2. **작업본을 읽는다.** 있으면 읽고(`버전:`, `LoB:`, 기존 Test Case), 없으면 새 작업본이다 — 위 형식대로 만들고 `버전: 0.1`, `LoB: <LoB>` 로 시작한다. LoB 는 사용자가
   알려 준 이름이다.
3. **범위를 받는다.** 이 LoB 에서 테스트할 **스코프 아이템**(SAP Best Practices 의 Scope Item ID 와 이름) 목록은 사람이 알려 준다. 어떤 스코프 아이템이 프로젝트 범위인지는
   이 스킬이 추측하지 않는다. 범위 목록을 받은 문서(SOW·Fit-Gap 등)가 저장소에 있으면 그것을 읽는다.
4. **스코프 아이템마다 공식 테스트 스크립트를 찾는다.** SAP Best Practices Explorer(https://rapid.sap.com/bp/)의 그 스코프 아이템 문서 중 **테스트 스크립트**(Test Script)와
   `sap-docs` 스킬의 출처(help.sap.com 등 SAP 공식)만 쓴다. 사용자가 올려 준 공식 테스트 스크립트 파일(pdf·xlsx 등)이 있으면 그것을 읽는다.
   - 읽지 못했으면 그 스코프 아이템은 초안을 만들지 않고 "확인 불능(문서를 읽지 못함)" 으로 알린다. 기억이나 비슷한 다른 스코프 아이템으로 채우지 않는다.
5. **초안을 만든다.** 읽은 스크립트마다 아래처럼 옮긴다. 스크립트의 열 이름은 문서마다 다를 수 있으니 의미로 맞춘다. 문서에 없는 것은 비운다.

   | 작업본 | 공식 스크립트에서 |
   |---|---|
   | `Test Case 명`·`Description` | 스코프 아이템(또는 시나리오) 이름과 목적 |
   | 단계 `수행업무 (Step)` | 테스트 단계 이름과 수행 내용 |
   | 단계 `App(T-Code)` | 스크립트가 단계에서 쓴다고 밝힌 앱(Fiori 앱 이름·ID) 또는 T-code 그대로 |
   | 단계 `Input` | 단계에서 입력하는 값(테스트 데이터) |
   | 단계 `Output` | 단계의 기대 결과(생성되는 문서·상태) |
   | 단계 `주요 점검 Point` | 기대 결과 중 점검할 점 |
   | `Test 대상 여부` | 공식 스크립트에서 가져온 단계는 `Yes` 로 초안을 쓴다. 안 할 단계는 컨설턴트가 `No` 로 바꾼다 |
   | `연계 모듈/타 시스템` | 스크립트가 다른 모듈·시스템과의 연결을 밝힌 곳의 **이름만**. 없으면 비운다 |

   - 계층 칸(Mega~Task Variant) 번호·이름은 위 "작업본 형식" 의 규칙을 따른다. 스코프 아이템이 Task 인지 Variant 인지도 사람이 정한 체계를 따르고, 정해진 것이 없으면 묻는다.
   - `근거` 열에 `스코프 아이템 <ID> · <문서 이름·판> · <단계 번호나 위치>` 를 적는다. 출처 URL 이나 문서 이름을 못 적으면 그 행은 근거 없는 행이므로 만들지 않는다.
   - 확인하지 못한 단계·앱·입력·출력은 비우고 `근거` 에 `확인 필요: App`, `확인 필요: Input·Output` 처럼 적는다. 값을 짐작해 채우지 않는다.
6. **보이고 확인받는다.** 한 번에 Test Case 목록과 단계 초안을 보이고, 사용자(컨설턴트)가 확인·수정한 것만 작업본에 쓴다. 이미 있는 Test Case 의 단계를 다시 쓰기 전에 무엇이 바뀌는지 알린다.
7. 새 Test Case 마다 단위테스트 List 행과 `TC.견본` 소절을 **짝으로** 더한다. 시트 이름(ID)이 31자를 넘지 않는지 센다.

## 버전 올리기

이 작업본은 계속 고쳐지고, 한 번 main 에 병합된 같은 이름의 xlsx 는 엔진이 덮어쓰지도 지우지도 않는다(거부 사유 "main 에 이미 있는 판이다"). 고쳐 새 xlsx 를 내려면 판을 올려야 한다.

1. `git fetch origin` 으로 `origin/main` 을 최신으로 맞춘다. 엔진은 fetch 하지 않는다.
2. 지금 `버전:`·`LoB:` 의 파일(`BW_단위테스트 List_<LoB>_v<버전>.xlsx`)이 `origin/main` 에 있는지 본다:
   `git -c core.quotepath=false ls-tree --name-only origin/main docs/unittest/` 의 목록에서 찾는다(`core.quotepath=false` 가 없으면 한글 이름이 `\352…` 로 나와 못 찾는다).
   헷갈리면 그냥 산출한다 — main 에 있는 판이면 엔진이 거부하니, 그때 버전을 올린다.
   - **있다** — 작업본 머리의 `버전:` 을 0.1 올리고(`0.1` → `0.2`; 큰 변경이면 사용자에게 묻는다) Document Control `개정 이력` 표에 새 `Version`·`개정일자`·`개정사유` 한 줄을 더한다.
     산출하면 새 파일이 생기고 **이전 판 xlsx 는 그대로 남는다.** 이전 판 파일을 이 스킬이 지우거나 고치지 않는다.
   - **없다** — 이 브랜치에서 만든(병합 전) 판이다. 버전을 올리지 않아도 같은 버전으로 다시 산출되고, 결과 JSON 에 `replaced: true` 가 붙는다.
   - 목록을 읽지 못하면(git 없음, `origin/main` 못 읽음) 판단하지 못한 것이다. 통과로 넘기지 않고 그렇다고 알린 뒤 fetch 를 다시 한다.
3. 판의 기록은 git 이력과 남아 있는 이전 판 xlsx 다. 작업본 md 는 판마다 따로 두지 않는다.

## 산출

작업본이 채워지고 사용자가 xlsx 를 원하면("단위테스트 엑셀로 뽑아줘") 먼저 **짝을 확인**한다 — 단위테스트 List 표의 `Test Case ID` 마다 `TC.견본 · <ID>` 소절이 있고 그 반대도 같은지,
`Test 대상 여부` 가 `Yes`/`No` 인지. 빠진 짝은 산출 전에 사용자에게 알린다(엔진은 짝을 보지 않는다). 이어서 `--check` 로 확인한 뒤 산출한다. `--check` 는 파일을 쓰지 않는다.

```bash
e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "산출 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
uvx --from "$e" \
  python -P -m checker.export --spec "docs/unittest/<LoB>.md" --form "단위테스트 List" --root "$(git rev-parse --show-toplevel)" --check
```

`--check` 가 거부 없이 끝나면 `--check` 를 빼고 같은 명령을 다시 돈다. 엔진 판·`uvx`·PowerShell 호출 방법·stdout JSON 한 줄·`산출 불능` 처리는
`<이 스킬의 base directory>/../spec/SKILL.md` "양식 파일 산출" 과 같다(`@main` 이나 다른 판으로 대신 받지 않는다). 산출 xlsx 는 지도 `산출.폴더` 인 `docs/unittest/` 에
`BW_단위테스트 List_<LoB>_v<버전>.xlsx` 로 생긴다.

종료코드:

- `0` `status: ok` — `files` 의 경로를 알린다. 엑셀로 한 번 열어 계층 칸·Test Case 시트 이름·서식을 확인하라고 권한다(사람 몫). 담당자·일정·상태·Test 결과 같은 사람 칸이 비어 있는 것이
  정상이라고 알리고, 컨설턴트가 엑셀에서 채운다고 안내한다. `warnings` 가 있으면 항목별로 그대로 보여 준다.
- `3` `status: warning` — 파일은 만들었다. `warnings` 를 그대로 보여 주고, `type: dropdown-unchecked`·`leftover-review` 는 검사를 못 한 것이라 통과가 아니니 그렇다고 알린다.
  `type: dropdown` 은 `Test 대상 여부` 가 `Yes`/`No` 가 아닌 값이다.
- `1` `status: rejected` — 파일을 만들지 않았다. `problems` 의 시트·항목·사유를 그대로 보이고 작업본을 고친 뒤 다시 돈다.
  - 시트 이름 규칙(31자, 금지 문자, 중복)이면 ID 를 고친다. 지어내서 고치지 않고 사용자에게 알린다.
  - 같은 이름 파일이 main 에 있어 거부된 것이면 위 "버전 올리기". 사유가 "main 에 있는 판인지 판단하지 못해" 이면 검사 불능이니 fetch 한 뒤 다시 한다.
  - 남은 견본(`leftover-sample`)이면 템플릿에 견본이 남은 것이다. 산출을 멈추고 Project Repository 담당자에게 템플릿 확인을 부탁한다.
- `2` `status: error` — 작업본·지도·템플릿을 읽지 못했거나, 작업본이 지도에 없는 시트·표·열을 가리킨다(양식 밖 항목을 모두 모아 알린다). 산출하지 못했다고 알리고 작업본을 지도의 이름으로 고친다.
- stdout 이 JSON 으로 읽히지 않으면(uvx 실패, 엔진 못 받음) "산출 불능" 이다. 거부로도 통과로도 취급하지 않는다.

**검사는 이 스킬이 하지 않는다.** 산출한 xlsx 의 파일 이름은 PR 을 열 때 Actions(doc-guard)가 `rules/unittest-output.yaml` 로 맡는다. 산출 성공은 doc-guard 통과가 아니다.
파일 이름 패턴은 지도 `산출.파일명` 을 읽어 만든 것이 아니라 사본이라, 양식이 바뀌어 파일명 모양이 바뀌면 패턴도 직접 고친다. "첫 판은 0.1", "0.1 씩 올림",
"공식 문서 근거가 맞는가" 는 어느 검사도 강제하지 않는다. 사람이 챙긴다.

## 규칙 설치

Project Repository 에 단위테스트 List 검사 규칙이 없으면 이 스킬 폴더의 세 파일을 복사한다(이 PR 은 `rules/`·`templates/` 를 바꾸므로 승인자 Approve 가 필요하다고 알린다.
엔진은 `rules/` 만 읽는다). 양식 xlsx 와 양식 지도(`templates/forms/단위테스트 List.yaml`)는 Project Repository 담당자가 따로 넣는다 — 이 스킬 폴더에 없다.

| 이 스킬 폴더 | Project Repository |
|---|---|
| `unittest.yaml` | `rules/unittest.yaml` (작업본: 파일명·필수 절·양식 밖 열·Test Case ID 형식) |
| `unittest-output.yaml` | `rules/unittest-output.yaml` (산출 xlsx 파일명 패턴) |
| `unittest-template.md` | `templates/harness/unittest.md` (필수 절의 기준) |

작업본의 관할은 `docs/unittest/*.md`, 산출물의 관할은 `docs/unittest/*.xlsx` 다.
