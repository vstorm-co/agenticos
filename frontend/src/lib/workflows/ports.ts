import { inputFieldsOf, typedPayloadPort } from "./input-fields";
import { FIELD_TRIGGERS } from "./triggers";
import type { JsonSchema, NodeDefinition, NodeInstance, Port } from "./types";

/**
 * The ports one node instance actually has, which its config and policy decide
 * as well as its definition - the client mirror of the backend's `instance_ports`.
 *
 * `error.handle` has one output per configured branch beside `default`,
 * `logic.switch` one per rule before `otherwise`, and `ai.classify` one per
 * category before `other`, then `unsure` when it sets a minimum confidence,
 * `human.approval` one per choice before `rejected` in place of `approved`, and
 * `logic.split` one per branch after `in`; a
 * Manual or API trigger's `out` carries a `payload` typed by the fields it
 * declares, and any node whose policy routes its errors has an `error` output
 * carrying the `WorkflowError`. Everything that reads ports - the node's handles, the edge
 * variant, the connection rule, the validation mirror, the binding pickers -
 * reads them through {@link effectiveDefinition}, so none of them can disagree.
 */

/**
 * The ports an author names on a step: its config's list, the key holding each
 * entry's name, and the ports the step has whatever the author names - what the
 * backend's `_RESERVED` sets hold. (The catalog's ports here already carry the
 * author's own, so they cannot say which are static.)
 */
export const AUTHOR_NAMED_PORTS: Readonly<
  Record<string, { list: string; key: string; static: readonly string[] }>
> = {
  "logic.switch": { list: "rules", key: "name", static: ["in", "otherwise"] },
  "ai.classify": { list: "categories", key: "name", static: ["in", "other"] },
  "error.handle": { list: "branches", key: "name", static: ["in", "default"] },
  "human.approval": { list: "choices", key: "id", static: ["in", "approved", "rejected"] },
  "logic.split": { list: "branches", key: "name", static: ["in"] },
};

/** The output a node with `on_error: "route"` fails through. */
export const ERROR_PORT = "error";

/** The shape of the `WorkflowError` an error port carries. */
export const WORKFLOW_ERROR_SCHEMA: JsonSchema = {
  type: "object",
  title: "WorkflowError",
  properties: {
    code: { type: "string", title: "Code" },
    message: { type: "string", title: "Message" },
    details: { type: "object", title: "Details", additionalProperties: true },
    retryable: { type: "boolean", title: "Retryable" },
    bypassable: { type: "boolean", title: "Bypassable" },
  },
  required: ["code", "message"],
};

/** Whether a failure leaves this node by its `error` port rather than failing the run. */
export function routesErrors(instance: Pick<NodeInstance, "policy">): boolean {
  return instance.policy?.on_error === "route";
}

/** The branch names an `error.handle` config declares, in order - bad entries skipped. */
export function errorBranches(config: Record<string, unknown>): string[] {
  return namedEntries(config.branches);
}

/** The rule names a `logic.switch` config declares, in order - bad entries skipped. */
export function switchRules(config: Record<string, unknown>): string[] {
  return namedEntries(config.rules);
}

/** The branch names a `logic.split` config declares, in order - bad entries skipped. */
export function splitBranches(config: Record<string, unknown>): string[] {
  return namedEntries(config.branches);
}

/** The category names an `ai.classify` config declares, in order - bad entries skipped. */
export function classifyCategories(config: Record<string, unknown>): string[] {
  return namedEntries(config.categories);
}

/**
 * `ports` with one output per `names`, in order, before the `last` way out -
 * the shape of a switch's rules before `otherwise` and a classifier's categories
 * before `other`.
 */
function namedOutputsBefore(ports: Port[], names: string[], last: string): Port[] {
  const fallback = ports.find((port) => port.id === last);
  const seen = new Set(ports.map((port) => port.id));
  const named = names
    .filter((name) => !seen.has(name))
    .map<Port>((name) => ({
      id: name,
      label: name,
      kind: "output",
      schema: fallback?.schema ?? null,
    }));
  return [
    ...ports.filter((port) => port.id !== last),
    ...named,
    ...(fallback === undefined ? [] : [fallback]),
  ];
}

