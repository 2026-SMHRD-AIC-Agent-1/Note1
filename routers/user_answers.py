"""USER_ANSWERS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import UserAnswers

router = APIRouter(prefix="/user-answers", tags=["UserAnswers"])


@router.post("", response_model=UserAnswers)
def create_user_answer(answer: UserAnswers, session: Session = Depends(get_session)):
    session.add(answer)
    session.commit()
    session.refresh(answer)
    return answer


@router.get("", response_model=List[UserAnswers])
def list_user_answers(session: Session = Depends(get_session)):
    return session.exec(select(UserAnswers)).all()


@router.get("/{answer_id}", response_model=UserAnswers)
def get_user_answer(answer_id: int, session: Session = Depends(get_session)):
    obj = session.get(UserAnswers, answer_id)
    if not obj:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")
    return obj
