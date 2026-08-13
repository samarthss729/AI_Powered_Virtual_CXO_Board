import "./BoardHeader.css";

function BoardHeader({ sessionTitle, openaiConfigured, llmMode }) {
  const isDemo = llmMode === "demo";
  const ready = isDemo || openaiConfigured;
  const statusLabel = isDemo ? "Demo mode" : openaiConfigured ? "LLM ready" : "API key needed";

  return (
    <header className="board-header">
      <div>
        <p className="board-eyebrow">Virtual Executive Leadership Team</p>
        <h2>AI Boardroom</h2>
        <p className="board-session-title">
          {sessionTitle ? `Current session: ${sessionTitle}` : "Select or create a session"}
        </p>
      </div>
      <div className={`status-pill ${ready ? "ok" : "warn"}`}>
        {statusLabel}
      </div>
    </header>
  );
}

export default BoardHeader;
