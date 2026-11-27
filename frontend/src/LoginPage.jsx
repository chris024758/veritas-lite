import { useState } from "react";

const KEY = "veritas-signed-in";

// Shown once when the app starts (per browser tab). There is no real sign-in yet: any or no
// ID and password lets you in.
export function useSignIn() {
  const [signedIn, setSignedIn] = useState(() => {
    try { return sessionStorage.getItem(KEY) === "1"; } catch { return false; }
  });
  const signIn = () => {
    try { sessionStorage.setItem(KEY, "1"); } catch { /* private mode: stays in memory */ }
    setSignedIn(true);
  };
  return [signedIn, signIn];
}

export default function LoginPage({ onEnter }) {
  const [id, setId] = useState("");
  const [password, setPassword] = useState("");
  return (
    <main className="login">
      <form className="login-card glass" onSubmit={(e) => { e.preventDefault(); onEnter(); }}>
        <p className="login-mark">VERITAS<span>Lite</span></p>
        <h1>Investigator sign-in</h1>
        <p className="muted small">Statement verification for live interviews.</p>
        <label>Investigator ID
          <input value={id} onChange={(e) => setId(e.target.value)} autoFocus placeholder="e.g. PUN-INV-042" autoComplete="off" />
        </label>
        <label>Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="off" />
        </label>
        <button type="submit" className="primary big">Enter</button>
        <p className="muted small login-note">Demo build: press Enter to continue. No credentials are checked or stored.</p>
      </form>
    </main>
  );
}
