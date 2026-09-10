"""
routers/ai_pipeline.py
------------------------
재명씨(RAG·언어 AI)의 interview_ai_service_v0_1.py 함수를 호출해서
그 결과를 DB(models.py 확정 테이블)에 저장하는 엔드포인트입니다.

AI연동규격 v0.1 "8. DB 매핑 기준"을 그대로 따릅니다.
  session.company/job/interview_type  -> INTERVIEW_SESSIONS (+ Companies/Jobs 참조는 Backend가 실제 ID로 연결)
  question.*                          -> INTERVIEW_QUESTIONS
  answer.stt_text                     -> USER_ANSWERS
  answer_analysis.*                   -> ANSWER_ANALYSES
  nonverbal_metrics(14개)              -> NONVERBAL_METRICS
  final_coaching.*                    -> FINAL_COACHINGS
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from ai_service_client import get_ai_service, is_ready
from models import (
    InterviewSessions, InterviewQuestions, UserAnswers,
    AnswerAnalyses, NonverbalMetrics, FinalCoachings,
)

router = APIRouter(prefix="/ai", tags=["AI Pipeline (RAG·언어 AI 연동)"])


def _require_ai_ready():
    if not is_ready():
        raise HTTPException(
            status_code=503,
            detail="AI 서비스가 초기화되지 않았습니다. RAG_DATA_DIR·OPENAI_API_KEY 설정을 확인하세요.",
        )


# ------------------------------------------------------------------
# 1) 세션 기준 질문 3개 생성 (직무이해 / 문제해결 / 협업)
#    AI연동규격 4. 초기 질문 생성 입력/출력
# ------------------------------------------------------------------
@router.post("/sessions/{session_id}/generate-questions", response_model=List[InterviewQuestions])
def generate_questions_for_session(session_id: int, db: Session = Depends(get_session)):
    _require_ai_ready()
    ai_service = get_ai_service()

    interview_session = db.get(InterviewSessions, session_id)
    if not interview_session:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")

    company_name = interview_session.company.company_name
    job_name = interview_session.job.job_name

    ai_questions = ai_service.generate_three_questions(
        company=company_name, job=job_name, interview_type=interview_session.interview_type,
    )

    saved: List[InterviewQuestions] = []
    for q in ai_questions:
        question = InterviewQuestions(
            session_id=session_id,
            question_type=q["question_type"],
            question_text=q["question_text"],
            question_reason=q["question_reason"],
            evaluation_points=q["evaluation_points"],  # list[str] 그대로 JSON 컬럼에 저장
            rag_evidence=q["rag_evidence"],              # list[dict] 그대로 JSON 컬럼에 저장
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        saved.append(question)

    return saved


# ------------------------------------------------------------------
# 2) 답변 분석 (job_evaluation / answer_evaluation / strengths / improvements)
#    AI연동규격 5. 답변 분석 규격
# ------------------------------------------------------------------
@router.post("/user-answers/{answer_id}/analyze", response_model=AnswerAnalyses)
def analyze_user_answer(answer_id: int, db: Session = Depends(get_session)):
    _require_ai_ready()
    ai_service = get_ai_service()

    answer = db.get(UserAnswers, answer_id)
    if not answer:
        raise HTTPException(status_code=404, detail="답변을 찾을 수 없습니다.")
    if not answer.stt_text:
        raise HTTPException(status_code=400, detail="stt_text가 비어있어 분석할 수 없습니다.")

    question = answer.question
    question_data = {
        "question_text": question.question_text,
        "evaluation_points": question.evaluation_points or [],
    }

    result = ai_service.analyze_answer(question_data=question_data, stt_text=answer.stt_text)

    analysis = AnswerAnalyses(
        answer_id=answer_id,
        job_evaluation=result["job_evaluation"],
        answer_evaluation=result["answer_evaluation"],
        strengths=result["strengths"],
        improvements=result["improvements"],
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ------------------------------------------------------------------
# 3) 세션 종합 코칭 (질문 3개 완료 후 1회)
#    AI연동규격 7. 세션 최종 코칭 규격
# ------------------------------------------------------------------
@router.post("/sessions/{session_id}/generate-coaching", response_model=FinalCoachings)
def generate_session_coaching(session_id: int, db: Session = Depends(get_session)):
    _require_ai_ready()
    ai_service = get_ai_service()

    interview_session = db.get(InterviewSessions, session_id)
    if not interview_session:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")

    questions = db.exec(
        select(InterviewQuestions).where(InterviewQuestions.session_id == session_id)
    ).all()
    if not questions:
        raise HTTPException(status_code=400, detail="이 세션에 저장된 질문이 없습니다.")

    session_items = []
    for q in questions:
        if not q.answer or not q.answer.analysis:
            raise HTTPException(
                status_code=400,
                detail=f"question_id={q.question_id}의 답변 또는 답변분석이 아직 없습니다. "
                       f"먼저 /ai/user-answers/{{answer_id}}/analyze를 호출하세요.",
            )
        metric = q.answer.nonverbal_metric
        nonverbal_dict = metric.model_dump(exclude={"metric_id", "answer_id"}) if metric else {}

        session_items.append({
            "question": {"question_type": q.question_type},
            "answer_analysis": {
                "job_evaluation": q.answer.analysis.job_evaluation,
                "answer_evaluation": q.answer.analysis.answer_evaluation,
                "strengths": q.answer.analysis.strengths,
                "improvements": q.answer.analysis.improvements,
            },
            "nonverbal_metrics": nonverbal_dict,
        })

    result = ai_service.generate_session_coaching(session_items)

    coaching = FinalCoachings(
        session_id=session_id,
        content_summary=result["content_summary"],
        delivery_summary=result["delivery_summary"],
        priority_focus=result["priority_focus"],
        next_practice_goal=result["next_practice_goal"],
    )
    db.add(coaching)
    db.commit()
    db.refresh(coaching)
    return coaching


# ------------------------------------------------------------------
# 4) 1회차 약점을 반영한 후속(2회차) 질문 생성
#    GPT 검토 "1회차 약점 반영 2회차 질문 - AI 함수는 있음, API 연결 안 됨" 반영.
#    이전 세션의 FinalCoachings(priority_focus, next_practice_goal)를 읽어
#    새 세션에 practice_reason이 채워진 질문을 하나 생성·저장합니다.
# ------------------------------------------------------------------
@router.post("/sessions/{next_session_id}/generate-followup-question", response_model=InterviewQuestions)
def generate_followup_question(
    next_session_id: int, previous_session_id: int, db: Session = Depends(get_session)
):
    _require_ai_ready()
    ai_service = get_ai_service()

    previous = db.get(InterviewSessions, previous_session_id)
    current = db.get(InterviewSessions, next_session_id)
    if not previous or not current:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    if previous.user_id != current.user_id:
        raise HTTPException(status_code=400, detail="서로 다른 사용자의 세션은 연결할 수 없습니다.")

    coaching = previous.coaching
    if not coaching:
        raise HTTPException(
            status_code=400,
            detail="이전 세션의 최종 코칭이 없습니다. 먼저 /ai/sessions/{id}/generate-coaching을 호출하세요.",
        )

    previous_payload = {
        "final_coaching": {
            "priority_focus": coaching.priority_focus or "",
            "next_practice_goal": coaching.next_practice_goal or "",
        },
        "questions": [
            {"question": {"question_text": q.question_text}} for q in previous.questions
        ],
    }

    result = ai_service.generate_followup_question(
        previous_session=previous_payload,
        company=current.company.company_name,
        job=current.job.job_name,
        interview_type=current.interview_type,
    )

    question = InterviewQuestions(
        session_id=next_session_id,
        question_type=result["question_type"],
        question_text=result["question_text"],
        question_reason=result["question_reason"],
        evaluation_points=result["evaluation_points"],
        rag_evidence=result["rag_evidence"],
        practice_reason=result["practice_reason"],  # 1회차 약점을 반영한 이유 (이 필드로 "왜 이 질문인지" 추적 가능)
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question
