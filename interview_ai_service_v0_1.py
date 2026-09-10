"""AI 모의면접 RAG/언어AI 서비스 모듈 v0.1

역할
- 기업/직무/면접유형 기반 RAG 질문 생성
- STT 답변 내용 분석
- 세션 단위 종합 코칭
- 이전 코칭을 반영한 후속 질문 생성
- Backend 저장용 payload 구성

주의
- Supervisor/LangGraph는 MVP에서 사용하지 않는다.
- voice_emotion_label은 저장만 가능하며 코칭 판단 근거로 사용하지 않는다.
- 합격/불합격, 성격, 자신감, 감정 추론을 하지 않는다.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import faiss
import numpy as np
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

load_dotenv()


DEFAULT_COMPANY = "SK하이닉스"
DEFAULT_JOB = "System Architecture / Software Solution"
DEFAULT_INTERVIEW_TYPE = "직무면접"
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

NONVERBAL_FIELDS = [
    "face_yaw",
    "gaze_center_ratio",
    "blink_rate",
    "smile_intensity",
    "expression_change_count",
    "upper_body_sway",
    "head_nod_count",
    "hand_gesture_rate",
    "pause_count",
    "average_volume",
    "speaking_speed",
    "pitch_variation",
    "filler_word_count",
    "voice_emotion_label",
]

# MVP 코칭에서 직접 사용하는 측정값.
# 나머지 값은 DB 저장은 가능하지만 의미/기준 확정 전까지 코칭 판단에 사용하지 않는다.
COACHING_NONVERBAL_FIELDS = [
    "face_yaw",
    "gaze_center_ratio",
    "upper_body_sway",
    "pause_count",
    "average_volume",
    "speaking_speed",
    "pitch_variation",
    "filler_word_count",
]

ANSWER_STRUCTURE_CRITERIA = """
- 질문에 직접 답하고 있는가
- 결론과 이유가 논리적으로 연결되는가
- 구체적인 설명이나 경험이 포함되어 있는가
- 불필요한 반복이나 모순이 적은가
""".strip()

SOURCE_RULES = {
    "02_": {"category": "job", "source_type": "official_job_report"},
    "03_": {"category": "interview", "source_type": "interview_summary"},
    "04_": {"category": "interview_process", "source_type": "official_process"},
    "05_": {"category": "recruiting_direction", "source_type": "official_story"},
    "06_": {"category": "job", "source_type": "official_job_posting"},
    "07_": {"category": "company_values", "source_type": "official_home"},
    # [교민 병합 2026-09] 재명씨 v0.3에서 08_ 추가 시 06_ 항목이 실수로 누락되어 있었음
    # (06_공식공고_SolutionSW_상세업무.txt가 조용히 검색 제외되는 회귀 버그).
    # 06_은 복원하고 08_만 새로 추가하는 형태로 병합함.
    "08_": {"category": "job_description", "source_type": "official_jd_extract"},
}


class QuestionDraft(BaseModel):
    question_type: Literal["직무이해", "문제해결", "협업"]
    question_text: str
    question_reason: str
    evaluation_points: List[str] = Field(description="공개자료 기반 평가 포인트 3개")
    source_numbers: List[int] = Field(description="사용한 RAG SOURCE 번호")


class QuestionSet(BaseModel):
    questions: List[QuestionDraft] = Field(description="직무이해/문제해결/협업 총 3개")


class AnswerAnalysisResult(BaseModel):
    job_evaluation: Literal["잘 드러남", "일부 드러남", "보완 필요"]
    answer_evaluation: Literal["잘 드러남", "일부 드러남", "보완 필요"]
    strengths: str
    improvements: str


class SessionCoachingResult(BaseModel):
    content_summary: str
    delivery_summary: str
    priority_focus: str
    next_practice_goal: str


class FollowUpQuestion(BaseModel):
    question_type: Literal["직무이해", "문제해결", "협업"]
    question_text: str
    question_reason: str
    evaluation_points: List[str]
    source_numbers: List[int]
    practice_reason: str


def normalize_nonverbal_metrics(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """비언어 결과를 14개 공통 필드로 정규화한다. 없는 값은 None."""
    data = data or {}
    return {field: data.get(field) for field in NONVERBAL_FIELDS}


def _safe_value(data: Dict[str, Any], key: str) -> Any:
    value = data.get(key)
    return "측정값 없음" if value is None else value


def _clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def _source_metadata(filename: str) -> Dict[str, str]:
    normalized = unicodedata.normalize("NFC", filename)
    for prefix, rule in SOURCE_RULES.items():
        if normalized.startswith(prefix):
            return rule.copy()
    return {"category": "job", "source_type": "official_job_description"}


class InterviewAIService:
    """FastAPI에서 한 번 생성해 재사용하는 RAG/언어AI 서비스."""

    def __init__(
        self,
        data_dir: str,
        company: str = DEFAULT_COMPANY,
        job: str = DEFAULT_JOB,
        embedding_model_name: str = DEFAULT_EMBEDDING_MODEL,
        openai_model: str = DEFAULT_OPENAI_MODEL,
        chunk_size: int = 500,
        chunk_overlap: int = 100,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.company = company
        self.job = job
        self.embedding_model_name = embedding_model_name
        self.openai_model = openai_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        if not self.data_dir.exists():
            raise FileNotFoundError(f"RAG_DATA_DIR을 찾을 수 없습니다: {self.data_dir}")

        self.documents = self._load_documents()
        if not self.documents:
            raise ValueError("RAG 문서를 한 건도 불러오지 못했습니다.")

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )
        self.chunks = splitter.split_documents(self.documents)
        if not self.chunks:
            raise ValueError("Chunking 결과가 없습니다.")

        self.embedding_model = SentenceTransformer(self.embedding_model_name)
        embeddings = self.embedding_model.encode(
            [doc.page_content for doc in self.chunks],
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")
        faiss.normalize_L2(embeddings)

        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings)

        # OPENAI_API_KEY는 환경변수로 받는다.
        self.llm = ChatOpenAI(model=self.openai_model)
        self.question_llm = self.llm.with_structured_output(QuestionDraft)
        self.question_set_llm = self.llm.with_structured_output(QuestionSet)
        self.answer_analysis_llm = self.llm.with_structured_output(AnswerAnalysisResult)
        self.session_coaching_llm = self.llm.with_structured_output(SessionCoachingResult)
        self.followup_llm = self.llm.with_structured_output(FollowUpQuestion)

    def _load_documents(self) -> List[Document]:
        documents: List[Document] = []

        for path in sorted(self.data_dir.iterdir()):
            if not path.is_file():
                continue

            filename = unicodedata.normalize("NFC", path.name)
            suffix = path.suffix.lower()
            allowed_text = any(filename.startswith(prefix) for prefix in SOURCE_RULES)
            allowed_pdf = suffix == ".pdf"

            # 00/01 등 실습용 파일은 RAG 원문에서 제외한다.
            if not (allowed_text or allowed_pdf):
                continue

            rule = _source_metadata(filename)
            base_meta = {
                "company": self.company,
                "job": self.job,
                "category": rule["category"],
                "source_type": rule["source_type"],
                "source_title": Path(filename).stem,
                "source_url": None,
            }

            if suffix == ".pdf":
                reader = PdfReader(str(path))
                for page_no, page in enumerate(reader.pages, start=1):
                    content = _clean_text(page.extract_text() or "")
                    if not content:
                        continue
                    meta = {**base_meta, "page": page_no}
                    documents.append(Document(page_content=content, metadata=meta))
            else:
                content = _clean_text(_read_text_file(path))
                if content:
                    meta = {**base_meta, "page": None}
                    documents.append(Document(page_content=content, metadata=meta))

        return documents

    def search_rag(self, query: str, k: int = 3) -> List[Dict[str, Any]]:
        query_embedding = self.embedding_model.encode(
            [query], convert_to_numpy=True, show_progress_bar=False
        ).astype("float32")
        faiss.normalize_L2(query_embedding)

        scores, indices = self.index.search(query_embedding, min(k, len(self.chunks)))
        results: List[Dict[str, Any]] = []

        for rank, (idx, score) in enumerate(zip(indices[0], scores[0]), start=1):
            if idx < 0:
                continue
            chunk = self.chunks[int(idx)]
            results.append(
                {
                    "rank": rank,
                    "score": float(score),
                    "content": chunk.page_content,
                    "metadata": chunk.metadata,
                }
            )
        return results

    def _retrieve_question_sources(
        self,
        company: str,
        job: str,
        interview_type: str,
        k: int = 4,
        extra_context: str = "",
    ) -> List[Dict[str, Any]]:
        query = (
            f"{company} {job} {interview_type} 직무 이해 문제 해결 협업 역량 "
            f"면접 질문 평가 포인트 공식 근거자료 {extra_context}"
        )
        results = self.search_rag(query, k=k)
        sources: List[Dict[str, Any]] = []

        for i, result in enumerate(results, start=1):
            meta = result["metadata"]
            sources.append(
                {
                    "source_no": i,
                    "content": result["content"],
                    "source_title": meta.get("source_title"),
                    "category": meta.get("category"),
                    "source_type": meta.get("source_type"),
                    "page": meta.get("page"),
                    "similarity": round(float(result["score"]), 4),
                }
            )
        return sources

    @staticmethod
    def _map_evidence(source_numbers: List[int], sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        evidence: List[Dict[str, Any]] = []
        seen = set()
        for source_no in source_numbers:
            if source_no in seen:
                continue
            seen.add(source_no)
            if 1 <= source_no <= len(sources):
                source = sources[source_no - 1]
                evidence.append(
                    {
                        "source_title": source["source_title"],
                        "category": source["category"],
                        "page": source["page"],
                        "similarity": source["similarity"],
                    }
                )
        return evidence

    def generate_three_questions(
        self,
        company: str,
        job: str,
        interview_type: str,
    ) -> List[Dict[str, Any]]:
        sources = self._retrieve_question_sources(company, job, interview_type, k=4)
        context = "\n".join(
            f"SOURCE {s['source_no']}\n자료유형: {s['category']}\n내용: {s['content']}"
            for s in sources
        )

        prompt = f"""
