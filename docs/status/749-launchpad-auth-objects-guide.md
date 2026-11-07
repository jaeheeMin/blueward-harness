# #749 Spec 사용 객체에 권한 객체 종류와 Launchpad 노출 객체 만드는 순서 안내 (2026-11-07)

RAP 앱을 Launchpad 에서 열리게 하려면 권한 객체·Access Control·Restriction·Business Role Template 이 필요한데, Spec `## 사용 객체` 종류에 적을 칸이 없었고 spec 스킬에도 순서 안내가 없었다.

## 바뀐 것

- skeleton `rules/spec.yaml`·`templates/harness/spec.md`·`rules/README.md`: 사용 객체 `종류` 에 `Authorization Field`, `Authorization Object`, `Access Control`, `Restriction Field`, `Restriction Type`, `Business Role Template` 추가. 새 규칙 종류가 아니라 같은 `md_table` 이라 엔진 판 제약은 없다. 이미 만든 Project Repository 에는 자동으로 오지 않아 직접 반영해야 한다.
- spec 스킬(`skills/spec/SKILL.md`): `## 권한` 단계 뒤에 안내 네 가지. (1) 권한 표의 커스텀 권한 객체와 Access Control 을 사용 객체에도 적게 한다. (2) 필드 값으로 범위를 제한하면 Restriction Field·Type 을 묻는다. (3) Launchpad 노출 객체의 공식 순서(패키지 소프트웨어 컴포넌트, 권한 객체, Access Control, BDEF, 서비스 바인딩 게시 후 권한 기본값 Synchronize, UI5 배포, IAM App, Restriction, Business Catalog, Business Role Template). (4) `@AccessControl.authorizationCheck` 값이 SAP 문서끼리 달라(`#CHECK` vs `#MANDATORY`) 정하지 않고 사용자에게 묻는다. 이 안내는 개발 단계에서 Claude 가 따르는 것이고 기계가 막지 않는다.
- 길잡이 `docs/guide/harness-guide.html` Spec 설명에 종류와 순서 안내 추가. 병합 뒤 아티팩트에 다시 올린다.
- 시험: `checker/tests/test_md_table.py` 에 새 6종 통과, 없는 종류(`Authorization Objects`) 거절.
- Plugin 0.10.189 -> 0.10.201, `console/whats_new.json` 에 0.10.201 한 줄.

## 근거 (이슈 #749 에 적힌 SAP 공식 문서)

- 권한 객체: help.sap.com/docs/abap-cloud/abap-development-tools-user-guide/defining-authorization-objects
- Restriction Field: .../defining-restriction-fields, Business Role Template: .../creating-business-role-template
- 노출 순서: help.sap.com/docs/SAP_S4HANA_CLOUD/6aa39f1ac05441e5a23f484f31e477e7/04330b95ea524c9bb89a3d1777c616e6.html
- 권한 기본값 Synchronize: .../964057839dc3401b91d03fabaa567c79.html, .../266999e6b9244e728583e10dbbffc8bd.html
- ZLOCAL 은 import 불가: .../851595ea424b432d98d899c5d0f5ce8e.html
- `#CHECK`(IAM 가이드): .../2a5524a8e57c4888a7ebec4898272484.html. `#MANDATORY`(ABAP 키워드 문서 "RAP - CDS-Based Authorization"): help.sap.com/docs/abap-cloud/abap-keyword/rap-cds-based-authorization (메인 세션이 원문 확인).

## 판단

- `checker/overlap.py` 는 `(종류, 이름)` 을 데이터로 비교해 코드 변경이 없다(코드 확인).
- `workflow.json` 은 spec SKILL.md 에서 바뀐 문장을 인용하지 않아 quote 변경 없음.
- `conventions/naming.md` 에 권한 객체 이름 규칙은 더하지 않았다. 스킬이 없으면 프로젝트에서 채우게 안내만 한다.

## 시험

- `uv run pytest checker/tests/test_md_table.py -q` 70 통과.
