import React, { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  Bot,
  Braces,
  Database,
  Maximize2,
  MessageSquare,
  RefreshCw,
  Send,
  Settings2,
  Sparkles
} from 'lucide-react';
import { fetchConfig, fetchTraces, sendChat, testMemoryToolCall } from './api';
import type { PublicConfig, TraceRecord } from './types';
import './styles.css';

const DEFAULT_TEMPERATURE = 1;
const MIN_TEMPERATURE = 0;
const MAX_TEMPERATURE = 2;
const TEMPERATURE_STORAGE_KEY = 'peppa.temperatureByModel.v1';

function App() {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [temperatureByModel, setTemperatureByModel] = useState<Record<string, number>>(
    loadStoredTemperatures
  );
  const [message, setMessage] = useState('');
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [activeTrace, setActiveTrace] = useState<TraceRecord | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [selectedTraceIds, setSelectedTraceIds] = useState<Set<string>>(() => new Set());
  const [isSending, setIsSending] = useState(false);
  const [isTestingMemory, setIsTestingMemory] = useState(false);
  const [expandedJsonPanel, setExpandedJsonPanel] = useState<{
    title: string;
    value: unknown;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadInitialData();
  }, []);

  async function loadInitialData() {
    try {
      const [nextConfig, nextTraces] = await Promise.all([fetchConfig(), fetchTraces()]);
      setConfig(nextConfig);
      setSelectedModel(nextConfig.default_model);
      applyTraces(nextTraces.traces);
      setActiveTrace(nextTraces.traces[0] ?? null);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load Peppa.');
    }
  }

  async function refreshTraces() {
    try {
      const nextTraces = await fetchTraces();
      applyTraces(nextTraces.traces);
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
        temperature: selectedTemperature,
        conversationId
      });
      setConversationId(result.conversation_id);
      setActiveTrace(result.trace);
      setMessage('');
      const nextTraces = await fetchTraces();
      applyTraces(nextTraces.traces);
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

  function handleTemperatureChange(nextValue: number) {
    if (!selectedModel) {
      return;
    }

    const nextTemperature = clampTemperature(nextValue);
    setTemperatureByModel((current) => {
      const next = {
        ...current,
        [selectedModel]: nextTemperature
      };
      saveStoredTemperatures(next);
      return next;
    });
  }

  function applyTraces(nextTraces: TraceRecord[]) {
    setTraces(nextTraces);
    setSelectedTraceIds((current) => {
      const selectableTraceIds = new Set(
        nextTraces.filter((trace) => !isToolCallTrace(trace)).map((trace) => trace.id)
      );
      return new Set([...current].filter((traceId) => selectableTraceIds.has(traceId)));
    });
  }

  function handleTraceSelection(trace: TraceRecord, checked: boolean) {
    if (isToolCallTrace(trace)) {
      return;
    }

    setSelectedTraceIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(trace.id);
      } else {
        next.delete(trace.id);
      }
      return next;
    });
  }

  async function handleMemoryToolTest() {
    const selectedTraces = traces
      .filter((trace) => selectedTraceIds.has(trace.id) && !isToolCallTrace(trace))
      .sort((left, right) => left.created_at.localeCompare(right.created_at));

    if (selectedTraces.length === 0 || !selectedModel || isTestingMemory) {
      return;
    }

    setIsTestingMemory(true);
    setError(null);
    try {
      const result = await testMemoryToolCall({
        traceIds: selectedTraces.map((trace) => trace.id),
        model: selectedModel,
        temperature: selectedTemperature
      });
      setActiveTrace(result.trace);
      setSelectedTraceIds(new Set());
      const nextTraces = await fetchTraces();
      applyTraces(nextTraces.traces);
    } catch (testError) {
      setError(testError instanceof Error ? testError.message : 'Memory tool test failed.');
    } finally {
      setIsTestingMemory(false);
    }
  }

  const activeModel = useMemo(
    () => config?.models.find((model) => model.model === selectedModel),
    [config, selectedModel]
  );
  const selectedTemperature = temperatureByModel[selectedModel] ?? DEFAULT_TEMPERATURE;
  const selectedTraceCount = selectedTraceIds.size;

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
          <label className="temperature-control">
            <span>Temperature</span>
            <input
              type="number"
              min={MIN_TEMPERATURE}
              max={MAX_TEMPERATURE}
              step="0.1"
              value={selectedTemperature}
              onChange={(event) => handleTemperatureChange(event.currentTarget.valueAsNumber)}
              disabled={!selectedModel}
              aria-label="Temperature"
            />
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
            <div className="trace-actions">
              <button
                className="icon-button"
                type="button"
                onClick={() => void handleMemoryToolTest()}
                disabled={selectedTraceCount === 0 || isTestingMemory}
              >
                {isTestingMemory ? <RefreshCw className="spin" size={16} /> : <Database size={16} />}
                <span>{isTestingMemory ? 'Testing' : `Memory ${selectedTraceCount}`}</span>
              </button>
              <button className="icon-button" type="button" onClick={() => void refreshTraces()}>
                <RefreshCw size={16} />
                <span>Refresh</span>
              </button>
            </div>
          </div>
          <div className="trace-list">
            {traces.map((trace) => {
              const isDisabled = isToolCallTrace(trace);
              return (
                <div className={isDisabled ? 'trace-item disabled' : 'trace-item'} key={trace.id}>
                  <input
                    type="checkbox"
                    checked={selectedTraceIds.has(trace.id)}
                    disabled={isDisabled}
                    aria-label={`Select trace ${trace.id}`}
                    onChange={(event) => handleTraceSelection(trace, event.currentTarget.checked)}
                  />
                  <button
                    className={trace.id === activeTrace?.id ? 'trace-row active' : 'trace-row'}
                    type="button"
                    onClick={() => setActiveTrace(trace)}
                  >
                    <span className="trace-model">{trace.model}</span>
                    <span className="trace-message">{trace.user_message}</span>
                    <span className={trace.error ? 'trace-state error' : 'trace-state'}>
                      {trace.error ? 'error' : `${trace.duration_ms ?? 0} ms`}
                    </span>
                  </button>
                </div>
              );
            })}
            {traces.length === 0 && <div className="empty-state">No traces yet.</div>}
          </div>
        </aside>
      </section>

      <section className="debug-grid">
        <JsonPanel
          title="Prompt"
          icon={<Bot size={16} />}
          value={activeTrace?.prompt_messages ?? []}
          onExpand={setExpandedJsonPanel}
        />
        <JsonPanel
          title="Memory Hits"
          icon={<Database size={16} />}
          value={activeTrace?.memory_hits ?? []}
          onExpand={setExpandedJsonPanel}
        />
        <JsonPanel
          title="Request"
          icon={<Braces size={16} />}
          value={activeTrace?.request_payload ?? {}}
          onExpand={setExpandedJsonPanel}
        />
        <JsonPanel
          title="Response"
          icon={<Braces size={16} />}
          value={activeTrace?.response_payload ?? {}}
          onExpand={setExpandedJsonPanel}
        />
      </section>

      {expandedJsonPanel && (
        <JsonModal
          title={expandedJsonPanel.title}
          value={expandedJsonPanel.value}
          onClose={() => setExpandedJsonPanel(null)}
        />
      )}
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
  value,
  onExpand
}: {
  title: string;
  icon: React.ReactNode;
  value: unknown;
  onExpand: (panel: { title: string; value: unknown }) => void;
}) {
  return (
    <section className="panel json-panel">
      <div className="json-title">
        <div className="json-heading">
          {icon}
          <h2>{title}</h2>
        </div>
        <button
          className="json-expand-button"
          type="button"
          aria-label={`Expand ${title}`}
          onClick={() => onExpand({ title, value })}
        >
          <Maximize2 size={15} />
        </button>
      </div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}

function JsonModal({
  title,
  value,
  onClose
}: {
  title: string;
  value: unknown;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="json-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="json-modal-header">
          <h2>{title}</h2>
          <button className="icon-button" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </section>
    </div>
  );
}

function loadStoredTemperatures(): Record<string, number> {
  const rawValue = window.localStorage.getItem(TEMPERATURE_STORAGE_KEY);
  if (!rawValue) {
    return {};
  }

  try {
    const parsedValue = JSON.parse(rawValue) as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(parsedValue)
        .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
        .map(([model, value]) => [model, clampTemperature(value as number)])
    );
  } catch {
    return {};
  }
}

function saveStoredTemperatures(temperatures: Record<string, number>) {
  window.localStorage.setItem(TEMPERATURE_STORAGE_KEY, JSON.stringify(temperatures));
}

function clampTemperature(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_TEMPERATURE;
  }

  const roundedValue = Math.round(value * 10) / 10;
  return Math.min(MAX_TEMPERATURE, Math.max(MIN_TEMPERATURE, roundedValue));
}

function isToolCallTrace(trace: TraceRecord): boolean {
  const requestMeta = getRecord(trace.request_payload._peppa);
  if (requestMeta?.kind === 'memory_tool_test') {
    return true;
  }

  const choices = trace.response_payload?.choices;
  if (!Array.isArray(choices)) {
    return false;
  }

  return choices.some((choice) => {
    const choiceRecord = getRecord(choice);
    const message = getRecord(choiceRecord?.message);
    const toolCalls = message?.tool_calls;
    return Array.isArray(toolCalls) && toolCalls.length > 0;
  });
}

function getRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
