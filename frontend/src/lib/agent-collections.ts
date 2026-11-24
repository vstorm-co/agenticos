import type { KnowledgeBase } from "@/types/knowledge-base";

/**
 * Whether an agent in `organizationId` can bind this collection, and if not, why.
 *
 * Publish checks each bound collection with `resolve_access`, which refuses a
 * row whose organization is not the caller's. So an agent binds its
 * organization's bases and the personal bases made in it - not an app-scoped
 * base, which belongs to no organization, and not a personal base its owner
 * made in another organization, which `/kb` still lists because the owner may
 * read it there.
 */
export type AgentBinding = "bindable" | "app" | "otherOrganization";

export function agentBinding(collection: KnowledgeBase, organizationId: string): AgentBinding {
  if (collection.scope === "app") return "app";
  return collection.organization_id === organizationId ? "bindable" : "otherOrganization";
}
