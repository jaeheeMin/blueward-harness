"""대조할 요소 목록. 시안(mock)과 콘솔(console)이 같은 클래스 이름을 쓰는 것이 기본이고, 다른 것만 따로 적는다.

키마다
  mock / console  CSS 선택자(첫 요소만 잰다). 콘솔 쪽이 다르면 console 에 적는다.
  props           비교할 항목. x y w h(위치·크기), fs(글자 크기), pad(안쪽 여백 4칸), rad(모서리 4칸),
                  bg(배경색)·color(글자색, 정확히 같아야 함), nat(이미지 실제 크기 > 0, 로고가 떴는지)
  tol             항목별 허용 오차(px). 없으면 DEFAULT_TOL.
화면마다 고칠 것은 screen_config.py 의 SCREEN_CONFIG[...]["elements"] 에서 키별로 덮어쓴다(선택자·props·tol, "skip", 또는 None 으로 건너뜀).
색(bg·color)은 computed 값 문자열이 정확히 같아야 한다. 일부러 다른 색은 screen_config.COLOR_EXCEPTIONS 에 이유와 함께 적는다.
내용(글 길이)에 따라 달라지는 높이·세로 위치(대화 판 높이, 입력칸 위치 등)는 기본에서 뺀다 - 시안의 견본 글과 시험 콘솔의 글이 다르기 때문이다.
세로 위치 y 는 헤더 아래끝 기준으로 견준다(compare.rel_y).
"""
DEFAULT_TOL = {"tcy": 2, "x": 2, "y": 2, "w": 2, "h": 2, "fs": 0.5, "pad": 2, "rad": 2}
ALL = ("x", "y", "w", "h", "fs", "pad", "rad")
C = ("bg", "color")

ELEMENTS = {
    "page": {"mock": ".app", "console": "body", "props": C},
    "ann": {"mock": ".ann", "props": (*ALL, *C)},
    "header": {"mock": "header.top", "props": ("x", "w", "h", "fs", "pad", *C)},
    "logo": {"mock": "header.top img.lg", "console": "header.top .brand-logo", "props": ("x", "y", "w", "h", "nat")},
    "nav": {"mock": "header.top .nav", "console": "header.top .topnav", "props": ("x", "w", "h")},
    "btnGhost": {"mock": "header.top .bs", "console": "header.top .pill.ghost", "props": ("w", "h", "pad", "rad", *C)},
    "side": {"mock": "aside.side", "props": ("x", "y", "w", "pad", *C)},
    "srow": {"mock": ".srow", "props": ("x", "y", "w", "h", "fs", "pad", "rad", *C)},
    "main": {"mock": "main.main", "props": ("x", "y", "w")},
    "eyebrow": {"mock": ".main .eb", "props": ("x", "tcy", "fs")},
    "h1": {"mock": ".main h1", "props": ("x", "y", "fs")},
    "steps": {"mock": ".steps", "console": ".stepbar.big", "props": ("x", "y", "h")},
    "pill": {"mock": ".steps .st", "console": ".stepbar.big .step", "props": ("fs", "h", "pad", "rad", *C)},
    "pillDone": {"mock": ".steps .st.d", "console": ".stepbar.big .step.done", "props": C},
    "pillNow": {"mock": ".steps .st.n", "console": ".stepbar.big .step.now", "props": C},
    "iso": {"mock": ".iso", "props": ("w", "h")},
    "strip": {"mock": ".strip", "props": ("x", "y", "w", "h", "rad", *C)},
    "stripCell": {"mock": ".strip > div", "props": ("h", "pad", *C)},
    "stripVal": {"mock": ".strip .x", "props": ("fs", "color")},
    "light": {"mock": "section.light", "props": ("x", "y", "w", "fs", "pad", "rad", *C)},
    "msgs": {"mock": ".msgs", "props": ("x", "w", "fs")},
    "ask": {"mock": ".ask", "console": ".ask, .nextstep, .nextflow", "props": ("x", "w", "h", "fs", "pad", "rad", *C)},
    "btnP": {"mock": ".main .bp", "console": ".main .pill.acc", "props": ("h", "pad", "rad", *C)},
    "btnD": {"mock": ".main .bd", "console": ".main .pill.dark", "props": ("h", "pad", "rad", *C)},
    "comp": {"mock": ".comp", "props": ("x", "w", "h", "pad", "rad")},
    "right": {"mock": ".split > aside", "console": "aside.sess-side", "props": ("x", "y", "w")},
    "paper": {"mock": ".paper", "props": ("x", "y", "w", "rad", *C)},
    "proj": {"mock": ".proj", "console": ".folder-opt.proj", "props": ("x", "w", "h", "pad", "rad")},  # 첫 화면 프로젝트 줄(G-02)
    "opt": {"mock": ".opt", "console": ".kind", "props": ("w", "h", "pad", "rad")},
    "tile": {"mock": ".tile", "console": ".docs-list, .tile2", "props": ("x", "w", "h", "pad", "rad", *C)},
}
