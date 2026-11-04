import { useCallback, useMemo } from "react";

import { suggestedBindingsFor } from "@/components/workflows/apps";
import { nodeOutputBinding } from "@/components/workflows/property-panel/bindings";
import {
  carryBranchKey,
  fittingMergeConfigs,
} from "@/components/workflows/property-panel/merge-config";
import { availableSourceNodes } from "@/components/workflows/validation";
import type {
  Binding,
  NodeDefinition,
  NodePosition,
  WorkflowEdge,
  WorkflowGraph,
} from "@/lib/workflows/types";
import { useChannelBots, usePermissions } from "@/hooks";
import type { ChannelBot } from "@/types/channels";
import { Perm } from "@/types/permissions";
import { type NodeInsertion, useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { buildCatalogMap, definitionsByNode } from "./graph-adapter";
import { type InsertFrom, planInsertion } from "./insertion";

/** Where a step is being added from: after a node's output, or where it was dropped. */
export interface InsertOptions {
  from?: InsertFrom;
  dropAt?: NodePosition;
  between?: WorkflowEdge;
  /** The step's config, when it is added already set up - an app's action, an `mcp.call` for a tool. */
  config?: Record<string, unknown>;
}

/** Add a step the way {@link planInsertion} places and wires it. */
export type InsertNode = (definition: NodeDefinition, options?: InsertOptions) => void;

/** The graph as it will be once `plan` is applied: the step, its wire, and any split. */
function graphAfter(graph: WorkflowGraph, plan: NodeInsertion): WorkflowGraph {
  const edges = graph.edges.filter((edge) => edge.id !== plan.split?.edgeId);
  return {
    ...graph,
    entry_node_id: plan.becomesEntry ? plan.node.id : graph.entry_node_id,
    nodes: [...graph.nodes, plan.node],
    edges: [
      ...edges,
      ...(plan.split?.tail == null ? [] : [plan.split.tail]),
      ...(plan.edge === null ? [] : [plan.edge]),
    ],
  };
}

/**
 * What a merge's config becomes when a step is put into one of its branches' wires: the
 * branch keeps the name its author gave it on the new step's wire, and the mode and
 * names are fitted as for any new wire. Empty when the step is not put into a merge's wire.
 */
function mergeConfigsAfter(
  graph: WorkflowGraph,
  after: WorkflowGraph,
  plan: NodeInsertion,
  catalogMap: Map<string, NodeDefinition>,
): Record<string, Record<string, unknown>> {
  const tail = plan.split?.tail;
  const cut = graph.edges.find((edge) => edge.id === plan.split?.edgeId);
  const merge = tail == null ? undefined : after.nodes.find((n) => n.id === tail.target_node_id);
  if (tail == null || cut === undefined || merge === undefined) return {};
  const carried = carryBranchKey(
    merge.config,
    { nodeId: cut.source_node_id, port: cut.source_port },
    { nodeId: tail.source_node_id, port: tail.source_port },
  );
  const carriedGraph = {
    ...after,
    nodes: after.nodes.map((n) => (n === merge ? { ...n, config: carried } : n)),
  };
  const fitted = fittingMergeConfigs(carriedGraph, definitionsByNode(carriedGraph, catalogMap), [
    merge.id,
  ]);
  return carried === merge.config ? fitted : { [merge.id]: carried, ...fitted };
}

/**
 * The bindings an app's action starts with: the mail the workflow's trigger delivered,
 * read into the arguments that answer it (`thread_id`, `in_reply_to`, ...). Empty unless
 * the step is a known mail tool and that app's trigger sits upstream of it as planned,
 * so every binding is one the validator accepts.
 */
function appBindings(after: WorkflowGraph, plan: NodeInsertion, upstream: Set<string>): Binding[] {
  // An app's action is an MCP call; a `tool` in any other step's config is not one.
  const tool = plan.node.definition_id === "mcp.call" ? plan.node.config.tool : undefined;
  const suggestion = typeof tool === "string" ? suggestedBindingsFor(tool) : null;
  if (suggestion === null) return [];
  const trigger = after.nodes.find(
    (node) => upstream.has(node.id) && suggestion.triggers.includes(node.definition_id),
  );
  if (trigger === undefined) return [];
  return Object.entries(suggestion.fields).map(([argument, field]) =>
    nodeOutputBinding(plan.node.id, `arguments/${argument}`, trigger.id, "out", [field]),
  );
}

const SEND_STEP = /^(slack|mattermost|telegram)\.message\.send$/;

/**
 * What a Send a message step starts with after a Channel message trigger: that trigger's
 * bot, and the channel and thread the message came from. Nothing unless the bots are
 * known (`null` while loading, on an error, or without `channels:manage`) and the bot is
 * on the step's own platform - a suggestion is never a guess.
 */
function channelReply(
  after: WorkflowGraph,
  plan: NodeInsertion,
  upstream: Set<string>,
  bots: readonly ChannelBot[] | null,
): { config: Record<string, unknown>; bindings: Binding[] } {
  const none = { config: {}, bindings: [] };
  const platform = SEND_STEP.exec(plan.node.definition_id)?.[1];
  if (platform === undefined || bots === null) return none;
  const trigger = after.nodes.find(
    (node) => upstream.has(node.id) && node.definition_id === "trigger.channel_message",
  );
  const botId = trigger?.config.bot_id;
  if (trigger === undefined || typeof botId !== "string") return none;
  if (bots.find((bot) => bot.id === botId)?.platform !== platform) return none;
  return {
    config: { bot_id: botId },
    bindings: ["channel_id", "thread_id"].map((field) =>
      nodeOutputBinding(plan.node.id, field, trigger.id, "out", [field]),
    ),
  };
}

/**
 * Add a step to the working graph, placed and wired by {@link planInsertion},
 * and open its settings when it has any.
 *
 * Reads the graph, the scope and the selection at the moment of the add rather
 * than subscribing to them, so the palette and every node's "+" can hold one
 * stable callback without re-rendering on each edit.
 */
export function useInsertNode(catalog: NodeDefinition[], readOnly = false): InsertNode {
  const insertNode = useWorkflowEditorStore((state) => state.insertNode);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const catalogMap = useMemo(() => buildCatalogMap(catalog), [catalog]);
  // A read-only canvas adds nothing, so it does not fetch the bots either.
  const mayManage = usePermissions().can(Perm.channelsManage) && !readOnly;
  const { bots, isLoading, error } = useChannelBots(mayManage);
  const knownBots = mayManage && !isLoading && error == null ? bots : null;
  return useCallback(
    (definition, { config, ...options } = {}) => {
      const { graph, scopePath, selection } = useWorkflowEditorStore.getState();
      if (graph === null) return;
      const plan = planInsertion({
        graph,
        definitions: definitionsByNode(graph, catalogMap),
        scopePath,
        selectedIds: selection.nodeIds,
        definition,
        ...options,
      });
      const configured = config === undefined ? plan : { ...plan, node: { ...plan.node, config } };
      const after = graphAfter(graph, configured);
      const upstream = availableSourceNodes(
        after,
        { items: catalog, total: catalog.length },
        configured.node.id,
      );
      const reply = channelReply(after, configured, upstream, knownBots);
      // One insertion, so one undo takes the step and its suggested bindings back together.
      const planned = {
        ...configured,
        node: { ...configured.node, config: { ...reply.config, ...configured.node.config } },
        bindings: [
          ...configured.bindings,
          ...appBindings(after, configured, upstream),
          ...reply.bindings,
        ],
        configs: mergeConfigsAfter(graph, after, configured, catalogMap),
      };
      insertNode(planned);
      // A step with something to set opens its settings at once: it is added to
      // be configured, and a builder should not have to find it and click it.
      if (definition.config_schema !== null || definition.input_schema !== null) {
        editNode(planned.node.id);
      }
    },
    [insertNode, editNode, catalog, catalogMap, knownBots],
  );
}
