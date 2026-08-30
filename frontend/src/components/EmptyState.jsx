import React from "react";

export default function EmptyState({ text, action }) {
  return (
    <div className="ds-empty">
      <p className="muted">{text}</p>
      {action}
    </div>
  );
}