너는 기업·직무 면접 연습용 질문 생성 AI다.
기업: {company}
직무: {job}
면접유형: {interview_type}

아래 RAG 자료만 사용하여 정확히 3개 질문을 생성하라.
- 직무이해 1개
- 문제해결 1개
- 협업 1개

각 질문에는 question_type, question_text, question_reason,
evaluation_points 정확히 3개, source_numbers를 포함한다.

규칙:
1. 실제 기업 내부 평가기준을 추측하지 않는다.
2. 공개자료에서 확인 가능한 내용만 사용한다.
3. 질문은 실제 직무면접 연습에 사용할 수 있게 작성한다.
4. question_reason은 왜 이 질문을 연습하는지 짧게 작성한다.
5. 근거는 SOURCE 번호만 선택한다.
6. RAG 자료에 없는 사실을 추가하지 않는다.

[RAG 자료]
{context}
""".strip()

        response = self.question_set_llm.invoke(prompt)
        if len(response.questions) != 3:
            raise ValueError(f"질문 3개를 기대했지만 {len(response.questions)}개가 생성되었습니다.")

        final_questions: List[Dict[str, Any]] = []
        for draft in response.questions:
            final_questions.append(
                {
                    "question_type": draft.question_type,
                    "question_text": draft.question_text,
                    "question_reason": draft.question_reason,
                    "evaluation_points": draft.evaluation_points[:3],
                    "rag_evidence": self._map_evidence(draft.source_numbers, sources),
                }
            )
        return final_questions

    def analyze_answer(self, question_data: Dict[str, Any], stt_text: str) -> Dict[str, Any]:
        evaluation_points = "\n".join(
            f"- {point}" for point in question_data.get("evaluation_points", [])
        )

        prompt = f"""
