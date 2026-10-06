# conventions

이 프로젝트에서만 통하는 Convention 을 둔다. 예를 들어 커스텀 필드 이름의
접두사를 Z 나 Y 로 고정하는 것, SAP Public Cloud naming rule, 고객사가 정한
코딩 표준처럼 이 프로젝트 안에서만 지키면 되는 규칙이다.

어느 프로젝트에서나 같은 규칙은 여기 두지 않는다. 그런 규칙은 harness
Plugin 의 [공통 개발 규칙](https://github.com/jaeheeMin/blueward-harness/blob/main/plugins/harness/conventions/common.md)
(CR-001 ~ CR-008)에 있다. 세션 시작 훅이 그 목록을 매번 요약해 보여 준다.

두 규칙이 부딪히면 이 폴더의 Convention 이 이긴다. 다만 공통 규칙의
CR-004(비밀정보)만은 예외 없이 지킨다 — 이 폴더의 어떤 파일로도 뒤집지
못한다.

파일은 주제별로 나눠 둔다. 예: 이름 접두어와 네이밍 규칙은
`naming.md`, 고객사 코딩 표준은 `coding-standard.md` 처럼 나눈다.

scaffold 가 블루어드 사내 표준을 기본값으로 두 파일 만들어 둔다.

| 파일 | 내용 |
|---|---|
| `naming.md` | SAP S/4HANA Public Cloud & BTP 객체 이름 규칙(Naming Guide v1.2 정리) |
| `cap-ui5.md` | CAP·SAPUI5 개발 표준(코딩 규칙, 폴더 구조, 이름 규칙)(개발표준 정의서 v1.0 정리) |

고객사 표준이 정해지면 이 두 파일을 고친다. 이미 같은 이름의 파일이 있으면
scaffold 는 덮어쓰지 않는다.
