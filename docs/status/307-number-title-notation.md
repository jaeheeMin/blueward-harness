# #307 REQ·DEV 번호 뒤에 괄호로 제목을 붙이는 표기 규칙 (2026-10-14)

번호만 보면 무슨 일인지 헷갈린다는 요청(public-cloud 세션)으로, `REQ-002(판매오더 조회 앱)` 처럼 번호 바로 뒤 괄호에 SRS 제목을 붙이는 규칙을 `plugins/harness/rules/issue-and-release.md` 의 "REQ·DEV 번호를 말할 때" 절에 넣었다(번호 체계를 다루는 문서가 이슈 제목 규칙의 그 파일이라서). CLAUDE.md 규칙 색인 한 줄을 맞췄다.

적용: Claude 답변·보고, 스킬 안내(srs 찜한 번호 표 밖 문장, start 개발 목록 보기·겹침 알림, spec 후보 목록·마무리 안내, deliver 보고와 PR 본문 `## 진행 원장` 예시). 범위 밖: 이슈 제목 `[DEV-xxx]`, 하위 작업 제목 끝 `(DEV-xxx)`, 파일명, 명령·코드·경로. 판단 — 표에 제목 열이 이미 있으면(srs 찜한 번호 표, start 개발 목록 표) 번호 칸에 제목을 또 붙이지 않는다. wrapup 은 이슈 번호(#)만 보고하므로 건드리지 않았다. 제목을 모르면 SRS, 없으면 이슈 제목·원장 내용, 그것도 없으면 `(제목 미확인)`, 추측 금지.

길잡이: "번호 하나로 다 이어진다", "내 번호 알아 두기", 주의사항 총정리 "항상 해", 용어 사전 "REQ · DEV 번호" 에 한 줄씩, 레일 harness 0.10.66. Plugin version 0.10.66(main 이 0.10.65(#305 병합)라 그다음).

미결 — 코드가 사람에게 내는 메시지의 번호는 이번에 바꾸지 않았다: `checker/pairing.py`(원장 중복·Spec 칸·번호 불일치 등 `DEV-nnn`/`REQ-nnn` 메시지), `checker/overlap.py`(`DEV-nnn` 라벨), `checker/risk_gate.py`(번호 언급 위험 사유), `plugins/harness/skills/start/reserve_number.py`(출력 JSON 의 번호). 후속 이슈 #308.
