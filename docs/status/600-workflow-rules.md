# #600 작업 순서 규칙 정리

규칙 문장끼리 어긋난 곳을 한 가지로 맞췄다(동작은 병합 문장만 빼고 그대로).

- 개발 순서: `rules/issue-and-release.md` 를 SRS → Spec → 개발 순서(`governance.md`·srs 스킬)에 맞췄다. SRS 를 거치지 않는 작은 개발은 start 로 바로 시작.
- Spec 병합 뒤 개발 시작: 원장 `리뷰` 인 DEV 는 start 가 `reserve_number.py review-reason --dev DEV-xxx` 로 GitHub PR 을 본다. 열린 같은 DEV PR 이 없고 그 DEV 의 Spec 을 담아 병합된 PR 이 있으면 묻지 않고 `진행`, 열린 PR 이 있거나 병합 Spec PR 을 못 찾거나 gh 실패면 묻는다. 판정이 결정적이고 시험이 필요해 스크립트에 뒀다(시험 6개 추가).
- 병합 문장: `governance.md` 의 "작성자 아닌 사람이 읽은 뒤 병합" 을 실제 동작(위험하지 않은 PR 은 검사 통과 시 자동 병합, 위험 PR 은 승인자 Approve, human-merge 경로는 사람이 병합)으로 고쳤다. deliver 13단계 문장도 맞춤.
- 미정 요구사항: srs(미결 사항에 남김)와 spec(그 자리에서 정함)을 둘 다 유지하고 서로의 경로를 한 줄씩 적었다.
- 길잡이 `docs/guide/harness-guide.html`: 작업 시작 `리뷰` 문장, 미정 행, 리뷰·병합 탭 문장을 같은 말로 맞췄다. 병합 뒤 아티팩트에 다시 올린다.
- plugin.json version 0.10.155.
