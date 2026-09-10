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
DEEP_MAX_FOLLOWUPS = 3

SCORING_VERSION = 'v8_answer_base95_excellence5'
JOB_MAX_LEVEL = 5
ANSWER_MAX_LEVEL = 4
ANSWER_BASE_MAX_SCORE = 95
ANSWER_EXCELLENCE_MAX_BONUS = 5

SOURCE_RULES = {
    '02_': {'category': 'job', 'source_type': 'official_job_report', 'scope': 'job', 'interview_type': 'ALL', 'job_scope': JOB_DEFAULT},
    '03_': {'category': 'interview', 'source_type': 'interview_summary', 'scope': 'company', 'interview_type': 'ALL', 'job_scope': 'ALL'},
    '04_': {'category': 'interview_process', 'source_type': 'official_process', 'scope': 'company', 'interview_type': 'AISK', 'job_scope': 'ALL'},
    '05_': {'category': 'recruiting_direction', 'source_type': 'official_story', 'scope': 'company', 'interview_type': 'ALL', 'job_scope': 'ALL'},
    '06_': {'category': 'job', 'source_type': 'official_job_posting', 'scope': 'job', 'interview_type': 'ALL', 'job_scope': 'Solution SW'},
    '07_': {'category': 'company_values', 'source_type': 'official_home', 'scope': 'company', 'interview_type': 'ALL', 'job_scope': 'ALL'},
    '08_': {'category': 'job_description', 'source_type': 'official_jd_extract', 'scope': 'job', 'interview_type': 'ALL', 'job_scope': 'MULTI'},
}

ANSWER_STRUCTURE_CRITERIA = [
    '질문에 직접 대응하는가',
    '논리적으로 구성되어 있는가',
    '구체적으로 설명하는가',
    '명료하고 일관되게 전달하는가',
]

JOB_SUBCHECK_LABELS = [
    '평가항목의 핵심 개념 또는 요구요소를 직접 다뤘는가',
    '그 개념·행동의 의미·이유와 필요한 원인·영향·관계를 논리적으로 설명했는가',
    '판단 기준·근거·지표·사례 중 하나 이상을 구체적으로 제시했는가',
    '실제로 어떻게 접근·행동·적용할지 구체적인 방법이나 순서를 제시했는가',
    '결과 확인·재측정·검증·성과·학습·후속 적용 중 하나 이상으로 마무리했는가',
]

ANSWER_EXCELLENCE_LABELS = [
    '답변 초반에 핵심 결론·입장·접근 방향이 분명하게 제시되고 끝까지 유지되는가',
    '결론·이유·근거/예시·방법/행동 중 질문에 필요한 요소들이 단계적으로 자연스럽게 연결되는가',
    '추상적 표현에 머물지 않고 서로 다른 구체적 근거·예시·방법이 충분히 제시되어 답변이 입체적인가',
    '반복·모순·불필요한 우회가 거의 없고 핵심을 한 번에 파악할 수 있을 만큼 완성도가 높은가',
]

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
    evaluation_points: List[str] = Field(min_length=3, max_length=3)
    practice_reason: str


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


class DeepSessionSummary(BaseModel):
    overall_summary: str
    strengths: str
    priority_improvement: str
    progress_summary: str
    next_practice_goal: str


def _read_text_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, 'r', encoding='cp949') as f:
            return f.read()


def _find_first_marker(text: str, markers: List[str], start: int = 0) -> int:
    positions = [text.find(marker, start) for marker in markers]
    positions = [pos for pos in positions if pos >= 0]
    return min(positions) if positions else -1


