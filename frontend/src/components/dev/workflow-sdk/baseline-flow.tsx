"use client";

import { Background, ReactFlow } from "@xyflow/react";
import type { Edge, Node } from "@xyflow/react";
import { useState } from "react";

import "@xyflow/react/dist/style.css";

import { syntheticGraph } from "./perf";

/**
 * The alternative the issue names: React Flow with no SDK, over the same synthetic
 * graph, with default node renderers and no properties form. It is the floor the
 * SDK's per-node cost is measured against, not a proposal for the editor.
 */
export default function BaselineFlow({ count }: { count: number }) {
  const [{ nodes, edges }] = useState(() => {
    const graph = syntheticGraph(count);
    return {
      nodes: graph.nodes.map<Node>((node) => ({
        id: node.id,
        position: node.position,
        data: { label: node.label },
      })),
      edges: graph.edges.map<Edge>((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
      })),
    };
  });
  return (
    <div className="h-full w-full" data-testid="baseline-flow">
      <ReactFlow nodes={nodes} edges={edges} fitView panOnScroll>
        <Background />
      </ReactFlow>
    </div>
  );
}
