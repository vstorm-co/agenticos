/**
 * Resource pickers — the single import point for the property panel's leaf.
 *
 * Each follows `collection-picker.tsx`'s shape (disambiguating context, an
 * orphaned-reference state, a create-new escape hatch). Every picker takes the
 * current value and an `onChange` that writes the appropriate ref/id, plus
 * `disabled` and a field-scoped `error`:
 *
 * - `AgentVersionPicker` (`AgentVersionRef {agent_id, version_id}`) — two-step;
 *   changing the agent clears the pinned version.
 * - `CollectionPicker` — reused as-is from the agents domain (a multi-select over
 *   `collection_ids`); re-exported so this barrel is the one place to import from.
 * - `TableColumnPicker` (`TableIORef`) — table then column, scoped to the table's
 *   current schema, with the schema-drift banner.
 * - `SecretPicker` (a vault secret id, never a value).
 */

export { CollectionPicker } from "@/components/agents/collection-picker";
export {
  AgentVersionPicker,
  type AgentVersionRef,
  type AgentVersionPickerProps,
} from "./agent-version-picker";
export { TableColumnPicker, type TableColumnPickerProps } from "./table-column-picker";
export { SecretPicker, type SecretPickerProps } from "./secret-picker";
