import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";

// When built for a sub-path (e.g. GitHub Pages at /<repo>/), Vite injects
// BASE_URL; the router needs the same prefix or deep links won't resolve.
const basename = (import.meta.env.BASE_URL || "/").replace(/\/+$/, "") || undefined;

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter basename={basename}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
