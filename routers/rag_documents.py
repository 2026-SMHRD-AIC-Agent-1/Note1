"""
RAG_DOCUMENTS 관련 API
----------------------
[2026-09 추가] "RAG -> DB 연결이 안 되어 있다"는 지적 반영.

기존 문제: interview_ai_service_v0_1.py는 rag_data/ 폴더 파일을 직접 읽어
자체 FAISS 인덱스만 만들고, 그 내용을 RAG_DOCUMENTS 테이블에는 전혀 기록하지
않았습니다. 그래서 REQ-003("기업·직무별 공식자료를 저장하고...")의 "저장" 부분이
실제로는 DB가 아니라 파일 시스템 + 메모리에서만 이뤄지고 있었습니다.

해결: POST /rag-documents/sync-from-files 가 rag_data/ 폴더를 스캔해서,
interview_ai_service_v0_1.py와 동일한 SOURCE_RULES 기준으로 각 파일을
RAG_DOCUMENTS 테이블에 저장(이미 있으면 갱신)합니다. AI 검색 자체는 여전히
파일 기반 FAISS가 담당하지만(속도상 이유), 이제 "어떤 자료가 실제로 검색에
쓰이고 있는지"를 DB에서 조회/추적할 수 있습니다.
"""

import os
import unicodedata
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from models import RagDocuments, Companies, Jobs

router = APIRouter(prefix="/rag-documents", tags=["RagDocuments"])


@router.post("", response_model=RagDocuments)
def create_rag_document(doc: RagDocuments, session: Session = Depends(get_session)):
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


@router.get("", response_model=List[RagDocuments])
def list_rag_documents(session: Session = Depends(get_session)):
    return session.exec(select(RagDocuments)).all()


def _get_or_create_company(session: Session, name: str) -> Companies:
    existing = session.exec(select(Companies).where(Companies.company_name == name)).first()
    if existing:
        return existing
    company = Companies(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company


def _get_or_create_job(session: Session, company_id: int, name: str) -> Jobs:
    existing = session.exec(
        select(Jobs).where(Jobs.company_id == company_id, Jobs.job_name == name)
    ).first()
    if existing:
        return existing
    job = Jobs(company_id=company_id, job_name=name)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


class SyncedDocument(BaseModel):
    filename: str
    action: str  # "created" | "updated" | "skipped"
    document_id: Optional[int] = None
    reason: Optional[str] = None


class SyncResult(BaseModel):
    data_dir: str
    company: str
    job: str
    synced: List[SyncedDocument]


@router.post("/sync-from-files", response_model=SyncResult)
def sync_rag_documents_from_files_endpoint(session: Session = Depends(get_session)):
    """
    RAG_DATA_DIR(기본 ./rag_data) 폴더를 스캔해서 RAG_DOCUMENTS 테이블에 반영합니다.
    같은 제목(title)의 문서가 이미 있으면 내용만 갱신하고, 없으면 새로 만듭니다.
    여러 번 실행해도 안전합니다(중복 생성되지 않음). 서버 시작 시 main.py에서도
    자동으로 한 번 호출되므로, 수동 호출은 파일을 나중에 추가/교체했을 때만 필요합니다.
    """
    return sync_rag_documents_from_files(session)


def sync_rag_documents_from_files(session: Session) -> SyncResult:
    try:
        from interview_ai_service_v0_1 import SOURCE_RULES
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"interview_ai_service_v0_1 로드 실패: {exc}")

    data_dir = Path(os.getenv("RAG_DATA_DIR", "./rag_data"))
    if not data_dir.exists():
        raise HTTPException(status_code=404, detail=f"RAG_DATA_DIR을 찾을 수 없습니다: {data_dir}")

    default_company = os.getenv("RAG_DEFAULT_COMPANY", "SK하이닉스")
    default_job = os.getenv("RAG_DEFAULT_JOB", "System Architecture / Software Solution")
    company = _get_or_create_company(session, default_company)
    job = _get_or_create_job(session, company.company_id, default_job)

    results: List[SyncedDocument] = []

    for path in sorted(data_dir.iterdir()):
        if not path.is_file():
            continue
        filename = unicodedata.normalize("NFC", path.name)
        suffix = path.suffix.lower()

        rule = next((r for prefix, r in SOURCE_RULES.items() if filename.startswith(prefix)), None)
        if rule is None and suffix != ".pdf":
            continue  # AI 서비스가 아예 안 읽는 파일과 동일한 기준으로 건너뜀

        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                content = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
            except Exception as exc:  # noqa: BLE001
                results.append(SyncedDocument(filename=filename, action="skipped", reason=f"PDF 읽기 실패: {exc}"))
                continue
            if not content:
                results.append(SyncedDocument(filename=filename, action="skipped", reason="추출된 텍스트 없음(이미지 기반 PDF)"))
                continue
            source_type = "official_job_description"
        else:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                results.append(SyncedDocument(filename=filename, action="skipped", reason="파일 내용 없음"))
                continue
            source_type = rule["source_type"]

        title = path.stem

        existing = session.exec(select(RagDocuments).where(RagDocuments.title == title)).first()
        if existing:
            existing.content = content
            existing.source_type = source_type
            existing.company_id = company.company_id
            existing.job_id = job.job_id
            session.add(existing)
            session.commit()
            results.append(SyncedDocument(filename=filename, action="updated", document_id=existing.document_id))
        else:
            doc = RagDocuments(
                company_id=company.company_id,
                job_id=job.job_id,
                title=title,
                source_type=source_type,
                source_url=None,
                content=content,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)
            results.append(SyncedDocument(filename=filename, action="created", document_id=doc.document_id))

    return SyncResult(
        data_dir=str(data_dir),
        company=default_company,
        job=default_job,
        synced=results,
    )
