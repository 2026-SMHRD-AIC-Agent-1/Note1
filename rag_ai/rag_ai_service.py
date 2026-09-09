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

# 답변 평가 점수체계 v7:
# 1) 직무평가 공통 세부조건을 6개 -> 5개로 정리한다.
#    v6의 '의미·이유'와 '원인·영향·관계'를 하나의 논리 설명 항목으로 통합한다.
# 2) 답변 구성 100점은 기존 16개 기본 체크만으로 주지 않는다.
#    기본 체크가 모두 True여도 별도의 우수답변 조건 4개를 모두 충족해야 100점이다.
# 3) LLM은 충족 여부만 판단하고 Python이 실제 점수를 계산한다.
SCORING_VERSION = 'v7_five_job_subchecks_strict_answer_100'
JOB_MAX_LEVEL = 5
ANSWER_MAX_LEVEL = 4

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
    '질문에 직접 대응하는가',
    '논리적으로 구성되어 있는가',
    '구체적으로 설명하는가',
    '명료하고 일관되게 전달하는가',
]

# 특정 기술문제뿐 아니라 직무이해·문제해결·협업 질문에도 공통 적용 가능한 5개 세부조건
JOB_SUBCHECK_LABELS = [
    '평가항목의 핵심 개념 또는 요구요소를 직접 다뤘는가',
    '그 개념·행동의 의미·이유와 필요한 원인·영향·관계를 논리적으로 설명했는가',
    '판단 기준·근거·지표·사례 중 하나 이상을 구체적으로 제시했는가',
    '실제로 어떻게 접근·행동·적용할지 구체적인 방법이나 순서를 제시했는가',
    '결과 확인·재측정·검증·성과·학습·후속 적용 중 하나 이상으로 마무리했는가',
]

# 답변 구성 100점 전용 우수답변 조건.
# 기본 구성점수와 별도로 판단하며, 모두 True일 때만 100점을 허용한다.
ANSWER_EXCELLENCE_LABELS = [
    '답변 초반에 핵심 결론·입장·접근 방향이 분명하게 제시되고 끝까지 유지되는가',
    '결론·이유·근거/예시·방법/행동 중 질문에 필요한 요소들이 단계적으로 자연스럽게 연결되는가',
    '추상적 표현에 머물지 않고 서로 다른 구체적 근거·예시·방법이 충분히 제시되어 답변이 입체적인가',
    '반복·모순·불필요한 우회가 거의 없고 핵심을 한 번에 파악할 수 있을 만큼 완성도가 높은가',
]

# 답변 구성은 직무내용의 정확성·충분성과 분리하여 표현 구조만 평가한다.
ANSWER_STRUCTURE_SUBCHECKS = {
    '질문에 직접 대응하는가': [
        '질문과 같은 주제나 문제에 직접 답하고 있는가',
        '답변의 중심 주제 또는 접근 방향이 분명한가',
        '질문과 무관한 내용으로 크게 벗어나지 않았는가',
        '질문을 회피하거나 동문서답하지 않았는가',
    ],
    '논리적으로 구성되어 있는가': [
        '핵심 주장 또는 접근 방향이 제시되어 있는가',
        '그 주장·방향을 뒷받침하는 이유나 설명이 있는가',
        '설명의 순서가 자연스럽게 이어지는가',
        '앞뒤 내용이 서로 모순되지 않는가',
    ],
    '구체적으로 설명하는가': [
        '추상적인 표현만이 아니라 구체적인 개념·행동·방법 중 하나 이상이 있는가',
        '무엇을 하겠는지 또는 무엇을 했는지 이해할 수 있을 정도로 설명하는가',
        '주장을 뒷받침하는 세부 내용이 하나 이상 있는가',
        '예시·기준·방법·과정 중 하나 이상으로 설명을 구체화했는가',
    ],
    '명료하고 일관되게 전달하는가': [
        '불필요한 반복이 발견되지 않는가',
        '지나치게 장황하거나 우회하는 표현이 두드러지지 않는가',
        '문장과 문장 사이의 연결이 자연스러운가',
        '답변의 핵심을 알아보기 쉬운가',
    ],
}


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


class JobCriterionChecklist(BaseModel):
    checks: List[bool] = Field(min_length=5, max_length=5)
    reason: str


class AnswerCriterionChecklist(BaseModel):
    checks: List[bool] = Field(min_length=4, max_length=4)
    reason: str


class AnswerAnalysisDraft(BaseModel):
    job_checks: List[JobCriterionChecklist] = Field(min_length=3, max_length=3)
    answer_checks: List[AnswerCriterionChecklist] = Field(min_length=4, max_length=4)
    answer_excellence_checks: List[bool] = Field(min_length=4, max_length=4)
    answer_excellence_reason: str
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


def _level_from_checks(checks: List[bool], max_level: int) -> int:
    return sum(1 for value in checks[:max_level] if value)


def _score_from_levels(levels: List[int], max_level: int) -> int:
    if not levels:
        return 0
    return round(sum(levels) / (len(levels) * max_level) * 100)


