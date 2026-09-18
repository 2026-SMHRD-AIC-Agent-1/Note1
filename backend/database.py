"""
DB 연결 설정
------------
.env 파일에서 설정값을 읽어옵니다 (없으면 기본값 사용).
SQLite 파일(app.db) 하나로 동작하므로 별도 DB 서버 설치가 필요 없습니다.
나중에 PostgreSQL 등으로 옮길 때는 .env의 DATABASE_URL 한 줄만 바꾸면 됩니다.
"""

import os
from dotenv import load_dotenv
from sqlmodel import SQLModel, create_engine, Session

# .env 파일이 있으면 읽어서 환경변수로 등록합니다 (없어도 에러 나지 않음)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# SQLite는 멀티스레드 접근을 위해 이 옵션이 필요합니다
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "true").lower() == "true",  # 실행되는 SQL을 콘솔에 로그로 보여줌
    connect_args=connect_args,
)


def init_db() -> None:
    """models.py + integration_models.py에 정의된 모든 테이블을 생성합니다."""
    # SQLModel.metadata에 통합 규격 V1 신규 테이블도 등록되도록 반드시 import 합니다.
    import models  # noqa: F401
    import integration_models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    seed_showcase_companies()


# [2026-09] 시연용 "보여주기" 기업 시드 데이터.
# RAG 자료가 없어서 실제 질문 생성은 안 되고(선택하면 400 에러), 드롭다운에
# 다양한 기업·직무가 있는 것처럼 보여주기 위한 용도입니다. SK하이닉스만 실제로
# 동작합니다.
SHOWCASE_COMPANIES = {
    "삼성전자": ["영업·마케팅", "경영지원", "기술·설비"],
    "현대자동차": ["일반·연구직"],
}


def seed_showcase_companies() -> None:
    from models import Companies, Jobs
    from sqlmodel import select

    with Session(engine, expire_on_commit=False) as session:
        for company_name, job_names in SHOWCASE_COMPANIES.items():
            company = session.exec(
                select(Companies).where(Companies.company_name == company_name)
            ).first()
            if not company:
                company = Companies(company_name=company_name, description="시연용 기업(자료 미등록)")
                session.add(company)
                session.commit()
                session.refresh(company)
            for job_name in job_names:
                existing_job = session.exec(
                    select(Jobs).where(
                        Jobs.company_id == company.company_id, Jobs.job_name == job_name
                    )
                ).first()
                if not existing_job:
                    session.add(Jobs(company_id=company.company_id, job_name=job_name))
        session.commit()


def get_session():
    """FastAPI 라우터에서 Depends(get_session)으로 사용하는 DB 세션."""
    with Session(engine, expire_on_commit=False) as session:
        yield session
