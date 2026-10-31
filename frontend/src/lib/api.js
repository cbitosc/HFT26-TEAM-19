// Real API client (contract: docs/api-contract.md). Demo mode (?demo=1) swaps in a
// synthetic board with canned results; the UI labels it as demo data at all times.
import { demoApi } from './demo.js';

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parse(res) {
  if (res.ok) return res.json();
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  const d = body?.detail;
  const message = body?.message || (typeof d === 'string' ? d : d?.message) || res.statusText || 'Request failed';
  const code = body?.code || (typeof d === 'object' ? d?.code : null) || `http_${res.status}`;
  throw new ApiError(res.status, code, message);
}

async function call(path, init) {
  let res;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError(0, 'network', 'The VisionGuard server is not reachable. Start the backend, then reload this page.');
  }
  return parse(res);
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

const realApi = {
  health: () => call('/health'),
  uploadImage(file) {
    const fd = new FormData();
    fd.append('image', file);
    return call('/images', { method: 'POST', body: fd });
  },
  startAnalysis: (imageId) => call('/analyses', json('POST', { image_id: imageId })),
  getAnalysis: (jobId) => call(`/analyses/${encodeURIComponent(jobId)}`),
  cancelAnalysis: (jobId) => call(`/analyses/${encodeURIComponent(jobId)}`, { method: 'DELETE' }),
  patchObservation: (id, patch) => call(`/observations/${encodeURIComponent(id)}`, json('PATCH', patch)),
  findSimilar: (id) => call(`/observations/${encodeURIComponent(id)}/similar`, { method: 'POST' }),
  confirmBoard: (imageId, variant) => call(`/images/${encodeURIComponent(imageId)}`, json('PATCH', { board_variant: variant })),
};

export const isDemo = new URLSearchParams(window.location.search).has('demo');
export const api = isDemo ? demoApi : realApi;
