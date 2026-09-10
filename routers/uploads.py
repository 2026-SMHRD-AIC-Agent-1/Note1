"""
routers/uploads.py — 답변 녹화 파일 업로드 → STT → (가능하면) 분석까지 한 번에
------------------------------------------------------------------------------
GPT 검토에서 지적된 두 가지를 함께 해결합니다.
  - "사용자 답변 녹화: 저장 구조만 있음"       -> 실제 업로드 API
  - "STT 변환: 이 코드에 없음"                  -> stt_service.py 연결

프론트 담당은 녹화 시작/종료 + MediaRecorder Blob 생성 + FormData 전송만
담당하면 되고, 그 뒤 처리(저장 -> STT -> 분석)는 이 엔드포인트가 합니다.
"""

import os
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from database import get_session
from models import InterviewQuestions, UserAnswers, AnswerAnalyses, Users
from stt_service import transcribe_audio, is_ready as stt_is_ready
from ai_service_client import get_ai_service, is_ready as ai_is_ready

router = APIRouter(tags=["Uploads"])

UPLOAD_ROOT = Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
AUDIO_DIR = UPLOAD_ROOT / "audio"
VIDEO_DIR = UPLOAD_ROOT / "video"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_VIDEO_EXTENSIONS = {".webm", ".mp4", ".mov", ".mkv"}
MAX_VIDEO_MB = 300

# 브라우저가 보내는 Content-Type도 함께 확인합니다 (확장자만으로는 위조가 쉬움).
ALLOWED_AUDIO_CONTENT_TYPES = {"audio/webm", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav", "audio/ogg"}
ALLOWED_VIDEO_CONTENT_TYPES = {"video/webm", "video/mp4", "video/quicktime", "video/x-matroska"}


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
    """
    저장된 경로가 UPLOAD_ROOT(uploads/) 밖을 가리키지 않는지 확인합니다.
    (GPT 검토본의 아이디어 병합 — DB에 잘못된/조작된 경로가 들어있어도
    업로드 폴더 밖의 임의 파일이 노출되지 않도록 방지)
    """
    path = Path(raw_path).resolve()
    if UPLOAD_ROOT not in path.parents and path != UPLOAD_ROOT:
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    return path


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
    답변 녹화 파일을 업로드받아: 저장 -> STT -> USER_ANSWERS 저장 -> (가능하면) AI 분석까지 수행합니다.

    - session_id/question_id/user_id: 어느 세션·질문·사용자의 답변인지 (권한 확인용)
    - audio: 필수. 음성 파일 (webm/wav/mp3/m4a/mp4/mpeg/mpga, 50MB 이하)
    - video: 선택. 영상 파일 (webm/mp4/mov/mkv, 300MB 이하) — 없으면 음성만 저장
    - duration_sec: 선택. 답변 소요 시간(초)

    반환: 저장된 answer_id, stt_text, (분석 성공 시) analysis_id
    """
    # 1. 권한/존재 확인 — 다른 사용자의 질문에 답변을 끼워넣지 못하게 방지
    question = session.get(InterviewQuestions, question_id)
    if not question or question.session_id != session_id:
        raise HTTPException(status_code=400, detail="해당 세션의 질문이 아닙니다.")
    if not session.get(Users, user_id):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")

    # 1-1. 개인정보 동의 실시간 확인 — 동의 없이 업로드가 들어오면 그 자리에서 막습니다.
    # (사후에 로그만 남기는 게 아니라, 저장 자체를 막는 것이 실제 개인정보 보호 취지에 맞음)
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

    try:
        # 2. 파일 저장
        if audio.content_type and audio.content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise ValueError(f"허용되지 않은 음성 Content-Type: {audio.content_type}")
        audio_bytes = await audio.read()
        audio_suffix = Path(audio.filename or "answer.webm").suffix or ".webm"
        audio_path = AUDIO_DIR / f"{uuid4().hex}{audio_suffix.lower()}"
        audio_path.write_bytes(audio_bytes)

        from stt_service import validate_audio_file
        validate_audio_file(audio_path)

        video_path_str = None
        if video is not None:
            video_bytes = await video.read()
            video_suffix = Path(video.filename or "answer.webm").suffix or ".webm"
            video_path_obj = VIDEO_DIR / f"{uuid4().hex}{video_suffix.lower()}"
            video_path_obj.write_bytes(video_bytes)
            _validate_video_file(video_path_obj, content_type=video.content_type)
            video_path_str = str(video_path_obj)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 3. USER_ANSWERS 생성 또는 (다시 제출한 경우) 갱신
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

    # 4. STT (필수 — 실패하면 답변 저장은 되어있지만 에러로 알림)
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

    # 5. (가능하면) AI 답변 분석까지 이어서 수행 — AI 서비스 미준비 시에도 업로드/STT 결과는 유지
    analysis_id = None
    analysis_note = None
    if not has_active_consent(session, user_id, "ANALYSIS"):
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
            analysis = AnswerAnalyses(
                answer_id=answer.answer_id,
                job_evaluation=result["job_evaluation"],
                answer_evaluation=result["answer_evaluation"],
                strengths=result["strengths"],
                improvements=result["improvements"],
            )
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
    }


# ------------------------------------------------------------------
# 저장된 답변 영상/음성 재생 (GPT 검토본 아이디어 병합)
# 최종 분석 화면에서 "문제 지점 클릭 → 그 시점 영상 재생"을 만들려면
# Frontend가 video_path 문자열만 갖고는 재생할 수 없고, 실제로 파일을
# 스트리밍해주는 엔드포인트가 필요합니다.
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
