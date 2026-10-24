# #433 public 저장소의 회사 식별 값을 예시 값으로 바꾸고 사내 전용 라이선스 추가 (2026-10-24)

## 배경

이 저장소는 Actions 분을 아끼려고 public 이다. 그런데 시험 코드에 실제 SAP 테넌트 주소와 트랜스포트 번호가 있었고, 라이선스 파일이 없었다. 테넌트 주소만으로 침입되지는 않지만(로그인은 회사 SSO) 공격 대상을 특정하는 정보라 공개할 이유가 없다.

## 찾은 것과 처리

`git grep -n -I -i -E` 로 `my\d{6}`, `s4hana.cloud`, `Z5U`, `CB99…`, `blueward.co.kr`, `partners.blueward`, `webhook.office`, `logic.azure` 를 찾았다.

| 값 | 위치 | 처리 |
|---|---|---|
| 테넌트 호스트 `my406740…` | `test_activation_gate.py`, `test_mcp_source_guard.py` | `my000001.s4hana.cloud.sap` |
| 테넌트 호스트 `my406600…` | `test_adt_tiers.py` | `my000002.s4hana.cloud.sap` |
| 트랜스포트 `Z5UK900001` | `test_activation_gate.py`, `test_mcp_source_guard.py` | `XXXK900001` |
| 시스템 ID `Z5U` | `test_adt_tiers.py`(YAML 예시와 단언), `plugins/harness/hooks/adt_tiers.py` 독스트링 | `XXX` |
| 쿠키 이름 `SAP_SESSIONID_Z5U_080` | `checker/gitleaks/harness.toml`·`plugins/harness/hooks/gitleaks-harness.toml` 주석, `test_gitleaks_scan.py`, `test_git_guard_secret_scan.py` | `SAP_SESSIONID_XXX_080` (규칙 정규식은 `[A-Z0-9]{3}` 라 모양이 같다) |
| 계정 ID `CB99…` | 없음 | - |
| 회사 이메일·도메인, Teams 웹훅 | 없음. `test_risk_gate.py` 의 `logic.azure.com` 은 가짜 주소(`sig=Zx9_…`)이고 `t@example.com` 류는 예시 | 유지 |

시험은 값이 아니라 모양(`corrNr` 쿼리, 호스트가 `*.s4hana.cloud.sap` 인지, 서버 이름)만 본다. 바꾼 뒤 동작은 같다.

## 유지한 것과 이유

| 값 | 이유 |
|---|---|
| MCP 서버 이름 `abap-adt-z5u`, `abap-adt-z5u-dev` (시험, README, 길잡이, `docs/status/`) | 훅이 `mcp__<서버>__<도구>` 이름을 읽는 동작 식별자다. 바꾸면 시험과 길잡이가 실제 `.mcp.json` 과 어긋난다 |
| `jaeheeMin`, `blueward-harness`, `blueward-26`, `public-cloud`, GitHub 아이디, 회사명 블루워드 | 저장소 주소·승인자 예시·브랜드. 바꾸면 동작이 깨진다 |
| 클라이언트 번호 `080`·`100` | 회사 식별 값이 아니다 |

## 재발 방지 판단 (구현하지 않음)

gitleaks `harness.toml` 에 `my\d{6}\.s4hana\.cloud\.sap` 규칙을 더하면 어떻게 되는지 읽었다.

- 이 규칙 파일은 Project Repository 도 쓴다(재사용 워크플로, 커밋 전 훅). Project Repository 의 `env/adt-tiers.yaml` 에는 실제 호스트(`host:`)를 적는 것이 정상이다(`adt_tiers.py` 는 `host` 를 무시하는 사람용 정보라 적게 되어 있다). 그러므로 테넌트 호스트 규칙은 그 파일을 매번 위반으로 잡는다.
- 허용 목록(`[allowlist]` 에 `env/adt-tiers.yaml`)을 Project Repository 마다 두면 풀리지만, 고객사 저장소 전부에 설정을 배포해야 한다. 그리고 호스트는 비밀값이 아니라 식별 정보라 gitleaks 의 "비밀" 규칙과 성격이 다르다.
- 이 저장소만 보호하려면 이 저장소 자체 시험(`my\d{6}` 이 `git ls-files` 에 없을 것)으로 충분하고 엔진 규칙을 건드리지 않는다.

의견: **gitleaks 규칙은 하지 말자.** 오탐이 Project Repository 에서 난다. 다시 막고 싶으면 이 저장소 전용 시험 하나(추적 파일에 `my\d{6}\.s4hana` 와 `Z5UK` 가 없음, 이 파일과 서버 이름 예외 없이)를 별도 이슈로 하자. 이번 이슈에서는 만들지 않았다.

## 라이선스

저장소 꼭대기 `LICENSE`(한국어 + 영어): 저작권자 jaeheeMin (Blueward), 블루워드 사내와 블루워드가 수행하는 고객사 프로젝트에서만 사용 허가, 그 밖의 복제·배포·수정·재사용 금지, 공개 저장소에 있다는 사실이 사용 허가를 뜻하지 않음, 무보증·책임 없음. `README.md` 맨 아래에 한 줄 안내.

## 버전

`plugins/harness/` 의 독스트링과 gitleaks 설정 파일 주석이 바뀌었다(동작은 같다). 배포 파일이 바뀌었으므로 plugin.json `0.10.106` → `0.10.107`. 길잡이의 판 표기는 병합 뒤 갱신 때 맞춘다.

## 알려진 한계

- **git 이력에는 옛 값이 남는다.** 지난 커밋과 이전 PR 의 diff 에서 옛 호스트와 트랜스포트 번호를 볼 수 있다. 이력을 다시 쓰려면 강제 푸시가 필요해 규칙상 금지이고 이 이슈 범위 밖이다. 필요하면 사람이 따로 결정한다.
- 표에 적은 대로 서버 이름의 `z5u` 는 시스템 ID 의 흔적이지만 동작 식별자라 남아 있다.