기업·직무 면접 답변을 분석하라.

[질문]
{question_data['question_text']}

[RAG 기반 평가 포인트]
{evaluation_points}

[답변 구조 기준]
{ANSWER_STRUCTURE_CRITERIA}

[지원자 답변]
{stt_text}

규칙:
1. job_evaluation은 RAG 기반 평가 포인트만 기준으로 판단한다.
2. answer_evaluation은 답변 구조 기준만 사용한다.
3. 기업의 실제 내부 평가기준을 추측하지 않는다.
4. 합격/불합격, 점수, 성격, 자신감, 감정을 판단하지 않는다.
5. strengths는 가장 중요한 강점 1개를 한 문장으로 작성한다.
6. improvements는 가장 중요한 보완점 1개를 한 문장으로 작성한다.
7. 짧고 구체적으로 작성한다.
""".strip()

        result = self.answer_analysis_llm.invoke(prompt)
        return result.model_dump()

    def generate_session_coaching(self, session_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        summary_items: List[str] = []

        for i, item in enumerate(session_items, start=1):
            analysis = item["answer_analysis"]
            nonverbal = normalize_nonverbal_metrics(item.get("nonverbal_metrics") or item.get("nonverbal"))

            selected_metrics = "\n".join(
                f"- {field}: {_safe_value(nonverbal, field)}"
                for field in COACHING_NONVERBAL_FIELDS
            )

            summary_items.append(
                f"""
[질문 {i}]
질문유형: {item['question']['question_type']}
직무 평가: {analysis['job_evaluation']}
답변 구조 평가: {analysis['answer_evaluation']}
강점: {analysis['strengths']}
보완점: {analysis['improvements']}
비언어 측정값:
{selected_metrics}
""".strip()
            )

        session_summary = "\n\n".join(summary_items)

        prompt = f"""
모의면접 1회 전체 결과를 종합하여 다음 연습을 위한 짧은 코칭을 작성하라.

[면접 결과]
{session_summary}

