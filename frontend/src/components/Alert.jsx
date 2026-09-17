import React from "react";
import Icon from "./Icon.jsx";

// tones: err (default) | ok | info | warn ; renders nothing for empty text.
const ICONS = { err: "alert", ok: "checkCircle", info: "info", warn: "alert" };

export default function Alert({ tone = "err", children, onDismiss }) {
  // Treat compound children like ["", false, null] as empty so callers can
  // inline {condition && <…>} without ghost alert boxes.
  const flat = React.Children.toArray(children).filter(
    (c) => c !== null && c !== false && c !== "" && c !== undefined
  );
  if (flat.length === 0) return null;
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
