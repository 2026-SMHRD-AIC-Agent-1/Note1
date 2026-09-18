import { useEffect, useRef, useState } from "react";
import {
  BarChart3,
  Sparkles,
  Target,
  Video,
  GitCompare,
  ListChecks,
  FileSearch,
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import ReportToc from "../components/ReportToc.jsx";
import {
  getAnswerEvents,
  getAnswerVideoUrl,
  listNonverbalMetrics,
  createSessionComparison,
  createInterviewSession,
  generateFollowupQuestion,
  getDeliverySummary,
} from "../api.js";

const MAX_SCORE = 100;

const TOC_ITEMS = [
  { id: "section-1", num: 1, title: "상단 요약 영역" },
  { id: "section-2", num: 2, title: "AI 종합 코칭" },
  { id: "section-3", num: 3, title: "다음 연습 목표" },
  { id: "section-4", num: 4, title: "영상 · 타임라인" },
  { id: "section-5", num: 5, title: "이전 회차 비교" },
  { id: "section-6", num: 6, title: "질문별 상세 분석" },
  { id: "section-7", num: 7, title: "RAG 평가 근거" },
  { id: "section-8", num: 8, title: "전달 분석 요약" },
];

const EVENT_LABELS = {
  SPEECH_HESITATION: "머뭇거림 표현",
  SPEECH_REPETITION: "반복 표현",
  GAZE_AWAY: "시선 이탈",
  FACE_TURNED: "고개 방향 이탈",
  BODY_MOVEMENT: "자세 이탈",
  LONG_PAUSE: "긴 침묵",
  LONG_BLINK: "긴 눈감음",
  NOD: "고개 끄덕임",
  SHAKE: "고개 젓기",
  HAND_GESTURE: "손 제스처",
  SMILE: "미소",
};

const NONVERBAL_CORE = [
  ["gaze_center_ratio", "시선 중앙 비율 (기존 참고값)"],
  ["speaking_speed", "발화 속도 (기존 참고값)"],
  ["pause_count", "침묵 횟수 (기존 참고값)"],
  ["average_volume", "평균 음량 (기존 참고값)"],
  ["upper_body_sway", "상체 움직임 (기존 참고값)"],
];

const NONVERBAL_ALL_LABELS = {
  face_yaw: "얼굴 정면 유지 (기존 참고값)",
  gaze_center_ratio: "시선 중앙 비율 (기존 참고값)",
  blink_rate: "눈 깜빡임 빈도 (관찰값)",
  smile_intensity: "미소 강도 (관찰값)",
  expression_change_count: "표정 변화 횟수 (관찰값)",
  upper_body_sway: "상체 움직임 (기존 참고값)",
  head_nod_count: "고개 끄덕임 횟수 (관찰값)",
  hand_gesture_rate: "손 제스처 빈도 (관찰값)",
  pause_count: "침묵 횟수 (기존 참고값)",
  average_volume: "평균 음량 (기존 참고값)",
  speaking_speed: "발화 속도 (기존 참고값)",
  pitch_variation: "음높이 변화 (기존 참고값)",
  filler_word_count: "머뭇거림 표현 횟수 (기존 호환값·점수 미반영)",
  voice_emotion_label: "음성 감정 (MVP 미사용)",
};

function formatTime(sec) {
  if (sec == null) return "--:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function formatExpressionCounts(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return "없음";
  return entries.map(([expression, count]) => `${expression} ${count}회`).join(", ");
}

function formatValue(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function SectionHead({ num, icon: Icon, title }) {
  return (
    <div className="section-head" id={`section-${num}`}>
      <div className="num">{Icon ? <Icon size={16} /> : num}</div>
      <h2>{title}</h2>
    </div>
  );
}

function ScoreBar({ label, value, color }) {
  const pct = value != null ? Math.max(0, Math.min(100, (value / MAX_SCORE) * 100)) : 0;
  return (
    <div className="score-bar-row">
      <div className="score-bar-head">
        <span className="score-bar-label">{label}</span>
        <span className="score-bar-value">
          {value ?? "—"}<span className="score-bar-max">/{MAX_SCORE}</span>
        </span>
      </div>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

function SpeechHabitsSummary({ answer, compact = false }) {
  const stability = answer?.stt_stability;
  if (!stability) return null;

  if (stability.status !== "available") {
    return (
      <div className="notice notice-info" style={{ fontSize: 12.5 }}>
        말하기 습관 분석을 사용할 수 없습니다. {stability.reason || "상세 STT 결과가 없습니다."}
      </div>
    );
  }

  const habits = stability.speech_habits || {};
  const hesitation = habits.hesitation || {};
  const repetition = habits.repetition || {};
  const hesitationItems = hesitation.items || [];
  const repetitionItems = repetition.items || [];

  return (
    <div className={compact ? "" : "notice notice-info"} style={{ fontSize: 12.5 }}>
      {!compact && <strong>말하기 습관 · 점수에는 반영하지 않음</strong>}
      <p style={{ margin: compact ? "4px 0" : "8px 0 4px" }}>
        <strong>머뭇거림 표현:</strong> {hesitation.total_count ?? 0}회
        {hesitation.total_count > 0 ? ` (${formatExpressionCounts(hesitation.counts_by_expression)})` : ""}
      </p>
      {hesitationItems.length > 0 && (
        <p style={{ margin: "4px 0" }}>
          발생 시점: {hesitationItems.map((item) => `${formatTime(item.start_sec)} ‘${item.expression}’`).join(" · ")}
        </p>
      )}
      <p style={{ margin: "4px 0" }}>
        <strong>반복 표현:</strong> {repetition.total_count ?? 0}회
      </p>
      {repetitionItems.length > 0 && (
        <p style={{ margin: "4px 0" }}>
          발생 시점: {repetitionItems.map((item) => `${formatTime(item.start_sec)} ‘${item.expression}’`).join(" · ")}
        </p>
      )}
    </div>
  );
}

function DeliveryMeasurements({ answer }) {
  const delivery = answer?.delivery_analysis;
  if (!delivery) return null;

  const profile = delivery.delivery_profile;
  const audioQuality = delivery.audio_quality;

  if (!profile) {
    return (
      <div className="notice notice-info" style={{ fontSize: 12.5 }}>
        <strong>전달 분석:</strong> {delivery.reason || "분석 결과가 없습니다."}
        {audioQuality?.is_valid === false && " 오디오 품질 문제는 감지되었습니다."}
      </div>
    );
  }

  const measurement = profile.measurement || {};
  const components = profile.components || {};
  const flow = components.speaking_flow || {};
  const pace = components.pace_stability || {};
  const volume = components.volume_stability || {};
  const gaze = components.gaze_stability || {};
  const posture = components.posture_stability || {};

  const pauseRatio = flow.pause_ratio != null ? `${formatValue(flow.pause_ratio * 100)}%` : "—";
  const articulation = pace.articulation_rate_units_per_min;
  const timedRate = pace.timed_span_hangul_syllables_per_min;
  const paceText = articulation != null
    ? `${formatValue(articulation)} 음절/분 (실제 말한 구간 기준)`
    : timedRate != null
      ? `${formatValue(timedRate)} 음절/분 (첫 단어~마지막 단어 기준)`
      : "—";

  return (
    <table className="compare" style={{ marginTop: 8 }}>
      <tbody>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>오디오 측정</td>
          <td style={{ textAlign: "left" }}>
            {measurement.audio_status === "available" ? "측정 가능" : "측정 불가"}
          </td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>말하기 흐름</td>
          <td style={{ textAlign: "left" }}>
            침묵 비율 {pauseRatio} · 가장 긴 침묵 {formatValue(flow.max_pause_sec)}초
          </td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>발화 속도 참고값</td>
          <td style={{ textAlign: "left" }}>{paceText}</td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>음량 변화폭</td>
          <td style={{ textAlign: "left" }}>
            {volume.volume_variation_db != null ? `${formatValue(volume.volume_variation_db, 2)} dB` : "—"}
          </td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>시선 안정성</td>
          <td style={{ textAlign: "left" }}>
            {gaze.score_eligible
              ? `점수 후보 · 이탈 ${formatValue(gaze.deviation_per_min)}회/분 · 시간비율 ${formatValue((gaze.deviation_time_ratio || 0) * 100)}%`
              : "캘리브레이션 연결 전 — 점수에 사용하지 않음"}
          </td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700, textAlign: "left" }}>자세 안정성</td>
          <td style={{ textAlign: "left" }}>
            {posture.score_eligible
              ? `점수 후보 · 고개 이탈 ${formatValue(posture.face_deviation_per_min)}회/분 · 상체 이탈 ${formatValue(posture.body_movement_per_min)}회/분`
              : "캘리브레이션 연결 전 — 점수에 사용하지 않음"}
          </td>
        </tr>
      </tbody>
    </table>
  );
}

export default function ReportPage({ user, session, questions, answers, coaching, onStartNextRound }) {
  const [nonverbalMetrics, setNonverbalMetrics] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [startingNext, setStartingNext] = useState(false);
  const [error, setError] = useState(null);
  const [events, setEvents] = useState(null);
  const [deliverySummary, setDeliverySummary] = useState(null);
  const [openQuestionId, setOpenQuestionId] = useState(questions[0]?.question_id ?? null);
  const videoRef = useRef(null);

  const answeredList = questions
    .map((q) => ({ q, a: answers[q.question_id] }))
    .filter((item) => item.a);

  const jobScores = answeredList
    .map((item) => item.a.analysis?.job_score)
    .filter((s) => s !== null && s !== undefined);
  const answerScores = answeredList
    .map((item) => item.a.analysis?.answer_score)
    .filter((s) => s !== null && s !== undefined);

  const avgJobScore = jobScores.length
    ? Math.round((jobScores.reduce((a, b) => a + b, 0) / jobScores.length) * 10) / 10
    : null;
  const avgAnswerScore = answerScores.length
    ? Math.round((answerScores.reduce((a, b) => a + b, 0) / answerScores.length) * 10) / 10
    : null;

  const strengths = answeredList.map((item) => item.a.analysis?.strengths).filter(Boolean);
  const improvements = answeredList.map((item) => item.a.analysis?.improvements).filter(Boolean);

  const [featuredIndex, setFeaturedIndex] = useState(0);
  const featured = answeredList[featuredIndex] || answeredList[0];
  const featuredAnswerId = featured?.a.answer_id;
  // answeredList 안에서의 실제 순번(질문 1, 질문 2, ...)을 이벤트 라벨에 쓴다.
  // "회차"라는 단어는 이 서비스에서 이미 세션(연습) 단위를 가리키는 용어라서
  // (예: attempt_no, "다음 회차") 같은 세션 안의 질문 번호에는 쓰지 않는다.
  const featuredRound = answeredList.findIndex((item) => item.a.answer_id === featuredAnswerId) + 1;
  // 심층면접은 "첫 질문 + 꼬리질문 최대 3개(총 4개)" 구조라서 A!SK(정확히 3개)와
  // 다르다. 둘 다 "질문 N"이라고만 부르면 왜 4개가 나오는지 헷갈리므로, 심층면접일
  // 때는 라벨을 다르게 보여준다.
  const isDeepInterview = session.interview_type === "DEEP_INTERVIEW";
  function questionLabel(idx) {
    if (!isDeepInterview) return `질문 ${idx + 1}`;
    return idx === 0 ? "첫 질문" : `꼬리질문 ${idx}`;
  }

  useEffect(() => {
    listNonverbalMetrics()
      .then(setNonverbalMetrics)
      .catch(() => setNonverbalMetrics([]));
  }, []);

  useEffect(() => {
    if (!session?.session_id) return;
    getDeliverySummary(session.session_id)
      .then(setDeliverySummary)
      .catch(() => setDeliverySummary(null));
  }, [session?.session_id]);

  useEffect(() => {
    if (!featuredAnswerId) return;
    getAnswerEvents(featuredAnswerId)
      .then(setEvents)
      .catch(() => setEvents(null));
  }, [featuredAnswerId]);

  const featuredMetric = nonverbalMetrics.find((m) => m.answer_id === featuredAnswerId);

  async function handleCompare() {
    if (!session.previous_session_id) return;
    setComparing(true);
    setError(null);
    try {
      setComparison(
        await createSessionComparison({
          first_session_id: session.previous_session_id,
          second_session_id: session.session_id,
        })
      );
    } catch (err) {
      setError(err.message || "이전 회차와 비교하지 못했습니다.");
    } finally {
      setComparing(false);
    }
  }

  async function handleNextRound() {
    setStartingNext(true);
    setError(null);
    try {
      const nextSession = await createInterviewSession({
        user_id: user.user_id,
        company_id: session.company_id,
        job_id: session.job_id,
        interview_type: session.interview_type,
        previous_session_id: session.session_id,
      });
      const followupQuestions = await generateFollowupQuestion(
        nextSession.session_id,
        session.session_id
      );
      onStartNextRound({
        session: { ...nextSession, companyName: session.companyName, jobName: session.jobName },
        questions: followupQuestions,
      });
    } catch (err) {
      setError(err.message || "다음 회차를 시작하지 못했습니다.");
    } finally {
      setStartingNext(false);
    }
  }

  return (
    <div className="main" style={{ maxWidth: 980 }}>
      <div className="eyebrow">최종 면접 분석 리포트</div>
      <h1>[{session.companyName}] {session.jobName}</h1>

      <div className="report-layout">
        <ReportToc items={TOC_ITEMS} />
        <div className="report-content">
          <SectionHead num={1} icon={BarChart3} title="상단 요약 영역" />
          <div className="panel">
            <table className="compare" style={{ marginTop: 0 }}>
              <tbody>
                <tr><td style={{ fontWeight: 700 }}>기업명</td><td style={{ textAlign: "left" }}>{session.companyName}</td></tr>
                <tr><td style={{ fontWeight: 700 }}>직무명</td><td style={{ textAlign: "left" }}>{session.jobName}</td></tr>
                <tr><td style={{ fontWeight: 700 }}>면접유형</td><td style={{ textAlign: "left" }}>{session.interview_type}</td></tr>
                <tr><td style={{ fontWeight: 700 }}>문항 수</td><td style={{ textAlign: "left" }}>{questions.length}문항</td></tr>
              </tbody>
            </table>

            <div className="panel-title" style={{ marginTop: 18 }}>핵심 지표 (100점 만점)</div>
            <ScoreBar label="직무 핵심 반영도" value={avgJobScore} color="var(--purple)" />
            <ScoreBar label="답변 구성 충실도" value={avgAnswerScore} color="var(--green, #10b981)" />
            <ScoreBar
              label="전달 안정성"
              value={deliverySummary?.status === "available" ? deliverySummary.delivery_score_average : null}
              color="var(--card-muted)"
            />
            {deliverySummary?.status === "available" ? (
              <p style={{ fontSize: 12.5, marginTop: -6 }}>
                시선·자세·말하기 흐름·발화 속도·음량 5개 항목을 종합한 점수입니다({deliverySummary.eligible_question_count}/{deliverySummary.question_count}문항 반영).
              </p>
            ) : (
              <p style={{ fontSize: 12.5, marginTop: -6 }}>
                {deliverySummary
                  ? `측정 가능한 질문이 부족해(${deliverySummary.eligible_question_count}/${deliverySummary.question_count}문항) 전달 안정성 점수를 표시하지 않습니다. 정상 측정된 질문이 전체의 2/3 이상이어야 표시됩니다.`
                  : "측정에 실패한 항목이 있어 전달 안정성 점수를 계산하지 못했습니다. 조명·마이크 상태를 확인하고 다시 녹화하면 다음 회차에 반영됩니다."}
              </p>
            )}
          </div>

          <SectionHead num={2} icon={Sparkles} title="AI 종합 코칭" />
          <div className="panel">
            <div className="panel-title">내용 종합 코칭</div>
            <p className="blockquote-blue">{coaching.content_summary}</p>
            <hr className="rule" />
            <div className="panel-title">전달 종합 코칭</div>
            <p className="blockquote-green">
              현재 실제 전달 측정값은 아래 ‘전달 분석 요약’에 표시합니다. 최종 전달 점수와 종합 코칭 문구는 캘리브레이션 통합과 점수 기준 확정 후 제공합니다.
            </p>

            {strengths.length > 0 && (
              <>
                <hr className="rule" />
                <div className="panel-title">주요 강점</div>
                {strengths.map((s, i) => (
                  <p key={i} style={{ margin: "4px 0" }}>✓ {s}</p>
                ))}
              </>
            )}

            {improvements.length > 0 && (
              <>
                <hr className="rule" />
                <div className="panel-title">개선 및 보완 포인트</div>
                {improvements.map((s, i) => (
                  <p key={i} style={{ margin: "4px 0", color: "var(--red)" }}>• {s}</p>
                ))}
              </>
            )}
          </div>

          <div className="panel panel-flag">
            <div className="panel-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <AlertTriangle size={17} /> 가장 먼저 고칠 점
            </div>
            <p style={{ fontSize: 17 }}>{coaching.priority_focus}</p>
          </div>

          <SectionHead num={3} icon={Target} title="다음 연습 목표" />
          <div className="panel">
            <div className="panel-title">다음 연습 목표</div>
            <p className="blockquote-purple">{coaching.next_practice_goal}</p>
            <button className="btn btn-primary" onClick={handleNextRound} disabled={startingNext} style={{ marginTop: 10 }}>
              {startingNext && <span className="spinner" />}
              다음 맞춤 면접 시작하기
            </button>
            {error && <div className="notice notice-error" style={{ marginTop: 12 }}>{error}</div>}
          </div>

          <SectionHead num={4} icon={Video} title="영상 다시보기 및 타임라인 이벤트" />
          <div className="panel">
            <div className="panel-title">면접 녹화 플레이어 및 타임라인 마커</div>
            <p style={{ fontSize: 14 }}>아래 타임라인 이벤트를 클릭하면 해당 구간으로 영상이 이동합니다.</p>
            {answeredList.length > 1 && (
              <div className="btn-row" style={{ marginTop: 10, flexWrap: "wrap" }}>
                {answeredList.map((item, idx) => (
                  <button
                    key={item.a.answer_id}
                    type="button"
                    className={idx === featuredIndex ? "tag tag-blue" : "tag tag-muted"}
                    style={{ cursor: "pointer", border: "none" }}
                    onClick={() => setFeaturedIndex(idx)}
                  >
                    {questionLabel(idx)}
                  </button>
                ))}
              </div>
            )}
          </div>
          {featuredAnswerId ? (
            <>
              <div style={{ display: "flex", justifyContent: "center", marginBottom: 15 }}>
                <video
                  ref={videoRef}
                  src={getAnswerVideoUrl(featuredAnswerId)}
                  controls
                  style={{
                    width: "100%",
                    maxWidth: 600,
                    maxHeight: 420,
                    objectFit: "contain",
                    borderRadius: 10,
                    background: "#000",
                  }}
                />
              </div>
              {events && events.events.length > 0 ? (
                <div className="timeline-list">
                  {events.events.map((ev) => (
                    <button
                      key={ev.event_id}
                      className="timeline-pill"
                      onClick={() => {
                        if (videoRef.current) {
                          videoRef.current.currentTime = ev.start_time_sec;
                          videoRef.current.play();
                        }
                      }}
                    >
                      ⏱️ [{formatTime(ev.start_time_sec)}] {EVENT_LABELS[ev.event_type] || ev.event_type}
                      {ev.value ? ` · ${ev.value}` : ""} ({questionLabel(featuredRound - 1)})
                    </button>
                  ))}
                </div>
              ) : (
                events && <p style={{ fontSize: 13 }}>이 답변에 기록된 타임스탬프 이벤트가 없습니다.</p>
              )}
            </>
          ) : (
            <p>아직 재생할 답변 영상이 없습니다.</p>
          )}

          <SectionHead num={5} icon={GitCompare} title="2회차부터 이전 연습과 비교" />
          <div className="panel">
            <div className="panel-title">이전 회차 대비 내용 종합 점수 비교</div>
            {session.previous_session_id ? (
              <>
                <button className="btn btn-ghost" onClick={handleCompare} disabled={comparing}>
                  {comparing && <span className="spinner" />}
                  이전 회차와 비교
                </button>
                {comparison && (
                  <table className="compare">
                    <thead>
                      <tr>
                        <th>{session.attempt_no - 1}회차</th>
                        <th>{session.attempt_no}회차</th>
                        <th>변화</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>{comparison.first_overall_score ?? "—"}</td>
                        <td>{comparison.second_overall_score ?? "—"}</td>
                        <td className={comparison.score_change > 0 ? "delta-up" : comparison.score_change < 0 ? "delta-down" : ""}>
                          {comparison.score_change > 0 ? "+" : ""}
                          {comparison.score_change ?? "—"}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                )}
                {comparison && <p style={{ marginTop: 10, whiteSpace: "pre-line" }}>{comparison.comparison_summary}</p>}
              </>
            ) : (
              <p>다음 회차를 진행하면 기존 회차를 이 자리에서 비교할 수 있습니다.</p>
            )}
          </div>

          <SectionHead num={6} icon={ListChecks} title="질문별 상세 분석" />
          <div className="qdetail-accordion">
            {questions.map((q, i) => {
              const a = answers[q.question_id];
              const isOpen = openQuestionId === q.question_id;
              return (
                <div className={`qdetail-card ${isOpen ? "open" : ""}`} key={q.question_id}>
                  <button
                    type="button"
                    className="qdetail-card-head"
                    onClick={() => setOpenQuestionId(isOpen ? null : q.question_id)}
                  >
                    <div className="qdetail-card-head-text">
                      <span className="qdetail-card-num">Q{i + 1}</span>
                      <span className="qdetail-card-title">{q.question_text}</span>
                    </div>
                    <div className="qdetail-card-head-right">
                      {a?.analysis?.job_score != null && (
                        <span className="tag tag-blue">직무 {a.analysis.job_score}점</span>
                      )}
                      {a?.analysis?.answer_score != null && (
                        <span className="tag tag-green">구성 {a.analysis.answer_score}점</span>
                      )}
                      {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                    </div>
                  </button>

                  {isOpen && (
                    <div className="qdetail-card-body">
                      {q.question_reason && (
                        <div className="qdetail-block">
                          <div className="qdetail-block-label">왜 이 질문을 했나요? (출제의도)</div>
                          <p>{q.question_reason}</p>
                        </div>
                      )}
                      {q.evaluation_points?.length > 0 && (
                        <div className="qdetail-block">
                          <div className="qdetail-block-label">핵심 평가 포인트</div>
                          <ul className="q-points">
                            {q.evaluation_points.map((p, idx) => <li key={idx}>{p}</li>)}
                          </ul>
                        </div>
                      )}
                      {a ? (
                        <>
                          <div className="qdetail-block">
                            <div className="qdetail-block-label">내 답변 (STT 텍스트)</div>
                            <div className="stt">{a.stt_text}</div>
                          </div>
                          {a.analysis ? (
                            <div className="qdetail-block-grid">
                              <div className="qdetail-block">
                                <div className="qdetail-block-label">직무 관점 분석</div>
                                <p className="label-blue">{a.analysis.job_evaluation}</p>
                              </div>
                              <div className="qdetail-block">
                                <div className="qdetail-block-label">답변 구성 분석</div>
                                <p className="label-green">{a.analysis.answer_evaluation}</p>
                              </div>
                            </div>
                          ) : (
                            <p>{a.note || "이 답변의 분석 결과가 아직 없습니다."}</p>
                          )}
                          <div className="qdetail-block">
                            <SpeechHabitsSummary answer={a} />
                          </div>
                        </>
                      ) : (
                        <p>이 질문에는 아직 답변이 없습니다.</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <SectionHead num={7} icon={FileSearch} title="RAG 평가 근거" />
          <details className="qdetail-row">
            <summary>공식 RAG 출처 및 매핑 정보 보기</summary>
            <div className="qdetail-body">
              <pre className="evidence">
                {questions
                  .map((q, i) => {
                    const lines = (q.rag_evidence || [])
                      .map((ev) => `  - ${ev.source_title} (${ev.category}, p.${ev.page}, 유사도 ${ev.similarity})`)
                      .join("\n");
                    return `[Q${i + 1}] ${q.question_text}\n${lines || "  - 근거 자료 없음"}`;
                  })
                  .join("\n\n")}
              </pre>
            </div>
          </details>

          <SectionHead num={8} icon={Activity} title="전달 분석 요약" />

          <div className="panel">
            <div className="panel-title">실제 영상·음성 측정값 · 최종 점수 전 단계</div>
            {answeredList.some((item) => item.a.delivery_analysis) ? (
              answeredList.map((item, idx) => (
                <div key={item.q.question_id} style={{ marginBottom: idx === answeredList.length - 1 ? 0 : 18 }}>
                  <strong>Q{idx + 1}</strong>
                  <DeliveryMeasurements answer={item.a} />
                </div>
              ))
            ) : (
              <p>전달 분석 결과가 아직 없습니다.</p>
            )}
          </div>

          {featuredMetric && (
            <div className="panel">
              <div className="panel-title">기존 DB 비언어 호환값</div>
              <p style={{ fontSize: 12.5 }}>
                아래 값은 과거 NONVERBAL_METRICS 구조와의 호환을 위한 참고값입니다. 최종 전달 안정성 점수에는 아직 사용하지 않습니다.
              </p>
              <table className="compare">
                <tbody>
                  {NONVERBAL_CORE.map(([key, label]) => (
                    <tr key={key}>
                      <td style={{ fontWeight: 700, textAlign: "left" }}>{label}</td>
                      <td style={{ textAlign: "left" }}>{featuredMetric[key] ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {featuredMetric && (
            <details className="qdetail-row">
              <summary>기존 비언어 분석 호환 지표 전체 보기</summary>
              <div className="qdetail-body">
                {Object.entries(NONVERBAL_ALL_LABELS)
                  .filter(([key]) => featuredMetric[key] !== null && featuredMetric[key] !== undefined)
                  .map(([key, label]) => (
                    <p key={key} style={{ margin: "4px 0" }}>
                      <strong>{label}</strong>: {String(featuredMetric[key])}
                    </p>
                  ))}
              </div>
            </details>
          )}

          <div className="footer-note">
            머뭇거림 표현과 반복 표현은 코칭 리포트 전용이며 점수에 반영하지 않습니다.
            시선·자세는 캘리브레이션을 통과한 측정값만 점수 후보로 사용합니다.
          </div>
        </div>
      </div>
    </div>
  );
}
