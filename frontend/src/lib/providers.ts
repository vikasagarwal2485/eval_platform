/** Client-side mirror of the server's provider validation, so mistakes are caught before a request is made. */

export const PROVIDER_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/;
const ENV_NAME_RE = /^[A-Z_][A-Z0-9_]{0,63}$/;
const KEYISH_RE = /^(sk-|sk_|pk-|key-|AIza)/i;

export const KIND_LABEL: Record<string, string> = { openai: 'OpenAI', anthropic: 'Anthropic' };
export const KIND_DEFAULTS: Record<string, { name: string; env: string }> = {
  openai: { name: 'openai', env: 'OPENAI_API_KEY' },
  anthropic: { name: 'anthropic', env: 'ANTHROPIC_API_KEY' },
};

export function validateName(name: string): string | null {
  return PROVIDER_NAME_RE.test(name)
    ? null
    : "Use 1-40 lowercase letters, digits, '-' or '_', starting with a letter or digit.";
}

/** Only a variable *name* is accepted; anything that looks like a key is refused with an explanation. */
export function validateEnvName(value: string): string | null {
  const v = value.trim();
  if (!v) return 'Enter the name of the environment variable that holds the key.';
  if (KEYISH_RE.test(v) || /[\s="']/.test(v) || v.length > 64)
    return 'That looks like an API key. Enter only the name of the environment variable that holds it, and never the key itself.';
  if (!ENV_NAME_RE.test(v)) return 'Use an upper-case variable name such as OPENAI_API_KEY.';
  return null;
}

export function validateBaseUrl(value: string): string | null {
  if (!value.trim()) return null;
  try {
    const u = new URL(value.trim());
    return u.protocol === 'http:' || u.protocol === 'https:'
      ? null
      : 'The base URL must start with http:// or https://.';
  } catch {
    return 'The base URL must start with http:// or https://.';
  }
}

export const STATUS_LABEL: Record<
  string,
  { text: string; kind: 'good' | 'warn' | 'bad' | 'info' }
> = {
  working: { text: 'working', kind: 'good' },
  key_not_set: { text: 'key not set', kind: 'warn' },
  authentication_failed: { text: 'authentication failed', kind: 'bad' },
  rate_limited: { text: 'rate limited', kind: 'warn' },
  unreachable: { text: 'unreachable', kind: 'bad' },
  error: { text: 'error', kind: 'bad' },
};
