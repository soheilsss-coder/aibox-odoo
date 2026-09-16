import React from "react";
import Icon from "./Icon.jsx";

// tones: err (default) | ok | info | warn ; renders nothing for empty text.
const ICONS = { err: "alert", ok: "checkCircle", info: "info", warn: "alert" };

export default function Alert({ tone = "err", children, onDismiss }) {
  if (!children) return null;
  return (
    <div className={`alert ${tone !== "err" ? `alert-${tone}` : ""}`} role="alert">
      <Icon name={ICONS[tone] || "alert"} size={16} />
      <div className="grow">{children}</div>
      {onDismiss && (
        <button className="alert-close" onClick={onDismiss} aria-label="Dismiss">
          <Icon name="x" size={14} />
        </button>
      )}
    </div>
  );
}
