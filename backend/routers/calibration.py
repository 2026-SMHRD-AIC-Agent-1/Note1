"""캘리브레이션(CALIBRATION_PROFILES) API — A안: 짧은 클립 녹화 후 업로드.

흐름:
    1. 프론트: 화면 중앙 점 보기(3초 유지) + 안내 문장 읽기를 한 번에
       4~6초짜리 영상(오디오 포함)으로 녹화해 업로드
    2. 백엔드: calibration_service.run_calibration()으로 판정
    3. CALIBRATION_PROFILES에 세션당 1개로 upsert 저장
    4. calibration_status == "passed"일 때만 프론트가 실제 질문 단계로 진입

세션 도중에는 다시 캘리브레이션하지 않는다(통합 규격 V1 원칙).
"""
from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from database import get_session
from models import InterviewSessions
from integration_models import CalibrationProfiles
from path_config import resolve_project_path
import calibration_service

router = APIRouter(prefix="/calibration", tags=["Calibration"])

UPLOAD_ROOT = resolve_project_path(os.getenv("UPLOAD_DIR"), "uploads").resolve()
CALIBRATION_DIR = UPLOAD_ROOT / "calibration"
CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_EXTENSIONS = {".webm", ".mp4", ".mov", ".mkv"}
MAX_CALIBRATION_VIDEO_MB = 60
MAX_CALIBRATION_VIDEO_BYTES = MAX_CALIBRATION_VIDEO_MB * 1024 * 1024


async def _save_upload_with_limit(upload: UploadFile, destination: Path, max_bytes: int) -> None:
    total = 0
    chunk_size = 1024 * 1024
    try:
        with destination.open("wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"업로드 파일이 너무 큽니다: 최대 {max_bytes / (1024 * 1024):.0f}MB")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@router.post("/sessions/{session_id}", response_model=CalibrationProfiles)
async def run_session_calibration(
    session_id: int,
    session: Session = Depends(get_session),
    duration_sec: Optional[float] = Form(default=None),
    video: UploadFile = File(...),
):
    """짧은 캘리브레이션 클립(영상+오디오 한 파일)을 받아 판정 후 저장한다."""
    interview_session = session.get(InterviewSessions, session_id)
    if not interview_session:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")

    suffix = Path(video.filename or "calibration.webm").suffix.lower() or ".webm"
    if suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 영상 형식: {suffix}")

    video_path = CALIBRATION_DIR / f"{uuid4().hex}{suffix}"
    try:
        await _save_upload_with_limit(video, video_path, MAX_CALIBRATION_VIDEO_BYTES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        contract = calibration_service.run_calibration(
            video_path=str(video_path),
            duration_sec=duration_sec,
        )
    finally:
        video_path.unlink(missing_ok=True)

    existing = session.exec(
        select(CalibrationProfiles).where(CalibrationProfiles.session_id == session_id)
    ).first()
    if existing:
        profile_row = existing
    else:
        profile_row = CalibrationProfiles(session_id=session_id)

    profile_row.calibration_version = contract["calibration_version"]
    profile_row.calibration_status = contract["calibration_status"]
    profile_row.visual_status = contract["visual_status"]
    profile_row.audio_status = contract["audio_status"]
    profile_row.visual_baseline = contract["visual_baseline"]
    profile_row.audio_baseline = contract["audio_baseline"]
    profile_row.audio_quality = contract["audio_quality"]
    profile_row.failure_reasons = contract["failure_reasons"]
    profile_row.technical_error = contract["technical_error"]

    session.add(profile_row)
    session.commit()
    session.refresh(profile_row)
    return profile_row


@router.get("/sessions/{session_id}", response_model=CalibrationProfiles)
def get_session_calibration(session_id: int, session: Session = Depends(get_session)):
    obj = session.exec(
        select(CalibrationProfiles).where(CalibrationProfiles.session_id == session_id)
    ).first()
    if not obj:
        raise HTTPException(status_code=404, detail="이 세션의 캘리브레이션 기록이 없습니다.")
    return obj
