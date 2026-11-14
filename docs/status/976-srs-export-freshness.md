# #976 산출 엑셀이 SRS 와 어긋난 채 병합·전달되지 않게 확인 (0.10.294)

## 배경
산출 PR(`버전:` +0.1, 그 판 Backlog 엑셀)을 연 뒤 다른 내용 PR 이 먼저 병합되면 충돌 없이 병합돼 엑셀이 main SRS 보다 낡는다(ruleset `strict:false`, GitHub 는 base 가 바뀌어도 검사를 다시 돌리지 않는다).

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/srs_export_check.py` (새) | `compare`(SRS 로 엑셀을 저장소 밖에 다시 만들어 칸 값 비교: same/differ/cannot_check), `merge-guard`(PR head 와 base 의 SRS 가 `버전:` 줄 말고 같은지), `push-check`(push 가 엑셀을 추가했을 때만 compare) |
| `checker/readers/xlsx.py` | `read_values`(시트의 값 행들) 추가 |
| `scripts/check_changed.py`, `scripts/render_report.py` | PR 이 엑셀을 추가했으면 `srs_split` 결과에 `stale_xlsx` 위반·검사 불능을 합침, 코멘트 제목 문구 |
| `plugins/harness/hooks/pre-bash-git-guard.sh` | `gh pr merge` 에 0-3 단계: 산출 PR 이고 base 의 SRS 가 바뀌었으면 거부, gh·엔진 실패는 검사 불능으로 거부 |
| `.github/workflows/main-checks.yml` | `srs-export`·`srs-export-issue` 단계, 종합 판정에 추가 |
| `plugins/harness/skills/srs/SKILL.md` | 산출 모드 8단계: 병합 뒤 main 에서 compare, same 일 때만 보내도 된다고 말함 |
| 길잡이·README·`whats_new.json`·`plugin.json` | 설명, 0.10.294 |
| `checker/tests/test_srs_export_check.py` 외 | 시험 |

## 결정
- 비교는 양식 지도 표가 쓰는 시트·열의 머리글 행부터 끝까지 칸 값이다. 바이트 비교는 하지 않는다. 산출이 날짜·시각을 넣지 않아(`checker/export.py` 에 `now`·`today` 호출 없음, zip 항목 시각도 템플릿 것) 같은 SRS 면 값이 같다.
- PR 검사는 `SRS_분리` 스위치를 같이 쓴다(새 키 없음). 같은 기능의 연장이고, 새 키를 만들면 스캐폴드·README·교차 스위치 시험이 같이 늘어난다.
- 훅은 로컬 `origin/main` 이 아니라 gh API 로 base 브랜치의 지금 SRS 와 PR head 를 읽는다(로컬은 fetch 전이면 낡아 병합 직전 판단에 부적합). 양식 지도는 작업 폴더의 것을 쓴다.
- main push 검사는 `has_doc_guard != 'false'` 일 때 돈다(docs/** 가 걸려 엑셀 추가는 항상 해당). 불일치는 job 실패 + 이슈, 확인 불능도 job 실패(원칙 7).

## 남은 일
- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- `main-checks.yml` 실제 실행은 병합 뒤 `stable` 로 배포돼야 확인된다.
