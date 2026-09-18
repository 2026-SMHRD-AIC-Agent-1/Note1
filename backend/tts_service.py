"""
tts_service.py
---------------
면접 질문을 브라우저 기본 TTS(Web Speech API) 대신 OpenAI TTS API(gpt-4o-mini-tts)로
읽어주기 위한 모듈. stt_service.py/ai_service_client.py와 같은 패턴(init_*, is_ready())을
따르되, 완전히 독립적으로 동작해서 기존 STT/LLM 초기화가 실패해도 영향을 주지 않는다.

동작 방식:
    - OPENAI_API_KEY가 설정돼 있으면 OpenAI 클라이언트를 준비한다.
    - synthesize_speech()가 텍스트를 받아 mp3 바이트를 반환한다.
    - 실패(키 미설정, API 오류 등) 시 예외를 던지고, 라우터에서 503/502로 변환한다.
      프론트는 이 경우 브라우저 TTS로 자동 폴백한다(기존 기능 유지).

환경변수:
    OPENAI_API_KEY   - 필수. 없으면 is_ready()가 False.
    TTS_MODEL        - 기본값 "gpt-4o-mini-tts" (자연스러운 톤 지시(instructions) 지원)
    TTS_VOICE        - 기본값 "nova" (차분하고 또렷한 편이라 면접 질문 낭독에 적합)
    TTS_INSTRUCTIONS - 기본값: 아래 DEFAULT_INSTRUCTIONS
"""

import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger("tts_service")

_client = None
_ready = False
_init_error: Optional[str] = None

DEFAULT_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")
DEFAULT_VOICE = os.getenv("TTS_VOICE", "nova")
DEFAULT_INSTRUCTIONS = os.getenv(
    "TTS_INSTRUCTIONS",
    "면접관이 지원자에게 질문을 읽어주는 상황입니다. "
    "차분하고 또렷하게, 너무 빠르지 않은 속도로, 자연스러운 억양으로 읽어주세요. "
    "기계적으로 끊어 읽지 말고 문장의 의미 단위로 자연스럽게 띄어 읽어주세요.",
)
MAX_INPUT_CHARS = 4096  # OpenAI TTS 입력 길이 제한


def init_tts_service() -> None:
    """앱 시작 시 호출. OPENAI_API_KEY가 없으면 조용히 비활성화 상태로 남는다."""
    global _client, _ready, _init_error

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _ready = False
        _init_error = "OPENAI_API_KEY가 설정되지 않았습니다."
        logger.warning("TTS 서비스 비활성화: %s", _init_error)
        return

    try:
        from openai import OpenAI

        _client = OpenAI(api_key=api_key)
        _ready = True
        _init_error = None
        logger.info("TTS 서비스 초기화 완료 (model=%s, voice=%s)", DEFAULT_MODEL, DEFAULT_VOICE)
    except Exception as exc:  # noqa: BLE001
        _client = None
        _ready = False
        _init_error = f"TTS 서비스 초기화 실패: {exc}"
        logger.warning(_init_error)


def is_ready() -> bool:
    return _ready and _client is not None


def init_error() -> Optional[str]:
    return _init_error


def synthesize_speech(
    text: str,
    voice: Optional[str] = None,
    instructions: Optional[str] = None,
) -> bytes:
    """텍스트를 mp3 오디오 바이트로 변환한다. 준비가 안 됐거나 실패하면 예외를 던진다."""
    if not is_ready():
        raise RuntimeError(_init_error or "TTS 서비스가 준비되지 않았습니다.")

    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("빈 텍스트는 음성으로 변환할 수 없습니다.")
    if len(cleaned) > MAX_INPUT_CHARS:
        cleaned = cleaned[:MAX_INPUT_CHARS]

    # instructions(톤 지시)는 gpt-4o-mini-tts에서만 지원되고 tts-1/tts-1-hd는
    # 이 파라미터를 받지 않으므로, 모델을 바꿔 쓰는 경우를 대비해 조건부로만 넣는다.
    kwargs = dict(
        model=DEFAULT_MODEL,
        voice=voice or DEFAULT_VOICE,
        input=cleaned,
        response_format="mp3",
    )
    if DEFAULT_MODEL == "gpt-4o-mini-tts":
        kwargs["instructions"] = instructions or DEFAULT_INSTRUCTIONS

    buffer = BytesIO()
    with _client.audio.speech.with_streaming_response.create(**kwargs) as response:
        for chunk in response.iter_bytes():
            buffer.write(chunk)

    return buffer.getvalue()
