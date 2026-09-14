import { Camera, Target, Database, TrendingUp, Check, Mic } from "lucide-react";

const FEATURES = [
  {
    icon: Camera,
    color: "#2563eb",
    bg: "#eaf1ff",
    title: "비언어 행동 분석",
    desc: "실시간으로 자세, 표정, 목소리를 분석하여 객관적인 피드백을 제공합니다.",
  },
  {
    icon: Target,
    color: "#8b5cf6",
    bg: "#f3edff",
    title: "맞춤형 코칭",
    desc: "지원한 기업·직무·면접유형에 맞춘 개인별 맞춤 코칭을 제공합니다.",
  },
  {
    icon: Database,
    color: "#3159e8",
    bg: "#eef2ff",
    title: "RAG 자료 기반",
    desc: "기업별 공식 채용자료 기반의 맞춤형 질문과 평가기준을 제공합니다.",
  },
  {
    icon: TrendingUp,
    color: "#10b981",
    bg: "#e8fbf3",
    title: "개선 가이드",
    desc: "분석 결과를 바탕으로 구체적인 다음 연습 목표를 제안합니다.",
  },
];

export default function LandingPage({ onStart }) {
  return (
    <div>
      <header className="landing-header">
        <div className="landing-brand">
          <span
            style={{
              width: 34,
              height: 34,
              borderRadius: 10,
              background: "var(--blue-soft)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            🎯
          </span>
          AI 면접코칭 Agent
        </div>
      </header>

      <section className="landing-hero">
        <div className="landing-hero-copy">
          <div className="landing-eyebrow">당신의 면접, 이제 AI와 함께 준비하세요</div>
          <h1>
            AI 면접코칭 <span className="accent">Agent</span>
          </h1>
          <p className="landing-hero-sub">
            기업·직무·면접유형에 맞춘 맞춤형 AI 면접 코칭으로 더 나은 나를, 더 가까운
            합격을 만들어드립니다.
          </p>
          <ul className="landing-checklist">
            <li>
              <span className="landing-check-icon"><Check size={12} /></span>
              실시간 비언어 행동 분석 (자세·표정·목소리)
            </li>
            <li>
              <span className="landing-check-icon"><Check size={12} /></span>
              AI 기반 맞춤형 피드백 및 개선 가이드
            </li>
            <li>
              <span className="landing-check-icon"><Check size={12} /></span>
              기업/직무/면접유형별 맞춤형 RAG 자료 제공
            </li>
          </ul>
          <div className="landing-cta-row">
            <button className="btn btn-primary" style={{ fontSize: 16.5, padding: "15px 30px" }} onClick={onStart}>
              지금 시작하기 →
            </button>
          </div>
        </div>

        <div className="landing-visual">
          <div className="landing-badge landing-badge-1">
            <span className="icon" style={{ background: "#eaf1ff" }}>
              <Mic size={16} color="#2563eb" />
            </span>
            <div>
              <div className="title">비언어 행동 분석</div>
              <div className="sub">자세 · 표정 · 목소리</div>
            </div>
          </div>
          <div className="landing-badge landing-badge-2">
            <span className="icon" style={{ background: "#f3edff" }}>
              <Target size={16} color="#8b5cf6" />
            </span>
            <div>
              <div className="title">맞춤형 코칭</div>
              <div className="sub">기업 · 직무 · 면접유형</div>
            </div>
          </div>

          <div className="landing-mock-card">
            <div className="landing-mock-score">
              <div className="landing-mock-ring">
                <span>85</span>
              </div>
              <div className="landing-mock-bars">
                <div className="landing-mock-bar-row">
                  <span>표정</span>
                  <div className="landing-mock-bar-track">
                    <div className="landing-mock-bar-fill" style={{ width: "82%" }} />
                  </div>
                </div>
                <div className="landing-mock-bar-row">
                  <span>자세</span>
                  <div className="landing-mock-bar-track">
                    <div className="landing-mock-bar-fill" style={{ width: "74%" }} />
                  </div>
                </div>
                <div className="landing-mock-bar-row">
                  <span>목소리</span>
                  <div className="landing-mock-bar-track">
                    <div className="landing-mock-bar-fill" style={{ width: "90%" }} />
                  </div>
                </div>
              </div>
            </div>
            <p style={{ fontSize: 12.5, margin: 0, color: "var(--muted-onDark)" }}>
              맞춤형 리포트 미리보기 — 실제 리포트 화면과 동일한 지표를 보여드립니다.
            </p>
          </div>

          <div className="landing-badge landing-badge-3">
            <span className="icon" style={{ background: "#eef2ff" }}>
              <Database size={16} color="#3159e8" />
            </span>
            <div>
              <div className="title">RAG 자료 기반</div>
              <div className="sub">신뢰도 높은 최신 정보</div>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-features">
        <div className="landing-features-head">
          <div>
            <div className="landing-features-eyebrow">KEY FEATURES</div>
            <div className="landing-features-title">
              AI 면접코칭 Agent의 <span className="accent">핵심 기능</span>을 확인해보세요
            </div>
          </div>
        </div>
        <div className="landing-feature-grid">
          {FEATURES.map((f) => (
            <div className="landing-feature-card" key={f.title}>
              <div className="landing-feature-icon" style={{ background: f.bg }}>
                <f.icon size={20} color={f.color} />
              </div>
              <h3>{f.title}</h3>
              <p>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
