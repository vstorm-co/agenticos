import { describe, expect, it } from "vitest";

import { ERROR_PORT } from "@/lib/workflows/ports";

import { DEBUG_ECHO, echo, edge, graph, makeCatalog, makeDefinition, node, port } from "./fixtures";
import { graphWarnings } from "./warnings";

const labelled = (id: string, label: string) => ({ ...port(id, "output", null), label });

const APPROVAL = makeDefinition({
  id: "human.approval",
  kind: "control",
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    labelled("approved", "Approved"),
    labelled("rejected", "Rejected"),
  ],
});
const IF = makeDefinition({
  id: "logic.if",
  kind: "control",
  exclusive_branches: true,
  ports: [
    port("in", "input", null),
    labelled("true", "True"),
    labelled("false", "False"),
    labelled(ERROR_PORT, "Error"),
  ],
});
const catalog = makeCatalog([DEBUG_ECHO, APPROVAL, IF]);
const t = (key: string, values?: Record<string, string | number>) =>
  values === undefined ? key : `${key} ${JSON.stringify(values)}`;
const found = (g: ReturnType<typeof graph>) =>
  graphWarnings(g, catalog, t).map((warning) => [warning.nodeId, warning.message]);

describe("graphWarnings", () => {
  it("names each approval outcome nothing follows", () => {
    const g = graph({
      entry: "a",
      nodes: [echo("a"), node("ok", "human.approval"), echo("b")],
      edges: [edge("e1", "a", "out", "ok", "in"), edge("e2", "ok", "approved", "b", "in")],
    });
    expect(found(g)).toEqual([["ok", 'validationApprovalOutcomeUnwired {"outcome":"Rejected"}']]);
  });

  it("names both outcomes of an approval that leads nowhere", () => {
    const g = graph({ entry: "ok", nodes: [node("ok", "human.approval")] });
    expect(found(g).map(([, message]) => message)).toEqual([
      'validationApprovalOutcomeUnwired {"outcome":"Approved"}',
      'validationApprovalOutcomeUnwired {"outcome":"Rejected"}',
    ]);
  });

  it("lets a deciding step end the run on one side, and flags it only when no side leads on", () => {
    const oneSide = graph({
      entry: "if",
      nodes: [node("if", "logic.if"), echo("b")],
      edges: [edge("e1", "if", "true", "b", "in")],
    });
    expect(found(oneSide)).toEqual([]);

    // Its error port is not an outcome: wiring only that still leads nowhere.
    const errorOnly = graph({
      entry: "if",
      nodes: [node("if", "logic.if"), echo("b")],
      edges: [edge("e1", "if", ERROR_PORT, "b", "in")],
    });
    expect(found(errorOnly)).toEqual([["if", "validationBranchOutputsUnwired"]]);
  });

  it("says nothing of a step switched off, a step that does not decide, or one unknown", () => {
    const g = graph({
      entry: "a",
      nodes: [
        echo("a"),
        { ...node("ok", "human.approval"), disabled: true },
        node("ghost", "nobody.knows"),
      ],
    });
    expect(found(g)).toEqual([]);
  });
});
