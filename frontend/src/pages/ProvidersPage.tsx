import { useProviders } from '../api/hooks';
import ProviderCard from '../components/ProviderCard';
import ProviderForm from '../components/ProviderForm';
import { Empty, ErrorBox, Spinner } from '../components/ui';

export default function ProvidersPage() {
  const { data: providers, isLoading, error } = useProviders();
  return (
    <>
      <div className="page-head">
        <div className="grow">
          <h1>Models</h1>
          <p className="muted">
            Register model providers - enterprise ones (OpenAI, Anthropic, Azure OpenAI) or your
            local Ollama server - and the models available under each, so they can be evaluated
            side by side or used as judges.
          </p>
        </div>
      </div>

      {isLoading && <Spinner label="Loading providers" />}
      {!!error && <ErrorBox error={error} title="Could not load providers." />}

      <section aria-labelledby="providers-list-h">
        <h2 id="providers-list-h" className="sr-only">
          Registered providers
        </h2>

        {providers && providers.length === 0 && (
          <Empty title="No models registered yet">
            <p>
              An enterprise provider is registered by the <strong>name of the environment
              variable</strong> that holds its API key; the key itself is never entered here and
              is never stored. Ollama needs no key at all - just the server address.
            </p>
            <p className="small">
              Set the variable before starting the application, for example{' '}
              <code>export OPENAI_API_KEY=…</code> and then <code>make run</code>.
            </p>
          </Empty>
        )}

        <div className="stack">
          {providers?.map((p) => (
            <ProviderCard key={p.id} provider={p} />
          ))}
          <ProviderForm />
        </div>
      </section>
    </>
  );
}
