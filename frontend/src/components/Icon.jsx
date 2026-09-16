import React from "react";

// Minimal stroke icon set (lucide-style). Usage: <Icon name="spark" size={18} />
const PATHS = {
  spark: <path d="M12 3v3m0 12v3M5.2 5.2l2.1 2.1m9.4 9.4 2.1 2.1M3 12h3m12 0h3M5.2 18.8l2.1-2.1m9.4-9.4 2.1-2.1M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z" />,
  plus: <path d="M12 5v14M5 12h14" />,
  send: <path d="M12 19V5m0 0-6 6m6-6 6 6" />,
  paperclip: <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />,
  mic: <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Zm7 10a7 7 0 0 1-14 0M12 19v3" />,
  stop: <path d="M6 6h12v12H6z" />,
  tasks: <path d="m3 6 1.5 1.5L7.5 4m3 3h10M3 13l1.5 1.5L7.5 11m3 3h10M3 20l1.5 1.5L7.5 18m3 3h10" />,
  calendar: <path d="M8 2v4m8-4v4M3 9h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" />,
  building: <path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M9 19h1m4 0h1" />,
  file: <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Zm0 0v6h6M9 13h6m-6 4h4" />,
  database: <path d="M12 8c4.97 0 9-1.34 9-3s-4.03-3-9-3-9 1.34-9 3 4.03 3 9 3Zm9 2c0 1.66-4.03 3-9 3s-9-1.34-9-3m18 5c0 1.66-4.03 3-9 3s-9-1.34-9-3M3 5v10m18-10v10" />,
  shield: <path d="M12 22s8-3.58 8-10V5l-8-3-8 3v7c0 6.42 8 10 8 10Zm-3-9.5 2 2 4-4" />,
  bot: <path d="M12 8V4H8m8 4h1a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h1m6 0H9m6 0-2-2M9 8l2-2m-2.5 9h.01m5 0h.01" />,
  bell: <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9m4.3 13a1.94 1.94 0 0 0 3.4 0" />,
  plug: <path d="M9 7V3m6 4V3M6 7h12v4a6 6 0 0 1-12 0V7Zm6 10v4" />,
  cog: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2.1-1.2L14.5 3h-4l-.4 2.6a7 7 0 0 0-2 1.2l-2.5-1-2 3.4 2.1 1.6a7.5 7.5 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2.1 1.2l.4 2.6h4l.4-2.6a7 7 0 0 0 2-1.2l2.5 1 2-3.4-2.1-1.6c.06-.4.1-.8.1-1.2Z" />,
  logout: <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5m5 5H9" />,
  sun: <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm0-15v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.3 6.3l1.4-1.4" />,
  moon: <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  x: <path d="M18 6 6 18M6 6l12 12" />,
  trash: <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m5 5v6m4-6v6" />,
  upload: <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4m14-7-5-5-5 5m5-5v12" />,
  refresh: <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />,
  alert: <path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />,
  info: <path d="M12 16v-4m0-4h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
  check: <path d="m5 12 5 5 9-10" />,
  checkCircle: <path d="m8.5 12.2 2.4 2.3 4.6-5M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
  search: <path d="M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.3-4.3" />,
  clock: <path d="M12 6v6l4 2m6-2a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z" />,
  copy: <path d="M9 9h10a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Zm-4 6H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />,
  arrowRight: <path d="M5 12h14m-6-6 6 6-6 6" />,
  users: <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2m22 0v-2a4 4 0 0 0-3-3.87M16 3.13A4 4 0 0 1 16 11M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" />,

  inbox: <path d="M22 12h-6l-2 3h-4l-2-3H2m2-7.5L5.5 3h13L20 4.5M2 7v11a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7" />,
  zap: <path d="M13 2 3 14h8l-1 8 11-13h-9l1-7Z" />,
  link: <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />,
  unlink: <path d="m18.84 12.25 1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71m-5.65 9.57-1.72 1.71a5 5 0 0 0 7.07 7.07l1.72-1.71M8 2v2m8 4h2M4 12H2m17 8v2M2 2l20 20" />,
  home: <path d="m3 10 9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V10Zm6 11v-7h6v7" />,
  message: <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10Z" />,
};

export default function Icon({ name, size = 18, strokeWidth = 1.9, className = "", style }) {
  const path = PATHS[name] || PATHS.spark;
  return (
    <svg
      className={className}
      style={style}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {path}
    </svg>
  );
}
