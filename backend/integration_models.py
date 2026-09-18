"""A!SK 통합 규격 V1에서 새로 추가되는 저장 구조.

기존 models.py의 테이블은 건드리지 않고, 앞으로 연결할 캘리브레이션/전달분석을
GitHub main 기준의 공통 변수명으로 저장하기 위한 테이블만 분리해 둡니다.

현재는 스키마 선확정 단계입니다. 실제 저장 API는 웹 캘리브레이션/전달분석 연결 단계에서
이 테이블을 사용하도록 붙입니다.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field

from integration_contract_v1 import (
    CALIBRATION_STATUS_PENDING,
    CALIBRATION_STAGE_NOT_RUN,
    CALIBRATION_VERSION,
    DELIVERY_PROFILE_VERSION,
)


class CalibrationProfiles(SQLModel, table=True):
    """면접 세션 1회당 하나의 캘리브레이션 기준값."""

    __tablename__ = "calibration_profiles"

    calibration_id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="interview_sessions.session_id", unique=True, index=True)

    calibration_version: str = Field(default=CALIBRATION_VERSION, max_length=80)
    calibration_status: str = Field(default=CALIBRATION_STATUS_PENDING, max_length=30)
    visual_status: str = Field(default=CALIBRATION_STAGE_NOT_RUN, max_length=30)
    audio_status: str = Field(default=CALIBRATION_STAGE_NOT_RUN, max_length=30)

    # nonverbal_ai.CalibrationProfile의 실제 baseline 이름을 JSON 안에서도 그대로 유지.
    visual_baseline: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    audio_baseline: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    audio_quality: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    failure_reasons: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    technical_error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DeliveryAnalyses(SQLModel, table=True):
    """답변 1개당 하나의 canonical delivery_profile 저장."""

    __tablename__ = "delivery_analyses"

    delivery_analysis_id: Optional[int] = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="user_answers.answer_id", unique=True, index=True)

    profile_version: str = Field(default=DELIVERY_PROFILE_VERSION, max_length=80)
    status: str = Field(default="unavailable", max_length=30)

    # canonical shape:
    # delivery_profile.measurement
    # delivery_profile.components.{speaking_flow, pace_stability, volume_stability,
    #                              gaze_stability, posture_stability}
    # delivery_profile.report_only
    # delivery_profile.aggregation_policy
    delivery_profile: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))

    # 점수 정책 확정 전에는 None. 측정 실패도 0점으로 저장하지 않는다.
    delivery_score: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DeliverySessionSummaries(SQLModel, table=True):
    """한 세션의 질문별 전달분석을 합친 결과."""

    __tablename__ = "delivery_session_summaries"

    delivery_summary_id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="interview_sessions.session_id", unique=True, index=True)

    summary_version: str = Field(default=DELIVERY_PROFILE_VERSION, max_length=80)
    status: str = Field(default="pending", max_length=30)
    question_count: int = Field(default=0, ge=0)
    eligible_question_count: int = Field(default=0, ge=0)

    # 점수 정책 확정 후 각 구성요소의 질문 평균을 저장한다.
    # 키는 gaze_score, posture_score, speaking_flow_score, pace_score, volume_score를 사용.
    component_averages: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    delivery_score_average: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
