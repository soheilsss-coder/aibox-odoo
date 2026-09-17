import React from "react";

export default function TextArea({ label, className = "", id, ...rest }) {
  const el = <textarea id={id} className={`textarea ${className}`} {...rest} />;
  if (!label) return el;
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {el}
    </div>
  );
}
