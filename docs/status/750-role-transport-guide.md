# #750 role 스킬에 Role·Space·Page 의 운영 전달 경로 안내 (2026-11-07)

role 스킬은 작업본에 Role·메뉴 배정을 정리하는 데서 끝났다. SAP 에서 Role·Space·Page 를 어디서 만들고 어떻게 운영으로 옮기는지는 안내하지 않았다. 그래서 개발 transport 만 옮기면 운영에서 앱이 안 보일 수 있었다.

## 바뀐 것

- `skills/role/SKILL.md`: "작업본의 Role·Space·Page 는 SAP 에서 관리자가 따로 만들고 따로 옮긴다" 단락을 더했다. 작업본을 산출한 뒤 사용자에게 아래를 알린다. 스킬이 SAP 에 쓰지는 않는다.
  - 만드는 곳은 customizing 테넌트다.
  - 만드는 앱은 Maintain Business Roles, Manage Launchpad Spaces·Pages 다. 앱은 Spaces 모드에서만 보인다.
  - 옮기는 길은 개발 transport 와 따로, Software Collection(Key User Extensibility)이다. Role·Space·Page 는 같은 컬렉션에 담는다. SAP* Role 은 옮길 수 없다.
  - 대안은 Download/Upload 이고, 제약이 있다.
- 길잡이 Role 탭에 같은 내용의 callout 을 더했다. 병합 뒤 아티팩트에 다시 올린다.
- Plugin 0.10.202, `console/whats_new.json` 에 한 줄을 더했다.

## 근거 (SAP S/4HANA Cloud Public Edition 공식 문서, 2026-11-07 원문 확인)

- customizing 테넌트에서 만들어 software collection 으로 운송: https://help.sap.com/docs/SAP_S4HANA_CLOUD/6aa39f1ac05441e5a23f484f31e477e7/c79fa657501546fa8d9a4eee07409b7b.html
- Transport Your App: https://help.sap.com/docs/SAP_S4HANA_CLOUD/6aa39f1ac05441e5a23f484f31e477e7/f259607ecde645f1b77bed32815c2db0.html
- 같은 컬렉션, SAP* 운송 불가: https://help.sap.com/docs/SAP_S4HANA_CLOUD/53e36b5493804bcdb3f6f14de8b487dd/83c1cd62666f48c68d93f2fdeae1ae95.html
- Download/Upload 제약: https://help.sap.com/docs/SAP_S4HANA_CLOUD/53e36b5493804bcdb3f6f14de8b487dd/a58f69585339484aa204cf0321cab2cd.html
- Spaces 모드: https://help.sap.com/docs/SAP_S4HANA_CLOUD/6aa39f1ac05441e5a23f484f31e477e7/e9c4108610d14b8e9c08353458ed7f8c.html

## 하지 않은 것

- cts 양식 지도에 Software Collection 칸이 있는지 보지 않았고, 칸도 더하지 않았다(양식 밖 열을 만들지 않는다). CTS 관리대장에 컬렉션 건을 적을지는 고객 양식에 칸이 생기면 따로 다룬다.
- 문서에는 "Perform this task in every system" 이라는 문장도 있다(Role 을 시스템마다 만드는 대안). 안내에는 대안으로만 적었다.

Plugin version 0.10.202.
