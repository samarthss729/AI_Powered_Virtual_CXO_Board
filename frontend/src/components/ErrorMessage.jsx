import "./ErrorMessage.css";

function ErrorMessage({ message, onDismiss }) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      <div>
        <strong>Something went wrong</strong>
        <p>{message}</p>
      </div>
      {onDismiss && (
        <button type="button" className="btn btn-ghost" onClick={onDismiss}>
          Dismiss
        </button>
      )}
    </div>
  );
}

export default ErrorMessage;
