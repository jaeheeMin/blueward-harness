# #921 scaffold Spec 관할에서 캡처 그림 빼기

## 배경

scaffold 가 까는 `rules/spec.yaml` 의 `관할: "docs/spec/**"` 가 `/harness:spec` 이 두라고 안내하는
`docs/spec/img/<이름>_v<판>.png` 까지 Spec 유형으로 잡았다. png 리더가 없어 doc-guard 가 "검사 불능"
(ConfigError)으로 멈췄다. 사례: blueward-26/public-cloud PR #606. public-cloud 는 #616 에서
`docs/spec/*.md` 로 고쳤다.

## 바꾼 것

- `plugins/harness/skills/scaffold/skeleton/rules/spec.yaml` 관할을 `docs/spec/*.md` 로, 이유 주석 추가.
- `checker/tests/test_scaffold.py` 에 시험 추가: skeleton rules 를 `loader.load` 로 읽고
  `resolve` 로 `docs/spec/DEV-001-x.md` 는 Spec 유형, `docs/spec/img/화면1_v0.1.png` 는 None.
- 길잡이 레일 표기 0.10.273, plugin.json 0.10.273, whats_new.json 항목.
- 스킬 문서·길잡이 본문에 Spec 관할을 `docs/spec/**` 로 적은 문장은 없었다(`rules/governance.md` 의
  `docs/spec/**` 는 사람 병합 경로 목록이라 그대로 뒀다).

## glob 함정

엔진 `_matches` 는 fnmatch 계열이라 `docs/spec/**/*.md` 는 `docs/spec/DEV-019-a.md` 를 못 잡는다
(`**/` 가 폴더 한 단계 이상을 요구). `*` 는 `/` 도 넘으므로 `docs/spec/*.md` 가 맞다.

## 시험 결과

- `PYTHONUTF8=1 uv run --group dev pytest checker/tests/test_scaffold.py -q` → 22 passed.
- 엔진 `_matches` 직접 확인: `docs/spec/**/*.md` 는 `docs/spec/DEV-019-a.md` False, `docs/spec/*.md` 는 True, `docs/spec/img/x.png` 는 둘 다 False.

## 남은 일

- 이미 만든 Project Repository 는 각자 `rules/spec.yaml` 관할을 고쳐야 한다(public-cloud 는 #616).
- 매뉴얼 관할(`skills/manual/manual.yaml` 의 `docs/manual/**/*.md`)은 매뉴얼 스킬이 작업본을
  `docs/manual/<LoB>/` 아래에 두게 정해서 지금은 문제없다. 고치지 않았다.
