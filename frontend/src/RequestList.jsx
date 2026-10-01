import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

const LIVE_EVENTS = ["request.created", "request.status_changed", "request.assignments_changed"];

export default function RequestList({ user, onOpen, onNew }) {
  const [requests, setRequests] = useState([]);
  const [error, setError] = useState(null);
  const isStaff = user.role !== "client";

  const load = useCallback(() => {
    api("/requests").then(setRequests).catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load]);

  // Staff get live updates: the server pushes an event, and we refetch the list.
  useEffect(() => {
    if (!isStaff) return undefined;
    const source = new EventSource("/api/events");
    LIVE_EVENTS.forEach((type) => source.addEventListener(type, load));
    return () => source.close();
  }, [isStaff, load]);

  return (
    <section>
      <div className="toolbar">
        <h2>{isStaff ? "All requests" : "My requests"}</h2>
        {isStaff ? <span className="muted">● live</span> : <button onClick={onNew}>New request</button>}
      </div>
      {error && <p className="error">{error}</p>}
      <table>
        <thead>
          <tr><th>#</th>{isStaff && <th>Client</th>}<th>Task</th><th>Assigned</th><th>Deadline</th><th>Status</th></tr>
        </thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id} className="clickable" onClick={() => onOpen(r.id)}>
              <td>{r.id}</td>
              {isStaff && <td>{r.client_name}</td>}
              <td>{r.task_name}</td>
              <td>{r.assigned_count} / {r.episodes_requested}</td>
              <td>{r.deadline}</td>
              <td><span className={`badge ${r.status}`}>{r.status.replace("_", " ")}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      {requests.length === 0 && <p className="muted">No requests yet.</p>}
    </section>
  );
}
