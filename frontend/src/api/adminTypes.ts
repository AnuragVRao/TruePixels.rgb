/** Response shapes of the admin endpoints (backend is the source of truth). */

export interface AdminSummary {
  total_predictions: number;
  predictions_last_24h: number;
  class_distribution: Record<string, number>;
  error_count_last_24h: number;
  active_models: { model_type: string; model_name: string; version: string }[];
}

export interface LatencySummary {
  warm_count: number;
  cold_count: number;
  unknown_count: number;
  p50_ms: number | null;
  p95_ms: number | null;
}

export interface SystemAnalytics {
  days: number;
  latency: LatencySummary | null;
  latency_over_time: { date: string; warm_count: number; p50_ms: number | null; p95_ms: number | null }[];
  total_predictions: number;
  class_distribution: Record<string, number>;
  usage_over_time: { date: string; predictions_count: number; active_users: number }[];
  confidence_distribution: { bin_range: string; count: number }[];
  error_rate_percentage: number;
  total_logs: number;
}

export interface LogItem {
  log_id: number;
  user_id: number | null;
  event_type: string;
  event_detail: string;
  severity: string;
  request_id: string | null;
  log_timestamp: string;
}

export interface PaginatedLogs {
  items: LogItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface AdminUser {
  user_id: number;
  full_name: string;
  email: string;
  role: 'User' | 'Admin';
  account_status: 'active' | 'disabled' | 'removed';
  registered_at: string;
}

export type ModelType = 'semantic-classifier' | 'frequency-artifact-classifier' | 'fusion-configuration';

export interface ModelRow {
  model_id: number;
  model_type: ModelType;
  model_name: string;
  model_version: string;
  is_active: boolean;
  artifact_sha256: string | null;
  artifact_ref: string;
  training_reference: string | null;
  configuration: Record<string, unknown>;
  head: { sha256: string; id2label?: Record<string, string> | null } | null;
  registered_at: string | null;
  registered_by: number | null;
}

export interface ModelList {
  active: Partial<Record<ModelType, ModelRow>>;
  models: ModelRow[];
}

export interface GateMetrics {
  accuracy: number;
  fpr: number;
  recall: number;
  auc: number;
  predicted_ai: number;
}

export interface GateResult {
  passed: boolean;
  available: boolean;
  advisory?: boolean;
  reasons: string[];
  reference?: { file: string; images: number; real: number; generated: number; split: string };
  thresholds?: Record<string, number>;
  baseline?: GateMetrics;
  current?: GateMetrics;
  candidate?: GateMetrics;
  labels_changed?: number;
}

export interface GatePreview {
  model_id: number;
  model_type: ModelType;
  is_active: boolean;
  canary: Record<string, unknown>;
  gate: GateResult;
}

export interface ActivationResponse {
  status: string;
  activated_model_id: number;
  model_type: ModelType;
  previous_model_id: number | null;
  action: 'activate' | 'rollback';
  forced: boolean;
  canary: Record<string, unknown>;
  gate: GateResult;
}

export interface Activation {
  activation_id: number;
  model_type: ModelType;
  model_id: number;
  previous_model_id: number | null;
  activated_by: number | null;
  activated_at: string;
  action: 'bootstrap' | 'activate' | 'rollback';
  forced: boolean;
  reason: string | null;
  gate: GateResult | null;
}

export const MODEL_TYPE_LABEL: Record<ModelType, string> = {
  'semantic-classifier': 'Semantic head (SigLIP 2)',
  'frequency-artifact-classifier': 'Frequency head (SPAI)',
  'fusion-configuration': 'Fusion configuration',
};
