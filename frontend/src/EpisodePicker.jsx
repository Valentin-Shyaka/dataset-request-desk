import { useEffect, useState } from "react";
import { api } from "./api";

export default function EpisodePicker({ defaultTask, onAssign, refreshKey }) {
  const [taskName, setTaskName] = useState(defaultTask);
  const [quality, setQuality] = useState("");
  const [page, setPage] = useState({ total: 0, items: [] });
  const [selected, setSelected] = useState(new Set());
  const [error, setError] = useState(null);

  useEffect(() => {
    const params = new URLSearchParams({ unassigned_only: "true", limit: "100" });
    if (taskName) params.set("task_name", taskName);
    if (quality) params.set("quality", quality);
    api(`/episodes?${params}`)
      .then((result) => { setPage(result); setSelected(new Set()); })
      .catch((e) => setError(e.message));
  }, [taskName, quality, refreshKey]);

  function toggle(episodeId) {
    const next = new Set(selected);
    next.has(episodeId) ? next.delete(episodeId) : next.add(episodeId);
    setSelected(next);
  }

  return (
    <div className="picker">
      <h3>Add episodes</h3>
      <div className="row">
        <label>Task <input value={taskName} onChange={(e) => setTaskName(e.target.value)} /></label>
        <label>Quality
          <select value={quality} onChange={(e) => setQuality(e.target.value)}>
            <option value="">any</option><option value="good">good</option>
            <option value="usable">usable</option><option value="bad">bad</option>
          </select>
        </label>
        <button disabled={selected.size === 0} onClick={() => onAssign([...selected])}>
          Assign {selected.size} selected
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <p className="muted">Showing {page.items.length} of {page.total} unassigned episodes. Bad episodes can't be selected.</p>
      <table>
        <thead><tr><th /><th>Episode</th><th>Robot</th><th>Task</th><th>Quality</th><th>Duration</th></tr></thead>
        <tbody>
          {page.items.map((e) => (
            <tr key={e.episode_id}>
              <td><input type="checkbox" disabled={e.quality === "bad"} checked={selected.has(e.episode_id)} onChange={() => toggle(e.episode_id)} /></td>
              <td>{e.episode_id}</td><td>{e.robot_id}</td><td>{e.task_name}</td><td>{e.quality}</td><td>{e.duration_seconds}s</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
