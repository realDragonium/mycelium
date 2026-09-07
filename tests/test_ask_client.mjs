import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const source = readFileSync(new URL('../src/mycelium/cockpit/api.js', import.meta.url), 'utf8');
const result = { outcome: 'answered', answer: 'A café 🧪', confidence: 'medium', interpretation: { as_asked: 'Q', resolved_to: 'Q', reframed: false }, gaps: ['Unknown limit'], provenance: ['stm_1'], trace: {} };
const frame = event => `event: ${event.type}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`;
function client(fetch) {
  const window = {};
  runInNewContext(source, { window, fetch, TextDecoder, DOMException });
  return window.Myc;
}
function response(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({ start(controller) {
    for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
    controller.close();
  }}), { headers: { 'content-type': 'text/event-stream' } });
}

test('fragmented UTF-8, CRLF, keepalive and reset are handled before final result', async () => {
  const events = [];
  const api = client(async () => response(': heartbeat\r\n\r\n' + [
    { type: 'progress', phase: 'retrieval', message: 'Read complete' },
    { type: 'answer_delta', text: 'Wrong draft' },
    { type: 'answer_reset' },
    { type: 'answer_delta', text: 'A café 🧪' },
    { type: 'complete', result },
  ].map(frame).join('')));
  const answer = await api.ask('Q', { onEvent: event => events.push(event) });
  assert.equal(answer.answer[0], result.answer);
  assert.deepEqual(events.map(e => e.type), ['progress', 'answer_delta', 'answer_reset', 'answer_delta']);
  assert.equal(answer.confidence.level, 'medium');
});

test('EOF after partial answer is an incomplete stream', async () => {
  const api = client(async () => response(frame({ type: 'answer_delta', text: 'partial' })));
  await assert.rejects(api.ask('Q', { onEvent() {} }), /connection ended before Ask completed/);
});

test('server errors and malformed completions are never adapted as answers', async () => {
  for (const event of [{ type: 'error', message: 'Ask failed' }, { type: 'complete', result: { detail: 'failure' } }, { type: 'complete', result: { outcome: 'answered' } }]) {
    const api = client(async () => response(frame(event)));
    await assert.rejects(api.ask('Q', { onEvent() {} }));
  }
});

test('clarification completes without answer text', async () => {
  const raw = { outcome: 'needs_clarification', question: 'Which worker?', candidates: [{ interpretation: 'A', would_pull: 'A' }, { interpretation: 'B', would_pull: 'B' }], known_so_far: 'Two workers exist.', trace: {} };
  const api = client(async () => response(frame({ type: 'complete', result: raw })));
  const answer = await api.ask('Q', { onEvent() { assert.fail('No deltas expected'); } });
  assert.equal(answer.outcome, 'needs_clarification');
  assert.equal(answer.interpretations.length, 2);
});

test('legacy JSON remains accepted and receives cancellation signal', async () => {
  const controller = new AbortController();
  const api = client(async (_, opts) => {
    assert.equal(opts.signal, controller.signal);
    return Response.json(result);
  });
  assert.equal((await api.ask('Q', { signal: controller.signal })).answer[0], result.answer);
});

test('cancelled stream rejects even if a completion is buffered', async () => {
  const controller = new AbortController();
  const api = client(async () => response(frame({ type: 'complete', result })));
  controller.abort();
  await assert.rejects(api.ask('Q', { signal: controller.signal, onEvent() {} }), { name: 'AbortError' });
});

test('JSON and streaming requests preserve HTTP error details and status', async () => {
  for (const options of [{}, { onEvent() {} }]) {
    for (const [body, message] of [
      [JSON.stringify({ detail: 'Ask access is restricted.' }), 'Ask access is restricted.'],
      [JSON.stringify({ detail: { reason: 'Rate limit reached' } }), '{"reason":"Rate limit reached"}'],
      ['<html>Unavailable</html>', '429 Too Many Requests'],
    ]) {
      const api = client(async () => new Response(body, { status: 429, statusText: 'Too Many Requests' }));
      await assert.rejects(api.ask('Q', options), err => {
        assert.equal(err.message, message);
        assert.equal(err.status, 429);
        assert.equal(err.path, '/ask');
        return true;
      });
    }
  }
});
