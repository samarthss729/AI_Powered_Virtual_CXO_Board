import ExecutiveCard from "./ExecutiveCard";
import "./DiscussionTimeline.css";

function DiscussionTimeline({ timeline, messages, liveDiscussion }) {
  let items = timeline || [];

  // Legacy fallback: isolate latest CEO cycle from persisted messages.
  if (!items.length && messages?.length) {
    let lastCeoIndex = -1;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === "CEO") {
        lastCeoIndex = i;
        break;
      }
    }
    if (lastCeoIndex >= 0) {
      items = messages
        .slice(lastCeoIndex)
        .filter((msg) => msg.role !== "SYNTHESIS")
        .map((msg) => ({
          key: `msg-${msg.id}`,
          role: msg.role,
          speaker: msg.speaker,
          content: msg.content,
          round: msg.round,
        }));
    }
  } else if (!items.length && liveDiscussion?.length) {
    items = liveDiscussion.map((entry, index) => ({
      key: `live-${index}`,
      role: entry.role,
      content: entry.content,
      round: entry.round,
    }));
  }

  if (!items.length) {
    return (
      <section className="discussion-panel">
        <div className="panel-label">
          <h3>Board Discussion</h3>
          <p>Ask a question to start a two-round executive debate.</p>
        </div>
        <div className="discussion-empty">
          The board is seated. When you ask a question, each executive will analyze independently,
          then challenge one another before a synthesis is formed.
        </div>
      </section>
    );
  }

  return (
    <section className="discussion-panel">
      <div className="panel-label">
        <h3>Board Discussion</h3>
        <p>Round 1: independent views · Round 2: cross-challenge</p>
      </div>
      <div className="discussion-timeline">
        {items.map((item, index) => {
          const prevRound = index > 0 ? items[index - 1].round : null;
          const showRoundHeader =
            item.round != null && item.round !== prevRound && item.role !== "CEO";
          return (
            <div key={item.key}>
              {showRoundHeader && (
                <div className={`round-divider round-${item.round}`}>
                  Round {item.round} — {item.round === 1 ? "Independent views" : "Cross-challenge"}
                </div>
              )}
              <ExecutiveCard
                role={item.role}
                speaker={item.speaker}
                content={item.content}
                round={item.round}
              />
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default DiscussionTimeline;
