"""
routers/uploads.py — 답변 녹화 파일 업로드 → STT → 내용/전달 분석
-------------------------------------------------------------------
프론트는 MediaRecorder Blob을 FormData로 전송하고, 백엔드는 아래를 순서대로 수행합니다.

1. 음성/영상 저장
2. 기본 STT -> 내용평가용 텍스트 저장
3. 상세 STT -> 머뭇거림/반복 표현 + 속도 raw feature
4. 로컬 비언어 AI -> 실제 음성/영상 측정 + delivery_profile 생성
5. 안전한 타임라인 이벤트 저장
6. 오디오 측정이 유효할 때만 RAG·언어 AI 내용평가

최종 전달 안정성 0~100 점수는 아직 만들지 않습니다.
"""

import os
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from database import get_session
from models import (
    InterviewQuestions,
    UserAnswers,
    AnswerAnalyses,
    Users,
    NonverbalEvents,
)
from stt_service import (
    transcribe_audio,
    transcribe_audio_detailed,
    is_ready as stt_is_ready,
    MAX_AUDIO_MB,
)
from stt_stability_features import analyze_stt_stability
from nonverbal_service import analyze_answer_delivery
from ai_service_client import get_ai_service, is_ready as ai_is_ready
from path_config import resolve_project_path

router = APIRouter(tags=["Uploads"])

UPLOAD_ROOT = resolve_project_path(os.getenv("UPLOAD_DIR"), "uploads").resolve()
AUDIO_DIR = UPLOAD_ROOT / "audio"
VIDEO_DIR = UPLOAD_ROOT / "video"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_EXTENSIONS = {".webm", ".mp4", ".mov", ".mkv"}
MAX_VIDEO_MB = 300
MAX_AUDIO_BYTES = MAX_AUDIO_MB * 1024 * 1024
MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024

STT_EVENT_TYPES = {"SPEECH_HESITATION", "SPEECH_REPETITION"}
AUTO_DELIVERY_EVENT_TYPES = {
    "GAZE_AWAY",
    "FACE_TURNED",
    "LONG_BLINK",
    "SMILE",
    "EXPRESSION_CHANGE",
    "NOD",
    "SHAKE",
    "BODY_MOVEMENT",
    "HAND_GESTURE",
    "LONG_PAUSE",
}

ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
    "audio/ogg",
}
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/webm",
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
}


async def _save_upload_with_limit(upload: UploadFile, destination: Path, max_bytes: int) -> int:
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
                    raise ValueError(
                        f"업로드 파일이 너무 큽니다: 최대 {max_bytes / (1024 * 1024):.0f}MB"
                    )
                out.write(chunk)
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _validate_video_file(path: Path, content_type: Optional[str] = None) -> None:
    if path.suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
        raise ValueError(
            f"허용되지 않은 영상 파일 형식: {path.suffix} "
            f"(허용: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))})"
        )
    if content_type and content_type not in ALLOWED_VIDEO_CONTENT_TYPES:
        raise ValueError(f"허용되지 않은 영상 Content-Type: {content_type}")
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_VIDEO_MB:
        raise ValueError(f"영상 파일이 너무 큽니다: {size_mb:.1f}MB (최대 {MAX_VIDEO_MB}MB)")


def _safe_media_path(raw_path: str) -> Path:
    path = Path(raw_path).resolve()
    if UPLOAD_ROOT not in path.parents and path != UPLOAD_ROOT:
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    return path


def _build_stt_stability_payload(features: dict) -> dict:
    return {
        "status": "available",
        "word_timestamps_available": bool(features.get("word_timestamps_available")),
        "speech_habits": features.get("speech_habits_report") or {},
        "pace": {
            "gross_syllables_per_min": features.get("gross_syllables_per_min"),
            "timed_span_syllables_per_min": features.get("timed_span_syllables_per_min"),
            "segment_rate_mean": features.get("segment_rate_mean"),
            "segment_rate_cv": features.get("segment_rate_cv"),
            "segment_rate_sample_count": features.get("segment_rate_sample_count"),
            "primary_metric_status": "policy_pending",
        },
        "pause_word_gap_reference": {
            "gap_0_5_count": features.get("pause_gap_0_5_count"),
            "gap_1_0_count": features.get("pause_gap_1_0_count"),
            "max_word_gap_sec": features.get("max_word_gap_sec"),
            "note": "단어 timestamp gap은 보조값이며 최종 침묵 평가는 실제 음성 신호 분석을 사용합니다.",
        },
        "scoring_note": "머뭇거림 표현과 반복 표현은 점수에 반영하지 않습니다.",
    }


def _delete_auto_events(session: Session, answer_id: int, event_types: set[str]) -> None:
    existing_events = session.exec(
        select(NonverbalEvents).where(NonverbalEvents.answer_id == answer_id)
    ).all()
    for event in existing_events:
        if event.event_type in event_types:
            session.delete(event)


