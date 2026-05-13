export type ModelConfig = {
  model: string;
  base_url: string;
  has_api_key: boolean;
};

export type PublicConfig = {
  default_model: string;
  models: ModelConfig[];
};

export type TraceRecord = {
  id: string;
  conversation_id: string;
  model: string;
  user_message: string;
  assistant_message: string | null;
  prompt_messages: Array<Record<string, unknown>>;
  memory_hits: Array<Record<string, unknown>>;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown> | null;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
};

export type ChatResponse = {
  conversation_id: string;
  trace: TraceRecord;
};
