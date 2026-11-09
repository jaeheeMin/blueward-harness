"""시험 콘솔을 화면별 상태로 띄워 시안 기준(baseline.json)과 치수를 대조한다.

  python -m checker.tests.console_mockup.check_console                 # 상태 만들기가 준비된 화면 전부
  python -m checker.tests.console_mockup.check_console G-09 G-10       # 화면 지정
  python -m checker.tests.console_mockup.check_console --shots out/    # 화면 그림도 저장(눈으로 볼 때)
  python -m checker.tests.console_mockup.check_console --list          # 화면과 상태 만들기 준비 여부

종료 코드: 0 = 모두 시안 안, 1 = 시안과 다른 곳 있음, 2 = 검사 못 함(브라우저 없음·서버 못 띄움 등). 2 를 통과로 보지 않는다.
환경변수: CONSOLE_CHECK_BROWSER(브라우저 실행 파일), CONSOLE_CHECK_PORT(기본 4881), CONSOLE_CHECK_REPO(다른 작업 폴더의 콘솔을 볼 때).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .cdp import Browser, find_browser
from .compare import fmt, screen_diffs
from .measure_lib import HERE, WIDTHS, measure, selectors
from .screen_config import COLOR_EXCEPTIONS, SCREEN_CONFIG

BASELINE = HERE / "baseline.json"


def _expect_js(ex: dict) -> str:
    """선택자에 맞는 요소 중 하나라도 글이 들어 있으면(exact 면 글이 정확히 같으면) 참."""
    test = "t === %s" if ex.get("exact") else "t.indexOf(%s) >= 0"
    return ("Array.from(document.querySelectorAll(%s)).some(function(e){var t=(e.textContent||'').trim();return " + test + "})") % (
        json.dumps(ex["sel"]), json.dumps(ex["text"]))


def check_screen(br, lib, screen: str, baseline: dict, builders: dict, shots: Path | None) -> tuple[list[str], list[str], dict]:
    """한 화면을 만들어 두 너비로 대조한다. (실패 줄 목록, 측정 못 한 줄 목록, 너비별 측정값)을 돌려준다."""
    cfg = SCREEN_CONFIG.get(screen, {})
    ov = {k: (dict(v) if v is not None else None) for k, v in cfg.get("elements", {}).items()}
    cex = {**COLOR_EXCEPTIONS, **cfg.get("color_exceptions", {})}
    lib.start_server(first_run_done=not cfg.get("first_run"))  # 첫 화면(G-01~03)은 '시작하기를 아직 안 눌렀다' 로 띄운다
    api = lib.Api().login()
    path = builders[screen](api)
    br.set_cookie("harness_console", api.cookie, lib.BASE)
    fails, unmeasured, got = [], [], {}
    sels = selectors("console", ov)
    for w in WIDTHS:
        br.set_viewport(w, 1000)
        if cfg.get("first_run"):  # 너비마다 처음 열린 상태로(시작하기를 누르면 표시가 남는다)
            (lib.STATE / "first-run.json").unlink(missing_ok=True)
            (lib.STATE / "folder-intro.json").unlink(missing_ok=True)  # 준비 안 된 폴더 안내(G-03)도 처음 보는 것으로
        br.goto(lib.BASE + path)
        end = time.time() + 15
        while time.time() < end and not br.evaluate("!!document.querySelector('main.main > *')"):
            time.sleep(0.3)
        time.sleep(1.0)
        end = time.time() + 15  # 산출물·점검 등 뒤늦게 채워지는 칸이 "불러오는 중" 을 벗어날 때까지
        while time.time() < end and br.evaluate("document.body.innerText.indexOf('불러오는 중') >= 0"):
            time.sleep(0.4)
        end = time.time() + 15  # 로고 같은 그림이 다 뜰 때까지(전체를 이어 돌릴 때 로고가 늦게 떠 '안 뜸' 으로 잘못 잰 적이 있다)
        while time.time() < end and not br.evaluate("Array.from(document.images).every(function(i){return i.complete})"):
            time.sleep(0.3)
        for sel in cfg.get("clicks", []):  # 화면 안 단추를 차례로 눌러 그 화면까지 간다(주소로 못 가는 첫 화면 둘째 쪽 등)
            end = time.time() + 15
            while time.time() < end and not br.evaluate(f"!!document.querySelector({json.dumps(sel)})"):
                time.sleep(0.3)
            br.evaluate(f"(function(){{var e=document.querySelector({json.dumps(sel)});if(e)e.click()}})()")
            time.sleep(1.0)
        if cfg.get("ready"):  # 화면 설정의 ready 선택자(예: 홈의 뒤늦게 그려지는 줄)가 나타날 때까지(없으면 그대로 재서 '없음' 으로 실패한다)
            end = time.time() + 15
            while time.time() < end and not br.evaluate(f"!!document.querySelector({json.dumps(cfg['ready'])})"):
                time.sleep(0.3)
            time.sleep(0.5)
        if cfg.get("scroll_top"):  # 대화가 길어 화면 안이 아래로 스크롤된 화면: 시안(스크롤 전)과 같은 위쪽에서 잰다
            br.evaluate("(function(){window.scrollTo(0,0);document.querySelectorAll('*').forEach(function(e){if(e.scrollTop)e.scrollTop=0})})()")
            time.sleep(0.3)
        meas = measure(br, sels)
        got[w] = meas
        if shots:
            br.screenshot(shots / f"{screen}-{w}.png")
        exp = baseline["screens"][screen]["widths"][str(w)]
        for d in screen_diffs(exp, meas, ov, cex):
            (unmeasured if d.get("kind") == "unmeasured" else fails).append(fmt(screen, w, d))
        for ex in cfg.get("expect", []):
            if not br.evaluate(_expect_js(ex)):
                fails.append(f"{screen} {w}px 기능·글자: '{ex['text']}' 가 {ex['sel']} 에 없음 - {ex.get('why', '')}")
    return fails, unmeasured, got


def run(screens: list[str] | None, shots: Path | None = None) -> int:
    from .fake_console import lib, screens as scr  # 시험 콘솔 도우미는 필요할 때만 불러온다

    if not BASELINE.exists():
        print("검사 불능: baseline.json 이 없다. extract_baseline 으로 먼저 만든다.")
        return 2
    exe = find_browser()
    if not exe:
        print("검사 불능: 헤드리스 브라우저(Chrome·Edge·Chromium)를 못 찾았다. CONSOLE_CHECK_BROWSER 로 실행 파일을 알려 줘.")
        return 2
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    todo = screens or sorted(scr.BUILDERS)
    unknown = [s for s in todo if s not in scr.BUILDERS or s not in baseline["screens"]]
    if unknown:
        print(f"검사 불능: 상태 만들기나 기준이 없는 화면 {unknown}. 준비된 화면: {sorted(scr.BUILDERS)}")
        return 2
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    total, failed, unmeasured_screens, passed = 0, 0, 0, 0
    try:
        with Browser(exe) as br:
            for s in todo:
                fails, unmeasured, _ = check_screen(br, lib, s, baseline, scr.BUILDERS, shots)
                total += 1
                if unmeasured:
                    unmeasured_screens += 1
                    print(f"[검사 불능] {s} - 못 잰 항목 {len(unmeasured)}건(통과도 위반도 아님)")
                    for line in unmeasured:
                        print("  " + line)
                if fails:
                    failed += 1
                    print(f"[실패] {s} - 시안과 다른 곳 {len(fails)}건")
                    for line in fails:
                        print("  " + line)
                elif not unmeasured:
                    passed += 1
                    print(f"[통과] {s} - 1440·1280 모두 시안 안")
    except Exception as e:  # noqa: BLE001 - 어떤 이유든 "통과" 로 둘러대지 않고 검사 불능으로 알린다
        print(f"검사 불능: {type(e).__name__}: {e}")
        return 2
    finally:
        try:
            lib.stop_server()
        except Exception as e:  # noqa: BLE001 - 끄다가 난 문제는 알리기만 한다(결과 코드는 아래에서 정해진다)
            print(f"경고: 시험 콘솔을 끄지 못했다: {e}")
    print(f"\n{total}개 화면 중 {passed}개 통과, {failed}개 실패, {unmeasured_screens}개 검사 불능")
    return 1 if failed else (2 if unmeasured_screens else 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("screens", nargs="*", help="예: G-09 (없으면 준비된 화면 전부)")
    ap.add_argument("--shots", type=Path, help="화면 그림을 저장할 폴더")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args(argv)
    if a.list:
        from .fake_console import screens as scr
        base = json.loads(BASELINE.read_text(encoding="utf-8"))["screens"] if BASELINE.exists() else {}
        for g in sorted(base):
            print(f"{g}: 기준 있음, 상태 만들기 {'준비됨' if g in scr.BUILDERS else '아직'}")
        return 0
    return run(a.screens or None, a.shots)


if __name__ == "__main__":
    sys.exit(main())
