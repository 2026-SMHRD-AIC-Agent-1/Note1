"""
stt_service.py
---------------
음성 파일 -> 텍스트 변환(STT)을 담당하는 얇은 래퍼입니다.
GPT 검토에서 "STT 변환 자체가 코드에 없음"으로 지적된 부분을 채웠습니다.

ai_service_client.py와 같은 방식으로 동작합니다:
  - OPENAI_API_KEY가 없어도 서버 전체는 죽지 않고, STT 관련 엔드포인트만
    503을 반환합니다.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger("stt_service")

ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga"}
MAX_AUDIO_MB = 50

_client = None
_init_error: str | None = None


def init_stt_service() -> None:
    """FastAPI lifespan에서 앱 시작 시 1회 호출."""
    global _client, _init_error
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _init_error = "OPENAI_API_KEY가 설정되지 않았습니다."
        logger.warning(_init_error + " (STT 엔드포인트만 비활성화됩니다.)")
        return

    try:
        from openai import OpenAI  # 지연 import (openai 미설치 환경 보호)
        _client = OpenAI(api_key=api_key)
        logger.info("STT 서비스(OpenAI) 초기화 완료")
    except Exception as exc:  # noqa: BLE001
        _init_error = f"STT 서비스 초기화 실패: {exc}"
        logger.warning(_init_error)


def is_ready() -> bool:
    return _client is not None


def validate_audio_file(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(
            f"허용되지 않은 음성 파일 형식: {path.suffix} "
            f"(허용: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))})"
        )
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_AUDIO_MB:
        raise ValueError(f"음성 파일이 너무 큽니다: {size_mb:.1f}MB (최대 {MAX_AUDIO_MB}MB)")


def transcribe_audio(audio_path: str, language: str = "ko") -> str:
    """저장된 음성 파일을 텍스트로 변환합니다. STT 서비스가 준비 안 됐으면 예외를 던집니다."""
    if _client is None:
        raise RuntimeError(_init_error or "STT 서비스가 아직 초기화되지 않았습니다.")

    path = Path(audio_path)
    validate_audio_file(path)

    with path.open("rb") as f:
        result = _client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=f,
            language=language,
        )
    return result.text.strip()