def _replace_stt_timeline_events(session: Session, answer_id: int, features: dict) -> int:
    _delete_auto_events(session, answer_id, STT_EVENT_TYPES)

    speech_habits = features.get("speech_habits_report") or {}
    saved_count = 0

    hesitation = speech_habits.get("hesitation") or {}
    for item in hesitation.get("items") or []:
        start = item.get("start_sec")
        if not isinstance(start, (int, float)):
            continue
        session.add(
            NonverbalEvents(
                answer_id=answer_id,
                event_type="SPEECH_HESITATION",
                start_time_sec=float(start),
                value=item.get("expression"),
            )
        )
        saved_count += 1

    repetition = speech_habits.get("repetition") or {}
    for item in repetition.get("items") or []:
        start = item.get("start_sec")
        if not isinstance(start, (int, float)):
            continue
        session.add(
            NonverbalEvents(
                answer_id=answer_id,
                event_type="SPEECH_REPETITION",
                start_time_sec=float(start),
                value=item.get("expression"),
            )
        )
        saved_count += 1

    session.commit()
    return saved_count


def _replace_delivery_timeline_events(session: Session, answer_id: int, events: list[dict]) -> int:
    _delete_auto_events(session, answer_id, AUTO_DELIVERY_EVENT_TYPES)
    saved_count = 0
    for item in events or []:
        event_type = item.get("event_type")
        start = item.get("start_time_sec")
        if event_type not in AUTO_DELIVERY_EVENT_TYPES or not isinstance(start, (int, float)):
            continue
        end = item.get("end_time_sec")
        session.add(
            NonverbalEvents(
                answer_id=answer_id,
                event_type=event_type,
                start_time_sec=float(start),
                end_time_sec=float(end) if isinstance(end, (int, float)) else None,
                value=item.get("value"),
            )
        )
        saved_count += 1
    session.commit()
    return saved_count


