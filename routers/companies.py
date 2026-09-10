"""COMPANIES 관련 API"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import Companies

router = APIRouter(prefix="/companies", tags=["Companies"])


@router.post("", response_model=Companies)
def create_company(company: Companies, session: Session = Depends(get_session)):
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


@router.get("", response_model=List[Companies])
def list_companies(session: Session = Depends(get_session)):
    return session.exec(select(Companies)).all()
