import { useState } from "react";
import "./CEOInput.css";

function CEOInput({ onSubmit, disabled }) {
  const [question, setQuestion] = useState("");

  const handleSubmit = (event) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setQuestion("");
  };

  return (
    <section className="ceo-panel">
      <div className="panel-label">
        <span className="role-badge ceo">CEO</span>
        <h3>Ask the Board</h3>
      </div>
      <form onSubmit={handleSubmit}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder='Example: "Our Q3 margins dropped by 4 percentage points. What should we do?"'
          rows={4}
          disabled={disabled}
        />
        <div className="ceo-actions">
          <p>Your question opens a multi-round discussion across CFO, CMO, COO, and CSO.</p>
          <button type="submit" className="btn btn-primary" disabled={disabled || !question.trim()}>
            {disabled ? "Board is discussing..." : "Ask the Board"}
          </button>
        </div>
      </form>
    </section>
  );
}

export default CEOInput;
