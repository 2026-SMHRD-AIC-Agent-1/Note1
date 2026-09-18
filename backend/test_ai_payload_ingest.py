"""
test_ai_payload_ingest.py — 재명씨의 실제 샘플 페이로드로 DB 스키마 검증
--------------------------------------------------------------------------
ai_interview_sample_payload_v0_1.json (재명씨가 실제로 만든 AI 출력 샘플)을
그대로 읽어서 DB에 저장해봅니다. AI를 직접 호출하지 않고도,
"AI가 실제로 만드는 형태의 데이터를 내 스키마가 정확히 담을 수 있는가"를
검증하는 테스트입니다.

실행 방법:
    python test_ai_payload_ingest.py
"""

import json
import os

from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Users, Companies, Jobs, InterviewSessions,
    InterviewQuestions, UserAnswers, NonverbalMetrics,
    AnswerAnalyses, FinalCoachings,
)

TEST_DB_PATH = "test_ai_payload.db"
PAYLOAD_PATH = "ai_interview_sample_payload_v0_1.json"

if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

with open(PAYLOAD_PATH, encoding="utf-8") as f:
    payload = json.load(f)

print("=" * 70)
print("재명씨 샘플 페이로드 -> DB 저장 테스트 시작")
print("=" * 70)

with Session(engine) as session:
    # 테스트용 사용자 + 세션 컨텍스트 (실제로는 Frontend가 로그인한 사용자 기준으로 생성)
    user = Users(email="candidate@example.com", password_hash="hashed", name="테스트 지원자", role="USER")
    session.add(user)
    session.commit()
    session.refresh(user)

    company = Companies(company_name=payload["session"]["company"])
    session.add(company)
    session.commit()
    session.refresh(company)

    job = Jobs(company_id=company.company_id, job_name=payload["session"]["job"])
    session.add(job)
    session.commit()
    session.refresh(job)

    interview_session = InterviewSessions(
        user_id=user.user_id, company_id=company.company_id, job_id=job.job_id,
        interview_type=payload["session"]["interview_type"], status="COMPLETED",
    )
    session.add(interview_session)
    session.commit()
    session.refresh(interview_session)
    print(f"[세션] {company.company_name} / {job.job_name} / {interview_session.interview_type} -> session_id={interview_session.session_id}")

    for i, item in enumerate(payload["questions"], start=1):
        q_data = item["question"]
        question = InterviewQuestions(
            session_id=interview_session.session_id,
            question_type=q_data["question_type"],
            question_text=q_data["question_text"],
            question_reason=q_data["question_reason"],
            evaluation_points=q_data["evaluation_points"],  # list[str] 그대로
            rag_evidence=q_data["rag_evidence"],              # list[dict] 그대로
        )
        session.add(question)
        session.commit()
        session.refresh(question)

        answer = UserAnswers(
            question_id=question.question_id, user_id=user.user_id,
            stt_text=item["answer"]["stt_text"],
        )
        session.add(answer)
        session.commit()
        session.refresh(answer)

        analysis_data = item["answer_analysis"]
        analysis = AnswerAnalyses(
            answer_id=answer.answer_id,
            job_evaluation=analysis_data["job_evaluation"],
            answer_evaluation=analysis_data["answer_evaluation"],
            strengths=analysis_data["strengths"],
            improvements=analysis_data["improvements"],
        )
        session.add(analysis)

        nv = item["nonverbal_metrics"]
        metrics = NonverbalMetrics(answer_id=answer.answer_id, **nv)
        session.add(metrics)
        session.commit()

        print(f"[질문 {i}] {q_data['question_type']} -> question_id={question.question_id}, "
              f"evaluation_points {len(q_data['evaluation_points'])}개, "
              f"rag_evidence {len(q_data['rag_evidence'])}개 저장 완료")

    fc = payload["final_coaching"]
    coaching = FinalCoachings(
        session_id=interview_session.session_id,
        content_summary=fc["content_summary"],
        delivery_summary=fc["delivery_summary"],
        priority_focus=fc["priority_focus"],
        next_practice_goal=fc["next_practice_goal"],
    )
    session.add(coaching)
    session.commit()
    print(f"[최종 코칭] session_id={interview_session.session_id} -> coaching_id={coaching.coaching_id}")

    print("-" * 70)
    print("재조회 검증: 저장된 값이 원본 JSON과 동일한지 확인")
    print("-" * 70)

    saved_session = session.exec(
        select(InterviewSessions).where(InterviewSessions.session_id == interview_session.session_id)
    ).first()
    saved_questions = saved_session.questions

    assert len(saved_questions) == len(payload["questions"]), "질문 개수가 다릅니다!"

    first_q = saved_questions[0]
    original_points = payload["questions"][0]["question"]["evaluation_points"]
    assert first_q.evaluation_points == original_points, "evaluation_points가 원본과 다릅니다!"
    print(f"  evaluation_points 일치 확인: {first_q.evaluation_points}")

    original_evidence = payload["questions"][0]["question"]["rag_evidence"]
    assert first_q.rag_evidence == original_evidence, "rag_evidence가 원본과 다릅니다!"
    print(f"  rag_evidence 일치 확인 (similarity 포함): {first_q.rag_evidence[0]['similarity']}")

    nv_saved = first_q.answer.nonverbal_metric
    print(f"  비언어 측정값 - 시선비율: {nv_saved.gaze_center_ratio}, 침묵횟수: {nv_saved.pause_count}, "
          f"발화속도: {nv_saved.speaking_speed}, 필러워드: {nv_saved.filler_word_count}")

    print(f"  최종 코칭 - 우선개선점: {saved_session.coaching.priority_focus}")

print("=" * 70)
print("✅ 재명씨 실제 샘플 데이터가 DB 스키마에 100% 정확히 저장/복원됨을 확인")
print("=" * 70)
print(f"테스트가 끝났으니 {TEST_DB_PATH} 파일은 지워도 됩니다.")
