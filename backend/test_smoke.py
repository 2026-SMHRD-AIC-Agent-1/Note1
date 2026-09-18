"""MVP DB smoke test.

실행:
    python test_smoke.py
    pytest -q test_smoke.py

실서비스 app.db와 분리된 test_app.db를 사용합니다.
현재 models.py의 14개 테이블을 기준으로 관계와 핵심 점수/동의 필드를 확인합니다.
"""
import os
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Users, Companies, Jobs, RagDocuments,
    InterviewSessions, InterviewQuestions, UserAnswers,
    NonverbalMetrics, AnswerAnalyses, FinalCoachings,
    NonverbalEvents, SessionTechnicalEvents, SessionComparisons, UserConsents,
)

TEST_DB_PATH = "test_app.db"


def build_test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    engine = create_engine(f"sqlite:///{TEST_DB_PATH}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def run_smoke_test():
    engine = build_test_db()
    with Session(engine) as session:
        user = Users(email="test@example.com", password_hash="hashed_pw", name="홍길동", role="USER")
        company = Companies(company_name="네이버", description="테스트용 기업 데이터")
        session.add_all([user, company])
        session.commit()
        session.refresh(user); session.refresh(company)

        job = Jobs(company_id=company.company_id, job_name="백엔드 개발자", job_category="개발")
        session.add(job); session.commit(); session.refresh(job)

        doc = RagDocuments(company_id=company.company_id, job_id=job.job_id,
                           title="2026 채용공고", source_type="채용공고",
                           content="테스트용 RAG 원문 텍스트입니다.")
        session.add(doc); session.commit(); session.refresh(doc)

        interview_session = InterviewSessions(
            user_id=user.user_id, company_id=company.company_id, job_id=job.job_id,
            interview_type="기술", status="IN_PROGRESS", attempt_no=1,
        )
        session.add(interview_session); session.commit(); session.refresh(interview_session)

        question = InterviewQuestions(
            session_id=interview_session.session_id,
            question_type="문제해결",
            question_text="AI 모델 성능이 기대보다 낮을 때 어떤 순서로 원인을 분석하시겠습니까?",
            question_reason="직무 공개자료에서 문제해결 역량이 중요하기 때문",
            evaluation_points=["원인 분석 순서", "기술적 근거", "논리적인 설명"],
            rag_evidence=[{"source_title": "공식 JOB Report", "similarity": 0.7653}],
        )
        session.add(question); session.commit(); session.refresh(question)

        answer = UserAnswers(
            question_id=question.question_id, user_id=user.user_id,
            stt_text="먼저 로그를 확인하고 데이터 분포를 점검하겠습니다.",
            video_path="/videos/test.mp4", audio_path="/audio/test.wav", duration_sec=42,
        )
        session.add(answer); session.commit(); session.refresh(answer)

        metrics = NonverbalMetrics(
            answer_id=answer.answer_id, face_yaw=3.2, gaze_center_ratio=0.81,
            pause_count=2, speaking_speed=145.0, filler_word_count=3,
            upper_body_sway=0.15, average_volume=0.6, pitch_variation=12.4,
        )
        session.add(metrics)

        analysis = AnswerAnalyses(
            answer_id=answer.answer_id,
            job_evaluation="공개자료 기준 문제해결 접근이 체계적임",
            answer_evaluation="논리적 순서가 명확함",
            strengths="원인 분석 절차를 단계적으로 설명함",
            improvements="구체적 사례를 더 들면 좋음",
            job_score=82.0, answer_score=78.0, scoring_version="v8_answer_base95_excellence5",
        )
        session.add(analysis)

        coaching = FinalCoachings(
            session_id=interview_session.session_id,
            content_summary="문제해결 역량이 잘 드러난 답변",
            delivery_summary="답변 구성이 안정적",
            priority_focus="구체적 사례 보강",
            next_practice_goal="실제 프로젝트 경험 예시 준비",
            overall_score=80.0,
        )
        session.add(coaching)

        consent = UserConsents(
            user_id=user.user_id, consent_type="ANALYSIS", is_agreed=True,
        )
        session.add(consent)

        event = NonverbalEvents(answer_id=answer.answer_id, event_type="GAZE_AWAY", start_time_sec=1.5, end_time_sec=2.0)
        session.add(event)
        tech = SessionTechnicalEvents(session_id=interview_session.session_id, event_type="MIC_NOT_DETECTED", severity="WARNING", occurred_at_sec=0.0, message="테스트 경고")
        session.add(tech)
        session.commit()

        comparison = SessionComparisons(
            first_session_id=interview_session.session_id,
            second_session_id=interview_session.session_id,
            first_overall_score=80.0,
            second_overall_score=80.0,
        )
        session.add(comparison)
        session.commit()

        # 관계와 핵심 필드 검증
        saved = session.get(InterviewSessions, interview_session.session_id)
        assert saved is not None
        assert saved.questions[0].answer.stt_text.startswith("먼저 로그")
        assert saved.questions[0].answer.analysis.job_score == 82.0
        assert saved.coaching.overall_score == 80.0
        assert session.exec(select(UserConsents).where(UserConsents.user_id == user.user_id)).first() is not None
        assert session.exec(select(RagDocuments)).first().job_id == job.job_id
        assert session.exec(select(SessionComparisons)).first().first_overall_score == 80.0

    return True


def main():
    run_smoke_test()
    print("✅ 현재 14개 테이블 생성/관계/핵심 점수·동의 필드 확인 성공")
    print(f"테스트 DB: {TEST_DB_PATH} (필요하면 삭제해도 됩니다.)")


def test_smoke():
    assert run_smoke_test() is True


if __name__ == "__main__":
    main()
