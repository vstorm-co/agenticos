import type { GrantLevel, GrantSubject, ResourceGrant, ShareInput } from "@/types/sharing";

/** Each level's word is in the `sharing` catalog; `words` names the key. */
export const LEVEL_OPTIONS: { value: GrantLevel; words: string }[] = [
  { value: "read", words: "levelRead" },
  { value: "use", words: "levelUse" },
  { value: "edit", words: "levelEdit" },
];

/** Radix hands back a plain string; a level the catalog does not know is a bug, not a default. */
export function toLevel(value: string): GrantLevel {
  const option = LEVEL_OPTIONS.find((candidate) => candidate.value === value);
  // i18n-exempt: a bug in the caller, never shown to a reader
  if (!option) throw new Error(`Unknown grant level: ${value}`);
  return option.value;
}

/** Who a grant is to, in the shape the revoke endpoints are addressed by. */
export function subjectOf(grant: ResourceGrant): GrantSubject {
  return grant.subject_group_id === null
    ? { kind: "user", id: grant.subject_user_id }
    : { kind: "group", id: grant.subject_group_id };
}

/**
 * A grant subject the server could not name is shown by id.
 *
 * Emails are resolved from the organization's members and group names from its
 * groups, so a subject whose membership is gone has neither - and printing the
 * id is more useful than printing nothing when the row still has to be revoked.
 */
export function subjectLabel(grant: ResourceGrant): string {
  return grant.subject_group_id === null
    ? (grant.subject_email ?? grant.subject_user_id)
    : (grant.subject_group_name ?? grant.subject_group_id);
}

/**
 * The picker's value for a subject.
 *
 * A Radix select holds one string, and a member and a group are both bare UUIDs,
 * so the kind travels in the value: `user:<id>` or `group:<id>`.
 */
export function encodeSubject(subject: GrantSubject): string {
  return `${subject.kind}:${subject.id}`;
}

/** The subject a picker value names. Anything else is a bug in the picker, not a default. */
export function parseSubject(value: string): GrantSubject {
  for (const kind of ["user", "group"] as const) {
    const prefix = `${kind}:`;
    if (value.startsWith(prefix) && value.length > prefix.length) {
      return { kind, id: value.slice(prefix.length) };
    }
  }
  // i18n-exempt: a bug in the caller, never shown to a reader
  throw new Error(`Unknown grant subject: ${value}`);
}

/** The body that shares with `subject` at `level` - one subject key, never both. */
export function shareInput(subject: GrantSubject, level: GrantLevel): ShareInput {
  return subject.kind === "group"
    ? { subject_group_id: subject.id, level }
    : { subject_user_id: subject.id, level };
}
