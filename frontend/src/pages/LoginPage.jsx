import React, { useState } from "react";
import { login, clearApiKey, getMe, ApiError } from "../api/client.js";
import { Alert, Button, Input } from "../components";

// Login screen: the employee's front door. Trades email+password for a
// session (cookie; the dev backend also returns an api_key the client then
// sends as X-API-Key so auth survives third-party iframe previews).
// Forms are pre-filled in `vite dev` and in the static GitHub Pages demo
// build (any credentials work there); real production builds stay empty.
export default function LoginPage({ onLoggedIn }) {
  const DEMO = Boolean(import.meta.env && (import.meta.env.DEV || import.meta.env.VITE_DEMO_MODE === "1"));
  const STATIC_DEMO = import.meta.env.VITE_DEMO_MODE === "1";
  // Dev-server runs talk to the REAL appliance (sandbox/codespaces): its
  // bootstrap account is admin/admin. The static GitHub Pages demo keeps the
  // fictional sara@example.com persona. Pre-filling the WRONG defaults here
  // made people hit "invalid email or password" on a working appliance.
  const APPLIANCE_CREDS = STATIC_DEMO ? ["sara@example.com", "demo"] : ["admin", "admin"];
  const [loginId, setLoginId] = useState(DEMO ? APPLIANCE_CREDS[0] : "");
  const [password, setPassword] = useState(DEMO ? APPLIANCE_CREDS[1] : "");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(loginId.trim(), password);
      const user = await getMe();
      onLoggedIn(user);
    } catch (err) {
      clearApiKey();
      setError(err instanceof ApiError ? err.message : "Could not connect.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-wrap">
      <span className="auth-blob b1" />
      <span className="auth-blob b2" />
      <span className="auth-blob b3" />

      <div className="auth-card">
        <div className="orb-glow" style={{ display: "inline-block" }}>
          <span className="orb" />
        </div>
        <h1>Welcome back</h1>
        <p className="sub">Sign in with the work email and password you were given at onboarding.</p>

        <form onSubmit={handleSubmit}>
          <Input
            id="login-email"
            type="text"
            label="Email"
            placeholder="you@company.com"
            value={loginId}
            onChange={(e) => setLoginId(e.target.value)}
            autoFocus
            autoComplete="username"
          />
          <Input
            id="login-password"
            type="password"
            label="Password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <Alert>{error}</Alert>
          <Button variant="primary" size="lg" type="submit" className="btn-block" disabled={!loginId || !password} loading={loading}>
            Sign in
          </Button>
        </form>

        <div className="auth-foot">
          Nova Enterprise · AI Operating System
          {STATIC_DEMO && (
            <div className="small muted mt-2">Static demo build — running fully in your browser, any credentials work.</div>
          )}
          {!STATIC_DEMO && DEMO && (
            <div className="small muted mt-2">
              Appliance demo — bootstrap admin <b>admin / admin</b>, seeded staff <b>demo.*@yourbrand.example / demo</b>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
