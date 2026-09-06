import {test} from 'node:test';
import assert from 'node:assert/strict';
import {access} from 'node:fs/promises';
import {PROFILE, modelDefinition, validateRequest, assertSession, assertPayload, extractAnswer, runWithPi} from '../scripts/v213_pi_inference.mjs';
const payload = () => ({model: PROFILE.model_id, stream: true, max_tokens: 4096,
  chat_template_kwargs: {enable_thinking: true, reasoning_effort: 'xhigh'}, reasoning_format: 'deepseek'});
const freshSession = () => ({model: modelDefinition(), thinkingLevel: 'xhigh', agent: {state: {tools: []}},
  messages: [{role: 'assistant', model: PROFILE.model_id, provider: PROFILE.provider, stopReason: 'stop', content: [{type: 'text', text: 'public answer'}]}]});

test('exact physical-model identity and explicit XHIGH request mapping', () => {
  const m = modelDefinition();
  assert.equal(m.thinkingLevelMap.xhigh, 'xhigh');
  assert.equal(m.reasoning, true);
  assert.equal(m.thinkingLevelMap.off, null);
  assert.equal(m.baseUrl, 'http://127.0.0.1:8080/v1');
  assert.equal(PROFILE.production_ready, false);
  assert.equal(PROFILE.direct_http_fallback, false);
  assertPayload(payload());
});

test('reject caller overrides, invalid query and oversized input', () => {
  for (const q of [null, [], {}, {query: ''}, {query: 'x'.repeat(361)}, {query: 2}, {query: 'x', model: 'other'}, {query: 'x', system: 'override'}])
    assert.throws(() => validateRequest(q), /PI_PUBLIC_REQUEST_INVALID/);
});

test('reject silent thinking downgrade, alias, remote backend, tools and persisted sessions', () => {
  for (const change of [s => s.thinkingLevel = 'off', s => s.model.id = 'qwen38-q6',
    s => s.model.baseUrl = 'https://example.invalid', s => s.agent.state.tools.push({name: 'read'}),
    s => s.sessionFile = '/owner/session.jsonl']) {
    const s = freshSession(); change(s); assert.throws(() => assertSession(s), /PI_/);
  }
});

test('verify actual payload fields, not just UI thinking setting', () => {
  for (const change of [p => p.model = 'qwen38-q6', p => p.stream = false,
    p => p.chat_template_kwargs.enable_thinking = false, p => p.chat_template_kwargs.reasoning_effort = 'high',
    p => p.max_tokens = 4097, p => p.max_tokens = true, p => p.tools = [{name: 'bash'}],
    p => p.reasoning_format = 'none']) {
    const p = payload(); change(p); assert.throws(() => assertPayload(p), /PI_XHIGH_PAYLOAD_INVALID/);
  }
});

test('do not expose reasoning, accept truncation or coerce malformed content', () => {
  const s = freshSession(); s.messages[0].content.unshift({type: 'thinking', thinking: 'private reasoning fixture'});
  assert.equal(extractAnswer(s).content, 'public answer');
  for (const change of [s => s.messages[0].stopReason = 'length', s => s.messages[0].model = 'other',
    s => s.messages[0].content = [{type: 'toolCall'}], s => s.messages[0].content = [{type: 'text', text: 3}],
    s => s.messages[0].content = [{type: 'text', text: '<think>hidden</think>answer'}]]) {
    const s = freshSession(); change(s); assert.throws(() => extractAnswer(s), /PI_/);
  }
});

function mockSdk({downgrade = false, missingPayload = false, hang = false} = {}) {
  const observed = {calls: 0, aborted: false, disposed: false};
  const session = freshSession();
  session.prompt = async (q, options) => {
    observed.calls++;
    assert.equal(options.expandPromptTemplates, false);
    assert.ok(q.startsWith('PUBLIC_USER_DATA='));
    if (!missingPayload) session.agent.onPayload(payload());
    if (hang) await new Promise(() => {});
  };
  session.abort = async () => { observed.aborted = true; };
  session.dispose = () => { observed.disposed = true; };
  const sdk = {
    ModelRuntime: {create: async o => { assert.equal(o.allowModelNetwork, false); observed.paths = o; return {}; }},
    SettingsManager: {inMemory: s => {assert.equal(s.retry.enabled, false); return s;}},
    DefaultResourceLoader: class {constructor(o) {assert.equal(o.noExtensions, true); assert.equal(o.noSkills, true); assert.deepEqual(o.agentsFilesOverride(), {agentsFiles: []});} async reload() {}},
    SessionManager: {inMemory: d => {observed.dir = d; return {};}},
    createAgentSession: async o => { assert.equal(o.noTools, 'all'); assert.deepEqual(o.customTools, []); if (downgrade) session.thinkingLevel = 'off'; return {session}; },
  };
  return {sdk, observed};
}

test('SDK caller enforces isolation, wire proof, cleanup and no preflight bypass', async () => {
  for (const options of [{}, {downgrade: true}, {missingPayload: true}, {hang: true}]) {
    const {sdk, observed} = mockSdk(options);
    const request = runWithPi({query: 'public fixture'}, sdk, {timeoutMs: options.hang ? 10 : 1000});
    if (options.downgrade || options.missingPayload || options.hang) await assert.rejects(request, /PI_/);
    else assert.equal((await request).xhigh_payload_validated, true);
    assert.equal(observed.calls, options.downgrade ? 0 : 1);
    assert.equal(observed.aborted, true);
    assert.equal(observed.disposed, true);
    await assert.rejects(access(observed.dir));
  }
});

test('one in-process request at a time; no unbounded queue', async () => {
  const {sdk} = mockSdk({hang: true});
  const first = runWithPi({query: 'one'}, sdk, {timeoutMs: 50});
  const outcome = assert.rejects(first, /PI_DEADLINE_EXCEEDED/);
  await assert.rejects(runWithPi({query: 'two'}, sdk), /PI_CAPACITY_EXHAUSTED/);
  await outcome;
});
