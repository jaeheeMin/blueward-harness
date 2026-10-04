"""checker.yml 이 부르는 얇은 진입점. 판정은 `checker.plugin_version` 에 있다(#136)."""
from __future__ import annotations

from checker.plugin_version import main

if __name__ == "__main__":
    raise SystemExit(main())
