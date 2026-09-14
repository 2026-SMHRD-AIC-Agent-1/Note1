"""
NONVERBAL_EVENTS 관련 API
------------------------
면접 영상의 특정 시점(예: 00:43 시선 이탈)을 기록/조회합니다.
`/user-answers/{answer_id}/events`는 video_path와 이벤트 목록을 함께
반환하므로, Frontend가 "문제 지점 클릭 → 그 시점부터 영상 재생" 기능을
바로 만들 수 있습니다.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import NonverbalEvents, UserAnswers

router = APIRouter(tags=["NonverbalEvents"])


@router.post("/nonverbal-events", response_model=NonverbalEvents)
def create_nonverbal_event(event: NonverbalEvents, session: Session = Depends(get_session)):
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/nonverbal-events", response_model=List[NonverbalEvents])
def list_nonverbal_events(session: Session = Depends(get_session)):
    return session.exec(select(NonverbalEvents)).all()


class AnswerEventsResponse(BaseModel):
    """영상 재생에 필요한 정보를 한 번에 묶어서 반환 (Frontend 편의용)"""
    answer_id: int
    video_path: Optional[str]
    audio_path: Optional[str]
    duration_sec: Optional[int]
    events: List[NonverbalEvents]


@router.get("/user-answers/{answer_id}/events", response_model=AnswerEventsResponse)
def get_events_for_answer(answer_id: int, session: Session = Depends(get_session)):
    """
    특정 답변의 영상 경로 + 그 안에서 발생한 이벤트 목록을 함께 반환합니다.
    Frontend는 이 응답 하나로 "영상 플레이어 + 문제 지점 마커"를 그릴 수 있습니다.
    """
    answer = session.get(UserAnswers, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")

    events = session.exec(
        select(NonverbalEvents)
        .where(NonverbalEvents.answer_id == answer_id)
        .order_by(NonverbalEvents.start_time_sec)
    ).all()

    return AnswerEventsResponse(
        answer_id=answer.answer_id,
        video_path=answer.video_path,
        audio_path=answer.audio_path,
        duration_sec=answer.duration_sec,
        events=events,
    )
