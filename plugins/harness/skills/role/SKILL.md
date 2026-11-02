---
name: role
description: User Role Mapping(사용자권한관리) 작업본에 Role 목록과 Role 별 Launchpad 메뉴 배정을 정리하고, Spec 에 있는데 작업본에 빠진 카탈로그를 알리고, 고객 양식 xlsx 로 산출할 때 쓴다. 사용자가 "Role 정리해줘", "Role 매핑", "사용자 권한 관리 만들어줘", "메뉴 배정", "Role 엑셀로 뽑아줘" 라고 말할 때 사용한다. 이럴 땐 쓰지 않는다 — SAP 에서 Role 이나 사용자를 만들고 배정하는 일, 사람(사번·이름)을 Role 에 매핑하는 일은 이 스킬이 하지 않는다(사람 행은 고객 담당자가 채운다). 개발 Spec 이나 CTS 관리대장이면 spec·cts 스킬로.
---

# /harness:role

`docs/권한관리/` 의 User Role Mapping 작업본(md)에 Role 목록과 Role 별 메뉴 배정을 쓰고, 고객 양식 xlsx 로 산출하는 입구다.
양식은 Project Repository 의 `templates/` 에 있고 양식 지도는 `templates/forms/사용자권한관리.yaml` 이다. 시트·표·열
이름과 Role 이 펼쳐지는 열 범위는 항상 지도에서 읽는다 — 이 스킬에 양식 고유 글자를 지어 적지 않는다(아래 예의 이름은
public-cloud 지도 기준이고, 지도가 다르면 지도를 따른다). `<이 스킬의 base directory>` 는 이 스킬이 로드될 때 위에 표시되는
경로다.

Role 은 **가로 열**로 늘어난다. 작업본에는 Role 개요 표에 한 번 적고, 메뉴 배정 표의 `Role` 열에 그 Role 의 ID 를 쉼표로
적으면 엔진이 Role 마다 열을 만들어 머리글(Role ID·설명·주요 권한·조직 레벨)을 쓰고 배정한 칸에 `O` 를 쓴다. 양식에 있는 열 수
(public-cloud 는 메뉴 배정 48열)를 넘으면 산출이 거부한다.

**사람 정보는 이 저장소에 두지 않는다.** `ID-Role Mapping` 시트는 Role 머리글만 채우고 사원 번호·이름·SAP ID 행은 비워 산출한다.
고객 담당자가 산출된 엑셀에서 채운다. 사용자가 사번·이름을 알려 줘도 작업본에 적지 않는다.

SAP 에서 Role·카탈로그가 실제로 어떻게 배정돼 있는지는 이 스킬이 읽지 않는다. 사람이 알려 준 것과 Spec 의 기록만 받아 적고,
모르는 값은 지어내지 않고 묻는다.

`git rev-parse --show-toplevel` 로 Project Repository 루트를 확인한다.

## 작업본 형식

위치와 이름: `docs/권한관리/사용자권한관리_User_Role Mapping.md`. 폴더와 이름은 지도 `산출` 의 폴더·파일명
(`사용자권한관리_User_Role Mapping_v{버전}.xlsx`)에서 `_v{버전}` 만 뺀 것이라, 산출 xlsx 와 같은 폴더에 나란히 놓인다. 작업본은
하나이고 판마다 따로 두지 않는다. 파일명 규칙은 `rules/role.yaml` 이 강제한다.

```markdown
# 사용자권한관리 (User Role Mapping)

버전: 0.1

## 양식 항목

### 사용자권한관리 · Role 개요

#### Role 개요

| Role ID | Description | 주요 권한 | 사용 대상자 | 비고 | 조직 레벨 |
|---|---|---|---|---|---|
| <값> | <값> | <값> | <값> | | <값> |

### 사용자권한관리 · Role to Area Menu

#### 메뉴 배정

| Space | Page | Section | Fiori App(한글) | Fiori App(영문) | Catalog | Role |
|---|---|---|---|---|---|---|
| <값> | <값> | <값> | <값> | <값> | <값> | <Role ID>, <Role ID> |

### 사용자권한관리 · ID-Role Mapping

양식 지도: 사람 행은 비워 두고 Role 머리글만 채운다.
```

