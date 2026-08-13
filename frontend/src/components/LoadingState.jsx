import "./LoadingState.css";

const STEPS = [
  "CFO analyzing financial impact...",
  "CMO assessing growth tradeoffs...",
  "COO checking operational feasibility...",
  "CSO evaluating strategic implications...",
  "Executives challenging each other...",
  "Synthesizing board recommendation...",
];

function LoadingState({ active }) {
  if (!active) return null;

  return (
    <div className="loading-state" role="status" aria-live="polite">
      <div className="loading-orb" />
      <div>
        <h3>Board is discussing...</h3>
        <ul>
          {STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default LoadingState;
