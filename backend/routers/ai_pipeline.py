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
from rag_ai.deep_followup_contract import (
    DEEP_MAX_FOLLOWUPS,
    generate_deep_followup_contract,
)
from routers.consents import has_active_consent

router = APIRouter(prefix="/ai", tags=["AI Pipeline (RAG·언어 AI 연동)"])


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
#
#    주의: RagInterviewAI는 서버 시작 시 RAG_DEFAULT_COMPANY/RAG_DEFAULT_JOB
#    자료로만 색인되는 단일 인스턴스라서, generate_aisk_questions()/
#    generate_deep_initial_question()는 company/job 인자를 받지 않는다.
#    (예전 generate_three_questions(company, job, interview_type)라는
#    메서드는 지금 rag_ai_service.py에 존재하지 않는다.) 그래서 세션에
#    저장된 기업/직무명이 서버가 색인한 것과 다르면 결과가 그 기업/직무와
#    안 맞을 수 있으니, 다르면 바로 알 수 있도록 400으로 막아둔다.
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
    if company_name != ai_service.company or job_name != ai_service.job:
        raise HTTPException(
            status_code=400,
            detail=(
                f"현재 서버는 '{ai_service.company} / {ai_service.job}' 자료로만 색인되어 있습니다. "
                f"요청한 '{company_name} / {job_name}'과 다릅니다."
            ),
        )

    if interview_session.interview_type == "AISK":
        ai_questions = ai_service.generate_aisk_questions()
    elif interview_session.interview_type == "DEEP_INTERVIEW":
        ai_questions = [ai_service.generate_deep_initial_question()]
    else:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 면접유형입니다: {interview_session.interview_type}",
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
# 꼬리질문의 출력 형식은 최상위 rag_ai/integration_contract.json과 동일하게
# question/reason/evaluation_points/practice_reason을 한 번에 생성합니다.
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

    # 가장 최근 질문의 답변에서만 다음 꼬리질문을 만들 수 있게 막아
    # 중간 질문에서 가지(branch)가 갈라지는 것을 방지합니다.
    if questions[-1].question_id != question_id:
        raise HTTPException(status_code=400, detail="가장 최근 질문의 답변에서만 다음 꼬리질문을 생성할 수 있습니다.")

    followup_count = max(0, len(questions) - 1)
    if followup_count >= DEEP_MAX_FOLLOWUPS:
        raise HTTPException(
            status_code=400,
            detail=f"심층면접 꼬리질문은 최대 {DEEP_MAX_FOLLOWUPS}회까지 가능합니다.",
        )
    next_followup_no = followup_count + 1

    # 첫 질문은 제외하고, 이미 끝난 꼬리질문/답변 기록만 전달합니다.
    # 현재 질문은 별도 current_question으로 전달되므로 history에 중복해서 넣지 않습니다.
    previous_followups = []
    for previous in questions[1:-1]:
        previous_followups.append({
            "question_text": previous.question_text,
            "stt_text": previous.answer.stt_text if previous.answer and previous.answer.stt_text else "",
        })

    current_question_data = {
        "question_type": current.question_type or "문제해결",
        "question_text": current.question_text,
        "evaluation_points": current.evaluation_points or [],
        "rag_evidence": current.rag_evidence or [],
    }
    result = generate_deep_followup_contract(
        ai_service=ai_service,
        current_question=current_question_data,
        stt_text=current.answer.stt_text,
        follow_up_no=next_followup_no,
        previous_followups=previous_followups,
    )

    question = InterviewQuestions(
        session_id=session_id,
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


# ------------------------------------------------------------------
# 2) 답변 분석 (job_evaluation / answer_evaluation / strengths / improvements)
#    - A!SK: analyze_answer() 그대로 사용
#    - DEEP_INTERVIEW: analyze_deep_turn() 사용
#      (내부적으로 analyze_answer()를 감싸는 것뿐이라 저장되는 결과 형식은
#      동일하다. 다만 이렇게 분리해두면 나중에 "심층면접 답변만 다르게
#      처리"해야 할 때 이 지점에서 바로 확장할 수 있다.)
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
        "question_type": question.question_type,
        "question_text": question.question_text,
        "evaluation_points": question.evaluation_points or [],
    }

    interview_type = question.session.interview_type if question.session else "AISK"
    if interview_type == "DEEP_INTERVIEW":
        turn = ai_service.analyze_deep_turn(question_data=question_data, stt_text=answer.stt_text)
        result = turn["analysis"]
    else:
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
#    A!SK는 3문항을 generate_session_coaching()으로 종합합니다.
#    DEEP_INTERVIEW는 이미 질문마다 저장해둔 analyze_deep_turn() 결과를
#    다시 채점하지 않고, analyze_deep_session()으로 그대로 종합합니다.
# ------------------------------------------------------------------
@router.post("/sessions/{session_id}/generate-coaching", response_model=FinalCoachings)
def generate_session_coaching(session_id: int, db: Session = Depends(get_session)):
    _require_ai_ready()
    ai_service = get_ai_service()

    interview_session = db.get(InterviewSessions, session_id)
    if not interview_session:
        raise HTTPException(status_code=404, detail="면접 세션을 찾을 수 없습니다.")

    questions = db.exec(
        select(InterviewQuestions)
        .where(InterviewQuestions.session_id == session_id)
        .order_by(InterviewQuestions.question_id)
    ).all()
    if not questions:
        raise HTTPException(status_code=400, detail="이 세션에 저장된 질문이 없습니다.")

    for q in questions:
        if not q.answer or not q.answer.analysis:
            raise HTTPException(
                status_code=400,
                detail=f"question_id={q.question_id}의 답변 또는 답변분석이 아직 없습니다. "
                       f"먼저 /ai/user-answers/{{answer_id}}/analyze를 호출하세요.",
            )

    if interview_session.interview_type == "DEEP_INTERVIEW":
        # 질문마다 이미 analyze_deep_turn()으로 평가·저장해둔 결과를 재채점하지
        # 않고 그대로 다시 조립해서 analyze_deep_session()에 넘긴다.
        turns = []
        for q in questions:
            a = q.answer.analysis
            turns.append({
                "question_data": {
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "evaluation_points": q.evaluation_points or [],
                },
                "stt_text": q.answer.stt_text,
                "analysis": {
                    "job_evaluation": a.job_evaluation,
                    "answer_evaluation": a.answer_evaluation,
                    "strengths": a.strengths,
                    "improvements": a.improvements,
                    "job_score": a.job_score,
                    "answer_score": a.answer_score,
                    "scoring_version": a.scoring_version,
                },
            })

        deep_result = ai_service.analyze_deep_session(turns)
        summary = deep_result["summary"]
        overall = deep_result["overall"]
        result = {
            "content_summary": summary["overall_summary"],
            # analyze_deep_session()은 내용(job_score/answer_score)만 종합하고
            # 비언어 지표는 다루지 않으므로, 델리버리 서머리는 별도 안내 문구로
            # 대체한다. 실제 전달 안정성 수치는 리포트의 전달 안정성 섹션
            # (/interview-sessions/{id}/delivery-summary)에서 확인한다.
            "delivery_summary": (
                "심층면접 종합에는 별도의 전달(비언어) 요약이 포함되지 않습니다. "
                "답변별 전달 안정성은 리포트의 전달 안정성 섹션을 참고하세요."
            ),
            "priority_focus": summary["priority_improvement"],
            "next_practice_goal": summary["next_practice_goal"],
            "overall_score": round((overall["job_score"] + overall["answer_score"]) / 2),
        }
    else:
        session_items = []
        for q in questions:
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
# 4) 1회차 약점을 반영한 후속(2회차 이상) 질문 생성
#    주의: 이것은 같은 심층면접 세션 안의 꼬리질문과 다른 기능입니다.
#    - AISK: 1회차와 동일하게 3개(직무이해/문제해결/협업) 생성
#    - DEEP_INTERVIEW: 1회차와 동일하게 첫 질문 1개 생성(꼬리질문은 답변 후 별도 생성)
# ------------------------------------------------------------------
@router.post("/sessions/{next_session_id}/generate-followup-question", response_model=List[InterviewQuestions])
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

    if current.interview_type == "AISK":
        results = ai_service.generate_followup_questions(
            previous_session=previous_payload,
            interview_type=current.interview_type,
        )
    else:
        results = [
            ai_service.generate_followup_question(
                previous_session=previous_payload,
                company=current.company.company_name,
                job=current.job.job_name,
                interview_type=current.interview_type,
            )
        ]

    saved: List[InterviewQuestions] = []
    for result in results:
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
        saved.append(question)

    return saved
