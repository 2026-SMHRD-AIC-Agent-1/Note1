"""
SESSION_COMPARISONS 관련 API — 1회차 vs 2회차 비교
----------------------------------------------------
같은 사용자의 두 세션에서 내용 종합점수와 기존 비언어 참고값의 변화량을 저장합니다.

현재 overall_score는 job_score와 answer_score를 바탕으로 계산한 '내용 종합점수'입니다.
전달 안정성 최종 점수는 아직 포함하지 않습니다.
머뭇거림 표현/반복 표현은 리포트 전용이므로 회차 점수 비교 항목에서 제외합니다.
"""

from statistics import mean
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import InterviewSessions, InterviewQuestions, UserAnswers, SessionComparisons

router = APIRouter(prefix="/session-comparisons", tags=["SessionComparisons"])

# 캘리브레이션 기반 새 전달 안정성 구조가 서비스에 연결되기 전까지 사용하는
# 기존 숫자형 참고 지표입니다. 머뭇거림/반복 표현은 점수·비교 지표에서 제외합니다.
LEGACY_REFERENCE_METRICS = [
    "gaze_center_ratio",
    "speaking_speed",
    "pause_count",
    "average_volume",
    "pitch_variation",
    "upper_body_sway",
]


def _session_metric_averages(db: Session, session_id: int) -> dict:
    """세션에 속한 모든 답변의 기존 비언어 참고값 평균을 계산합니다."""
    questions = db.exec(
        select(InterviewQuestions).where(InterviewQuestions.session_id == session_id)
    ).all()

    values: dict = {m: [] for m in LEGACY_REFERENCE_METRICS}
    for q in questions:
        answer = db.exec(
            select(UserAnswers).where(UserAnswers.question_id == q.question_id)
        ).first()
        if not answer or not answer.nonverbal_metric:
            continue
        metric = answer.nonverbal_metric
        for name in LEGACY_REFERENCE_METRICS:
            value = getattr(metric, name, None)
            if value is not None:
                values[name].append(float(value))

    return {name: (mean(vals) if vals else None) for name, vals in values.items()}


class CreateComparisonRequest(BaseModel):
    first_session_id: int
    second_session_id: int


@router.post("", response_model=SessionComparisons)
def create_session_comparison(req: CreateComparisonRequest, db: Session = Depends(get_session)):
    first = db.get(InterviewSessions, req.first_session_id)
    second = db.get(InterviewSessions, req.second_session_id)
    if not first or not second:
        raise HTTPException(status_code=404, detail="비교할 세션을 찾을 수 없습니다.")
    if first.user_id != second.user_id:
        raise HTTPException(status_code=400, detail="서로 다른 사용자의 세션은 비교할 수 없습니다.")

    a = _session_metric_averages(db, req.first_session_id)
    b = _session_metric_averages(db, req.second_session_id)

    changed_lines = []
    for metric in LEGACY_REFERENCE_METRICS:
        av, bv = a[metric], b[metric]
        if av is not None and bv is not None:
            changed_lines.append(f"{metric}: {av:.2f} -> {bv:.2f} (변화 {bv - av:+.2f})")

    first_score = first.coaching.overall_score if first.coaching else None
    second_score = second.coaching.overall_score if second.coaching else None
    score_change = (
        second_score - first_score if first_score is not None and second_score is not None else None
    )

    score_line = None
    if first_score is not None and second_score is not None:
        direction = "향상" if score_change > 0 else ("하락" if score_change < 0 else "변화 없음")
        score_line = (
            f"내용 종합점수: {first_score:.1f} -> {second_score:.1f} "
            f"({score_change:+.1f}, {direction})"
        )

    summary_lines = []
    if score_line:
        summary_lines.append(score_line)
    if changed_lines:
        summary_lines.append("기존 비언어 참고값:")
        summary_lines.extend(changed_lines)
    elif not score_line:
        summary_lines.append("내용 종합점수와 기존 비언어 참고값이 없어 비교할 수치가 없습니다.")

    comparison = SessionComparisons(
        first_session_id=req.first_session_id,
        second_session_id=req.second_session_id,
        first_overall_score=first_score,
        second_overall_score=second_score,
        score_change=score_change,
        improved_items=score_line,
        comparison_summary="\n".join(summary_lines),
    )
    db.add(comparison)
    db.commit()
    db.refresh(comparison)
    return comparison


@router.get("", response_model=List[SessionComparisons])
def list_session_comparisons(db: Session = Depends(get_session)):
    return db.exec(select(SessionComparisons)).all()