@router.post("/user-answers/submit")
async def submit_answer(
    session: Session = Depends(get_session),
    session_id: int = Form(...),
    question_id: int = Form(...),
    user_id: int = Form(...),
    duration_sec: Optional[int] = Form(default=None),
    audio: UploadFile = File(...),
    video: Optional[UploadFile] = File(default=None),
):
    question = session.get(InterviewQuestions, question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(status_code=400, detail="해당 세션의 질문이 아닙니다.")
    if not session.get(Users, user_id):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    from routers.consents import has_active_consent

    if not has_active_consent(session, user_id, "AUDIO_RECORDING"):
        raise HTTPException(status_code=403, detail="음성 저장 동의(AUDIO_RECORDING)가 필요합니다.")
    if video is not None and not has_active_consent(session, user_id, "VIDEO_RECORDING"):
        raise HTTPException(status_code=403, detail="영상 저장 동의(VIDEO_RECORDING)가 필요합니다.")

    analysis_consent = has_active_consent(session, user_id, "ANALYSIS")

    try:
        if audio.content_type and audio.content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise ValueError(f"허용되지 않은 음성 Content-Type: {audio.content_type}")
        audio_suffix = Path(audio.filename or "answer.webm").suffix or ".webm"
        audio_path = AUDIO_DIR / f"{uuid4().hex}{audio_suffix.lower()}"
        await _save_upload_with_limit(audio, audio_path, MAX_AUDIO_BYTES)

        from stt_service import validate_audio_file
        validate_audio_file(audio_path)

        video_path_str = None
        if video is not None:
            video_suffix = Path(video.filename or "answer.webm").suffix or ".webm"
            video_path_obj = VIDEO_DIR / f"{uuid4().hex}{video_suffix.lower()}"
            await _save_upload_with_limit(video, video_path_obj, MAX_VIDEO_BYTES)
            _validate_video_file(video_path_obj, content_type=video.content_type)
            video_path_str = str(video_path_obj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = session.exec(
        select(UserAnswers).where(UserAnswers.question_id == question_id)
    ).first()
    if existing:
        if existing.user_id != user_id:
            raise HTTPException(status_code=403, detail="다른 사용자의 답변을 덮어쓸 수 없습니다.")
        answer = existing
    else:
        answer = UserAnswers(question_id=question_id, user_id=user_id)
        session.add(answer)

    answer.audio_path = str(audio_path)
    answer.video_path = video_path_str
    answer.duration_sec = duration_sec
    session.commit()
    session.refresh(answer)

    if not stt_is_ready():
        raise HTTPException(
            status_code=503,
            detail="STT 서비스가 초기화되지 않았습니다. 파일은 저장되었으니 OPENAI_API_KEY를 확인하세요.",
        )

    try:
        answer.stt_text = transcribe_audio(str(audio_path))
        session.add(answer)
        session.commit()
        session.refresh(answer)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"STT 변환 실패: {exc}") from exc

    stt_detail = None
    stt_features = None
    if analysis_consent:
        try:
            stt_detail = transcribe_audio_detailed(str(audio_path))
            stt_features = analyze_stt_stability(stt_detail)
            event_count = _replace_stt_timeline_events(session, answer.answer_id, stt_features)
            stt_stability = _build_stt_stability_payload(stt_features)
            stt_stability["timeline_event_count"] = event_count
        except Exception as exc:  # noqa: BLE001
            stt_stability = {
                "status": "unavailable",
                "reason": f"상세 STT 안정성 분석 실패: {exc}",
                "scoring_note": "기본 STT와 내용평가는 계속 사용할 수 있습니다.",
            }
    else:
        stt_stability = {
            "status": "not_run",
            "reason": "AI 분석 동의(ANALYSIS)가 없어 상세 말하기 습관 분석을 실행하지 않았습니다.",
        }

    # 캘리브레이션 웹 연결 전이므로 calibration=None.
    # 영상 분석이 실패하더라도 오디오 품질 검사는 가능한 한 별도로 유지됩니다.
    if analysis_consent:
        delivery_analysis = analyze_answer_delivery(
            video_path=video_path_str,
            audio_path=str(audio_path),
            stt_text=answer.stt_text or "",
            stt_detail=stt_detail,
            stt_features=stt_features,
            duration_sec=duration_sec,
            calibration=None,
        )
        delivery_event_count = _replace_delivery_timeline_events(
            session, answer.answer_id, delivery_analysis.get("events") or []
        )
        delivery_analysis["timeline_event_count"] = delivery_event_count
        delivery_analysis.pop("legacy_metrics", None)
        delivery_analysis.pop("events", None)
    else:
        delivery_analysis = {
            "status": "not_run",
            "reason": "AI 분석 동의(ANALYSIS)가 없어 전달 분석을 실행하지 않았습니다.",
            "delivery_profile": None,
            "audio_quality": None,
        }

    delivery_profile = delivery_analysis.get("delivery_profile") or {}
    measurement = delivery_profile.get("measurement") or {}
    audio_quality = delivery_analysis.get("audio_quality") or {}

    analysis_allowed_by_audio = measurement.get("language_analysis_allowed") is not False
    if audio_quality and audio_quality.get("is_valid") is False:
        analysis_allowed_by_audio = False

    analysis_id = None
    analysis_note = None
    analysis_retry_allowed = bool(analysis_consent and analysis_allowed_by_audio)

    if not analysis_consent:
        analysis_note = "AI 분석 동의(ANALYSIS)가 없어 내용평가를 건너뜁니다."
        analysis_retry_allowed = False
    elif not analysis_allowed_by_audio:
        issue_codes = measurement.get("audio_issue_codes") or [
            item.get("code")
            for item in (audio_quality.get("issues") or [])
            if isinstance(item, dict) and item.get("code")
        ]
        issue_text = ", ".join(issue_codes) if issue_codes else "오디오 품질 문제"
        analysis_note = f"{issue_text}로 측정이 어려워 내용평가를 실행하지 않았습니다. 답변을 다시 녹화해주세요."
        analysis_retry_allowed = False
    elif ai_is_ready():
        try:
            ai_service = get_ai_service()
            result = ai_service.analyze_answer(
                question_data={
                    "question_text": question.question_text,
                    "evaluation_points": question.evaluation_points or [],
                },
                stt_text=answer.stt_text,
            )
            analysis = answer.analysis
            if analysis is None:
                analysis = AnswerAnalyses(answer_id=answer.answer_id)
            analysis.job_evaluation = result["job_evaluation"]
            analysis.answer_evaluation = result["answer_evaluation"]
            analysis.strengths = result["strengths"]
            analysis.improvements = result["improvements"]
            analysis.job_score = result.get("job_score")
            analysis.answer_score = result.get("answer_score")
            analysis.scoring_version = result.get("scoring_version")
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
            analysis_id = analysis.analysis_id
        except Exception as exc:  # noqa: BLE001
            analysis_note = f"내용 분석은 실패했지만 답변/STT는 정상 저장됨: {exc}"
    else:
        analysis_note = "AI 서비스 미준비 상태 — 서비스 준비 후 내용평가를 다시 시도할 수 있습니다."

    return {
        "answer_id": answer.answer_id,
        "stt_text": answer.stt_text,
        "analysis_id": analysis_id,
        "note": analysis_note,
        "analysis_retry_allowed": analysis_retry_allowed,
        "stt_stability": stt_stability,
        "delivery_analysis": delivery_analysis,
    }


@router.get("/user-answers/{answer_id}/video")
def get_answer_video(answer_id: int, session: Session = Depends(get_session)):
    answer = session.get(UserAnswers, answer_id)
    if not answer or not answer.video_path:
        raise HTTPException(status_code=404, detail="이 답변에는 영상 파일이 없습니다.")
    return FileResponse(_safe_media_path(answer.video_path))


@router.get("/user-answers/{answer_id}/audio")
def get_answer_audio(answer_id: int, session: Session = Depends(get_session)):
    answer = session.get(UserAnswers, answer_id)
    if not answer or not answer.audio_path:
        raise HTTPException(status_code=404, detail="이 답변에는 음성 파일이 없습니다.")
    return FileResponse(_safe_media_path(answer.audio_path))
