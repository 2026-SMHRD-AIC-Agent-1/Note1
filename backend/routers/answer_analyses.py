"""ANSWER_ANALYSES 관련 API"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import AnswerAnalyses

router = APIRouter(prefix="/answer-analyses", tags=["AnswerAnalyses"])


@router.post("", response_model=AnswerAnalyses)
def create_answer_analysis(analysis: AnswerAnalyses, session: Session = Depends(get_session)):
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    return analysis


@router.get("", response_model=List[AnswerAnalyses])
def list_answer_analyses(session: Session = Depends(get_session)):
    return session.exec(select(AnswerAnalyses)).all()
