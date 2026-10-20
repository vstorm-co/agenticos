/**
 * Types for published artifacts, mirroring `app/schemas/artifact.py`.
 *
 * An artifact is a page an agent published - a report, a small dashboard - that
 * people open under a link. Its content changes only when the agent republishes
 * it, so nothing here carries a body: the page is loaded into a sandboxed frame
 * from a short-lived signed address (`ArtifactView`).
 */

import type { Visibility } from "./sharing";
import type { ColumnTypeName } from "./tables";

export type ArtifactMediaType = "text/html" | "text/markdown";

export interface ArtifactVersion {
  id: string;
  number: number;
  media_type: ArtifactMediaType;
  size_bytes: number;
  /** The run that published it, while that run is still kept. */
  run_id: string | null;
  created_at: string;
}

export interface Artifact {
  id: string;
  /** The handle the agent republishes it by; unique per agent and environment. */
  name: string;
  title: string;
  visibility: Visibility;
  owner_user_id: string | null;
  /** Null once the agent that published it is deleted. */
  agent_id: string | null;
  /** The named environment whose runs publish it; null for the default one. */
  environment_id: string | null;
  /** That environment's name, while it exists. */
  environment_name: string | null;
  /** The "anyone with the link" address, when one is on. */
  public_url: string | null;
  /** Whether the current version is bound to saved views of Virtual Tables. */
  live: boolean;
  published_at: string;
  current_version: ArtifactVersion | null;
  created_at: string;
  updated_at: string | null;
}

/** The public link's settings, which hold whether or not the link is on. */
export interface ArtifactPublicLink {
  expires_at: string | null;
  pinned_version_id: string | null;
  pinned_version: number | null;
  password_protected: boolean;
  view_count: number;
  last_viewed_at: string | null;
  /** The sites allowed to frame the public page, as `https://host` origins. */
  embed_origins: string[];
  /** The address another site puts in an `<iframe>`, while the link is on. */
  embed_url: string | null;
}

/** A page's named link to a saved view, as an API client sees it: field names only. */
export interface ArtifactBindingInfo {
  name: string;
  view_id: string;
  table_id: string;
  fields: string[];
  status: "ok" | "unavailable";
  reason: string | null;
}

/** One artifact as its own page reads it: with what the caller may do, decided by the server. */
export interface ArtifactDetail extends Artifact {
  can_edit: boolean;
  bindings: ArtifactBindingInfo[];
  public_link: ArtifactPublicLink;
}

/**
 * A change to the public link's settings. A field left out stays as it is;
 * `null` clears the expiry, the pin or the password.
 */
export interface ArtifactPublicLinkUpdate {
  expires_at?: string | null;
  pinned_version_id?: string | null;
  password?: string | null;
  embed_origins?: string[];
}

/** An agent behind at least one artifact the caller may open - the list's filter. */
export interface ArtifactAgent {
  id: string;
  name: string;
}

export interface ArtifactList {
  items: Artifact[];
  total: number;
}

export interface ArtifactVersionList {
  items: ArtifactVersion[];
  total: number;
}

/** Where a frame loads one version from, and until when that address holds. */
export interface ArtifactView {
  url: string;
  /** Names this load of the page, so its frame knows which messages are its own. */
  nonce: string;
  /** Whether the version is bound to live data. */
  live: boolean;
  expires_at: string;
  version: ArtifactVersion;
}

/** What one field of a binding reads now: its column's current label and type. */
export interface BoundField {
  label: string;
  type: ColumnTypeName;
  /** A select column's live choices, by label. */
  options: string[] | null;
  /** `archived` or `missing` when the column no longer serves values. */
  state: "ok" | "archived" | "missing";
}

/** One binding's records for a page load, read with the viewer's own access. */
export interface BindingData {
  status: "ok" | "unavailable";
  /** Why it is unavailable; only sent to a viewer who may edit the page. */
  reason: string | null;
  truncated: boolean;
  /** Which limit left records out. */
  limit: "records" | "bytes" | null;
  count: number;
  /** A filter of the view named a column no longer live, so it matches more. */
  filters_dropped: boolean;
  fields: Record<string, BoundField>;
  /** Each record as its `id` and every named field; `null` when empty. */
  records: Record<string, unknown>[];
}

/** A page version's live data: every binding, each read as the viewer. */
export interface ArtifactData {
  bindings: Record<string, BindingData>;
  /**
   * The version asked about is still the current one. False once a newer one
   * was published: every binding is then unavailable, and the console moves to
   * the current version.
   */
  current: boolean;
  read_at: string;
}

/**
 * What a stranger holding the public link receives: the page, or - behind a
 * password - only that one is needed.
 */
export type PublicArtifact =
  | { password_required: false; title: string; published_at: string; view: ArtifactView }
  | { password_required: true; title: null; published_at: null; view: null };

/** An opened public link: the page and nothing that says who made it. */
export type OpenPublicArtifact = Extract<PublicArtifact, { password_required: false }>;
