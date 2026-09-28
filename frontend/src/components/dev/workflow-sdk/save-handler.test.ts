import { describe, expect, it, vi } from "vitest";

import { sampleGraph } from "./fixtures";
import { MockWorkflowServer, RevisionConflictError, saveWorkflow } from "./mock-workflow-api";
import { toSdkScope } from "./sdk-adapter";
import {
  SaveRefusedError,
  createGuardedSave,
  createNaiveSave,
  type SaveOutcome,
  type SaveTarget,
} from "./save-handler";
import { scopeAt } from "./typed-graph";

const NAME = "acme/wf-a";

function setup(overrides: Partial<SaveTarget> = {}) {
  const server = new MockWorkflowServer();
  server.latencyMs = 0;
  const graph = sampleGraph();
  const outcomes: SaveOutcome[] = [];
  const state = { revision: 1, graph };
  const target: SaveTarget = {
    expectedName: NAME,
    isCurrent: () => true,
    scopePath: [],
    getScope: () => graph,
    getGraph: () => state.graph,
    getRevision: () => state.revision,
    persist: async (next, expected) => {
      const saved = await saveWorkflow(server, NAME, next, expected);
      state.graph = next;
      state.revision = saved.revision;
      return saved;
    },
    onOutcome: (outcome) => outcomes.push(outcome),
    ...overrides,
  };
  const sdk = toSdkScope(graph);
  const data = { name: NAME, globalVariables: {}, layoutDirection: "RIGHT" as const, ...sdk };
  return { server, target, outcomes, data, state };
}

describe("the save callback handed to the SDK", () => {
  it("resolves success only after the server committed", async () => {
    const { target, outcomes, data, state } = setup();
    await expect(createGuardedSave(target)(data)).resolves.toBe("success");
    expect(outcomes).toEqual([{ status: "saved", revision: 2 }]);
    expect(state.revision).toBe(2);
  });

  it("throws on a 409, because a resolved 'error' is read as success by the SDK", async () => {
    const { target, outcomes, data, server } = setup();
    server.forced = "conflict";
    await expect(createGuardedSave(target)(data)).rejects.toBeInstanceOf(RevisionConflictError);
    expect(outcomes).toEqual([{ status: "conflict", expectedRevision: 1, serverRevision: 1 }]);
  });

  it("throws on any other server failure and reports it", async () => {
    const { target, outcomes, data, server } = setup();
    server.forced = "error";
    await expect(createGuardedSave(target)(data)).rejects.toThrow(/500/);
    expect(outcomes).toEqual([{ status: "failed", message: "the server answered 500" }]);
  });

  it("reports an error that is not one of ours", async () => {
    const { target, outcomes, data } = setup({
      persist: () => Promise.reject(new Error("offline")),
    });
    await expect(createGuardedSave(target)(data)).rejects.toThrow("offline");
    expect(outcomes).toEqual([{ status: "failed", message: "Error: offline" }]);
    const odd = setup({ persist: () => Promise.reject("just a string") });
    await expect(createGuardedSave(odd.target)(odd.data)).rejects.toBe("just a string");
    expect(odd.outcomes).toEqual([{ status: "failed", message: "just a string" }]);
  });

  it("refuses a save scheduled by an editor that is gone", async () => {
    const persist = vi.fn();
    const { target, outcomes, data } = setup({ isCurrent: () => false, persist });
    await expect(createGuardedSave(target)(data)).rejects.toBeInstanceOf(SaveRefusedError);
    expect(persist).not.toHaveBeenCalled();
    expect(outcomes[0]).toMatchObject({ status: "refused" });
  });

  it("refuses a payload that belongs to another workflow", async () => {
    const persist = vi.fn();
    const { target, outcomes, data } = setup({ persist });
    await expect(createGuardedSave(target)({ ...data, name: "acme/wf-b" })).rejects.toThrow(
      /payload is for acme\/wf-b/,
    );
    expect(persist).not.toHaveBeenCalled();
    expect(outcomes[0]).toMatchObject({ status: "refused" });
  });

  it("saves into a nested scope without touching the rest", async () => {
    const graph = sampleGraph();
    const body = scopeAt(graph, ["each-file"]);
    const sdk = toSdkScope(body);
    const { target, data, state } = setup({
      scopePath: ["each-file"],
      getScope: () => body,
      expectedName: "acme/wf-a::each-file",
    });
    const first = sdk.nodes[0];
    if (!first) throw new Error("no node");
    first.data.properties = { ...first.data.properties, label: "renamed" };
    await createGuardedSave(target)({ ...data, name: "acme/wf-a::each-file", ...sdk });
    expect(scopeAt(state.graph, ["each-file"]).nodes[0]?.label).toBe("renamed");
    expect(state.graph.nodes.map((n) => n.id)).toEqual(["start", "each-file", "end"]);
  });

  it("reports a stale scope path as a failure and rethrows, saving nothing", async () => {
    const persist = vi.fn();
    const { target, outcomes, data } = setup({ scopePath: ["missing"], persist });
    await expect(createGuardedSave(target)(data)).rejects.toThrow(/not a foreach/);
    expect(persist).not.toHaveBeenCalled();
    expect(outcomes).toHaveLength(1);
    expect(outcomes[0]).toMatchObject({ status: "failed" });
  });

  it("the naive callback resolves the strings the SDK reads as success, and skips the guards", async () => {
    const conflict = setup();
    conflict.server.forced = "conflict";
    await expect(createNaiveSave(conflict.target)(conflict.data)).resolves.toBe("alreadyStarted");

    const failure = setup();
    failure.server.forced = "error";
    await expect(createNaiveSave(failure.target)(failure.data)).resolves.toBe("error");

    const stale = setup({ isCurrent: () => false });
    await expect(createNaiveSave(stale.target)({ ...stale.data, name: "acme/wf-b" })).resolves.toBe(
      "success",
    );
    expect(stale.outcomes).toEqual([{ status: "saved", revision: 2 }]);
  });
});
