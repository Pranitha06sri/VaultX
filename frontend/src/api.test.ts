import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, daysUntil, formatDate, money, requireReason } from './api';

afterEach(() => vi.unstubAllGlobals());
describe('review safety and API integration', () => {
  it('blocks reviews without a meaningful reason before contacting the API', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    expect(() => api.review('record-1', { action: 'approve', reason: ' ' })).toThrow('reason');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('sends reason, actor and key with a real review request', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'approved' }) }); vi.stubGlobal('fetch', fetch);
    await api.review('record-1', { action: 'approve', reason: ' Evidence checked ' });
    const [url, options] = fetch.mock.calls[0];
    expect(url).toContain('/instruments/record-1/review');
    expect(options.headers['X-API-Key']).toBeTruthy();
    expect(JSON.parse(options.body).reason).toBe('Evidence checked');
  });
  it('surfaces backend transition errors instead of reporting success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'Already approved' }) }));
    await expect(api.review('record-1', { action: 'reject', reason: 'Check required' })).rejects.toThrow('Already approved');
  });
  it('rejects a persisted extraction failure even when the endpoint returns HTTP 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 'record-1', extraction_error: 'Model timed out' }) }));
    await expect(api.extract('record-1', 'gemma')).rejects.toThrow('Model timed out');
  });
  it('builds encoded list filters', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [] }) }); vi.stubGlobal('fetch', fetch);
    await api.instruments('Bank & Trust', 'pending_review', 2);
    expect(fetch.mock.calls[0][0]).toContain('q=Bank+%26+Trust');
    expect(fetch.mock.calls[0][0]).toContain('page=2');
  });
});
describe('financial and date display', () => {
  it('handles unknown values without manufacturing data', () => { expect(money(null)).toBe('Not extracted'); expect(daysUntil(null)).toBeNull(); expect(formatDate(null)).toBe('—'); });
  it('does not assume a currency when only the amount was extracted', () => { expect(money('10000', '')).toBe('10000 · currency unknown'); });
  it('formats valid financial values and rejects short reasons', () => { expect(money('100000.50', 'INR')).toContain('1,00,000.5'); expect(() => requireReason('no')).toThrow(); });
  it('preserves cents and integer precision for amounts larger than JavaScript safe integers', () => { expect(money('999999999999999999.99', 'INR')).toContain('9,99,99,99,99,99,99,99,999.99'); });
});
