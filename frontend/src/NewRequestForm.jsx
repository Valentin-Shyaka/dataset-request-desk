import { useState } from "react";
import { api } from "./api";

export default function NewRequestForm({ onCreated, onCancel }) {
  const [form, setForm] = useState({ task_name: "", episodes_requested: 10, deadline: "", notes: "" });
  const [error, setError] = useState(null);
  const update = (field) => (e) => setForm({ ...form, [field]: e.target.value });

  async function submit(event) {
    event.preventDefault();
    setError(null);
    try {
      const created = await api("/requests", {
        method: "POST",
        body: { ...form, episodes_requested: Number(form.episodes_requested) },
      });
      onCreated(created.id);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="narrow" onSubmit={submit}>
      <h2>New dataset request</h2>
      <label>Task name<input value={form.task_name} onChange={update("task_name")} placeholder="pick cup" required /></label>
      <label>Episodes needed<input type="number" min="1" value={form.episodes_requested} onChange={update("episodes_requested")} required /></label>
      <label>Deadline<input type="date" value={form.deadline} onChange={update("deadline")} required /></label>
      <label>Notes<textarea value={form.notes} onChange={update("notes")} /></label>
      {error && <p className="error">{error}</p>}
      <div className="row"><button type="submit">Submit</button><button type="button" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}