def _extract_multi_job_text(text: str, job: str) -> str:
    solution_start = _find_first_marker(text, ['A. Solution SW'])
    system_start = _find_first_marker(text, ['B. System Architecture / Software Solution', 'B. System Architecture · Software Solution'])
    section_end = _find_first_marker(
        text,
        [
            '==================================================\n2. 기존 자료에서 수정이 필요한 부분',
            '==================================================\r\n2. 기존 자료에서 수정이 필요한 부분',
        ],
        start=max(system_start, 0),
    )

    if job == 'Solution SW':
        if solution_start < 0 or system_start < 0:
            return ''
        return text[solution_start:system_start].strip()

    if job == JOB_DEFAULT:
        if system_start < 0:
            return ''
        end = section_end if section_end >= 0 else len(text)
        return text[system_start:end].strip()

    return ''


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


def _round_half_up(value: float) -> int:
    return int(value + 0.5)


def _answer_score_v8(answer_levels: List[int], excellence_checks: List[bool]) -> Dict[str, Any]:
    total_basic_checks = len(answer_levels) * ANSWER_MAX_LEVEL
    passed_basic_checks = sum(answer_levels)
    base_exact = passed_basic_checks / total_basic_checks * ANSWER_BASE_MAX_SCORE if total_basic_checks else 0.0
    excellence_count = sum(1 for value in excellence_checks[:4] if value)
    excellence_bonus = excellence_count / 4 * ANSWER_EXCELLENCE_MAX_BONUS
    final_score = min(100, _round_half_up(base_exact + excellence_bonus))
    return {
        'base_score': _round_half_up(base_exact),
        'excellence_bonus': round(excellence_bonus, 2),
        'final_score': final_score,
        'perfect_eligible': passed_basic_checks == total_basic_checks and excellence_count == 4,
    }


def _progress_label(change: int) -> str:
    if change >= 15:
        return '크게 향상'
    if change >= 5:
        return '향상'
    if change <= -15:
        return '크게 하락'
    if change <= -5:
        return '하락'
    return '비슷한 수준'


