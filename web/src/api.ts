import type {
  ChatResponse,
  IdentityContextResponse,
  MemoryGraphResponse,
  MemoryRecallResponse,
  PublicConfig,
  TraceRecord
} from './types';

async function requestJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {})
    },
    ...options
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed with ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function fetchConfig(): Promise<PublicConfig> {
  return requestJson<PublicConfig>('/api/config');
}

export function fetchTraces(): Promise<{ traces: TraceRecord[] }> {
  return requestJson<{ traces: TraceRecord[] }>('/api/traces?limit=25');
}

export function fetchMemoryGraph(): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>('/api/memory/graph');
}

export function deleteMemoryGraphNode(nodeId: string): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/nodes/${encodeURIComponent(nodeId)}`, {
    method: 'DELETE'
  });
}

export function deleteMemoryGraphEdge(edgeId: string): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/edges/${encodeURIComponent(edgeId)}`, {
    method: 'DELETE'
  });
}

export function recallMemory(params: {
  message: string;
  conversationId?: string;
  promptHistoryMessages: number;
}): Promise<MemoryRecallResponse> {
  return requestJson<MemoryRecallResponse>('/api/memory/recall', {
    method: 'POST',
    body: JSON.stringify({
      message: params.message,
      conversation_id: params.conversationId,
      prompt_history_messages: params.promptHistoryMessages
    })
  });
}

export function fetchIdentityContext(): Promise<IdentityContextResponse> {
  return requestJson<IdentityContextResponse>('/api/identity/context');
}

export function sendChat(params: {
  message: string;
  model: string;
  temperature: number;
  promptHistoryMessages: number;
  conversationId?: string;
}): Promise<ChatResponse> {
  return requestJson<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: params.message,
      model: params.model,
      temperature: params.temperature,
      prompt_history_messages: params.promptHistoryMessages,
      conversation_id: params.conversationId
    })
  });
}

export function extractMemory(params: {
  traceIds: string[];
  model: string;
  temperature: number;
}): Promise<{ trace: TraceRecord }> {
  return requestJson<{ trace: TraceRecord }>('/api/memory/extract', {
    method: 'POST',
    body: JSON.stringify({
      trace_ids: params.traceIds,
      model: params.model,
      temperature: params.temperature
    })
  });
}

export function extractIdentity(params: {
  traceIds: string[];
  model: string;
  temperature: number;
}): Promise<{ trace: TraceRecord; identity: IdentityContextResponse['identity'] }> {
  return requestJson<{ trace: TraceRecord; identity: IdentityContextResponse['identity'] }>(
    '/api/identity/extract',
    {
      method: 'POST',
      body: JSON.stringify({
        trace_ids: params.traceIds,
        model: params.model,
        temperature: params.temperature
      })
    }
  );
}
