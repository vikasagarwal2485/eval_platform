import { useState } from 'react';
import { ApiError } from '../api/client';
import { useTrace } from '../api/hooks';
import { fmtMs } from '../lib/format';
import { parseTrace, type SpanNode } from '../lib/trace';
import { Spinner } from './ui';

/** Readable reason text for the three failure codes `GET /api/traces/{trace_id}` can return
 * (`trace-observability`: graceful degradation - this is the only thing that's ever affected). */
function unavailableReason(error: unknown): string {
  const code = error instanceof ApiError ? error.code : undefined;
  if (code === 'tempo_unreachable') return 'Tempo is unreachable right now.';
  if (code === 'tempo_not_configured') return 'Tracing is not configured on this backend.';
  if (code === 'trace_not_found') return 'This trace is no longer available (it may have expired).';
  return 'Trace unavailable.';
}

function SpanRow({ node, depth }: { node: SpanNode; depth: number }) {
  const attrs = Object.entries(node.attributes);
  return (
    <div style={{ marginLeft: depth * 16, marginTop: depth === 0 ? 0 : 6 }}>
      <div className="row">
        <code>{node.name}</code>
        {node.kind && (
          <span className="muted small">{node.kind.replace('SPAN_KIND_', '').toLowerCase()}</span>
        )}
        <span className="muted small">{fmtMs(node.durationMs)}</span>
        {node.statusCode === 'STATUS_CODE_ERROR' && <span className="badge bad">error</span>}
      </div>
      {attrs.length > 0 && (
        <div className="small muted" style={{ marginLeft: 4 }}>
          {attrs.map(([k, v]) => (
            <span key={k} style={{ marginRight: 10 }}>
              {k}={String(v)}
            </span>
          ))}
        </div>
      )}
      {node.children.map((c) => (
        <SpanRow key={c.spanId} node={c} depth={depth + 1} />
      ))}
    </div>
  );
}

/** The structured span tree for one trace, fetched live from Tempo by id (`trace-observability`). Shared
 * between the benchmark results drill-down and the agent turn drill-down. A collapsed disclosure that fetches
 * lazily, only once opened - rendering a list of results/turns never fetches every one's trace up front, and a
 * missing/unresolvable trace never hides anything else in the drill-down around it (graceful degradation). */
export default function SpanTree({ traceId }: { traceId: string | null }) {
  const [open, setOpen] = useState(false);
  const { data, error, isLoading } = useTrace(traceId, open);

  return (
    <details
      className="small"
      style={{ marginTop: 8 }}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary>Trace</summary>
      {!traceId && <div className="muted">No trace recorded for this result.</div>}
      {traceId && isLoading && <Spinner label="Loading trace" />}
      {traceId && error && <div className="muted">{unavailableReason(error)}</div>}
      {traceId && data && (
        <div style={{ marginTop: 4 }}>
          {(() => {
            const roots = parseTrace(data);
            return roots.length === 0 ? (
              <div className="muted">Trace is empty.</div>
            ) : (
              roots.map((r) => <SpanRow key={r.spanId} node={r} depth={0} />)
            );
          })()}
        </div>
      )}
    </details>
  );
}