(시트·표·열 이름은 **지도에서 읽은 것**이다. 지도에 없는 시트·표·열은 쓰지 않는다 — 저장할 때(훅)와 PR(doc-guard
`form_columns`)이 "양식 밖" 으로 거절하고 산출도 멈춘다. `App List` 는 양식 그대로 두므로 작업본에 쓰지 않는다.)

- **머리.** 첫 `##` 앞의 `버전: 0.1` 줄이 산출 파일명의 버전(`v0.1`)이 된다. 처음은 0.1, 올릴 때 0.1 씩이다. 줄이 없거나 `x.y`
  모양이 아니면 산출이 거부한다.
- **Role 개요 표.** Role 목록의 원본이다. 이 표가 없거나 행이 없으면 펼칠 열을 정하지 못해 산출이 거부한다. 이 표의 `Role ID` 순서가 펼쳐지는 열의 순서이고, 같은 `Role ID` 가 둘이면 산출이 거부한다.
  `조직 레벨` 같은 열은 작업본에만 있고 엑셀 열로는 가지 않는다(메뉴 배정 머리글 칸으로만 간다). 지도 `펼침.머리글` 이 읽는 열 이름이
  이 표에 있는지 지도에서 확인한다.
- **메뉴 배정 표.** 행 하나가 메뉴 한 줄이다. `Space`·`Page`·`Section`·`Fiori App`·`Catalog` 는 양식의 계층 열이고, **`Role` 열은
  작업본에만 있는 열**이다. 그 줄을 배정받는 Role 의 `Role ID` 를 쉼표로 적는다(`Z_PP_100, Z_PP_200`). 값이 Role 개요 표에 없으면
  양식 밖 값이라 거절·거부한다. 비워 두면 어느 Role 에도 배정하지 않은 줄이다.
- **사람 행.** `ID-Role Mapping` 소절에는 표를 쓰지 않는다.

## 0단계: 브랜치 확인

작업본을 쓰기 전에, 지금 브랜치가 이번 Role 작업에 맞는지 확인한다. 확인은 `<이 스킬의 base directory>/../start/SKILL.md` 의
"다른 스킬이 부르는 브랜치 확인" 을 그대로 따른다 — 미커밋 변경, main 이면 start 절차, 다른 작업 브랜치면 같은 일인지 판단·질문,
판정 불능이 거기 있다. start 를 따로 부르라고 하지 않는다. 이 스킬에서 정하는 것은 아래뿐이다.

- **이번 작업 설명**은 "사용자권한관리 — Role 매핑 <요약>" 한 줄이다. 작업 내용(Role 추가, 메뉴 배정 등)을 받은 뒤에 브랜치를
  비교한다(그 전에는 읽기만 하고 파일을 쓰지 않는다).
- **같은 일의 판단 기준.** 브랜치 이슈 제목·본문이 사용자권한관리 / Role 매핑 작업이면 같은 일이다. 아니면 묻는다.
- **main 이면 번호 없는 작업 이슈를 만든다.** start 절차를 `docs` 작업으로 수행한다 — 제목은 `사용자권한관리 — Role 매핑 <요약>`,
  브랜치는 `docs/{이슈번호}-…`. DEV 번호는 받지 않는다(Role 매핑은 개발 건이 아니다).

## Role 목록 정리

1. **지도를 읽는다.** `templates/forms/사용자권한관리.yaml` 의 시트·표·열 이름과 메뉴 배정 표의 `펼침`(원본 표·열, `시작_열`~`끝_열`,
   `머리글`, `표시`)을 읽어 둔다.
   - 지도가 없으면 **멈추고** 지도가 없다고 알린다. 지도를 추측해 만들지 않는다(`<이 스킬의 base directory>/../spec/form-map.md`).
   - 지도에 `펼침` 이 없으면 엔진이 Role 열을 못 채운다. 멈추고 지도에 `펼침` 이 필요하다고 알린다.
   - `rules/role.yaml`·`rules/role-output.yaml`·`templates/harness/role.md` 가 없으면 아래 "규칙 설치" 로 안내한다.
