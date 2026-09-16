import React from "react";

// options: [{ value, label }] ; placeholder adds a leading disabled option.
export default function Select({ label, options = [], placeholder, className = "", id, ...rest }) {
  const el = (
    <select id={id} className={`select ${className}`} {...rest}>
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
  if (!label) return el;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {el}
    </div>
  );
}
