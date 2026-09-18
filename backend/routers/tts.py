"""
routers/tts.py — 면접 질문 음성 낭독 (OpenAI TTS)
--------------------------------------------------
프론트(InterviewPage.jsx)의 "질문 다시 듣기" 버튼이 브라우저 내장 TTS
(Web Speech API) 대신 이 엔드포인트를 호출해서, 더 자연스러운 신경망 음성으로
질문을 들을 수 있게 한다.

- POST /tts/speak : {"text": "..."} -> audio/mpeg 바이트 스트림
- 서비스가 준비 안 됐으면(OPENAI_API_KEY 없음 등) 503을 반환하고,
  프론트는 이 경우 기존 브라우저 TTS로 자동 폴백한다.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from tts_service import synthesize_speech, is_ready, init_error

router = APIRouter(prefix="/tts", tags=["TTS (질문 음성 낭독)"])


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4096)
    voice: str | None = None


@router.post("/speak")
def speak(payload: SpeakRequest):
    if not is_ready():
        raise HTTPException(
            status_code=503,
            detail=init_error() or "TTS 서비스가 초기화되지 않았습니다. OPENAI_API_KEY 설정을 확인하세요.",
        )

    try:
        audio_bytes = synthesize_speech(payload.text, voice=payload.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"TTS 생성 중 오류: {exc}") from exc

    return Response(content=audio_bytes, media_type="audio/mpeg")