2. **작업본을 읽는다.** 있으면 읽고(`버전:`, 기존 Role), 없으면 새 작업본이다 — 위 형식대로 만들고 `버전: 0.1` 로 시작한다.
3. **Role 을 받는다.** 사용자가 알려 준 Role 의 `Role ID`·`Description`·`주요 권한`·`사용 대상자`·`조직 레벨`·`비고` 를 Role 개요 표에
   한 줄씩 적는다. 모르는 값은 비워 두고 알린다. 지어내지 않는다. 새 Role 을 더하면 양식의 열 수(지도 `시작_열`~`끝_열`)를 넘지
   않는지 센다 — 남은 열이 적으면 알린다.
4. 이미 있는 Role 의 `Role ID` 를 바꾸면 메뉴 배정 표 `Role` 열의 같은 ID 도 함께 바꾼다(안 그러면 양식 밖 값으로 거절된다).

## 메뉴 배정

1. **Spec 에서 초안을 만든다.** 개발 건 Spec(`docs/spec/DEV-*.md`)의 `## Launchpad 노출` 표(`타일 제목`·`카탈로그`·`배치`)와 `## 권한`
   표를 읽는다. 카탈로그가 있는 줄마다 메뉴 배정 표에 한 줄 더하는 안을 만든다.
   - `Catalog` 에는 Spec 의 카탈로그 이름을 그대로 적는다. 앱 이름(`Fiori App(한글)`)은 Spec 의 타일 제목을 쓰고, 영문 이름·`Space`·
     `Page`·`Section` 은 Spec 에 없으면 비워 두고 묻는다.
   - `Role` 열은 Spec 의 `배치` 칸에 "역할 `Z_PP_100` 에 카탈로그 배정" 처럼 적힌 것만 근거로 한다. 적혀 있지 않으면 어느 Role 인지 사용자에게
     묻는다. 추측해 채우지 않는다. `## 권한` 표는 어떤 권한 객체가 필요한지 알려 줄 뿐 Role 배정이 아니다. 이 표로 Role 을 정하지 않는다.
2. 한 번에 안을 보이고 사용자가 확인한 줄만 표에 더한다. 이미 있는 줄(같은 `Catalog`)은 새로 더하지 않고 `Role` 열만 고친다.
3. 계층 열(`Space` > `Page` > `Section` > App)은 양식이 행마다 한 단계씩 들여써 채우는 칸이다. 같은 값이 이어지는 줄은 첫 줄에만 쓰는
   방식이면 기존 줄의 쓰는 방식을 따른다. 기존 줄이 없으면 사용자에게 묻는다.

## Spec 대조

메뉴 배정을 정리한 뒤, 또 사용자가 "빠진 거 없어?" 라고 하면, Spec 에 있는 카탈로그가 작업본에 없는지 엔진 명령으로 대조한다.
읽기만 하고 파일을 쓰지 않는다. 엔진 판·`uvx` 호출은 아래 "산출" 과 같다.

```bash
e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "대조 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
uvx --from "$e" \
  python -P -m checker.role_check --workbook "docs/권한관리/사용자권한관리_User_Role Mapping.md" --form 사용자권한관리 \
  --sheet "Role to Area Menu" --table "메뉴 배정" --column Catalog --root "$(git rev-parse --show-toplevel)" --spec-dir docs/spec
```

`--sheet`·`--table`·`--column` 은 지도에서 읽은 시트·메뉴 배정 표·카탈로그 열 이름이다(위는 public-cloud 지도 값). 한 Spec 만 보려면
`--spec-dir` 대신 `--spec <Spec 경로>` 를 준다.

- `0` `status: ok` — Spec 의 카탈로그가 모두 작업본에 있다. 대조한 Spec 수(`specs_checked`)와 건너뛴 Spec(`skipped`, Launchpad 절이 없는
  Spec)을 알린다.
