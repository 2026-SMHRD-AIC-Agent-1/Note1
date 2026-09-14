"""실제 FastAPI가 사용하는 단일 AI/RAG 서비스 진입점."""

import os
import logging
from pathlib import Path

from path_config import resolve_project_path

logger = logging.getLogger("ai_service_client")
_service = None
_init_error: str | None = None


def _resolve_rag_base_path() -> str:
    configured = resolve_project_path(os.getenv("RAG_DATA_DIR"), "rag_data")
    candidates = [configured, configured / "rag_data"]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.iterdir()):
            return str(candidate)
    return str(configured)


def init_ai_service() -> None:
    """앱 시작 시 RAG+언어 AI 서비스를 1회 초기화한다."""
    global _service, _init_error
    try:
        from rag_ai.rag_ai_service import RagInterviewAI

        _service = RagInterviewAI(
            base_path=_resolve_rag_base_path(),
            company=os.getenv("RAG_DEFAULT_COMPANY", "SK하이닉스"),
            job=os.getenv("RAG_DEFAULT_JOB", "System Architecture / Software Solution"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        )
        _service.load_and_index()
        logger.info("RagInterviewAI 초기화 및 RAG 인덱싱 완료")
    except Exception as exc:  # noqa: BLE001
        _service = None
        _init_error = f"AI 서비스 초기화 실패: {exc}"
        logger.warning(_init_error)


def get_ai_service():
    if _service is None:
        raise RuntimeError(_init_error or "AI 서비스가 아직 초기화되지 않았습니다.")
    return _service


def is_ready() -> bool:
    return _service is not None
