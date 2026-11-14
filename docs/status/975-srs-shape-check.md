# #975 SRS 모양 검사 `srs_shape` 규칙 종류 추가 (0.10.293)

## 배경
SRS 를 여럿이 동시에 고치면 git 이 충돌 없이 합쳐도 같은 REQ 표 행·상세 절·`버전:` 줄이 둘이 된다. 상세 절 중복과 표 행 없는 상세 절은 산출 때(`export.py`)만 잡혔고, 표 행 중복과 상세 절 없는 표 행은 어디서도 안 잡혔다.

## 한 것
| 파일 | 내용 |
|---|---|
| `checker/rules/srs_shape.py` | 새 규칙 종류. 머리(첫 `##` 앞)의 `버전:` 줄 1개, 표 REQ 집합 = `### REQ-n` 절 집합(한쪽에만 있는 번호를 각각 밝힘), 표 행·절 중복 금지. 표·절은 `pairing.section_span`·`table_indexed`, 절은 `req_cross_reference.parse_sections` 를 다시 썼다 |
| `checker/tests/test_srs_shape.py` | 정상, 버전 0개·2개, 표에만, 절에만, 표 행 중복, 절 중복, 표/절 없음(검사 불능), 작성 전, 코드 펜스, CRLF |
| `checker/tests/test_registry.py` | 규칙 종류 목록에 `srs_shape` |
| `checker/README.md` | 규칙 설명과 배포 순서 |
| `docs/guide/harness-guide.html` | SRS 탭에 "SRS 모양" 콜아웃(병합 뒤 아티팩트에 다시 올린다) |
| `plugins/harness/.claude-plugin/plugin.json` | 0.10.293 |

## 결정
- 검사 불능은 `ConfigError`(종료코드 2)로 낸다. 읽지 못함, `## 요구사항` 절 없음, REQ 가 있는데 표 머리(`ID` 열) 없음.
- 요구사항 절에 표도 상세 절도 없는 작성 전 SRS 는 버전 줄만 본다. 이슈는 "표·절을 못 찾으면 검사 불능" 이라 했지만 스캐폴드가 만드는 새 SRS 가 이 모양이라, 그대로면 새 저장소가 처음부터 멈춘다. `pairing._load_srs` 와 같은 기준이다.
- `버전:` 줄은 `export._head_meta` 와 같은 범위·같은 읽기(불릿·굵은 글씨, 값이 있는 줄)로 센다.
- 스캐폴드 skeleton `rules/ssot.yaml` 에는 켜지 않았다(켰다가 되돌림). 배포 전 규칙 종류를 기준 폴더에 켜면 이 저장소 훅이 규칙 파일을 읽다 멈춘다(원인). skeleton `rules/README.md` 에도 더하지 않았다.
- `whats_new.json` 에는 넣지 않았다: 팀원이 할 일이 없다(규칙을 켜는 것은 저장소 담당자).
- `skills/srs/SKILL.md` 는 안 고쳤다: 아직 어떤 저장소에도 켜지지 않아 "검사한다" 고 쓰면 사실이 아니다. 켠 뒤에 고친다.

## 켜는 법 (엔진 v0.10.293 `stable` 이 퍼진 뒤, 스캐폴드와 public-cloud 가 따로)
`rules/ssot.yaml` 의 `규칙:` 목록 끝에 한 줄을 더한다.
```yaml
  - 종류: srs_shape
```
- 팀원 PC 훅은 plugin.json 판의 엔진을 쓴다. 팀원이 `/harness:update` 로 0.10.293 이상을 받기 전에 rules 에 켜면, 그 팀원의 저장 훅은 모든 문서를 검사 불능으로 처리한다.
- 2026-11-14 public-cloud main SRS(`버전: 3.5`, 표 행 20, `### REQ` 20)는 통과한다.

## 시험
`checker/tests/test_srs_shape.py` 16개 통과(아래 최종 보고에 나머지 숫자).
