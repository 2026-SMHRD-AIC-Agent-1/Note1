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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from database import init_db, engine
from ai_service_client import init_ai_service, is_ready
from stt_service import init_stt_service, is_ready as stt_is_ready
from routers import (
    users, companies, jobs, rag_documents,
    interview_sessions, interview_questions, user_answers,
    nonverbal_metrics, nonverbal_events, session_technical_events,
    session_comparisons, answer_analyses, final_coachings,
    ai_pipeline, uploads, consents,
)

load_dotenv()
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 앱 시작 시 테이블이 없으면 자동 생성
    init_ai_service()  # RAG·언어 AI 서비스 1회 초기화 (실패해도 서버는 계속 뜸, /ai/* 만 비활성화)
    init_stt_service()  # STT 서비스 1회 초기화 (실패해도 서버는 계속 뜸, STT 관련 엔드포인트만 비활성화)

    # RAG_DATA_DIR의 파일들을 RAG_DOCUMENTS 테이블에 동기화 (RAG -> DB 연결).
    # 실패해도(폴더 없음 등) 서버 자체는 정상적으로 뜨게 예외를 잡아둡니다.
    try:
        with Session(engine) as session:
            result = rag_documents.sync_rag_documents_from_files(session)
            logger.info(f"RAG_DOCUMENTS 동기화 완료: {len(result.synced)}건 처리")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"RAG_DOCUMENTS 동기화 실패(무시하고 계속 진행): {exc}")

    yield


app = FastAPI(title="AI 모의면접 코칭 Agent API", lifespan=lifespan)

# ------------------------------------------------------------------
# CORS: .env의 CORS_ORIGINS 값을 읽어서 Frontend 호출을 허용합니다.
# ------------------------------------------------------------------
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------
# 테이블별 라우터 연결 (10개 확정 테이블)
# ------------------------------------------------------------------
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


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인용 (Docker에서도 활용)"""
    return {"status": "ok", "ai_service_ready": is_ready(), "stt_service_ready": stt_is_ready()}
