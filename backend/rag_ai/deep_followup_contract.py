"""심층면접 꼬리질문 출력 형식을 실제 웹 런타임과 통합 규격에 맞추는 어댑터.

최상위 rag_ai/integration_contract.json과 rag_ai/rag_ai_service.py의 심층 꼬리질문
형식을 FastAPI 런타임에서도 동일하게 사용하기 위한 작은 연결 계층이다.

기존 backend/rag_ai/rag_ai_service.py는 다른 백엔드 전용 변경(PDF 지원 등)을 포함하고
있어서 파일 전체를 교체하지 않는다. 대신 실제 심층면접 API가 이 함수를 사용해
질문·이유·평가포인트·practice_reason을 한 번에 생성한다.
"""

import copy
import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


DEEP_MAX_FOLLOWUPS = 3


class DeepFollowUpDraft(BaseModel):
    follow_up_question: str
    follow_up_reason: str
    evaluation_points: List[str] = Field(min_length=3, max_length=3)
    practice_reason: str


def generate_deep_followup_contract(
    ai_service: Any,
    current_question: Dict[str, Any],
    stt_text: str,
    follow_up_no: int = 1,
    previous_followups: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """심층면접 꼬리질문 1개를 통합 계약 형식으로 생성한다."""
    if not 1 <= follow_up_no <= DEEP_MAX_FOLLOWUPS:
        raise ValueError(f"follow_up_no는 1~{DEEP_MAX_FOLLOWUPS}만 가능합니다.")

    previous_followups = previous_followups or []
    history_lines: List[str] = []
    for i, item in enumerate(previous_followups, 1):
        previous_question = item.get("question_text") or item.get("follow_up_question") or ""
        previous_answer = item.get("stt_text") or item.get("answer") or ""
        history_lines.append(
            f"{i}차 꼬리질문: {previous_question}\n{i}차 답변: {previous_answer}"
        )
    history_text = "\n\n".join(history_lines) if history_lines else "없음"

    prompt = f'''너는 기업·직무 심층면접의 꼬리질문 생성 AI다.
첫 질문 이후 꼬리질문을 최대 {DEEP_MAX_FOLLOWUPS}개까지 순차 생성한다.

[이번 번호] {follow_up_no}/{DEEP_MAX_FOLLOWUPS}

[이전 꼬리질문 기록]
{history_text}

[현재 질문]
{current_question['question_text']}

[현재 평가포인트]
{json.dumps(current_question.get('evaluation_points', []), ensure_ascii=False)}

[지원자 답변]
{stt_text}

현재 답변에서 아직 충분히 설명되지 않은 한 가지 핵심을 골라 꼬리질문을 정확히 1개 생성하라.
evaluation_points도 정확히 3개 생성하고 practice_reason에는 왜 이 부분을 더 확인해야 하는지 한 문장으로 작성하라.
이미 충분히 설명했거나 이전 꼬리질문에서 확인한 내용은 반복하지 않는다.
현재 질문과 평가포인트 범위를 벗어나지 않고, 지원자가 말하지 않은 경험이나 회사 내부정보를 전제하지 않는다.
1차는 빠진 기준·지표·근거·방법, 2차는 판단 논리·원인관계·선택 기준·트레이드오프,
3차는 검증·우선순위·대안·한계·후속 조치 중 부족한 하나를 우선 확인한다.
기업 내부 평가기준과 합격 가능성은 추측하지 않는다.'''

    structured_llm = ai_service.llm.with_structured_output(DeepFollowUpDraft)
    draft = structured_llm.invoke(prompt)

    return {
        "question_type": current_question.get("question_type", "문제해결"),
        "question_text": draft.follow_up_question,
        "question_reason": draft.follow_up_reason,
        "evaluation_points": draft.evaluation_points[:3],
        "rag_evidence": copy.deepcopy(current_question.get("rag_evidence", [])),
        "practice_reason": draft.practice_reason,
        "follow_up_no": follow_up_no,
        "max_followups": DEEP_MAX_FOLLOWUPS,
        # 하위 호환 키: 최상위 RAG 계약과 기존 호출부가 모두 읽을 수 있게 유지한다.
        "follow_up_question": draft.follow_up_question,
        "follow_up_reason": draft.follow_up_reason,
    }
