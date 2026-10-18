// Explicit opt-in local diagnostic. Never qualifies Production publication or delivery.
import { it, expect, vi } from 'vitest';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { ingestV213ActivationBundle } from '../src/v213/activation-v3';
import { asKv, MemoryKv } from './fake-kv';

const input = process.env.INVESTOR_LINE_PROBE_BUNDLE;
const output = process.env.INVESTOR_LINE_PROBE_RECEIPT;
it.skipIf(!input || !output)('diagnoses actual public bundle against unchanged Worker validator without network', async () => {
  const bytes = readFileSync(input!);
  const publicKv = new MemoryKv(), privateKv = new MemoryKv(), securityKv = new MemoryKv();
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('NETWORK_DISABLED'));
  let accepted = false, code = 'UNCLASSIFIED';
  try {
    await ingestV213ActivationBundle(new TextDecoder('utf-8', { fatal: true }).decode(bytes), {
      PUBLIC_CACHE: asKv(publicKv), TENANT_PRIVATE_CACHE: asKv(privateKv), EPHEMERAL_SECURITY_CACHE: asKv(securityKv),
    });
    accepted = true; code = 'LOCAL_VALIDATOR_ACCEPTED_NOT_REMOTE_ACCEPTANCE';
  } catch (error) {
    const message = error instanceof Error ? error.message : '';
    code = /^[A-Z][A-Z0-9_]{1,100}$/.test(message) ? message : 'VALIDATION_FAILED_DETAILS_SUPPRESSED';
  } finally {
    try { expect(fetchSpy).not.toHaveBeenCalled(); } finally { fetchSpy.mockRestore(); }
    writeFileSync(output!, JSON.stringify({ scope: 'ACTUAL_BUNDLE_LOCAL_WORKER_VALIDATION_ONLY',
      accepted, code, inputSha256: createHash('sha256').update(bytes).digest('hex'),
      evaluatedUtc: new Date().toISOString(), productionWrites: 0, lineSends: 0, LINE_LIVE: false,
    }, null, 2), { flag: 'wx' });
  }
  // The diagnostic itself passes when rejection was safely recorded; consult accepted, not Vitest status.
  expect(createHash('sha256').update(readFileSync(input!)).digest('hex'))
    .toBe(createHash('sha256').update(bytes).digest('hex'));
});
