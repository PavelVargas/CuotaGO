/* Real worker source in a Node VM with isolated network/cache doubles.
 * This does NOT claim browser SW installation or real offline navigation.
 * Run: node --test tests/test_service_worker_runtime.cjs
 */
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const test = require('node:test');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../cuotago/static/service-worker.js'), 'utf8');
const origin = 'https://cuotago.test';
const never = () => new Promise(() => {});
const response = (text, type = 'basic') => {
  const r = new Response(text);
  Object.defineProperty(r, 'type', {value: type});
  return r;
};
const soon = (promise) => Promise.race([
  promise,
  new Promise((_, reject) => { const t = setTimeout(() => reject(Error('blocked on optional cache work')), 250); t.unref(); }),
]);
function fixture(overrides = {}) {
  const handlers = {}, requests = [], writes = [];
  const cache = { put: async (...args) => writes.push(args) };
  const ctx = vm.createContext({ URL, Response, AbortController, console, setTimeout, clearTimeout,
    self: { location: new URL(`${origin}/service-worker.js?v=test`), addEventListener: (n, f) => handlers[n] = f,
      skipWaiting: () => {}, registration: {}, clients: {claim: async () => {}, matchAll: async () => []} },
    caches: {open: async () => cache, match: async () => null, keys: async () => [], delete: async () => true},
    fetch: async (...args) => {requests.push(args); return response('live');}, ...overrides,
  });
  vm.runInContext(source, ctx);
  const invoke = (request, preloadResponse = Promise.resolve(undefined)) => {
    const tasks = []; let answered = false, result;
    handlers.fetch({ request, preloadResponse, waitUntil: (p) => tasks.push(p),
      respondWith: (p) => {answered = true; result = p;} });
    return {answered, result, tasks};
  };
  return {ctx, handlers, requests, writes, invoke};
}
const request = (p, mode = 'cors', method = 'GET') => ({url: origin + p, mode, method});

test('navigation preload is delivered once, no parallel duplicate fetch', async () => {
  const f = fixture();
  const event = f.invoke(request('/clients', 'navigate'), Promise.resolve(response('preloaded')));
  assert.equal(await (await event.result).text(), 'preloaded');
  assert.equal(f.requests.length, 0); assert.equal(f.writes.length, 0);
});
test('absent preload fetches live tenant HTML without storing it', async () => {
  const f = fixture(); const event = f.invoke(request('/sales', 'navigate'));
  assert.equal(await (await event.result).text(), 'live');
  assert.equal(f.requests.length, 1); assert.equal(f.writes.length, 0);
});
test('deadline includes unresolved preload, and never starts duplicate fetch after timeout', async () => {
  const f = fixture();
  f.ctx.req = request('/sales', 'navigate'); f.ctx.preload = never();
  await assert.rejects(vm.runInContext('fetchWithTimeout(req, 20, preload)', f.ctx), /navigation_timeout/);
  assert.equal(f.requests.length, 0);
});
test('deadline aborts a stalled fetch', async () => {
  let signal;
  const f = fixture({fetch: (_, opts) => {signal = opts.signal; return never();}});
  f.ctx.req = request('/sales', 'navigate');
  await assert.rejects(vm.runInContext('fetchWithTimeout(req, 20)', f.ctx), /navigation_timeout/);
  assert.equal(signal.aborted, true);
});
test('network failure uses the neutral offline shell', async () => {
  const f = fixture({fetch: async () => {throw Error('offline');}, caches: {match: async () => response('offline shell')}});
  const event = f.invoke(request('/assets', 'navigate'));
  assert.equal(await (await event.result).text(), 'offline shell');
});
test('network failure without precache has an explicit no-store response', async () => {
  const f = fixture({fetch: async () => {throw Error('offline');}});
  const result = await f.invoke(request('/assets', 'navigate')).result;
  assert.equal(result.status, 503); assert.equal(result.headers.get('cache-control'), 'no-store');
});
test('versioned cache hit avoids another network request', async () => {
  const f = fixture({caches: {match: async () => response('cached')}});
  assert.equal(await (await f.invoke(request('/static/css/app.css?v=test')).result).text(), 'cached');
  assert.equal(f.requests.length, 0);
});
test('static response never waits for cache disk open/write', async () => {
  const f = fixture({caches: {match: async () => null, open: never}});
  const event = f.invoke(request('/static/css/app.css?v=test'));
  assert.equal(await (await soon(event.result)).text(), 'live');
  assert.equal(event.tasks.length, 1);
});
test('optional disk write failure does not reject delivered response', async () => {
  const f = fixture({caches: {match: async () => null, open: async () => ({put: async () => {throw Error('quota');}})}});
  const event = f.invoke(request('/static/js/app.js?v=test'));
  assert.equal(await (await event.result).text(), 'live');
  await Promise.all(event.tasks);
});
test('unversioned cached asset is delivered during a stalled refresh', async () => {
  const f = fixture({fetch: never, caches: {match: async () => response('cached')}});
  assert.equal(await (await soon(f.invoke(request('/static/icons/icon-192.png')).result)).text(), 'cached');
});
test('worker does not intercept APIs, private photos, customer receipts, other origins or writes', () => {
  const f = fixture();
  for (const r of [request('/api/notifications?summary=1'), request('/assets/1/image?thumb=1'),
    request('/sales/1/receipt.pdf', 'navigate'), request('/sales/1/receipt', 'navigate'),
    request('/sales/new', 'navigate', 'POST'), {url:'https://other.test/x', mode:'cors', method:'GET'}]) {
    assert.equal(f.invoke(r).answered, false, r.url);
  }
});
test('install prefetch concurrency is capped at four, individual failures tolerated', async () => {
  let active = 0, peak = 0, count = 0, disk = 0;
  const f = fixture({fetch: async () => {
    count++; active++; peak = Math.max(peak, active);
    await new Promise(r => setTimeout(r, 3)); active--;
    if (count % 7 === 0) throw Error('optional unavailable');
    return response('asset');
  }, caches: {open: async () => ({put: async () => {disk++;}})}});
  let work; f.handlers.install({waitUntil: p => work=p}); await work;
  assert.ok(count > 20); assert.equal(peak, 4); assert.ok(disk > 0);
});
