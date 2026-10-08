/**
 * API client for TruePixels.rgb (Contract v1.0 error envelope).
 *
 * Session token: kept in sessionStorage, not localStorage. Both are readable
 * by script on this origin, so neither protects against XSS; the difference
 * is lifetime - sessionStorage dies with the tab, so a token left on a shared
 * machine does not outlive the browser session. The cost is signing in again
 * per tab. (No cookies: the API authenticates with a Bearer header.)
 *
 * Every request goes through `apiRequest` / `apiBlob`. A 401 clears the
 * session and notifies the registered handler (the app redirects to /login).
 * Files (originals, thumbnails, panels, PDFs) are fetched WITH the header and
 * turned into blob URLs - nothing is ever authenticated by a URL parameter.
 */

const API_BASE = '/api/v1';
const TOKEN_KEY = 'tp_token';

export class ApiError extends Error {
  code: string;
  status: number;
  requestId?: string;
  body?: unknown;

  constructor(code: string, message: string, status: number, requestId?: string, body?: unknown) {
    super(message);
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.body = body;
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): the session simply does not persist */
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Called on any 401 from an authenticated request (expired / invalid session). */
export function onUnauthorized(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/** Plain-language messages for the error codes a user can meet. */
const MESSAGES: Record<string, string> = {
  AUTH_INVALID_CREDENTIALS: 'Email or password is incorrect.',
  AUTH_EMAIL_TAKEN: 'An account with this email already exists.',
  AUTH_TOKEN_INVALID: 'Your session has expired. Please sign in again.',
  AUTH_FORBIDDEN: 'You do not have permission to do that.',
  AUTH_ACCOUNT_DISABLED: 'This account is disabled.',
  AUTH_CURRENT_PASSWORD_INCORRECT: 'The current password is not correct.',
  // AUTH_WEAK_PASSWORD: the server's own message names the rule that failed.
  // AUTH_RATE_LIMITED: the server's own message carries the wait in seconds.
  IMG_FORMAT_UNSUPPORTED: 'Only JPG, JPEG and PNG images are accepted.',
  IMG_TOO_LARGE: 'The file is larger than the allowed upload size.',
  IMG_CORRUPTED: 'The file could not be read as an image (it may be truncated or corrupted).',
  IMG_NOT_FOUND: 'That image was not found.',
  IMG_FILE_MISSING: 'This record exists, but its stored image file is no longer available.',
  INF_MODEL_UNAVAILABLE: 'The detection models are not available right now. Please try again later.',
  INF_TIMEOUT: 'The analysis took too long and was stopped.',
  INF_FAILED: 'The analysis failed. Please try again.',
  INF_PREDICTION_NOT_FOUND: 'That result was not found.',
  XAI_UNAVAILABLE: 'No explainability visualisation is available for this result.',
  XAI_FILE_MISSING: 'This visualisation was recorded, but its file is no longer available.',
  RPT_GENERATION_FAILED: 'The PDF report could not be generated.',
};

export function messageFor(err: unknown): string {
  if (err instanceof ApiError) return MESSAGES[err.code] ?? err.message;
  if (err instanceof Error) return err.message;
  return 'Something went wrong.';
}

async function send(endpoint: string, options: RequestInit, token: string | null | undefined): Promise<Response> {
  const headers = new Headers(options.headers);
  const auth = token === undefined ? getToken() : token;
  if (auth) headers.set('Authorization', `Bearer ${auth}`);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err;
    throw new ApiError('NETWORK_ERROR', 'Cannot reach the server. Check your connection and try again.', 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const code = body?.error?.code ?? `HTTP_${response.status}`;
    const message = body?.error?.message ?? `Request failed with status ${response.status}`;
    if (response.status === 401 && auth) {
      setToken(null);
      unauthorizedHandler?.();
    }
    throw new ApiError(code, message, response.status, body?.error?.request_id, body);
  }
  return response;
}

export async function apiRequest<T>(endpoint: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const response = await send(endpoint, options, token);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function postJson<T>(endpoint: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/** A file from an authenticated endpoint, as a Blob. */
export async function apiBlob(endpoint: string, signal?: AbortSignal): Promise<Blob> {
  const response = await send(endpoint, { signal }, undefined);
  return response.blob();
}

/** Strip the /api/v1 prefix the backend puts on its own URLs. */
export function apiPath(url: string): string {
  return url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url;
}
