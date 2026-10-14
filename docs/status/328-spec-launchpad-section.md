# #328 Spec 에 Launchpad 노출 절 (2026-10-14)

#327 로 Claude 가 080 에서 앱 디스크립터(UIAD)를 쓸 수 있게 됐지만, 무엇을 쓸지(타일 제목·카탈로그·이동 대상)를 적을 자리가 Spec 틀에 없었다. public-cloud DEV-003(기간별 재고 수불부)이 그 경우다. Spec 을 쓸 때 한 번 정하고, 개발할 때 Claude 가 Spec 을 읽어 채운다. Spec 에 값이 없을 때만 묻고 추측하지 않는다.

## 바뀐 것

- skeleton `templates/harness/spec.md`: `## 사용 객체` 다음에 선택 절 `## Launchpad 노출`(안내문과 빈 행 하나). 사용 객체 종류 목록에 3종 추가.
- skeleton `rules/spec.yaml`: `required_sections` 의 `선택_섹션` 에 `Launchpad 노출` 추가, `md_table` 규칙 하나 더, 사용 객체 `종류` 허용 값에 3종 추가. 이 절이 없는 기존 Spec 은 통과한다.
- spec 스킬: 새 Spec 에서 노출 여부를 묻고 표를 채운다(추측 금지). 080 에 UIAD 를 쓸 때 이 표가 근거다. 기존 Spec 을 고칠 때 절이 없고 노출이 있는 개발이면 넣을지 묻는다.
- 테스트: `test_md_table`(Launchpad 표 정상·위반 5종·머리 불일치·절 없음, 새 종류 3종), `test_overlap`(Business Catalog 수정 겹침 경고). 길잡이 Spec 만들기 탭·용어 사전(앱 디스크립터), skeleton `rules/README.md`. Plugin version 0.10.73 → 0.10.74.

## 열 구성 (최소안, 사용자 결정)

`| 타일 제목 | 부제 | 아이콘 | 시맨틱 오브젝트 | 액션 | 파라미터 | 카탈로그 | 배치 |`. 한 개발에 타일이 여럿이면 행이 여럿이다. 예시값은 public-cloud DEV-003 실제 값(기간별 재고 수불부 / 재고 수불 집계 / `sap-icon://inventory` / AnalyticQuery / preview / `query=ZMM_C_STOCKLEDGERQUERY` / ZMM_BC_AUTO1 / MM AUTO1 페이지 · 재고원장 보고서 영역). 이슈 본문에 있던 "대상 롤" 열은 최소안에서 뺐다.

## 판단과 근거

- 사용 객체 종류 3종의 표기. 앱 디스크립터 = `Launchpad App Descriptor Item`(철자 근거: #327 조사 때 080 `findCollectionByUrl /sap/bc/adt/fiori/uiad` 의 제목이 "Launchpad App Descriptor Item" 이었다, 메인 세션 확인). `IAM App`, `Business Catalog` 는 skeleton `conventions/naming.md` 7절 표(397·399줄)의 원어 그대로.
- 패턴 근거: SAP Help "Editing Launchpad App Descriptor Items"(help.sap.com/docs/abap-cloud/abap-development-tools-user-guide/editing-launchpad-app-descriptor-items). 시맨틱 오브젝트는 영문자·숫자, 첫 글자는 영문자 → 검토 지적으로 커스텀 이름의 밑줄도 허용해 `[A-Za-z][A-Za-z0-9_]*`(좁혀서 정상 값을 거절하는 쪽이 더 나쁘다). 액션은 소문자로 시작하는 동사·짧은 구, 공백 없음, 허용 문자 영문자·숫자·밑줄 → `[a-z][A-Za-z0-9_]*`. 아이콘(`sap-icon://…`)은 근거를 찾지 못해 패턴을 넣지 않았다. 부제·파라미터·카탈로그·배치도 형식을 정하지 않는다. 길이 한도(시맨틱 오브젝트 30자, 액션 50자)는 Launchpad Designer(deprecated) 문서에만 있어 넣지 않았다. 웹 검색 결과의 요약으로 확인했고 페이지 전문은 읽지 못했다 — 첫 실제 Spec 에서 한 번 더 대조한다.
- `md_table` 은 파싱된 규칙 목록의 항목마다 따로 도므로 한 파일에 둘 이상 둘 수 있다(테스트로 확인: 같은 spec.yaml 의 두 규칙이 한 Spec 에서 각각 돈다).
- 칸 일부만 비면 `md_table` 은 위반으로 본다(엔진의 기존 동작). 패턴을 건 시맨틱 오브젝트·액션은 행이 있으면 비울 수 없고, 나머지 열은 비어도 된다. 칸이 전부 빈 행(틀의 자리표시)은 통과.
- 객체 겹침(`checker/overlap.py`)은 종류를 데이터로 비교한다(`(종류, 이름)` 키, 종류 목록을 코드에 두지 않음). 새 종류는 코드 변경 없이 비교된다. 두 Spec 이 같은 Business Catalog 를 `수정`(앱 추가)하면 경고가 뜨는 것이 의도다(팀 간 카탈로그 겹침 알림).
- 엔진 판 제약 없음: 새 규칙 종류가 아니라 기존 `md_table` 이다.

## 남은 일

- public-cloud 의 `rules/spec.yaml`·`templates/harness/spec.md` 는 이 저장소에서 자동으로 오지 않는다. 그쪽에서 같은 변경을 직접 반영해야 한다(요청 필요). 반영 전에는 새 종류를 쓴 Spec 이 종류 허용 목록 위반이 된다. 기존 Spec(DEV-002·DEV-003)은 강제하지 않는다.
- 병합 뒤 길잡이를 아티팩트에 다시 올린다(`docs/guide/README.md`).
