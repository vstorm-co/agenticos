import type { CapabilityGuide } from "@/hooks/use-capability-guide";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";
import type { CapabilityCatalogEntry, McpServerRef } from "@/types/agents";
import type { McpCatalogEntry } from "@/types/mcp";

/** How many of an agent's capabilities the panel names - the audit's 2-3. */
export const CAPABILITY_PANEL_LIMIT = 3;

/** One capability, in the reader's words, with something to try. */
export interface AgentCapabilityRow {
  id: string;
  name: string;
  does: string;
  /** The guide's first example prompt, or null where it has none to offer. */
  example: string | null;
}

/**
 * The capabilities an agent's empty chat can say it has, in spec order.
 *
 * Read off the published version's enabled bindings, joined to the catalog and
 * the plain-language guide - never hand-written per agent. A published id the
 * catalog no longer names is a stale binding, not a capability to describe, and
 * a capability with no tools (a guardrail, thinking, compaction) is not
 * something a person asks the agent to do, so both are skipped rather than
 * shown as a bare id or a line that promises nothing.
 */
export function capabilityRows(
  publishedIds: readonly string[] | null | undefined,
  catalog: readonly CapabilityCatalogEntry[],
  guide: (id: string) => CapabilityGuide | undefined,
  limit: number = CAPABILITY_PANEL_LIMIT,
): AgentCapabilityRow[] {
  const rows: AgentCapabilityRow[] = [];
  for (const id of publishedIds ?? []) {
    if (rows.length >= limit) break;
    const entry = catalog.find((candidate) => candidate.id === id);
    if (!entry || entry.tools.length === 0) continue;
    const plain = guide(id);
    rows.push({
      id,
      name: plain?.name ?? entry.name,
      does: plain?.does ?? entry.description,
      example: plain?.examples[0] ?? null,
    });
  }
  return rows;
}

/**
 * The connected apps an agent's published version is bound to, by name.
 *
 * The organization's connections resolve by id; each person's own by catalog
 * key, falling back to the key itself where the catalog no longer names it.
 * The platform's own server is not a connected app, and a connection the
 * caller cannot see is skipped rather than shown as an id - the panel names
 * apps, it does not leak references.
 */
export function connectedAppNames(
  servers: readonly McpServerRef[] | null | undefined,
  connections: readonly McpConnectionRecord[],
  catalog: readonly McpCatalogEntry[],
): string[] {
  const names: string[] = [];
  for (const ref of servers ?? []) {
    if (ref.account === "platform") continue;
    const name =
      ref.account === "organization"
        ? connections.find((connection) => connection.id === ref.connection_id)?.name
        : (catalog.find((server) => server.key === ref.catalog_key)?.name ?? ref.catalog_key);
    if (name !== undefined && !names.includes(name)) names.push(name);
  }
  return names;
}
