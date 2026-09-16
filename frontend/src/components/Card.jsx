import React from "react";

export default function Card({ title, actions, children, className = "", hover = false, style }) {
  return (
    <section className={`card ${hover ? "card-hover" : ""} ${className}`} style={style}>
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          {actions ? <div className="h-stack">{actions}</div> : null}
        </header>
      )}
      {children}
    </section>
  );
}
