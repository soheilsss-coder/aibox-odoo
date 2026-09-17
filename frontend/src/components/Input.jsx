import React from "react";

export default function Input({ label, className = "", id, ...rest }) {
  const input = <input id={id} className={`input ${className}`} {...rest} />;
  if (!label) return input;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {input}
    </div>
  );
}
