import { type InputField, inputFieldsOf } from "@/lib/workflows/input-fields";
import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";

/**
 * The trigger nodes a workflow starts from - `app/workflows/triggers.py`.
 *
 * A workflow starts from one trigger, its entry: by hand or the API, a chat
 * message, a signed webhook, a schedule, or a new table record. Publishing a
 * version is what switches its trigger on.
 */

export const TRIGGER_CATEGORY = "triggers";

export const MANUAL_TRIGGER = "core.input";
export const CHAT_TRIGGER = "trigger.chat";
export const WEBHOOK_TRIGGER = "trigger.webhook";
export const SCHEDULE_TRIGGER = "trigger.schedule";
export const TABLE_RECORD_TRIGGER = "trigger.table_record";

/** Whether a catalog entry is a trigger - a way a run of the workflow begins. */
export function isTrigger(definition: Pick<NodeDefinition, "category"> | null): boolean {
  return definition?.category === TRIGGER_CATEGORY;
}

/** The graph's trigger node, when it has one, by the catalog it resolves against. */
export function triggerNodeOf(
  graph: WorkflowGraph,
  definitions: ReadonlyMap<string, NodeDefinition | null>,
): NodeInstance | null {
  return graph.nodes.find((node) => isTrigger(definitions.get(node.id) ?? null)) ?? null;
}

/**
 * Whether a live version starting from `liveTrigger` is started by a member
 * pressing Run or calling the API: `core.input`, or a graph whose entry is no
 * trigger. Every other trigger has its own surface.
 */
export function startsByHand(liveTrigger: string | null): boolean {
  return liveTrigger === null || liveTrigger === MANUAL_TRIGGER;
}

/** A stand-in id for a sample's conversation or record: a test run has none to name. */
const SAMPLE_ID = "00000000-0000-0000-0000-000000000000";

/**
 * What a test run of `graph` starts with by default: the input its trigger
 * would hand on, in that trigger's shape, so trying a webhook workflow does not
 * begin with an input its first step refuses. Empty for a graph that starts by
 * hand, whose input is whatever the caller sends.
 */
export function sampleRunInput(graph: WorkflowGraph | null): Record<string, unknown> {
  const entry = graph?.nodes.find((node) => node.id === graph.entry_node_id);
  switch (entry?.definition_id) {
    case CHAT_TRIGGER:
      return { prompt: "Hello", conversation_id: SAMPLE_ID, user_id: null };
    case WEBHOOK_TRIGGER:
      return { body: {}, delivery_id: "test" };
    case SCHEDULE_TRIGGER:
      return { fired_at: new Date().toISOString(), input: entry.config["input"] ?? {} };
    case TABLE_RECORD_TRIGGER: {
      const table = entry.config["table"];
      const tableId =
        table !== null && typeof table === "object" && "table_id" in table
          ? table.table_id
          : SAMPLE_ID;
      return { table_id: tableId, record_id: SAMPLE_ID, values: {}, fields: {}, author_id: null };
    }
    default:
      return {};
  }
}

/**
 * The typed fields a run of `graph` starts with: those its "Manual or API"
 * entry declares, or none - for any other entry, or a graph not loaded yet.
 */
export function declaredFields(graph: WorkflowGraph | null | undefined): InputField[] {
  const entry = graph?.nodes.find((node) => node.id === graph.entry_node_id);
  return entry?.definition_id === MANUAL_TRIGGER ? inputFieldsOf(entry.config) : [];
}
