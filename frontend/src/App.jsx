import { useEffect, useState } from "react";
import { api } from "./api";
import Login from "./Login";
import NewRequestForm from "./NewRequestForm";
import RequestDetail from "./RequestDetail";
import RequestList from "./RequestList";

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = checking session, null = logged out
  const [view, setView] = useState({ name: "list" });

  useEffect(() => {
    api("/auth/me").then(setUser).catch(() => setUser(null));
    const onExpired = () => setUser(null);
    window.addEventListener("session-expired", onExpired);
    return () => window.removeEventListener("session-expired", onExpired);
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setUser(null);
    setView({ name: "list" });
  }

  if (user === undefined) return <p className="page">Loading…</p>;
  if (user === null) return <Login onLogin={setUser} />;

  const showList = () => setView({ name: "list" });
  return (
    <div className="page">
      <header>
        <h1><a href="#" onClick={showList}>Dataset Request Desk</a></h1>
        <span>{user.name} · {user.role} <button onClick={logout}>Log out</button></span>
      </header>
      {view.name === "list" && (
        <RequestList user={user} onOpen={(id) => setView({ name: "detail", id })}
                     onNew={() => setView({ name: "new" })} />
      )}
      {view.name === "new" && (
        <NewRequestForm onCreated={(id) => setView({ name: "detail", id })} onCancel={showList} />
      )}
      {view.name === "detail" && <RequestDetail id={view.id} user={user} onBack={showList} />}
    </div>
  );
}
