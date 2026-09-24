import React from "react";

export default function Spinner({ label = "در حال بارگذاری..." }) {
  return (
    <div className="ds-spinner-row">
      <span className="ds-spinner" aria-hidden="true" />
      <span className="muted">{label}</span>
    </div>
  );
}
