/** Installed-Chrome smoke test. Requires Node 22+ and the local app on ports 5173/8001.
 * Exercises the real UI against synthetic documents only. No npm browser dependency.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const local = path.join(root, '.local');
const origin = process.env.SMOKE_FRONTEND_URL || 'http://127.0.0.1:5173';
const backend = process.env.SMOKE_BACKEND_URL || 'http://127.0.0.1:8001';
const apiKey = process.env.SMOKE_API_KEY || 'local-demo-key';
const port = Number(process.env.SMOKE_DEBUG_PORT || 19222);
const chromePath = process.env.CHROME_BIN || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const checks = [];
const consoleErrors = [];
const networkErrors = [];
const requests = new Map();
const summary = { started_at: new Date().toISOString(), checks, console_errors: consoleErrors, network_errors: networkErrors, passed: false };
let chrome;
let browser;
let session;
let activeStep = 'launch';

class CDP {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const waiter = this.pending.get(message.id);
        if (!waiter) return;
        clearTimeout(waiter.timer);
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(`${waiter.method}: ${message.error.message}`));
        else waiter.resolve(message.result || {});
      } else {
        for (const listener of this.listeners) listener(message);
      }
    });
    socket.addEventListener('close', () => {
      for (const waiter of this.pending.values()) {
        clearTimeout(waiter.timer);
        waiter.reject(new Error('Chrome debugging connection closed'));
      }
      this.pending.clear();
    });
  }
  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Chrome WebSocket connection timed out')), 10000);
      socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Chrome WebSocket connection failed')); }, { once: true });
    });
    return new CDP(socket);
  }
  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      this.pending.set(id, { resolve, reject, timer, method });
      this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }
}

const send = (method, params) => browser.send(method, params, session);
async function evaluate(expression) {
  const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
  return result.result.value;
}
async function waitFor(expression, description, timeout = 15000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await evaluate(expression)) return;
    await pause(100);
  }
  const visible = await evaluate('document.body?.innerText?.slice(-2500)');
  throw new Error(`Timed out waiting for ${description}. Visible text: ${visible}`);
}
async function step(name, run) {
  activeStep = name;
  const start = Date.now();
  await run();
  checks.push({ name, passed: true, milliseconds: Date.now() - start });
  console.log(`PASS ${name}`);
}
async function click(selector, text) {
  const result = await evaluate(`(() => {
    const nodes = [...document.querySelectorAll(${JSON.stringify(selector)})];
    const node = nodes.find(item => ${text === undefined ? 'true' : `item.textContent.trim() === ${JSON.stringify(text)}`});
    if (!node) return 'missing';
    if (node.disabled) return 'disabled';
    node.click(); return 'clicked';
  })()`);
  assert.equal(result, 'clicked', `Cannot click ${selector} ${text || ''}: ${result}`);
}
async function setValue(selector, value) {
  await evaluate(`(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) throw new Error('Form control not found');
    const prototype = node instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : node instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, 'value').set.call(node, ${JSON.stringify(value)});
    node.dispatchEvent(new Event(node instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }));
  })()`);
  await pause(30);
}
async function navigate(route, ready) {
  await evaluate(`window.location.hash = ${JSON.stringify(route)}`);
  await waitFor(ready, route);
}
async function record() {
  const id = await evaluate('decodeURIComponent(location.hash.slice(12))');
  const response = await fetch(`${backend}/instruments/${encodeURIComponent(id)}`, { headers: { 'X-API-Key': apiKey }, signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200);
  return response.json();
}
async function saveDialog(reason) {
  await waitFor('!!document.querySelector("[role=dialog]")', 'review dialog');
  assert.equal(await evaluate('document.querySelector("[role=dialog] button[type=submit]").disabled'), true, 'A reason must be required');
  await setValue('#review-reason', reason);
  await click('[role=dialog] button[type=submit]');
  await waitFor('!document.querySelector("[role=dialog]")', 'saved review action');
  await waitFor('!!document.querySelector(".success-box")', 'review success');
}
async function uploadFixture(name) {
  const response = await fetch(`${backend}/samples/${name}`, { headers: { 'X-API-Key': apiKey }, signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, 'Synthetic fixture download');
  const file = path.join(local, `browser-${name}`);
  await writeFile(file, Buffer.from(await response.arrayBuffer()));
  await navigate('upload', '!!document.querySelector("input[type=file]")');
  const { root: documentNode } = await send('DOM.getDocument', {});
  const { nodeId } = await send('DOM.querySelector', { nodeId: documentNode.nodeId, selector: 'input[type=file]' });
  await send('DOM.setFileInputFiles', { nodeId, files: [file] });
  await waitFor('!document.querySelector(".upload-submit button[type=submit]").disabled', 'upload file selection');
  await click('.upload-submit button[type=submit]');
  await waitFor('location.hash.startsWith("#instrument/") && !!document.querySelector(".extraction-source")', 'upload, extraction and review screen', 30000);
  return record();
}

try {
  await mkdir(local, { recursive: true });
  if (!existsSync(chromePath)) throw new Error('Installed Chrome was not found. Set CHROME_BIN to the browser executable.');
  chrome = spawn(chromePath, [
    '--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
    '--disable-default-apps', '--disable-extensions', '--window-size=1440,1100',
    `--remote-debugging-port=${port}`, `--user-data-dir=${path.join(local, 'browser-smoke')}`, 'about:blank',
  ], { cwd: root, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  let launchError;
  chrome.on('error', error => { launchError = error; });
  let diagnostics = '';
  chrome.stderr.on('data', chunk => { diagnostics = (diagnostics + chunk).slice(-3000); });
  let version;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (launchError) throw launchError;
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(500) });
      if (response.ok) { version = await response.json(); break; }
    } catch { /* Chrome needs a short startup window. */ }
    await pause(100);
  }
  if (!version) throw new Error(`Chrome debugging endpoint did not start: ${diagnostics}`);
  browser = await CDP.connect(version.webSocketDebuggerUrl);
  const { targetId } = await browser.send('Target.createTarget', { url: 'about:blank' });
  ({ sessionId: session } = await browser.send('Target.attachToTarget', { targetId, flatten: true }));
  browser.listeners.push(message => {
    if (message.sessionId !== session) return;
    const data = message.params || {};
    if (message.method === 'Runtime.exceptionThrown') consoleErrors.push(data.exceptionDetails.exception?.description || data.exceptionDetails.text);
    if (message.method === 'Runtime.consoleAPICalled' && data.type === 'error') consoleErrors.push(data.args.map(arg => arg.value || arg.description || '').join(' '));
    if (message.method === 'Network.requestWillBeSent') requests.set(data.requestId, data.request.url);
    if (message.method === 'Network.responseReceived' && data.response.status >= 400 && data.response.url.startsWith(origin)) networkErrors.push({ url: data.response.url, status: data.response.status });
    if (message.method === 'Network.loadingFailed' && !data.canceled && requests.get(data.requestId)?.startsWith(origin)) networkErrors.push({ url: requests.get(data.requestId), error: data.errorText });
  });
  await send('Page.enable', {});
  await send('Runtime.enable', {});
  await send('Network.enable', {});
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });

  await step('Dashboard connects to the actual backend', async () => {
    await send('Page.navigate', { url: origin });
    await waitFor('document.querySelectorAll(".metric-value").length === 4 && [...document.querySelectorAll(".metric-value")].every(node => /^\\d/.test(node.textContent.trim()))', 'live dashboard metrics');
    assert.match(await evaluate('document.body.innerText'), /Backend connected/);
  });
  await step('Load synthetic samples through the UI and verify the register', async () => {
    await click('.mode-banner button');
    await waitFor('Number(document.querySelector(".metric-value").textContent.replaceAll(",", "")) >= 5 && document.querySelectorAll("tbody tr").length >= 5', 'sample workspace');
    await waitFor('!document.querySelector(".mode-banner button").disabled', 'sample load complete');
    const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    await writeFile(path.join(local, 'dashboard.png'), Buffer.from(screenshot.data, 'base64'));
  });
  await step('Review queue search and filtering use persisted records', async () => {
    await click('nav a[href="#queue"]');
    await waitFor(`!!document.querySelector('select[aria-label="Filter by status"]') && document.querySelectorAll('tbody tr').length > 0`, 'review queue');
    await setValue('input[aria-label="Search instruments"]', 'SYN-FDR-2026-004');
    await waitFor('document.querySelectorAll("tbody tr").length === 1 && document.querySelector("tbody").innerText.includes("SYN-FDR-2026-004")', 'instrument search');
    await setValue('select[aria-label="Filter by status"]', 'approved');
    await waitFor('document.body.innerText.includes("No matching instruments")', 'status filter');
  });

  let uploaded;
  await step('Browser uploads a synthetic PDF, extracts, validates and previews privately', async () => {
    uploaded = await uploadFixture('valid-fdr.pdf');
    assert.equal(uploaded.extraction_mode, 'demo');
    assert.equal(uploaded.status, 'pending_review');
    assert.equal(uploaded.original_extraction.fields.amount, '250000.00');
    await waitFor('document.querySelector(".document-viewer iframe")?.src.startsWith("blob:")', 'authenticated document blob preview');
    assert.match(await evaluate('document.querySelector(".extraction-source").innerText'), /no AI inference/);
    await click('.evidence summary');
    assert.match(await evaluate('document.querySelector(".evidence[open]").innerText'), /Page 1/);
  });
  await step('Findings require an explanation before resolution', async () => {
    await click('[role=tab]', 'Findings' + String(uploaded.findings.filter(finding => !finding.resolved).length));
    await waitFor('!!document.querySelector(".finding")', 'duplicate findings');
    assert.match(await evaluate('document.querySelector(".findings-list").innerText'), /DUPLICATE_NUMBER/);
    await click('.finding button');
    await saveDialog('Browser smoke: synthetic duplicate inspected; will correct the test receipt identifier.');
    assert((await record()).findings.some(finding => finding.resolved));
  });
  await step('Clarification and correction preserve the original extraction', async () => {
    await click('.decision-buttons button', 'Clarify');
    await saveDialog('Browser smoke: confirm a unique synthetic instrument number before approval.');
    assert.equal((await record()).status, 'clarification_requested');
    await click('[role=tab]', 'Extracted fields');
    await click('.field-actions button', 'Correct fields');
    await waitFor('!!document.querySelector(".correction-grid input")', 'correction form');
    const uniqueNumber = `SYN-BROWSER-${Date.now()}`;
    await setValue('.correction-grid label:first-child input', uniqueNumber);
    await saveDialog('Browser smoke: assigned a unique identifier to this synthetic test receipt.');
    const updated = await record();
    assert.equal(updated.status, 'pending_review');
    assert.equal(updated.fields.instrument_number, uniqueNumber);
    assert.deepEqual(updated.original_extraction, uploaded.original_extraction);
    assert.equal(updated.findings.filter(finding => !finding.resolved).length, 0);
    assert.match(await evaluate('document.querySelector(".fields-grid").innerText'), /CORRECTED/);
  });
  await step('Validation and approval record human reasons in the audit trail', async () => {
    await click('.field-actions button', 'Re-run validation');
    await waitFor('document.querySelector(".success-box")?.innerText.includes("Validation complete")', 'manual validation');
    await click('.decision-buttons button', 'Approve');
    await saveDialog('Browser smoke: original synthetic receipt and all evidence inspected; review approved.');
    const approved = await record();
    assert.equal(approved.status, 'approved');
    assert(approved.audit.some(event => event.action === 'approve' && event.reason.startsWith('Browser smoke:')));
    await click('[role=tab]', 'History');
    await waitFor('document.querySelector(".review-panel-body")?.innerText.includes("Browser smoke: original synthetic")', 'record history');
    assert.equal(await evaluate('!!document.querySelector(".final-decision")'), true);
  });
  await step('Rejecting an incomplete synthetic receipt requires a reason', async () => {
    await uploadFixture('missing-fields.pdf');
    await click('.decision-buttons button', 'Reject');
    await saveDialog('Browser smoke: synthetic receipt lacks required holder and maturity evidence.');
    assert.equal((await record()).status, 'rejected');
  });
  await step('Workspace audit search and action filter show persisted decisions', async () => {
    await click('nav a[href="#audit"]');
    await waitFor(`!!document.querySelector('input[aria-label="Search audit history"]') && !!document.querySelector('.activity-list')`, 'workspace audit');
    await setValue('input[aria-label="Search audit history"]', uploaded.id);
    await waitFor('document.querySelector(".audit-panel")?.innerText.includes("Browser smoke: original synthetic")', 'audit record search');
    await setValue('select[aria-label="Filter audit action"]', 'approve');
    await waitFor('document.querySelector(".audit-panel")?.innerText.includes("Browser smoke: original synthetic")', 'audit action filter');
  });
  await step('Mobile screens fit a 390px viewport and menu navigation works', async () => {
    await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
    for (const [route, ready] of [
      ['dashboard', 'document.querySelectorAll(".metric-value").length === 4'],
      ['queue', '!!document.querySelector(".records-panel")'],
      ['upload', '!!document.querySelector(".upload-form")'],
      ['audit', '!!document.querySelector(".audit-panel")'],
      [`instrument/${uploaded.id}`, '!!document.querySelector(".detail-layout")'],
    ]) {
      await navigate(route, ready);
      await pause(150);
      const sizes = await evaluate('({ viewport: innerWidth, width: document.documentElement.scrollWidth })');
      assert(sizes.width <= sizes.viewport + 1, `${route} overflows: ${JSON.stringify(sizes)}`);
    }
    await click('button[aria-label="Open menu"]');
    assert.equal(await evaluate('document.querySelector(".sidebar").classList.contains("open")'), true);
    await click('nav a[href="#dashboard"]');
    await waitFor('!document.querySelector(".sidebar").classList.contains("open") && location.hash === "#dashboard"', 'mobile menu navigation');
  });
  await step('No application console exceptions or failed network requests', async () => {
    assert.deepEqual(consoleErrors, []);
    assert.deepEqual(networkErrors, []);
    assert.equal(await evaluate('document.querySelectorAll("[role=alert]").length'), 0);
  });
  summary.passed = true;
} catch (error) {
  summary.error = { step: activeStep, message: error.message, stack: error.stack };
  console.error(`FAIL ${activeStep}: ${error.message}`);
  process.exitCode = 1;
} finally {
  summary.finished_at = new Date().toISOString();
  await mkdir(local, { recursive: true });
  await writeFile(path.join(local, 'browser-smoke.json'), JSON.stringify(summary, null, 2) + '\n');
  if (browser) {
    try { await browser.send('Browser.close'); } catch { /* Closing Chrome also closes its transport. */ }
    browser.socket.close();
  }
  if (chrome && chrome.exitCode === null) chrome.kill('SIGTERM');
}
