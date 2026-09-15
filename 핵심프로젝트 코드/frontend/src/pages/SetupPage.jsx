import { useEffect, useState } from "react";
import { Building2, Briefcase, Mic2, Lightbulb, Rocket } from "lucide-react";
import {
  listCompanies,
  listJobsByCompany,
  createInterviewSession,
  generateQuestions,
  ApiError,
} from "../api.js";

// rag_ai/rag_ai_service.py의 INTERVIEW_TYPES = ('AISK', 'DEEP_INTERVIEW')와
// 정확히 일치해야 합니다.
const INTERVIEW_TYPES = [
  { value: "AISK", label: "A!SK 영상면접 (직무이해·문제해결·협업 3문항)" },
  { value: "DEEP_INTERVIEW", label: "심층면접 (첫 질문 + 답변 기반 꼬리질문 최대 3회)" },
];

export default function SetupPage({ user, onReady }) {
  const [companies, setCompanies] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [companyId, setCompanyId] = useState("");
  const [jobId, setJobId] = useState("");
  const [interviewType, setInterviewType] = useState(INTERVIEW_TYPES[0].value);

  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    listCompanies()
      .then((list) => {
        setCompanies(list);
        if (list.length) setCompanyId(String(list[0].company_id));
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingCompanies(false));
  }, []);

  useEffect(() => {
    if (!companyId) {
      setJobs([]);
      setJobId("");
      return;
    }
    setLoadingJobs(true);
    listJobsByCompany(companyId)
      .then((list) => {
        setJobs(list);
        setJobId(list.length ? String(list[0].job_id) : "");
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoadingJobs(false));
  }, [companyId]);

  async function handleStart(e) {
    e.preventDefault();
    if (!companyId || !jobId) return;
    setSubmitting(true);
    setError(null);
    try {
      const session = await createInterviewSession({
        user_id: user.user_id,
        company_id: Number(companyId),
        job_id: Number(jobId),
        interview_type: interviewType,
      });
      const questions = await generateQuestions(session.session_id);
      const company = companies.find((c) => c.company_id === Number(companyId));
      const job = jobs.find((j) => j.job_id === Number(jobId));
      onReady({
        session: { ...session, companyName: company?.company_name, jobName: job?.job_name },
        questions,
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(
          "AI 서비스가 아직 준비되지 않았습니다. 백엔드 .env의 OPENAI_API_KEY / RAG_DATA_DIR 설정을 확인해주세요."
        );
      } else {
        setError(err.message || "면접 세션을 시작하지 못했습니다.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="main">
      <h1>AI 모의면접 맞춤 설정</h1>
      <p className="lede">지원하실 기업·직무와 면접 유형을 선택해주세요.</p>

      <form onSubmit={handleStart} className="panel">
        <div className="setup-grid">
          <div>
            <div className="field">
              <label htmlFor="company" className="icon-label">
                <Building2 size={15} /> 지원 기업
              </label>
              {loadingCompanies ? (
                <p style={{ fontSize: 13.5 }}>불러오는 중…</p>
              ) : companies.length === 0 ? (
                <div className="notice notice-info">
                  등록된 기업이 없습니다. 백엔드 담당자에게 기업·직무 데이터 등록을 요청해주세요.
                </div>
              ) : (
                <select id="company" value={companyId} onChange={(e) => setCompanyId(e.target.value)}>
                  {companies.map((c) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.company_name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div className="field">
              <label htmlFor="job" className="icon-label">
                <Briefcase size={15} /> 지원 직무
              </label>
              {loadingJobs ? (
                <p style={{ fontSize: 13.5 }}>불러오는 중…</p>
              ) : jobs.length === 0 ? (
                <div className="notice notice-info">
                  이 기업에 등록된 직무가 없습니다. 백엔드 담당자에게 직무 데이터 등록을 요청해주세요.
                </div>
              ) : (
                <select id="job" value={jobId} onChange={(e) => setJobId(e.target.value)}>
                  {jobs.map((j) => (
                    <option key={j.job_id} value={j.job_id}>
                      {j.job_name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          <div>
            <div className="field">
              <label htmlFor="interviewType" className="icon-label">
                <Mic2 size={15} /> 면접 유형
              </label>
              <select
                id="interviewType"
                value={interviewType}
                onChange={(e) => setInterviewType(e.target.value)}
              >
                {INTERVIEW_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="notice notice-info" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Lightbulb size={15} /> 현재 카메라·마이크 권한은 답변 녹화 직전에 확인합니다. 캘리브레이션 화면은 다음 통합 단계에서 연결합니다.
            </div>
          </div>
        </div>

        {error && <div className="notice notice-error">{error}</div>}

        <button
          className="btn btn-primary btn-block"
          type="submit"
          disabled={submitting || !companyId || !jobId}
          style={{ marginTop: 8 }}
        >
          {submitting && <span className="spinner" />}
          <Rocket size={16} /> 면접 시작하기
        </button>
      </form>
    </div>
  );
}
