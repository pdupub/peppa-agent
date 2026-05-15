import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, Database, GitBranch, RefreshCw, Tag } from 'lucide-react';
import { fetchMemoryGraph } from './api';
import type {
  MemoryGraphEdge,
  MemoryGraphNode,
  MemoryGraphResponse,
  MemoryGraphTag
} from './types';
import type { ElementDatum, Graph as G6Graph, GraphData, IElementEvent } from '@antv/g6';

type Selection =
  | { kind: 'node'; value: MemoryGraphNode }
  | { kind: 'edge'; value: MemoryGraphEdge };

const NODE_COLORS: Record<string, { fill: string; stroke: string }> = {
  person: { fill: '#23695f', stroke: '#88e2d1' },
  project: { fill: '#5c4d8f', stroke: '#b4a6ff' },
  preference: { fill: '#7a4c56', stroke: '#f2a5b7' },
  event: { fill: '#725b28', stroke: '#ffd06a' },
  concept: { fill: '#2e5f91', stroke: '#93cbff' },
  decision: { fill: '#596236', stroke: '#d7ea83' },
  rule: { fill: '#735438', stroke: '#f4ba7a' },
  artifact: { fill: '#4d6174', stroke: '#b8d6ef' }
};

const DEFAULT_NODE_COLOR = { fill: '#394150', stroke: '#aeb8c6' };

export function MemoryGraphPage({ onBack }: { onBack: () => void }) {
  const [memoryGraph, setMemoryGraph] = useState<MemoryGraphResponse | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<G6Graph | null>(null);

  useEffect(() => {
    void loadGraph();
  }, []);

  useEffect(() => {
    if (!memoryGraph) {
      return;
    }
    if (selection?.kind === 'node') {
      const node = memoryGraph.nodes.find((item) => item.id === selection.value.id);
      if (node) {
        if (node !== selection.value) {
          setSelection({ kind: 'node', value: node });
        }
        return;
      }
    }
    if (selection?.kind === 'edge') {
      const edge = memoryGraph.edges.find((item) => item.id === selection.value.id);
      if (edge) {
        if (edge !== selection.value) {
          setSelection({ kind: 'edge', value: edge });
        }
        return;
      }
    }
    setSelection(memoryGraph.nodes[0] ? { kind: 'node', value: memoryGraph.nodes[0] } : null);
  }, [memoryGraph, selection]);

  const graphData = useMemo(() => {
    if (!memoryGraph) {
      return null;
    }
    return toG6Data(memoryGraph);
  }, [memoryGraph]);

  useEffect(() => {
    const container = containerRef.current;
    const data = graphData;
    if (!container || !data || data.nodes?.length === 0) {
      return;
    }
    const resolvedData: GraphData = data;

    let disposed = false;
    let observer: ResizeObserver | null = null;

    async function renderGraph() {
      const { Graph } = await import('@antv/g6');
      if (disposed || !container) {
        return;
      }

      graphRef.current?.destroy();
      const graph = new Graph({
        container,
        width: container.clientWidth,
        height: container.clientHeight,
        data: resolvedData,
        animation: false,
        layout: {
          type: 'force',
          preventOverlap: true,
          linkDistance: 150,
          nodeStrength: -360,
          edgeStrength: 0.18,
          iterations: 260,
          animation: false
        },
        node: {
          type: 'circle',
          style: (datum) => nodeStyle(datum.data)
        },
        edge: {
          type: 'quadratic',
          style: (datum) => edgeStyle(datum.data)
        },
        behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
        transforms: [{ type: 'process-parallel-edges', mode: 'bundle', distance: 24 }],
        plugins: [
          { type: 'grid-line', size: 36, stroke: '#202633', lineWidth: 1 },
          {
            type: 'tooltip',
            trigger: 'hover',
            enable: (_event: IElementEvent, items: ElementDatum[]) =>
              Boolean(extractMemoryPayload(items[0])),
            getContent: async (_event: IElementEvent, items: ElementDatum[]) =>
              buildTooltip(extractMemoryPayload(items[0])),
            onOpenChange: () => undefined
          }
        ]
      });

      graph.on<IElementEvent>('node:click', (event) => {
        const node = memoryGraph?.nodes.find((item) => item.id === getEventElementId(event));
        if (node) {
          setSelection({ kind: 'node', value: node });
        }
      });
      graph.on<IElementEvent>('edge:click', (event) => {
        const edge = memoryGraph?.edges.find((item) => item.id === getEventElementId(event));
        if (edge) {
          setSelection({ kind: 'edge', value: edge });
        }
      });

      graphRef.current = graph;
      await graph.render();
      if (disposed) {
        graph.destroy();
        return;
      }
      await graph.fitView({ when: 'overflow', direction: 'both' });
      if (graph.getZoom() > 1) {
        await graph.zoomTo(1);
      }
      await graph.fitCenter();

      observer = new ResizeObserver(() => {
        graph.resize(container.clientWidth, container.clientHeight);
      });
      observer.observe(container);
    }

    void renderGraph();

    return () => {
      disposed = true;
      observer?.disconnect();
      graphRef.current?.destroy();
      graphRef.current = null;
    };
  }, [graphData, memoryGraph]);

  async function loadGraph() {
    setIsLoading(true);
    setError(null);
    try {
      const nextGraph = await fetchMemoryGraph();
      setMemoryGraph(nextGraph);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load memory graph.');
    } finally {
      setIsLoading(false);
    }
  }

  const nodeTypeCounts = useMemo(() => countNodeTypes(memoryGraph?.nodes ?? []), [memoryGraph]);
  const topTags = useMemo(() => collectTopTags(memoryGraph), [memoryGraph]);

  return (
    <section className="memory-page" aria-label="Memory graph">
      <div className="memory-page-header">
        <div>
          <h2>Memory Graph</h2>
          <p>Current nodes, edges, and tag links stored in SQLite.</p>
        </div>
        <div className="memory-page-actions">
          <button className="icon-button" type="button" onClick={onBack}>
            <ArrowLeft size={16} />
            <span>Console</span>
          </button>
          <button className="icon-button" type="button" onClick={() => void loadGraph()}>
            <RefreshCw className={isLoading ? 'spin' : ''} size={16} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {error && <div className="memory-error">{error}</div>}

      <div className="memory-stats">
        <MemoryStat icon={<Database size={16} />} label="Nodes" value={memoryGraph?.stats.nodes ?? 0} />
        <MemoryStat icon={<GitBranch size={16} />} label="Edges" value={memoryGraph?.stats.edges ?? 0} />
        <MemoryStat icon={<Tag size={16} />} label="Tags" value={memoryGraph?.stats.tags ?? 0} />
        <MemoryStat
          icon={<RefreshCw size={16} />}
          label="Extractions"
          value={memoryGraph?.stats.extraction_runs ?? 0}
        />
      </div>

      <div className="memory-layout">
        <section className="panel memory-graph-panel">
          <div ref={containerRef} className="memory-graph-canvas" />
          {!isLoading && memoryGraph?.nodes.length === 0 && (
            <div className="memory-empty-state">
              No memory graph data yet. Extract memory from selected history traces first.
            </div>
          )}
          {isLoading && <div className="memory-empty-state">Loading memory graph...</div>}
        </section>

        <aside className="panel memory-inspector">
          <section>
            <h3>Node Types</h3>
            <div className="memory-type-list">
              {nodeTypeCounts.map(([type, count]) => (
                <div className="memory-type-row" key={type}>
                  <span
                    className="memory-type-dot"
                    style={{ background: nodeColor(type).stroke }}
                    aria-hidden="true"
                  />
                  <span>{type}</span>
                  <strong>{count}</strong>
                </div>
              ))}
              {nodeTypeCounts.length === 0 && <p className="memory-muted">No node types.</p>}
            </div>
          </section>

          <section>
            <h3>Top Tags</h3>
            <div className="memory-tag-list">
              {topTags.map((tag) => (
                <span className="memory-tag" key={tag.name}>
                  {tag.name}
                </span>
              ))}
              {topTags.length === 0 && <p className="memory-muted">No tags.</p>}
            </div>
          </section>

          <section>
            <h3>Selection</h3>
            {selection ? (
              <MemorySelection selection={selection} />
            ) : (
              <p className="memory-muted">Click a node or edge to inspect it.</p>
            )}
          </section>
        </aside>
      </div>
    </section>
  );
}

