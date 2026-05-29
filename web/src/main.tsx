import React, { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  AlertCircle,
  Bot,
  Braces,
  Database,
  Maximize2,
  RefreshCw,
  Send,
  Settings2,
  Sparkles,
  UserRound
} from 'lucide-react';
import {
  extractIdentity,
  extractMemory,
  fetchConfig,
  fetchIdentityContext,
  fetchTraces,
  recallMemory,
  sendChat
} from './api';
import { MemoryGraphPage } from './MemoryGraphPage';
import type { IdentityContextResponse, PublicConfig, TraceRecord } from './types';
import './styles.css';

const DEFAULT_TEMPERATURE = 1;
const MIN_TEMPERATURE = 0;
const MAX_TEMPERATURE = 2;
const TEMPERATURE_STORAGE_KEY = 'peppa.temperatureByModel.v1';
const TOPIC_BOUNDARY_TOOL_NAMES = new Set(['mark_topic_boundary', 'record_topic_boundaries']);
const DEFAULT_PROMPT_HISTORY_MESSAGES = 12;
const PROMPT_HISTORY_MESSAGE_OPTIONS = [0, 2, 4, 6, 8, 12, 16, 24, 32, 50];
type TraceTab = 'history' | 'memory' | 'topic';
type AppRoute = 'console' | 'memory';

function initialRoute(): AppRoute {
  return window.location.pathname === '/memory' ? 'memory' : 'console';
}

