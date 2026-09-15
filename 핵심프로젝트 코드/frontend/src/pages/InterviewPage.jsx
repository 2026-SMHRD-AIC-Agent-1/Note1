import { useEffect, useState } from "react";
import {
  Volume2,
  HelpCircle,
  CheckCircle2,
  Send,
  FileText,
  RotateCcw,
  AlertTriangle,
  MessageCircleMore,
} from "lucide-react";
import Recorder from "../components/Recorder.jsx";
import {
  submitAnswer,
  analyzeAnswer,
  listAnswerAnalyses,
  generateCoaching,
  generateDeepFollowup,
  ApiError,
} from "../api.js";

const SPEECH_SUPPORTED = typeof window !== "undefined" && "speechSynthesis" in window;
const DEEP_MAX_FOLLOWUPS = 3;

export default function InterviewPage({ user, session, questions, onFinish }) {
  const [interviewQuestions, setInterviewQuestions] = useState(questions);
  const [index, setIndex] = useState(0);
  const [recorded, setRecorded] = useState(null);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [generatingFollowup, setGeneratingFollowup] = useState(false);
  const [error, setError] = useState(null);
  const [recorderKey, setRecorderKey] = useState(0);
  const [speaking, setSpeaking] = useState(false);

  const question = interviewQuestions[index];
  const isDeep = session.interview_type === "DEEP_INTERVIEW";
  const isLast = index === interviewQuestions.length - 1;
  const deepFollowupCount = isDeep ? Math.max(0, interviewQuestions.length - 1) : 0;
  const canGenerateDeepFollowup = isDeep && isLast && deepFollowupCount < DEEP_MAX_FOLLOWUPS;
  const currentAnswer = question ? answers[question.question_id] : null;
  const alreadyAnswered = Boolean(currentAnswer);
  const needsRetake = Boolean(
    currentAnswer?.delivery_analysis?.delivery_profile?.measurement?.retake_recommended
  );

  // 새 세션으로 바뀌면 심층면접에서 동적으로 추가했던 질문/답변 상태도 초기화합니다.
  useEffect(() => {
    setInterviewQuestions(questions);
    setIndex(0);
    setAnswers({});
    setRecorded(null);
    setError(null);
    setRecorderKey((k) => k + 1);
  }, [session.session_id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!question) return;
    if (SPEECH_SUPPORTED) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [question?.question_id]);

  useEffect(() => {
    return () => {
      if (SPEECH_SUPPORTED) window.speechSynthesis.cancel();
    };
  }, []);

  if (!question) {
    return (
      <div className="main" style={{ maxWidth: 900 }}>
        <div className="notice notice-error">면접 질문을 불러오지 못했습니다.</div>
      </div>
    );
  }

  function handleSpeakQuestion() {
    if (!SPEECH_SUPPORTED) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(question.question_text);
    utterance.lang = "ko-KR";
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  }

  async function handleSubmitAnswer() {
    if (!recorded) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitAnswer({
        session_id: session.session_id,
        question_id: question.question_id,
        user_id: user.user_id,
        audioBlob: recorded.audioBlob,
        videoBlob: recorded.videoBlob,
        durationSec: recorded.durationSec,
      });

      let analysis = null;
      let note = result.note;
      if (result.analysis_id) {
        const all = await listAnswerAnalyses();
        analysis = all.find((a) => a.analysis_id === result.analysis_id) || null;
      } else if (result.analysis_retry_allowed !== false) {
        try {
          analysis = await analyzeAnswer(result.answer_id);
          note = null;
        } catch (retryErr) {
          note = note || (retryErr instanceof ApiError ? retryErr.detail : retryErr.message);
        }
      }

      setAnswers((prev) => ({
        ...prev,
        [question.question_id]: {
          answer_id: result.answer_id,
          stt_text: result.stt_text,
          analysis,
          stt_stability: result.stt_stability || null,
          delivery_analysis: result.delivery_analysis || null,
          note,
        },
      }));
      setRecorded(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError(
          "AI 서비스가 아직 준비되지 않았습니다. 백엔드 .env의 OPENAI_API_KEY 설정을 확인해주세요."
        );
      } else if (err instanceof ApiError && err.status === 403) {
        setError(`제출할 수 없습니다: ${err.detail}`);
      } else if (err instanceof ApiError && err.status === 502) {
        setError(`답변 처리에 실패했습니다: ${err.detail}`);
      } else {
        setError(err.message || "답변 제출에 실패했습니다.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleRetake() {
    setAnswers((prev) => {
      const next = { ...prev };
      delete next[question.question_id];
      return next;
    });
    setRecorded(null);
    setError(null);
    setRecorderKey((k) => k + 1);
  }

  function handleNext() {
    setRecorded(null);
    setError(null);
    setRecorderKey((k) => k + 1);
    setIndex((i) => i + 1);
  }

  async function handleDeepFollowup() {
    if (!canGenerateDeepFollowup) return;
    setGeneratingFollowup(true);
    setError(null);
    try {
      const nextQuestion = await generateDeepFollowup(
        session.session_id,
        question.question_id
      );
      const nextIndex = interviewQuestions.length;
      setInterviewQuestions((prev) => [...prev, nextQuestion]);
      setRecorded(null);
      setRecorderKey((k) => k + 1);
      setIndex(nextIndex);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail || err.message || "꼬리질문 생성에 실패했습니다.");
      } else {
        setError(err.message || "꼬리질문 생성에 실패했습니다.");
      }
    } finally {
      setGeneratingFollowup(false);
    }
  }

  async function handleFinish() {
    setFinishing(true);
    setError(null);
    try {
      const coaching = await generateCoaching(session.session_id);
      onFinish({ questions: interviewQuestions, answers, coaching });
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError(`아직 모든 질문의 답변·분석이 끝나지 않았습니다: ${err.detail}`);
      } else {
        setError(err.message || "종합 코칭 생성에 실패했습니다.");
      }
    } finally {
      setFinishing(false);
    }
  }

  const questionProgressLabel = isDeep
    ? index === 0
      ? `첫 질문 · 최대 ${DEEP_MAX_FOLLOWUPS}회 꼬리질문`
      : `꼬리질문 ${index} / ${DEEP_MAX_FOLLOWUPS}`
    : `질문 ${index + 1} / ${interviewQuestions.length}`;

  return (
    <div className="main" style={{ maxWidth: 900, paddingTop: 24, paddingBottom: 24 }}>
      <div className="eyebrow">{session.companyName} · {session.jobName} · {session.interview_type}</div>

      <div className="interview-grid">
        <div className="panel panel-compact">
          <div
            className="tag"
            style={{ marginBottom: 10, display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <HelpCircle size={13} />
            {questionProgressLabel}
            {question.question_type ? ` · ${question.question_type}` : ""}
          </div>
          <h3 className="q-text" style={{ fontSize: 16 }}>{question.question_text}</h3>

          {SPEECH_SUPPORTED && (
            <button
              type="button"
              className="btn btn-ghost"
              style={{ marginBottom: 6, fontSize: 12.5, padding: "6px 14px" }}
              onClick={handleSpeakQuestion}
            >
              <Volume2 size={13} /> {speaking ? "재생 중…" : "질문 다시 듣기"}
            </button>
          )}

          {question.evaluation_points?.length > 0 && (
            <details className="reason" open style={{ marginTop: 6 }}>
              <summary>핵심 평가 포인트</summary>
              <ul className="q-points" style={{ marginTop: 6 }}>
                {question.evaluation_points.map((p, i) => (
                  <li key={i} style={{ padding: "3px 0 3px 18px", fontSize: 13 }}>{p}</li>
                ))}
              </ul>
            </details>
          )}

          {question.question_reason && (
            <details className="reason">
              <summary>이 질문을 왜 받았나요?</summary>
              <p style={{ marginTop: 6, fontSize: 13 }}>{question.question_reason}</p>
            </details>
          )}

          {question.practice_reason && (
            <div className="notice notice-info" style={{ marginTop: 10, fontSize: 12.5, padding: "8px 12px" }}>
              {isDeep ? "꼬리질문 이유" : "이전 회차 코칭 반영"}: {question.practice_reason}
            </div>
          )}
        </div>

        <div>
          {!alreadyAnswered ? (
            <>
              <Recorder
                key={recorderKey}
                disabled={submitting}
                onRecorded={(payload) => setRecorded(payload)}
              />

              {error && <div className="notice notice-error">{error}</div>}

              <button
                className="btn btn-primary btn-block"
                disabled={!recorded || submitting}
                onClick={handleSubmitAnswer}
              >
                {submitting && <span className="spinner" />}
                <Send size={15} /> 답변 제출
              </button>
            </>
          ) : (
            <div className="panel panel-compact">
              <div className="panel-title" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14.5 }}>
                <CheckCircle2 size={16} color="var(--green)" /> 답변 저장 완료
              </div>
              <p style={{ fontSize: 13, display: "flex", gap: 6 }}>
                <FileText size={14} style={{ flexShrink: 0, marginTop: 2 }} />
                <span><strong>내 답변:</strong> {currentAnswer.stt_text}</span>
              </p>

              {currentAnswer.analysis ? (
                <p style={{ fontSize: 13 }}>
                  <span className="tag">직무 관점: {currentAnswer.analysis.job_evaluation}</span>
                  <span className="tag">답변 구성: {currentAnswer.analysis.answer_evaluation}</span>
                </p>
              ) : (
                <div className="notice notice-info" style={{ fontSize: 12.5 }}>
                  {currentAnswer.note || "이 답변의 분석 결과가 아직 없습니다."}
                </div>
              )}

              {needsRetake ? (
                <>
                  <div className="notice notice-error" style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                    <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
                    <span>
                      마이크 입력이나 주변 소음 때문에 이 답변을 안정적으로 분석하기 어렵습니다.
                      점수로 처리하지 않고 다시 녹화하는 것이 좋습니다.
                    </span>
                  </div>
                  <button className="btn btn-primary btn-block" onClick={handleRetake}>
                    <RotateCcw size={15} /> 이 질문 다시 녹화하기
                  </button>
                </>
              ) : canGenerateDeepFollowup ? (
                <button
                  className="btn btn-primary btn-block"
                  onClick={handleDeepFollowup}
                  disabled={generatingFollowup}
                >
                  {generatingFollowup && <span className="spinner" />}
                  <MessageCircleMore size={15} />
                  답변을 바탕으로 꼬리질문 받기 ({deepFollowupCount + 1}/{DEEP_MAX_FOLLOWUPS})
                </button>
              ) : !isLast ? (
                <button className="btn btn-primary btn-block" onClick={handleNext}>
                  다음 질문으로
                </button>
              ) : (
                <button className="btn btn-primary btn-block" onClick={handleFinish} disabled={finishing}>
                  {finishing && <span className="spinner" />}
                  답변 완료 및 최종 리포트 보기
                </button>
              )}
              {error && <div className="notice notice-error" style={{ marginTop: 10 }}>{error}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
