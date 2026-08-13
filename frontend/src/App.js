import { useCallback, useEffect, useMemo, useState } from "react";
import Sidebar from "./components/Sidebar";
import BoardHeader from "./components/BoardHeader";
import FileUpload from "./components/FileUpload";
import CEOInput from "./components/CEOInput";
import DiscussionTimeline from "./components/DiscussionTimeline";
import BoardSynthesis from "./components/BoardSynthesis";
import LoadingState from "./components/LoadingState";
import ErrorMessage from "./components/ErrorMessage";
import { api } from "./services/api";
import { boardResultToTimeline, extractLatestBoardFromMessages } from "./utils/boardDisplay";
import "./App.css";

function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [sessionDetail, setSessionDetail] = useState(null);
  const [latestSynthesis, setLatestSynthesis] = useState(null);
  const [currentBoard, setCurrentBoard] = useState(null);
  const [health, setHealth] = useState({ openai_configured: false });
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [creating, setCreating] = useState(false);
  const [discussing, setDiscussing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [uploadSummary, setUploadSummary] = useState(null);
  const [error, setError] = useState("");

  const refreshSessions = useCallback(async () => {
    const list = await api.listSessions();
    setSessions(list);
    return list;
  }, []);

  const loadSession = useCallback(async (sessionId) => {
    if (!sessionId) {
      setSessionDetail(null);
      setLatestSynthesis(null);
      setCurrentBoard(null);
      setUploadSummary(null);
      return;
    }
    setLoadingSession(true);
    try {
      const detail = await api.getSession(sessionId);
      const extracted = extractLatestBoardFromMessages(detail.messages);
      setSessionDetail(detail);
      setCurrentBoard(extracted);
      setLatestSynthesis(extracted?.synthesis || null);
    } finally {
      setLoadingSession(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [healthData, list] = await Promise.all([api.health(), api.listSessions()]);
        if (cancelled) return;
        setHealth(healthData);
        setSessions(list);
        if (list.length) {
          setActiveSessionId(list[0].id);
          await loadSession(list[0].id);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err.message ||
              "Could not reach the API. Start the FastAPI backend on port 8000."
          );
        }
      } finally {
        if (!cancelled) setLoadingSessions(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSession]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || sessionDetail,
    [sessions, activeSessionId, sessionDetail]
  );

  const handleCreateSession = async () => {
    setCreating(true);
    setError("");
    try {
      const created = await api.createSession("New Board Session");
      await refreshSessions();
      setActiveSessionId(created.id);
      await loadSession(created.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleSelectSession = async (sessionId) => {
    setError("");
    setActiveSessionId(sessionId);
    try {
      await loadSession(sessionId);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDeleteSession = async (sessionId) => {
    setError("");
    try {
      await api.deleteSession(sessionId);
      const list = await refreshSessions();
      if (activeSessionId === sessionId) {
        const next = list[0]?.id || null;
        setActiveSessionId(next);
        await loadSession(next);
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const handleAskBoard = async (question) => {
    if (!activeSessionId || discussing) return;
    setDiscussing(true);
    setError("");
    setLatestSynthesis(null);
    setCurrentBoard(null);
    try {
      const result = await api.askBoard(activeSessionId, question);
      setLatestSynthesis(result.synthesis);
      setCurrentBoard({
        question: result.question,
        discussion: result.discussion,
        synthesis: result.synthesis,
      });
      await refreshSessions();
      await loadSession(activeSessionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setDiscussing(false);
    }
  };

  const handleUpload = async (file) => {
    if (!activeSessionId) {
      setError("Create or select a session before uploading company data.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const result = await api.uploadFile(activeSessionId, file);
      if (result?.summary) {
        setUploadSummary(result.summary);
      }
      await refreshSessions();
      await loadSession(activeSessionId);
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="app-shell">
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelectSession={handleSelectSession}
        onCreateSession={handleCreateSession}
        onDeleteSession={handleDeleteSession}
        creating={creating}
      />

      <main className="main-stage">
        <div className="stage-backdrop" aria-hidden="true" />
        <div className="stage-inner">
          <BoardHeader
            sessionTitle={activeSession?.title}
            openaiConfigured={Boolean(health?.openai_configured)}
            llmMode={health?.llm_mode}
          />

          <ErrorMessage message={error} onDismiss={() => setError("")} />

          {loadingSessions ? (
            <p className="boot-copy">Loading boardroom...</p>
          ) : !activeSessionId ? (
            <section className="empty-hero">
              <h3>Convene your first board</h3>
              <p>
                Create a session, optionally upload company metrics, then ask the CEO question that
                needs a cross-functional answer.
              </p>
              <button type="button" className="btn btn-primary" onClick={handleCreateSession}>
                + New Board Session
              </button>
            </section>
          ) : (
            <>
              <FileUpload
                onUpload={handleUpload}
                uploading={uploading}
                disabled={discussing}
                uploads={sessionDetail?.uploads || []}
                uploadSummary={uploadSummary}
              />

              <CEOInput onSubmit={handleAskBoard} disabled={discussing} />

              <LoadingState active={discussing} />

              {loadingSession ? (
                <p className="boot-copy">Loading session...</p>
              ) : (
                <>
                  {currentBoard?.question && (
                    <section className="current-question-panel">
                      <div className="panel-label">
                        <h3>Current CEO Question</h3>
                      </div>
                      <p className="current-question-text">{currentBoard.question}</p>
                    </section>
                  )}

                  <DiscussionTimeline timeline={boardResultToTimeline(currentBoard)} />

                  {currentBoard?.question ? (
                    <BoardSynthesis
                      synthesis={latestSynthesis || currentBoard?.synthesis}
                      question={currentBoard.question}
                    />
                  ) : null}
                </>
              )}

              {!discussing && (sessionDetail?.messages?.length || 0) > 0 && (
                <p className="continue-hint">
                  Continue the conversation by asking a follow-up as CEO above.
                </p>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
