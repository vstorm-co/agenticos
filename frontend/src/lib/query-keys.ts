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
  rag: {
    stats: () => ["rag", "stats"] as const,
    // Keyed on the organization. Collection names and document titles belong to
    // one tenant, and a cache that outlived an org switch would paint the
    // previous tenant's names onto the new one's page for as long as the
    // refetch took - the names being the part worth not leaking.
    collections: (orgId: string) => ["rag", "collections", orgId] as const,
    documents: (orgId: string, collection: string) =>
      ["rag", "documents", orgId, collection] as const,
    // The sync tab, under one prefix so a mutation on any of it refreshes all
    // of it: creating a source changes the source list, triggering a sync
    // changes the history, and the two are read side by side.
    sync: (orgId: string) => ["rag", "sync", orgId] as const,
    syncSources: (orgId: string) => ["rag", "sync", orgId, "sources"] as const,
    syncLogs: (orgId: string, collection: string) =>
      ["rag", "sync", orgId, "logs", collection] as const,
    connectors: (orgId: string) => ["rag", "sync", orgId, "connectors"] as const,
    // Not keyed on the organization: what the deployment's parsers accept is a
    // property of the deployment, the same answer for every tenant.
    supportedFormats: () => ["rag", "supported-formats"] as const,
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
  conversationWorkspace: {
    all: () => ["conversation-workspace"] as const,
    files: (conversationId: string) => ["conversation-workspace", conversationId] as const,
    file: (conversationId: string, path: string) =>
      ["conversation-workspace", conversationId, path] as const,
    // The same file's bytes, keyed apart from its text: two different bodies, and
    // a viewer showing a PDF must not read a cached string for it.
    bytes: (conversationId: string, path: string) =>
      ["conversation-workspace", "bytes", conversationId, path] as const,
  },
  sandboxWorkspaces: {
    all: () => ["sandbox-workspaces"] as const,
    list: () => ["sandbox-workspaces", "list"] as const,
    files: (id: string) => ["sandbox-workspaces", "files", id] as const,
    // Every file across every visible workspace, which is a different request
    // from any one workspace's - and an expensive one, so it gets its own entry
    // rather than sharing the listing's.
    allFiles: () => ["sandbox-workspaces", "all-files"] as const,
    // One file's bytes, for a download or an image. Keyed apart from `file`, which
    // holds the same file's text - they are two different bodies.
    bytes: (id: string, path: string) => ["sandbox-workspaces", "bytes", id, path] as const,
    file: (id: string, path: string) => ["sandbox-workspaces", "file", id, path] as const,
  },
  skillChanges: {
    all: () => ["skill-changes"] as const,
    // Keyed by filter: the reviewer's list is the pending ones, and a page
    // showing every decided proposal must not overwrite it in the cache.
    list: (status: string) => ["skill-changes", "list", status] as const,
  },
  sandboxConnections: {
    all: () => ["sandbox-connections"] as const,
    list: () => ["sandbox-connections", "list"] as const,
    // What one connection's service allows, keyed per connection: a policy is a
    // round trip to a host that may be down, and two connections must not share
    // a cache entry that one of them cannot fill.
    policy: (id: string) => ["sandbox-connections", "policy", id] as const,
    // Whether this deployment runs a service of its own. One entry: it is a fact
    // about the deployment rather than about any connection.
    local: () => ["sandbox-connections", "local"] as const,
    // The library's runtime catalog. Static for the life of the deployment, so it
    // is keyed once and never invalidated.
    runtimes: () => ["sandbox-connections", "runtimes"] as const,
    // Live state on a host, keyed per connection for the same reason the policy
    // is: two hosts must not share a cache entry one of them cannot fill.
    sessions: (id: string) => ["sandbox-connections", "sessions", id] as const,
    events: (id: string, sessionId: string) =>
      ["sandbox-connections", "events", id, sessionId] as const,
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
