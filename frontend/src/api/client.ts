/**
 * Abhijatri Base API Client
 * Base URL resolution, headers, and the single error contract of Platform Foundation 12.3:
 * every error body is { error: { code, message, request_id, field_errors } }.
 * Callers branch on `code`, never on `message`.
 */

import type { ApiErrorBody, FieldError } from '../types';

/**
 * In a production build the app calls `/api/...` on its own address and Vercel forwards it to the
 * API (vercel.json). The session cookies then belong to this site, so browsers keep them; cookies of
 * another site (the Railway API) are not sent on cross-site requests. Set VITE_API_DIRECT=true only
 * when the API is served from the same site. Development uses VITE_API_BASE_URL (localhost:8000).
 */
const configuredApi = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '');
export const API_BASE_URL: string = import.meta.env.PROD && import.meta.env.VITE_API_DIRECT !== 'true' ? '' : configuredApi;

export class ApiError extends Error {
  status: number;
  code: string;
  requestId?: string;
  fieldErrors: FieldError[];

  constructor(status: number, code: string, message: string, requestId?: string, fieldErrors: FieldError[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.fieldErrors = fieldErrors;
  }
}

/** Raised when the request never produced an HTTP response (offline, DNS, CORS, aborted). */
export const NETWORK_ERROR = 'NETWORK_ERROR';

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  params?: Record<string, string | number | boolean | undefined | null>;
  body?: unknown;
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false;
  const error = (value as { error: unknown }).error;
  return typeof error === 'object' && error !== null && typeof (error as { code?: unknown }).code === 'string';
}

/**
 * JSON fetch helper.
 *
 * - `Accept-Language` follows the interface language, so server error messages match it.
 * - `Content-Type` is sent only with a body: public GETs stay CORS "simple" requests with no
 *   preflight round trip on slow networks (Platform Foundation 16.1).
 */
export async function apiRequest<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { params, headers, body, ...rest } = options;

  let url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, val]) => {
      if (val !== undefined && val !== null) searchParams.append(key, String(val));
    });
    const qs = searchParams.toString();
    if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  }

  const requestHeaders: Record<string, string> = {
    Accept: 'application/json',
    'Accept-Language': document.documentElement.lang === 'en' ? 'en' : 'bn',
  };
  if (body !== undefined) requestHeaders['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: { ...requestHeaders, ...(headers as Record<string, string> | undefined) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, NETWORK_ERROR, error instanceof Error ? error.message : 'Network request failed');
  }

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      // Non-JSON error body (proxy or gateway page)
    }
    if (isErrorBody(parsed)) {
      const { code, message, request_id, field_errors } = parsed.error;
      throw new ApiError(response.status, code, message, request_id, field_errors ?? []);
    }
    throw new ApiError(response.status, `HTTP_${response.status}`, response.statusText || `HTTP ${response.status}`);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
