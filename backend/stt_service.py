"""
stt_service.py
---------------
음성 파일 -> 텍스트 변환(STT)을 담당하는 래퍼입니다.

- 일반 서비스 전사: transcribe_audio() -> 기존처럼 최종 텍스트만 반환
- 안정성 분석용 상세 전사: transcribe_audio_detailed() -> 단어/구간 timestamp까지 반환

OPENAI_API_KEY가 없어도 서버 전체는 죽지 않고 STT 관련 기능만 비활성화됩니다.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger("stt_service")

ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga"}
MAX_AUDIO_MB = 50

# 일반 서비스용 모델은 기존 환경변수를 존중합니다.
DEFAULT_TEXT_MODEL = "gpt-4o-transcribe"
# word/segment timestamp는 verbose_json이 필요합니다. 현재 상세 분석 기본값은 whisper-1입니다.
DEFAULT_DETAIL_MODEL = "whisper-1"

# 필러/반복/자기수정을 안정성 분석에 쓰기 위해 문장답게 정리하지 말고 발화 그대로 전사하도록 유도합니다.
VERBATIM_TRANSCRIPTION_PROMPT = (
    "면접 답변을 가능한 한 실제 발화 그대로 전사하세요. "
    "'어', '음', '그' 같은 필러, 반복, 말하다가 고친 표현을 삭제하거나 문장답게 정리하지 마세요. "
    "기술용어와 영문 약어도 들리는 대로 유지하세요."
)

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


def _get_value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _serialize_timestamp_items(items, text_field: str):
    out = []
    for item in items or []:
        out.append({
            text_field: _get_value(item, text_field, ""),
            "start": _get_value(item, "start"),
            "end": _get_value(item, "end"),
        })
    return out


def transcribe_audio(audio_path: str, language: str = "ko") -> str:
    """기존 서비스 호환용: 저장된 음성 파일을 최종 텍스트로 변환합니다."""
    if _client is None:
        raise RuntimeError(_init_error or "STT 서비스가 아직 초기화되지 않았습니다.")

    path = Path(audio_path)
    validate_audio_file(path)
    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", DEFAULT_TEXT_MODEL)

    with path.open("rb") as f:
        result = _client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language,
            prompt=VERBATIM_TRANSCRIPTION_PROMPT,
        )
    return result.text.strip()


def transcribe_audio_detailed(audio_path: str, language: str = "ko") -> dict:
    """안정성 분석용 상세 STT.

    반환값:
    {
      text, model, duration_sec,
      words: [{word, start, end}, ...],
      segments: [{text, start, end}, ...],
      word_timestamps_available
    }

    word/segment timestamp를 받으려면 response_format=verbose_json이 필요합니다.
    현재 상세 분석 기본 모델은 whisper-1이며, OPENAI_TRANSCRIBE_DETAIL_MODEL로 변경할 수 있습니다.
    """
    if _client is None:
        raise RuntimeError(_init_error or "STT 서비스가 아직 초기화되지 않았습니다.")

    path = Path(audio_path)
    validate_audio_file(path)
    model = os.getenv("OPENAI_TRANSCRIBE_DETAIL_MODEL", DEFAULT_DETAIL_MODEL)
    if model != "whisper-1":
        raise ValueError(
            f"현재 상세 word/segment timestamp 경로는 whisper-1을 사용해야 합니다. "
            f"현재 설정: {model}. OPENAI_TRANSCRIBE_DETAIL_MODEL=whisper-1 로 설정하세요."
        )

    with path.open("rb") as f:
        result = _client.audio.transcriptions.create(
            model=model,
            file=f,
            language=language,
            prompt=VERBATIM_TRANSCRIPTION_PROMPT,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )

    words = _serialize_timestamp_items(_get_value(result, "words", []), "word")
    segments = _serialize_timestamp_items(_get_value(result, "segments", []), "text")
    text = (_get_value(result, "text", "") or "").strip()
    duration_sec = _get_value(result, "duration", None)

    return {
        "text": text,
        "model": model,
        "duration_sec": duration_sec,
        "words": words,
        "segments": segments,
        "word_timestamps_available": bool(words),
    }
