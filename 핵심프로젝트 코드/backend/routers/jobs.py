"""JOBS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import Jobs

router = APIRouter(tags=["Jobs"])


@router.post("/jobs", response_model=Jobs)
def create_job(job: Jobs, session: Session = Depends(get_session)):
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


@router.get("/jobs", response_model=List[Jobs])
def list_jobs(session: Session = Depends(get_session)):
    return session.exec(select(Jobs)).all()


@router.get("/companies/{company_id}/jobs", response_model=List[Jobs])
def list_jobs_by_company(company_id: int, session: Session = Depends(get_session)):
    return session.exec(select(Jobs).where(Jobs.company_id == company_id)).all()