- `1` `status: missing` — `missing` 의 Spec·타일 제목·카탈로그를 **Spec 별 목록**으로 알린다. 작업본이 틀린 것이 아니라 Role 배정이 안 된
  카탈로그다. 어느 Role 에 배정할지 사용자에게 묻고, 정해진 줄만 메뉴 배정 표에 더한다. 배정하지 않기로 한 카탈로그는 그대로 두고 알린다.
- `2` `status: error` — 작업본이나 Spec 을 읽지 못했거나, 넘긴 시트·표·열 이름이 양식 지도에 없거나(오타), 대조한 Spec 이 하나도 없거나,
  카탈로그 칸에서 이름을 뽑지 못한 줄이 있다(`unchecked` 의 파일과 사유). **대조를 못 한 것**이라고 알린다. 통과도 빠짐도
  아니다. 읽은 Spec 의 결과(`missing`)는 함께 보인다. 이름을 뽑지 못한 칸은 Spec 의 카탈로그 칸 표기를 사람에게 묻는다. stdout 이 JSON 으로 읽히지 않아도(uvx 실패, 엔진 못 받음) "대조 불능" 이다.

이 대조는 카탈로그 이름만 본다. Role 배정이 SAP 에 실제로 돼 있는지는 보지 않는다. 저장·PR 의 doc-guard 도 이 대조를 하지 않는다 —
스킬을 부를 때 사람이 챙긴다.

## 버전 올리기

