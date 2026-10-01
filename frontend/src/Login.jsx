import { useState } from "react";
import { api } from "./api";

export default function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setError(null);
    try {
      onLogin(await api("/auth/login", { method: "POST", body: { email, password } }));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="page narrow" onSubmit={submit}>
      <h1>Dataset Request Desk</h1>
      <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      {error && <p className="error">{error}</p>}
      <button type="submit">Log in</button>
    </form>
  );
}
