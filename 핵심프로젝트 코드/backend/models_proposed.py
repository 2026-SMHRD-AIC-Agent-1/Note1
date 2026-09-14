"""
[변경 제안 / 팀 합의 전 초안] models_proposed.py
--------------------------------------------------
현재 이 파일에는 확정 전 제안 테이블이 없습니다. (USER_CONSENTS,
SESSION_TECHNICAL_EVENTS, NONVERBAL_EVENTS 모두 팀 확정을 거쳐
models.py로 이동 완료)

새로운 테이블/필드가 필요할 때는 여기에 table=False로 먼저 추가하고,
팀 합의 후 models.py로 옮기는 흐름을 유지하기 위해 파일은 남겨둡니다.

[2026-09 정리]
- PRACTICE_RECOMMENDATIONS 제안 테이블은 제거했습니다. 실제 구현 결과
  InterviewQuestions.practice_reason 필드 + SESSION_COMPARISONS 테이블
  조합으로 같은 목적(이전 회차 반영, 회차 비교)을 더 단순하게 달성해서
  중복이 되었기 때문입니다.
- SESSION_TECHNICAL_EVENTS, NONVERBAL_EVENTS, USER_CONSENTS는 모두
  팀 확정으로 models.py로 승격되었습니다.
"""

from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


# ------------------------------------------------------------------
# [2026-09 확정] USER_CONSENTS는 팀 요청("개인정보 동의 코드 확정")으로
# 정식 테이블로 승격되어 models.py로 이동했습니다. (영상 저장 동의, 분석 동의,
# 보유기간, 동의 철회까지 포함)
# ------------------------------------------------------------------
# [2026-09 확정] SESSION_TECHNICAL_EVENTS는 팀 요청("실시간 경고 - 확정")으로
# 정식 테이블로 승격되어 models.py로 이동했습니다.
# [2026-09 확정] NONVERBAL_EVENTS는 팀 요청("영상+타임스탬프 빠르게 필요")으로
# 정식 테이블로 승격되어 models.py로 이동했습니다.
# ------------------------------------------------------------------

