export type ModelConfig = {
  model: string;
  base_url: string;
  has_api_key: boolean;
};

export type PublicConfig = {
  default_model: string;
  models: ModelConfig[];
  prompt_history_messages_default: number;
};

export type TraceRecord = {
  id: string;
  conversation_id: string;
  model: string;
  user_message: string;
  assistant_message: string | null;
  prompt_messages: Array<Record<string, unknown>>;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown> | null;
  duration_ms: number | null;
  error: string | null;
  created_at: string;
  auto_memory_extracted?: boolean;
};

export type ChatResponse = {
  conversation_id: string;
  trace: TraceRecord;
};

export type MemoryRecallResponse = {
  message: string;
  memory_recall: Record<string, unknown>;
};

export type ConversationIdentity = {
  id: string;
  channel: string;
  channel_instance: string;
  memory_node_id: string | null;
  current_user_identity: string;
  created_at: string;
  updated_at: string;
};

export type IdentityCandidateNode = {
  id: string;
  title: string;
  summary: string;
  confidence: number;
  mention_count: number;
  updated_at: string;
};

export type IdentityContextResponse = {
  identity: ConversationIdentity;
  candidates: IdentityCandidateNode[];
};

export type MemoryGraphTag = {
  id: string;
  name: string;
  kind: string;
  confidence: number;
  reason: string;
  mention_count: number;
};

export type MemoryGraphStoredTag = {
  id: string;
  name: string;
  normalized_name: string;
  kind: string;
  mention_count: number;
  created_at: string;
  updated_at: string;
};

export type MemoryGraphNode = {
  id: string;
  type: string;
  title: string;
  summary: string;
  confidence: number;
  mention_count: number;
  created_at: string;
  updated_at: string;
  tags: MemoryGraphTag[];
  source_trace_ids: string[];
};

export type MemoryGraphEdge = {
  id: string;
  source_node_id: string;
  source_title: string;
  source_type: string;
  target_node_id: string;
  target_title: string;
  target_type: string;
  relation_type: string;
  summary: string;
  confidence: number;
  mention_count: number;
  created_at: string;
  updated_at: string;
  tags: MemoryGraphTag[];
  source_trace_ids: string[];
};

export type MemoryGraphResponse = {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
  tags: MemoryGraphStoredTag[];
  stats: {
    nodes: number;
    edges: number;
    tags: number;
    extraction_runs: number;
  };
};
