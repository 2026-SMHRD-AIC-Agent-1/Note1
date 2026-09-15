"""
routers/uploads.py — 답변 녹화 파일 업로드 → STT → (가능하면) 분석까지 한 번에
------------------------------------------------------------------------------
프론트는 녹화 시작/종료 + MediaRecorder Blob 생성 + FormData 전송만 담당합니다.
백엔드는 저장 -> 기본 STT -> 내용 분석 -> 상세 STT 안정성 분석까지 이어서 수행합니다.

상세 STT 안정성 분석은 최종 점수를 만들지 않습니다.
- 머뭇거림 표현/반복 표현: 리포트 전용
- 단어 timestamp가 있으면 발생 시점을 NONVERBAL_EVENTS에 저장
- 발화 속도 관련 raw feature는 응답으로 전달하되 최종 점수 기준은 아직 적용하지 않음
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

# 상세 STT에서 자동 생성하는 타임라인 이벤트.
# 재제출 시 이 두 종류만 지웠다가 다시 생성하여 중복 누적을 막습니다.
STT_EVENT_TYPES = {"SPEECH_HESITATION", "SPEECH_REPETITION"}

# 브라우저가 보내는 Content-Type도 함께 확인합니다 (확장자만으로는 위조가 쉬움).
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
    """업로드 전체를 메모리에 올리지 않고 chunk 단위로 저장하고 크기를 제한합니다."""
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
    """저장된 경로가 UPLOAD_ROOT 밖을 가리키지 않는지 확인합니다."""
    path = Path(raw_path).resolve()
    if UPLOAD_ROOT not in path.parents and path != UPLOAD_ROOT:
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    return path


def _build_stt_stability_payload(features: dict) -> dict:
    """프론트가 바로 쓸 수 있도록 상세 STT 결과 중 필요한 값만 정리합니다."""
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
            "note": "단어 timestamp 기반 gap은 보조값이며 최종 침묵 평가는 음성 신호 분석을 사용합니다.",
        },
        "scoring_note": "머뭇거림 표현과 반복 표현은 점수에 반영하지 않습니다.",
    }


def _replace_stt_timeline_events(session: Session, answer_id: int, features: dict) -> int:
    """상세 STT의 말하기 습관 발생 시점을 타임라인 이벤트로 저장합니다."""
    existing_events = session.exec(
        select(NonverbalEvents).where(NonverbalEvents.answer_id == answer_id)
    ).all()
    for event in existing_events:
        if event.event_type in STT_EVENT_TYPES:
            session.delete(event)

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
    """
    답변 녹화 파일을 업로드받아 아래 순서로 처리합니다.

    1. 음성/영상 저장
    2. 기본 STT -> USER_ANSWERS.stt_text 저장
    3. ANALYSIS 동의가 있으면 상세 STT -> 말하기 습관/속도 raw feature 계산
    4. 머뭇거림/반복 표현 timestamp를 NONVERBAL_EVENTS에 저장
    5. 가능하면 RAG·언어 AI 답변 분석

    상세 STT 분석 실패는 기본 STT/내용평가를 실패시키지 않습니다.
    """
    # 1. 권한/존재 확인
    question = session.get(InterviewQuestions, question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(status_code=400, detail="해당 세션의 질문이 아닙니다.")
    if not session.get(Users, user_id):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    from routers.consents import has_active_consent

    if not has_active_consent(session, user_id, "AUDIO_RECORDING"):
        raise HTTPException(
            status_code=403,
            detail="음성 저장 동의가 확인되지 않았습니다. 먼저 POST /consents로 "
                   "AUDIO_RECORDING 동의를 받아야 답변을 업로드할 수 있습니다.",
        )
    if video is not None and not has_active_consent(session, user_id, "VIDEO_RECORDING"):
        raise HTTPException(
            status_code=403,
            detail="영상 저장 동의가 확인되지 않았습니다. 먼저 POST /consents로 "
                   "VIDEO_RECORDING 동의를 받거나, 영상 없이(음성만) 제출하세요.",
        )

    analysis_consent = has_active_consent(session, user_id, "ANALYSIS")

    try:
        # 2. 파일 저장
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

    # 3. USER_ANSWERS 생성 또는 갱신
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

    # 4. 기본 STT — 내용평가가 사용하는 텍스트 경로는 기존 그대로 유지
    if not stt_is_ready():
        raise HTTPException(
            status_code=503,
            detail="STT 서비스가 초기화되지 않았습니다 (OPENAI_API_KEY 확인 필요). "
                   "파일과 답변 레코드는 저장되었으니, 서비스 준비 후 다시 분석을 시도하세요.",
        )
    try:
        answer.stt_text = transcribe_audio(str(audio_path))
        session.add(answer)
        session.commit()
        session.refresh(answer)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"STT 변환 실패: {exc}") from exc

    # 5. 상세 STT 안정성 분석 — 보조 경로이므로 실패해도 답변 제출 자체는 성공 처리
    if analysis_consent:
        try:
            detail = transcribe_audio_detailed(str(audio_path))
            features = analyze_stt_stability(detail)
            event_count = _replace_stt_timeline_events(session, answer.answer_id, features)
            stt_stability = _build_stt_stability_payload(features)
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

    # 6. (가능하면) AI 답변 분석까지 이어서 수행
    analysis_id = None
    analysis_note = None
    if not analysis_consent:
        analysis_note = "AI 분석 동의(ANALYSIS)가 없어 분석은 건너뜁니다. STT까지의 결과는 정상 저장됨."
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
            analysis_note = f"분석은 실패했지만 답변/STT는 정상 저장됨: {exc}"
    else:
        analysis_note = "AI 서비스 미준비 상태 — 나중에 /ai/user-answers/{answer_id}/analyze를 직접 호출하세요."

    return {
        "answer_id": answer.answer_id,
        "stt_text": answer.stt_text,
        "analysis_id": analysis_id,
        "note": analysis_note,
        "stt_stability": stt_stability,
    }


# ------------------------------------------------------------------
# 저장된 답변 영상/음성 재생
# ------------------------------------------------------------------
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
