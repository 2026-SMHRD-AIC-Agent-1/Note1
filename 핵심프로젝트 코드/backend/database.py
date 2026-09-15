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


def get_session():
    """FastAPI 라우터에서 Depends(get_session)으로 사용하는 DB 세션."""
    with Session(engine, expire_on_commit=False) as session:
        yield session
