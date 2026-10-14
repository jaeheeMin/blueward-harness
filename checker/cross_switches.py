"""교차 검사(번호 짝 #284, 객체 겹침 #292, 판 번호 겹침 #315)를 저장소마다 켜고 끄는 스위치.

설정 파일은 Project Repository 의 `rules/cross-checks/switches.yaml` 이다. 하위 폴더에 둔 이유는
엔진의 규칙 로더가 `rules/` 최상위 `*.yaml` 을 전부 문서 규칙 파일로 읽기 때문이다 — 최상위에
두면 '관할' 이 없다며 모든 검사가 설정 오류로 멈춘다. 하위 폴더는 로더가 읽지 않는다.

- 파일이 없으면 모두 켠다(스위치가 생기기 전과 같은 동작).
- 키: `번호_짝`, `객체_겹침`, `판_겹침`. 값은 true/false 만. 파일에 없는 키는 켬.
- 모르는 키, 불린이 아닌 값, 깨진 YAML 은 `SwitchError` — 조용히 무시하지 않는다. 호출하는 쪽이
  검사 불능(종료코드 2)으로 알린다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SWITCH_FILE = "rules/cross-checks/switches.yaml"
KEYS = ("번호_짝", "객체_겹침", "판_겹침")
DISABLED = "disabled"  # 리포트에 싣는 상태: 돌릴 조건인데 스위치가 꺼져 있다


class SwitchError(Exception):
    """스위치 파일을 읽을 수 없다. 켜짐으로도 꺼짐으로도 답하지 않는다."""


def load_switches(root: Path) -> dict[str, bool]:
    result = {k: True for k in KEYS}
    path = root / SWITCH_FILE
    if not path.exists():
        return result
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SwitchError(f"`{SWITCH_FILE}` 를 읽지 못했습니다: {exc}") from exc
    if raw is None:
        return result
    if not isinstance(raw, dict):
        raise SwitchError(f"`{SWITCH_FILE}` 의 최상위가 사전이어야 합니다")
    unknown = [str(k) for k in raw if k not in KEYS]
    if unknown:
        raise SwitchError(
            f"`{SWITCH_FILE}` 에 모르는 키가 있습니다: {', '.join(unknown)} (쓸 수 있는 키: {', '.join(KEYS)})"
        )
    for key, value in raw.items():
        if not isinstance(value, bool):
            raise SwitchError(f"`{SWITCH_FILE}` 의 {key} 는 true 나 false 여야 합니다(지금: {value!r})")
        result[key] = value
    return result
