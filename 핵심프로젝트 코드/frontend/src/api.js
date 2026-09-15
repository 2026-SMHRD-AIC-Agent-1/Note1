// 백엔드(FastAPI) 호출을 모아둔 얇은 API 클라이언트.
// 여기 있는 경로/파라미터는 전부 실제 backend/routers/*.py, ai_pipeline.py,
// uploads.py, session_comparisons.py, session_technical_events.py, consents.py에
// 정의된 엔드포인트를 그대로 따릅니다 (백엔드 최신버전 기준). 존재하지 않는
// 엔드포인트는 만들지 않았습니다.

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, options);
  if (!res.ok) {
    let detail = null;
    try {
      const body = await res.json();
      detail = body.detail;
    } catch {
      // 응답 본문이 JSON이 아닐 수 있음
    }
    throw new ApiError(
      detail || `요청이 실패했습니다 (HTTP ${res.status})`,
      res.status,
      detail
    );
  }
  if (res.status === 204) return null;
  return res.json();
}

function postJson(path, body) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------
// USERS / CONSENTS
// ---------------------------------------------------------------
export function createUser({ email, password_hash, name }) {
  return postJson("/users", { email, password_hash, name });
}

export function listUsers() {
  return request("/users");
}

export function createConsent({ user_id, consent_type, is_agreed, policy_version }) {
  return postJson("/consents", { user_id, consent_type, is_agreed, policy_version });
}

// ---------------------------------------------------------------
// COMPANIES / JOBS
// ---------------------------------------------------------------
export function listCompanies() {
  return request("/companies");
}

export function listJobsByCompany(companyId) {
  return request(`/companies/${companyId}/jobs`);
}

// ---------------------------------------------------------------
// INTERVIEW SESSIONS / QUESTIONS
// ---------------------------------------------------------------
export function createInterviewSession({ user_id, company_id, job_id, interview_type, previous_session_id }) {
  return postJson("/interview-sessions", {
    user_id,
    company_id,
    job_id,
    interview_type,
    previous_session_id: previous_session_id ?? null,
  });
}

export function getInterviewSession(sessionId) {
  return request(`/interview-sessions/${sessionId}`);
}

export function getSessionCoaching(sessionId) {
  return request(`/interview-sessions/${sessionId}/coaching`);
}

export function listQuestionsBySession(sessionId) {
  return request(`/interview-sessions/${sessionId}/questions`);
}

// ---------------------------------------------------------------
// AI 파이프라인 (RAG·언어 AI)
// ---------------------------------------------------------------
export function generateQuestions(sessionId) {
  return postJson(`/ai/sessions/${sessionId}/generate-questions`, {});
}

export function generateCoaching(sessionId) {
  return postJson(`/ai/sessions/${sessionId}/generate-coaching`, {});
}

// 심층면접: 같은 세션 안에서 직전 답변을 보고 꼬리질문을 1개 생성합니다.
// 백엔드가 최대 3회 제한과 "가장 최근 질문에서만 생성" 규칙을 관리합니다.
export function generateDeepFollowup(sessionId, questionId) {
  return postJson(
    `/ai/sessions/${sessionId}/generate-deep-followup?question_id=${questionId}`,
    {}
  );
}

// 저장된 답변을 (다시) 분석합니다. uploads.py의 /user-answers/submit이 업로드 시점에
// 자동으로 분석까지 시도하지만, 그때 AI가 준비 안 돼 있었을 경우 이 엔드포인트로
// 나중에 다시 시도할 수 있습니다.
export function analyzeAnswer(answerId) {
  return postJson(`/ai/user-answers/${answerId}/analyze`, {});
}

// 1회차 코칭(우선 개선점·다음 목표)을 반영한 "다음 회차" 연습 질문 생성.
// 같은 심층면접 세션 안의 꼬리질문(generateDeepFollowup)과는 다른 기능입니다.
export function generateFollowupQuestion(nextSessionId, previousSessionId) {
  return postJson(
    `/ai/sessions/${nextSessionId}/generate-followup-question?previous_session_id=${previousSessionId}`,
    {}
  );
}

// ---------------------------------------------------------------
// 답변 제출 (녹화 파일 업로드 -> STT -> 분석)
// ---------------------------------------------------------------
export async function submitAnswer({ session_id, question_id, user_id, audioBlob, videoBlob, durationSec }) {
  const form = new FormData();
  form.append("session_id", String(session_id));
  form.append("question_id", String(question_id));
  form.append("user_id", String(user_id));
  form.append("audio", audioBlob, "answer-audio.webm");
  if (videoBlob) {
    form.append("video", videoBlob, "answer-video.webm");
  }
  if (durationSec !== undefined && durationSec !== null) {
    form.append("duration_sec", String(durationSec));
  }
  return request("/user-answers/submit", { method: "POST", body: form });
}

export function getAnswerEvents(answerId) {
  return request(`/user-answers/${answerId}/events`);
}

export function getAnswerVideoUrl(answerId) {
  return `${API_BASE}/user-answers/${answerId}/video`;
}

export function listNonverbalMetrics() {
  return request("/nonverbal-metrics");
}

export function listAnswerAnalyses() {
  return request("/answer-analyses");
}

export function listUserAnswers() {
  return request("/user-answers");
}

// ---------------------------------------------------------------
// 회차 비교 (SESSION_COMPARISONS)
// ---------------------------------------------------------------
export function createSessionComparison({ first_session_id, second_session_id }) {
  return postJson("/session-comparisons", { first_session_id, second_session_id });
}

// ---------------------------------------------------------------
// 기술 경고 로그 (마이크/소음/네트워크)
// ---------------------------------------------------------------
export function createSessionTechnicalEvent({ session_id, event_type, severity, occurred_at_sec, message }) {
  return postJson("/session-technical-events", { session_id, event_type, severity, occurred_at_sec, message });
}

// ---------------------------------------------------------------
// 헬스체크
// ---------------------------------------------------------------
export function health() {
  return request("/health");
}

export { ApiError };
