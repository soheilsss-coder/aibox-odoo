import React, { useState } from "react";
import { login, clearApiKey, getMe, ApiError } from "../api/client.js";
import { Alert, Button, Input } from "../components";

// Login screen: the employee's front door. Trades email+password for a
// session (cookie; the dev backend also returns an api_key the client then
// sends as X-API-Key so auth survives third-party iframe previews).
// In `vite dev` the form is pre-filled with demo credentials; production
// builds compile to an empty form.
export default function LoginPage({ onLoggedIn }) {
  const DEV = import.meta.env && import.meta.env.DEV;
  const [loginId, setLoginId] = useState(DEV ? "sara@example.com" : "");
  const [password, setPassword] = useState(DEV ? "demo" : "");
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

        <div className="auth-foot">Nova Enterprise · AI Operating System</div>
      </div>
    </div>
  );
}
