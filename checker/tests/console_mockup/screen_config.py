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
