import React, { useState } from "react";
import { login, clearApiKey, getMe, ApiError } from "../api/client.js";
import { Card, Input, Button, Alert } from "../components";

// v24: this used to ask the user to paste in a raw API key ("get it
// from your admin"). Every onboarded employee already has a normal
// email + password (see onboarding/onboard_from_excel.py) - there is
// no reason to make them separately handle a 48-character key by hand
// day to day. This screen now takes login/password like any ordinary
// app; /api/login (backend) checks the real Odoo credentials once and
// hands back that same user's existing API key, which is then stored
// exactly as before and used for every request after this one.
export default function LoginPage({ onLoggedIn }) {
  // In `vite dev` (import.meta.env.DEV) the form is pre-filled with demo
  // credentials - one click on «ورود» is enough. In production builds this
  // compiles to the original empty form; nothing changes for real users.
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
      setError(err instanceof ApiError ? err.message : "اتصال برقرار نشد");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="main" style={{ maxWidth: 380, margin: "80px auto" }}>
      <Card>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>ورود</h1>
        <p className="muted">
          با ایمیل و رمز عبوری که هنگام راه‌اندازی برایتان ساخته شده وارد
          شوید.
        </p>
        <form onSubmit={handleSubmit}>
          <Input
            type="text"
            placeholder="ایمیل"
            value={loginId}
            onChange={(e) => setLoginId(e.target.value)}
            autoFocus
            autoComplete="username"
          />
          <Input
            type="password"
            placeholder="رمز عبور"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
          <Alert>{error}</Alert>
          <Button type="submit" disabled={!loginId || !password} loading={loading}>
            ورود
          </Button>
        </form>
      </Card>
    </div>
  );
}
