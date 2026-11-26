import { useState } from "react";
import { login } from "./api.js";

export default function LoginPage({ onEnter }) {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      await login(id.trim(), password);
      onEnter();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="login">
      <form className="login-card glass" onSubmit={submit}>
        <p className="login-mark">VERITAS<span>Lite</span></p>
        <h1>Investigator sign-in</h1>
        <p className="muted small">Statement verification for live interviews.</p>
        <label>Username
          <input value={id} onChange={(e) => setId(e.target.value)} autoFocus autoComplete="username" maxLength={64} required />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
            maxLength={256} required />
        </label>
        <button type="submit" className="primary big" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </main>
  );
}
