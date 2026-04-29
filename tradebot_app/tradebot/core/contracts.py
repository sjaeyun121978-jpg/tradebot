"""모듈 간 공통 계약 설명.
각 레이어는 dict 입력/출력만 공유하고 서로의 내부 로직을 호출하지 않는다.
"""
STEP_STATES = ("WAIT", "EARLY", "PRE", "REAL", "HOLD", "EXIT")
DIRECTIONS = ("LONG", "SHORT", "NEUTRAL")
