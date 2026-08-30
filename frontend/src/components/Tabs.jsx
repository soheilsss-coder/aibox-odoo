import React from "react";

// tabs: [{ key, label }]
export default function Tabs({ tabs, active, onChange }) {
  return (
    <div className="ds-tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          aria-selected={active === tab.key}
          className={`ds-tab ${active === tab.key ? "ds-tab-active" : ""}`}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