function MemoryStat({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="memory-stat">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function MemorySelection({ selection }: { selection: Selection }) {
  if (selection.kind === 'edge') {
    const edge = selection.value;
    return (
      <div className="memory-selection">
        <div className="memory-selection-kicker">edge / {edge.relation_type}</div>
        <h4>
          {edge.source_title} {'->'} {edge.target_title}
        </h4>
        <p>{edge.summary || 'No summary.'}</p>
        <TagCloud tags={edge.tags} />
        <small>{edge.source_trace_ids.length} source trace(s)</small>
      </div>
    );
  }

  const node = selection.value;
  return (
    <div className="memory-selection">
      <div className="memory-selection-kicker">node / {node.type}</div>
      <h4>{node.title}</h4>
      <p>{node.summary || 'No summary.'}</p>
      <TagCloud tags={node.tags} />
      <small>{node.source_trace_ids.length} source trace(s)</small>
    </div>
  );
}

function TagCloud({ tags }: { tags: MemoryGraphTag[] }) {
  if (tags.length === 0) {
    return <p className="memory-muted">No linked tags.</p>;
  }

  return (
    <div className="memory-tag-list">
      {tags.map((tag) => (
        <span className="memory-tag" key={tag.id}>
          {tag.name}
        </span>
      ))}
    </div>
  );
}

function toG6Data(memoryGraph: MemoryGraphResponse): GraphData {
  return {
    nodes: memoryGraph.nodes.map((node) => ({
      id: node.id,
      data: node
    })),
    edges: memoryGraph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_node_id,
      target: edge.target_node_id,
      data: edge
    }))
  };
}