def _qualitative_label(levels: List[int], max_level: int) -> str:
    if not levels:
        return '보완 필요'
    ratio = sum(levels) / (len(levels) * max_level)
    if ratio >= 0.75:
        return '잘 드러남'
    if ratio >= 0.375:
        return '일부 드러남'
    return '보완 필요'


def _answer_score_v7(answer_levels: List[int], excellence_checks: List[bool]) -> int:
    """기본 구성점수는 유지하되 100점에만 별도 만점 자격을 적용한다."""
    raw_score = _score_from_levels(answer_levels, ANSWER_MAX_LEVEL)
    if raw_score < 100:
        return raw_score
    return 100 if all(excellence_checks[:4]) else 95


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
이미 충분히 설명된 내용을 반복하지 말고 현재 질문과 평가포인트 범위를 벗어나지 않안는다.
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
            'scoring_version': SCORING_VERSION,
            'company': self.company,
            'job': self.job,
            'question_text': question_data.get('question_text', ''),
            'evaluation_points': question_data.get('evaluation_points', [])[:3],
            'job_subcheck_labels': JOB_SUBCHECK_LABELS,
            'answer_structure_criteria': ANSWER_STRUCTURE_CRITERIA,
            'answer_excellence_labels': ANSWER_EXCELLENCE_LABELS,
            'stt_text': ' '.join(stt_text.split()),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    def _analyze_answer_once(
        self,
        question_data: Dict[str, Any],
        stt_text: str,
    ) -> Dict[str, Any]:
        """LLM은 체크만 판단하고 실제 점수 계산과 100점 제한은 Python이 수행한다."""
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

[직무 평가포인트별 공통 세부조건 - 반드시 이 순서로 5개]
{json.dumps(JOB_SUBCHECK_LABELS, ensure_ascii=False)}

[답변 구성 기준과 각 세부조건]
{json.dumps(ANSWER_STRUCTURE_SUBCHECKS, ensure_ascii=False)}

[답변 구성 100점 전용 우수답변 조건 - 반드시 이 순서로 4개]
{json.dumps(ANSWER_EXCELLENCE_LABELS, ensure_ascii=False)}

[STT 답변]
{stt_text}

반드시 다음 규칙을 지켜라.
- 점수나 레벨을 직접 선택하지 않는다.
- 직무 평가포인트 3개 각각에 대해 세부조건 5개를 순서대로 True/False로만 판단한다.
- 답변 구성 기준 4개 각각에 대해 해당 기준의 세부조건 4개를 순서대로 True/False로만 판단한다.
- 마지막으로 답변 구성 100점 전용 우수답변 조건 4개를 별도로 True/False 판단한다.
- STT 답변에 실제로 드러난 내용만 근거로 판단하고, 말하지 않은 직무지식·경험은 추측하지 않는다.
- 단순히 관련 전문용어가 있다는 이유만으로 여러 직무 세부조건을 동시에 True로 만들지 않는다.
- 직무 세부조건의 True는 답변 안에 그 조건을 뒷받침하는 내용이 실제로 있을 때만 선택한다.
- 2번째 직무 세부조건은 단순 정의만 있으면 부족하다. 질문에 필요한 의미·이유·원인·영향·관계 중 적절한 논리 연결이 실제로 설명되어야 True다.
- 3번째 직무 세부조건은 판단 기준·근거·지표·사례 중 해당 평가항목에 자연스럽게 맞는 것이 하나 이상 구체적으로 드러나야 True다.
- 5번째 직무 세부조건은 기술 질문에서는 재측정·검증, 경험 질문에서는 결과·성과·학습·후속 적용처럼 질문 성격에 맞게 판단한다.

[직무 평가와 답변 구성 평가를 반드시 분리한다]
- 직무 평가는 '무엇을 알고 얼마나 충분하게 말했는가'를 본다.
- 답변 구성 평가는 '그 내용을 얼마나 조직적이고 명료하게 말했는가'만 본다.
- 특정 직무 개념, 지표, 메모리 영향, 검증 방법 등이 빠졌다는 이유만으로 답변 구성 기본 체크를 False로 만들지 않는다. 그런 부족함은 직무 평가에서 반영한다.
- '질문에 직접 대응하는가'는 답변이 같은 문제·주제에 직접 답하고 접근 방향을 제시하면 충족 가능하다.
- '논리적으로 구성되어 있는가'는 답변 내부의 주장→이유→방법 순서와 앞뒤 일관성을 본다.
- '구체적으로 설명하는가'에서는 구체적 개념·행동·방법 자체가 확인되면 기본 체크에서는 인정할 수 있다.
- '명료하고 일관되게 전달하는가'는 답변 전체를 보고 반복·장황함·문장 연결·핵심 파악 용이성을 판단한다.
- 짧다는 이유만으로 기본 구성평가를 낮추지 않는다. 짧아도 직접적이고 논리적이며 이해 가능하면 기본 구성점수는 높을 수 있다.

