"""시안(*.dc.html)을 1440·1280 너비로 열어 요소 치수를 baseline.json 에 저장한다. 시안이 바뀌면 다시 돌린다.

  python -m checker.tests.console_mockup.extract_baseline <시안 폴더> [--screens G-04,G-09]

시안 폴더는 G-01.dc.html … 이 든 곳(예: design-canvas/project). 환경변수 CONSOLE_MOCKUP_DIR 로도 준다.
시안 폴더의 _blob/ 에 진짜 로고(png)와 글꼴(woff2)이 있어야 한다(없으면 이미지를 못 불러왔다고 멈춘다).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .cdp import Browser, find_browser
from .measure_lib import HERE, STATIC, WIDTHS, measure, selectors, serve_dir, sha

BASELINE = HERE / "baseline.json"

# 시안은 /_blob/ 글꼴·로고를 시안 폴더의 진짜 파일(_blob/)로 받는다. 없는 것은 IBM Plex Mono(구글 글꼴, 밖에서 안 불러와짐)뿐이라
# 같은 자리에 콘솔이 쓰는 JetBrains Mono 를 대 준다.
PATCH_JS = r"""(async function (base) {
  var st = document.createElement('style');
  st.textContent = "@font-face{font-family:'IBM Plex Mono';src:url('" + base + "/fonts/JetBrainsMono-Regular.woff2') format('woff2');font-weight:100 900}";
  document.head.appendChild(st);
  await Promise.all([document.fonts.load("14px Pretendard"), document.fonts.load("400 12px 'IBM Plex Mono'")]);
  await document.fonts.ready;
  await Promise.all(Array.from(document.images).map(function (i) { return i.complete ? 0 : new Promise(function (r) { i.onload = i.onerror = r; }); }));
  var bad = Array.from(document.images).filter(function (i) { return !i.naturalWidth; });
  if (bad.length) throw new Error('시안 이미지를 못 불러옴: ' + bad.map(function (i) { return i.getAttribute('src'); }).join(', '));
  return true;
})"""


def extract(mock_dir: Path, screens: list[str] | None = None) -> dict:
    exe = find_browser()
    if not exe:
        raise RuntimeError("헤드리스 브라우저(Chrome·Edge·Chromium)를 못 찾았다. CONSOLE_CHECK_BROWSER 로 실행 파일을 알려 줘.")
    files = sorted(mock_dir.glob("G-*.dc.html"))
    if screens:
        files = [f for f in files if f.name.split(".")[0] in screens]
    if not files:
        raise RuntimeError(f"시안 파일이 없다: {mock_dir}")
    srv_m, port_m = serve_dir(mock_dir)
    data = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {"_meta": {}, "screens": {}}
    sels = selectors("mock")
    try:
        with Browser(exe) as br:
            for f in files:
                gid = f.name.split(".")[0]
                per = {}
                for w in WIDTHS:
                    br.set_viewport(w, 1000)
                    br.goto(f"http://127.0.0.1:{port_m}/{f.name}")
                    br.evaluate(f"({PATCH_JS})('http://127.0.0.1:{port_m}/__static')")
                    per[str(w)] = measure(br, sels)
                data["screens"][gid] = {"source": sha(f), "widths": per}
                print(f"{gid}: " + ", ".join(f"{w}→{sum(1 for k, v in per[str(w)].items() if v and k != '_layout')}개 요소" for w in WIDTHS))
    finally:
        srv_m.shutdown()
    data["_meta"] = {"widths": list(WIDTHS), "note": "extract_baseline.py 로 만든 파일. 직접 고치지 않는다."}
    data["screens"] = dict(sorted(data["screens"].items()))
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mock_dir", nargs="?", default=os.environ.get("CONSOLE_MOCKUP_DIR"))
    ap.add_argument("--screens", help="쉼표로 구분한 화면 번호(예: G-04,G-09). 없으면 전부")
    a = ap.parse_args(argv)
    if not a.mock_dir:
        ap.error("시안 폴더를 인자나 CONSOLE_MOCKUP_DIR 로 줘")
    try:
        extract(Path(a.mock_dir), a.screens.split(",") if a.screens else None)
    except Exception as e:  # noqa: BLE001 - 못 뽑았으면 검사 불능(2)이다. 기준 파일은 바뀌지 않았다고 보지 않는다
        print(f"검사 불능: {type(e).__name__}: {e}")
        return 2
    print(f"저장: {BASELINE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
