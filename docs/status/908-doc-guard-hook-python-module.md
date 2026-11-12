# #908 SAC 켜진 Windows 에서 doc-guard 쓰기 훅이 doc-guard.exe 로 막힘 (0.10.269)

## 원인

`pre_write_guard.py` 가 엔진을 `uvx --from <engine> doc-guard` 로 불렀다. `doc-guard` 는 `pyproject.toml` `[project.scripts]` 로 uv 가 PC 마다 만들어 복사하는 실행 파일이라 서명이 없고, Smart App Control(SAC)이 켜진 PC 에서 차단됐다(오류 4551, CodeIntegrity 3077). 훅은 검사 불능이라 저장을 거절했다(blueward-26/public-cloud#562 SRS 작업). 다른 훅·스킬의 엔진 호출 30여 곳은 모두 `python -P -m checker.xxx` 라 같은 PC 에서 막히지 않았다.

## 바꾼 것

- `pre_write_guard.py`: `uvx --from <engine> python -P -m checker.cli ...` 로 부른다. `checker/cli.py` 의 `__main__` 이 같은 `main()` 을 부른다.
- 시험 `test_훅과_스킬은_엔진을_콘솔_스크립트_exe_가_아니라_python_m_으로_부른다`(test_engine_pin.py): 훅(py·sh)·SKILL.md 의 `uvx --from` 호출 31건이 모두 `python` 인지 본다(줄잇기 모양 포함, 20건 미만이면 정규식이 놓친 것으로 실패).
- whats_new 0.10.269.

## 보안 판단 (공식 문서 기준, 사용자 결정 2026-11-12)

- 이 수정으로 새로 실행되는 코드는 없다. 그 PC 는 이미 같은 엔진 코드를 python 으로 돌린다.
- 이 방식이 SAC 에 막히지 않는 이유는 SAC 가 python 이 읽어 실행하는 코드를 검사하지 않기 때문이다. 근거는 SAC 의 기반인 App Control 문서("App Control doesn't control scripts run through an unenlightened script host, such as many 3rd-party Java or Python engines.")이고, 이 문장이 SAC 에도 적용된다는 공식 문장은 없다. "SAC 가 보증하는 정상 사용" 으로 쓰지 않는다.
- Microsoft 공식 해결책은 서명뿐이다(SAC FAQ "sign your app with a valid certificate", Security Book 은 스크립트까지 서명하라고 안내). 서명 전환은 하네스 전체 실행 구조 문제라 이 이슈 범위 밖이다.
- SAC 끄기는 PC 전체 보호를 끄는 것이라 쓰지 않는다.
- 남는 한계: PC 의 python 자체가 서명 없는 판(uv 관리 Python)이면 python 실행도 막힐 수 있다(공식 문서 아님, astral-sh/uv#22869).

## 확인

- 옛 코드로 되돌리면 새 시험이 `pre_write_guard.py: uvx", "--from", engine_spec(), "doc-guard` 를 잡아 실패, 새 코드로 통과.
- `test_hook.py`(실제 훅을 로컬 엔진으로 실행)·`test_engine_pin.py`·`test_activation_gate.py`·`test_hook_block_cards.py`·`test_shims.py`: 182 passed, 5 skipped.
- SAC 켜진 PC 실시험은 아직이다. 병합 뒤 보고한 팀원이 `/harness:update` 하고 SRS 저장이 통과·위반으로 판정되는지 확인한다.
- 길잡이는 고치지 않았다. 팀원이 보는 훅 동작(언제 막고 무엇을 안내하는지)은 바뀌지 않았다.
