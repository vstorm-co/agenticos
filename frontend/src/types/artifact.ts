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

/**
 * Where a version's data stands with the page's owner. `not_needed`: it reads none.
 * `withdrawn`: it was consented, but an editor withdrew it or the owner it was given
 * under is no longer the page's.
 */
export type ConsentState = "not_needed" | "pending" | "consented" | "declined" | "withdrawn";

export interface ArtifactVersion {
  id: string;
  number: number;
  media_type: ArtifactMediaType;
  size_bytes: number;
  /** The run that published it, while that run is still kept. */
  run_id: string | null;
  /** The number of the version a person restored to make this one; null for a publish. */
  restored_from: number | null;
  consent_state: ConsentState;
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
  /**
   * When it was archived, or null. An archived page serves nothing until someone
   * who may edit it restores it; the server shows one only to such a caller.
   */
  archived_at: string | null;
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

/** A page's named query of a table, as an API client sees it: field names only. */
export interface ArtifactBindingInfo {
  name: string;
  table_id: string;
  fields: string[];
}

/**
 * Where the latest version's data stands, for a caller served the latest version -
 * its owner, its editors and the roles that read every table.
 */
export interface ArtifactConsent {
  version: number;
  state: ConsentState;
  /** The digest of its page queries; confirming sends it back. */
  fingerprint: string | null;
  /** Consented without anyone confirming: the same queries, or auto-consent. */
  automatic: boolean;
  /** For an automatic consent, what it reaches that the version before it did not. */
  grown: string[];
  /** For an automatic consent given by an `edit_data` grant, whose grant it was. */
  via: string | null;
  /** The version everyone else is served; null when none is available to them yet. */
  audience_version: number | null;
  /** Whether the audience is served that version's data now. */
  shared: boolean;
  owner_name: string | null;
  withdrawn_at: string | null;
  auto_consent: boolean;
  may_confirm: boolean;
  may_withdraw: boolean;
  may_enable_auto_consent: boolean;
  may_disable_auto_consent: boolean;
}

/** One artifact as its own page reads it: with what the caller may do, decided by the server. */
export interface ArtifactDetail extends Artifact {
  can_edit: boolean;
  /** Whether the caller may hand the page to another member: its owner, or an Owner or Admin. */
  may_change_owner: boolean;
  /** Whether the caller may give someone the "data included" level: its owner, or an Owner or Admin. */
  may_grant_edit_data: boolean;
  bindings: ArtifactBindingInfo[];
  public_link: ArtifactPublicLink;
  /** Null for the page's audience, and when the latest version reads no data. */
  consent: ArtifactConsent | null;
}

/** A page query in the server's English words - what an agent is told. */
export interface BindingDisclosure {
  table: string;
  filters: string[];
  sort: string;
  limit: number;
  /** Each field and what it reads - a column, or what a worked-out one is made from. */
  fields: Record<string, string>;
}

/** A filter's operator, as the server names it. */
export type DisclosedOp =
  "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "contains" | "starts_with" | "in" | "is_null";

export type DisclosedAggregate = "count" | "sum" | "avg" | "min" | "max";

type DisclosedValue = string | number | boolean | null;

/** Where a worked-out column's values come from. */
export interface DisclosedDerivation {
  kind: "formula" | "lookup" | "rollup" | "link";
  /** A formula's input columns, by label. */
  inputs: string[];
  /** The linked table a link, lookup or rollup reads. */
  table: string | null;
  /** The column read there; none for a rollup count, and for a link none means record ids. */
  column: string | null;
  aggregate: DisclosedAggregate | null;
}

/** A page query as structured parts, for the console to put into its own words. */
export interface BindingParts {
  table: string;
  /** `value` shows a choice by its label; for `is_null`, true means the cell is empty. */
  filters: { column: string; op: DisclosedOp; value: DisclosedValue | DisclosedValue[] }[];
  sort: {
    record_time: "created_at" | "updated_at" | null;
    column: string | null;
    derived: DisclosedDerivation | null;
    direction: "asc" | "desc";
  };
  limit: number;
  fields: {
    name: string;
    column: string;
    type: ColumnTypeName;
    derived: DisclosedDerivation | null;
  }[];
  /** The other tables the query reaches through its links. */
  linked: string[];
}

/** What confirming a version shares, and with whom - shown before it is confirmed. */
export interface ArtifactDisclosure {
  version: number;
  fingerprint: string | null;
  bindings: Record<string, BindingDisclosure>;
  /** The same queries as parts, which the console words in the reader's language. */
  parts: Record<string, BindingParts>;
  tables: string[];
  visibility: Visibility;
  /** The addresses of the people the page is shared with. */
  people: string[];
  groups: string[];
  /** The roles that open every page, as role names (`owner`, `admin`, ...). */
  roles: string[];
  /** Why it cannot be confirmed now, in the server's words. */
  problem: string | null;
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
  /**
   * The page is served with its bindings' data written in, so it has them on
   * load and the console reads nothing for the first one. Only when the view was
   * asked for with data.
   */
  injected: boolean;
  /**
   * The version this viewer is served reads data its owner has not confirmed
   * sharing with them, so every binding is empty. Known when the address is minted,
   * for any viewer.
   */
  awaiting_consent: boolean;
  /** How many bindings the version has. */
  bindings: number;
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

/** One binding's records for a page load, its query read with the page owner's access. */
export interface BindingData {
  status: "ok" | "unavailable";
  /** Why it is unavailable; only sent to a viewer who may edit the page. */
  reason: string | null;
  /** With `source_changed`: the column or table that changed; only for an editor. */
  changed?: string | null;
  truncated: boolean;
  /** Which limit left records out. */
  limit: "records" | "bytes" | null;
  count: number;
  fields: Record<string, BoundField>;
  /** Each record as its `id` and every named field; `null` when empty. */
  records: Record<string, unknown>[];
}

/** A page version's live data: every binding's query, read as the page's owner. */
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

/** What a request to the page's owner asks: see `app/schemas/artifact_share_request.py`. */
export type ShareRequestKind = "audience" | "access" | "version";

export type ShareRequestStatus = "pending" | "approved" | "declined" | "voided";

export type VoidReason = "replaced" | "page_changed" | "owner_changed" | "archived" | "superseded";

/** One person or group an `audience` request asks to share the page with. */
export interface ShareRequestSubject {
  level: "read" | "use" | "edit";
  user_id: string | null;
  email: string | null;
  group_id: string | null;
  group_name: string | null;
}

/** One request, with the names to show it by - never what the page's data holds. */
export interface ArtifactShareRequest {
  id: string;
  artifact_id: string;
  kind: ShareRequestKind;
  status: ShareRequestStatus;
  requester_user_id: string;
  requester_name: string | null;
  version_id: string | null;
  version_number: number | null;
  query_fingerprint: string | null;
  requested_visibility: Visibility | null;
  requested_subjects: ShareRequestSubject[];
  note: string | null;
  void_reason: VoidReason | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  created_at: string;
  /** Whether the caller may approve or decline it; always false once decided. */
  can_decide: boolean;
}

export interface ArtifactShareRequestList {
  items: ArtifactShareRequest[];
  total: number;
}

/** What a member who cannot open a page is told about the request they filed. */
export interface ArtifactAccessRequested {
  id: string;
  kind: ShareRequestKind;
  status: ShareRequestStatus;
  created_at: string;
  note: string | null;
}

/** The answer to a share a page's guard turned into a request (HTTP 202). */
export interface SharingDeferred {
  status: "requested";
  request_id: string;
  /** Who decides it, by name; null when it has nobody left to. */
  waiting_for: string | null;
}

export type ChangeEffect = "widens" | "narrows" | "neutral";

export type ChangeAspect = "table" | "field" | "filter" | "sort" | "limit" | "linked" | "reach";

/** What a change names: a field, a condition, an order, a table or column label, or a limit. */
export type ChangeValue =
  | BindingParts["fields"][number]
  | BindingParts["filters"][number]
  | BindingParts["sort"]
  | string
  | number;

export interface BindingChange {
  aspect: ChangeAspect;
  change: "added" | "removed" | "changed";
  effect: ChangeEffect;
  before: ChangeValue | null;
  after: ChangeValue | null;
}

export interface BindingReview {
  name: string;
  change: "added" | "removed" | "changed";
  effect: ChangeEffect;
  /** An added binding's whole page query, or a removed one's last. */
  parts: BindingParts | null;
  changes: BindingChange[];
}

/** A version's page queries against the version the page's audience is served. */
export interface ArtifactVersionReview {
  version: ArtifactVersion;
  /** The number of the audience's version; null when it is served none yet. */
  compared_to: number | null;
  publisher_name: string | null;
  bindings: BindingReview[];
  unchanged: string[];
  widens: boolean;
  /** Why the words are incomplete: a table nobody can read. */
  problem: string | null;
}
