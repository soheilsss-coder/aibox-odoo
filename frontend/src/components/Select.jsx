import React from "react";

// options: [{ value, label }]
export default function Select({ label, error, id, options = [], placeholder, className = "", ...rest }) {
  const inputId = id || rest.name;
  return (
    <div className="ds-field">
      {label && (
        <label className="ds-label" htmlFor={inputId}>
          {label}
        </label>
      )}
      <select id={inputId} className={`ds-input ds-select ${className}`} {...rest}>
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {error && <p className="ds-field-error">{error}</p>}
    </div>
  );
}
