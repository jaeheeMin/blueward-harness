# #503 객체 겹침 경고를 이 PR 의 Spec 과 공용 아닌 객체로 좁히고 문구 수정 (2026-10-28)

## 배경

- 객체 겹침 경고(#292)가 public-cloud 최근 PR 16개에 모두 같은 `Message Class ZPP` 경고로 떴고 쓸모 있는 경고가 없었다.
- Spec 하나만 바뀌어도 저장소 전체 Spec 을 비교해 무관한 기존 겹침이 매번 떴다.
- Message Class 는 여러 개발이 번호를 더해 같이 쓰는 공용 객체라 겹침이 정상이다.
- 문구("두 사람이 동시에 고치면 충돌")가 원래 목적(한 개발이 DEV 둘로 쪼개진 것 잡기)과 달라 위험 신호로 오해됐다.

## 결정

- `check_overlap(root, changed_specs=None)`: 바뀐 Spec 이 하나라도 낀 겹침만 경고한다. 안 낀 겹침은 `unrelated` 개수로만 남긴다. None 이면 전부 본다. `check_changed.py` 가 바뀐 파일(found, 지워진 파일 제외) 중 `docs/spec/` 경로를 posix 로 넘긴다.
- 공용 종류는 `rules/cross-checks/shared-objects.yaml` 의 `공용_종류`(문자열 목록). 파일·키가 없으면 `["Message Class"]`, `[]` 이면 제외 없음. 비교는 앞뒤 공백·대소문자 무시. 모르는 키·목록 아님·문자열 아님·깨진 YAML 은 겹침 결과를 검사 불능(`config_error`, 사유에 파일 경로)으로 낸다. 하위 폴더라 규칙 로더(rules/ 최상위만 읽음)가 건드리지 않음을 시험으로 확인했다.
- 판단 — 순서: 먼저 바뀐 Spec 이 낀 그룹인지 보고, 낀 그룹 중 공용 종류를 `shared` 로 센다. 무관한 그룹은 종류와 상관없이 `unrelated` 로만 센다(무관한 공용 겹침까지 매번 "공용 n건" 으로 뜨는 소음을 막는다). 조용히 빼지 않고 둘 다 코멘트에 개수가 남는다.
- 판단 — 설정 오류 시 경고를 내지도, 전부 경고하지도 않는다. 어느 겹침을 빼야 할지 모르기 때문이다(원칙 7).
- 문구: "이 PR 이 바꾼 Spec 이 다른 Spec 과 같은 객체를 만들거나 고칩니다. 한 개발이 DEV 둘로 나뉜 것은 아닌지 확인하십시오. 따로 할 일이 맞으면 그대로 두어도 됩니다." 0 이 아닐 때만 "이 PR 과 무관한 기존 겹침 n건, 공용 객체(종류) 겹침 n건은 경고하지 않았습니다." 한 줄을 붙인다.
- 스켈레톤에 `shared-objects.yaml` 을 더하고 `test_scaffold` 기대 목록·스켈레톤 `rules/README.md`·`checker/README.md`·길잡이 검사 표 행을 고쳤다.
- plugin version 0.10.128.

## 남은 일

- 병합 뒤 길잡이 아티팩트에 다시 올린다(`docs/guide/README.md`).
- 이미 만든 Project Repository 에는 `shared-objects.yaml` 이 자동으로 오지 않는다. 없어도 기본값(Message Class)이 적용된다.
- 이 파일은 v0.10.128 이상 엔진이 읽는다. 옛 엔진은 파일을 모르고 전체를 경고한다(해롭지 않다).
