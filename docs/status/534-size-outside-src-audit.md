# #534 크기 승인 판정에서 src·audit 밖만 재기 (2026-10-29)

## 배경

크기 판정(`_crit_size`)은 PR 이 바꾼 모든 파일의 줄을 합쳤다. 예외(#436 `size_warn_only_paths`)는 바뀐 파일이 **전부** `src/` 아래일 때뿐이라, 개발 PR 이 Spec 한 줄만 같이 고쳐도 `src/` 전체 줄이 승인 사유가 됐다. #436 의 뜻("`src/` 는 활성화된 코드의 사본이라 크기로 막지 않고, 사람이 봐야 할 그 밖의 부분만 잰다")대로 `src/`·`audit/` 밖만 잰다.

## 바꾼 것

| 곳 | 내용 |
|---|---|
| `checker/risk_gate.py` | 설정 키 `size_exclude_paths`(문자열 목록, 기본 `[]` = 지금 동작). `size_excluded_split`(센 파일·뺀 파일로 나눔, 매칭은 `path_reasons` 와 같음), `_size_exceeded`(종류별 사유). `_crit_size`: 센 파일만으로 판정해 넘으면 승인 사유, 뺀 파일까지 합칠 때만 넘는 종류는 `note=True` 참고 |
| 두 키의 관계 | `size_exclude_paths` 를 먼저 적용한다. `size_warn_only_paths` 는 **센 파일**이 모두 그 아래일 때 남은 사유를 참고로 바꾼다(그대로 유지, 하위 호환). 설정 파싱은 기존 목록 키와 같다(목록이 아니면 `ConfigError` → 검사 불능) |
| scaffold `risk-gate.yaml` | `size_exclude_paths: [src/, audit/]`. `size_warn_only_paths: [src/]` 는 그대로 |
| `governance.md`, `docs/guide/harness-guide.html` | 설정 설명과 "승인이 필요할 때" 표(300줄·10파일 행) |
| `plugin.json` | `0.10.135` → `0.10.136` |

## 판정 예(max 300줄·10파일, `[src/, audit/]`)

| PR | 결과 |
|---|---|
| `src/` 400줄 + Spec 5줄 | 승인 사유 없음(크기), 참고 1건 |
| `src/` 만 | 참고만 |
| 밖만 301줄 | 승인 사유 |
| `src/` 400줄 + 밖 301줄 | 승인 사유(301줄). 줄은 이미 사유라 같은 종류 참고는 없다 |

## 남은 일

- public-cloud `.github/risk-gate.yaml` 에 `size_exclude_paths: [src/, audit/]` 추가(별도 PR, `.github` 변경이라 승인자 Approve 필요). 이 판이 stable 이 된 뒤(모르는 키 오류 방지).
- 길잡이는 병합 뒤 아티팩트에 다시 올린다.
