import { describe, expect, it } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";

import {
  ERROR_PORT,
  WORKFLOW_ERROR_SCHEMA,
  effectiveDefinition,
  errorBranches,
  instancePorts,
  routesErrors,
} from "./ports";
import type { NodeInstance } from "./types";

/**
 * The ports a node instance has once its config and policy are read - the client
 * mirror of the backend's `instance_ports`, so the canvas, the connection rule and
 * the validation mirror agree with what publishing checks.
 */

const HANDLED = { type: "object", title: "HandledError" };
const HANDLE = makeDefinition({
  id: "error.handle",
  ports: [port("in", "input", null), port("default", "output", HANDLED)],
});
const ACTION = makeDefinition({
  id: "data.map",
  ports: [port("in", "input", null), port("out", "output", null)],
});

function instance(overrides: Partial<NodeInstance>): NodeInstance {
  return {
    id: "n",
    definition_id: "data.map",
    definition_version: 1,
    config: {},
    layout: { x: 0, y: 0 },
    ...overrides,
  };
}

describe("instancePorts", () => {
  it("gives an error handler one output per configured branch, carrying the default's shape", () => {
    const handle = instance({
      definition_id: "error.handle",
      config: { branches: [{ name: "missing" }, { name: "default" }, { nope: 1 }, "junk"] },
    });
    const ports = instancePorts(handle, HANDLE);
    expect(ports.map((p) => p.id)).toEqual(["in", "default", "missing"]);
    expect(ports[2]?.schema).toBe(HANDLED);
  });

  it("gives a step that routes its errors an error port carrying the WorkflowError", () => {
    const routed = instancePorts(instance({ policy: { on_error: "route" } }), ACTION);
    expect(routed.map((p) => p.id)).toEqual(["in", "out", ERROR_PORT]);
    expect(routed[2]?.schema).toBe(WORKFLOW_ERROR_SCHEMA);
  });

  it("adds nothing to a step that fails its run, and never a second error port", () => {
    expect(instancePorts(instance({}), ACTION)).toBe(ACTION.ports);
    const already = makeDefinition({ id: "x", ports: [port(ERROR_PORT, "output", null)] });
    expect(instancePorts(instance({ policy: { on_error: "route" } }), already)).toHaveLength(1);
  });
});

describe("the Manual or API trigger's ports", () => {
  const MANUAL = makeDefinition({
    id: "core.input",
    ports: [port("out", "output", { type: "object", properties: { payload: { type: "object" } } })],
  });

  it("types its payload by the fields it declares, and leaves it open with none", () => {
    expect(instancePorts(instance({ definition_id: "core.input" }), MANUAL)).toBe(MANUAL.ports);
    const typed = instancePorts(
      instance({
        definition_id: "core.input",
        config: { fields: [{ name: "email", type: "text" }] },
      }),
      MANUAL,
    );
    expect(typed[0]?.schema).toMatchObject({
      properties: { payload: { properties: { email: { type: "string" } }, required: ["email"] } },
    });
  });
});

describe("effectiveDefinition", () => {
  it("is the definition itself when the instance adds no port", () => {
    expect(effectiveDefinition(instance({}), ACTION)).toBe(ACTION);
  });

  it("carries the instance's own ports otherwise", () => {
    const effective = effectiveDefinition(instance({ policy: { on_error: "route" } }), ACTION);
    expect(effective).not.toBe(ACTION);
    expect(effective.ports.some((p) => p.id === ERROR_PORT)).toBe(true);
  });
});

describe("helpers", () => {
  it("reads branch names only from a list of named branches", () => {
    expect(errorBranches({ branches: "no" })).toEqual([]);
    expect(errorBranches({ branches: [{ name: "a" }, { name: "" }, null] })).toEqual(["a"]);
  });

  it("routes errors only under on_error: route", () => {
    expect(routesErrors({ policy: { on_error: "route" } })).toBe(true);
    expect(routesErrors({ policy: { on_error: "fail_run" } })).toBe(false);
    expect(routesErrors({ policy: null })).toBe(false);
  });
});
