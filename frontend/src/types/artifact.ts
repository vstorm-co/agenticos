/**
 * Types for published artifacts, mirroring `app/schemas/artifact.py`.
 *
 * An artifact is a page an agent published - a report, a small dashboard - that
 * people open under a link. Its content changes only when the agent republishes
 * it, so nothing here carries a body: the page is loaded into a sandboxed frame
 * from a short-lived signed address (`ArtifactView`).
 */

import type { Visibility } from "./sharing";

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
  /** The handle the agent republishes it by; unique per agent. */
  name: string;
  title: string;
  visibility: Visibility;
  owner_user_id: string | null;
  /** Null once the agent that published it is deleted. */
  agent_id: string | null;
  /** The "anyone with the link" address, when one is on. */
  public_url: string | null;
  published_at: string;
  current_version: ArtifactVersion | null;
  created_at: string;
  updated_at: string | null;
}

/** One artifact as its own page reads it: with what the caller may do, decided by the server. */
export interface ArtifactDetail extends Artifact {
  can_edit: boolean;
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
  expires_at: string;
  version: ArtifactVersion;
}

/** What a stranger holding the public link receives. */
export interface PublicArtifact {
  title: string;
  published_at: string;
  view: ArtifactView;
}