규칙:
1. 세 질문 전체에서 공통적으로 나타난 특징을 우선한다.
2. 합격/불합격이나 점수를 판단하지 않는다.
3. 성격, 자신감, 긴장도, 감정을 추측하지 않는다.
4. 비언어 값은 실제 측정된 값만 근거로 설명한다.
5. 측정값만으로 좋다/나쁘다를 임의 판단하지 않는다.
6. voice_emotion_label은 코칭 근거로 사용하지 않는다.
7. content_summary는 답변 내용 전체를 1~2문장으로 요약한다.
8. delivery_summary는 관찰 가능한 전달 특징만 1~2문장으로 요약한다.
9. priority_focus는 가장 먼저 개선할 한 가지를 선택한다.
10. next_practice_goal은 다음 면접에서 실제 연습 가능한 행동으로 작성한다.
11. 측정값으로 확인할 수 없는 행동이나 상태를 추측하지 않는다.
12. 짧고 구체적으로 작성한다.
""".strip()

        result = self.session_coaching_llm.invoke(prompt)
        return result.model_dump()

    def generate_followup_question(
        self,
        previous_session: Dict[str, Any],
        company: str,
        job: str,
        interview_type: str,
    ) -> Dict[str, Any]:
        final_coaching = previous_session["final_coaching"]
        priority_focus = final_coaching["priority_focus"]
        next_practice_goal = final_coaching["next_practice_goal"]

        previous_questions: List[str] = []
        for item in previous_session.get("questions", []):
            question = item.get("question", item)
            if isinstance(question, dict) and question.get("question_text"):
                previous_questions.append(question["question_text"])

        previous_question_text = "\n".join(f"- {q}" for q in previous_questions) or "없음"
        extra_context = f"우선 개선점 {priority_focus} 다음 연습 목표 {next_practice_goal}"
        sources = self._retrieve_question_sources(
            company, job, interview_type, k=3, extra_context=extra_context
        )
        context = "\n".join(
            f"SOURCE {s['source_no']}\n내용: {s['content']}" for s in sources
        )

        prompt = f"""
너는 기업·직무 맞춤형 면접 연습 질문 생성 AI다.
기업: {company}
직무: {job}
면접유형: {interview_type}

[이전 질문들]
{previous_question_text}

[이전 우선 개선점]
{priority_focus}

[다음 연습 목표]
{next_practice_goal}

아래 RAG 자료만 사용하여 이전 약점을 다시 연습할 수 있는 후속 질문 1개를 생성하라.

규칙:
1. 이전 질문을 그대로 반복하지 않는다.
2. next_practice_goal을 실제로 연습할 수 있는 질문을 만든다.
3. question_reason은 공개자료 관점에서 왜 필요한 질문인지 작성한다.
4. practice_reason은 이전 코칭 때문에 왜 이 질문을 연습하는지 작성한다.
5. evaluation_points는 정확히 3개 작성한다.
6. 실제 기업 내부 평가기준을 추측하지 않는다.
7. 사용한 자료는 SOURCE 번호로만 선택한다.
8. 짧고 명확하게 작성한다.

[RAG 자료]
{context}
""".strip()

        draft = self.followup_llm.invoke(prompt)
        return {
            "question_type": draft.question_type,
            "question_text": draft.question_text,
            "question_reason": draft.question_reason,
            "evaluation_points": draft.evaluation_points[:3],
            "rag_evidence": self._map_evidence(draft.source_numbers, sources),
            "practice_reason": draft.practice_reason,
        }

    @staticmethod
    def build_backend_payload(
        company: str,
        job: str,
        interview_type: str,
        session_items: List[Dict[str, Any]],
        final_coaching: Dict[str, Any],
    ) -> Dict[str, Any]:
        questions: List[Dict[str, Any]] = []

        for item in session_items:
            question = item["question"]
            analysis = item["answer_analysis"]
            nonverbal = normalize_nonverbal_metrics(
                item.get("nonverbal_metrics") or item.get("nonverbal")
            )

            question_payload = {
                "question_type": question["question_type"],
                "question_text": question["question_text"],
                "question_reason": question["question_reason"],
                "evaluation_points": question.get("evaluation_points", []),
                "rag_evidence": question.get("rag_evidence", []),
            }

            questions.append(
                {
                    "question": question_payload,
                    "answer": {"stt_text": item.get("stt_text", "")},
                    "answer_analysis": {
                        "job_evaluation": analysis["job_evaluation"],
                        "answer_evaluation": analysis["answer_evaluation"],
                        "strengths": analysis["strengths"],
                        "improvements": analysis["improvements"],
                    },
                    "nonverbal_metrics": nonverbal,
                }
            )

        return {
            "session": {
                "company": company,
                "job": job,
                "interview_type": interview_type,
            },
            "questions": questions,
            "final_coaching": {
                "content_summary": final_coaching["content_summary"],
                "delivery_summary": final_coaching["delivery_summary"],
                "priority_focus": final_coaching["priority_focus"],
                "next_practice_goal": final_coaching["next_practice_goal"],
            },
        }
