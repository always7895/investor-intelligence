import { readFileSync, writeFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { configuredModelProfile, validateModelProfile, modelProfileSha256 } from '../src/v213/model-profile';
import { compactGeneralAnswer, minimalModelSmoke, SMOKE_MARKER } from '../src/v213/compact-qa';
import { edgeReadiness } from '../src/v213/readiness';
import { v213RuntimeCompatibleFetch } from '../src/v213/production-worker';
import { parseQuery } from '../src/core';
import { MemoryKv, asKv } from './fake-kv';

const profile = { schema_version: 1, model: 'synthetic-model-a', enable_thinking: true,
  reasoning_effort: 'xhigh', max_output_tokens: 1024, smoke_output_tokens: 128, timeout_ms: 18000 };
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('matches the Python canonical digest vector', async () => {
  expect(await modelProfileSha256(validateModelProfile(profile))).toBe('2bea7c8ce0f160ea609ddf82c7f34631a6841f9a939debdb0a663444b5307d19');
});

it.each([
  { schema_version: true }, { model: 'bad\nmodel' }, { model: 'x'.repeat(201) }, { enable_thinking: 'true' },
  { reasoning_effort: [] }, { reasoning_effort: 'unknown' }, { reasoning_effort: 'none' },
  { max_output_tokens: true }, { max_output_tokens: 8193 }, { smoke_output_tokens: 1025 },
  { timeout_ms: 20001 }, { extra: 'unreviewed' },
])('rejects invalid configuration %j', change => {
  expect(() => validateModelProfile({ ...profile, ...change })).toThrow('MODEL_PROFILE_INVALID');
});

it('rejects duplicate keys including escaped spellings, never hides invalid explicit config', () => {
  for (const extra of ['"model":"hidden"', '"\\u006dodel":"hidden"']) {
    expect(() => configuredModelProfile({ V213_MODEL_PROFILE_JSON: JSON.stringify(profile).slice(0, -1) + ',' + extra + '}' })).toThrow();
  }
  expect(() => configuredModelProfile({ V213_MODEL_PROFILE_JSON: '' })).toThrow();
  expect(configuredModelProfile({})).toBeUndefined();
});

it('smoke requires the exact profile pin, not just a successful answer', async () => {
  let digest = await modelProfileSha256(validateModelProfile(profile));
  const native = vi.fn(async () => new Response(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: SMOKE_MARKER } }],
    ii_exact_model_pin: { selected_model: profile.model, request_model_substitution_allowed: false, model_profile_sha256: digest } })));
  vi.stubGlobal('fetch', native);
  const env = { V213_MODEL_PROFILE_JSON: JSON.stringify(profile), LOCAL_LLM_BASE_URL: 'https://gateway.example.test',
    LOCAL_LLM_ALLOWED_HOSTS: 'gateway.example.test', LOCAL_LLM_SHARED_SECRET: 'SYNTHETIC_AUTH' } as any;
  expect(await minimalModelSmoke(env)).toBe(true);
  digest = '0'.repeat(64);
  expect(await minimalModelSmoke(env)).toBe(false);
});

it('readiness binds the same profile and rejects invalid or different configuration without writes', async () => {
  const digest = await modelProfileSha256(validateModelProfile(profile));
  const env = { CF_VERSION_METADATA: { id: '12345678-1234-1234-1234-123456789abc' }, V213_MODEL_PROFILE_JSON: JSON.stringify(profile) };
  const request = (hash: string) => new Request('https://worker.example.test/ready?challenge=' + 'a'.repeat(32) + '&expected_model_profile_sha256=' + hash);
  const ok = await edgeReadiness(request(digest), env);
  expect(ok.status).toBe(200);
  expect((await ok.json() as any).model_profile_sha256).toBe(digest);
  expect((await edgeReadiness(request('0'.repeat(64)), env)).status).toBe(409);
  expect((await edgeReadiness(request(digest), { ...env, V213_MODEL_PROFILE_JSON: '' })).status).toBe(409);
});

it.each(['synthetic-model-a', 'other/model-v2'])('actual public QA caller propagates %s profile without changing source', async model => {
  const selected = { ...profile, model };
  // Optional development fixture emits only the actual Worker's public request,
  // not auth headers, private context or a fabricated model response receipt.
  const liveFixture = process.env.V213_PROFILE_REQUEST_OUT;
  const active = liveFixture ? JSON.parse(readFileSync('../config/v213-model-profile-v1.json', 'utf8')) : selected;
  const bodies: any[] = [];
  const native = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    bodies.push(JSON.parse(String(init?.body)));
    return new Response(JSON.stringify({ choices: [{ finish_reason: 'stop', message: { content: '供應鏈瓶頸是限制整體產出的環節，仍需獨立證據。' } }] }));
  });
  vi.stubGlobal('fetch', (input: RequestInfo | URL, init?: RequestInit) => v213RuntimeCompatibleFetch(native as typeof fetch, input, init));
  const kv = new MemoryKv();
  const env = { PUBLIC_CACHE: asKv(kv), TENANT_PRIVATE_CACHE: asKv(new MemoryKv()), EPHEMERAL_SECURITY_CACHE: asKv(new MemoryKv()),
    GENERAL_QA_ENABLED: 'true', MEMORY_FEATURE_AVAILABLE: 'false', LOCAL_LLM_BASE_URL: 'https://gateway.example.test',
    LOCAL_LLM_ALLOWED_HOSTS: 'gateway.example.test', LOCAL_LLM_SHARED_SECRET: 'SYNTHETIC_AUTH',
    V213_MODEL_PROFILE_JSON: JSON.stringify(active) };
  await compactGeneralAnswer(env, parseQuery('Serenity 的供應鏈瓶頸與公司價值捕捉有何差別？'), { tenantId: 'synthetic-tenant', chatType: 'user' });
  expect(bodies).toHaveLength(1);
  expect(bodies[0].model).toBe(active.model);
  expect(bodies[0].ii_model_profile).toEqual(active);
  expect(bodies[0].max_tokens).toBe(active.max_output_tokens);
  expect(bodies[0].messages[0].content).not.toContain('runtime_model_profile');
  if (liveFixture) writeFileSync(liveFixture, JSON.stringify(bodies[0]));
});