이 작업본은 계속 고쳐지고, 한 번 main 에 병합된 같은 이름의 xlsx 는 엔진이 덮어쓰지도 지우지도 않는다(거부 사유 "main 에 이미 있는
판이다"). 고쳐 새 xlsx 를 내려면 판을 올려야 한다.

1. `git fetch origin` 으로 `origin/main` 을 최신으로 맞춘다. 엔진은 fetch 하지 않는다.
2. 지금 `버전:` 의 파일(`사용자권한관리_User_Role Mapping_v<버전>.xlsx`)이 `origin/main` 에 있는지 본다:
   `git -c core.quotepath=false ls-tree --name-only origin/main docs/권한관리/` 의 목록에서 찾는다(`core.quotepath=false` 가 없으면
   한글 이름이 `\352…` 로 나와 못 찾는다). 헷갈리면 그냥 산출한다 — main 에 있는 판이면 엔진이 거부하니, 그때 버전을 올린다.
   - **있다** — 작업본 머리의 `버전:` 을 0.1 올린다(`0.1` → `0.2`; 큰 변경이면 사용자에게 묻는다). 산출하면 새 파일이 생기고
     **이전 판 xlsx 는 그대로 남는다.** 이전 판 파일을 이 스킬이 지우거나 고치지 않는다.
   - **없다** — 이 브랜치에서 만든(병합 전) 판이다. 버전을 올리지 않아도 같은 버전으로 다시 산출되고, 결과 JSON 에 `replaced: true` 가 붙는다.
   - 목록을 읽지 못하면(git 없음, `origin/main` 못 읽음) 판단하지 못한 것이다. 통과로 넘기지 않고 그렇다고 알린 뒤 fetch 를 다시 한다.
3. 판의 기록은 git 이력과 남아 있는 이전 판 xlsx 다. 작업본 md 는 판마다 따로 두지 않는다.

## 산출

작업본이 채워지고 사용자가 xlsx 를 원하면("Role 엑셀로 뽑아줘") **먼저 Spec 대조**를 하고, 이어서 `--check` 로 확인한 뒤 산출한다.
`--check` 는 파일을 쓰지 않는다.

```bash
e="$(uv run --no-project python "${CLAUDE_PLUGIN_ROOT}/hooks/engine_spec.py")" && [ -n "$e" ] || { echo "산출 불능: 엔진 판을 정하지 못했다" >&2; exit 1; }
uvx --from "$e" \
  python -P -m checker.export --spec "docs/권한관리/사용자권한관리_User_Role Mapping.md" --form "사용자권한관리" --root "$(git rev-parse --show-toplevel)" --check
```

`--check` 가 거부 없이 끝나면 `--check` 를 빼고 같은 명령을 다시 돈다. 엔진 판·`uvx`·PowerShell 호출 방법·stdout JSON 한 줄·`산출 불능`
처리는 `<이 스킬의 base directory>/../spec/SKILL.md` "양식 파일 산출" 과 같다(`@main` 이나 다른 판으로 대신 받지 않는다). 산출 xlsx 는 지도
`산출.폴더` 인 `docs/권한관리/` 에 `사용자권한관리_User_Role Mapping_v<버전>.xlsx` 로 생긴다.

종료코드:

- `0` `status: ok` — `files` 의 경로를 알린다. 엑셀로 한 번 열어 Role 머리글·`O` 표시 위치·서식을 확인하라고 권한다(사람 몫). `ID-Role Mapping`
  의 사람 행이 비어 있는 것이 정상이라고 알리고, 고객 담당자가 그 시트에서 채운다고 안내한다. `warnings` 가 있으면 항목별로 그대로 보여 준다.
- `3` `status: warning` — 파일은 만들었다. `warnings` 를 그대로 보여 주고, `type: dropdown-unchecked`·`leftover-review` 는 검사를 못 한 것이라
  통과가 아니니 그렇다고 알린다.
- `1` `status: rejected` — 파일을 만들지 않았다. `problems` 의 시트·항목·사유를 그대로 보이고 작업본을 고친 뒤 다시 돈다.
  - "양식의 …열을 넘는다" 면 Role 이 양식 열보다 많은 것이다. Role 을 줄이거나 양식에 열을 더해야 한다(양식은 이 스킬이 고치지 않는다).
    사용자에게 알리고 멈춘다.
  - "같은 값이 둘 이상이다" 면 Role 개요 표의 `Role ID` 중복이다.
  - 같은 이름 파일이 main 에 있어 거부된 것이면 위 "버전 올리기". 사유가 "main 에 있는 판인지 판단하지 못해" 이면 검사 불능이니 fetch 한 뒤 다시 한다.
- `2` `status: error` — 작업본·지도·템플릿을 읽지 못했거나, 작업본이 지도에 없는 시트·표·열이나 Role 개요에 없는 Role 을 가리킨다(양식 밖
  항목을 모두 모아 알린다). 산출하지 못했다고 알리고 작업본을 지도의 이름과 Role 개요의 `Role ID` 로 고친다.
- stdout 이 JSON 으로 읽히지 않으면(uvx 실패, 엔진 못 받음) "산출 불능" 이다. 거부로도 통과로도 취급하지 않는다.

**검사는 이 스킬이 하지 않는다.** 산출한 xlsx 의 파일 이름은 PR 을 열 때 Actions(doc-guard)가 `rules/role-output.yaml` 로 맡는다. 산출 성공은
doc-guard 통과가 아니다. 파일 이름 패턴은 지도 `산출.파일명` 을 읽어 만든 것이 아니라 사본이라, 양식이 바뀌어 파일명 모양이 바뀌면 패턴도 직접
고친다. "첫 판은 0.1", "0.1 씩 올림" 은 어느 검사도 강제하지 않는다. 사람이 챙긴다.

## 규칙 설치

Project Repository 에 Role 매핑 검사 규칙이 없으면 이 스킬 폴더의 세 파일을 복사한다(이 PR 은 `rules/`·`templates/` 를 바꾸므로 승인자
Approve 가 필요하다고 알린다. 엔진은 `rules/` 만 읽는다).

| 이 스킬 폴더 | Project Repository |
|---|---|
| `role.yaml` | `rules/role.yaml` (작업본: 파일명·필수 절·양식 밖 열·없는 Role) |
| `role-output.yaml` | `rules/role-output.yaml` (산출 xlsx 파일명 패턴) |
| `role-template.md` | `templates/harness/role.md` (필수 절의 기준) |

작업본의 관할은 `docs/권한관리/*.md`, 산출물의 관할은 `docs/권한관리/*.xlsx` 다.
