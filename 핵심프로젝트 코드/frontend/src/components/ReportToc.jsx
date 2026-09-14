import { useEffect, useState } from "react";

export default function ReportToc({ items }) {
  const [active, setActive] = useState(items[0]?.id);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) setActive(entry.target.id);
        });
      },
      { rootMargin: "-96px 0px -70% 0px", threshold: 0 }
    );
    items.forEach((item) => {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    });
    return () => observer.disconnect();
  }, [items]);

  return (
    <nav className="report-sidebar" aria-label="리포트 목차">
      <div className="report-toc-title">목차</div>
      {items.map((item) => (
        <div
          key={item.id}
          role="button"
          tabIndex={0}
          className={`report-toc-item ${active === item.id ? "active" : ""}`}
          onClick={() => document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
          onKeyDown={(e) => {
            if (e.key === "Enter") document.getElementById(item.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
        >
          <span className="report-toc-num">{item.num}</span>
          {item.title}
        </div>
      ))}
    </nav>
  );
}
