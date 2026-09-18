import { Check } from "lucide-react";

const STEPS = ["동의", "설정", "면접", "리포트"];

export default function TopBar({ current }) {
  return (
    <div className="topbar">
      <div className="topbar-brand">
        <span className="logo-dot">🎯</span>
        AI 면접코칭 Agent
      </div>
      <div className="stepper">
        {STEPS.map((label, i) => (
          <div className="stepper-item" key={label}>
            {i > 0 && <div className={`stepper-line ${i <= current ? "done" : ""}`} />}
            <div className={`stepper-circle ${i < current ? "done" : i === current ? "active" : ""}`}>
              {i < current ? <Check size={13} /> : i + 1}
            </div>
            <span className={`stepper-label ${i === current ? "active" : ""}`}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
