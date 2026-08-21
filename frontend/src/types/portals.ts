/**
 * Types for trigger portals, mirroring the backend's `PortalRead`.
 *
 * A **portal** is the friendly face of an event trigger: a named service
 * (GitHub, Email) with a handful of ready-made **presets** - "fire
 * when a new issue is opened" - so a person picks a card instead of composing a
 * raw `event_source` and signing secret. The picker consumes
 * `GET /trigger-portals`; the raw form under `TriggerFormDialog` stays as the
 * advanced escape hatch.
 *
 * A portal shares its connected account with the MCP catalog through
 * `connection_catalog_key` (the `mcp_servers.json` key), so one connection backs
 * both an agent's tools and its triggers - there is no second connection system.
 * The OAuth scopes a portal registers with are deliberately not part of this
 * contract; the backend owns them.
 */

/** How a portal's webhook reaches the platform. Mirrors the backend's `DeliveryMode`. */
export type PortalDelivery = "auto_webhook" | "manual" | "polling";

/** One ready-made event a portal can fire on. */
export interface PortalPreset {
  key: string;
  label: string;
  description: string;
  /** Whether this preset needs a target (which repository) before it can be set up. */
  target_required: boolean;
}

/** One connectable service and the events it fires an agent on. */
export interface PortalCatalogEntry {
  key: string;
  name: string;
  description: string;
  category: string;
  /** Brand mark to draw, by name. Null falls back to a monogram. */
  icon: string | null;
  /** The `EventSource` every preset here fires through. */
  event_source: string;
  delivery: PortalDelivery;
  /**
   * The OAuth scope(s) a connected account must hold to auto-register this
   * portal's webhook (e.g. `["admin:repo_hook"]`). Empty for a manual or polling
   * portal that registers nothing. Checked against a connection's `granted_scopes`
   * to tell "connected" apart from "connected but missing the webhook scope".
   */
  webhook_admin_scopes: string[];
  /** What a preset's target names - "repo", "channel" - or null when none is needed. */
  target_kind: string | null;
  /** The `mcp_servers.json` key this portal shares a connection with, for joining state. */
  connection_catalog_key: string | null;
  /**
   * The organization's connection for this portal, resolved server-side so a
   * caller who may create a trigger sees the connected state without the
   * `mcp:manage`-gated connection listing. Null when nobody has connected it.
   */
  connection_id: string | null;
  /** How usable that connection is; null exactly when `connection_id` is null. */
  connection_state: "connected" | "needs_authorization" | "disabled" | "error" | null;
  /** Whether the grant covers every webhook scope - create vs re-authorize. */
  connection_covers_webhook_scopes: boolean;
  /**
   * Why connecting cannot start yet, or null when it can. Three reasons, and the
   * count matters: the card used to choose its sentence with a two-way ternary,
   * so the third rendered GitHub's message on a Gmail portal blocked by something
   * else entirely.
   *
   * GitHub's flow spends the organization's own OAuth App credentials, so with
   * none stored (`oauth_app_secret`) - or two org-visible ones and nothing to say
   * which was meant (`ambiguous_oauth_app_secret`) - pressing Connect could only
   * fail, which it did as a red toast. `oauth_unavailable` is a polled portal on a
   * deployment with no Google client configured, which the vault cannot fix: an
   * operator sets it in the environment (#1068).
   */
  connect_blocked_by:
    "oauth_app_secret" | "ambiguous_oauth_app_secret" | "oauth_unavailable" | null;
  /**
   * The vault kind whose client this portal's consent flow spends, so the card's
   * "Add credentials" opens on the right service. Null for a portal that needs no
   * account at all (the manual relay). Answered by the server rather than mapped
   * on this side: a third portal would otherwise silently ask for GitHub's.
   */
  oauth_app_kind: string | null;
  presets: PortalPreset[];
}

export interface PortalCatalogResponse {
  items: PortalCatalogEntry[];
  total: number;
}

/** One place a preset can point at - a repository, a channel. */
export interface PortalTarget {
  id: string;
  label: string;
}

export interface PortalTargetResponse {
  items: PortalTarget[];
  total: number;
}
