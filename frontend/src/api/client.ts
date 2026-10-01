/**
 * API client conforming to TruePixels.rgb Contract v1.0 standard envelope
 */

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id?: string;
  };
}

export interface UserSession {
  user_id: number;
  email: string;
  role: 'User' | 'Admin';
  account_status: 'active' | 'disabled' | 'removed';
  session_token: string;
  expires_at: string;
}

export interface ImageUploadResult {
  image_id: number;
  validation_status: 'valid' | 'invalid' | 'pending';
  content_sha256: string;
  width?: number;
  height?: number;
  file_format: string;
}

const API_BASE = '/api/v1';

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  const authToken = token !== undefined ? token : localStorage.getItem('tp_token');
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => null);

  if (!response.ok) {
    if (data && data.error) {
      const err = new Error(data.error.message);
      (err as any).code = data.error.code;
      (err as any).requestId = data.error.request_id;
      throw err;
    }
    throw new Error(`Request failed with status ${response.status}`);
  }

  return data as T;
}
