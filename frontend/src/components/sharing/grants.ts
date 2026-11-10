import type {
  GrantLevel,
  GrantSubject,
  ResourceGrant,
  ShareInput,
  SharingResourceType,
} from "@/types/sharing";

type LevelOption = { value: GrantLevel; words: string };

/** Each level's word is in the `sharing` catalog; `words` names the key. */
export const LEVEL_OPTIONS: LevelOption[] = [
  { value: "read", words: "levelRead" },
  { value: "use", words: "levelUse" },
  { value: "edit", words: "levelEdit" },
];

/**
 * A level a resource no longer offers, worded to say why, for a grant that still holds it.
 *
 * A dataset's `use` gives no built-in role anything: running evals also needs
 * permission to read runs, and every role that reads runs already runs every
 * dataset. It comes back with custom roles; until then it is not offered.
 */
const RETIRED: Partial<Record<SharingResourceType, LevelOption>> = {
  dataset: { value: "use", words: "levelUseNoEffect" },
};

/** A page's level above edit; no other resource type has an owner whose data it consents to. */
const EDIT_DATA_OPTION: LevelOption = { value: "edit_data", words: "levelEditData" };

/**
 * The levels one resource type offers.
 *
 * Only a page has "Can edit, including data", and it is offered to a caller the
 * server said may give it (`mayGrantEditData`) - or kept in the list for a row that
 * holds it already, so the row can be read and moved down by any editor. A level
 * the type has retired is offered only to a row that still holds it.
 */
export function levelOptions(
  resourceType: SharingResourceType,
  { mayGrantEditData, held }: { mayGrantEditData: boolean; held?: GrantLevel },
): LevelOption[] {
  const retired = RETIRED[resourceType];
  const base = LEVEL_OPTIONS.filter((option) => option.value !== retired?.value);
  const withRetired = retired !== undefined && held === retired.value ? [...base, retired] : base;
  const offered = resourceType === "artifact" && (mayGrantEditData || held === "edit_data");
  return offered ? [...withRetired, EDIT_DATA_OPTION] : withRetired;
}

/**
 * The ids of the texts a person confirms to give "including data". The server
 * accepts only these, and records the English text in the audit entry, so a change
 * to what `editDataConfirmPerson` or `editDataConfirmGroup` says goes with a new id
 * on both sides.
 */
export const EDIT_DATA_WORDING = {
  user: "edit_data.person.v2",
  group: "edit_data.group.v2",
} as const;
/** Radix hands back a plain string; a level the catalog does not know is a bug, not a default. */
export function toLevel(value: string): GrantLevel {
  const option = [...LEVEL_OPTIONS, EDIT_DATA_OPTION].find(
    (candidate) => candidate.value === value,
  );
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

/**
 * The body that shares with `subject` at `level` - one subject key, never both.
 *
 * "Data included" carries the id of the text for this kind of subject: it is only
 * ever sent from the confirmation that shows that text.
 */
export function shareInput(subject: GrantSubject, level: GrantLevel): ShareInput {
  const confirmed = level === "edit_data" ? { confirmed: EDIT_DATA_WORDING[subject.kind] } : {};
  return subject.kind === "group"
    ? { subject_group_id: subject.id, level, ...confirmed }
    : { subject_user_id: subject.id, level, ...confirmed };
}
