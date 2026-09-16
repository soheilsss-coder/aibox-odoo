import React, { useEffect } from "react";
import { IconButton } from "./Button.jsx";

export default function Modal({ open, title, onClose, children, footer, maxWidth }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && onClose && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" style={maxWidth ? { maxWidth } : undefined}>
        <div className="modal-head">
          <h3>{title}</h3>
          <IconButton icon="x" label="Close" onClick={onClose} />
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : <div style={{ height: 14 }} />}
      </div>
    </div>
  );
}
