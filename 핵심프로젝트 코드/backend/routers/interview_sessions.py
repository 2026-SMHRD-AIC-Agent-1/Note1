"""INTERVIEW_SESSIONS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import InterviewSessions, FinalCoachings

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


@router.get("/users/{user_id}/history", response_model=List[InterviewSessions])
def get_user_session_history(user_id: int, session: Session = Depends(get_session)):
    """특정 사용자의 전체 회차(1회차, 2회차...)를 오래된 순으로 반환합니다."""
    return session.exec(
        select(InterviewSessions)
        .where(InterviewSessions.user_id == user_id)
        .order_by(InterviewSessions.attempt_no)
    ).all()
