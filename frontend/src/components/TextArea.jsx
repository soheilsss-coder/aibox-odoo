import React from "react";

export default function TextArea({ label, error, id, className = "", ...rest }) {
  const inputId = id || rest.name;
  return (
    <div className="ds-field">
      {label && (
        <label className="ds-label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <textarea id={inputId} className={`ds-input ${className}`} {...rest} />
      {error && <p className="ds-field-error">{error}</p>}
    </div>
  );
}
