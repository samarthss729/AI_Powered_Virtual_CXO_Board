import "./SessionList.css";

function formatDate(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function SessionList({ sessions, activeSessionId, onSelectSession, onDeleteSession }) {
  if (!sessions.length) {
    return <p className="session-empty">No sessions yet. Create one to convene the board.</p>;
  }

  return (
    <ul className="session-list">
      {sessions.map((session) => {
        const active = session.id === activeSessionId;
        return (
          <li key={session.id} className={active ? "session-item active" : "session-item"}>
            <button
              type="button"
              className="session-select"
              onClick={() => onSelectSession(session.id)}
            >
              <span className="session-title">{session.title}</span>
              <span className="session-meta">
                {session.message_count || 0} msgs · {formatDate(session.updated_at)}
              </span>
            </button>
            <button
              type="button"
              className="session-delete"
              aria-label={`Delete ${session.title}`}
              onClick={(e) => {
                e.stopPropagation();
                if (window.confirm(`Delete "${session.title}" and all its messages?`)) {
                  onDeleteSession(session.id);
                }
              }}
            >
              ×
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default SessionList;
