# #436 소스만 바꾼 개발 PR 은 크기 기준을 승인 대신 경고로 (2026-10-25)

## 배경

우리 개발 PR 의 `src/` 는 080 에서 이미 활성화된 코드의 스냅샷이라 승인할 때쯤 코드는 이미 돌고 있다. 그런데 크기 기준(300줄·10파일)이 ABAP 스냅샷 거의 전부에 걸려 열린 PR 대부분이 "위험" 이 됐고 승인이 형식이 됐다. 결정: 소스만 바꾼 개발 PR 은 크기로 승인을 요구하지 않고 경고만 한다.

## 바꾼 것

| 곳 | 내용 |
|---|---|
| `checker/risk_gate.py` | 설정 키 `size_warn_only_paths`(문자열 목록, 기본 `[]`). `Finding.note`. `_crit_size`: 목록이 비어 있지 않고 PR 이 바꾼 파일이 모두 그 접두어 아래면 크기 사유를 `note=True` 로 낸다(문구 끝에 " — 소스만 바뀐 PR 이라 승인은 필요 없음(경고)"). 접두어 매칭은 `path_reasons` 와 같은 `_normalize`·`human_merge_hits` |
| 결과 JSON | `notes` 를 새로 둔다. `reasons`·`risk`·`requires_approval` 에는 note 를 넣지 않는다(옛 소비자가 위험으로 오해하지 않게). `decide_pr`·`precheck_pr`(`risky`·`reasons`·`criteria` 도 note 제외)·`_disabled_result`·`_unknown` 에 있고, `decide_commit` 의 직접 커밋 경로는 note 를 위험으로 세지 않는다 |
| `.github/workflows/pr-checks.yml`·`pr-review.yml`·`risk-gate.yml` | 코멘트 스크립트에 "참고(승인 필요 없음)" 절. 위험하지 않고 notes 만 있으면 코멘트를 지우지 않고 "ℹ️ 참고" 코멘트를 남긴다. 위험한 PR 은 이유 아래에 같은 절이 붙는다 |
| scaffold `risk-gate.yaml` | `size_warn_only_paths: [src/]` 와 주석 |
| `governance.md`, `docs/guide/harness-guide.html` | "위험도에 따른 승인" 절과 "승인이 필요할 때" 표(300줄·10파일 행) |
| `plugin.json` | `0.10.107` → `0.10.108` |

## note 가 흐르는 길

- 만드는 곳: `_crit_size` 한 곳.
- 승인 사유에서 빠지는 곳: `decide_pr`·`precheck_pr` 가 `evaluate` 결과를 note 와 아닌 것으로 나눈다. `decide_commit` 의 직접 커밋 경로는 note 를 거른다. 병합 뒤 감지의 PR 경로는 `decide_pr` 의 `requires_approval` 을 읽으므로 따로 고칠 것이 없다.
- 읽는 쪽 확인: `pr_queue._risk_gate_view` 는 코멘트의 "이유" 아래 `- ` 줄만 사유로 읽고 "사람의 승인이 필요합니다"·"승인됨"·"검사 불능" 문구로 종류를 가른다. 참고 절은 "이유" 로 시작하지 않고 그 문구도 없어 사유로 읽히지 않는다(그리고 참고 코멘트는 risk-gate 가 통과일 때만 남아 pr_queue 가 읽지 않는다). `pr_approvals` 는 `_risk_gate_view` 만 쓴다. 병합 훅(`pre-bash-git-guard.sh`)은 `reasons` 만 읽는다. `ai-review.yml` 은 `risky`·`reasons`·`criteria` 만 읽는다. 모두 고치지 않았다.

## 알려진 한계

- 이름 바꾸기(rename)로 `docs/spec/` 에서 `src/` 로 옮긴 파일은 새 이름(`filename`)만 본다. 위험 경로 기준(`paths`)도 같다.
- public-cloud 적용(`risk-gate.yaml` 에 키 추가)은 이 판이 stable 이 된 뒤 그쪽 PR 로 한다.
- 길잡이는 병합 뒤 아티팩트에 다시 올린다. 판 표기(0.10.108)는 그때 맞춘다.
