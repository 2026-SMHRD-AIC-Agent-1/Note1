"""INTERVIEW_QUESTIONS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import InterviewQuestions

router = APIRouter(tags=["InterviewQuestions"])


@router.post("/interview-questions", response_model=InterviewQuestions)
def create_interview_question(q: InterviewQuestions, session: Session = Depends(get_session)):
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


@router.get("/interview-questions", response_model=List[InterviewQuestions])
def list_interview_questions(session: Session = Depends(get_session)):
    return session.exec(select(InterviewQuestions)).all()


@router.get("/interview-sessions/{session_id}/questions", response_model=List[InterviewQuestions])
def list_questions_by_session(session_id: int, session: Session = Depends(get_session)):
    return session.exec(
        select(InterviewQuestions).where(InterviewQuestions.session_id == session_id)
    ).all()
