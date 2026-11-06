# #736 risk-gate 완화: 크기는 경고만, Spec 은 새 파일만 승인 (2026-11-07)

## 배경

크기 초과(300줄·10파일)와 Spec 수정이 승인 사유가 되어, 개발 흐름에서 승인 대기가 잦았다. 이슈 #736.

## 결정

- 크기: 새 설정 `size_gate`(기본 `false`). false 면 줄·파일 수 초과를 `note=True` 참고로만 낸다. `true` 면 이전 동작(`size_exclude_paths`·`size_warn_only_paths` 포함). `max_changed_*` 키와 기본값 300/10 은 그대로.
- Spec: `docs/spec/` 는 PR files 의 status 가 `added` 인 파일만 위험 경로로 센다. `modified`·`renamed`·`removed`·`changed`·`unchanged` 는 센 목록에서 뺀다. status 가 없거나 `copied`·처음 보는 값이면 새 파일로 보고 센다(메인 검토에서 고침 — 확인 못 한 것을 승인 불필요로 뭉개지 않는다, 원칙 7). SRS(`docs/ssot/`)·`rules/`·`.github/` 와 `.github/human-merge-paths` 는 그대로.
- 비밀값·CR-009·AI 리뷰·다른 검사 실패·검사 못 한 파일(unscanned) 사유는 건드리지 않았다.

## 바꾼 파일

| 곳 | 내용 |
|---|---|
| `checker/risk_gate.py` | `size_gate` 설정(DEFAULT_CONFIG, `_BOOL_KEYS`), `_crit_size` 의 false 분기, `_crit_paths` 의 Spec 필터(`_is_spec_path`). PR 검사·pr-review·main 직접 커밋 판정이 모두 `Context` 를 지나므로 한 곳에서 처리된다. size 계산 등 다른 기준의 파일 목록은 그대로 |
| `checker/tests/test_risk_gate.py` | 크기를 위험으로 기대하던 시험은 `size_gate: true` 로 고침. 새 시험: 기본 false 경고만, true 위험, Spec added/modified/renamed/removed, SRS 수정, SRS+Spec 혼합 |
| `plugins/harness/rules/governance.md`, `commit-and-pr.md` | 위험도 절·설정 설명·PR 나누기 절 정정 |
| `skills/scaffold/skeleton/dot-github/risk-gate.yaml` | `size_gate: false` 와 주석 |
| `skills/{spec,deliver,start}/SKILL.md`, `workflow.json` | "Spec 을 고치면 승인" 문장 정정, `quote` 맞춤 |
| `docs/guide/harness-guide.html` | "승인이 필요할 때" 표와 callout, risk-gate 설명 |
| `plugin.json` | `0.10.186` → `0.10.196` (main 0.10.186, 열린 PR 최대 0.10.195) |

## 남은 일

- 이 저장소 밖 Project Repository(public-cloud 등)의 `.github/risk-gate.yaml` 은 기본값이 바뀌어 별도 조치 없이 적용된다. 크기 승인을 계속 쓰려면 `size_gate: true` 를 적어야 한다.
- 같은 `docs/spec` 판단을 하는 다른 소비처 점검 결과는 PR 설명 참고. 길잡이는 병합 뒤 아티팩트에 다시 올린다.
