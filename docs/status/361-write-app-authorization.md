# #361 데이터를 바꾸는 앱의 권한 검사를 Spec·검토에서 놓치지 않게 (2026-10-19)

public-cloud DEV-006(반복제조 생산실적 엑셀 업로드)은 재고를 전기하는 앱인데, BDEF 가 `authorization master ( global )` 이고 behavior pool 의 `get_global_authorizations` 가 `auth-allowed` 만 대입했다(파일에 실제 `AUTHORITY-CHECK` 0건). Spec 8절에 "플랜트 단위 권한 검사 제외(사용자 결정)" 이 적혀 있었지만 승인 없이 병합돼 080 역할 57명·100 역할 17명에게 배포됐다. 사용자 결정으로 ① Spec 절 ② CR-009 코드 경고 ③ risk-gate 사유를 모두 넣었다.

## 근거(SAP 공식)

help.sap.com RAP 가이드 "Authorization Definition/Control/Implementation", "Implementing Global/Instance Authorization". BDEF `authorization master ( global | instance | global, instance )`, `authorization dependent by`, `authorization : update`/`none`. behavior pool 은 `FOR GLOBAL AUTHORIZATION`/`FOR INSTANCE AUTHORIZATION` 메서드를 구현하고 권한 객체는 `AUTHORITY-CHECK OBJECT`(ACTVT 01/02/06)로 검사한다. 공식 예시의 "모두 허용" 은 권한 객체가 없을 때의 시뮬레이션이며 운영에서 쓰지 말라고 안내한다. instance 권한은 필드 값(예: 플랜트)을 보고, create 와 static action 은 instance 를 쓸 수 없다.

## 바뀐 것

① Spec `## 권한` 절
- skeleton `templates/harness/spec.md`: `## 사용 객체` 와 `## Launchpad 노출` 사이에 선택 절. 표 `| 동작 | 검사 방식 | 권한 객체 | 활동 | 검사 기준 필드 | 비고 |`. 검사 방식은 `global` / `instance` / `global, instance` / `update 위임` / `검사 안 함`.
- skeleton `rules/spec.yaml`: `선택_섹션` 에 `권한`, `md_table` 규칙(열 6개, 검사 방식 허용 값, 활동 `\d{2}(?:\s*,\s*\d{2})*|-`, `조건_필수`).
- `checker/rules/md_table.py`: 새 키 `조건_필수`(영문 `required_if`). `[{열: 비고, 조건: {검사 방식: [검사 안 함]}}]` 처럼 다른 열이 어떤 값(`""` 는 빈 칸)일 때 이 열을 채우게 한다. 조건 열이 여럿이면 모두 맞아야 하고, 같은 칸을 여러 조건이 가리켜도 위반은 한 번만 낸다. 규칙은 `검사 안 함` 이거나 검사 기준 필드가 `-`/빈 칸이면 비고 필수 둘이다. 내용(이유·결정자·날짜)이 맞는지는 기계가 못 본다 — 승인자의 몫.
- spec 스킬: 새 Spec 에서 "데이터를 바꾸는 동작이 있나" 를 묻고 있으면 권한 표를 채운다(모르면 묻고 추측 금지). 권한을 빼는 결정이면 이유·결정자·날짜를 받고 PR 에서 승인자가 본다고 안내한다. 기존 Spec 을 고칠 때 절이 없고 쓰기 동작이 있으면 넣을지 묻는다.

