"""
USER_CONSENTS 관련 API (개인정보 동의)
--------------------------------------
영상 저장 동의 / 분석 동의 / 보유기간 / 동의 철회를 관리합니다.

"실시간 경고"는 이 라우터가 아니라 routers/uploads.py의 submit_answer()에서
처리됩니다 — 영상·음성을 실제로 업로드하려는 순간에 해당 동의가 없으면
그 자리에서 막고 이유를 알려주는 방식이 "사후 로그"보다 실제 개인정보
보호 취지에 맞기 때문입니다. (기술 문제 경고는 SESSION_TECHNICAL_EVENTS가
따로 담당 — 그건 "환경 문제 기록", 이건 "동의 여부 실시간 확인"으로 성격이 다름)
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import UserConsents, Users

router = APIRouter(prefix="/consents", tags=["UserConsents"])

VALID_CONSENT_TYPES = {"VIDEO_RECORDING", "AUDIO_RECORDING", "ANALYSIS", "DATA_RETENTION"}
DEFAULT_RETENTION_DAYS = 365  # 팀에서 별도 정책을 정하기 전까지의 기본값


@router.post("", response_model=UserConsents)
def create_consent(consent: UserConsents, session: Session = Depends(get_session)):
    if consent.consent_type not in VALID_CONSENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"consent_type은 {sorted(VALID_CONSENT_TYPES)} 중 하나여야 합니다.",
        )
    if not session.get(Users, consent.user_id):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    if consent.retention_days is None:
        consent.retention_days = DEFAULT_RETENTION_DAYS
    if consent.is_agreed and consent.retention_until is None:
        consent.retention_until = consent.consented_at + timedelta(days=consent.retention_days)

    session.add(consent)
    session.commit()
    session.refresh(consent)
    return consent


@router.get("", response_model=List[UserConsents])
def list_consents(session: Session = Depends(get_session)):
    return session.exec(select(UserConsents)).all()


@router.get("/users/{user_id}", response_model=List[UserConsents])
def get_user_consents(user_id: int, session: Session = Depends(get_session)):
    """이 사용자가 지금까지 어떤 동의를 했는지 전체 이력을 반환합니다."""
    return session.exec(
        select(UserConsents).where(UserConsents.user_id == user_id).order_by(UserConsents.consented_at)
    ).all()


def has_active_consent(session: Session, user_id: int, consent_type: str) -> bool:
    """
    이 사용자가 해당 항목에 '현재 유효한' 동의를 했는지 확인합니다.
    (동의했음 + 철회 안 함 + 보유기간 안 지남) 전부 만족해야 True.
    routers/uploads.py가 파일 업로드 직전에 이 함수를 호출해 실시간으로 막습니다.
    """
    consents = session.exec(
        select(UserConsents)
        .where(UserConsents.user_id == user_id, UserConsents.consent_type == consent_type)
        .order_by(UserConsents.consented_at.desc())
    ).all()
    if not consents:
        return False
    latest = consents[0]
    if not latest.is_agreed or latest.revoked_at is not None:
        return False
    if latest.retention_until is not None and latest.retention_until < datetime.utcnow():
        return False
    return True


@router.post("/{consent_id}/revoke", response_model=UserConsents)
def revoke_consent(consent_id: int, session: Session = Depends(get_session)):
    consent = session.get(UserConsents, consent_id)
    if not consent:
        raise HTTPException(status_code=404, detail="동의 기록을 찾을 수 없습니다.")
    consent.revoked_at = datetime.utcnow()
    session.add(consent)
    session.commit()
    session.refresh(consent)
    return consent


@router.get("/expiring", response_model=List[UserConsents])
def list_expired_or_expiring(within_days: Optional[int] = None, session: Session = Depends(get_session)):
    """
    보유기간이 이미 지났거나(기본), within_days를 주면 그 안에 곧 만료될 동의 목록을 반환합니다.
    PM/운영 담당이 주기적으로 확인해서 파일 삭제 배치를 돌리는 용도로 씁니다.
    """
    now = datetime.utcnow()
    cutoff = now + timedelta(days=within_days) if within_days else now
    return session.exec(
        select(UserConsents)
        .where(UserConsents.retention_until != None)  # noqa: E711
        .where(UserConsents.retention_until <= cutoff)
        .where(UserConsents.media_deleted == False)  # noqa: E712
    ).all()
