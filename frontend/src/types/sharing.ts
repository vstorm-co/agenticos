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
export type SharingResourceType =
  "agent" | "skill" | "collection" | "secret" | "table" | "artifact";

interface GrantBase {
  id: string;
  resource_type: string;
  resource_id: string;
  level: GrantLevel;
}

/** A grant to one member. */
interface UserGrant extends GrantBase {
  subject_user_id: string;
  /**
   * Resolved from the organization's members. Null for a subject the server
   * could not name - and null on the response to a share, which returns the
   * grant it wrote rather than a view of it.
   */
  subject_email: string | null;
  subject_group_id: null;
  subject_group_name: null;
}

/** A grant to a group, reaching everybody in it. */
interface GroupGrant extends GrantBase {
  subject_user_id: null;
  subject_email: null;
  subject_group_id: string;
  /** Resolved from the organization's groups; null where the server could not. */
  subject_group_name: string | null;
}

/** Exactly one subject is set, which is what the union says and the server enforces. */
export type ResourceGrant = UserGrant | GroupGrant;

/** Who a grant is to, as the two endpoints that remove one address it. */
export type GrantSubject = { kind: "user"; id: string } | { kind: "group"; id: string };

export interface ResourceSharing {
  resource_type: string;
  resource_id: string;
  owner_user_id: string | null;
  visibility: Visibility;
  grants: ResourceGrant[];
}

/**
 * Share with a member or a group, or change the level of a share that already
 * exists. One subject key or the other, never both.
 */
export type ShareInput =
  { subject_user_id: string; level: GrantLevel } | { subject_group_id: string; level: GrantLevel };
