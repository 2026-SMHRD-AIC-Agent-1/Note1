import { useEffect, useRef, useState } from "react";
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
  fetchQuestionSpeech,
  ApiError,
} from "../api.js";

const BROWSER_SPEECH_SUPPORTED = typeof window !== "undefined" && "speechSynthesis" in window;
const DEEP_MAX_FOLLOWUPS = 3;

export default function InterviewPage({ user, session, questions, onFinish }) {
  const [interviewQuestions, setInterviewQuestions] = useState(questions);
  const [index, setIndex] = useState(0);
  const [recorded, setRecorded] = useState(null);
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [generatingFollowup, setGeneratingFollowup] = useState(false);

  // 답변 제출/분석, 종합 코칭 생성, 꼬리질문 생성 중에는 새로고침·탭 닫기를 시도하면
  // 브라우저 자체 경고창이 뜨도록 한다(안내 문구만으로는 놓칠 수 있어서).
  const isBusy = submitting || finishing || generatingFollowup;
  useEffect(() => {
    if (!isBusy) return;
    const handler = (e) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isBusy]);
  const [error, setError] = useState(null);
  const [recorderKey, setRecorderKey] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [speechLoading, setSpeechLoading] = useState(false);
  const audioRef = useRef(null);
  const audioUrlRef = useRef(null);

  function stopSpeaking() {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    if (BROWSER_SPEECH_SUPPORTED) window.speechSynthesis.cancel();
    setSpeaking(false);
    setSpeechLoading(false);
  }

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
    stopSpeaking();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question?.question_id]);

  useEffect(() => {
    return () => stopSpeaking();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!question) {
    return (
      <div className="main" style={{ maxWidth: 900 }}>
        <div className="notice notice-error">면접 질문을 불러오지 못했습니다.</div>
      </div>
    );
  }

  // 브라우저 내장 TTS(기계음에 가까움)로 읽어주는 폴백. 서버 TTS(OpenAI)가
  // 실패했을 때만(키 미설정, 네트워크 오류 등) 사용한다.
  function speakWithBrowserFallback() {
    if (!BROWSER_SPEECH_SUPPORTED) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(question.question_text);
    utterance.lang = "ko-KR";
    utterance.onstart = () => setSpeaking(true);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
  }

  async function handleSpeakQuestion() {
    stopSpeaking();
    setSpeechLoading(true);
    try {
      // 1순위: 서버(OpenAI TTS)에서 자연스러운 음성을 받아온다.
      const url = await fetchQuestionSpeech(question.question_text);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onplay = () => {
        setSpeechLoading(false);
        setSpeaking(true);
      };
      audio.onended = () => {
        setSpeaking(false);
        if (audioUrlRef.current) {
          URL.revokeObjectURL(audioUrlRef.current);
          audioUrlRef.current = null;
        }
      };
      audio.onerror = () => {
        setSpeaking(false);
        setSpeechLoading(false);
        speakWithBrowserFallback();
      };
      await audio.play();
    } catch {
      // 2순위: 서버 TTS를 쓸 수 없으면(설정 안 됨 등) 브라우저 TTS로 폴백.
      setSpeechLoading(false);
      speakWithBrowserFallback();
    }
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

          <button
            type="button"
            className="btn btn-ghost"
            style={{ marginBottom: 6, fontSize: 12.5, padding: "6px 14px" }}
            onClick={handleSpeakQuestion}
            disabled={speechLoading}
          >
            <Volume2 size={13} />{" "}
            {speechLoading ? "음성 준비 중…" : speaking ? "재생 중…" : "질문 다시 듣기"}
          </button>

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

              {submitting && (
                <div className="notice notice-info" style={{ marginTop: 10, fontSize: 13 }}>
                  <strong>답변 분석 중입니다.</strong> STT·내용 평가·비언어 분석을 순서대로 처리하고
                  있어 시간이 조금 걸릴 수 있어요. <strong>완료될 때까지 새로고침하거나 다른 페이지로
                  이동하지 말고 잠시만 기다려주세요.</strong> 중간에 창을 닫으면 이번 답변이 저장되지
                  않을 수 있습니다.
                </div>
              )}
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
                <>
                  <button
                    className="btn btn-primary btn-block"
                    onClick={handleDeepFollowup}
                    disabled={generatingFollowup}
                  >
                    {generatingFollowup && <span className="spinner" />}
                    <MessageCircleMore size={15} />
                    답변을 바탕으로 꼬리질문 받기 ({deepFollowupCount + 1}/{DEEP_MAX_FOLLOWUPS})
                  </button>
                  {generatingFollowup && (
                    <div className="notice notice-info" style={{ marginTop: 10, fontSize: 13 }}>
                      꼬리질문을 만드는 중입니다. <strong>완료될 때까지 새로고침하거나 이동하지
                      말고</strong> 잠시만 기다려주세요.
                    </div>
                  )}
                </>
              ) : !isLast ? (
                <button className="btn btn-primary btn-block" onClick={handleNext}>
                  다음 질문으로
                </button>
              ) : (
                <>
                  <button className="btn btn-primary btn-block" onClick={handleFinish} disabled={finishing}>
                    {finishing && <span className="spinner" />}
                    답변 완료 및 최종 리포트 보기
                  </button>
                  {finishing && (
                    <div className="notice notice-info" style={{ marginTop: 10, fontSize: 13 }}>
                      <strong>최종 코칭을 생성하는 중입니다.</strong> 질문마다 STT·내용 평가·비언어
                      분석이 다시 확인되고 있어 시간이 조금 걸릴 수 있어요. <strong>완료될 때까지
                      새로고침하거나 다른 페이지로 이동하지 말아주세요.</strong>
                    </div>
                  )}
                </>
              )}
              {error && <div className="notice notice-error" style={{ marginTop: 10 }}>{error}</div>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
