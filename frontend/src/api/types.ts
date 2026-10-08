/** Response shapes of the endpoints the React app uses (backend is the source of truth). */

export interface Me {
  user_id: number;
  email: string;
  role: 'User' | 'Admin';
  account_status: 'active' | 'disabled' | 'removed';
  expires_at: string;
}

export interface LoginResponse {
  token: string;
  role: 'User' | 'Admin';
  user_id: number;
  requires_otp: boolean;
}

export interface RegisterResponse {
  user_id: number;
  message: string;
  requires_2fa: boolean;
}

export interface OtpVerifyResponse {
  message: string;
  token?: string | null;
}

export interface UploadResponse {
  image_id: number;
  validation_status: string;
  content_sha256: string;
  width?: number;
  height?: number;
  file_format: string;
}

export type XaiStatus = 'not_requested' | 'generated' | 'partial' | 'unavailable';

export interface PredictionResponse {
  prediction_id: number;
  image_id: number;
  predicted_class: 'Real' | 'AI Generated';
  /** C2 v2: P(AI) for EITHER verdict, [0.01, 0.99]; null = not calibrated for the configuration that ran. */
  p_ai: number | null;
  certainty: Certainty | null;
  semantic_score: number;
  frequency_score: number | null;
  fusion_score: number;
  latency_ms: number;
  xai_status: XaiStatus;
  xai_reasons: string[];
}

export interface Visualization {
  branch: 'semantic' | 'frequency';
  technique: string;
  visualization_url: string;
  generated_at: string;
  caption: string;
}

export type Certainty = 'confident' | 'inconclusive';

/** C2 v2 display fields, worded server-side (backend/app/m3_results/likelihood.py). */
export interface Likelihood {
  p_ai: number | null;
  p_ai_percentage: number | null;
  p_ai_display: string | null;
  certainty: Certainty | null;
  certainty_label: string | null;
  semantic_only: boolean;
  leans_ai_below_threshold: boolean;
  likelihood_headline: string;
  likelihood_notes: string[];
  /** The fitted P(AI) map that produced p_ai (D4); null with p_ai. */
  calibration_ref: string | null;
}

export interface ModelRef {
  model_id: number;
  model_name: string;
  model_version: string;
}

export interface ResultView extends Likelihood {
  prediction_id: number;
  image_id: number;
  predicted_class: 'Real' | 'AI Generated';
  /** Detector SCORES (higher = more AI-like), not probabilities. */
  semantic_score: number;
  frequency_score: number | null;
  fusion_score: number;
  original_image_url: string;
  original_available: boolean;
  visualizations: Visualization[];
  model_name: string;
  model_version: string;
  models: { semantic: ModelRef | null; frequency: ModelRef | null; fusion: ModelRef | null };
  prediction_timestamp: string;
  interpretive_caption: string;
}

export interface HistoryItem extends Likelihood {
  prediction_id: number;
  image_id: number;
  thumbnail_url: string;
  predicted_class: 'Real' | 'AI Generated';
  prediction_timestamp: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type LoginOutcome =
  | 'success' | 'otp_sent' | 'wrong_password' | 'unknown_account' | 'account_disabled'
  | 'not_admin' | 'otp_failed' | 'password_reset' | 'password_changed';

/** One row of login activity (GET /users/me/login-activity, GET /admin/login-activity). */
export interface LoginEvent {
  event_id: number;
  user_id: number | null;
  email: string;
  portal: 'user' | 'admin';
  outcome: LoginOutcome;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

export interface PaginatedLoginEvents {
  items: LoginEvent[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface MessageResponse {
  message: string;
}
