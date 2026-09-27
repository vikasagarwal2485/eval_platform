import type { ModelSource, ProviderKind } from '../api/types';
import { KIND_LABEL } from '../lib/providers';

/** A model's name with a cloud badge and provider when it is an enterprise model; plain text for local models. */
export default function ModelChip({
  name,
  source,
  provider,
  providerKind,
}: {
  name: string;
  source?: ModelSource | null;
  provider?: string | null;
  providerKind?: ProviderKind | null;
}) {
  if (source !== 'cloud') return <>{name}</>;
  return (
    <>
      {name}{' '}
      <span
        className="badge info"
        title={provider && providerKind ? `${provider} (${KIND_LABEL[providerKind]})` : undefined}
      >
        cloud{provider ? ` · ${provider}` : ''}
      </span>
    </>
  );
}
