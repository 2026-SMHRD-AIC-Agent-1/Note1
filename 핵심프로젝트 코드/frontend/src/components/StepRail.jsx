const STEPS = [
  { key: "entry", label: "시작 · 동의" },
  { key: "setup", label: "기업·직무 설정" },
  { key: "interview", label: "모의면접 진행" },
  { key: "report", label: "종합 리포트" },
];

export default function StepRail({ current }) {
  const currentIndex = STEPS.findIndex((s) => s.key === current);

  return (
    <nav className="rail">
      <div className="rail-brand">AI 모의면접 코칭</div>
      {STEPS.map((step, i) => {
        const state =
          i === currentIndex ? "active" : i < currentIndex ? "done" : "";
        return (
          <div className={`rail-step ${state}`} key={step.key}>
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            <span>{step.label}</span>
          </div>
        );
      })}
    </nav>
  );
}
