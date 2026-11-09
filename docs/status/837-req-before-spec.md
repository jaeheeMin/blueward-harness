# #837 SRS 요구사항 없는 Spec 작성과 개발 시작 막기 (2026-11-09)

## 배경

public-cloud 의 DEV-010(이슈 #340, 10-21)과 DEV-011(이슈 #366, 10-23)은 SRS 요구사항(REQ) 없이 개발됐고, DEV-011 Spec 은 뒤에 "REQ-011 안(SRS 에 아직 안 올림)" 으로 쓰였다. 그때는 막는 장치가 없었다. start 의 Spec 확인과 `spec-ready` 는 #668(11-04)부터다. 그런데 #668 이후에도 REQ 없는 Spec 은 경고(`pairing` 의 `spec_without_req`)만으로 통과했고, start·`spec-ready`·콘솔은 Spec 파일 유무만 봐서 그 구멍을 이어받았다.

## 새던 곳

| 단계 | 전 | 후 |
|---|---|---|
| `/harness:spec` | 특정 REQ 가 없어도 "SRS 를 거치지 않는 개발" 이면 찜한 `[DEV-xxx]` 로 Spec 을 썼다 | origin/main SRS 요구사항 표에 REQ 가 없으면 Spec 을 쓰지 않고 멈춰 `/harness:srs` 를 안내한다. 새 번호 찜(`claim`)도 하지 않는다 |
| PR 검사 | `pairing` 경고뿐 | `spec-ready` 둘째 관문: 이 PR 이 새로 만들거나 바꾼 Spec 의 REQ 가 base·head SRS 어디에도 없으면 위반 |
| `spec-ready` 첫 관문(`src/`) | Spec 파일 유무만 | 그대로(Spec 유무). REQ 는 둘째 관문이 본다 |
| `/harness:start` | Spec 이 main 에 있으면 시작 | `list` 의 `req` 키가 없으면(REQ 가 SRS 에 없음) 시작하지 않고 srs 부터 안내 |
| 웹 콘솔 개발 갈래 | Spec 있는 건 수만 봄 | REQ 없는 건은 Spec 있는 건에 안 세고 `noReq` 로 따로 알린다 |
| 훅 | REQ 를 안 봄 | 바꾸지 않음(범위 밖) |

## 바꾼 것

- `checker/pairing.py`: `covered_dev_numbers(text)` — SRS 본문에서 DEV 에 대응하는 번호(REQ 번호, `Development RICEFW ID` 칸의 DEV)를 낸다. 읽지 못하면 `CannotCheck`.
- `checker/spec_ready.py`: 둘째 관문 `_spec_without_req`(위반 종류 `no_req`). 판정 위치는 `check_pr` 첫머리이고 `src/` 변경 여부와 무관하다. 삭제된 Spec 은 보지 않는다. base 에 `audit/ledger/` 가 없거나 SRS 가 base·head 어디에도 없으면 건너뛴다(기존 동작, 이 플러그인 저장소 포함). SRS 를 읽지 못하거나 표를 해석하지 못하면 검사 불능(종료코드 2). 메시지는 쉬운 말 + "다음: `/harness:srs` 로 REQ-xxx 를 먼저 올립니다". `pr-checks.yml` 은 실패 사유 문구와 설명 주석만 고쳤다.
- `plugins/harness/skills/spec/SKILL.md`: "Spec 번호" 의 SRS 를 거치지 않는 개발 허용 문장을 REQ 없으면 멈춤 원칙으로 바꾸고, 만들기 1·2·3 단계와 고치기 1 단계를 맞췄다. `Dropped`·`Duplicate`·`On Hold`, 다음 단계 `설정`·`표준` 처리는 그대로다.
- `plugins/harness/skills/start/reserve_number.py`·`SKILL.md`: `list` 의 `devs[]` 에 `req: true`(SRS 표에 그 번호의 REQ 가 있거나 RICEFW ID 칸이 그 DEV 를 가리킴)를 더하고, 없으면 시작을 멈춘다.
- `plugins/harness/console/devready.py`·`static/flow-logic.js`: `noReq`·`noReqCount`, 종류 버튼 밑 글과 개발 막기 문구.
- `docs/guide/harness-guide.html`(Spec 만들기·작업 시작하기 탭), `plugins/harness/workflow.json`(spec·start 단계 hint 와 근거 문장), `whats_new.json`, plugin.json 0.10.244.

## 옛 Spec 은 경고만 두는 이유

이미 main 에 있는 옛 Spec(DEV-010·011 등)을 막으면, 그 Spec 을 건드리지 않은 무관한 PR 까지 막힌다. 그래서 이 PR 이 건드린 Spec 만 위반으로 보고 나머지는 `pairing` 경고(`spec_without_req`, `ledger_without_req`)로 둔다. 옛 Spec 을 고치려면 REQ 부터 SRS 에 올려야 한다(DEV-010·011 의 SRS 사후 등록은 이 이슈 밖 — 그쪽 담당·PO 결정).

## SRS 와 Spec 을 한 PR 에

PR 검사는 head SRS 에 REQ 가 있으면 통과로 본다(한 PR 에 같이 올리는 흐름이 허용이다). 다만 `/harness:spec` 스킬은 origin/main 에 REQ 가 병합돼 있어야 Spec 을 쓰기 시작하므로 스킬 순서와는 다르다.

## 확인하지 못한 것

- 실제 GitHub Actions 에서의 실행(시험은 가짜 GitHub 클라이언트로 했다). 포크 PR 은 head 커밋을 `repo` 에서 읽으므로 읽지 못해 검사 불능이 될 수 있다.
- `Development RICEFW ID` 칸이 여러 DEV 를 쉼표로 적은 SRS 는 모두 대응으로 읽는다.
- 이 관문은 REQ 가 표에 있느냐만 본다. 다음 단계가 `설정`·`표준` 인 REQ 에 Spec 이 달린 경우는 따로 막지 않는다(기존 동작).
- `rules/governance.md`·`docs/design/web-console.md` 의 서술은 고치지 않았다.
