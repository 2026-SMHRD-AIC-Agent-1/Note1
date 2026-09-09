import hashlib
import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

try:
    from .rag_ai_service import (
        ANSWER_STRUCTURE_CRITERIA,
        ANSWER_STRUCTURE_SUBCHECKS,
        RagInterviewAI as RagInterviewAIV6,
        _level_from_checks,
        _qualitative_label,
        _score_from_levels,
    )
except ImportError:
    from rag_ai_service import (
        ANSWER_STRUCTURE_CRITERIA,
        ANSWER_STRUCTURE_SUBCHECKS,
        RagInterviewAI as RagInterviewAIV6,
        _level_from_checks,
        _qualitative_label,
        _score_from_levels,
    )


# V7 핵심 변경
# 1) 직무평가 공통 세부조건을 6개 -> 5개로 정리한다.
#    V6의 '의미·이유'와 '원인·영향·관계'를 하나의 논리 설명 항목으로 통합한다.
# 2) 답변 구성 100점은 기존 16개 기본 체크만으로 주지 않는다.
#    기본 체크가 모두 True여도 별도의 우수답변 조건 4개를 모두 충족해야 100점이다.
SCORING_VERSION = 'v7_five_job_subchecks_strict_answer_100'
JOB_MAX_LEVEL = 5
ANSWER_MAX_LEVEL = 4


JOB_SUBCHECK_LABELS = [
    '평가항목의 핵심 개념 또는 요구요소를 직접 다뤘는가',
    '그 개념·행동의 의미·이유와 필요한 원인·영향·관계를 논리적으로 설명했는가',
    '판단 기준·근거·지표·사례 중 하나 이상을 구체적으로 제시했는가',
    '실제로 어떻게 접근·행동·적용할지 구체적인 방법이나 순서를 제시했는가',
    '결과 확인·재측정·검증·성과·학습·후속 적용 중 하나 이상으로 마무리했는가',
]


# 답변 구성 100점 전용 우수답변 조건.
# 기본 구성점수와는 별개로 판단하며, 모두 True일 때만 100점을 허용한다.
ANSWER_EXCELLENCE_LABELS = [
    '답변 초반에 핵심 결론·입장·접근 방향이 분명하게 제시되고 끝까지 유지되는가',
    '결론·이유·근거/예시·방법/행동 중 질문에 필요한 요소들이 단계적으로 자연스럽게 연결되는가',
    '추상적 표현에 머물지 않고 서로 다른 구체적 근거·예시·방법이 충분히 제시되어 답변이 입체적인가',
    '반복·모순·불필요한 우회가 거의 없고 핵심을 한 번에 파악할 수 있을 만큼 완성도가 높은가',
]


class JobCriterionChecklistV7(BaseModel):
    checks: List[bool] = Field(min_length=5, max_length=5)
    reason: str


class AnswerCriterionChecklistV7(BaseModel):
    checks: List[bool] = Field(min_length=4, max_length=4)
    reason: str


class AnswerAnalysisDraftV7(BaseModel):
    job_checks: List[JobCriterionChecklistV7] = Field(min_length=3, max_length=3)
    answer_checks: List[AnswerCriterionChecklistV7] = Field(min_length=4, max_length=4)
    answer_excellence_checks: List[bool] = Field(min_length=4, max_length=4)
    answer_excellence_reason: str
    strengths: str
    improvements: str


def _answer_score_v7(answer_levels: List[int], excellence_checks: List[bool]) -> int:
    """기본 구성점수는 유지하되 100점에만 별도 만점 자격을 적용한다."""
    raw_score = _score_from_levels(answer_levels, ANSWER_MAX_LEVEL)
    if raw_score < 100:
        return raw_score

    # 16개 기본 체크가 모두 True여도 우수답변 조건 하나라도 빠지면 95점으로 제한한다.
    return 100 if all(excellence_checks[:4]) else 95


class RagInterviewAI(RagInterviewAIV6):
    """V6 전체 기능을 유지하고 답변 평가 로직만 V7로 교체한다."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.answer_analysis_llm = self.llm.with_structured_output(AnswerAnalysisDraftV7)

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
