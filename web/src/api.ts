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

export function updateMemoryGraphNodeSummary(
  nodeId: string,
  summary: string
): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(
    `/api/memory/graph/nodes/${encodeURIComponent(nodeId)}/summary`,
    {
      method: 'PATCH',
      body: JSON.stringify({ summary })
    }
  );
}

export function mergeMemoryGraphNode(
  nodeId: string,
  targetId: string
): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/nodes/${encodeURIComponent(nodeId)}/merge`, {
    method: 'POST',
    body: JSON.stringify({ target_id: targetId })
  });
}

export function deleteMemoryGraphEdge(edgeId: string): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/edges/${encodeURIComponent(edgeId)}`, {
    method: 'DELETE'
  });
}

export function updateMemoryGraphEdgeSummary(
  edgeId: string,
  summary: string
): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(
    `/api/memory/graph/edges/${encodeURIComponent(edgeId)}/summary`,
    {
      method: 'PATCH',
      body: JSON.stringify({ summary })
    }
  );
}

export function mergeMemoryGraphEdge(
  edgeId: string,
  targetId: string
): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/edges/${encodeURIComponent(edgeId)}/merge`, {
    method: 'POST',
    body: JSON.stringify({ target_id: targetId })
  });
}

export function updateMemoryGraphTag(
  tagId: string,
  payload: { name?: string; kind?: string }
): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/tags/${encodeURIComponent(tagId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
}

export function mergeMemoryGraphTag(tagId: string, targetId: string): Promise<MemoryGraphResponse> {
  return requestJson<MemoryGraphResponse>(`/api/memory/graph/tags/${encodeURIComponent(tagId)}/merge`, {
    method: 'POST',
    body: JSON.stringify({ target_id: targetId })
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

type ChatStreamPayloads = {
  meta: {
    conversation_id?: string;
  };
  delta: {
    content?: string;
  };
  done: ChatResponse;
  error: {
    message?: string;
    conversation_id?: string;
    trace?: TraceRecord;
  };
};

export function streamChat(
  params: {
    message: string;
    model: string;
    temperature: number;
    promptHistoryMessages: number;
    conversationId?: string;
  },
  handlers: {
    onMeta?: (payload: ChatStreamPayloads['meta']) => void;
    onDelta?: (payload: ChatStreamPayloads['delta']) => void;
    onError?: (payload: ChatStreamPayloads['error']) => void;
  } = {}
): Promise<ChatResponse> {
  return streamChatResponse(params, handlers);
}

async function streamChatResponse(
  params: {
    message: string;
    model: string;
    temperature: number;
    promptHistoryMessages: number;
    conversationId?: string;
  },
  handlers: {
    onMeta?: (payload: ChatStreamPayloads['meta']) => void;
    onDelta?: (payload: ChatStreamPayloads['delta']) => void;
    onError?: (payload: ChatStreamPayloads['error']) => void;
  }
): Promise<ChatResponse> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      message: params.message,
      model: params.model,
      temperature: params.temperature,
      prompt_history_messages: params.promptHistoryMessages,
      conversation_id: params.conversationId
    })
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Request failed with ${response.status}`);
  }
  if (!response.body) {
    throw new Error('Streaming response is not available.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let donePayload: ChatResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const parsed = drainSseEvents(buffer);
    buffer = parsed.remaining;
    for (const event of parsed.events) {
      const payload = parseSseJson(event.data);
      if (event.event === 'meta') {
        handlers.onMeta?.(payload as ChatStreamPayloads['meta']);
      } else if (event.event === 'delta') {
        handlers.onDelta?.(payload as ChatStreamPayloads['delta']);
      } else if (event.event === 'done') {
        donePayload = payload as ChatResponse;
      } else if (event.event === 'error') {
        const errorPayload = payload as ChatStreamPayloads['error'];
        handlers.onError?.(errorPayload);
        throw new Error(errorPayload.message || 'Message failed.');
      }
    }
  }

  buffer += decoder.decode();
  const parsed = drainSseEvents(buffer + '\n\n');
  for (const event of parsed.events) {
    const payload = parseSseJson(event.data);
    if (event.event === 'done') {
      donePayload = payload as ChatResponse;
    } else if (event.event === 'error') {
      const errorPayload = payload as ChatStreamPayloads['error'];
      handlers.onError?.(errorPayload);
      throw new Error(errorPayload.message || 'Message failed.');
    }
  }

  if (!donePayload) {
    throw new Error('Streaming response ended before completion.');
  }
  return donePayload;
}

function drainSseEvents(buffer: string): {
  events: Array<{ event: string; data: string }>;
  remaining: string;
} {
  const normalized = buffer.replace(/\r\n/g, '\n');
  const blocks = normalized.split('\n\n');
  const remaining = blocks.pop() ?? '';
  return {
    events: blocks.map(parseSseBlock).filter((event) => event.data),
    remaining
  };
}

function parseSseBlock(block: string): { event: string; data: string } {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart());
    }
  }
  return { event, data: dataLines.join('\n') };
}

function parseSseJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return {};
  }
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