/** The ways of approving a `human.approval` config offers, in order - bad entries skipped. */
export function approvalChoices(config: Record<string, unknown>): { id: string; label: string }[] {
  if (!Array.isArray(config.choices)) return [];
  return config.choices.flatMap((entry) => {
    if (typeof entry !== "object" || entry === null) return [];
    const { id, label } = entry as { id?: unknown; label?: unknown };
    if (typeof id !== "string" || id.length === 0) return [];
    return [{ id, label: typeof label === "string" && label.length > 0 ? label : id }];
  });
}

function namedEntries(entries: unknown): string[] {
  if (!Array.isArray(entries)) return [];
  return entries
    .map((branch) =>
      typeof branch === "object" && branch !== null ? (branch as { name?: unknown }).name : null,
    )
    .filter((name): name is string => typeof name === "string" && name.length > 0);
}

/** The ports `instance` has, in the order the node draws them. */
export function instancePorts(instance: NodeInstance, definition: NodeDefinition): Port[] {
  let ports = definition.ports;
  if (definition.id === "error.handle") {
    const defaultPort = ports.find((port) => port.id === "default");
    const seen = new Set(ports.map((port) => port.id));
    const branches = errorBranches(instance.config)
      .filter((name) => !seen.has(name))
      .map<Port>((name) => ({
        id: name,
        label: name,
        kind: "output",
        schema: defaultPort?.schema ?? null,
      }));
    ports = [...ports, ...branches];
  }
  if (definition.id === "logic.split") {
    // One output per branch, taking any step: a Split hands nothing on.
    const seen = new Set(ports.map((port) => port.id));
    ports = [
      ...ports,
      ...splitBranches(instance.config)
        .filter((name) => !seen.has(name))
        .map<Port>((name) => ({ id: name, label: name, kind: "output", schema: null })),
    ];
  }
  if (definition.id === "logic.switch") {
    // Rules first, in their order, then the way out when none holds.
    ports = namedOutputsBefore(ports, switchRules(instance.config), "otherwise");
  }
  if (definition.id === "ai.classify") {
    ports = namedOutputsBefore(ports, classifyCategories(instance.config), "other");
    // Below its minimum confidence the step leaves by `unsure`; the backend declares
    // that port only when a minimum is set, so a graph cannot wire it otherwise.
    if (
      typeof instance.config.min_confidence === "number" &&
      !ports.some((port) => port.id === "unsure")
    ) {
      const other = ports.find((port) => port.id === "other");
      ports = [
        ...ports,
        { id: "unsure", label: "Unsure", kind: "output", schema: other?.schema ?? null },
      ];
    }
  }
  if (definition.id === "human.approval") {
    // With choices there is no `approved`: the approver's choice is the way out.
    const choices = approvalChoices(instance.config);
    if (choices.length > 0) {
      const rejected = ports.find((port) => port.id === "rejected");
      const schema = rejected?.schema ?? null;
      const kept = ports.filter((port) => port.id !== "approved" && port.id !== "rejected");
      // A draft config may repeat an id or reuse `in` or `rejected`; one handle per id.
      const seen = new Set([...ports.map((port) => port.id), "approved"]);
      const named = choices.filter(({ id }) => !seen.has(id) && seen.add(id));
      ports = [
        ...kept,
        ...named.map<Port>(({ id, label }) => ({ id, label, kind: "output", schema })),
        ...(rejected === undefined ? [] : [rejected]),
      ];
    }
  }
  if (FIELD_TRIGGERS.has(definition.id)) {
    const fields = inputFieldsOf(instance.config);
    if (fields.length > 0) ports = ports.map((port) => typedPayloadPort(port, fields));
  }
  if (routesErrors(instance) && !ports.some((port) => port.id === ERROR_PORT)) {
    ports = [
      ...ports,
      { id: ERROR_PORT, label: "Error", kind: "output", schema: WORKFLOW_ERROR_SCHEMA },
    ];
  }
  return ports;
}

/** `definition` with the ports this instance actually has. */
export function effectiveDefinition(
  instance: NodeInstance,
  definition: NodeDefinition,
): NodeDefinition {
  const ports = instancePorts(instance, definition);
  return ports === definition.ports ? definition : { ...definition, ports };
}
