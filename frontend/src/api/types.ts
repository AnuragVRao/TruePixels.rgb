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
  confidence_score: number;
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

export interface ModelRef {
  model_id: number;
  model_name: string;
  model_version: string;
}

export interface ResultView {
  prediction_id: number;
  image_id: number;
  predicted_class: 'Real' | 'AI Generated';
  confidence_score: number;
  confidence_percentage: number;
  confidence_band: 'High' | 'Moderate' | 'Low';
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

export interface HistoryItem {
  prediction_id: number;
  image_id: number;
  thumbnail_url: string;
  predicted_class: 'Real' | 'AI Generated';
  confidence_score: number;
  confidence_percentage: number;
  confidence_band: 'High' | 'Moderate' | 'Low';
  prediction_timestamp: string;
}

export interface HistoryPage {
  items: HistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
