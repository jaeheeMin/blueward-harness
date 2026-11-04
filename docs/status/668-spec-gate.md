# #668 Spec 없이 개발을 시작·병합하지 못하게 막기 (2026-11-04)

## 배경

규칙은 "SRS → Spec → 개발 순"이고 Spec 없이 개발은 없다(SRS 에서 설정으로 정한 건은 개발이 아니다). 그런데 start 도 PR 검사도 Spec 이 있는지 보지 않았다. public-cloud DEV-010 은 SRS·Spec 없이 개발돼 원장 `완료` 다.

## 이번 PR 의 범위

판정 엔진, PR 검사 단계(`spec-ready`), start 의 미리 막기, 규칙·길잡이·workflow.json. **웹 콘솔 부분(이슈 4번)은 같은 파일을 고치는 PR #669 가 병합된 뒤 따로 한다.**

## 규칙

- `src/` 아래 파일이 하나라도 바뀌면 대상이다(README·package.devc.xml·템플릿도 개발 변경). 없으면 해당 없음(통과, 코멘트 없음).
- DEV 번호는 `pr_queue._order_devs` 로 찾는다(제목 끝 `(DEV-…)`·제목·브랜치·바꾼 Spec 파일, 모두 없으면 본문 첫 번호). 여럿이면 각각 판정.
- 통과: 찾은 모든 DEV 의 `docs/spec/DEV-<번호>-*.md` 가 base(병합 대상 브랜치)에 있다.
- 위반: DEV 못 찾음 / Spec 이 base 에 없음(같은 PR 에서 Spec 을 새로 추가해도 위반 — Spec 은 먼저 따로 승인·병합) / 원장 Spec 칸이 `설정` 인 DEV 의 `src/` 변경.
- 검사 불능(종료 2): PR·바뀐 파일·base 의 Spec 목록·원장을 읽지 못함, 파이썬 예외. 원장 폴더가 base 에 없으면 원장을 안 쓰는 저장소로 보고 Spec 판정만 한다. `docs/spec/` 이 base 에 없고 `src/` 변경이 있으면 위반(Spec 없음).
- PR 제목·본문만 고치면 검사가 다시 안 돈다(트리거에 `edited` 없음, #411). 트리거를 늘리지 않고 사유에 "새 커밋을 올리거나 Actions 에서 Re-run" 으로 안내한다.

## 바뀐 것

| 곳 | 내용 |
|---|---|
| `checker/spec_ready.py`, `scripts/spec_ready.py` | 판정 엔진과 얇은 진입점(`ledger_stale.py`·`ledger_ready.py` 와 같은 모양, 종료 0/1/2) |
| `.github/workflows/pr-checks.yml` | `spec-ready` 단계(ledger-ready 뒤·early-status 앞), early-comments 마커 `<!-- spec-ready -->`, 종합 `judge`, 코멘트 실패 경고. commit status 는 안 단다 |
| `plugins/harness/skills/start/SKILL.md`, `reserve_number.py` | `list` 의 `ledger` 에 `spec`(원장 Spec 칸) 추가. Spec 이 main 에 없는 개발(기존 DEV·하위 작업·새 개발)은 시작하지 않고 `/harness:spec`(새 개발은 SRS·Spec 먼저)을 안내하고 멈춘다. 설정 건은 막지 않는다. 목록을 못 읽으면 멈춘다 |
| `plugins/harness/workflow.json` | dev 갈래 start 단계 hint·근거 |
| `plugins/harness/rules/governance.md` | "SRS → Spec → 개발 순" 아래에 이 관문 |
| `docs/guide/harness-guide.html` | 검사 표 `spec-ready`, 작업 시작 탭의 멈춤, 레일 판 표시 0.10.173 |
| `plugin.json` | 0.10.173 (열린 PR #669 가 0.10.171, #671 이 0.10.172) |

## public-cloud 최근 PR 47개에 대입한 결과 (조사)

- Spec 먼저 병합돼 통과 28
- 같은 PR 에서 Spec 을 만들며 개발 2 (이 규칙이면 위반)
- Spec 없음 8 (DEV-010 3, DEV-001 5)
- DEV 를 못 찾음 9 (GRIV 4 등)

DEV-010·GRIV 는 public-cloud 쪽에서 SRS·Spec 을 올리는 중이다(plugin-help 세션). 켜지면 그 전까지 DEV-010 소스 변경 PR 은 막힌다.

## 검토 지적과 처리

| 지적 | 처리 |
|---|---|
| start 의 새 멈춤이 `/harness:spec`·`/harness:srs` 가 부르는 경로까지 막아 Spec 을 쓸 수 없는 교착 | SKILL.md 에 srs·spec 이 부르는 경로에는 이 멈춤을 적용하지 않는다고 명시 |
| `src/` 를 안 바꾸는 feat·fix(템플릿·규칙·문서)까지 막힘 | 멈춤 조건을 "이번 작업이 `src/` 를 바꾸는 개발" 로 좁힘. 사용자가 직접 불렀고 애매하면 `AskUserQuestion` 으로 개발인지 묻는다. 새 번호 찜 경로도 같은 조건. workflow.json quote·hint, 길잡이 문장도 맞춤 |
| 본문 첫 번호 폴백이 아무 번호(REQ 포함)나 잡아 통과 | 본문은 `_order_devs` 에 넘기지 않고, 제목·브랜치·Spec 파일로 못 찾을 때만 `DEV-xxx 하위 작업`·`진행 원장: DEV-xxx`·`## 진행 원장` 절의 DEV 번호를 읽는다(`spec_ready.body_devs`). 코드·인용·주석 안은 무시. 본문에 스친 번호만 있으면 DEV 못 찾음 위반 |
| 시험 보강 | `srcx/`·`docs/src/` 는 대상 아님, 파일 120개 PR, 삭제·이름 바꾸기(previous_filename), base 가 main 이 아닌 PR, 본문 표시 3종·스친 번호 4종 |

## 고친 판정을 public-cloud 에 다시 대입 (읽기 전용)

최근 병합 PR 150개 중 `src/` 를 바꾼 47개. 기준: 그 PR 의 병합 커밋의 첫째 부모(병합 직전 main)에 `docs/spec/DEV-…` 가 있는가. 대입 스크립트는 저장소에 넣지 않았다.

| 결과 | 개수 | 비고 |
|---|---|---|
| 통과(Spec 먼저) | 28 | 본문 규칙을 좁힌 뒤에도 위반으로 바뀐 PR 없음. 본문 표시로 DEV 를 찾은 통과는 #263 하나(`DEV-002 하위 작업` 류 표시) |
| 같은 PR 에서 Spec | 2 | #208(DEV-005), #367(DEV-011) |
| Spec 없음 | 8 | DEV-010 #347·#380·#382, DEV-001 #368·#396·#402·#407·#412 |
| DEV 못 찾음 | 9 | #232(src 스냅샷 chore), 회계전표 스냅샷 #326~#329, GRIV #441·#447·#457·#469 |

본문 규칙 변경 전·후로 찾은 DEV 가 달라진 PR 은 47개 중 없다.

## 남은 일 / 한계

- 웹 콘솔(종류 버튼에 가능 여부 미리 보이기, AI 추천을 덮지 않고 묻기)은 #669 병합 뒤 따로.
- 원장 Spec 칸 `설정` 만 본다. SRS 의 다음 단계 `설정` 은 읽지 않는다(DEV 와 REQ 번호를 잇는 규칙을 새로 짜지 않았다).
- 열린 Spec PR 안내는 열린 PR 목록 100개 안에서 제목·브랜치·본문으로 DEV 를 잡은 것만 본다. 못 읽으면 생략한다.
- start 와 엔진은 같은 정의(base=origin/main 의 `docs/spec/DEV-…`)지만 코드가 둘이라, `test_spec_ready.py` 가 파일명 규칙이 같은 번호를 내는지 고정한다.