function App() {
  const [route, setRoute] = useState<AppRoute>(initialRoute);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [identityContext, setIdentityContext] = useState<IdentityContextResponse | null>(null);
  const [selectedModel, setSelectedModel] = useState('');
  const [temperatureByModel, setTemperatureByModel] = useState<Record<string, number>>(
    loadStoredTemperatures
  );
  const [promptHistoryMessages, setPromptHistoryMessages] = useState(
    DEFAULT_PROMPT_HISTORY_MESSAGES
  );
  const [shouldCallModel, setShouldCallModel] = useState(true);
  const [message, setMessage] = useState('');
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [activeTrace, setActiveTrace] = useState<TraceRecord | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [selectedTraceIds, setSelectedTraceIds] = useState<Set<string>>(() => new Set());
  const [activeTraceTab, setActiveTraceTab] = useState<TraceTab>('history');
  const [isSending, setIsSending] = useState(false);
  const [isIdentifying, setIsIdentifying] = useState(false);
  const [isExtractingMemory, setIsExtractingMemory] = useState(false);
  const [expandedJsonPanel, setExpandedJsonPanel] = useState<{
    title: string;
    value: unknown;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadInitialData();
  }, []);

  useEffect(() => {
    function handlePopState() {
      setRoute(initialRoute());
    }

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  async function loadInitialData() {
    try {
      const [nextConfig, nextTraces, nextIdentityContext] = await Promise.all([
        fetchConfig(),
        fetchTraces(),
        fetchIdentityContext()
      ]);
      setConfig(nextConfig);
      setIdentityContext(nextIdentityContext);
      setSelectedModel(nextConfig.default_model);
      setPromptHistoryMessages(
        nextConfig.prompt_history_messages_default ?? DEFAULT_PROMPT_HISTORY_MESSAGES
      );
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
    if (!message.trim() || isSending || (shouldCallModel && !selectedModel)) {
      return;
    }

    setIsSending(true);
    setError(null);
    try {
      if (!shouldCallModel) {
        const result = await recallMemory({
          message,
          conversationId,
          promptHistoryMessages
        });
        setExpandedJsonPanel({
          title: 'Memory Recall Preview',
          value: {
            input: result.message,
            memory_recall: result.memory_recall
          }
        });
        return;
      }

      const result = await sendChat({
        message,
        model: selectedModel,
        temperature: selectedTemperature,
        promptHistoryMessages,
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
        nextTraces
          .filter((trace) => !isMemoryExtractionTrace(trace) && !isToolCallTrace(trace))
          .map((trace) => trace.id)
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

  async function handleMemoryExtraction() {
    const selectedTraces = traces
      .filter((trace) => selectedTraceIds.has(trace.id) && !isToolCallTrace(trace))
      .sort((left, right) => left.created_at.localeCompare(right.created_at));

    if (selectedTraces.length === 0 || !selectedModel || isExtractingMemory) {
      return;
    }

    setIsExtractingMemory(true);
    setError(null);
    try {
      const result = await extractMemory({
        traceIds: selectedTraces.map((trace) => trace.id),
        model: selectedModel,
        temperature: selectedTemperature
      });
      setActiveTrace(result.trace);
      const nextTraces = await fetchTraces();
      applyTraces(nextTraces.traces);
    } catch (extractError) {
      setError(extractError instanceof Error ? extractError.message : 'Memory extraction failed.');
    } finally {
      setIsExtractingMemory(false);
    }
  }

  async function handleIdentityExtraction() {
    const selectedTraces = traces
      .filter((trace) => selectedTraceIds.has(trace.id) && !isToolCallTrace(trace))
      .sort((left, right) => left.created_at.localeCompare(right.created_at));

    if (selectedTraces.length === 0 || !selectedModel || isIdentifying) {
      return;
    }

    setIsIdentifying(true);
    setError(null);
    try {
      const result = await extractIdentity({
        traceIds: selectedTraces.map((trace) => trace.id),
        model: selectedModel,
        temperature: selectedTemperature
      });
      setIdentityContext((current) => ({
        identity: result.identity,
        candidates: current?.candidates ?? []
      }));
      setActiveTrace(result.trace);
      const [nextTraces, nextIdentityContext] = await Promise.all([
        fetchTraces(),
        fetchIdentityContext()
      ]);
      setIdentityContext(nextIdentityContext);
      applyTraces(nextTraces.traces);
    } catch (identityError) {
      setError(identityError instanceof Error ? identityError.message : 'Identity update failed.');
    } finally {
      setIsIdentifying(false);
    }
  }

  const activeModel = useMemo(
    () => config?.models.find((model) => model.model === selectedModel),
    [config, selectedModel]
  );
  const historyTraces = useMemo(
    () => traces.filter((trace) => !isMemoryExtractionTrace(trace) && !isTopicBoundaryTrace(trace)),
    [traces]
  );
  const memoryExtractionTraces = useMemo(
    () => traces.filter((trace) => isMemoryExtractionTrace(trace)),
    [traces]
  );
  const topicBoundaryTraces = useMemo(
    () => traces.filter((trace) => isTopicBoundaryTrace(trace)),
    [traces]
  );
  const visibleTraces =
    activeTraceTab === 'history'
      ? historyTraces
      : activeTraceTab === 'memory'
        ? memoryExtractionTraces
        : topicBoundaryTraces;
  const selectableHistoryTraceIds = useMemo(
    () => historyTraces.filter((trace) => !isToolCallTrace(trace)).map((trace) => trace.id),
    [historyTraces]
  );
  const selectedTemperature = temperatureByModel[selectedModel] ?? DEFAULT_TEMPERATURE;
  const promptHistoryMessageOptions = useMemo(
    () =>
      [...new Set([...PROMPT_HISTORY_MESSAGE_OPTIONS, promptHistoryMessages])].sort(
        (left, right) => left - right
      ),
    [promptHistoryMessages]
  );
  const currentUserIdentity = identityContext?.identity.current_user_identity ?? '用户';
  const selectedTraceCount = selectedTraceIds.size;
  const isAllHistorySelected =
    selectableHistoryTraceIds.length > 0 &&
    selectableHistoryTraceIds.every((traceId) => selectedTraceIds.has(traceId));
  const selectionToggleLabel = isAllHistorySelected ? 'Clear selection' : 'Select all history traces';

  function handleToggleHistorySelection() {
    setSelectedTraceIds(() => {
      if (isAllHistorySelected) {
        return new Set();
      }
      return new Set(selectableHistoryTraceIds);
    });
  }

  function navigate(nextRoute: AppRoute) {
    const nextPath = nextRoute === 'memory' ? '/memory' : '/';
    window.history.pushState({}, '', nextPath);
    setExpandedJsonPanel(null);
    setRoute(nextRoute);
  }

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
          <button
            className={route === 'memory' ? 'icon-button active' : 'icon-button'}
            type="button"
            onClick={() => navigate('memory')}
          >
            <Database size={16} />
            <span>Memory</span>
          </button>
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
          <StatusPill icon={<UserRound size={14} />} label="Talking to" value={currentUserIdentity} />
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

      {route === 'memory' ? (
        <MemoryGraphPage onBack={() => navigate('console')} />
      ) : (
        <>
          <section className="console-grid">
            <section className="panel chat-panel" aria-label="Chat">
              <div className="panel-header">
                <div>
                  <h2>Chat Probe</h2>
                  <p>{activeModel?.base_url ?? 'Waiting for config'}</p>
                </div>
                <label className="context-control" title="Messages included before the current input">
                  <span>Context</span>
                  <select
                    value={promptHistoryMessages}
                    onChange={(event) => setPromptHistoryMessages(Number(event.currentTarget.value))}
                    aria-label="Context messages"
                  >
                    {promptHistoryMessageOptions.map((option) => (
                      <option value={option} key={option}>
                        {option} messages
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="conversation-window">
                <MessageBubble
                  role="user"
                  content={activeTrace?.user_message ?? 'Send a message to create a trace.'}
                />
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
                <div className="composer-actions">
                  <label
                    className="model-call-toggle"
                    title="When off, only local tag-based memory recall is shown."
                  >
                    <input
                      type="checkbox"
                      checked={shouldCallModel}
                      onChange={(event) => setShouldCallModel(event.currentTarget.checked)}
                    />
                    <span>Call model</span>
                  </label>
                  <button
                    className="send-button"
                    type="submit"
                    disabled={isSending || !message.trim()}
                  >
                    {isSending ? <RefreshCw className="spin" size={17} /> : <Send size={17} />}
                    <span>
                      {isSending ? (shouldCallModel ? 'Sending' : 'Recalling') : shouldCallModel ? 'Send' : 'Preview'}
                    </span>
                  </button>
                </div>
              </form>
            </section>

            <aside className="panel trace-list-panel" aria-label="Recent traces">
              <div className="panel-header compact">
                <div>
                  <h2>Recent Traces</h2>
                  <p>{traces.length} loaded</p>
                </div>
                <div className="trace-actions">
                  <label className="selection-toggle" title={selectionToggleLabel}>
                    <input
                      type="checkbox"
                      checked={isAllHistorySelected}
                      disabled={selectableHistoryTraceIds.length === 0}
                      aria-label={selectionToggleLabel}
                      onChange={handleToggleHistorySelection}
                    />
                  </label>
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() => void handleIdentityExtraction()}
                    disabled={selectedTraceCount === 0 || isIdentifying}
                  >
                    {isIdentifying ? <RefreshCw className="spin" size={16} /> : <UserRound size={16} />}
                    <span>{isIdentifying ? 'Identifying' : `Identify ${selectedTraceCount}`}</span>
                  </button>
                  <button
                    className="icon-button"
                    type="button"
                    onClick={() => void handleMemoryExtraction()}
                    disabled={selectedTraceCount === 0 || isExtractingMemory}
                  >
                    {isExtractingMemory ? <RefreshCw className="spin" size={16} /> : <Database size={16} />}
                    <span>{isExtractingMemory ? 'Extracting' : `Extract ${selectedTraceCount}`}</span>
                  </button>
                  <button className="icon-button" type="button" onClick={() => void refreshTraces()}>
                    <RefreshCw size={16} />
                    <span>Refresh</span>
                  </button>
                </div>
              </div>
              <div className="trace-list">
                <div className="trace-tabs" role="tablist" aria-label="Trace type">
                  <button
                    className={activeTraceTab === 'history' ? 'trace-tab active' : 'trace-tab'}
                    type="button"
                    role="tab"
                    aria-selected={activeTraceTab === 'history'}
                    onClick={() => setActiveTraceTab('history')}
                  >
                    History
                    <span>{historyTraces.length}</span>
                  </button>
                  <button
                    className={activeTraceTab === 'memory' ? 'trace-tab active' : 'trace-tab'}
                    type="button"
                    role="tab"
                    aria-selected={activeTraceTab === 'memory'}
                    onClick={() => setActiveTraceTab('memory')}
                  >
                    Memory Extraction
                    <span>{memoryExtractionTraces.length}</span>
                  </button>
                  <button
                    className={activeTraceTab === 'topic' ? 'trace-tab active' : 'trace-tab'}
                    type="button"
                    role="tab"
                    aria-selected={activeTraceTab === 'topic'}
                    onClick={() => setActiveTraceTab('topic')}
                  >
                    Topic Boundary
                    <span>{topicBoundaryTraces.length}</span>
                  </button>
                </div>

                {visibleTraces.map((trace) => {
                  const isDisabled = isToolCallTrace(trace);
                  const traceItemClassName = ['trace-item', isDisabled ? 'disabled' : '']
                    .filter(Boolean)
                    .join(' ');
                  const traceRowClassName = [
                    'trace-row',
                    trace.id === activeTrace?.id ? 'active' : '',
                    trace.auto_memory_extracted ? 'auto-memory-extracted' : ''
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <div className={traceItemClassName} key={trace.id}>
                      <input
                        type="checkbox"
                        checked={selectedTraceIds.has(trace.id)}
                        disabled={isDisabled}
                        aria-label={`Select trace ${trace.id}`}
                        onChange={(event) => handleTraceSelection(trace, event.currentTarget.checked)}
                      />
                      <button
                        className={traceRowClassName}
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
                {visibleTraces.length === 0 && <div className="empty-state">No traces yet.</div>}
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
        </>
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

function isMemoryExtractionTrace(trace: TraceRecord): boolean {
  const requestMeta = getRecord(trace.request_payload._peppa);
  return requestMeta?.kind === 'memory_extraction';
}

function isTopicBoundaryTrace(trace: TraceRecord): boolean {
  const requestMeta = getRecord(trace.request_payload._peppa);
  return requestMeta?.kind === 'topic_boundary_detection';
}

function isToolCallTrace(trace: TraceRecord): boolean {
  if (isMemoryExtractionTrace(trace)) {
    return true;
  }

  const requestMeta = getRecord(trace.request_payload._peppa);
  if (requestMeta?.kind === 'identity_update' || requestMeta?.kind === 'topic_boundary_detection') {
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
    return (
      Array.isArray(toolCalls) &&
      toolCalls.some((toolCall) => !TOPIC_BOUNDARY_TOOL_NAMES.has(getToolCallName(toolCall) ?? ''))
    );
  });
}

function getToolCallName(value: unknown): string | null {
  const toolCall = getRecord(value);
  const functionRecord = getRecord(toolCall?.function);
  if (typeof functionRecord?.name === 'string') {
    return functionRecord.name;
  }
  return typeof toolCall?.name === 'string' ? toolCall.name : null;
}

function getRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
