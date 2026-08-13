import "./BoardSynthesis.css";

function BoardSynthesis({ synthesis, question }) {
  const data = synthesis;

  if (!data) {
    return (
      <section className="synthesis-panel">
        <div className="panel-label">
          <span className="role-badge synthesis">Board</span>
          <h3>Board Recommendation</h3>
          {question ? <p className="synthesis-question-ref">Answering: {question}</p> : null}
        </div>
        <p className="synthesis-unavailable">Board recommendation unavailable for this question.</p>
      </section>
    );
  }

  return (
    <section className="synthesis-panel">
      <div className="panel-label">
        <span className="role-badge synthesis">Board</span>
        <h3>Board Recommendation</h3>
        {question ? <p className="synthesis-question-ref">Answering: {question}</p> : null}
      </div>

      <div className="synthesis-grid">
        <div className="synthesis-main">
          <h4>Primary recommendation</h4>
          <p>{data.recommendation}</p>
        </div>
        <div className="confidence-box">
          <span>Confidence</span>
          <strong className={`confidence-${(data.confidence || "medium").toLowerCase()}`}>
            {data.confidence || "Medium"}
          </strong>
        </div>
      </div>

      <div className="synthesis-columns">
        <div>
          <h4>Key disagreements</h4>
          <ul>
            {(data.disagreements || []).length ? (
              data.disagreements.map((item) => <li key={item}>{item}</li>)
            ) : (
              <li className="muted-item">Broad alignment across executives</li>
            )}
          </ul>
        </div>
        <div>
          <h4>Key risks</h4>
          <ul>
            {(data.key_risks || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Recommended actions</h4>
          <ol>
            {(data.actions || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </div>
        <div>
          <h4>Metrics to monitor</h4>
          <ul>
            {(data.metrics || []).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export default BoardSynthesis;
