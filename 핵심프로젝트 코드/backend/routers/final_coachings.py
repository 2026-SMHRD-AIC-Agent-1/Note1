"""FINAL_COACHINGS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import FinalCoachings

router = APIRouter(prefix="/final-coachings", tags=["FinalCoachings"])


@router.post("", response_model=FinalCoachings)
def create_final_coaching(coaching: FinalCoachings, session: Session = Depends(get_session)):
    session.add(coaching)
    session.commit()
    session.refresh(coaching)
    return coaching


@router.get("", response_model=List[FinalCoachings])
def list_final_coachings(session: Session = Depends(get_session)):
    return session.exec(select(FinalCoachings)).all()
