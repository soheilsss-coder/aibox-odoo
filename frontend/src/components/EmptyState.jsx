import React from "react";
import Icon from "./Icon.jsx";

export default function EmptyState({ icon = "inbox", title, text, action }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={24} strokeWidth={1.6} />
      </div>
      {title ? <h4>{title}</h4> : null}
      <div className="small">{text}</div>
      {action}
    </div>
  );
}
