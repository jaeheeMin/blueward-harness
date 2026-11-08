"""화면별 설정. 시안 화면 번호(G-xx)가 키다.

elements  요소 키별 덮어쓰기. None 이면 그 화면에서 건너뜀, {"console": 선택자} 로 콘솔 쪽 선택자 변경,
          {"props": (...)} 로 비교 항목 변경, {"tol": {"w": 4}} 로 허용 오차 변경.
expect    기능·글자 확인: {"sel": CSS 선택자, "text": 포함돼야 할 글, "why": 설명}. 선택자에 맞는 요소 중 하나라도 그 글을 가지면 통과("exact": True 면 글이 정확히 같아야 통과).
          시안의 견본 글이 아니라, 상태 만들기(fake_console/screens.py)가 만드는 화면에서 꼭 있어야 하는 판정·단추만 적는다.

COLOR_EXCEPTIONS  {(시안 글자색, 콘솔 글자색): 이유}. 글자색(color)이 정확히 이 쌍일 때만 통과로 본다(요소 이름이 아니라 값 쌍이라, 다른 색으로
          바뀌면 그대로 실패한다). 배경색·테두리색에는 예외가 없다. 모든 화면에 적용되고, 화면 설정의 "color_exceptions" 로 그 화면에만 더할 수도 있다.

건너뛰기·허용 오차를 늘릴 때는 이유를 옆에 적는다. 시안과 달라서 실패하는 것을 "허용" 으로 덮지 않는다(고치거나, 시안이 바뀐 것이면 baseline 을 다시 뽑는다).
"""
_WHY = "11-07 이전 사용자 결정: 글자 대비 4.5:1 위해 콘솔 값 유지(#722)"
COLOR_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("rgb(255, 255, 255)", "rgb(243, 250, 248)"): _WHY + " - 기본 글자색 #fff -> rgb(243,250,248)",
    ("rgb(109, 119, 117)", "rgb(85, 98, 95)"): _WHY + " - --lmuted #6d7775 -> #55625f",
}

NAV_4 = {"sel": "header.top .topnav a", "text": "작업", "exact": True, "why": "시안 헤더는 내 일·작업·산출물·새 작업 네 칸"}

SCREEN_CONFIG: dict[str, dict] = {
    "G-04": {"expect": [NAV_4, {"sel": ".main h1", "text": "아직 시작한 작업이 없어", "why": "빈 홈 제목"}]},
    "G-05": {"expect": [NAV_4]},
    "G-06": {"expect": [NAV_4]},
    "G-09": {"expect": [
        NAV_4,
        {"sel": ".stepbar.big .now", "text": "올리기", "why": "시안 G-09 지금 단계 알약은 짧은 이름 '올리기'"},
        {"sel": ".nextstep .acts *, .ask .acts *, .nextstep button, .ask button", "text": "올리고 검토 요청", "why": "시안 G-09 할 일 카드 단추 글자"},
    ]},
    # 시안 G-10 에는 순서 알약이 없다. 단계는 숫자 띠·사이드바·안내 문장으로 보인다.
    "G-10": {"expect": [
        NAV_4,
        {"sel": ".strip", "text": "3 / 3 승인 기다림", "why": "숫자 띠 단계 칸"},
        {"sel": ".side .srow", "text": "승인 기다림 · PR #", "why": "사이드바 줄 상태"},
        {"sel": ".light", "text": "합쳐지면 여기와 홈에서 알려 줄게", "why": "시안 G-10 안내 문장"},
    ]},
    "G-12": {"expect": [NAV_4, {"sel": ".nextflow", "text": "다음 일", "why": "병합 뒤 다음 갈래 카드"}]},
    "G-13": {"expect": [NAV_4, {"sel": ".startchecks", "text": "시작 점검 · 자동", "why": "시안 G-13 시작 점검 머리글"}]},
    "G-15": {
        # 시안 G-15 는 .comp 가 흰 판 폭 전체인 한 장 화면이고, 콘솔 /docs 는 .comp 가 오른쪽 칸에 있다(화면 구조가 달라 같은 요소가 아님).
        "elements": {"comp": None},
        "expect": [NAV_4, {"sel": "main.main", "text": "BW_Backlog List_v0.1.xlsx", "why": "산출물 목록에 양식 xlsx"}],
    },
}

NAV_5 = {"sel": "header.top .topnav a", "text": "기록", "exact": True, "why": "시안 헤더는 내 일·작업·산출물·새 작업·기록 다섯 칸"}

# 헤더 메뉴 칸 수(2026-11-07 사용자 결정, #779): 시안 G-01~19 는 기록 화면을 그리기 전이라 네 칸이고, G-20~24 는 '기록' 을 더한
# 다섯 칸이다. 나중 시안(다섯 칸)을 정답으로 본다. 그래서 G-20 앞 화면에서는 메뉴 너비(nav.w)만 비교에서 빼고(x·h 는 그대로 본다),
# 다섯째 칸 '기록' 이 있는지를 글자 확인으로 본다.
for _g in ("G-04", "G-05", "G-06", "G-09", "G-10", "G-12", "G-13", "G-15"):
    SCREEN_CONFIG[_g].setdefault("elements", {})["nav"] = {"props": ("x", "h")}
    SCREEN_CONFIG[_g]["expect"].append(NAV_5)

