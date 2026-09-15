"""
routers/ai_pipeline.py
------------------------
통합된 rag_ai/rag_ai_service.py를 호출해서
그 결과를 DB(models.py 확정 테이블)에 저장하는 엔드포인트입니다.

AI연동규격 v0.1 "8. DB 매핑 기준"을 그대로 따릅니다.
  session.company/job/interview_type  -> INTERVIEW_SESSIONS (+ Companies/Jobs 참조는 Backend가 실제 ID로 연결)
  question.*                          -> INTERVIEW_QUESTIONS
  answer.stt_text                     -> USER_ANSWERS
  answer_analysis.*                   -> ANSWER_ANALYSES
  nonverbal_metrics(14개)             -> NONVERBAL_METRICS
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
from routers.consents import has_active_consent

router = APIRouter(prefix="/ai", tags=["AI Pipeline (RAG·언어 AI 연동)"])

# 심층면접은 첫 질문 1개 + 답변 기반 꼬리질문 최대 3개로 운영합니다.
# 즉 한 세션에서 최대 4문항까지 진행합니다.
DEEP_MAX_FOLLOWUPS = 3


def _require_ai_ready():
    if not is_ready():
        raise HTTPException(
            status_code=503,
            detail="AI 서비스가 초기화되지 않았습니다. RAG_DATA_DIR·OPENAI_API_KEY 설정을 확인하세요.",
        )


# ------------------------------------------------------------------
# 1) 세션 기준 질문 생성
#    - A!SK: 직무이해 / 문제해결 / 협업 3개
#    - DEEP_INTERVIEW: 첫 질문 1개
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
            evaluation_points=q["evaluation_points"],
            rag_evidence=q["rag_evidence"],
        )
        db.add(question)
        db.commit()
        db.refresh(question)
        saved.append(question)

    return saved


# ------------------------------------------------------------------
# 1-1) 심층면접 세션 안에서 답변 기반 꼬리질문 생성
#
# 첫 질문에 답하면 1차 꼬리질문, 그 답변에 답하면 2차, 다시 답하면 3차까지 생성합니다.
# 기존 RAG의 generate_deep_followup_question()은 "한 번에 꼬리질문 1개"만 만드는 함수라
# 백엔드가 호출 횟수를 관리해서 최대 3회 연쇄 흐름으로 연결합니다.
#
# 현재 Backend RAG의 DeepFollowUpDraft는 question/reason만 반환하므로, 꼬리질문은
# 직전 질문의 공개자료 기반 evaluation_points/rag_evidence를 그대로 이어받습니다.
# 이렇게 해야 새 꼬리질문 답변도 기존 V8 분석기로 동일하게 평가할 수 있습니다.
# ------------------------------------------------------------------
@router.post(
    "/sessions/{session_id}/generate-deep-followup",
    response_model=InterviewQuestions,
)
def generate_deep_followup(
    session_id: int,
    question_id: int,
    db: Session = Depends(get_session),
):
    _require_ai_ready()
    ai_service = get_ai_service()

    interview_session = db.get(InterviewSessions, session_id)
    if not interview_session:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")
    if interview_session.interview_type != "DEEP_INTERVIEW":
        raise HTTPException(status_code=400, detail="심층면접 세션에서만 꼬리질문을 생성할 수 있습니다.")

    current = db.get(InterviewQuestions, question_id)
    if not current or current.session_id != session_id:
        raise HTTPException(status_code=400, detail="현재 심층면접 세션의 질문이 아닙니다.")
    if not current.answer or not current.answer.stt_text:
        raise HTTPException(status_code=400, detail="현재 질문의 답변 STT가 있어야 꼬리질문을 만들 수 있습니다.")

    questions = db.exec(
        select(InterviewQuestions)
        .where(InterviewQuestions.session_id == session_id)
        .order_by(InterviewQuestions.question_id)
    ).all()
    if not questions:
        raise HTTPException(status_code=400, detail="이 세션의 첫 질문이 없습니다.")

    # 이미 생성된 가장 마지막 질문의 답변에서만 다음 꼬리질문을 만들 수 있게 막습니다.
    # 중간 질문에서 다시 생성해 가지(branch)가 갈라지는 것을 방지합니다.
    if questions[-1].question_id != question_id:
        raise HTTPException(status_code=400, detail="가장 최근 질문의 답변에서만 다음 꼬리질문을 생성할 수 있습니다.")

    followup_count = max(0, len(questions) - 1)
    if followup_count >= DEEP_MAX_FOLLOWUPS:
        raise HTTPException(
            status_code=400,
            detail=f"심층면접 꼬리질문은 최대 {DEEP_MAX_FOLLOWUPS}회까지 가능합니다.",
        )
    next_followup_no = followup_count + 1

    # 이전 질문 문장을 함께 전달해 같은 내용을 반복해서 묻는 가능성을 낮춥니다.
    previous_question_texts = [q.question_text for q in questions[:-1]]
    history_hint = ""
    if previous_question_texts:
        history_hint = (
            "\n\n[이미 앞에서 물어본 질문 - 같은 내용을 그대로 반복하지 말 것]\n- "
            + "\n- ".join(previous_question_texts)
        )

    current_question_data = {
        "question_text": f"{current.question_text}{history_hint}",
        "evaluation_points": current.evaluation_points or [],
    }
    result = ai_service.generate_deep_followup_question(
        current_question=current_question_data,
        stt_text=current.answer.stt_text,
    )

    question = InterviewQuestions(
        session_id=session_id,
        question_type=current.question_type or "문제해결",
        question_text=result["follow_up_question"],
        question_reason=result["follow_up_reason"],
        evaluation_points=current.evaluation_points or [],
        rag_evidence=current.rag_evidence or [],
        practice_reason=(
            f"심층면접 {next_followup_no}차 꼬리질문: 직전 답변에서 더 구체적으로 확인할 부분을 이어서 질문"
        ),
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question


# ------------------------------------------------------------------
# 2) 답변 분석 (job_evaluation / answer_evaluation / strengths / improvements)
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

    if not has_active_consent(db, answer.user_id, "ANALYSIS"):
        raise HTTPException(
            status_code=403,
            detail="AI 분석 동의(ANALYSIS)가 없거나 철회/만료되어 분석할 수 없습니다.",
        )

    question = answer.question
    question_data = {
        "question_text": question.question_text,
        "evaluation_points": question.evaluation_points or [],
    }

    result = ai_service.analyze_answer(question_data=question_data, stt_text=answer.stt_text)

    analysis = answer.analysis
    if analysis is None:
        analysis = AnswerAnalyses(answer_id=answer_id)

    analysis.job_evaluation = result["job_evaluation"]
    analysis.answer_evaluation = result["answer_evaluation"]
    analysis.strengths = result["strengths"]
    analysis.improvements = result["improvements"]
    analysis.job_score = result.get("job_score")
    analysis.answer_score = result.get("answer_score")
    analysis.scoring_version = result.get("scoring_version")
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


# ------------------------------------------------------------------
# 3) 세션 종합 코칭
#    A!SK는 3문항, 심층면접은 실제 생성된 첫 질문+꼬리질문 전체를 종합합니다.
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
                "job_score": q.answer.analysis.job_score,
                "answer_score": q.answer.analysis.answer_score,
                "scoring_version": q.answer.analysis.scoring_version,
            },
            "nonverbal_metrics": nonverbal_dict,
        })

    result = ai_service.generate_session_coaching(session_items)

    coaching = interview_session.coaching
    if coaching is None:
        coaching = FinalCoachings(session_id=session_id)

    coaching.content_summary = result["content_summary"]
    coaching.delivery_summary = result["delivery_summary"]
    coaching.priority_focus = result["priority_focus"]
    coaching.next_practice_goal = result["next_practice_goal"]
    coaching.overall_score = result.get("overall_score")
    db.add(coaching)
    db.commit()
    db.refresh(coaching)
    return coaching


# ------------------------------------------------------------------
# 4) 1회차 약점을 반영한 후속(2회차) 질문 생성
#    주의: 이것은 같은 심층면접 세션 안의 꼬리질문과 다른 기능입니다.
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
        practice_reason=result["practice_reason"],
    )
    db.add(question)
    db.commit()
    db.refresh(question)
    return question
