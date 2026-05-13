import React, { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  Bot,
  Braces,
  Database,
  MessageSquare,
  RefreshCw,
  Send,
  Settings2,
  Sparkles
} from 'lucide-react';
import { fetchConfig, fetchTraces, sendChat } from './api';
import type { PublicConfig, TraceRecord } from './types';
import './styles.css';

function App() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [message, setMessage] = useState('');
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [activeTrace, setActiveTrace] = useState<TraceRecord | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadInitialData();
  }, []);

  async function loadInitialData() {
    try {
      const [nextConfig, nextTraces] = await Promise.all([fetchConfig(), fetchTraces()]);
      setConfig(nextConfig);
      setSelectedModel(nextConfig.default_model);
      setTraces(nextTraces.traces);
      setActiveTrace(nextTraces.traces[0] ?? null);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load Peppa.');
    }
  }

  async function refreshTraces() {
    try {
      const nextTraces = await fetchTraces();
      setTraces(nextTraces.traces);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to refresh traces.');
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitMessage();
  }

  async function submitMessage() {
    if (!message.trim() || !selectedModel || isSending) {
      return;
    }

    setIsSending(true);
    setError(null);
    try {
      const result = await sendChat({
        message,
        model: selectedModel,
        conversationId
      });
      setConversationId(result.conversation_id);
      setActiveTrace(result.trace);
      setMessage('');
      const nextTraces = await fetchTraces();
      setTraces(nextTraces.traces);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : 'Message failed.');
    } finally {
      setIsSending(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submitMessage();
    }
  }

  const activeModel = useMemo(
    () => config?.models.find((model) => model.model === selectedModel),
    [config, selectedModel]
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-icon" aria-hidden="true">
            <Sparkles size={18} />
          </div>
          <div>
            <h1>Peppa Debug Console</h1>
            <p>Local agent runtime</p>
          </div>
        </div>

        <div className="topbar-controls">
          <label className="model-picker">
            <Settings2 size={16} />
            <select
              value={selectedModel}
              onChange={(event) => setSelectedModel(event.target.value)}
              disabled={!config}
              aria-label="Model"
            >
              {config?.models.map((model) => (
                <option value={model.model} key={model.model}>
                  {model.model}
                </option>
              ))}
            </select>
          </label>
          <StatusPill icon={<Activity size={14} />} label="Runtime" value="Running" />
          <StatusPill icon={<Database size={14} />} label="SQLite" value="state" />
        </div>
      </header>

      {error && (
        <div className="error-strip">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      <section className="console-grid">
        <section className="panel chat-panel" aria-label="Chat">
          <div className="panel-header">
            <div>
              <h2>Chat Probe</h2>
              <p>{activeModel?.base_url ?? 'Waiting for config'}</p>
            </div>
            <button className="icon-button" type="button" onClick={() => setConversationId(undefined)}>
              <MessageSquare size={16} />
              <span>New</span>
            </button>
          </div>

          <div className="conversation-window">
            <MessageBubble role="user" content={activeTrace?.user_message ?? 'Send a message to create a trace.'} />
            <MessageBubble
              role="assistant"
              content={activeTrace?.assistant_message ?? activeTrace?.error ?? 'Model output will appear here.'}
              muted={!activeTrace?.assistant_message}
            />
          </div>

          <form className="composer" onSubmit={handleSubmit}>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask Peppa something..."
              rows={4}
            />
            <button className="send-button" type="submit" disabled={isSending || !message.trim()}>
              {isSending ? <RefreshCw className="spin" size={17} /> : <Send size={17} />}
              <span>{isSending ? 'Sending' : 'Send'}</span>
            </button>
          </form>
        </section>

        <aside className="panel trace-list-panel" aria-label="Recent traces">
          <div className="panel-header compact">
            <div>
              <h2>Recent Traces</h2>
              <p>{traces.length} loaded</p>
            </div>
            <button className="icon-button" type="button" onClick={() => void refreshTraces()}>
              <RefreshCw size={16} />
              <span>Refresh</span>
            </button>
          </div>
          <div className="trace-list">
            {traces.map((trace) => (
              <button
                className={trace.id === activeTrace?.id ? 'trace-row active' : 'trace-row'}
                key={trace.id}
                type="button"
                onClick={() => setActiveTrace(trace)}
              >
                <span className="trace-model">{trace.model}</span>
                <span className="trace-message">{trace.user_message}</span>
                <span className={trace.error ? 'trace-state error' : 'trace-state'}>
                  {trace.error ? 'error' : `${trace.duration_ms ?? 0} ms`}
                </span>
              </button>
            ))}
            {traces.length === 0 && <div className="empty-state">No traces yet.</div>}
          </div>
        </aside>
      </section>

      <section className="debug-grid">
        <JsonPanel title="Prompt" icon={<Bot size={16} />} value={activeTrace?.prompt_messages ?? []} />
        <JsonPanel title="Memory Hits" icon={<Database size={16} />} value={activeTrace?.memory_hits ?? []} />
        <JsonPanel title="Request" icon={<Braces size={16} />} value={activeTrace?.request_payload ?? {}} />
        <JsonPanel title="Response" icon={<Braces size={16} />} value={activeTrace?.response_payload ?? {}} />
      </section>
    </main>
  );
}

function StatusPill({
  icon,
  label,
  value
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="status-pill">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MessageBubble({
  role,
  content,
  muted = false
}: {
  role: 'user' | 'assistant';
  content: string;
  muted?: boolean;
}) {
  return (
    <article className={`message-bubble ${role} ${muted ? 'muted' : ''}`}>
      <div className="bubble-role">{role}</div>
      <p>{content}</p>
    </article>
  );
}

function JsonPanel({
  title,
  icon,
  value
}: {
  title: string;
  icon: React.ReactNode;
  value: unknown;
}) {
  return (
    <section className="panel json-panel">
      <div className="json-title">
        {icon}
        <h2>{title}</h2>
      </div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
