# #335 고객 견본에서 빈 양식 만들기 — PR A 견본 지우기 (2026-10-15)

고객사 견본 xlsx 에 지도 밖 샘플(셀 값, 그림·도형, 다른 고객사·사내 서버를 가리키는 외부 참조)이 섞여 있어 템플릿으로 그대로 못 쓴다. 분할: A 견본 지우기(이 PR) → B 남은 견본 검사(`견본_검사`·`유지`) → C1 셀 서식·병합 쓰기 → C2 화면 md 문법과 그리기.

## 바뀐 것

- 새 모듈 `checker/blank_template.py` + CLI `python -m checker.blank_template --root R --form F --src 견본 --out 빈양식 [--check]`. `--out` 이 있으면 거부.
- 지도 키(시트): `비우기: [범위…]`(값만 지움, `SheetXml.clear_range` 재사용), `그림_지우기: true`, `유지: [범위…]`(키만 인정). 최상위 `외부_참조_지우기: true`.
- 쓰기는 zip 수준(openpyxl 저장 안 함). 바뀐 파트 말고는 바이트 그대로 → x14 드롭다운 시트 보존.
- sharedStrings: 지운 칸이 가리키던 `<si>` 중 더는 아무 칸도 안 가리키는 것만 `<si><t/></si>` 로 비움(번호 유지, `count` 조정).
- 그림 지우기: 시트 XML 의 `<drawing>`·`<picture>` 제거 → 시트 rels 에서 drawing 관계만 제거(printerSettings 유지, 관계가 비면 rels 파트 삭제) → 아무도 안 쓰는 drawing·drawing rels 삭제 → media 는 남은 rels 가 가리키지 않을 때만 삭제(참조 수 세기) → `[Content_Types].xml` Override 정리. 차트·도식·삽입 개체를 가리키는 drawing, 시트의 legacyDrawing·oleObjects·controls 는 지원 안 함(2).
- 외부 참조 지우기(사용자 결정 추가): externalLinks 파트·rels, `workbook.xml` 의 `externalReferences`, workbook rels, Content_Types, `[N]` 을 쓰는 이름 정의 삭제. 그 이름이나 `[N]` 을 쓰는 데이터 유효성(표준·x14)·셀 수식·조건부 서식·차트·표 수식이 있으면 지우지 않고 위치를 밝히며 2. `#REF!` 이름은 외부 참조가 아니라 그대로 두고 알림.
- `비우기` 는 지도의 칸·표(`시작_행`~`최대_행`, 없으면 끝까지)·서술·`유지` 범위와 겹치면 지도 오류(2). 검증 함수 `blank_template.map_problems` 를 `export.load_map` 과 `form_columns._valid_map` 이 같이 쓴다.
- `export.py`: 산출 때도 지도 `비우기` 를 적용(안전망, 공유 문자열 정리 포함). 기존 `해당 없음` 경고 블록은 그대로(PR B 에서 대체).
- 서술 두 칸 결함 수정: 서술 항목에 `열: {제목: D, 설명: E}` 를 두면 md 줄 `제목 | 설명` 을 각 칸에 쓴다(설명 안 줄바꿈은 `<br>`, `|` 없는 줄은 제목만). `열` 이 없으면 기존 한 칸 동작. 열은 위치의 열 범위 안이어야 한다.
- 문서: `form-map.md`(새 키·CLI), spec `SKILL.md`("비우기 로 지운다"). Plugin version 0.10.75 → 0.10.76.

## 종료코드 판단

1 거부: `--out` 존재·`.xlsx` 아님·루트 밖·폴더 없음, 범위 문자열 모양 오류. 2: 읽지 못함·지원 안 함·지도 오류(겹침 등)·외부 참조 사용처 있음. 3: 만들었으나 결과 패키지(sharedStrings 의 안 쓰는 항목, drawings, 이름 정의, externalLinks)에 지운 견본 글자가 다시 보임. `--check` 는 파일만 안 쓰고 같은 검사(`dry_run: true`). 칸이 아직 가리키는 공유 문자열은 눈에 보이는 값이라 남은 견본으로 세지 않는다. 구두점뿐인 글자는 견본으로 보지 않는다.

## 실제 템플릿 읽기 전용 확인 (scratchpad 사본)

외부 참조 이름 10개(Complexity·DeliveryChannel·GeneralDefiniton·Priority·ValidStatus·데이터처리방식·리포트방식·리포트조회주기·비가동·활용도)를 쓰는 데이터 유효성·셀 수식·조건부 서식은 없었다. 시트 5개의 데이터 유효성은 표준 4개(Initial Screen 의 리터럴 목록)뿐이고 x14 는 없다. 수식 셀도 없다. 이름을 가리키는 곳은 externalLink1.xml 안의 캐시 이름뿐이다. 따라서 `외부_참조_지우기: true` 로 지워도 깨지는 곳은 없다. `_xlnm._FilterDatabase` 가 `'Display Screen'!#REF!` 를 가리키는데 그 시트에 autoFilter 가 없어 고아 이름이다(그대로 두고 알림; 지워도 되지만 이번엔 건드리지 않았다).

## 확인하지 못한 것

- 결과 xlsx 를 엑셀에서 열어 보지 못했다(복구 창 여부 미확인). openpyxl 로 읽히고 모든 XML 파트가 well-formed 인 것까지만 확인.
- `docProps/app.xml` 의 이름 목록(TitlesOfParts)은 지운 이름을 아직 담고 있을 수 있다(엑셀은 무시하는 것으로 알지만 확인하지 못함).
- 길잡이(`docs/guide/harness-guide.html`)에는 이 기능 설명이 없어 고치지 않았다.

## 검토 반영 (2026-10-15)

- 표준(접두사 없는) 조건부 서식의 외부 참조가 검사되지 않던 정규식 오류를 고쳤다(`\1` 역참조가 접두사 없을 때 실패). 같은 모양의 x14 데이터 유효성 정규식은 접두사가 필수라 문제없다. 테스트 추가.
- `legacyDrawingHF` 가 `\b` 때문에 지원 안 함 검사에 안 걸리던 것을 고쳤다(그림_지우기 시트에서 2).
- `"<f" in inner` 가 `<family>` 를 수식으로 오인하던 것을 `export.is_formula`(`<f[\s>/]`)로 좁혔다(`blank_template`·`export` 공통).
- 기본 동작: docProps core 의 제목·작성자·마지막 수정자, app 의 Company·Manager 를 빈 양식 생성 때 비운다. 근거: 견본 파일의 출처 정보(다른 고객사·작성자 이름)이고 빈 양식에 남을 이유가 없다.
- 남은 견본 판정에서 안 보는 곳(머리글·바닥글, 머리글 그림, 메모, 시트 이름, 드롭다운 목록 직접 입력 값, 문서 속성 나머지)은 있으면 `notices`(`review-needed`)로 알린다. 견본 여부 판정과 지우기는 PR B 범위.
- `docProps/app.xml` 의 TitlesOfParts·HeadingPairs 는 갱신하지 않는다. 지운 이름이 거기 남아도 엑셀이 문제 삼지 않는지는 근거를 못 찾아 확인하지 못했다.
- 범위 문자열 모양 오류: `blank_template` 는 거부(1), `export` 는 읽지 못함(2). `form-map.md` 에 적었다.
