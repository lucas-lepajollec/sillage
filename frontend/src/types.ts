export type Track = {
  id: string;
  index: number | null;
  language: string;
  format: string;
  title: string;
  default: boolean;
  forced: boolean;
  sdh: boolean;
  external: boolean;
  path?: string;
  supported: boolean;
};
export type Episode = {
  path: string;
  name: string;
  duration: number;
  tracks: Track[];
  has_french: boolean;
  status: string;
  error?: string;
};
export type Browse = {
  path: string;
  parent: string | null;
  roots: string[];
  directories: { name: string; path: string }[];
  files: { name: string; path: string }[];
};
export type Scan = {
  episodes: Episode[];
  errors: { path: string; error: string }[];
};
export type Cue = {
  id: string;
  start: number;
  end: number;
  text: string;
  translated?: string;
  warning?: string;
  proposed_start?: number;
  proposed_end?: number;
};
export type Preview = {
  format: string;
  cues: Cue[];
  warnings: string[];
  timing_status: string;
  sync_pending?: boolean;
  sync_proposal?: {
    offset_ms: number;
    confidence: number;
    warnings: string[];
  } | null;
};
export type ProviderKind =
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "openrouter"
  | "ollama"
  | "custom";
export type ModelCatalog = {
  models: { id: string; name: string }[];
  truncated: boolean;
};
export type Provider = {
  id?: string;
  name: string;
  kind: ProviderKind;
  base_url: string;
  model: string;
  temperature: number | null;
  batch_size: number;
  concurrency: number;
  timeout: number;
  retries: number;
  source_language: string;
  target_language: string;
  glossary: string;
  api_key?: string;
  has_key?: boolean;
};
export type JobStatus =
  | "queued"
  | "extracting"
  | "translating"
  | "validating"
  | "syncing"
  | "writing"
  | "completed"
  | "error"
  | "review"
  | "cancelled"
  | "interrupted";
export type SyncMode = "preserve" | "offset" | "auto";
export type Job = {
  id: string;
  path: string;
  name: string;
  track_id: string;
  provider_id: string;
  status: JobStatus;
  progress: number;
  done: number;
  total: number;
  error: string | null;
  warnings: string[];
  output: string | null;
  created_at: string;
  sync_mode: SyncMode;
  offset_ms: number;
  timing_status: string;
  adaptive_batch_size?: number;
  sync_pending?: boolean;
  sync_proposal?: {
    offset_ms: number;
    confidence: number;
    warnings: string[];
  } | null;
};
export type Health = {
  status: string;
  tools: Record<string, boolean>;
  version: string;
};
