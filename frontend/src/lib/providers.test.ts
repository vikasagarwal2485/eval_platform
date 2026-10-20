import {
  KIND_DEFAULTS,
  KIND_LABEL,
  STATUS_LABEL,
  validateApiVersion,
  validateHealthCheckPath,
} from './providers';

describe('azure-openai provider kind (4.1)', () => {
  it('is labelled and has a conventional default env var name', () => {
    expect(KIND_LABEL['azure-openai']).toBe('Azure OpenAI');
    expect(KIND_DEFAULTS['azure-openai']).toEqual({
      name: 'azure-openai',
      env: 'AZURE_OPENAI_API_KEY',
    });
  });

  it('still labels openai and anthropic unchanged', () => {
    expect(KIND_LABEL.openai).toBe('OpenAI');
    expect(KIND_LABEL.anthropic).toBe('Anthropic');
  });

  it('has a status label for the no_deployments Test Connection outcome', () => {
    expect(STATUS_LABEL.no_deployments).toEqual({ text: 'no deployment to test', kind: 'warn' });
  });
});

describe('validateApiVersion', () => {
  it('rejects an empty value', () => {
    expect(validateApiVersion('')).toMatch(/enter the api version/i);
    expect(validateApiVersion('   ')).toMatch(/enter the api version/i);
  });

  it('rejects an overly long value', () => {
    expect(validateApiVersion('x'.repeat(51))).toMatch(/at most 50/);
  });

  it('accepts a normal API version string', () => {
    expect(validateApiVersion('2024-12-01-preview')).toBeNull();
  });
});

describe('custom provider kind (add-custom-model-provider-kind)', () => {
  it('is labelled and has no default key env var (like ollama)', () => {
    expect(KIND_LABEL.custom).toBe('Custom');
    expect(KIND_DEFAULTS.custom.env).toBe('');
  });
});

describe('validateHealthCheckPath', () => {
  it('accepts an empty value - a documented default applies', () => {
    expect(validateHealthCheckPath('')).toBeNull();
    expect(validateHealthCheckPath('   ')).toBeNull();
  });

  it('accepts a path starting with a slash', () => {
    expect(validateHealthCheckPath('/healthz')).toBeNull();
  });

  it('rejects a path with no leading slash', () => {
    expect(validateHealthCheckPath('healthz')).toMatch(/must start with/i);
  });
});
