export type Status = 'uploaded' | 'pending_review' | 'clarification_requested' | 'approved' | 'rejected';
export const fieldNames = { instrument_number: 'Instrument number', bank_name: 'Issuing bank', amount: 'Deposit amount', currency: 'Currency', issue_date: 'Issue date', maturity_date: 'Maturity date', holder_name: 'Holder / institution' };
export type FieldKey = keyof typeof fieldNames;
export type Fields = Record<FieldKey, string | null>;
export interface Evidence { field: string; page: number; quote: string }
export interface Extraction { fields: Fields; evidence: Evidence[]; uncertain_fields: string[]; missing_fields: string[]; mode: string; model?: string }
export interface Finding { id: string; rule_id: string; severity: 'error' | 'warning' | 'info'; field?: string; observed_value: unknown; expected_value: unknown; explanation: string; resolved: boolean; resolution_reason: string | null }
export interface Audit { id: string; instrument_id: string; action: string; actor: string; timestamp: string; reason: string | null; from_status: string | null; to_status: string | null; details: unknown }
export interface Instrument { id: string; status: Status; created_at: string; updated_at: string; filename: string; mime_type: string; size_bytes: number; fields: Fields; original_extraction: Extraction | null; extraction_mode: string | null; extraction_error: string | null; findings: Finding[]; audit?: Audit[] }
export interface InstrumentList { items: Instrument[]; total: number; page: number; page_size: number }
export interface Dashboard { total: number; pending: number; flagged: number; upcoming: number; activity: Audit[]; upcoming_instruments: Instrument[]; by_status: Record<string, number>; reminder_days: number; minimum_amount: string; currency: string; extraction_mode: string }
export interface Health { status: string; extraction_mode: string; model: string | null; ocr_available: boolean; ocr_runtime_verified: boolean; demo_auth: boolean; max_upload_mb: number; max_document_pages: number }
export interface Sample { name: string; title: string; description: string }
export type ReviewAction = 'correct' | 'resolve' | 'clarify' | 'approve' | 'reject';
export interface ReviewInput { action: ReviewAction; reason: string; fields?: Partial<Fields>; finding_id?: string }

const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const apiKey = import.meta.env.VITE_API_KEY || 'local-demo-key';

export function headers(): HeadersInit { return { 'X-API-Key': apiKey, 'X-Actor': 'Local reviewer' }; }

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...options, headers: { ...headers(), ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((item: { msg?: string }) => item.msg || 'Invalid input').join('; ') : body.detail?.message || message;
    } catch { /* The status is retained when the server returns a non-JSON error. */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function download(path: string): Promise<Blob> {
  const response = await fetch(`${base}${path}`, { headers: headers() });
  if (!response.ok) throw new Error(`Document could not be loaded (${response.status}).`);
  return response.blob();
}

export function requireReason(reason: string): string {
  const value = reason.trim();
  if (value.length < 3) throw new Error('Add a clear reason of at least 3 characters.');
  return value;
}

export const api = {
  health: () => request<Health>('/health'),
  dashboard: () => request<Dashboard>('/dashboard'),
  instruments: (search = '', status = '', page = 1) => request<InstrumentList>(`/instruments?${new URLSearchParams({ q: search, status, page: String(page), page_size: '8' })}`),
  instrument: (id: string) => request<Instrument>(`/instruments/${encodeURIComponent(id)}`),
  upload: (file: File) => { const body = new FormData(); body.append('file', file); return request<Instrument>('/instruments/upload', { method: 'POST', body }); },
  extract: async (id: string, mode: string) => {
    const record = await request<Instrument>(`/instruments/${encodeURIComponent(id)}/extract`, { method: 'POST', body: JSON.stringify({ mode }) });
    // Failed attempts are persisted for the audit trail, so a 200 response alone is insufficient.
    if (record.extraction_error) throw new Error(record.extraction_error);
    return record;
  },
  validate: (id: string) => request<Instrument>(`/instruments/${encodeURIComponent(id)}/validate`, { method: 'POST' }),
  review: (id: string, input: ReviewInput) => request<Instrument>(`/instruments/${encodeURIComponent(id)}/review`, { method: 'POST', body: JSON.stringify({ ...input, reason: requireReason(input.reason) }) }),
  audit: () => request<Audit[]>('/audit'),
  seed: () => request<unknown>('/demo/seed', { method: 'POST' }),
  samples: () => request<Sample[]>('/samples'),
};

export function money(value?: string | null, currency = ''): string {
  if (!value) return 'Not extracted';
  if (!currency) return `${value} · currency unknown`;
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return value;
  const [integer, fraction = ''] = value.split('.');
  try {
    // BigInt preserves every deposited rupee; a Number can silently round large amounts.
    const parts = new Intl.NumberFormat('en-IN', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).formatToParts(BigInt(integer));
    return parts.map(part => part.type === 'fraction' ? fraction.padEnd(2, '0') : part.value).join('');
  }
  catch { return `${currency} ${value}`; }
}

export function formatDate(value?: string | null, withTime = false): string {
  if (!value) return '—';
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}) }).format(date);
}

export function daysUntil(value?: string | null): number | null {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  return Math.round((date.getTime() - today.getTime()) / 86_400_000);
}

export function displayValue(value: unknown): string {
  return value === null || value === undefined ? 'Not available' : typeof value === 'object' ? JSON.stringify(value) : String(value);
}
