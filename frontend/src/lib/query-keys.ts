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
    // One boolean assembled from as many pages as it takes - "may this caller
    // create a trigger anywhere". Its own key, not a list page's, and under
    // "agents" so the same invalidations that move the list refresh the answer.
    anyRunnable: () => ["agents", "any-runnable"] as const,
    detail: (id: string) => ["agents", id] as const,
    // The page is part of the key: a history past its page size is several
    // answers, and caching one as another shows the wrong decade of the timeline.
    versions: (id: string, skip = 0, limit = 50) =>
      ["agents", id, "versions", skip, limit] as const,
    // Every version, walked page by page - what the pickers read. Its own key
    // rather than one page's, because it is one answer assembled from several and
    // caching it as a page would hand a pager the whole history.
    allVersions: (id: string) => ["agents", id, "versions", "all"] as const,
    delegationTree: (id: string) => ["agents", id, "delegation-tree"] as const,
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
  triggers: {
    all: () => ["triggers"] as const,
    // One agent's schedules and event triggers, for the Builder's panel.
    list: (agentId: string) => ["triggers", agentId] as const,
    // Every trigger across the organization, for the sidebar and the Activity
    // tab. A separate key from `list`: it is a different question and a different
    // endpoint, and a mutation on one agent's trigger invalidates both under the
    // shared `all()` prefix.
    orgList: () => ["triggers", "org"] as const,
  },
  triggerTemplates: {
    all: () => ["trigger-templates"] as const,
    // The seeded template catalog, both modes. Curated and compiled into the
    // deployment, so it changes on redeploy and never on a mutation - cached
    // like the portal one.
    catalog: () => ["trigger-templates", "catalog"] as const,
  },
  portals: {
    all: () => ["portals"] as const,
    // The trigger-portals catalog. Curated and compiled into the deployment, so
    // it changes on redeploy and never on a mutation - cached like the MCP one.
    catalog: () => ["portals", "catalog"] as const,
    // The repositories one connected account can point a preset at. Keyed per
    // (portal, connection) because that is what is fetched - two accounts see two
    // different lists, and a shared key would serve one for the other.
    // The agent is part of the key: the server answers per the caller's access
    // on that agent, so one agent's answer must not serve another's picker.
    targets: (portalKey: string, connectionId: string, agentId: string) =>
      ["portals", "targets", portalKey, connectionId, agentId] as const,
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
    // Which providers can draw an image and what each may be asked to draw with.
    // One request rather than the catalog plus a listing per provider: which
    // models qualify is a rule the SDK enforces, so the server answers it.
    imageModels: () => ["providers", "image-models"] as const,
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
    // The window is part of the key: the same agent over two windows is two
    // answers, and caching one as the other is how a figure ends up describing a
    // period nobody asked for. The sort, the minimum-duration filter and the
    // "rated down" filter are here for the same reason: the slowest runs, the
    // newest runs and the runs somebody rated down are different answers over one
    // window, and caching one as another draws the wrong list.
    list: (
      opts: {
        agentId?: string;
        startedFrom?: string;
        startedTo?: string;
        orderBy?: string;
        descending?: boolean;
        tookOverMs?: number;
        rated?: string;
        statuses?: string[];
        surface?: string;
        modelLabel?: string;
        userId?: string;
        agentVersionId?: string;
        skip?: number;
      } = {},
    ) =>
      [
        "runs",
        "list",
        opts.agentId ?? "all",
        opts.startedFrom ?? "all-time",
        opts.startedTo ?? "no-end",
        opts.orderBy ?? "started_at",
        opts.descending ?? true,
        opts.tookOverMs ?? "no-min",
        opts.rated ?? "any-rating",
        opts.statuses?.join(",") ?? "any-status",
        opts.surface ?? "any-surface",
        opts.modelLabel ?? "any-model",
        opts.userId ?? "anyone",
        opts.agentVersionId ?? "any-version",
        opts.skip ?? 0,
      ] as const,
    detail: (id: string) => ["runs", id] as const,
    // One run's transcript, where the run-detail surface reads the answers
    // people rated down and their comments. Its own key: it is a different body
    // from the run row, and a caching collision would draw one as the other.
    // The scope is part of it - the run's own turns and the whole thread are
    // two different answers.
    transcript: (runId: string, scope: "run" | "conversation" = "run") =>
      ["runs", runId, "transcript", scope] as const,
    // What the run handed its model. Its own key like the transcript's, and for
    // the same reason: a different body from the run row, written once when the
    // run ends and never invalidated by anything the run row is invalidated by.
    manifest: (runId: string) => ["runs", runId, "manifest"] as const,
    // A separate key from `list`, because it is a separate question: `list`
    // answers "the top level", this answers "what did this run delegate", and
    // caching one as the other would show a run's children as the whole history.
    delegations: (parentRunId: string) => ["runs", "list", "delegations", parentRunId] as const,
    approvals: () => ["runs", "approvals"] as const,
    // The decided record over a window - a different question from the queue,
    // so a different key: the queue must refresh on a decision, the record on
    // a window change.
    approvalHistory: (from: string, to: string) =>
      ["runs", "approvals", "history", from, to] as const,
    // A rolling day count and an explicit range are different answers, so the
    // window descriptor is the key, whichever shape it takes.
    spend: (range: number | { from: string; to: string }) => ["runs", "spend", range] as const,
    /** Failed or out-of-budget runs, for the dashboard's recent-failures card. */
    failures: (limit: number) => ["runs", "failures", limit] as const,
  },
  stats: {
    all: () => ["stats"] as const,
    // The window is part of the key: several widgets asking the same window
    // dedupe into one request, which is the composed response's whole point.
    // `filter` is a card's own narrowing (one agent, one person). It is part of
    // the key because it is part of the question: without it, a card pinned to
    // an agent and a card asking about everybody would share one cached answer
    // and each would show the other's.
    usage: (scope: string, from: string, to: string, filter?: unknown) =>
      ["stats", "usage", scope, from, to, filter ?? null] as const,
    usageByVersion: (agentId: string, from: string, to: string) =>
      ["stats", "usage", "version", agentId, from, to] as const,
    usageByUser: (scope: string, from: string, to: string, limit: number, filter?: unknown) =>
      ["stats", "usage", "user", scope, from, to, limit, filter ?? null] as const,
    usageByHour: (scope: string, from: string, to: string, filter?: unknown) =>
      ["stats", "usage", "hour", scope, from, to, filter ?? null] as const,
  },
  ratings: {
    summary: (scope: string, from: string, to: string) =>
      ["ratings", "summary", scope, from, to] as const,
  },
  dashboard: {
    /** One card, one query: the three shared_with_me counts travel together. */
    sharedWithMe: () => ["dashboard", "shared-with-me"] as const,
    /**
     * The caller's saved arrangement, keyed on the organization: the layout is
     * per user *and* per org, so switching org must refetch rather than paint
     * one org's arrangement onto another's dashboard.
     */
    layout: (orgId: string) => ["dashboard", "layout", orgId] as const,
    /** The caller's named presets, keyed on the organization for the same reason. */
    presets: (orgId: string) => ["dashboard", "presets", orgId] as const,
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
  },
  context: {
    all: () => ["context"] as const,
    list: (query: { search: string; sort: string; skip: number; limit: number }) =>
      ["context", "list", query] as const,
    detail: (id: string) => ["context", id] as const,
  },
  invitations: {
    all: () => ["invitations"] as const,
    list: (orgId: string) => ["invitations", orgId] as const,
  },
  conversations: {
    all: () => ["conversations"] as const,
    /**
     * One page of the sidebar, under the filters it was fetched with.
     *
     * The filters are part of the key because the server applies them: a
     * search is a request, not a slice of what the client already holds, so
     * two searches are two lists and neither may answer for the other.
     *
     * Called with nothing it is the prefix over every one of them, which is
     * what a mutation invalidates - archiving a thread changes which lists it
     * belongs to, and the ones not on screen are the ones that would otherwise
     * still be holding it when somebody switches tab.
     */
    list: (params?: string) =>
      params ? (["conversations", "list", params] as const) : (["conversations", "list"] as const),
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
    // `["kb", id]` is also the prefix over everything below, so invalidating it
    // refreshes the whole detail page - the collection, its documents and the
    // three sources feeding it - in one call.
    detail: (id: string) => ["kb", id] as const,
    documents: (id: string) => ["kb", id, "documents"] as const,
    // The three sources feeding a collection, each its own key so a failure in
    // one is that section's rather than the page's. They sit behind
    // `connections:manage`, so a member who may read the collection but not the
    // integrations gets the page with these three empty, not an error.
    syncSources: (id: string) => ["kb", id, "sync-sources"] as const,
    orgIntegrations: (id: string) => ["kb", id, "org-integrations"] as const,
    connectors: (id: string) => ["kb", id, "connectors"] as const,
    // One document's stored file, as the viewer reads it. Text and bytes keyed
    // apart because they are two different bodies for one download route, and a
    // viewer showing a PDF must not be handed a cached string for it.
    documentText: (id: string, documentId: string) =>
      ["kb", id, "documents", documentId, "text"] as const,
    documentBytes: (id: string, documentId: string) =>
      ["kb", id, "documents", documentId, "bytes"] as const,
  },
  attachments: {
    // A chat attachment, which is scoped to the user rather than to a collection
    // or a workspace - so it is keyed on nothing but the file's own id.
    text: (fileId: string) => ["attachment", fileId, "text"] as const,
    bytes: (fileId: string) => ["attachment", fileId, "bytes"] as const,
    // The same file read through a run rather than through its uploader, and
    // keyed apart on purpose: the two addresses authorise different callers, so a
    // reviewer's 200 must not be answered from a cache entry a 404 wrote.
    runText: (runId: string, fileId: string) =>
      ["attachment", "run", runId, fileId, "text"] as const,
    runBytes: (runId: string, fileId: string) =>
      ["attachment", "run", runId, fileId, "bytes"] as const,
  },
  rag: {
    // Keyed on the organization: a sync source names a collection and a remote
    // folder, both of which belong to one tenant, and a cache that outlived an
    // org switch would paint the previous tenant's names onto the new one's
    // dashboard for as long as the refetch took.
    syncSources: (orgId: string) => ["rag", "sync", orgId, "sources"] as const,
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
    // Keyed on whether the files were counted: turning counting on is a different
    // request, not a refetch that replaces the cheap answer with the expensive one.
    list: (measure = false) => ["sandbox-workspaces", "list", measure] as const,
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
    // is: two hosts must not share a cache entry one of them cannot fill. `usage`
    // is part of the key rather than appended at the call site: a listing the
    // service sampled for per-sandbox usage is a different, more expensive
    // request than one without, so the two must not share a cache entry.
    sessions: (id: string, usage = false) =>
      ["sandbox-connections", "sessions", id, usage] as const,
    // The durable record, keyed on the whole query: the filters narrow a request
    // rather than an array, so two filters are two cache entries - which is what
    // makes paging back and forth free.
    operations: (query: Record<string, unknown>) =>
      ["sandbox-connections", "operations", query] as const,
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
    // One user's recent conversations, for the admin user drawer. Both are part
    // of the key because both are part of the request: a different user or a
    // different limit is a different answer, and `unknown` let a caller drift
    // onto a fresh key with a typo instead of failing.
    conversations: (params: { userId?: string; limit?: number }) =>
      ["admin", "conversations", params] as const,
    system: () => ["admin", "system"] as const,
    // The deployment-wide answer-quality summary over a window. The window is
    // the key, so picking another period refetches rather than re-rendering the
    // last one's chart.
    ratings: (params: { from?: string; to?: string }) => ["admin", "ratings", params] as const,
    organizations: () => ["admin", "organizations"] as const,
    // This deployment's own identity and access policy, as its administrator
    // edits it. Distinct from `branding.notice()` below, which is the same row
    // read by everybody: invalidating one must not refetch the other, since the
    // form and the banner answer different questions about it.
    settings: () => ["admin", "settings"] as const,
  },
  branding: {
    // The announcement banner. Not the public branding read - that one is
    // resolved on the server above `[locale]` and handed down through a context,
    // so it never enters the query cache at all.
    notice: () => ["branding", "notice"] as const,
  },
} as const;
