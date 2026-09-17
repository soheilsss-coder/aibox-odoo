import React, { useMemo } from "react";
import { Card, Icon } from "../components";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Renders the real current month (client clock) with today highlighted.
export default function CalendarPage() {
  const now = new Date();
  const { cells, label } = useMemo(() => {
    const y = now.getFullYear();
    const m = now.getMonth();
    const first = new Date(y, m, 1);
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    // Monday-first offset (getDay(): 0=Sun..6=Sat)
    const offset = (first.getDay() + 6) % 7;
    const total = Math.ceil((offset + daysInMonth) / 7) * 7;
    const cells = Array.from({ length: total }, (_, i) => {
      const day = i - offset + 1;
      return day >= 1 && day <= daysInMonth ? day : null;
    });
    const label = first.toLocaleDateString("en-US", { month: "long", year: "numeric" });
    return { cells, label };
  }, []);

  return (
    <>
      <header className="page-head">
        <div>
          <div className="eyebrow">Time</div>
          <h1>Calendar</h1>
          <p>Leave, meetings and tasks in one time view.</p>
        </div>
        <div className="h-stack muted small"><Icon name="calendar" size={16} /> Today · {now.toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>
      </header>

      <Card className="cal-card">
        <div className="cal-head">
          <strong>{label}</strong>
        </div>
        <div className="cal-dow">{DOW.map((d) => <span key={d}>{d}</span>)}</div>
        <div className="cal-grid" style={{ marginTop: 6 }}>
          {cells.map((day, i) => (
            <div
              key={i}
              className={`cal-day ${day === null ? "dim" : ""} ${day === now.getDate() ? "today" : ""}`}
            >
              {day ?? ""}
              {day === now.getDate() && <span className="tag">Today</span>}
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
