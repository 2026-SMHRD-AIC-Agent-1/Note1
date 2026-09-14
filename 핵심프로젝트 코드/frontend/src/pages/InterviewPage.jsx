import { useEffect, useState } from "react";
import { Volume2, HelpCircle, CheckCircle2, Send, FileText } from "lucide-react";
import Recorder from "../components/Recorder.jsx";
import { submitAnswer, analyzeAnswer, listAnswerAnalyses, generateCoaching, ApiError } from "../api.js";

const SPEECH_SUPPORTED = typeof window !== "undefined" && "speechSynthesis" in window;

export default function InterviewPage({ user, session, questions, onFinish }) {
  const [index, setIndex] = useState(0);
  const [recorded, setRecorded] = useState(null); // { audioBlob, videoBlob }
  const [answers, setAnswers] = useState({}); // question_id -> { answer_id, stt_text, analysis, note }
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [error, setError] = useState(null);
  const [recorderKey, setRecorderKey] = useState(0); // Recorder 재마운트용
  const [speaking, setSpeaking] = useState(false);

  const question = questions[index];
  const isLast = index === questions.length - 1;
  const alreadyAnswered = Boolean(answers[question.question_id]);

  // 질문이 바뀌면 이전 질문을 읽던 음성은 멈춥니다.
  useEffect(() => {
    if (SPEECH_SUPPORTED) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [question.question_id]);

  useEffect(() => {
    return () => {
      if (SPEECH_SUPPORTED) window.speechSynthesis.cancel();
    };
  }, []);

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
      // uploads.py는 이제 {answer_id, stt_text, analysis_id, note}만 돌려줍니다
      // (분석 전체 내용은 따로 조회해야 함). analysis_id가 없으면(예: 업로드 시점에
      // AI가 아직 준비 안 됐던 경우) 여기서 한 번 더 분석을 시도합니다.
      let analysis = null;
      let note = result.note;
      if (result.analysis_id) {
        const all = await listAnswerAnalyses();
        analysis = all.find((a) => a.analysis_id === result.analysis_id) || null;
      } else {
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

  function handleNext() {
    setRecorded(null);
    setError(null);
    setRecorderKey((k) => k + 1);
    setIndex((i) => i + 1);
  }

  async function handleFinish() {
    setFinishing(true);
    setError(null);
    try {
      const coaching = await generateCoaching(session.session_id);
      onFinish({ questions, answers, coaching });
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
            질문 {index + 1} / {questions.length}
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
              이전 회차 코칭 반영: {question.practice_reason}
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
                <span><strong>내 답변:</strong> {answers[question.question_id].stt_text}</span>
              </p>
              {answers[question.question_id].analysis ? (
                <p style={{ fontSize: 13 }}>
                  <span className="tag">
                    직무 관점: {answers[question.question_id].analysis.job_evaluation}
                  </span>
                  <span className="tag">
                    답변 구성: {answers[question.question_id].analysis.answer_evaluation}
                  </span>
                </p>
              ) : (
                <div className="notice notice-info" style={{ fontSize: 12.5 }}>
                  {answers[question.question_id].note || "이 답변의 분석 결과가 아직 없습니다."}
                </div>
              )}

              {!isLast ? (
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
