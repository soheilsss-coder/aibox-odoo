import React from "react";

// Design System (roadmap #45). Every page in this app should reach
// for this component instead of a raw <button> - that's what turns
// "a shared palette" (tokens.css, the pre-phase-7 state of #45) into
// an actual reusable component library, the gap #45 named explicitly.
//
// variant: "primary" (default) | "danger" | "ghost"
// size: "md" (default) | "sm"
export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  disabled = false,
  children,
  className = "",
  ...rest
}) {
  const classes = ["ds-btn", `ds-btn-${variant}`, `ds-btn-${size}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <button className={classes} disabled={disabled || loading} {...rest}>
      {loading ? "..." : children}
    </button>
  );
}
