import { KIND_DEFAULTS, KIND_LABEL, STATUS_LABEL, validateApiVersion } from './providers';

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
