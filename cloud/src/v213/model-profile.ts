export interface ModelProfile {
  schema_version: 1;
  model: string;
  enable_thinking: boolean;
  reasoning_effort: string;
  max_output_tokens: number;
  smoke_output_tokens: number;
  timeout_ms: number;
}
export type ModelProfileEnv = { V213_MODEL_PROFILE_JSON?: string };
const fields = ['schema_version', 'model', 'enable_thinking', 'reasoning_effort',
  'max_output_tokens', 'smoke_output_tokens', 'timeout_ms'] as const;

export function validateModelProfile(raw: unknown): ModelProfile {
  const fail = (): never => { throw new Error('MODEL_PROFILE_INVALID'); };
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return fail();
  const p = raw as Record<string, unknown>;
  if (Object.keys(p).length !== fields.length || fields.some(k => !Object.prototype.hasOwnProperty.call(p, k))) return fail();
  if (p.schema_version !== 1 || typeof p.model !== 'string' || p.model !== p.model.trim() || !/^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,199}$/.test(p.model)) return fail();
  if (typeof p.enable_thinking !== 'boolean' || typeof p.reasoning_effort !== 'string' ||
      !['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'].includes(p.reasoning_effort) ||
      p.enable_thinking === (p.reasoning_effort === 'none')) return fail();
  for (const [key, low, high] of [['max_output_tokens', 1, 8192], ['smoke_output_tokens', 1, 8192], ['timeout_ms', 1000, 20000]] as const) {
    if (!Number.isInteger(p[key]) || (p[key] as number) < low || (p[key] as number) > high) return fail();
  }
  if ((p.smoke_output_tokens as number) > (p.max_output_tokens as number)) return fail();
  return Object.fromEntries(fields.map(k => [k, p[k]])) as unknown as ModelProfile;
}

export function configuredModelProfile(env: ModelProfileEnv): ModelProfile | undefined {
  if (env.V213_MODEL_PROFILE_JSON === undefined) return undefined; // explicit legacy compatibility
  const raw = env.V213_MODEL_PROFILE_JSON;
  try {
    if (raw.length > 4096) throw new Error();
    const value = validateModelProfile(JSON.parse(raw));
    const numericTokens = raw.match(/:\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?=\s*[,}])/g) ?? [];
    if (numericTokens.some(token => /[.eE]/.test(token))) throw new Error();
    // Flat schema; count lexical keys too, so JSON.parse cannot hide duplicates.
    if ((raw.match(/"(?:[^"\\]|\\.)*"\s*:/g) ?? []).length !== fields.length) throw new Error();
    return value;
  } catch { throw new Error('MODEL_PROFILE_INVALID'); }
}

export async function modelProfileSha256(profile: ModelProfile): Promise<string> {
  const value = validateModelProfile(profile);
  const bytes = new TextEncoder().encode(JSON.stringify(fields.map(k => value[k])));
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b => b.toString(16).padStart(2, '0')).join('');
}
