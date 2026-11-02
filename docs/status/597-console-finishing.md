# #597 웹 콘솔 마무리 — 승인 안내 문구·옛 단계 이름·길잡이 주소 (2026-11-02)

## 바꾼 것

- `checker/risk_gate.py`: `build_next` 에 `admin_only` 인자를 더했다(`_result_from`·`decide_pr` 까지 전달). 승인자 파일이 없거나 비어 저장소 admin 만 승인자로 판정되는 경우(#586), "다음:" 안내가 "승인자(.github/ssot-approvers …)" 대신 "저장소 관리자(admin, 작성자 제외)에게 최신 커밋을 보고 (다시) Approve 를 요청" 으로 나간다. 판정 결과는 바꾸지 않았다. 파일이 있을 때 문구와 PR 나누기 꼬리는 그대로다.
- `plugins/harness/console/flows.py`·`store.py`·`server.py`: 세션 `flowState` 는 만들 때 단계 name·hint 를 복사해 저장하므로, 갈래 개편 전에 저장된 세션은 옛 이름("새 이슈·브랜치 만들기", "커밋·푸시·PR")이 화면에 남았다. `public_fields(s, data)` 가 서버가 읽어 둔 현재 갈래 정의(`Store.flow_data`, 서버가 한 번 넣는다)에서 같은 갈래 id·단계 id 를 찾아 갈래 name, 단계 name·hint 를 현재 값으로 내보낸다. 정의에서 못 찾으면 저장값 그대로. 저장 상태는 바꾸지 않는다.
- `docs/guide/README.md`: 길잡이 게시 주소를 새 아티팩트(`XcbPn4JkPkeLGgVKBG4yEi`)로 바꿨다.
- `plugin.json` 0.10.154 (열린 다른 PR 이 0.10.152·153 사용).

## 시험

- `checker/tests/test_risk_gate.py`: 파일 없음/빈 파일의 missing 안내, build_next stale 문구, 파일 있을 때 기존 문구.
- `checker/tests/test_web_console.py`: 옛 이름 저장 세션 → 현재 이름, 정의에 없는 단계·갈래 → 저장값 유지.

## 남은 것

- `.github/workflows/release-tag.yml` 의 `GUIDE_URL` 과 `checker/tests/test_engine_pin.py` 는 아직 옛 주소다(이 작업 범위 밖).
- 길잡이 `harness-guide.html` 은 "다음:" 문구나 단계 이름을 인용하지 않아 손대지 않았다.