[100점 전용 우수답변 조건은 엄격하게 판단한다]
- 이 4개 조건은 '평범하게 괜찮은 답변'을 가려내기 위한 것이 아니라 정말 완성도 높은 답변에만 100점을 허용하기 위한 조건이다.
- 기본 구성 체크가 모두 True라는 이유만으로 우수답변 조건도 자동으로 True로 만들지 않는다.
- 단순히 짧고 오류가 없거나, 반복·모순이 없다는 이유만으로 우수답변 조건을 True로 만들지 않는다.
- 1번째 조건은 핵심 결론·입장·접근 방향이 답변 초반부터 명확하고 답변 전체가 그 중심을 유지할 때만 True다.
- 2번째 조건은 질문에 맞는 복수의 설명 단계가 실제로 연결되어 있어야 한다. 단순 나열은 False다.
- 3번째 조건은 한 가지 전문용어나 한 가지 행동만 언급한 정도로는 부족하다. 서로 다른 구체적 근거·예시·방법이 충분히 있어야 True다.
- 4번째 조건은 단순히 큰 오류가 없는 수준이 아니라 압축도, 흐름, 핵심 전달력이 모두 뛰어난 경우에만 True다.
- 조금이라도 판단 근거가 부족하면 우수답변 조건은 False로 둔다.

- 신입 지원자에게 실제 현업 경험이나 회사 내부 수치를 요구하지 않는다.
- 각 평가항목마다 전체 판단 이유를 한 문장으로 반환한다.
- answer_excellence_reason에는 100점 자격을 충족하거나 충족하지 못한 핵심 이유를 한 문장으로 반환한다.
- strengths와 improvements는 체크 결과에 근거해 작성한다.
- 합격/불합격, 기업 내부 채점기준, 성격·감정·자신감은 추측하지 않는다.
'''
        result = self.answer_analysis_llm.invoke(prompt)

        job_levels = [
            _level_from_checks(item.checks, JOB_MAX_LEVEL)
            for item in result.job_checks
        ]
        answer_levels = [
            _level_from_checks(item.checks, ANSWER_MAX_LEVEL)
            for item in result.answer_checks
        ]
        excellence_checks = list(result.answer_excellence_checks)
        raw_answer_score = _score_from_levels(answer_levels, ANSWER_MAX_LEVEL)
        answer_score = _answer_score_v7(answer_levels, excellence_checks)

        return {
            'scoring_version': SCORING_VERSION,
            'job_evaluation': _qualitative_label(job_levels, JOB_MAX_LEVEL),
            'answer_evaluation': _qualitative_label(answer_levels, ANSWER_MAX_LEVEL),
            'job_score': _score_from_levels(job_levels, JOB_MAX_LEVEL),
            'answer_score': answer_score,
            'answer_raw_score': raw_answer_score,
            'answer_perfect_eligible': all(excellence_checks[:4]),
            'answer_excellence_checks': excellence_checks,
            'answer_excellence_labels': ANSWER_EXCELLENCE_LABELS,
            'answer_excellence_reason': result.answer_excellence_reason,
            'strengths': result.strengths,
            'improvements': result.improvements,
            'job_criteria': [
                {
                    'criterion': criterion,
                    'level': job_levels[i],
                    'max_level': JOB_MAX_LEVEL,
                    'checks': list(result.job_checks[i].checks),
                    'check_labels': JOB_SUBCHECK_LABELS,
                    'reason': result.job_checks[i].reason,
                }
                for i, criterion in enumerate(job_criteria)
            ],
            'answer_criteria': [
                {
                    'criterion': criterion,
                    'level': answer_levels[i],
                    'max_level': ANSWER_MAX_LEVEL,
                    'checks': list(result.answer_checks[i].checks),
                    'check_labels': ANSWER_STRUCTURE_SUBCHECKS[criterion],
                    'reason': result.answer_checks[i].reason,
                }
                for i, criterion in enumerate(ANSWER_STRUCTURE_CRITERIA)
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
            'scoring_version': SCORING_VERSION,
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
        캐시를 끄고 LLM 자체의 세부조건 판정 변동을 점검한다.
        운영 점수로 사용하지 않고 개발/검증용으로만 사용한다.
        """
        if repeats < 2:
            raise ValueError('repeats는 2 이상이어야 합니다.')

        runs = [self._analyze_answer_once(question_data, stt_text) for _ in range(repeats)]
        job_scores = [r['job_score'] for r in runs]
        answer_scores = [r['answer_score'] for r in runs]

        return {
            'mode': 'raw_llm_variability',
            'scoring_version': SCORING_VERSION,
            'repeats': repeats,
            'job_scores': job_scores,
            'job_range': max(job_scores) - min(job_scores),
            'job_std': round(statistics.pstdev(job_scores), 3),
            'answer_scores': answer_scores,
            'answer_range': max(answer_scores) - min(answer_scores),
            'answer_std': round(statistics.pstdev(answer_scores), 3),
            'raw_runs': runs,
        }
