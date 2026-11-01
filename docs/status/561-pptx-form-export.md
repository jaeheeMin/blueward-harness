# #561 고객 양식 pptx 산출 엔진 (2026-10-31)

## 배경

고객사 사용자 매뉴얼을 고객 양식 pptx 로 내야 하는데 `checker.export` 는 xlsx 만 산출했다. 양식은 슬라이드 4장에 자리 표시자가 없고 일반 도형뿐이며 언제든 바뀐다. 그래서 양식별 코드나 고정 위치를 엔진에 넣지 않고, 지도(`templates/forms/*.yaml`)가 양식의 예시 글자로 도형을 찾게 했다.

## 바꾼 것

- `checker/export_pptx.py`(새 파일): pptx 쓰기. 지도 검증(`validate_map`, 같은 `견본` 을 두 쪽이 쓰면 거절), 도형 찾기(앞부분 일치, 0개·2개 이상 거부, 위치 없는 도형은 번호 후보에서 제외), 글 치환(첫 문단 서식 유지, 서식이 다른 run 이 여럿이면 `format-merged` 경고), 쪽 복제(그림 관계 다시 잇기)·순서 맞추기·안 쓰는 견본 쪽 제거·쓰지 않는 그림 관계 끊기, 그림 비율 맞춤, 번호 설명 쌓기·쪽 넘김, 목차 목록, 도형을 지우는 쪽의 `p:timing` 제거(`animation-removed` 경고), 도형 목록(`--dump`). 채우는 중 도형 찾기가 어긋나면 버리지 않고 거부로 올린다.
- `checker/export.py`: 템플릿 확장자로 분기. `load_map` 은 pptx 지도에 `쪽` 을 요구하고 `blank_template.check_map` 은 xlsx 에만 적용. `_out_path`(금지 문자·파일명 패턴·origin/main 덮어쓰기 방지)를 xlsx 쪽 코드에서 그대로 떼어 공통 함수로 만들고, 새 `_build_pptx`·`_head_meta` 가 쓴다. `is_srs_map`·`list_values` 는 `시트` 없는 지도에서 죽지 않게 했다. `run` 은 `layout-unchecked` 경고를 경고 종료(3)로 세고, 이 경고만 있으면 "산출은 됐다. 사람이 PowerPoint 로 확인(검사 불능)" 으로 안내한다(드롭다운 안내·"고쳐 다시 산출" 없음, xlsx 경고 문구는 그대로).
- `checker/rules/form_columns.py`: pptx 지도의 Spec 은 건너뛰지 않고 `export_pptx.normalize_sections` 로 대조한다. 지도에 없는 쪽·칸·소제목은 `양식 밖 항목` 위반이고, 지도를 읽지 못하면 검사 불능(ConfigError)이다. SRS 지도 찾기에서는 pptx 지도를 건너뛴다(원본이 SRS 일 수 없다).
- `checker/blank_template.py`: pptx 지도는 `KeyError` 대신 "빈 양식 만들기 대상이 아니다" 로 종료 2.
- `plugins/harness/skills/spec/form-map.md`: "pptx 지도" 절(서식 합침·애니메이션·그룹/표 안 글 한계 포함). `plugins/harness/skills/spec/SKILL.md`: `status: warning (3)` 에 `layout-unchecked` 안내. `checker/README.md`: 짧은 안내.
- 시험 `checker/tests/test_export_pptx.py`: 시험용 양식은 python-pptx 로 코드에서 만든다(고객 양식 파일은 저장소에 없다).
- plugin.json version 은 첫 구현 때 0.10.142 로 올려 두었고 이후 더 건드리지 않았다(최종 값은 메인이 정한다).

## 지도 형식에서 바꾼 점

- `목록` 에 `제목` 키를 더했다(본문 쪽의 어느 칸 값을 목차 줄로 쓸지).
- `번호_설명` 에 선택 키 `아래`(EMU)를 더했다. 기본은 그림 자리의 아래 끝.
- `유지` 는 `표` 말고 글자도 받는다(그 도형을 남김). `유지` 키가 있는 쪽만 지도가 안 가리킨 도형을 모두 지운다.
- 원본 md: 칸은 `| 항목 | 값 |` 표와 `#### <항목>` 본문 둘 다 받는다. 기존 `parse_spec` 은 고치지 않았다. 파일명 `자리.버전: {메타: 버전}` 은 작업본 머리(첫 `##` 앞)의 `버전: 0.1` 줄을 읽는다.

## 확인한 것

- `uv run pytest checker/tests/test_export_pptx.py checker/tests/test_export.py checker/tests/test_form_columns.py checker/tests/test_form_map.py checker/tests/test_blank_template.py checker/tests/test_leftover.py -q`: 296 통과. 전체(`checker/tests`)는 메모리 부족으로 하니스가 중단시켜 돌리지 못했다.
- public-cloud PR #455 의 정리본 양식(슬라이드 4장)으로 임시 프로젝트(저장소 밖)를 꾸려 산출하고 PowerPoint COM 으로 PNG 를 뽑아 눈으로 봤다. 복구 창 없이 열렸고, 본문 2화면 중 번호 8개 화면이 두 쪽으로 나뉘어 번호가 이어졌다.

## 확인하지 못한 것·남긴 것

- 글 넘침·겹침은 사람 눈 확인이 필요하다. 산출은 항상 `layout-unchecked` 경고(종료 3)를 낸다. 글 높이 추정은 보수적이라 실제보다 일찍 쪽을 넘길 수 있다.
- 목차 줄이 글상자에 다 들어가는지(화면 수가 많을 때)는 검사하지 않는다.
- 차트·미디어(영상·소리)가 든 견본 쪽을 복제할 때 관계를 공유로 복제하는 동작은 확인하지 못했다. 지금 양식에 없어서 시험하지 않았다.
- 슬라이드 노트는 복제하지 않는다. 그룹 도형·표 안의 글은 `찾기` 가 보지 못한다(`form-map.md` 에 대처를 적었다). 애니메이션은 도형을 지우는 쪽에서만 지운다.
- 양식에 PowerPoint 구역 목록(`sectionLst`)이 있으면 걷어 낸다.
- 길잡이(`docs/guide/harness-guide.html`)는 고치지 않았다. pptx 지도는 스킬·훅 동작이 아니라 지도 형식 추가라서다. 필요하면 따로 정한다.
- 병합 뒤 엔진 태그가 새로 붙는다.
