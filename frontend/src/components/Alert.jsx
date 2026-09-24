import React from "react";

// tone: "danger" (default, replaces old .error-text) | "success" | "info"
export default function Alert({ tone = "danger", children }) {
  if (!children) return null;
  return <div className={`ds-alert ds-alert-${tone}`}>{children}</div>;
}
