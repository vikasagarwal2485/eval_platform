/** The task types a declared model can be keyed by - a closed, well-known set rather than free text, so the
 * field's purpose (which task this row's model serves) is obvious at a glance instead of relying on a
 * placeholder that disappears the moment you start typing. The backend itself doesn't restrict these keys to
 * this list (any string works - `agent-registry`'s "for example `reasoning`, `generation`, or `default`"), but
 * these four cover every agent shape this platform ships or documents. */
export const TASK_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'reasoning', label: 'Reasoning' },
  { value: 'generation', label: 'Generation' },
  { value: 'classification', label: 'Classification' },
  { value: 'default', label: 'Default (single, undifferentiated task)' },
];

export const DECLARED_MODELS_HINT =
  'The task each row’s model serves. Use "Default" for an agent with one undifferentiated model (e.g. the reference chatbot); use "Reasoning"/"Generation" (one row each) for a multi-step agent that calls different models for different steps, like the reference reasoning agent.';
