import os
import json
import copy
import hashlib
import statistics
from typing import Any, Dict, List, Literal, Optional

import faiss
import numpy as np
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import ChatOpenAI


COMPANY_DEFAULT = 'SK하이닉스'
JOB_DEFAULT = 'System Architecture / Software Solution'
INTERVIEW_TYPES = ('AISK', 'DEEP_INTERVIEW')
QUESTION_TYPES = ('직무이해', '문제해결', '협업')

SOURCE_RULES = {
    '02_': {'category': 'job', 'source_type': 'official_job_report', 'scope': 'job', 'interview_type': 'ALL'},
    '03_': {'category': 'interview', 'source_type': 'interview_summary', 'scope': 'company', 'interview_type': 'ALL'},
    '04_': {'category': 'interview_process', 'source_type': 'official_process', 'scope': 'company', 'interview_type': 'AISK'},
    '05_': {'category': 'recruiting_direction', 'source_type': 'official_story', 'scope': 'company', 'interview_type': 'ALL'},
    '06_': {'category': 'job', 'source_type': 'official_job_posting', 'scope': 'job', 'interview_type': 'ALL'},
    '07_': {'category': 'company_values', 'source_type': 'official_home', 'scope': 'company', 'interview_type': 'ALL'},
    '08_': {'category': 'job_description', 'source_type': 'official_jd_extract', 'scope': 'job', 'interview_type': 'ALL'},
}

ANSWER_STRUCTURE_CRITERIA = [
    '질문이 요구한 핵심에 대응하고 있는가',
    '결론과 이유가 논리적으로 연결되는가',
    '구체적인 설명이나 경험이 포함되어 있는가',
    '불필요한 반복이나 모순이 적은가',
]


class QuestionDraft(BaseModel):
    question_type: Literal['직무이해', '문제해결', '협업']
    question_text: str
    question_reason: str
    evaluation_points: List[str] = Field(description='공개자료 기반 평가 포인트 정확히 3개')
    source_numbers: List[int]


class QuestionSet(BaseModel):
    questions: List[QuestionDraft]


class DeepFollowUpDraft(BaseModel):
    follow_up_question: str
    follow_up_reason: str


class AnswerAnalysisDraft(BaseModel):
    job_levels: List[Literal[0, 1, 2]] = Field(min_length=3, max_length=3)
    job_reasons: List[str] = Field(min_length=3, max_length=3)
    answer_levels: List[Literal[0, 1, 2]] = Field(min_length=4, max_length=4)
    answer_reasons: List[str] = Field(min_length=4, max_length=4)
    strengths: str
    improvements: str


class SessionCoachingResult(BaseModel):
    content_summary: str
    delivery_summary: str
    priority_focus: str
    next_practice_goal: str


def _read_text_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, 'r', encoding='cp949') as f:
            return f.read()


def _score_from_levels(levels: List[int]) -> int:
    if not levels:
        return 0
    return round(sum(levels) / (len(levels) * 2) * 100)


def _qualitative_label(levels: List[int]) -> str:
    if not levels:
        return '보완 필요'
    avg = sum(levels) / len(levels)
    if avg >= 1.5:
        return '잘 드러남'
    if avg >= 0.75:
        return '일부 드러남'
    return '보완 필요'


