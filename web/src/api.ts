import type { ChatResponse, PublicConfig, TraceRecord } from './types';

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

export function sendChat(params: {
  message: string;
  model: string;
  temperature: number;
  conversationId?: string;
}): Promise<ChatResponse> {
  return requestJson<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message: params.message,
      model: params.model,
      temperature: params.temperature,
      conversation_id: params.conversationId
    })
  });
}

export function testMemoryToolCall(params: {
  traceIds: string[];
  model: string;
  temperature: number;
}): Promise<{ trace: TraceRecord }> {
  return requestJson<{ trace: TraceRecord }>('/api/memory/tool-call-test', {
    method: 'POST',
    body: JSON.stringify({
      trace_ids: params.traceIds,
      model: params.model,
      temperature: params.temperature
    })
  });
}
