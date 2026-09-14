"""
SESSION_TECHNICAL_EVENTS 관련 API
---------------------------------
면접 연습 중 발생하는 마이크 미감지·소음·네트워크 문제 등을 기록합니다.

역할 분담:
  - 실시간 경고(사용자에게 즉시 뜨는 팝업/배너)는 Frontend가 감지하고 직접 처리합니다.
  - 이 API는 "그런 일이 있었다"는 로그를 남기는 역할만 합니다.
    (나중에 면접자가 "왜 이 구간에서 답변이 이상하지?" 확인할 때 참고 가능)
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import SessionTechnicalEvents, InterviewSessions

router = APIRouter(prefix="/session-technical-events", tags=["SessionTechnicalEvents"])


@router.post("", response_model=SessionTechnicalEvents)
def create_technical_event(event: SessionTechnicalEvents, session: Session = Depends(get_session)):
    if not session.get(InterviewSessions, event.session_id):
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("", response_model=List[SessionTechnicalEvents])
def list_technical_events(session: Session = Depends(get_session)):
    return session.exec(select(SessionTechnicalEvents)).all()


@router.get("/sessions/{session_id}", response_model=List[SessionTechnicalEvents])
def list_technical_events_for_session(session_id: int, session: Session = Depends(get_session)):
    """특정 세션에서 발생한 기술 경고 이력을 시간순으로 반환합니다."""
    return session.exec(
        select(SessionTechnicalEvents)
        .where(SessionTechnicalEvents.session_id == session_id)
        .order_by(SessionTechnicalEvents.created_at)
    ).all()
