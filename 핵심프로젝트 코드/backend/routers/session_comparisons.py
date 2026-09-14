"""
SESSION_COMPARISONS 관련 API — 1회차 vs 2회차 비교
----------------------------------------------------
같은 사용자의 두 세션에서 비언어 지표 평균을 계산해 변화량을 저장합니다.

종합 점수 비교는 답변 분석에서 계산된 job_score와 answer_score를 평균한
회차 점수(overall_score)를 기준으로 동작합니다. 비언어 데이터가 없어도
1회차/2회차 점수 비교가 가능하고, 비언어 데이터가 들어오면 추가 지표도 함께 비교합니다.
"""

from statistics import mean
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import InterviewSessions, InterviewQuestions, UserAnswers, SessionComparisons

router = APIRouter(prefix="/session-comparisons", tags=["SessionComparisons"])

# 비교에 사용할 비언어 지표 (숫자형만 — voice_emotion_label 등 문자열 필드는 제외)
COMPARISON_METRICS = [
    "gaze_center_ratio",
    "speaking_speed",
    "filler_word_count",
    "pause_count",
    "average_volume",
    "pitch_variation",
    "upper_body_sway",
]


def _session_metric_averages(db: Session, session_id: int) -> dict:
    """세션에 속한 모든 답변의 비언어 지표 평균을 계산합니다."""
    questions = db.exec(
        select(InterviewQuestions).where(InterviewQuestions.session_id == session_id)
    ).all()

    values: dict = {m: [] for m in COMPARISON_METRICS}
    for q in questions:
        answer = db.exec(
            select(UserAnswers).where(UserAnswers.question_id == q.question_id)
        ).first()
        if not answer or not answer.nonverbal_metric:
            continue
        metric = answer.nonverbal_metric
        for name in COMPARISON_METRICS:
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
    for metric in COMPARISON_METRICS:
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
        direction = '향상' if score_change > 0 else ('하락' if score_change < 0 else '변화 없음')
        score_line = f'종합점수: {first_score:.1f} -> {second_score:.1f} ({score_change:+.1f}, {direction})'

    summary_lines = []
    if score_line:
        summary_lines.append(score_line)
    if changed_lines:
        summary_lines.extend(changed_lines)
    elif not score_line:
        summary_lines.append('비언어 및 종합점수 데이터가 없어 비교할 수치가 없습니다.')

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
