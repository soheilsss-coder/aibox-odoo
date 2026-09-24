import React from "react";

// tone: "neutral" (default) | "success" | "danger" | "warning" | "info"
export default function Badge({ tone = "neutral", children, className = "" }) {
  return <span className={`ds-badge ds-badge-${tone} ${className}`}>{children}</span>;
}
