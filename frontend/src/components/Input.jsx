import React from "react";

// Design System (#45). Thin wrapper - the point is not new behavior,
// it's ONE place that owns the visual treatment of every text/date/
// password input in the app, plus an optional label so pages stop
// hand-rolling <label>/<input> pairs with slightly different markup
// each time (compare the old LeavesPage.jsx and LoginPage.jsx before
// this existed - same input, two different structures).
export default function Input({ label, error, id, className = "", ...rest }) {
  const inputId = id || rest.name;
  return (
    <div className="ds-field">
      {label && (
        <label className="ds-label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <input id={inputId} className={`ds-input ${className}`} {...rest} />
      {error && <p className="ds-field-error">{error}</p>}
    </div>
  );
}
