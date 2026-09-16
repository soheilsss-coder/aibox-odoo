import React from "react";

// tones: neutral | info | ok | warn | err | accent
export default function Badge({ tone = "neutral", dot = false, children }) {
  return (
    <span className={`bgd ${tone !== "neutral" ? `bgd-${tone}` : ""}`}>
      {dot && <span className="bgd-dot" />}
      {children}
    </span>
  );
}
