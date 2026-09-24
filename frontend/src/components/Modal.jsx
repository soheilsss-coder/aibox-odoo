import React from "react";

export default function Modal({ open, title, onClose, children, footer }) {
  if (!open) return null;
  return (
    <div className="ds-modal-backdrop" onClick={onClose}>
      <div className="ds-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ds-modal-header">
          <h3 className="ds-card-title">{title}</h3>
          <button className="ds-modal-close" onClick={onClose} aria-label="بستن">
            ×
          </button>
        </div>
        <div className="ds-modal-body">{children}</div>
        {footer && <div className="ds-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
