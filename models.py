"""
데이터베이스 모델 정의 (SQLModel)
---------------------------------
ERD의 10개 테이블을 파이썬 클래스로 그대로 옮긴 파일입니다.
SQL 문을 직접 작성하지 않아도, 아래 클래스 정의만으로
테이블 생성 / 조회 / 저장이 전부 가능합니다. (database.py 참고)
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, Relationship


# ------------------------------------------------------------------
# 1. USERS (사용자)
# ------------------------------------------------------------------
class Users(SQLModel, table=True):
    __tablename__ = "users"

    user_id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(max_length=255, unique=True, index=True)
    password_hash: str = Field(max_length=255)
    name: str = Field(max_length=50)
    role: str = Field(max_length=20, default="USER")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    sessions: List["InterviewSessions"] = Relationship(back_populates="user")
    answers: List["UserAnswers"] = Relationship(back_populates="user")
    consents: List["UserConsents"] = Relationship(back_populates="user")


# ------------------------------------------------------------------
# 2. COMPANIES (기업)
# ------------------------------------------------------------------
class Companies(SQLModel, table=True):
    __tablename__ = "companies"

    company_id: Optional[int] = Field(default=None, primary_key=True)
    company_name: str = Field(max_length=100)
    description: Optional[str] = None

    jobs: List["Jobs"] = Relationship(back_populates="company")
    rag_documents: List["RagDocuments"] = Relationship(back_populates="company")
    sessions: List["InterviewSessions"] = Relationship(back_populates="company")


# ------------------------------------------------------------------
# 3. JOBS (직무)
# ------------------------------------------------------------------
class Jobs(SQLModel, table=True):
    __tablename__ = "jobs"

    job_id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.company_id")
    job_name: str = Field(max_length=100)
    job_category: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = None

    company: Optional[Companies] = Relationship(back_populates="jobs")
    rag_documents: List["RagDocuments"] = Relationship(back_populates="job")
    sessions: List["InterviewSessions"] = Relationship(back_populates="job")


# ------------------------------------------------------------------
# 4. RAG_DOCUMENTS (근거자료)
# ------------------------------------------------------------------
class RagDocuments(SQLModel, table=True):
    __tablename__ = "rag_documents"

    document_id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.company_id")
    job_id: Optional[int] = Field(default=None, foreign_key="jobs.job_id")
    title: str = Field(max_length=200)
    source_type: str = Field(max_length=50)          # 채용공고 / JOB Report 등
    source_url: Optional[str] = Field(default=None, max_length=500)
    content: str                                       # RAG 검색 대상 원문
    created_at: datetime = Field(default_factory=datetime.utcnow)

    company: Optional[Companies] = Relationship(back_populates="rag_documents")
    job: Optional[Jobs] = Relationship(back_populates="rag_documents")


# ------------------------------------------------------------------
# 5. INTERVIEW_SESSIONS (면접 세션)
# ------------------------------------------------------------------
class InterviewSessions(SQLModel, table=True):
    __tablename__ = "interview_sessions"

    session_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id")
    company_id: int = Field(foreign_key="companies.company_id")
    job_id: int = Field(foreign_key="jobs.job_id")
    interview_type: str = Field(max_length=30)          # 인성 / 기술 등
    status: str = Field(max_length=20, default="IN_PROGRESS")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # [2026-09 추가] 반복 연습 회차 추적 (GPT 검토본 아이디어 병합).
    # SESSION_COMPARISONS(지표 비교)와는 별개로, "이 세션이 몇 회차이고
    # 어느 세션 다음인지"를 세션 자체에 직접 기록해두면 조회가 더 간단해집니다.
    # attempt_no는 라우터(create_interview_session)에서 previous_session_id가
    # 있으면 자동으로 이전 회차+1로 계산해줍니다 (수동으로 틀리게 넣을 걱정 없음).
    attempt_no: int = Field(default=1, ge=1)
    previous_session_id: Optional[int] = Field(default=None, foreign_key="interview_sessions.session_id")

    user: Optional[Users] = Relationship(back_populates="sessions")
    company: Optional[Companies] = Relationship(back_populates="sessions")
    job: Optional[Jobs] = Relationship(back_populates="sessions")
    questions: List["InterviewQuestions"] = Relationship(back_populates="session")
    coaching: Optional["FinalCoachings"] = Relationship(back_populates="session")
    technical_events: List["SessionTechnicalEvents"] = Relationship(back_populates="session")


# ------------------------------------------------------------------
# 6. INTERVIEW_QUESTIONS (질문)
# ------------------------------------------------------------------
class InterviewQuestions(SQLModel, table=True):
    __tablename__ = "interview_questions"

    question_id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="interview_sessions.session_id")
    question_type: Optional[str] = Field(default=None, max_length=30)
    question_text: str
    question_reason: Optional[str] = None

    # [결정 2026-09] AI연동규격 v0.1 "11. 교민 전달 시 확인할 것" 항목 1·2 반영.
    # RAG·언어 AI가 list[str] / list[dict] 형태로 그대로 반환하므로,
    # 문자열(str)로 받아 수동 직렬화하지 않고 JSON 컬럼으로 선언해
    # Python에서는 list/dict 그대로 넣고 꺼내 쓸 수 있게 함 (SQLite에는 TEXT로 저장되지만
    # SQLAlchemy가 자동으로 JSON 인코딩/디코딩 처리).
    evaluation_points: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    rag_evidence: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))

    # [신규 추가, 2026-09] AI연동규격 v0.1 "11. 교민 전달 시 확인할 것" 항목 4 반영.
    # 반복 맞춤 연습(REQ-009)에서 "이전 코칭 때문에 왜 이 질문을 연습하는지" 저장.
    # 최초 질문 생성 시에는 값이 없고(None), 후속 질문(follow-up) 생성 시에만 채워짐.
    # PRACTICE_RECOMMENDATIONS 테이블이 팀 합의로 확정되면 그쪽으로 옮길지 재검토 필요.
    practice_reason: Optional[str] = None

    session: Optional[InterviewSessions] = Relationship(back_populates="questions")
    answer: Optional["UserAnswers"] = Relationship(back_populates="question")


# ------------------------------------------------------------------
# 7. USER_ANSWERS (답변)
# ------------------------------------------------------------------
class UserAnswers(SQLModel, table=True):
    __tablename__ = "user_answers"

    answer_id: Optional[int] = Field(default=None, primary_key=True)
    question_id: int = Field(foreign_key="interview_questions.question_id", unique=True)
    user_id: int = Field(foreign_key="users.user_id")
    stt_text: Optional[str] = None
    video_path: Optional[str] = Field(default=None, max_length=500)
    audio_path: Optional[str] = Field(default=None, max_length=500)
    duration_sec: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    question: Optional[InterviewQuestions] = Relationship(back_populates="answer")
    user: Optional[Users] = Relationship(back_populates="answers")
    nonverbal_metric: Optional["NonverbalMetrics"] = Relationship(back_populates="answer")
    analysis: Optional["AnswerAnalyses"] = Relationship(back_populates="answer")
    events: List["NonverbalEvents"] = Relationship(back_populates="answer")


# ------------------------------------------------------------------
# 8. NONVERBAL_METRICS (비언어 측정)
# ------------------------------------------------------------------
class NonverbalMetrics(SQLModel, table=True):
    """
    비언어 평가 항목 (총 14개, MVP 활용 기준안 반영)
      핵심   : face_yaw, upper_body_sway, pause_count, speaking_speed, filler_word_count
      보조   : gaze_center_ratio, average_volume, pitch_variation
      관찰만 : smile_intensity, expression_change_count, head_nod_count, hand_gesture_rate
      평가 제외 권장(관찰값만 기록) : blink_rate
      제외(MVP 미사용, 필드만 예약) : voice_emotion_label
    """
    __tablename__ = "nonverbal_metrics"

    metric_id: Optional[int] = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="user_answers.answer_id", unique=True)

    # ---- 얼굴/시선 ----
    face_yaw: Optional[float] = None                     # 얼굴 방향 (정면 유지 비율·이탈 지속시간) - 핵심
    gaze_center_ratio: Optional[float] = None             # 시선 방향 (중앙/좌/우 비율) - 핵심·보조
    blink_rate: Optional[float] = None                    # 눈 깜빡임 빈도 (분당) - 평가 제외 권장, 관찰값만
    smile_intensity: Optional[float] = None                # 미소/표정 강도 (빈도·구간) - 관찰만
    expression_change_count: Optional[int] = None          # 표정 변화량 (변화 횟수) - 관찰만

    # ---- 자세/상체 ----
    upper_body_sway: Optional[float] = None                # 상체 움직임/흔들림 (변화량, 이전 세션 대비) - 핵심
    head_nod_count: Optional[int] = None                    # 고개 끄덕임/젓기 (횟수) - 관찰만
    hand_gesture_rate: Optional[float] = None               # 손 제스처 빈도 (분당) - 관찰만

    # ---- 음성 ----
    pause_count: Optional[int] = None                       # 침묵 시간 관련 (휴지 횟수) - 핵심
    average_volume: Optional[float] = None                  # 평균 음량 (변화량 중심) - 보조
    speaking_speed: Optional[float] = None                  # 발화 속도 (WPM/음절 초) - 핵심
    pitch_variation: Optional[float] = None                 # 음높이(피치) 변화 (표준편차) - 보조
    filler_word_count: Optional[int] = None                 # 필러워드(어/음 등) (분당 횟수) - 핵심
    voice_emotion_label: Optional[str] = None               # 음성 감정(긴장/자신감) - MVP 제외, 향후 확장용 예약 필드

    answer: Optional[UserAnswers] = Relationship(back_populates="nonverbal_metric")


# ------------------------------------------------------------------
# 9. ANSWER_ANALYSES (답변 분석)
# ------------------------------------------------------------------
class AnswerAnalyses(SQLModel, table=True):
    __tablename__ = "answer_analyses"

    analysis_id: Optional[int] = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="user_answers.answer_id", unique=True)
    job_evaluation: Optional[str] = None
    answer_evaluation: Optional[str] = None
    strengths: Optional[str] = None
    improvements: Optional[str] = None

    answer: Optional[UserAnswers] = Relationship(back_populates="analysis")


# ------------------------------------------------------------------
# 10. FINAL_COACHINGS (종합 코칭)
# ------------------------------------------------------------------
class FinalCoachings(SQLModel, table=True):
    __tablename__ = "final_coachings"

    coaching_id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="interview_sessions.session_id", unique=True)
    content_summary: Optional[str] = None
    delivery_summary: Optional[str] = None
    priority_focus: Optional[str] = None
    next_practice_goal: Optional[str] = None

    # [2026-09 추가 - 스키마만 준비, 계산 로직은 미구현]
    # GPT 검토에서 "종합 점수"가 미충족 항목으로 지적됨. 다만 점수를 몇 점
    # 만점으로 할지, 어떤 지표를 어떤 가중치로 합산할지는 팀이 아직 정하지
    # 않았으므로(다른 파트 결과를 추측해서 확정하지 않는다는 팀 규칙),
    # 필드만 nullable로 미리 만들어두고 실제 계산 함수는 만들지 않았습니다.
    # 팀이 점수 산정 기준을 정하면 이 필드에 값을 채우는 로직만 추가하면 됩니다.
    overall_score: Optional[float] = None

    session: Optional[InterviewSessions] = Relationship(back_populates="coaching")


# ------------------------------------------------------------------
# 11. NONVERBAL_EVENTS (타임스탬프 이벤트 로그)
# [2026-09 확정] models_proposed.py의 NonverbalEventsProposed에서 승격됨.
# 팀 요청 사유: "면접 영상 + 타임스탬프를 빠르게 구현해서, 최종 분석에서
# 단순 코칭 문구보다 문제 지점의 실제 영상을 보여주자."
#
# 기획서의 "00:43초에 시선이탈"처럼 정확한 시점을 저장합니다.
# NonverbalMetrics(요약 통계)와는 성격이 다릅니다.
#   - NonverbalMetrics : "총 몇 번, 평균 얼마" 같은 집계값
#   - NonverbalEvents  : "몇 초에 무슨 일이 있었는지" 하나하나의 사건
#     → answer_id + video_path(UserAnswers) + start_time_sec을 조합하면
#       Frontend가 "그 지점부터 영상 재생"을 만들 수 있습니다.
# ------------------------------------------------------------------
class NonverbalEvents(SQLModel, table=True):
    __tablename__ = "nonverbal_events"

    event_id: Optional[int] = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="user_answers.answer_id")  # 어느 답변 중 발생한 이벤트인지

    event_type: str = Field(max_length=30)
    # 예: "GAZE_AWAY"(시선 이탈), "LONG_PAUSE"(긴 침묵), "FILLER_WORD"(필러워드),
    #     "HEAD_NOD"(고개 끄덕임), "SMILE"(미소) 등
    # ⚠️ 아직 비언어 AI 담당과 정확한 값 목록을 확정하지 않았습니다.
    #    구조(테이블)는 확정이지만, event_type에 어떤 문자열이 들어올지는 계속 협의 필요.

    start_time_sec: float                              # 답변 시작 시점 기준 이벤트 발생 초 (예: 43.0 → "00:43")
    end_time_sec: Optional[float] = None                # 지속되는 이벤트면 종료 시점 (예: 시선 이탈 3초간)
    value: Optional[str] = None                          # 부가 정보 (예: 필러워드면 실제 단어, 방향이면 "좌/우" 등)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    answer: Optional[UserAnswers] = Relationship(back_populates="events")


# ------------------------------------------------------------------
# 12. SESSION_TECHNICAL_EVENTS (실시간 기술 경고 로그)
# [2026-09 확정] models_proposed.py의 SessionTechnicalEventsProposed에서 승격됨.
# 팀 요청 사유: "마이크 안 들림 / 소음 / 네트워크 문제 시 실시간 경고 필요 - 확정".
#
# 실시간 경고 자체(사용자에게 즉시 보여주는 팝업 등)는 Frontend가 처리하고,
# 이 테이블은 "나중에 다시 확인 가능한 로그" 역할입니다.
#   - NONVERBAL_EVENTS         : 시선 이탈, 침묵 등 "면접자의" 행동 이벤트
#   - SESSION_TECHNICAL_EVENTS : 마이크 문제, 소음, 네트워크 등 "환경/기기" 문제
# ------------------------------------------------------------------
class SessionTechnicalEvents(SQLModel, table=True):
    __tablename__ = "session_technical_events"

    event_id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="interview_sessions.session_id")  # 특정 답변이 아니라 세션 전체에 걸쳐 발생 가능

    event_type: str = Field(max_length=40)
    # 예: "MIC_NOT_DETECTED"(마이크 미감지), "HIGH_BACKGROUND_NOISE"(소음),
    #     "NETWORK_UNSTABLE"(네트워크 불안정), "NETWORK_DISCONNECTED"(연결 끊김)
    # ⚠️ Frontend가 실제로 감지할 수 있는 상황 기준으로 최종 값 목록 확정 필요.

    severity: Optional[str] = Field(default=None, max_length=20)  # 예: "WARNING", "CRITICAL"
    occurred_at_sec: Optional[float] = None    # 세션 시작 기준 발생 시점(초)
    message: Optional[str] = None               # 사용자에게 실제로 보여준 경고 문구 (로그/재현용)
    resolved: bool = Field(default=False)        # 이후 정상화됐는지 여부
    created_at: datetime = Field(default_factory=datetime.utcnow)

    session: Optional[InterviewSessions] = Relationship(back_populates="technical_events")


# ------------------------------------------------------------------
# 13. SESSION_COMPARISONS (1회차 vs 2회차 비교)
# [2026-09 신규] GPT 검토 "1회차 vs 2회차 비교 - 미완성" 항목 반영.
# 같은 사용자의 두 세션 간 비언어 지표 평균을 비교해 변화량을 저장합니다.
# ⚠️ "종합 점수" 비교는 FinalCoachings.overall_score가 실제로 채워지기
#    시작한 뒤에나 의미가 있습니다 (그 전까진 지표 비교만 가능).
# ------------------------------------------------------------------
class SessionComparisons(SQLModel, table=True):
    __tablename__ = "session_comparisons"

    comparison_id: Optional[int] = Field(default=None, primary_key=True)
    first_session_id: int = Field(foreign_key="interview_sessions.session_id")
    second_session_id: int = Field(foreign_key="interview_sessions.session_id")

    first_overall_score: Optional[float] = None   # FinalCoachings.overall_score가 있으면 복사
    second_overall_score: Optional[float] = None
    score_change: Optional[float] = None

    improved_items: Optional[str] = None           # 지표별 변화 요약 텍스트 (예: "speaking_speed: 125.0 -> 140.0 (+15.0)")
    remaining_weaknesses: Optional[str] = None      # 2회차에도 여전히 부족한 부분 (아직 자동 계산 로직 없음, 수동/AI 입력용)
    comparison_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ------------------------------------------------------------------
# 14. USER_CONSENTS (개인정보 동의)
# [2026-09 확정] REQ-010, "개인정보 동의 코드 확정" 요청으로 승격.
# 영상 저장 동의 / 분석(AI 처리) 동의 / 데이터 보유기간 / 동의 철회까지 포함합니다.
#
# consent_type 종류 (Frontend가 실제 동의 화면에서 체크박스별로 하나씩 보냄):
#   - "VIDEO_RECORDING"  : 면접 영상 저장에 대한 동의
#   - "AUDIO_RECORDING"  : 면접 음성 저장에 대한 동의
#   - "ANALYSIS"         : STT·비언어·AI 분석에 활용하는 것에 대한 동의
#   - "DATA_RETENTION"   : 위 데이터를 retention_days 기간 동안 보관하는 것에 대한 동의
#
# retention_days/retention_until: "보유기간"을 저장 시점 값으로 고정합니다.
# (나중에 정책이 바뀌어도 이미 받은 동의의 보유기간이 소급 변경되지 않도록,
#  요청 시점의 일수를 그대로 저장하고 만료 시각을 미리 계산해둡니다.)
# ------------------------------------------------------------------
class UserConsents(SQLModel, table=True):
    __tablename__ = "user_consents"

    consent_id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.user_id")
    session_id: Optional[int] = Field(default=None, foreign_key="interview_sessions.session_id")  # 세션 단위 동의면 사용, 계정 단위면 비움

    consent_type: str = Field(max_length=30)
    is_agreed: bool = Field(default=False)
    consented_at: datetime = Field(default_factory=datetime.utcnow)

    retention_days: Optional[int] = None            # 보유기간 (예: 365) - 동의 시점 정책 스냅샷
    retention_until: Optional[datetime] = None       # consented_at + retention_days로 자동 계산되어 저장됨

    revoked_at: Optional[datetime] = None            # 동의 철회 시각 (철회 전이면 None)
    media_deleted: bool = Field(default=False)        # 보유기간 만료/철회로 실제 파일까지 삭제했는지
    media_deleted_at: Optional[datetime] = None

    user: Optional[Users] = Relationship(back_populates="consents")