function nodeStyle(payload: Record<string, unknown> | undefined) {
  const node = isMemoryGraphNode(payload) ? payload : null;
  const color = nodeColor(node?.type ?? '');
  const mentionCount = node?.mention_count ?? 1;

  return {
    size: Math.min(54, 30 + mentionCount * 3),
    fill: color.fill,
    stroke: color.stroke,
    lineWidth: 2,
    labelText: node?.title ?? '',
    labelFill: '#e7eaf0',
    labelFontSize: 12,
    labelFontWeight: 650,
    labelPlacement: 'bottom' as const,
    labelMaxWidth: 160,
    labelBackground: true,
    labelBackgroundFill: '#10141bdd',
    labelBackgroundStroke: '#2b3340',
    labelBackgroundRadius: 4,
    labelPadding: [3, 5]
  };
}

function edgeStyle(payload: Record<string, unknown> | undefined) {
  const edge = isMemoryGraphEdge(payload) ? payload : null;
  const mentionCount = edge?.mention_count ?? 1;

  return {
    stroke: '#69768a',
    lineWidth: Math.min(3.5, 1.2 + mentionCount * 0.35),
    opacity: 0.82,
    endArrow: true,
    labelText: edge?.relation_type ?? '',
    labelFill: '#c5cfdd',
    labelFontSize: 10,
    labelBackground: true,
    labelBackgroundFill: '#0f1115dd',
    labelBackgroundStroke: '#2b3340',
    labelBackgroundRadius: 4,
    labelPadding: [2, 4]
  };
}

function nodeColor(type: string) {
  return NODE_COLORS[type] ?? DEFAULT_NODE_COLOR;
}

function buildTooltip(payload: MemoryGraphNode | MemoryGraphEdge | null): HTMLElement | string {
  if (!payload) {
    return '';
  }

  const root = document.createElement('div');
  root.className = 'memory-tooltip-card';

  const kicker = document.createElement('div');
  kicker.className = 'memory-tooltip-kicker';
  kicker.textContent = isMemoryGraphNode(payload) ? `node / ${payload.type}` : `edge / ${payload.relation_type}`;
  root.appendChild(kicker);

  const title = document.createElement('strong');
  title.textContent = isMemoryGraphNode(payload)
    ? payload.title
    : `${payload.source_title} -> ${payload.target_title}`;
  root.appendChild(title);

  const summary = document.createElement('p');
  summary.textContent = payload.summary || 'No summary.';
  root.appendChild(summary);

  if (payload.tags.length > 0) {
    const tagList = document.createElement('div');
    tagList.className = 'memory-tooltip-tags';
    payload.tags.slice(0, 12).forEach((tag) => {
      const tagItem = document.createElement('span');
      tagItem.textContent = tag.name;
      tagList.appendChild(tagItem);
    });
    root.appendChild(tagList);
  }

  return root;
}

function extractMemoryPayload(item: ElementDatum | undefined): MemoryGraphNode | MemoryGraphEdge | null {
  const record = asRecord(item);
  const nestedData = asRecord(record?.data);
  if (isMemoryGraphNode(nestedData) || isMemoryGraphEdge(nestedData)) {
    return nestedData;
  }
  if (isMemoryGraphNode(record) || isMemoryGraphEdge(record)) {
    return record;
  }
  return null;
}

function getEventElementId(event: IElementEvent): string | null {
  const target = event.target as unknown as {
    id?: unknown;
    attributes?: { id?: unknown };
    getAttribute?: (name: string) => unknown;
  };
  const id = target.id ?? target.attributes?.id ?? target.getAttribute?.('id');
  return typeof id === 'string' ? id : null;
}

function countNodeTypes(nodes: MemoryGraphNode[]) {
  const counts = new Map<string, number>();
  nodes.forEach((node) => counts.set(node.type, (counts.get(node.type) ?? 0) + 1));
  return [...counts.entries()].sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));
}

function collectTopTags(memoryGraph: MemoryGraphResponse | null): Array<{ name: string; count: number }> {
  if (!memoryGraph) {
    return [];
  }

  const counts = new Map<string, number>();
  [...memoryGraph.nodes, ...memoryGraph.edges].forEach((item) => {
    item.tags.forEach((tag) => counts.set(tag.name, (counts.get(tag.name) ?? 0) + tag.mention_count));
  });
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name))
    .slice(0, 24);
}

function isMemoryGraphNode(value: unknown): value is MemoryGraphNode {
  const record = asRecord(value);
  return Boolean(record && typeof record.id === 'string' && typeof record.title === 'string');
}

function isMemoryGraphEdge(value: unknown): value is MemoryGraphEdge {
  const record = asRecord(value);
  return Boolean(
    record &&
      typeof record.id === 'string' &&
      typeof record.source_node_id === 'string' &&
      typeof record.target_node_id === 'string'
  );
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}
