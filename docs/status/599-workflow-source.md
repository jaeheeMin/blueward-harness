# #599 웹 콘솔 갈래를 플러그인 작업 순서 파일 기준으로 다시 세우기

콘솔은 화면만 쉽게 하고, 절차의 정본은 플러그인이다. 추정으로 순서를 만들지 않는다 - 단계마다 근거 스킬·규칙 문장이 있어야 한다.

- 정본: `plugins/harness/workflow.json`. 갈래·단계·다음 갈래·도구·조건마다 `basis: [{file, quote}]`. 옛 `console/flows.json` 은 지웠다.
- 갈래 다섯: `srs`(srs → deliver → 병합 기다리기), `spec`(→ 다음 `dev`), `dev`(start → 구현(SAP 080) → deliver → 기다리기, ATC 단계 없음), `config`(설정하기: start → 설정·SRS Configuration Considerations 기록 → deliver → 기다리기, 화면엔 "설정 DEV-xxx"), `fix`.
- SRS 다음 단계: 개발 → `spec`, 설정 → `config`(전에는 `dev` 로 보내고 있었다), 미정 → 안내만(spec 스킬이 그 자리에서 정한다). Dropped·Duplicate·On Hold 는 세지 않는다.
- 없앤 것: `new-customer`·`atc`·`review` 갈래, "권한·CTS 양식(준비 중)" 다음 갈래. scaffold 는 조건 `project-not-ready` 일 때 보이는 관리자 도구, atc·prs·approvals·role·cts·manual 은 도구다. 옛 id 로 저장된 세션은 저장된 이름·단계가 그대로 보인다.
- 프로젝트 준비: 조건 `project-ready`(`templates/`·`rules/` 모두 있나). 없으면 홈 카드와 도구 줄 위에 "프로젝트 준비 안 됨", 판정 불능이면 "확인하지 못했어요".
- 검사: `flows.validate` 가 basis 가 비었거나 file 이 없거나 quote 가 파일에 없으면 오류(콘솔은 갈래 기능만 끈다). `checker/tests/test_workflow_source.py` 가 모든 근거·모든 스킬이 workflow.json 의 단계나 도구에 있는지 PR 에서 확인한다.
- 설정 갈래로 넘길 때 요구사항 번호(`ids`)를 `POST .../flow/next` 로 보내 새 세션 사유를 "설정 DEV-003" 으로 적는다.
- 문서: `docs/design/web-console.md` §7a, `docs/guide/harness-guide.html` 웹 콘솔 항목, `rules/governance.md` 의 "작업 순서의 정본" 절, `CLAUDE.md` 11번.
- plugin.json version 0.10.159.

## 검토·브라우저 시험 뒤 고친 것

- SRS 다음 단계 분기별 `skipStatuses`: 개발·설정은 Dropped·Duplicate·On Hold, 미정은 근거가 없어 필터 없음. spec 갈래 deliver 근거를 spec 스킬 문장으로 바꿨다. srs·config 병합 문구는 SRS 승인 문장만(자동 병합 설명은 dev·fix).
- 설정하기로 넘기는 요구사항이 20건을 넘으면 job warning 에 "N건 중 20건만" 을 적고 확인 창에 보인다. 서버·화면 정규식 범위(REQ-1~6자리)를 맞췄다.
- `flows.missing_skills` 를 검사와 시험이 같이 쓴다. `basis_errors` 의 resolve 를 try 안으로.
- 새 작업: 도구만 쓰는 일은 `none`("순서 없이 이 도구만"), 앞에 다른 스킬을 붙이지 않는다. 분석 프롬프트에 Public Cloud·ABAP Cloud 대상, 프로젝트 준비 상태, `system_type`.
- 프로젝트 준비: 플러그인 저장소·`HARNESS_NO_SCAFFOLD_HINT=1` 은 따지지 않고, `templates/`·`rules/` 를 함께 가진 폴더를 3단계 아래까지 찾는다.

## 남은 것

- 근거 부족: `미정` 분기에서 Dropped·Duplicate·On Hold 를 뺄 근거 문장이 없다(그래서 안 뺀다).

- 스킬 안내의 "다음 할 일" 문장이 workflow.json 과 어긋나는 곳은 고치지 않고 목록으로만 남겼다(구현 보고서의 "어긋남 목록").
- 병합 뒤 길잡이 아티팩트에 다시 올린다. 설정 요구사항이 설정 순서로 진행되고 병합 뒤 원장이 완료가 되는지는 브라우저로 확인해야 한다(이번에는 못 했다).