② CR-009 코드 경고
- `checker/code_rules.py` `_scan_abap_cr009`: 마스킹한 ABAP 에서 `METHODS x ... FOR GLOBAL|INSTANCE AUTHORIZATION` (콜론 체인 `METHODS: a FOR ..., b FOR ...` 도 읽는다)로 선언된 메서드의 구현이 (a) `auth-allowed` 를 쓰고 `auth-unauthorized` 가 없는데 그 클래스 구현(`CLASS ... IMPLEMENTATION` ~ `ENDCLASS`) 안에 `AUTHORITY-CHECK` 가 없거나, (b) 본문이 비었거나 주석뿐이면 경고한다. 주석·문자열 속 AUTHORITY-CHECK 는 세지 않는다. 빈 본문 사유는 "권한 메서드가 비어 있음 — 실제로 무엇을 허용하는지 확인 필요" 이다. `harness:allow CR-009 <이유>` 는 `METHOD` 구현 줄이나 바로 위 줄에 쓴다(기존 `_check_allow` 그대로).
- 빈 본문을 경고하는 이유: 빈 본문일 때 SAP 가 무엇을 허용으로 보는지 상수 값을 확인하지 못했다. 안전한 쪽(경고)으로 두었다. 표준 BO·DCL 에 위임한 것이라는 해석은 **기계로 확인하지 못한 가정**이다.
- AUTHORITY-CHECK 범위: 전엔 파일 전체였고 이제 클래스 구현 범위다. 같은 파일의 헬퍼 클래스나 다른 파일에 검사가 있으면 오탐 경고가 나므로 `harness:allow` 로 남긴다(common.md 한계에 적음).
- 못 잡는 것: 메서드 정의가 다른 파일(`locals_def`)에 있는 경우, 틀린 권한 객체를 쓴 경우.
- 심각도: `code_checks.yaml` 규칙 항목에 `level`(`violation` 기본, `warn`). 발견마다 `level` 이 붙고 요약에 `warnings` 가 더해진다. `warn` 은 파일 `status` 도 종료코드도 바꾸지 않는다. 그 밖의 값은 `ConfigError` 이고, `_check_file` 이 그것을 파일 `error`(검사 불능, 종료코드 2)로 낸다. 전엔 `ConfigError` 가 잡히지 않아 트레이스백(종료코드 1, 위반처럼 보임)으로 끝났다.
- `scripts/render_report.py`: 코드 규칙 절에 위반과 따로 "경고(병합을 막지는 않습니다)" 목록. 훅(`pre_write_guard.py`, `mcp_source_guard.py`)은 `level: warn` 만 있으면 막지 않고 `allow_with_notice`(`additionalContext`)로 경고를 알려 준다(mcp 쪽에 같은 함수를 추가). 위반이 있어 막을 때는 거절 사유에 경고도 붙인다. `_filter_report_to_rules` 의 `has_violation` 은 warn 을 세지 않는다. 이름만 보는 MCP 경로(CR-001 만)는 경고를 보이지 않는다.
- `conventions/common.md` 에 CR-009. 세션 시작 훅 요약은 `common.md` 의 `## CR-` 헤딩을 파싱하므로(`session-start-sync.sh`) 따로 고칠 것이 없다. `test_plugin_layout` 헤딩 검사를 009 까지 넓혔다.

③ risk-gate `write_auth`
- `checker/risk_gate.py`: 새 기준 `write_auth`(등록 순서 `split_hint` 다음). PR 이 바꾼(삭제 제외) `.abap` 파일의 head 내용을 읽어 `check_source` 로 CR-009 발견(예외 처리 안 된 것)이 있으면 "쓰기 앱인데 권한 검사 없음: <파일>" 사유. 읽지 못하면(None·빈 문자열·파일 아님) 통과로 뭉개지 않고 "권한 검사 여부를 확인하지 못함" 사유. `build_next` 에 안내 한 줄.
- **설정 키를 만들지 않았다.** 게이트가 켜져 있으면 항상 본다. 새 키를 만들면 옛 엔진(0.10.84 이하)이 `risk-gate.yaml` 의 모르는 키로 판정 불능이 되기 때문이다. 끄는 방법은 코드 쪽 `harness:allow CR-009` 뿐이다. 비용: `.abap` 파일마다 GitHub contents 호출 한 번.
- 사유 목록은 `decide_pr` 하나라 병합 뒤 감지(`decide_commit`, after-merge)와 승인 없이 병합된 PR 의 알림 이슈에도 같은 줄이 찍힌다. PR 없이 main 에 직접 들어온 커밋 경로도 같은 기준을 돈다. `precheck-pr`(AI 리뷰 사전 판정)은 `PRECHECK_CRITERIA` 밖이라 보지 않는다.

## 엔진 판 제약

