import type { TempoAttributeValue, TempoTrace } from '../api/types';

export interface SpanNode {
  spanId: string;
  name: string;
  kind: string | null;
  durationMs: number;
  attributes: Record<string, string | number | boolean>;
  statusCode: string | null;
  children: SpanNode[];
}

function attrValue(v: TempoAttributeValue): string | number | boolean {
  if (v.stringValue !== undefined) return v.stringValue;
  if (v.intValue !== undefined) return typeof v.intValue === 'string' ? Number(v.intValue) : v.intValue;
  if (v.doubleValue !== undefined) return v.doubleValue;
  if (v.boolValue !== undefined) return v.boolValue;
  return '';
}

/** Tempo's trace JSON -> a forest of span trees, ordered by start time, each node's own duration in ms.
 * Usually one root (the request's own top-level span); a judge span continuing an earlier phase's trace by id
 * alone (no real parent span id survives that - see backend `app/core/tracing.py`) becomes its own root too,
 * rather than being forced under a parent it was never really nested in. */
export function parseTrace(trace: TempoTrace): SpanNode[] {
  type Raw = SpanNode & { parentSpanId: string | null; startNs: bigint };
  const flat: Raw[] = [];
  for (const batch of trace.batches ?? []) {
    for (const scopeSpans of batch.scopeSpans ?? []) {
      for (const s of scopeSpans.spans ?? []) {
        const startNs = BigInt(s.startTimeUnixNano);
        const endNs = BigInt(s.endTimeUnixNano);
        const attributes: Record<string, string | number | boolean> = {};
        for (const a of s.attributes ?? []) attributes[a.key] = attrValue(a.value);
        flat.push({
          spanId: s.spanId,
          parentSpanId: s.parentSpanId ?? null,
          name: s.name,
          kind: s.kind ?? null,
          startNs,
          durationMs: Number(endNs - startNs) / 1e6,
          attributes,
          statusCode: s.status?.code ?? null,
          children: [],
        });
      }
    }
  }
  const byId = new Map(flat.map((s) => [s.spanId, s]));
  const roots: Raw[] = [];
  for (const s of flat) {
    const parent = s.parentSpanId ? byId.get(s.parentSpanId) : undefined;
    (parent ? parent.children : roots).push(s);
  }
  const sortByStart = (nodes: Raw[]) => {
    nodes.sort((a, b) => (a.startNs < b.startNs ? -1 : a.startNs > b.startNs ? 1 : 0));
    nodes.forEach((n) => sortByStart(n.children as Raw[]));
  };
  sortByStart(roots);
  return roots;
}
