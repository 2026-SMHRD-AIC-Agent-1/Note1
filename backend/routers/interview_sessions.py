"""INTERVIEW_SESSIONS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import InterviewSessions, FinalCoachings, InterviewQuestions, UserAnswers
from integration_models import DeliveryAnalyses, DeliverySessionSummaries
from delivery_scoring import compute_delivery_score, COMPONENT_WEIGHTS

router = APIRouter(prefix="/interview-sessions", tags=["InterviewSessions"])


@router.post("", response_model=InterviewSessions)
def create_interview_session(sess: InterviewSessions, session: Session = Depends(get_session)):
    # previous_session_id가 있으면 attempt_no를 "이전 회차 + 1"로 자동 계산합니다.
    # (프론트/AI가 attempt_no를 직접 계산해서 보낼 필요 없이, 이전 세션 id만 넘기면 됨)
    if sess.previous_session_id is not None:
        previous = session.get(InterviewSessions, sess.previous_session_id)
        if not previous:
            raise HTTPException(status_code=404, detail="previous_session_id에 해당하는 세션이 없습니다.")
        if previous.user_id != sess.user_id:
            raise HTTPException(status_code=400, detail="서로 다른 사용자의 세션은 연결할 수 없습니다.")
        sess.attempt_no = previous.attempt_no + 1

    session.add(sess)
    session.commit()
    session.refresh(sess)
    return sess


@router.get("", response_model=List[InterviewSessions])
def list_interview_sessions(session: Session = Depends(get_session)):
    return session.exec(select(InterviewSessions)).all()


@router.get("/{session_id}", response_model=InterviewSessions)
def get_interview_session(session_id: int, session: Session = Depends(get_session)):
    obj = session.get(InterviewSessions, session_id)
    if not obj:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")
    return obj


@router.get("/{session_id}/coaching", response_model=FinalCoachings)
def get_coaching_by_session(session_id: int, session: Session = Depends(get_session)):
    stmt = select(FinalCoachings).where(FinalCoachings.session_id == session_id)
    obj = session.exec(stmt).first()
    if not obj:
        raise HTTPException(status_code=404, detail="해당 세션의 코칭 결과가 없습니다.")
    return obj


@router.get("/{session_id}/delivery-summary", response_model=DeliverySessionSummaries)
def get_delivery_summary(session_id: int, session: Session = Depends(get_session)):
    """세션의 질문별 전달 안정성 점수를 모아 세션 평균을 계산·저장(upsert)하고 반환한다.

    측정 실패(measurement_unavailable)한 답변은 평균 계산에서 제외한다.
    정상 측정된 질문이 전체 질문의 2/3 미만이면 대표성이 없다고 보고
    delivery_score_average 자체를 계산하지 않는다(status="measurement_unavailable").
    """
    if not session.get(InterviewSessions, session_id):
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")

    question_ids = session.exec(
        select(InterviewQuestions.question_id).where(InterviewQuestions.session_id == session_id)
    ).all()
    question_count = len(question_ids)

    answer_ids = []
    if question_ids:
        answer_ids = session.exec(
            select(UserAnswers.answer_id).where(UserAnswers.question_id.in_(question_ids))
        ).all()

    delivery_rows = []
    if answer_ids:
        delivery_rows = session.exec(
            select(DeliveryAnalyses).where(DeliveryAnalyses.answer_id.in_(answer_ids))
        ).all()

    per_component_scores: dict[str, list[float]] = {key: [] for key in COMPONENT_WEIGHTS}
    eligible_scores: list[float] = []

    for row in delivery_rows:
        result = compute_delivery_score(row.delivery_profile)
        if result["status"] == "available" and result["delivery_score"] is not None:
            eligible_scores.append(result["delivery_score"])
            for key, value in (result.get("component_scores") or {}).items():
                if value is not None and key in per_component_scores:
                    per_component_scores[key].append(value)

    eligible_question_count = len(eligible_scores)

    # PM 리뷰 반영: 정상 측정된 질문이 전체 질문의 2/3 미만이면 세션 전달 안정성
    # 점수 자체를 표시하지 않는다 (측정 범위가 너무 좁아 대표성이 없다고 봄).
    MIN_ELIGIBLE_RATIO = 2 / 3
    enough_coverage = (
        question_count > 0 and (eligible_question_count / question_count) >= MIN_ELIGIBLE_RATIO
    )

    delivery_score_average = (
        round(sum(eligible_scores) / eligible_question_count, 1)
        if eligible_question_count and enough_coverage
        else None
    )
    component_averages = {
        f"{key}_score": (round(sum(values) / len(values), 1) if values else None)
        for key, values in per_component_scores.items()
    }
    status = "available" if (eligible_question_count and enough_coverage) else "measurement_unavailable"

    existing = session.exec(
        select(DeliverySessionSummaries).where(DeliverySessionSummaries.session_id == session_id)
    ).first()
    summary_row = existing or DeliverySessionSummaries(session_id=session_id)
    summary_row.status = status
    summary_row.question_count = question_count
    summary_row.eligible_question_count = eligible_question_count
    summary_row.component_averages = component_averages
    summary_row.delivery_score_average = delivery_score_average

    session.add(summary_row)
    session.commit()
    session.refresh(summary_row)
    return summary_row


@router.get("/users/{user_id}/history", response_model=List[InterviewSessions])
def get_user_session_history(user_id: int, session: Session = Depends(get_session)):
    """특정 사용자의 전체 회차(1회차, 2회차...)를 오래된 순으로 반환합니다."""
    return session.exec(
        select(InterviewSessions)
        .where(InterviewSessions.user_id == user_id)
        .order_by(InterviewSessions.attempt_no)
    ).all()
