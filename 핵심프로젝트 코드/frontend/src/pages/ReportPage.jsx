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
} from "lucide-react";
import ReportToc from "../components/ReportToc.jsx";
import {
  getAnswerEvents,
  getAnswerVideoUrl,
  listNonverbalMetrics,
  createSessionComparison,
  createInterviewSession,
  generateFollowupQuestion,
} from "../api.js";

const MAX_SCORE = 100; // job_score/answer_score/overall_score 모두 0~100점 만점 (rag_ai_service.py 기준)

const TOC_ITEMS = [
  { id: "section-1", num: 1, title: "상단 요약 영역" },
  { id: "section-2", num: 2, title: "AI 종합 코칭" },
  { id: "section-3", num: 3, title: "다음 연습 목표" },
  { id: "section-4", num: 4, title: "영상 · 타임라인" },
  { id: "section-5", num: 5, title: "이전 회차 비교" },
  { id: "section-6", num: 6, title: "질문별 상세 분석" },
  { id: "section-7", num: 7, title: "RAG 평가 근거" },
  { id: "section-8", num: 8, title: "비언어 분석 요약" },
];

function formatTime(sec) {
  if (sec == null) return "--:--";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
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
        <span className="score-bar-value">{value ?? "—"}<span className="score-bar-max">/{MAX_SCORE}</span></span>
      </div>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

const NONVERBAL_CORE = [
  ["gaze_center_ratio", "시선 중앙 비율"],
  ["speaking_speed", "발화 속도 (WPM)"],
  ["filler_word_count", "필러워드"],
  ["pause_count", "침묵 횟수"],
  ["average_volume", "평균 음량"],
];

const NONVERBAL_ALL_LABELS = {
  face_yaw: "얼굴 정면 유지",
  gaze_center_ratio: "시선 중앙 비율",
  blink_rate: "눈 깜빡임 빈도",
  smile_intensity: "미소 강도",
  expression_change_count: "표정 변화 횟수",
  upper_body_sway: "상체 흔들림",
  head_nod_count: "고개 끄덕임 횟수",
  hand_gesture_rate: "손 제스처 빈도",
  pause_count: "침묵 횟수",
  average_volume: "평균 음량",
  speaking_speed: "발화 속도 (WPM)",
  pitch_variation: "음높이 변화",
  filler_word_count: "필러워드 횟수",
  voice_emotion_label: "음성 감정 (MVP 미사용)",
};

export default function ReportPage({ user, session, questions, answers, coaching, onStartNextRound }) {
  const [nonverbalMetrics, setNonverbalMetrics] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [startingNext, setStartingNext] = useState(false);
  const [error, setError] = useState(null);
  const [events, setEvents] = useState(null);
  const videoRef = useRef(null);

  const answeredList = questions
    .map((q) => ({ q, a: answers[q.question_id] }))
    .filter((item) => item.a);

  // '직무 핵심 반영도'와 '답변 구성 충실도'는 문항별로 이미 매겨지는
  // job_score / answer_score의 평균입니다 (실제 AI 채점 결과, 지어낸 값 아님).
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

  // 리포트 상단 영상/타임라인은 답변이 있는 첫 질문 기준으로 보여줍니다.
  const featured = answeredList[0];
  const featuredAnswerId = featured?.a.answer_id;

  useEffect(() => {
    listNonverbalMetrics()
      .then(setNonverbalMetrics)
      .catch(() => setNonverbalMetrics([]));
  }, []);

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
      const followupQuestion = await generateFollowupQuestion(
        nextSession.session_id,
        session.session_id
      );
      onStartNextRound({
        session: { ...nextSession, companyName: session.companyName, jobName: session.jobName },
        questions: [followupQuestion],
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
        <ScoreBar label="종합 점수" value={coaching.overall_score} color="var(--blue)" />
        <ScoreBar label="직무 핵심 반영도" value={avgJobScore} color="var(--purple)" />
        <ScoreBar label="답변 구성 충실도" value={avgAnswerScore} color="var(--green, #10b981)" />
        <ScoreBar label="전달 안정성" value={null} color="var(--card-muted)" />
        {!featuredMetric && (
          <p style={{ fontSize: 12.5, marginTop: -6 }}>
            전달 안정성은 비언어 분석(시선·음성 안정성) 데이터가 아직 없어 계산할 수 없습니다. 비언어 분석
            파이프라인이 연결되면 자동으로 채워집니다.
          </p>
        )}
      </div>

      {/* 2. AI 종합 코칭 (강점·개선점·우선순위를 여기 하나로 모았습니다) */}
      <SectionHead num={2} icon={Sparkles} title="AI 종합 코칭" />
      <div className="panel">
        <div className="panel-title">내용 종합 코칭</div>
        <p className="blockquote-blue">{coaching.content_summary}</p>
        <hr className="rule" />
        <div className="panel-title">전달 종합 코칭</div>
        <p className="blockquote-green">{coaching.delivery_summary}</p>

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

      {/* 3. 다음 연습 목표 */}
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

      {/* 4. 영상 다시보기 및 타임라인 이벤트 */}
      <SectionHead num={4} icon={Video} title="영상 다시보기 및 타임라인 이벤트" />
      <div className="panel">
        <div className="panel-title">면접 녹화 플레이어 및 타임라인 마커</div>
        <p style={{ fontSize: 14 }}>아래 타임라인 이벤트를 클릭하면 해당 구간으로 영상이 이동합니다.</p>
      </div>
      {featuredAnswerId ? (
        <>
          <div style={{ display: "flex", justifyContent: "center", marginBottom: 15 }}>
            <video
              ref={videoRef}
              src={getAnswerVideoUrl(featuredAnswerId)}
              controls
              style={{ width: "100%", maxWidth: 600, borderRadius: 10, background: "#000" }}
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
                  ⏱️ [{formatTime(ev.start_time_sec)}] {ev.event_type}
                  {ev.value ? ` · ${ev.value}` : ""}
                </button>
              ))}
            </div>
          ) : (
            events && (
              <p style={{ fontSize: 13, color: "var(--muted-onDark)" }}>
                이 답변에 기록된 타임스탬프 이벤트가 없습니다.
              </p>
            )
          )}
        </>
      ) : (
        <p style={{ color: "var(--muted-onDark)" }}>아직 재생할 답변 영상이 없습니다.</p>
      )}

      {/* 5. 2회차부터 이전 연습과 비교 */}
      <SectionHead num={5} icon={GitCompare} title="2회차부터 이전 연습과 비교" />
      <div className="panel">
        <div className="panel-title">이전 회차 대비 종합 점수 비교</div>
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

      {/* 6. 질문별 상세 분석 */}
      <SectionHead num={6} icon={ListChecks} title="질문별 상세 분석" />
      {questions.map((q, i) => {
        const a = answers[q.question_id];
        return (
          <details className="qdetail-row" key={q.question_id} open={i === 0}>
            <summary>Q{i + 1}. {q.question_text}</summary>
            <div className="qdetail-body">
              {q.question_reason && (
                <p><strong>왜 이 질문을 했나요? (출제의도)</strong><br />{q.question_reason}</p>
              )}
              {q.evaluation_points?.length > 0 && (
                <>
                  <p style={{ marginBottom: 4 }}><strong>핵심 평가 포인트</strong></p>
                  <ul className="q-points">
                    {q.evaluation_points.map((p, idx) => (
                      <li key={idx}>{p}</li>
                    ))}
                  </ul>
                </>
              )}
              {a ? (
                <>
                  <p><strong>내 답변 (STT 텍스트)</strong></p>
                  <div className="stt">{a.stt_text}</div>
                  {a.analysis ? (
                    <>
                      <p>
                        <strong>직무 관점 분석:</strong>{" "}
                        <span className="label-blue">{a.analysis.job_evaluation}</span>
                        {a.analysis.job_score != null && ` (${a.analysis.job_score}점)`}
                      </p>
                      <p>
                        <strong>답변 구성 분석:</strong>{" "}
                        <span className="label-green">{a.analysis.answer_evaluation}</span>
                        {a.analysis.answer_score != null && ` (${a.analysis.answer_score}점)`}
                      </p>
                    </>
                  ) : (
                    <p>{a.note || "이 답변의 분석 결과가 아직 없습니다."}</p>
                  )}
                </>
              ) : (
                <p>이 질문에는 아직 답변이 없습니다.</p>
              )}
            </div>
          </details>
        );
      })}

      {/* 7. RAG 평가 근거 */}
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

      {/* 8. 비언어 분석 요약 */}
      <SectionHead num={8} icon={Activity} title="비언어 분석 요약" />
      <div className="panel">
        <div className="panel-title">전달력 핵심 지표</div>
        {featuredMetric ? (
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
        ) : (
          <p>
            이 답변의 비언어 분석 데이터가 아직 없습니다. (비언어 분석 파이프라인이 현재
            백엔드에 자동으로 연동되어 있지 않을 수 있습니다.)
          </p>
        )}
      </div>

      {featuredMetric && (
        <details className="qdetail-row">
          <summary>상세 비언어 분석 지표 전체 보기 (14개 항목)</summary>
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
        비언어 분석(NONVERBAL_METRICS)은 별도의 비언어 AI 파이프라인이 값을 저장해야 표시됩니다.
        값이 없으면 위와 같이 안내 문구만 표시됩니다.
      </div>
        </div>
      </div>
    </div>
  );
}
