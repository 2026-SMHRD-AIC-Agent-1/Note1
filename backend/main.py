"""
FastAPI 진입점
--------------
API 로직은 routers/ 폴더에 테이블별로 나뉘어 있고, 이 파일은 그것들을
불러와서 하나의 앱으로 합치는 역할만 합니다.

실행:
    pip install -r requirements.txt
    uvicorn main:app --reload
그 다음 브라우저에서 http://127.0.0.1:8000/docs 접속하면
자동 생성된 API 문서(Swagger UI)에서 바로 테스트할 수 있습니다.

Frontend 연동:
    .env(.env.example 참고)의 CORS_ORIGINS에 Frontend 개발 서버 주소를
    넣어주면 브라우저에서 fetch/axios로 이 API를 호출할 수 있습니다.
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from database import init_db, engine
from ai_service_client import init_ai_service, is_ready
from stt_service import init_stt_service, is_ready as stt_is_ready
from tts_service import init_tts_service, is_ready as tts_is_ready, init_error as tts_init_error
from nonverbal_service import is_ready as nonverbal_is_ready, init_error as nonverbal_init_error
from routers import (
    users, companies, jobs, rag_documents,
    interview_sessions, interview_questions, user_answers,
    nonverbal_metrics, nonverbal_events, session_technical_events,
    session_comparisons, answer_analyses, final_coachings,
    ai_pipeline, uploads, consents, calibration, tts,
)

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_ai_service()
    init_stt_service()
    init_tts_service()

    try:
        with Session(engine) as session:
            result = rag_documents.sync_rag_documents_from_files(session)
            logger.info(f"RAG_DOCUMENTS 동기화 완료: {len(result.synced)}건 처리")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"RAG_DOCUMENTS 동기화 실패(무시하고 계속 진행): {exc}")

    yield


app = FastAPI(title="AI 모의면접 코칭 Agent API", lifespan=lifespan)

cors_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(companies.router)
app.include_router(jobs.router)
app.include_router(rag_documents.router)
app.include_router(interview_sessions.router)
app.include_router(interview_questions.router)
app.include_router(user_answers.router)
app.include_router(nonverbal_metrics.router)
app.include_router(nonverbal_events.router)
app.include_router(session_technical_events.router)
app.include_router(session_comparisons.router)
app.include_router(answer_analyses.router)
app.include_router(final_coachings.router)
app.include_router(ai_pipeline.router)
app.include_router(uploads.router)
app.include_router(consents.router)
app.include_router(calibration.router)
app.include_router(tts.router)


@app.get("/health")
def health_check():
    """로컬 데모에서 세 핵심 AI 경로의 준비 상태를 한 번에 확인합니다."""
    nonverbal_ready = nonverbal_is_ready()
    tts_ready = tts_is_ready()
    return {
        "status": "ok",
        "ai_service_ready": is_ready(),
        "stt_service_ready": stt_is_ready(),
        "tts_service_ready": tts_ready,
        "tts_service_error": None if tts_ready else tts_init_error(),
        "nonverbal_service_ready": nonverbal_ready,
        "nonverbal_service_error": None if nonverbal_ready else nonverbal_init_error(),
    }
