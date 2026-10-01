export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// The session is an HttpOnly cookie: the browser sends it automatically, and JS never sees it.
export async function api(path, { method = "GET", body } = {}) {
  const response = await fetch(`/api${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 401 && path !== "/auth/login" && path !== "/auth/me") {
    window.dispatchEvent(new Event("session-expired"));
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, describeError(data) ?? response.statusText);
  return data;
}

function describeError(data) {
  if (!data?.detail) return null;
  if (typeof data.detail === "string") return data.detail;
  // FastAPI validation errors look like [{loc: ["body", "deadline"], msg: "..."}]
  return data.detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ");
}