class RagInterviewAI:
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
        self.llm = ChatOpenAI(model=openai_model or os.environ.get('OPENAI_MODEL', 'gpt-5.4-mini'), temperature=0)
        self.embedding_model = SentenceTransformer(embedding_model)
        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100, separators=['\n\n', '\n', '. ', ' ', ''])
        self.documents: List[Document] = []
        self.chunks: List[Document] = []
        self.faiss_index = None
        self._analysis_cache: Dict[str, Dict[str, Any]] = {}
        self.question_set_llm = self.llm.with_structured_output(QuestionSet)
        self.deep_followup_llm = self.llm.with_structured_output(DeepFollowUpDraft)
        self.answer_analysis_llm = self.llm.with_structured_output(AnswerAnalysisDraft)
        self.session_coaching_llm = self.llm.with_structured_output(SessionCoachingResult)
        self.deep_session_summary_llm = self.llm.with_structured_output(DeepSessionSummary)

    def load_and_index(self) -> None:
        if not os.path.isdir(self.base_path):
            raise FileNotFoundError(f'RAG 자료 폴더를 찾을 수 없습니다: {self.base_path}')
        documents: List[Document] = []
        for filename in sorted(os.listdir(self.base_path)):
            full_path = os.path.join(self.base_path, filename)
            if not os.path.isfile(full_path) or filename.lower().endswith('.pdf'):
                continue
            matched_rule = next((rule for prefix, rule in SOURCE_RULES.items() if filename.startswith(prefix)), None)
            if matched_rule is None:
                continue
            text = _read_text_file(full_path).strip()
            if not text:
                continue
            job_scope = matched_rule.get('job_scope', 'ALL')
            if job_scope not in ('ALL', 'MULTI', self.job):
                continue
            if job_scope == 'MULTI':
                text = _extract_multi_job_text(text, self.job)
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
        vectors = self.embedding_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False).astype('float32')
        self.faiss_index = faiss.IndexFlatIP(vectors.shape[1])
        self.faiss_index.add(vectors)

    def _ensure_index(self) -> None:
        if self.faiss_index is None or not self.chunks:
            raise RuntimeError('load_and_index()를 먼저 실행하세요.')

    def search_rag(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        self._ensure_index()
        k = min(k, len(self.chunks))
        query_vector = self.embedding_model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype('float32')
        scores, indices = self.faiss_index.search(query_vector, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk = self.chunks[idx]
            results.append({'content': chunk.page_content, 'metadata': chunk.metadata, 'score': float(score)})
        return results

    def retrieve_question_sources(self, interview_type: str, query_hint: str = '', search_k: int = 20, unique_k: int = 6) -> List[Dict[str, Any]]:
        if interview_type not in INTERVIEW_TYPES:
            raise ValueError(f'지원하지 않는 면접유형입니다: {interview_type}')
        query = f'{self.company} {self.job} {interview_type} 직무 이해 문제 해결 협업 역량 면접 질문 평가 포인트 {query_hint}'
        raw = self.search_rag(query, k=search_k)
        sources, seen_titles = [], set()
        for result in raw:
            meta = result['metadata']
            src_type = meta.get('interview_type', 'ALL')
            if src_type not in ('ALL', interview_type):
                continue
            source_job = meta.get('job', 'ALL')
            if source_job not in ('ALL', self.job):
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
            f"SOURCE {s['source_no']}\n자료명: {s['source_title']}\n자료유형: {s['category']}\n면접유형: {s['interview_type']}\n내용:\n{s['content']}\n"
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
        prompt = f'''너는 기업·직무 맞춤형 A!SK 영상 모의면접 질문 생성 AI다.
기업: {self.company}\n직무: {self.job}
아래 RAG 자료만 근거로 질문을 정확히 3개 생성하라: 직무이해 1개, 문제해결 1개, 협업 1개.
각 질문의 evaluation_points는 정확히 3개다.
현재 선택 직무의 업무와 역량만 사용하고 다른 직무의 업무를 섞지 않는다.
기업 내부 평가기준과 합격 가능성은 추측하지 않는다. 사용한 근거는 SOURCE 번호만 선택한다.
[RAG 자료]\n{self._context(sources)}'''
        response = self.question_set_llm.invoke(prompt)
        order = {'직무이해': 0, '문제해결': 1, '협업': 2}
        drafts = sorted(response.questions, key=lambda x: order.get(x.question_type, 99))[:3]
        return self._finalize_questions(drafts, sources)

    def generate_deep_initial_question(self) -> Dict[str, Any]:
        sources = self.retrieve_question_sources('DEEP_INTERVIEW')
        prompt = f'''너는 {self.company} {self.job} 심층 모의면접 질문 생성 AI다.
아래 RAG 자료만 근거로 지원자의 직무 이해와 문제해결 사고를 깊게 확인할 첫 질문을 정확히 1개 생성하라.
evaluation_points는 정확히 3개다. 현재 선택 직무만 사용하고 다른 직무를 섞지 않는다. 기업 내부 평가기준은 추측하지 않는다.
[RAG 자료]\n{self._context(sources)}'''
        response = self.question_set_llm.invoke(prompt)
        if not response.questions:
            raise ValueError('심층면접 첫 질문 생성 실패')
        return self._finalize_questions([response.questions[0]], sources)[0]

    def generate_deep_followup_question(self, current_question: Dict[str, Any], stt_text: str, follow_up_no: int = 1, previous_followups: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not 1 <= follow_up_no <= DEEP_MAX_FOLLOWUPS:
            raise ValueError(f'follow_up_no는 1~{DEEP_MAX_FOLLOWUPS}만 가능합니다.')
        previous_followups = previous_followups or []
        history_lines = []
        for i, item in enumerate(previous_followups, 1):
            previous_question = item.get('question_text') or item.get('follow_up_question') or ''
            previous_answer = item.get('stt_text') or item.get('answer') or ''
            history_lines.append(f'{i}차 꼬리질문: {previous_question}\n{i}차 답변: {previous_answer}')
        history_text = '\n\n'.join(history_lines) if history_lines else '없음'
        prompt = f'''너는 기업·직무 심층면접의 꼬리질문 생성 AI다.
첫 질문 이후 꼬리질문을 최대 {DEEP_MAX_FOLLOWUPS}개까지 순차 생성한다.
[이번 번호] {follow_up_no}/{DEEP_MAX_FOLLOWUPS}
[이전 기록]\n{history_text}
[현재 질문]\n{current_question['question_text']}
[현재 평가포인트]\n{json.dumps(current_question.get('evaluation_points', []), ensure_ascii=False)}
[지원자 답변]\n{stt_text}
현재 답변에서 아직 충분히 설명되지 않은 한 가지 핵심을 골라 꼬리질문을 정확히 1개 생성하라.
evaluation_points도 정확히 3개 생성하고 practice_reason에는 왜 더 설명해야 하는지 한 문장으로 작성하라.
이미 충분히 설명했거나 이전 꼬리질문에서 확인한 내용은 반복하지 않는다.
현재 질문과 평가포인트 범위를 벗어나지 않고, 지원자가 말하지 않은 경험이나 회사 내부정보를 전제하지 않는다.
1차는 빠진 기준·지표·근거·방법, 2차는 판단 논리·원인관계·선택 기준·트레이드오프, 3차는 검증·우선순위·대안·한계·후속 조치 중 부족한 하나를 우선 확인한다.
기업 내부 평가기준과 합격 가능성은 추측하지 않는다.'''
        draft = self.deep_followup_llm.invoke(prompt)
        return {
            'question_type': current_question.get('question_type', '문제해결'),
            'question_text': draft.follow_up_question,
            'question_reason': draft.follow_up_reason,
            'evaluation_points': draft.evaluation_points[:3],
            'rag_evidence': copy.deepcopy(current_question.get('rag_evidence', [])),
            'practice_reason': draft.practice_reason,
            'follow_up_no': follow_up_no,
            'max_followups': DEEP_MAX_FOLLOWUPS,
            'follow_up_question': draft.follow_up_question,
            'follow_up_reason': draft.follow_up_reason,
        }

    def _analysis_cache_key(self, question_data: Dict[str, Any], stt_text: str) -> str:
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

    def _analyze_answer_once(self, question_data: Dict[str, Any], stt_text: str) -> Dict[str, Any]:
        job_criteria = question_data.get('evaluation_points', [])[:3]
        if len(job_criteria) != 3:
            raise ValueError('evaluation_points는 정확히 3개가 필요합니다.')
        prompt = f'''너는 모의면접 답변 분석 AI다. 기업 내부 평가표가 아니라 공개자료 기반 평가포인트와 답변 구성 기준만 사용한다.
[질문]\n{question_data['question_text']}
[직무 평가포인트]\n{json.dumps(job_criteria, ensure_ascii=False)}
[직무 세부조건]\n{json.dumps(JOB_SUBCHECK_LABELS, ensure_ascii=False)}
[답변 구성 기준]\n{json.dumps(ANSWER_STRUCTURE_SUBCHECKS, ensure_ascii=False)}
[우수성 보너스 조건]\n{json.dumps(ANSWER_EXCELLENCE_LABELS, ensure_ascii=False)}
[STT 답변]\n{stt_text}

규칙:
- 점수나 레벨을 직접 선택하지 말고 직무 평가포인트 3개 각각 세부조건 5개, 답변 구성 4개 각각 세부조건 4개, 우수성 조건 4개를 True/False로만 판단한다.
- 답변에 실제로 드러난 내용만 근거로 판단하고 말하지 않은 지식·경험은 추측하지 않는다.
- 직무 평가포인트 3개와 세부조건 5개는 서로 독립적으로 판단한다.
- 한 평가포인트의 좋은 설명을 다른 평가포인트에 자동 재사용하지 않는다. 다만 동일 내용이 서로 다른 평가포인트의 핵심 요구에 실제로 직접 답하면 각각 인정한다.
- 평가포인트가 서로 일부 겹친다는 이유로 한 항목에서만 인정하지 않는다.
- 답변에 평가포인트의 기준·지표·근거·예시가 실제로 있으면 별도의 추가 설명이나 추가 확장을 임의로 요구하지 않는다.
- 일반적인 측정→분석→최적화→검증 절차만으로 서로 다른 평가포인트를 모두 높게 평가하지 말고 각 평가포인트 고유의 핵심 요구를 먼저 확인한다.
- 실제 AI 워크로드, 차세대 메모리, HW-SW, 협업 등 특정 조건이 있으면 그 조건과 답변 내용이 직접 연결되어야 한다.
- 1번째 직무 세부조건은 관련 단어 언급이 아니라 평가포인트 핵심 요구에 실제로 답해야 True다.
- 2번째는 의미·이유·원인·영향·관계 중 필요한 논리 연결이 실제로 있어야 True다.
- 3번째는 판단 기준·근거·지표·사례 중 자연스럽게 맞는 것이 하나 이상 구체적으로 있어야 True다.
- 한 세부조건이 False라는 이유로 다른 세부조건까지 연쇄적으로 False로 만들지 않는다.
- 평가포인트에 없는 추가 전문지식이나 세부 이론을 임의로 요구하지 않는다.
- 답변이 핵심 요구에 의미상 직접 답했다면 더 깊은 전문 설명이 없다는 이유만으로 1번째 조건을 False로 만들지 않는다.
- 5번째 직무 세부조건은 별도로 엄격하게 본다. 기술 질문에서는 판단·방법·최적화가 맞는지 재측정·재실험·전후 비교·기준선 비교 등으로 실제 확인하는 과정이 명시돼야 True다. 검증이 없으면 5번째만 False로 하며 1~4번째를 낮추지 않는다. 경험 질문은 결과·성과·학습·후속 적용 중 하나 이상이 실제로 있어야 True다.
- 직무 평가는 무엇을 알고 얼마나 충분히 말했는지, 답변 구성은 그 내용을 얼마나 조직적이고 명료하게 말했는지를 본다.
- 직무 개념·지표·검증이 빠졌다는 이유만으로 답변 구성 기본 체크를 False로 만들지 않는다.
- 짧아도 직접적이고 논리적이며 이해 가능하면 답변 구성 기본점수는 높을 수 있다.
- 우수성 보너스는 엄격하게 판단한다. 기본 구성 체크가 모두 True여도 자동으로 True가 아니다. 초반 핵심 방향, 단계적 연결, 충분한 구체성, 높은 압축도와 완성도가 실제로 있어야 한다.
- 신입 지원자에게 실제 현업 경험이나 회사 내부 수치를 요구하지 않는다.
- 각 평가항목 이유는 한 문장으로, strengths와 improvements는 체크 결과에 근거해 작성한다.
- 합격/불합격, 기업 내부 채점기준, 성격·감정·자신감은 추측하지 않는다.'''
        result = self.answer_analysis_llm.invoke(prompt)
        job_levels = [_level_from_checks(item.checks, JOB_MAX_LEVEL) for item in result.job_checks]
        answer_levels = [_level_from_checks(item.checks, ANSWER_MAX_LEVEL) for item in result.answer_checks]
        excellence_checks = list(result.answer_excellence_checks)
        raw_answer_score = _score_from_levels(answer_levels, ANSWER_MAX_LEVEL)
        answer_score_result = _answer_score_v8(answer_levels, excellence_checks)
        return {
            'scoring_version': SCORING_VERSION,
            'job_evaluation': _qualitative_label(job_levels, JOB_MAX_LEVEL),
            'answer_evaluation': _qualitative_label(answer_levels, ANSWER_MAX_LEVEL),
            'job_score': _score_from_levels(job_levels, JOB_MAX_LEVEL),
            'answer_score': answer_score_result['final_score'],
            'answer_raw_score': raw_answer_score,
            'answer_base_score': answer_score_result['base_score'],
            'answer_excellence_bonus': answer_score_result['excellence_bonus'],
            'answer_perfect_eligible': answer_score_result['perfect_eligible'],
            'answer_excellence_checks': excellence_checks,
            'answer_excellence_labels': ANSWER_EXCELLENCE_LABELS,
            'answer_excellence_reason': result.answer_excellence_reason,
            'strengths': result.strengths,
            'improvements': result.improvements,
            'job_criteria': [
                {'criterion': criterion, 'level': job_levels[i], 'max_level': JOB_MAX_LEVEL, 'checks': list(result.job_checks[i].checks), 'check_labels': JOB_SUBCHECK_LABELS, 'reason': result.job_checks[i].reason}
                for i, criterion in enumerate(job_criteria)
            ],
            'answer_criteria': [
                {'criterion': criterion, 'level': answer_levels[i], 'max_level': ANSWER_MAX_LEVEL, 'checks': list(result.answer_checks[i].checks), 'check_labels': ANSWER_STRUCTURE_SUBCHECKS[criterion], 'reason': result.answer_checks[i].reason}
                for i, criterion in enumerate(ANSWER_STRUCTURE_CRITERIA)
            ],
        }

    def analyze_answer(self, question_data: Dict[str, Any], stt_text: str, use_cache: bool = True) -> Dict[str, Any]:
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

    def analyze_deep_session(self, turns: List[Dict[str, Any]], use_cache: bool = True) -> Dict[str, Any]:
        if not turns:
            raise ValueError('심층면접 turns가 비어 있습니다.')
        max_turns = 1 + DEEP_MAX_FOLLOWUPS
        if len(turns) > max_turns:
            raise ValueError(f'심층면접 답변은 최대 {max_turns}개까지 분석할 수 있습니다.')

        answer_reviews = []
        for turn_no, turn in enumerate(turns, 1):
            question_data = turn.get('question_data')
            stt_text = turn.get('stt_text', '')
            if not isinstance(question_data, dict):
                raise ValueError(f'{turn_no}번째 turn의 question_data가 필요합니다.')
            if not str(stt_text).strip():
                raise ValueError(f'{turn_no}번째 turn의 stt_text가 비어 있습니다.')
            analysis = self.analyze_answer(question_data, stt_text, use_cache=use_cache)
            answer_reviews.append({
                'turn_no': turn_no,
                'question_type': question_data.get('question_type'),
                'question_text': question_data.get('question_text', ''),
                'stt_text': stt_text,
                'job_score': analysis['job_score'],
                'answer_score': analysis['answer_score'],
                'strengths': analysis['strengths'],
                'improvements': analysis['improvements'],
                'analysis': analysis,
            })

        job_scores = [item['job_score'] for item in answer_reviews]
        answer_scores = [item['answer_score'] for item in answer_reviews]
        overall_job_score = _round_half_up(sum(job_scores) / len(job_scores))
        overall_answer_score = _round_half_up(sum(answer_scores) / len(answer_scores))
        job_change = job_scores[-1] - job_scores[0] if len(job_scores) > 1 else 0
        answer_change = answer_scores[-1] - answer_scores[0] if len(answer_scores) > 1 else 0
        weakest = min(answer_reviews, key=lambda item: (item['job_score'], item['answer_score']))
        strongest = max(answer_reviews, key=lambda item: (item['job_score'], item['answer_score']))

        progress = {
            'job_scores': job_scores,
            'answer_scores': answer_scores,
            'job': {'first': job_scores[0], 'last': job_scores[-1], 'change': job_change, 'trend': _progress_label(job_change) if len(job_scores) > 1 else '비교 불가'},
            'answer': {'first': answer_scores[0], 'last': answer_scores[-1], 'change': answer_change, 'trend': _progress_label(answer_change) if len(answer_scores) > 1 else '비교 불가'},
        }
        compact_reviews = [
            {'turn_no': item['turn_no'], 'question_text': item['question_text'], 'job_score': item['job_score'], 'answer_score': item['answer_score'], 'strengths': item['strengths'], 'improvements': item['improvements']}
            for item in answer_reviews
        ]
        summary_prompt = f'''너는 심층 모의면접 종료 후 종합 코칭을 만드는 AI다.
아래 답변별 분석 결과만 사용해 종합평가를 작성하라. 새로운 점수를 만들거나 합격 가능성을 추측하지 않는다.
사용자가 몇 번째 답변에서 부족했고 어떻게 좋아졌는지 알 수 있게 변화 흐름을 반영한다.
강점과 우선 보완점은 반복하지 말고 가장 중요한 내용 중심으로 작성한다.
[기업] {self.company}\n[직무] {self.job}
[종합 점수] 직무 {overall_job_score}, 답변 구성 {overall_answer_score}
[변화 흐름]\n{json.dumps(progress, ensure_ascii=False)}
[답변별 분석]\n{json.dumps(compact_reviews, ensure_ascii=False)}'''
        summary = self.deep_session_summary_llm.invoke(summary_prompt).model_dump()
        return {
            'interview_type': 'DEEP_INTERVIEW',
            'scoring_version': SCORING_VERSION,
            'turn_count': len(answer_reviews),
            'overall': {'job_score': overall_job_score, 'answer_score': overall_answer_score},
            'progress': progress,
            'weakest_turn': {'turn_no': weakest['turn_no'], 'job_score': weakest['job_score'], 'answer_score': weakest['answer_score'], 'improvements': weakest['improvements']},
            'strongest_turn': {'turn_no': strongest['turn_no'], 'job_score': strongest['job_score'], 'answer_score': strongest['answer_score'], 'strengths': strongest['strengths']},
            'summary': summary,
            'answer_reviews': answer_reviews,
        }

    def check_analysis_repeatability(self, question_data: Dict[str, Any], stt_text: str, repeats: int = 3) -> Dict[str, Any]:
        if repeats < 2:
            raise ValueError('repeats는 2 이상이어야 합니다.')
        cache_key = self._analysis_cache_key(question_data, stt_text)
        self._analysis_cache.pop(cache_key, None)
        runs = [self.analyze_answer(question_data, stt_text, use_cache=True) for _ in range(repeats)]
        job_scores = [r['job_score'] for r in runs]
        answer_scores = [r['answer_score'] for r in runs]
        return {
            'mode': 'service_cached_repeatability', 'scoring_version': SCORING_VERSION, 'repeats': repeats,
            'job_scores': job_scores, 'job_range': max(job_scores) - min(job_scores), 'job_std': round(statistics.pstdev(job_scores), 3),
            'answer_scores': answer_scores, 'answer_range': max(answer_scores) - min(answer_scores), 'answer_std': round(statistics.pstdev(answer_scores), 3),
            'cache_hits': [r.get('cache_hit', False) for r in runs], 'raw_runs': runs,
        }

    def check_raw_llm_variability(self, question_data: Dict[str, Any], stt_text: str, repeats: int = 3) -> Dict[str, Any]:
        if repeats < 2:
            raise ValueError('repeats는 2 이상이어야 합니다.')
        runs = [self._analyze_answer_once(question_data, stt_text) for _ in range(repeats)]
        job_scores = [r['job_score'] for r in runs]
        answer_scores = [r['answer_score'] for r in runs]
        return {
            'mode': 'raw_llm_variability', 'scoring_version': SCORING_VERSION, 'repeats': repeats,
            'job_scores': job_scores, 'job_range': max(job_scores) - min(job_scores), 'job_std': round(statistics.pstdev(job_scores), 3),
            'answer_scores': answer_scores, 'answer_range': max(answer_scores) - min(answer_scores), 'answer_std': round(statistics.pstdev(answer_scores), 3),
            'raw_runs': runs,
        }
