import { inputFieldsOf, typedPayloadPort } from "./input-fields";
import { FIELD_TRIGGERS } from "./triggers";
import type { JsonSchema, NodeDefinition, NodeInstance, Port } from "./types";

/**
 * The ports one node instance actually has, which its config and policy decide
 * as well as its definition - the client mirror of the backend's `instance_ports`.
 *
 * `error.handle` has one output per configured branch beside `default`, and
 * `logic.switch` one per rule before `otherwise`; a
 * Manual or API trigger's `out` carries a `payload` typed by the fields it
 * declares, and any node whose policy routes its errors has an `error` output
 * carrying the `WorkflowError`. Everything that reads ports - the node's handles, the edge
 * variant, the connection rule, the validation mirror, the binding pickers -
 * reads them through {@link effectiveDefinition}, so none of them can disagree.
 */

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
  if (definition.id === "logic.switch") {
    const otherwise = ports.find((port) => port.id === "otherwise");
    const seen = new Set(ports.map((port) => port.id));
    const rules = switchRules(instance.config)
      .filter((name) => !seen.has(name))
      .map<Port>((name) => ({
        id: name,
        label: name,
        kind: "output",
        schema: otherwise?.schema ?? null,
      }));
    // Rules first, in their order, then the way out when none holds.
    ports = [
      ...ports.filter((port) => port.id !== "otherwise"),
      ...rules,
      ...(otherwise === undefined ? [] : [otherwise]),
    ];
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
