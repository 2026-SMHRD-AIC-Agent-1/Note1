"""
ai_service_client.py
---------------------
재명씨(RAG·언어 AI)의 interview_ai_service_v0_1.py를 감싸는 얇은 래퍼입니다.

[결정 2026-09] AI연동규격 v0.1 "11. 교민 전달 시 확인할 것" 항목 6 반영.
규격 문서는 "FastAPI startup/lifespan 등에서 1회 초기화"를 권장합니다
(SentenceTransformer·FAISS 인덱스를 요청마다 다시 만들면 매우 느려지기 때문).

다만 아직 팀원 전원이 OPENAI_API_KEY·RAG_DATA_DIR을 세팅한 상태가 아닐 수 있으므로,
초기화 실패가 서버 전체를 죽이지 않도록 예외를 감싸서 처리합니다.
→ AI 관련 엔드포인트만 503으로 응답하고, 나머지 DB API(Users/Companies 등)는
  평소처럼 정상 동작합니다.
"""

import os
import logging

logger = logging.getLogger("ai_service_client")

_service = None
_init_error: str | None = None


def init_ai_service() -> None:
    """FastAPI lifespan에서 앱 시작 시 1회 호출.

    interview_ai_service_v0_1.py의 import 자체를 이 함수 안에서 시도합니다.
    (faiss·sentence-transformers·langchain-openai 등이 설치되지 않은 팀원 컴퓨터에서는
    이 import부터 실패할 수 있으므로, 여기서 잡아야 나머지 DB API가 죽지 않습니다.)
    """
    global _service, _init_error
    try:
        from interview_ai_service_v0_1 import InterviewAIService  # 지연 import
    except Exception as exc:  # noqa: BLE001 - 패키지 미설치 등 어떤 이유든 서버 전체를 죽이지 않음
        _init_error = f"AI 서비스 모듈 import 실패: {exc}"
        logger.warning(_init_error + " (requirements.txt의 RAG·언어 AI 패키지가 설치됐는지 확인하세요.)")
        return

    try:
        _service = InterviewAIService(
            data_dir=os.getenv("RAG_DATA_DIR", "./rag_data"),
            company=os.getenv("RAG_DEFAULT_COMPANY", "SK하이닉스"),
            job=os.getenv("RAG_DEFAULT_JOB", "System Architecture / Software Solution"),
        )
        logger.info("InterviewAIService 초기화 완료")
    except Exception as exc:  # noqa: BLE001 - 초기화 실패 사유를 그대로 보존해 전달
        _init_error = f"AI 서비스 초기화 실패: {exc}"
        logger.warning(_init_error + " (RAG_DATA_DIR·OPENAI_API_KEY 설정을 확인하세요. /ai/* 엔드포인트만 비활성화됩니다.)")


def get_ai_service():
    """라우터에서 Depends로 사용. 초기화 안 됐으면 에러를 그대로 올림 (라우터에서 503으로 변환)."""
    if _service is None:
        raise RuntimeError(_init_error or "AI 서비스가 아직 초기화되지 않았습니다.")
    return _service


def is_ready() -> bool:
    return _service is not None
