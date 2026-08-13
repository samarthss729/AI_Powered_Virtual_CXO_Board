import "./FileUpload.css";

function FileUpload({ onUpload, uploading, disabled, uploads, uploadSummary }) {
  const handleChange = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    await onUpload(file);
  };

  const latest = uploads?.[uploads.length - 1];

  return (
    <section className="upload-panel">
      <div className="panel-label">
        <h3>Company Data</h3>
        <p>Upload CSV or JSON so executives can ground their advice in your numbers.</p>
      </div>
      <label className={`upload-button ${disabled ? "disabled" : ""}`}>
        <input
          type="file"
          accept=".csv,.json,application/json,text/csv"
          onChange={handleChange}
          disabled={disabled || uploading}
        />
        {uploading ? "Uploading..." : "Upload CSV / JSON"}
      </label>
      {latest ? (
        <div className="upload-status-block">
          <p className="upload-status">Attached: {latest.filename}</p>
          {uploadSummary ? (
            <p className="upload-summary">
              {uploadSummary.format?.toUpperCase()} · {uploadSummary.record_count} records
              {uploadSummary.fields?.length ? ` · ${uploadSummary.fields.length} fields` : ""}
            </p>
          ) : latest.preview ? (
            <p className="upload-summary muted">Data loaded and ready for board analysis</p>
          ) : null}
        </div>
      ) : (
        <p className="upload-status muted">No company data attached yet.</p>
      )}
    </section>
  );
}

export default FileUpload;
