"""USERS 관련 API"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import Users

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=Users)
def create_user(user: Users, session: Session = Depends(get_session)):
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("", response_model=List[Users])
def list_users(session: Session = Depends(get_session)):
    return session.exec(select(Users)).all()


@router.get("/{user_id}", response_model=Users)
def get_user(user_id: int, session: Session = Depends(get_session)):
    user = session.get(Users, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return user
