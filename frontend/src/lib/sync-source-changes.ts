import type { SyncSourceCreate, SyncSourceRead, SyncSourceUpdate } from "@/lib/rag-api";

/** The wizard's form, filled in from a source that already exists. */
export function syncSourceForm(source: SyncSourceRead): SyncSourceCreate {
  return {
    name: source.name,
    connector_type: source.connector_type,
    collection_name: source.collection_name,
    config: { ...source.config },
    secret_id: source.secret_id,
    organizational_unit: source.organizational_unit,
    sync_mode: source.sync_mode,
    schedule_minutes: source.schedule_minutes,
  };
}

function sameConfig(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((key) => JSON.stringify(a[key]) === JSON.stringify(b[key]));
}

/**
 * The edited config, with a key the form cleared sent as null.
 *
 * The server merges a patch over the stored config, so a key simply left out
 * would keep its old value; null is how a patch removes it.
 */
function configPatch(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): Record<string, unknown> {
  const patch: Record<string, unknown> = { ...after };
  for (const key of Object.keys(before)) {
    if (after[key] === undefined) patch[key] = null;
  }
  return patch;
}

/**
 * What the edit changed, and nothing else.
 *
 * Not the whole form, because resending a field is not neutral: a `secret_id`
 * sent is checked again as the editor's own choice, so a credential private to
 * whoever set the source up would refuse an edit that only renamed it.
 */
export function syncSourceChanges(
  before: SyncSourceRead,
  form: SyncSourceCreate,
): SyncSourceUpdate {
  const changes: SyncSourceUpdate = {};
  if (form.name !== before.name) changes.name = form.name;
  if (!sameConfig(form.config, before.config)) {
    changes.config = configPatch(before.config, form.config);
  }
  if ((form.secret_id ?? null) !== before.secret_id) changes.secret_id = form.secret_id ?? null;
  if ((form.organizational_unit ?? null) !== before.organizational_unit) {
    changes.organizational_unit = form.organizational_unit ?? null;
  }
  if (form.sync_mode !== before.sync_mode) changes.sync_mode = form.sync_mode;
  if ((form.schedule_minutes ?? null) !== before.schedule_minutes) {
    changes.schedule_minutes = form.schedule_minutes ?? null;
  }
  return changes;
}
