import type { Translate } from "@/lib/agent-step-captions";
import { ROUTES } from "@/lib/constants";
import type { DelegationTreeNode } from "@/types/agents";

import type { MapDelegate } from "./agent-map-nodes";

/**
 * The server's delegation tree as map nodes, keyed by path.
 *
 * The server's `key` is unique within one roster, not within the tree - the
 * same delegate pinned under two parents arrives as two nodes wearing one key,
 * and the map's focus and edge-measure registries are keyed maps, so a
 * collision drops one of them silently. Prefixing each key with its parent's
 * makes the path the identity, which is also what focusing "the Researcher
 * under Writer" rather than "the Researcher" means.
 *
 * A `restricted` node carries no name by design - the server refuses to say -
 * so it wears the same "an agent you cannot see" the one-hop map already uses.
 */
export function toMapDelegates(
  nodes: DelegationTreeNode[],
  t: Translate,
  parentKey: string,
): MapDelegate[] {
  return nodes.map((node) => {
    const key = `${parentKey}/${node.key}`;
    return {
      key,
      name: node.name ?? t("delegateUnreachable"),
      kind: node.kind,
      mode: node.mode,
      href: node.status === "ok" && node.agent_id ? ROUTES.AGENT_DETAIL(node.agent_id) : undefined,
      problem: node.status === "ok" ? undefined : node.status,
      stale: node.stale || undefined,
      truncated: node.truncated || undefined,
      children: node.children.length > 0 ? toMapDelegates(node.children, t, key) : undefined,
    };
  });
}
