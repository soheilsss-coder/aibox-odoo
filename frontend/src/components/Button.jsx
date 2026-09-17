import React from "react";
import Icon from "./Icon.jsx";

// variants: primary | gradient | ghost | soft | danger ; sizes: sm | md | lg
export default function Button({
  variant = "default",
  size = "md",
  loading = false,
  icon = null,
  iconRight = null,
  className = "",
  children,
  disabled,
  ...rest
}) {
  const cls = [
    "btn",
    variant === "primary" && "btn-primary",
    variant === "gradient" && "btn-gradient",
    variant === "ghost" && "btn-ghost",
    variant === "soft" && "btn-soft",
    variant === "danger" && "btn-danger",
    size === "sm" && "btn-sm",
    size === "lg" && "btn-lg",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button className={cls} disabled={disabled || loading} {...rest}>
      {loading ? <span className="btn-spinner" /> : icon ? (typeof icon === "string" ? <Icon name={icon} size={16} /> : icon) : null}
      {children}
      {iconRight && !loading ? (typeof iconRight === "string" ? <Icon name={iconRight} size={16} /> : iconRight) : null}
    </button>
  );
}

export function IconButton({ icon, className = "", label, ...rest }) {
  return (
    <button
      className={`btn btn-ghost btn-icon ${className}`}
      aria-label={label}
      title={label}
      {...rest}
    >
      <Icon name={icon} size={18} />
    </button>
  );
}
