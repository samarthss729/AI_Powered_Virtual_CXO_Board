const API_BASE = process.env.REACT_APP_API_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (response.status === 204) {
    return null;
  }

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const detail =
      (data && (data.detail || data.message)) ||
      `Request failed (${response.status})`;
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    error.status = response.status;
    error.payload = data;
    throw error;
  }

  return data;
}

export const api = {
  health() {
    return request("/health");
  },

  listSessions() {
    return request("/sessions");
  },

  createSession(title) {
    return request("/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
  },

  getSession(sessionId) {
    return request(`/sessions/${sessionId}`);
  },

  deleteSession(sessionId) {
    return request(`/sessions/${sessionId}`, { method: "DELETE" });
  },

  getMessages(sessionId) {
    return request(`/sessions/${sessionId}/messages`);
  },

  askBoard(sessionId, question) {
    return request(`/sessions/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
  },

  uploadFile(sessionId, file) {
    const form = new FormData();
    form.append("file", file);
    return request(`/sessions/${sessionId}/upload`, {
      method: "POST",
      body: form,
    });
  },
};

export default api;
