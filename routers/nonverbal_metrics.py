"""
NONVERBAL_METRICS 관련 API
※ 14개 측정 필드는 비언어 AI 담당의 최종 확인 전 초안입니다.
  (통합 프로젝트 문서 "충돌 ④⑤" 참고)
"""

from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from database import get_session
from models import NonverbalMetrics

router = APIRouter(prefix="/nonverbal-metrics", tags=["NonverbalMetrics"])


@router.post("", response_model=NonverbalMetrics)
def create_nonverbal_metrics(metrics: NonverbalMetrics, session: Session = Depends(get_session)):
    session.add(metrics)
    session.commit()
    session.refresh(metrics)
    return metrics


@router.get("", response_model=List[NonverbalMetrics])
def list_nonverbal_metrics(session: Session = Depends(get_session)):
    return session.exec(select(NonverbalMetrics)).all()
