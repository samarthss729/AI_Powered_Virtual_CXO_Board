import SessionList from "./SessionList";
import "./Sidebar.css";

function Sidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onCreateSession,
  onDeleteSession,
  creating,
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <p className="sidebar-kicker">Executive Suite</p>
        <h1>AI Boardroom</h1>
        <p className="sidebar-sub">Boardroom in a Box</p>
      </div>

      <button
        type="button"
        className="btn btn-primary sidebar-new"
        onClick={onCreateSession}
        disabled={creating}
      >
        {creating ? "Creating..." : "+ New Board Session"}
      </button>

      <div className="sidebar-section">
        <h2>Previous Sessions</h2>
        <SessionList
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={onSelectSession}
          onDeleteSession={onDeleteSession}
        />
      </div>
    </aside>
  );
}

export default Sidebar;