class RagInterviewAI:
    """Backend가 import해서 사용할 재명 파트 서비스 클래스."""

    def __init__(
        self,
        base_path: Optional[str] = None,
        company: str = COMPANY_DEFAULT,
        job: str = JOB_DEFAULT,
        openai_model: Optional[str] = None,
        embedding_model: str = 'paraphrase-multilingual-MiniLM-L12-v2',
    ):
        self.base_path = base_path or os.environ.get('RAG_BASE_PATH')
        if not self.base_path:
            raise ValueError('RAG_BASE_PATH 또는 base_path가 필요합니다.')

        self.company = company
        self.job = job
        self.llm = ChatOpenAI(
            model=openai_model or os.environ.get('OPENAI_MODEL', 'gpt-5.4-mini'),
            temperature=0,
        )
        self.embedding_model = SentenceTransformer(embedding_model)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=['\n\n', '\n', '. ', ' ', ''],
        )

        self.documents: List[Document] = []
        self.chunks: List[Document] = []
        self.faiss_index = None

        # 동일한 질문 + 평가포인트 + STT 답변은 같은 분석결과를 재사용한다.
        # PoC에서는 프로세스 메모리 캐시를 사용하며, 실제 서비스에서는 DB/Redis로 확장할 수 있다.
        self._analysis_cache: Dict[str, Dict[str, Any]] = {}

        self.question_set_llm = self.llm.with_structured_output(QuestionSet)
        self.deep_followup_llm = self.llm.with_structured_output(DeepFollowUpDraft)
        self.answer_analysis_llm = self.llm.with_structured_output(AnswerAnalysisDraft)
        self.session_coaching_llm = self.llm.with_structured_output(SessionCoachingResult)

    def load_and_index(self) -> None:
        if not os.path.isdir(self.base_path):
            raise FileNotFoundError(f'RAG 자료 폴더를 찾을 수 없습니다: {self.base_path}')

        documents: List[Document] = []
        for filename in sorted(os.listdir(self.base_path)):
            full_path = os.path.join(self.base_path, filename)
            if not os.path.isfile(full_path) or filename.lower().endswith('.pdf'):
                continue

            matched_rule = None
            for prefix, rule in SOURCE_RULES.items():
                if filename.startswith(prefix):
                    matched_rule = rule
                    break
            if matched_rule is None:
                continue

            text = _read_text_file(full_path).strip()
            if not text:
                continue

            metadata = {
                'company': self.company,
                'job': self.job if matched_rule['scope'] == 'job' else 'ALL',
                'interview_type': matched_rule['interview_type'],
                'category': matched_rule['category'],
                'source_type': matched_rule['source_type'],
                'source_title': filename,
                'source_path': full_path,
                'page': None,
            }
            documents.append(Document(page_content=text, metadata=metadata))

        if not documents:
            raise ValueError('RAG 원문 문서가 없습니다.')

        self.documents = documents
        self.chunks = self.text_splitter.split_documents(documents)
        texts = [chunk.page_content for chunk in self.chunks]
        vectors = self.embedding_model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).astype('float32')

        self.faiss_index = faiss.IndexFlatIP(vectors.shape[1])
        self.faiss_index.add(vectors)

    def _ensure_index(self) -> None:
        if self.faiss_index is None or not self.chunks:
            raise RuntimeError('load_and_index()를 먼저 실행하세요.')

    def search_rag(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        self._ensure_index()
        k = min(k, len(self.chunks))
        query_vector = self.embedding_model.encode(
            [query], convert_to_numpy=True, normalize_embeddings=True
        ).astype('float32')
        scores, indices = self.faiss_index.search(query_vector, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk = self.chunks[idx]
            results.append({
                'content': chunk.page_content,
                'metadata': chunk.metadata,
                'score': float(score),
            })
        return results

    def retrieve_question_sources(
        self,
        interview_type: str,
        query_hint: str = '',
        search_k: int = 20,
        unique_k: int = 6,
    ) -> List[Dict[str, Any]]:
        if interview_type not in INTERVIEW_TYPES:
            raise ValueError(f'지원하지 않는 면접유형입니다: {interview_type}')

        query = (
            f'{self.company} {self.job} {interview_type} '
            f'직무 이해 문제 해결 협업 역량 면접 질문 평가 포인트 {query_hint}'
        )
        raw = self.search_rag(query, k=search_k)

        sources, seen_titles = [], set()
        for result in raw:
            meta = result['metadata']
            src_type = meta.get('interview_type', 'ALL')
            if src_type not in ('ALL', interview_type):
                continue
            title = meta['source_title']
            if title in seen_titles:
                continue
            seen_titles.add(title)
            sources.append({
                'source_no': len(sources) + 1,
                'content': result['content'],
                'source_title': title,
                'interview_type': src_type,
                'category': meta['category'],
                'source_type': meta['source_type'],
                'page': meta.get('page'),
                'similarity': round(result['score'], 4),
            })
            if len(sources) >= unique_k:
                break
        return sources

    @staticmethod
    def _context(sources: List[Dict[str, Any]]) -> str:
        return '\n'.join(
            f"SOURCE {s['source_no']}\n자료명: {s['source_title']}\n"
            f"자료유형: {s['category']}\n면접유형: {s['interview_type']}\n내용:\n{s['content']}\n"
            for s in sources
        )

    @staticmethod
    def _finalize_questions(drafts, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = []
        for draft in drafts:
            evidence = []
            for source_no in draft.source_numbers:
                if 1 <= source_no <= len(sources):
                    src = sources[source_no - 1]
                    evidence.append({
                        'source_title': src['source_title'],
                        'category': src['category'],
                        'interview_type': src['interview_type'],
                        'page': src['page'],
                        'similarity': src['similarity'],
                    })
            result.append({
                'question_type': draft.question_type,
                'question_text': draft.question_text,
                'question_reason': draft.question_reason,
                'evaluation_points': draft.evaluation_points[:3],
                'rag_evidence': evidence,
                'practice_reason': None,
            })
        return result

    def generate_aisk_questions(self) -> List[Dict[str, Any]]:
        sources = self.retrieve_question_sources('AISK')
        prompt = f'''
너는 기업·직무 맞춤형 A!SK 영상 모의면접 질문 생성 AI다.
기업: {self.company}
직무: {self.job}

아래 RAG 자료만 근거로 질문을 정확히 3개 생성하라.
- 직무이해 1개
- 문제해결 1개
- 협업 1개
각 질문의 evaluation_points는 정확히 3개다.
기업 내부 평가기준과 합격 가능성은 추측하지 않는다.
사용한 근거는 SOURCE 번호만 선택한다.

[RAG 자료]
{self._context(sources)}
'''
        response = self.question_set_llm.invoke(prompt)
        order = {'직무이해': 0, '문제해결': 1, '협업': 2}
        drafts = sorted(response.questions, key=lambda x: order.get(x.question_type, 99))[:3]
        return self._finalize_questions(drafts, sources)

    def generate_deep_initial_question(self) -> Dict[str, Any]:
        sources = self.retrieve_question_sources('DEEP_INTERVIEW')
        prompt = f'''
너는 {self.company} {self.job} 심층 모의면접 질문 생성 AI다.
아래 RAG 자료만 근거로 지원자의 직무 이해와 문제해결 사고를 깊게 확인할 첫 질문을 정확히 1개 생성하라.
evaluation_points는 정확히 3개다. 기업 내부 평가기준은 추측하지 않는다.

[RAG 자료]
{self._context(sources)}
'''
        response = self.question_set_llm.invoke(prompt)
        if not response.questions:
            raise ValueError('심층면접 첫 질문 생성 실패')
        return self._finalize_questions([response.questions[0]], sources)[0]

    def generate_deep_followup_question(
        self,
        current_question: Dict[str, Any],
        stt_text: str,
    ) -> Dict[str, str]:
        prompt = f'''
너는 기업·직무 심층면접의 꼬리질문 생성 AI다.

[현재 질문]
{current_question['question_text']}

[공개자료 기반 평가포인트]
{json.dumps(current_question.get('evaluation_points', []), ensure_ascii=False)}

[지원자 STT 답변]
{stt_text}

답변에서 더 구체적으로 확인할 한 가지를 골라 꼬리질문을 정확히 1개 생성하라.
이미 충분히 설명된 내용을 반복하지 말고 현재 질문과 평가포인트 범위를 벗어나지 않는다.
기업 내부 평가기준과 합격 가능성은 추측하지 않는다.
PoC에서는 추가 연쇄 꼬리질문을 생성하지 않는다.
'''
        return self.deep_followup_llm.invoke(prompt).model_dump()

    def _analysis_cache_key(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
    ) -> str:
        payload = {
            'company': self.company,
            'job': self.job,
            'question_text': question_data.get('question_text', ''),
            'evaluation_points': question_data.get('evaluation_points', [])[:3],
            'answer_structure_criteria': ANSWER_STRUCTURE_CRITERIA,
            'stt_text': ' '.join(stt_text.split()),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _analyze_answer_once(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
    ) -> Dict[str, Any]:
        """LLM을 실제로 한 번 호출해 답변을 분석한다. 캐시는 사용하지 않는다."""
        job_criteria = question_data.get('evaluation_points', [])[:3]
        if len(job_criteria) != 3:
            raise ValueError('evaluation_points는 정확히 3개가 필요합니다.')

        prompt = f'''
너는 모의면접 답변 분석 AI다.
기업 내부 평가표가 아니라 아래 공개자료 기반 평가포인트와 답변 구성 기준만 사용한다.

[질문]
{question_data['question_text']}

[공개자료 기반 직무 평가포인트]
{json.dumps(job_criteria, ensure_ascii=False)}

[답변 구성 기준]
{json.dumps(ANSWER_STRUCTURE_CRITERIA, ensure_ascii=False)}

[STT 답변]
{stt_text}

반드시 다음 규칙을 지켜라.
- 직무 평가포인트 3개 각각을 순서대로 0/1/2로 판단한다.
- 답변 구성 기준 4개 각각을 순서대로 0/1/2로 판단한다.
- 각 항목마다 판정 이유를 정확히 1개씩 반환한다.
- 0=드러나지 않음 또는 질문과 무관
- 1=일부 드러남
- 2=핵심이 직접적이고 명확하게 드러남
- 점수는 직접 100점으로 만들지 않는다.
- 합격/불합격, 기업 내부 채점기준, 성격·감정·자신감은 추측하지 않는다.
'''
        result = self.answer_analysis_llm.invoke(prompt)
        job_levels = list(result.job_levels)
        answer_levels = list(result.answer_levels)

        return {
            'job_evaluation': _qualitative_label(job_levels),
            'answer_evaluation': _qualitative_label(answer_levels),
            'job_score': _score_from_levels(job_levels),
            'answer_score': _score_from_levels(answer_levels),
            'strengths': result.strengths,
            'improvements': result.improvements,
            'job_criteria': [
                {
                    'criterion': c,
                    'level': job_levels[i],
                    'reason': result.job_reasons[i],
                }
                for i, c in enumerate(job_criteria)
            ],
            'answer_criteria': [
                {
                    'criterion': c,
                    'level': answer_levels[i],
                    'reason': result.answer_reasons[i],
                }
                for i, c in enumerate(ANSWER_STRUCTURE_CRITERIA)
            ],
        }

    def analyze_answer(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        기본 동작은 동일 입력에 대해 최초 분석결과를 재사용한다.
        따라서 같은 질문/평가포인트/STT에는 사용자에게 동일한 점수와 피드백을 반환한다.
        """
        cache_key = self._analysis_cache_key(question_data, stt_text)

        if use_cache and cache_key in self._analysis_cache:
            cached = copy.deepcopy(self._analysis_cache[cache_key])
            cached['cache_hit'] = True
            return cached

        analyzed = self._analyze_answer_once(question_data, stt_text)
        analyzed['cache_hit'] = False

        if use_cache:
            self._analysis_cache[cache_key] = copy.deepcopy(analyzed)

        return analyzed

    def check_analysis_repeatability(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
        repeats: int = 3,
    ) -> Dict[str, Any]:
        """
        서비스 관점의 동일 입력 재현성을 확인한다.
        최초 분석 후 같은 입력은 캐시를 사용하므로 동일한 결과가 반환되어야 한다.
        """
        if repeats < 2:
            raise ValueError('repeats는 2 이상이어야 합니다.')

        cache_key = self._analysis_cache_key(question_data, stt_text)
        self._analysis_cache.pop(cache_key, None)

        runs = [self.analyze_answer(question_data, stt_text, use_cache=True) for _ in range(repeats)]
        job_scores = [r['job_score'] for r in runs]
        answer_scores = [r['answer_score'] for r in runs]

        return {
            'mode': 'service_cached_repeatability',
            'repeats': repeats,
            'job_scores': job_scores,
            'job_range': max(job_scores) - min(job_scores),
            'job_std': round(statistics.pstdev(job_scores), 3),
            'answer_scores': answer_scores,
            'answer_range': max(answer_scores) - min(answer_scores),
            'answer_std': round(statistics.pstdev(answer_scores), 3),
            'cache_hits': [r.get('cache_hit', False) for r in runs],
            'raw_runs': runs,
        }

    def check_raw_llm_variability(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
        repeats: int = 3,
    ) -> Dict[str, Any]:
        """
        캐시를 끄고 LLM 자체의 판정 변동을 점검한다.
        운영 점수로 사용하지 않고 개발/검증용으로만 사용한다.
        """
        if repeats < 2:
            raise ValueError('repeats는 2 이상이어야 합니다.')

        runs = [self._analyze_answer_once(question_data, stt_text) for _ in range(repeats)]
        job_scores = [r['job_score'] for r in runs]
        answer_scores = [r['answer_score'] for r in runs]

        return {
            'mode': 'raw_llm_variability',
            'repeats': repeats,
            'job_scores': job_scores,
            'job_range': max(job_scores) - min(job_scores),
            'job_std': round(statistics.pstdev(job_scores), 3),
            'answer_scores': answer_scores,
            'answer_range': max(answer_scores) - min(answer_scores),
            'answer_std': round(statistics.pstdev(answer_scores), 3),
            'raw_runs': runs,
        }