# 기록 화면 셋(G-20~22).
SCREEN_CONFIG["G-20"] = {"expect": [NAV_5,
    {"sel": ".main h1", "text": "팀이 겪은 문제와 푼 방법", "why": "시안 G-20 제목"},
    {"sel": ".strip", "text": "이번 달 기록", "why": "숫자 띠 첫 칸"},
    {"sel": ".light", "text": "ATC 검사에서 운송이 막힘(금지 API)", "why": "목록 맨 위 기록(가짜 gh 이슈)"},
    {"sel": ".light", "text": "확인 못 함", "why": "못 읽은 저장소(cloud-b)는 보라 '? 확인 못 함' 줄"},
    {"sel": ".light button, .light a", "text": "+ 새 기록", "why": "새 기록 단추"}]}
SCREEN_CONFIG["G-21"] = {"expect": [NAV_5,
    {"sel": ".main h1", "text": "ATC 검사에서 운송이 막힘(금지 API)", "why": "시안 G-21 제목"},
    {"sel": ".light", "text": "해결 후보", "why": "이력의 해결 후보 줄"},
    {"sel": ".light button", "text": "이걸로 해결", "why": "해결 후보 줄의 단추"},
    {"sel": ".light", "text": "내 이야기 더하기", "why": "댓글 입력 구역"},
    {"sel": ".light", "text": "비슷한 기록", "why": "비슷한 기록 구역"}]}
SCREEN_CONFIG["G-22"] = {
    # 시안 .paper 는 콘솔에서 .tb-paper(GitHub 에 올라갈 모양 미리보기)다.
    "elements": {"paper": {"console": ".tb-paper"}},
    "expect": [NAV_5,
    {"sel": ".main h1", "text": "어떤 문제였어?", "why": "시안 G-22 제목"},
    {"sel": ".ask", "text": "AI 초안", "why": "AI 초안 줄"},
    {"sel": ".light", "text": "비밀번호·키처럼 보이는 글이 있어", "why": "비밀 줄 빨간 표시"},
    {"sel": ".light button", "text": "GitHub 에 올리기", "why": "올리기 단추(비밀 줄이 있으면 잠김)"},
    {"sel": ".light", "text": "이미 비슷한 기록이 있어", "why": "비슷한 기록 구역"}]}

# 세션·홈에서 기록을 만나는 곳(G-23·24). 세션 목록 등 나머지는 G-20 과 같은 상태(판매오더 조회 앱·PR #812 검사 실패).
SCREEN_CONFIG["G-23"] = {"scroll_top": True, "expect": [NAV_5,
    {"sel": ".main h1", "text": "판매오더 조회 앱", "why": "세션 제목"},
    {"sel": ".bad.blocked", "text": "✕ 막힘", "why": "막힘 카드"},
    {"sel": "[data-similar-line]", "text": "비슷한 기록 2건", "why": "막힘 카드 아래 비슷한 기록 줄"},
    {"sel": ".ask", "text": "기록해 둘까?", "why": "풀린 뒤 기록 제안 카드"},
    {"sel": ".ask button", "text": "기록하기", "why": "제안 카드 [기록하기]"},
    {"sel": ".ask button", "text": "괜찮아", "why": "제안 카드 [괜찮아]"}]}
SCREEN_CONFIG["G-24"] = {"ready": "[data-fix-pr]", "expect": [NAV_5,
    {"sel": ".main h1", "text": "오늘 내 일", "why": "홈 제목"},
    {"sel": "main.main", "text": "고쳐야 할 내 PR 1건", "why": "고쳐야 할 내 PR 줄"},
    {"sel": "main.main", "text": "아직 안 풀린 문제", "why": "팀 기록 타일"},
    {"sel": "main.main", "text": "3건", "why": "열린 기록 3건"}]}

# 첫 실행 화면(G-01~03). 첫 실행·화면 안 단추 누르기는 check_console 의 first_run·clicks 가 한다.
SCREEN_CONFIG["G-01"] = {"first_run": True, "ready": ".crow.ok", "expect": [
    {"sel": ".intro-box h1", "text": "Blueward Harness에 온 걸 환영해", "why": "시안 G-01 제목"},
    {"sel": ".intro-box", "text": "GitHub 연결", "why": "점검 줄"},
    {"sel": ".intro-box button", "text": "시작하기", "why": "시작하기 단추"}]}
SCREEN_CONFIG["G-02"] = {"first_run": True, "clicks": ["[data-intro-start]", "[data-pick-folder]"], "ready": "[data-pick-folder]", "expect": [
    {"sel": ".intro-box h1", "text": "어느 고객사 프로젝트에서 일할까?", "why": "시안 G-02 제목"},
    {"sel": "[data-pick-folder]", "text": "harness-console-sandbox", "why": "최근 폴더(준비 필요)"},
    {"sel": "[data-pick-folder]", "text": "public-cloud", "why": "최근 폴더(준비됨)"},
    {"sel": ".proj.add", "text": "다른 폴더 찾아보기", "why": "점선 줄"},
    {"sel": ".intro-box button", "text": "이 프로젝트로", "why": "확인 단추"}]}
SCREEN_CONFIG["G-03"] = {"first_run": True, "clicks": ["[data-intro-start]", "[data-pick-folder$=\"harness-console-sandbox\"]", "[data-pick-ok]:not([disabled])"], "ready": ".ask", "expect": [
    {"sel": "main.main", "text": "표준 구조", "why": "시안 G-03 표준 구조 만들기 안내"}]}
# G-03 도 헤더 메뉴는 시안이 네 칸(기록 화면 앞)이라 다른 G-01~19 와 같이 처리한다.
SCREEN_CONFIG["G-03"].setdefault("elements", {})["nav"] = {"props": ("x", "h")}
SCREEN_CONFIG["G-03"]["expect"].append(NAV_5)
