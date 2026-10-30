import { describe, expect, it } from "vitest";

import { makeDefinition, port } from "@/components/workflows/validation/fixtures";

import {
  ERROR_PORT,
  WORKFLOW_ERROR_SCHEMA,
  effectiveDefinition,
  approvalChoices,
  errorBranches,
  instancePorts,
  splitBranches,
  switchRules,
  classifyCategories,
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

  it("gives a switch one output per rule, in order, before otherwise", () => {
    const OUT = { type: "object", title: "LogicSwitchOutput" };
    const SWITCH = makeDefinition({
      id: "logic.switch",
      ports: [port("in", "input", null), port("otherwise", "output", OUT)],
    });
    const configured = instance({
      definition_id: "logic.switch",
      config: { rules: [{ name: "poland" }, { name: "otherwise" }, { name: "germany" }] },
    });
    const ports = instancePorts(configured, SWITCH);
    expect(ports.map((p) => p.id)).toEqual(["in", "poland", "germany", "otherwise"]);
    expect(ports[1]?.schema).toBe(OUT);
    expect(switchRules({ rules: "junk" })).toEqual([]);
    const bare = makeDefinition({ id: "logic.switch", ports: [port("in", "input", null)] });
    expect(instancePorts(configured, bare).map((p) => p.id)).toEqual([
      "in",
      "poland",
      "otherwise",
      "germany",
    ]);
  });

  it("gives a Split one output per branch, taking any step", () => {
    const SPLIT = makeDefinition({ id: "logic.split", ports: [port("in", "input", null)] });
    const configured = instance({
      definition_id: "logic.split",
      config: { branches: [{ name: "a" }, { name: "in" }, { name: "b" }] },
    });
    const ports = instancePorts(configured, SPLIT);
    expect(ports.map((p) => [p.id, p.kind, p.schema])).toEqual([
      ["in", "input", null],
      ["a", "output", null],
      ["b", "output", null],
    ]);
    expect(splitBranches({ branches: "junk" })).toEqual([]);
  });

  it("gives a classifier one output per category, in order, before other", () => {
    const OUT = { type: "object", title: "AiClassifyOutput" };
    const CLASSIFY = makeDefinition({
      id: "ai.classify",
      ports: [port("in", "input", null), port("other", "output", OUT)],
    });
    const configured = instance({
      definition_id: "ai.classify",
      config: { categories: [{ name: "sales" }, { name: "support" }, { description: "nameless" }] },
    });

    const ports = instancePorts(configured, CLASSIFY);

    expect(ports.map((p) => p.id)).toEqual(["in", "sales", "support", "other"]);
    expect(ports[1]?.schema).toBe(OUT);
    expect(classifyCategories({})).toEqual([]);
  });

  describe("an approval's choices", () => {
    const OUT = { type: "object", title: "HumanApprovalOutput" };
    const APPROVAL = makeDefinition({
      id: "human.approval",
      ports: [
        port("in", "input", null),
        port("approved", "output", OUT),
        port("rejected", "output", OUT),
      ],
    });

    it("keeps approved and rejected when the step offers no choices", () => {
      const plain = instance({ definition_id: "human.approval", config: { title: "Send?" } });
      expect(instancePorts(plain, APPROVAL).map((p) => p.id)).toEqual([
        "in",
        "approved",
        "rejected",
      ]);
      expect(effectiveDefinition(plain, APPROVAL)).toBe(APPROVAL);
    });

    it("gives one output per choice, labelled as the author wrote it, in place of approved", () => {
      const asking = instance({
        definition_id: "human.approval",
        config: {
          choices: [
            { id: "draft", label: "Keep a draft" },
            { id: "send_now", label: "Send now" },
            { label: "no id" },
            "junk",
          ],
        },
      });
      const ports = instancePorts(asking, APPROVAL);
      expect(ports.map((p) => [p.id, p.label])).toEqual([
        ["in", "in"],
        ["draft", "Keep a draft"],
        ["send_now", "Send now"],
        ["rejected", "rejected"],
      ]);
      expect(ports[1]?.schema).toBe(OUT);
    });

    it("draws one handle per id, skipping a repeat and any id a port already has", () => {
      const asking = instance({
        definition_id: "human.approval",
        config: {
          choices: [
            { id: "draft", label: "Keep a draft" },
            { id: "draft", label: "Again" },
            { id: "in", label: "In" },
            { id: "rejected", label: "No" },
            { id: "approved", label: "Yes" },
            { id: "send_now", label: "Send now" },
          ],
        },
      });
      expect(instancePorts(asking, APPROVAL).map((p) => p.id)).toEqual([
        "in",
        "draft",
        "send_now",
        "rejected",
      ]);
    });

    it("reads a choice with no label as its id, and nothing from a config with no list", () => {
      expect(approvalChoices({ choices: [{ id: "draft" }] })).toEqual([
        { id: "draft", label: "draft" },
      ]);
      expect(approvalChoices({})).toEqual([]);
    });
  });

  describe("a classifier's unsure port", () => {
    const OUT = { type: "object", title: "AiClassifyOutput" };
    const CLASSIFY = makeDefinition({
      id: "ai.classify",
      ports: [port("in", "input", null), port("other", "output", OUT)],
    });
    const categories = [{ name: "sales" }, { name: "support" }];

    it("adds an unsure way out after other when the classifier has a minimum confidence", () => {
      const ports = instancePorts(
        instance({ definition_id: "ai.classify", config: { categories, min_confidence: 0.7 } }),
        CLASSIFY,
      );

      expect(ports.map((p) => p.id)).toEqual(["in", "sales", "support", "other", "unsure"]);
      expect(ports[4]).toEqual({ id: "unsure", label: "Unsure", kind: "output", schema: OUT });
      expect(ports[4]?.schema).toBe(ports[3]?.schema);
    });

    it("draws the unsure port for a minimum of zero", () => {
      const ports = instancePorts(
        instance({ definition_id: "ai.classify", config: { categories, min_confidence: 0 } }),
        CLASSIFY,
      );
      expect(ports.map((p) => p.id)).toEqual(["in", "sales", "support", "other", "unsure"]);
    });

    it("draws one unsure handle when a category is called unsure too", () => {
      const ports = instancePorts(
        instance({
          definition_id: "ai.classify",
          config: { categories: [{ name: "unsure" }], min_confidence: 0.5 },
        }),
        CLASSIFY,
      );
      expect(ports.filter((p) => p.id === "unsure")).toHaveLength(1);
    });

    it("draws no unsure port without a minimum", () => {
      for (const config of [{ categories, min_confidence: null }, { categories }]) {
        const ports = instancePorts(instance({ definition_id: "ai.classify", config }), CLASSIFY);
        expect(ports.map((p) => p.id)).toEqual(["in", "sales", "support", "other"]);
      }
    });

    it("keeps a category called unsure as a category when there is no minimum", () => {
      const ports = instancePorts(
        instance({
          definition_id: "ai.classify",
          config: { categories: [{ name: "sales" }, { name: "unsure" }] },
        }),
        CLASSIFY,
      );

      expect(ports.map((p) => p.id)).toEqual(["in", "sales", "unsure", "other"]);
      expect(ports.filter((p) => p.id === "unsure")).toHaveLength(1);
    });
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
