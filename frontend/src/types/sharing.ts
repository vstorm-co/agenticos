/**
 * Types for per-resource sharing, mirroring the backend's `resource_grant`
 * schemas.
 *
 * Nothing here names a resource. Agents, skills, collections and vault secrets
 * are shared by the same four endpoints generated once per type, so what differs
 * between sharing an agent and sharing a key is the path, never the shape.
 */

/** How widely a resource is exposed inside its organization. */
export type Visibility = "private" | "team" | "org";

/** What a grant lets its subject do. Ordered read < use < edit. */
export type GrantLevel = "read" | "use" | "edit";

/** The resource kinds that carry an owner, a visibility and a grant list. */
export type SharingResourceType = "agent" | "skill" | "collection" | "secret";

export interface ResourceGrant {
  id: string;
  subject_user_id: string;
  /**
   * Resolved from the organization's members. Null for a subject the server
   * could not name — and null on the response to a share, which returns the
   * grant it wrote rather than a view of it.
   */
  subject_email: string | null;
  resource_type: string;
  resource_id: string;
  level: GrantLevel;
}

export interface ResourceSharing {
  resource_type: string;
  resource_id: string;
  owner_user_id: string | null;
  visibility: Visibility;
  grants: ResourceGrant[];
}

/** Share with a member, or change the level of a share that already exists. */
export interface ShareInput {
  subject_user_id: string;
  level: GrantLevel;
}
