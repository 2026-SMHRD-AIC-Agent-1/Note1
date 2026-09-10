"""
test_smoke.py — DB 틀이 실제로 작동하는지 한 번에 확인하는 테스트 스크립트
--------------------------------------------------------------------------
FastAPI 서버를 켜지 않고도, 10개 테이블에 순서대로 데이터를 하나씩 넣고
관계(FK)가 제대로 연결되는지 직접 확인합니다.

실행 방법:
    python test_smoke.py

성공하면 마지막에 "전체 10개 테이블 정상 동작 확인" 메시지가 뜹니다.
실패하면 어느 단계에서 멈췄는지 바로 알 수 있습니다.
"""

import os
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Users, Companies, Jobs, RagDocuments,
    InterviewSessions, InterviewQuestions, UserAnswers,
    NonverbalMetrics, AnswerAnalyses, FinalCoachings,
)

# 실제 서비스 DB(app.db)와 섞이지 않도록 테스트 전용 DB 파일을 사용합니다.
TEST_DB_PATH = "test_app.db"
if os.path.exists(TEST_DB_PATH):
    os.remove(TEST_DB_PATH)

engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)

print("=" * 60)
print("DB 틀 동작 확인 시작 (테스트 전용 DB: test_app.db)")
print("=" * 60)

with Session(engine) as session:

    # 1. USERS ------------------------------------------------------
    user = Users(email="test@example.com", password_hash="hashed_pw", name="홍길동", role="USER")
    session.add(user)
    session.commit()
    session.refresh(user)
    print(f"[1/10] USERS 생성 완료          -> user_id={user.user_id}")

    # 2. COMPANIES ----------------------------------------------------
    company = Companies(company_name="네이버", description="테스트용 기업 데이터")
    session.add(company)
    session.commit()
    session.refresh(company)
    print(f"[2/10] COMPANIES 생성 완료      -> company_id={company.company_id}")

    # 3. JOBS ----------------------------------------------------------
    job = Jobs(company_id=company.company_id, job_name="백엔드 개발자", job_category="개발")
    session.add(job)
    session.commit()
    session.refresh(job)
    print(f"[3/10] JOBS 생성 완료           -> job_id={job.job_id} (company_id={job.company_id} 참조)")

    # 4. RAG_DOCUMENTS ---------------------------------------------
    doc = RagDocuments(
        company_id=company.company_id, job_id=job.job_id,
        title="2026 채용공고", source_type="채용공고",
        content="테스트용 RAG 원문 텍스트입니다.",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    print(f"[4/10] RAG_DOCUMENTS 생성 완료  -> document_id={doc.document_id}")

    # 5. INTERVIEW_SESSIONS -----------------------------------------
    interview_session = InterviewSessions(
        user_id=user.user_id, company_id=company.company_id, job_id=job.job_id,
        interview_type="기술", status="IN_PROGRESS",
    )
    session.add(interview_session)
    session.commit()
    session.refresh(interview_session)
    print(f"[5/10] INTERVIEW_SESSIONS 생성  -> session_id={interview_session.session_id}")

    # 6. INTERVIEW_QUESTIONS -----------------------------------------
    question = InterviewQuestions(
        session_id=interview_session.session_id,
        question_type="문제해결",
        question_text="AI 모델 성능이 기대보다 낮을 때 어떤 순서로 원인을 분석하시겠습니까?",
        question_reason="직무 공개자료에서 문제해결 역량이 중요하게 나타났기 때문",
        evaluation_points=["원인 분석 순서", "메모리와 소프트웨어를 함께 보는 관점", "논리적인 설명"],
        rag_evidence=[{"source_title": "공식 JOB Report", "category": "job", "page": None, "similarity": 0.7653}],
    )
    session.add(question)
    session.commit()
    session.refresh(question)
    print(f"[6/10] INTERVIEW_QUESTIONS 생성 -> question_id={question.question_id}")

    # 7. USER_ANSWERS --------------------------------------------------
    answer = UserAnswers(
        question_id=question.question_id, user_id=user.user_id,
        stt_text="먼저 로그를 확인하고 데이터 분포를 점검하겠습니다.",
        video_path="/videos/test.mp4", audio_path="/audio/test.wav",
        duration_sec=42,
    )
    session.add(answer)
    session.commit()
    session.refresh(answer)
    print(f"[7/10] USER_ANSWERS 생성        -> answer_id={answer.answer_id}")

    # 8. NONVERBAL_METRICS (14개 측정 항목 중 일부만 테스트로 채움) --
    metrics = NonverbalMetrics(
        answer_id=answer.answer_id,
        face_yaw=3.2, gaze_center_ratio=0.81,
        pause_count=2, speaking_speed=145.0, filler_word_count=3,
        upper_body_sway=0.15, average_volume=0.6, pitch_variation=12.4,
    )
    session.add(metrics)
    session.commit()
    session.refresh(metrics)
    print(f"[8/10] NONVERBAL_METRICS 생성   -> metric_id={metrics.metric_id}")

    # 9. ANSWER_ANALYSES -------------------------------------------
    analysis = AnswerAnalyses(
        answer_id=answer.answer_id,
        job_evaluation="공개자료 기준 문제해결 접근이 체계적임",
        answer_evaluation="논리적 순서가 명확함",
        strengths="원인 분석 절차를 단계적으로 설명함",
        improvements="구체적 사례를 더 들면 좋음",
    )
    session.add(analysis)
    session.commit()
    session.refresh(analysis)
    print(f"[9/10] ANSWER_ANALYSES 생성     -> analysis_id={analysis.analysis_id}")

    # 10. FINAL_COACHINGS ---------------------------------------------
    coaching = FinalCoachings(
        session_id=interview_session.session_id,
        content_summary="문제해결 역량이 잘 드러난 답변",
        delivery_summary="발화 속도와 침묵 구간이 안정적",
        priority_focus="구체적 사례 보강",
        next_practice_goal="실제 프로젝트 경험 예시 준비",
    )
    session.add(coaching)
    session.commit()
    session.refresh(coaching)
    print(f"[10/10] FINAL_COACHINGS 생성    -> coaching_id={coaching.coaching_id}")

    print("-" * 60)
    print("관계(FK) 연결 확인: 세션 -> 질문 -> 답변 -> 비언어측정/분석 -> 코칭")
    print("-" * 60)

    # 관계를 타고 들어가서 실제로 연결되는지 확인
    saved_session = session.exec(
        select(InterviewSessions).where(InterviewSessions.session_id == interview_session.session_id)
    ).first()
    print(f"  세션 담당자: {saved_session.user.name} / 지원 기업: {saved_session.company.company_name} / 직무: {saved_session.job.job_name}")

    saved_question = saved_session.questions[0]
    print(f"  질문: {saved_question.question_text[:30]}...")

    saved_answer = saved_question.answer
    print(f"  답변(STT): {saved_answer.stt_text[:30]}...")
    print(f"  비언어 측정 - 발화속도: {saved_answer.nonverbal_metric.speaking_speed} WPM, 필러워드: {saved_answer.nonverbal_metric.filler_word_count}회")
    print(f"  내용 분석 - 강점: {saved_answer.analysis.strengths}")
    print(f"  종합 코칭 - 다음 목표: {saved_session.coaching.next_practice_goal}")

print("=" * 60)
print("✅ 전체 10개 테이블 정상 동작 확인 (생성 + 조회 + FK 관계 탐색까지 성공)")
print("=" * 60)
print(f"테스트가 끝났으니 {TEST_DB_PATH} 파일은 지워도 됩니다.")
