import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import EpisodePicker from "./EpisodePicker";

const ACTION_LABELS = {
  in_progress: "Start work",
  delivered: "Mark delivered",
  accepted: "Accept delivery",
  rejected: "Reject delivery",
};

export default function RequestDetail({ id, user, onBack }) {
  const [request, setRequest] = useState(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    api(`/requests/${id}`).then(setRequest).catch((e) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  // Every mutation returns the fresh request detail, so we just replace our copy.
  async function run(action) {
    setError(null);
    try {
      setRequest(await action());
      setNote("");
    } catch (err) {
      setError(err.message);
    }
  }
  const transition = (to) => run(() => api(`/requests/${id}/transitions`, {
    method: "POST", body: { to_status: to, note: note || null },
  }));
  const assign = (ids) => run(() => api(`/requests/${id}/assignments`, { method: "POST", body: { episode_ids: ids } }));
  const unassign = (episodeId) => run(() => api(
    `/requests/${id}/assignments/${encodeURIComponent(episodeId)}`, { method: "DELETE" },
  ));

  if (!request) return error ? <p className="error">{error}</p> : <p>Loading…</p>;
  const canEditEpisodes = user.role !== "client" && request.status === "in_progress";

  return (
    <section>
      <button onClick={onBack}>← Back</button>
      <h2>Request #{request.id}: {request.task_name} <span className={`badge ${request.status}`}>{request.status.replace("_", " ")}</span></h2>
      <p>
        Client: {request.client_name} · Deadline: {request.deadline} ·
        Assigned: <strong>{request.assigned_count} / {request.episodes_requested}</strong>
      </p>
      {request.notes && <p className="notes">{request.notes}</p>}
      {error && <p className="error">{error}</p>}

      {request.allowed_transitions.length > 0 && (
        <div className="row">
          <input placeholder="Note (optional, e.g. why you reject)" value={note} onChange={(e) => setNote(e.target.value)} />
          {request.allowed_transitions.map((to) => (
            <button key={to} onClick={() => transition(to)}>{ACTION_LABELS[to]}</button>
          ))}
        </div>
      )}

      <h3>Assigned episodes</h3>
      <table>
        <thead><tr><th>Episode</th><th>Robot</th><th>Task</th><th>Quality</th><th>Recorded</th><th /></tr></thead>
        <tbody>
          {request.assignments.map((e) => (
            <tr key={e.episode_id}>
              <td>{e.episode_id}</td><td>{e.robot_id}</td><td>{e.task_name}</td><td>{e.quality}</td>
              <td>{new Date(e.recorded_at).toLocaleString()}</td>
              <td>{canEditEpisodes && <button onClick={() => unassign(e.episode_id)}>Unassign</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {canEditEpisodes && <EpisodePicker defaultTask={request.task_name} onAssign={assign} refreshKey={request.assigned_count} />}

      <h3>History</h3>
      <ul className="history">
        {request.history.map((h, i) => (
          <li key={i}>
            {new Date(h.created_at).toLocaleString()}: <strong>{h.actor_name}</strong> {h.from_status ?? "created"} → {h.to_status}
            {h.note && <em> — “{h.note}”</em>}
          </li>
        ))}
      </ul>
    </section>
  );
}
