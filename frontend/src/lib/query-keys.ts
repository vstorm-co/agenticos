/**
 * Centralized, typed React Query key factory.
 *
 * One source of truth for cache keys so queries dedupe and mutations can
 * invalidate precisely (e.g. `queryClient.invalidateQueries({ queryKey: qk.runs.all() })`).
 * Keep keys hierarchical: broader prefixes invalidate everything beneath them.
 */
import type { SharingResourceType } from "@/types/sharing";

export const qk = {
  auth: {
    me: () => ["auth", "me"] as const,
  },
  health: () => ["health"] as const,
  organizations: {
    all: () => ["organizations"] as const,
    list: () => ["organizations", "list"] as const,
    members: (orgId: string) => ["organizations", orgId, "members"] as const,
    permissions: (orgId: string) => ["organizations", orgId, "permissions"] as const,
    roleCatalog: () => ["organizations", "role-catalog"] as const,
    audit: (orgId: string) => ["organizations", orgId, "audit"] as const,
  },
  agents: {
    all: () => ["agents"] as const,
    /** `includeArchived` is part of the key: the two lists are different rows. */
    list: (includeArchived = false) => ["agents", "list", includeArchived] as const,
    detail: (id: string) => ["agents", id] as const,
    versions: (id: string) => ["agents", id, "versions"] as const,
    version: (id: string, versionId: string) => ["agents", id, "versions", versionId] as const,
    capabilityCatalog: () => ["agents", "capability-catalog"] as const,
  },
  channelBots: {
    list: () => ["channel-bots"] as const,
  },
  catalog: {
    icons: () => ["catalog", "icons"] as const,
  },
  environments: {
    all: () => ["environments"] as const,
    list: (agentId: string) => ["environments", agentId] as const,
  },
  exposures: {
    all: () => ["exposures"] as const,
    list: (agentId: string) => ["exposures", agentId] as const,
    targets: (agentId: string) => ["exposures", agentId, "targets"] as const,
  },
  embeds: {
    all: () => ["embeds"] as const,
    list: (agentId: string) => ["embeds", agentId] as const,
  },
  providers: {
    all: () => ["providers"] as const,
    // What the platform can talk to, which changes on redeploy and not on a
    // mutation. Under `providers` all the same: the credential form cannot be
    // opened without it, so a refetch of one is a refetch of the other.
    catalog: () => ["providers", "catalog"] as const,
    modelProfiles: () => ["providers", "model-profiles"] as const,
    // What one provider offers, for the model field's suggestions. Keyed per
    // provider because that is what is fetched - a shared key would make
    // switching provider serve the previous one's list.
    models: (providerId: string) => ["providers", providerId, "models"] as const,
  },
  secrets: {
    all: () => ["secrets"] as const,
    list: () => ["secrets", "list"] as const,
    // The shapes a secret can take, with the schema each form is generated
    // from. Deployment-wide and immutable at runtime, so no mutation touches it.
    kinds: () => ["secrets", "kinds"] as const,
    // What a secret can be for. Generated from the provider table server-side,
    // so it changes on redeploy and never on a mutation.
    purposes: () => ["secrets", "purposes"] as const,
  },
  runs: {
    all: () => ["runs"] as const,
    list: (agentId?: string) => ["runs", "list", agentId ?? "all"] as const,
    detail: (id: string) => ["runs", id] as const,
    approvals: () => ["runs", "approvals"] as const,
    spend: (days: number) => ["runs", "spend", days] as const,
  },
  sharing: {
    all: () => ["sharing"] as const,
    detail: (resourceType: SharingResourceType, resourceId: string) =>
      ["sharing", resourceType, resourceId] as const,
  },
  skills: {
    all: () => ["skills"] as const,
    list: (query: {
      search: string;
      category: string;
      sort: string;
      skip: number;
      limit: number;
    }) => ["skills", "list", query] as const,
    detail: (id: string) => ["skills", id] as const,
    resource: (skillId: string, resourceId: string) =>
      ["skills", skillId, "resources", resourceId] as const,
    /** What this deployment ships with - changes on redeploy, not on a mutation. */
    library: () => ["skills", "library"] as const,
  },
  invitations: {
    all: () => ["invitations"] as const,
    list: (orgId: string) => ["invitations", orgId] as const,
  },
  conversations: {
    all: () => ["conversations"] as const,
    list: () => ["conversations", "list"] as const,
    count: () => ["conversations", "count"] as const,
    /**
     * The newest few, for the dashboard. Its own key because `list()` is owned
     * by the chat sidebar, which caches a different page under a different
     * shape - one key with two fetchers is one of them silently winning.
     */
    recent: (limit: number) => ["conversations", "recent", limit] as const,
    messages: (id: string) => ["conversations", id, "messages"] as const,
  },
  conversationShares: {
    all: () => ["conversation-shares"] as const,
    list: (conversationId: string) => ["conversation-shares", conversationId] as const,
    sharedWithMe: (skip: number, limit: number) =>
      ["conversation-shares", "shared-with-me", skip, limit] as const,
  },
  kb: {
    all: () => ["kb"] as const,
    list: () => ["kb", "list"] as const,
    detail: (id: string) => ["kb", id] as const,
    documents: (id: string) => ["kb", id, "documents"] as const,
  },
  integrations: {
    all: () => ["integrations"] as const,
    // Keyed on the organization, not shared with `kb`: these rows belong to the
    // organization rather than to any collection, and a cache that outlived an
    // org switch would show the previous tenant's connectors on the new one's
    // page - with the connector names being the part worth not leaking.
    reusable: (orgId: string) => ["integrations", "reusable", orgId] as const,
    connectors: (orgId: string) => ["integrations", "connectors", orgId] as const,
  },
  slashCommands: {
    list: () => ["slash-commands", "list"] as const,
  },
  mcpConnections: {
    list: () => ["mcp-connections", "list"] as const,
    workspace: () => ["mcp-connections", "workspace"] as const,
    // The organization's own servers. A separate key rather than a parameter on
    // `list()`, because the two are different resources from different
    // endpoints - sharing a key would let one page's refetch overwrite the
    // other's data with rows it has no business showing.
    org: () => ["mcp-connections", "org"] as const,
  },
  mcpServers: {
    // The organization catalog. Not under `agents`: the same list backs the
    // Builder and Settings, and invalidating the agent registry must not
    // discard a catalog that only changes on redeploy.
    catalog: () => ["mcp-servers", "catalog"] as const,
  },
  sessions: {
    // The namespace, for invalidating every page at once: a revocation shifts
    // rows across all of them, so refreshing only the page on screen leaves
    // revoked sessions cached on the others.
    all: () => ["sessions"] as const,
    list: (page: number) => ["sessions", "list", page] as const,
  },
  admin: {
    stats: () => ["admin", "stats"] as const,
    events: () => ["admin", "events"] as const,
    users: (params?: unknown) => ["admin", "users", params] as const,
    conversations: (params?: unknown) => ["admin", "conversations", params] as const,
    system: () => ["admin", "system"] as const,
    ratings: (params?: unknown) => ["admin", "ratings", params] as const,
  },
} as const;