- `level` 과 CR-009: `code_checks.yaml` 은 `checker/` 안에 있어 엔진과 함께 배포된다. 훅은 plugin.json version 과 같은 태그의 엔진을, Actions 는 `stable` 을 받으므로 같은 판의 yaml 과 코드가 같이 간다. 옛 엔진은 `level` 키를 읽지 않고 CR-009 도 모르므로, 옛 엔진에 새 yaml 이 가는 경로가 없다.
- `md_table` 의 `조건_필수`: 옛 엔진은 `md_table` 의 모르는 키를 설정 오류(검사 불능)로 본다. 그래서 새 `rules/spec.yaml` 은 엔진 v0.10.85 이상(`stable`)이 된 뒤에만 쓸 수 있다. `rules/README.md` 에 적었다. 이미 만든 Project Repository 에는 자동으로 오지 않는다(public-cloud 는 그쪽에서 직접 반영해야 한다).
- 새 훅(0.10.85)이 옛 엔진을 받는 경우는 없다(태그가 version 과 같다). 만약 받으면 `level` 이 없는 발견을 위반으로 보므로(`f.get("level") == "warn"` 일 때만 거름) 기존과 같게 동작한다.

## 실제 데이터로 확인(public-cloud main, behavior pool 10개)

`gh api repos/blueward-26/public-cloud/contents/src/...` 로 받은 `zbp_*.clas.locals_imp.abap` 10개(`*.clas.abap` 10개·`testclasses.abap` 2개 포함 22개 파일)에 `check_source` 를 돌렸다.

빈 본문 경고와 클래스 범위를 반영한 재집계다. **10개 중 10개 파일, 11건**이 경고다.
- 이전 판(빈 본문 제외)의 7개 파일 8건: `zbp_pp_r_remconfupload`(DEV-006, 헤더 `Upload`·`Item` 두 메서드), `zbp_csh_i_griv`, `zbp_csh_i_griv_item`, `zbp_csh_i_inb_req`, `zbp_csh_i_mvt_req`, `zbp_csh_i_po_dp`, `zbp_csh_i_po_req` — 그대로 경고.
- 빈 본문(주석뿐)이라 새로 경고: `zbp_mjh_r_pochg`, `zbp_mm_r_mrppoconvday`, `zbp_mm_r_mrppoconvhdr` 3건. 주석에 "표준 BO·IAM 이 검사한다" 고 적혀 있지만 기계로는 위임을 확인하지 못한다.
- 다른 `*.clas.abap`·`testclasses.abap` 은 권한 메서드가 없어 0건.
- DEV-006 은 `AUTHORITY-CHECK` 가 주석(`AUTHORITY-CHECK(DCL) 덤프 ...`)에만 한 번 나온다 — 마스킹 덕분에 세지 않고 경고가 난다.
- 오탐 판단: 10개 모두 경고라 오탐과 진짜를 기계로 가를 수 없다. csh 6개 중에는 주석에 "표준 공급업체 송장 BO 와 CDS DCL 이 검사한다" 처럼 위임을 적은 것도 있다(`zbp_csh_i_griv`). 그 위임이 실제로 성립하는지는 확인하지 않은 가정이다. 기계는 위임 여부를 모르므로 경고가 나고, 의도한 것이면 `harness:allow CR-009 <이유>` 로 남기게 한다 — 이 PR 이 원하는 동작이다(이유와 결정자를 남기게 하는 것). 이 파일들을 바꾸는 PR 은 risk-gate 가 승인을 요구한다.

## 남은 일

- public-cloud 의 `rules/spec.yaml`·`templates/harness/spec.md` 에는 자동으로 오지 않는다. 엔진 0.10.85 `stable` 확인 뒤 그쪽에서 반영을 요청해야 한다.
- 기존 behavior pool 10개의 경고는 public-cloud 담당자가 위임이 사실로 확인되면 `harness:allow CR-009` 로, 아니면 `AUTHORITY-CHECK` 로 정리한다.
- 병합 뒤 길잡이를 아티팩트에 다시 올린다(`docs/guide/README.md`).
