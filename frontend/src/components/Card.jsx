import React from "react";

export default function Card({ title, actions, children, className = "", ...rest }) {
  return (
    <div className={`card ${className}`} {...rest}>
      {(title || actions) && (
        <div className="ds-card-header">
          {title && <h3 className="ds-card-title">{title}</h3>}
          {actions && <div className="ds-card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
