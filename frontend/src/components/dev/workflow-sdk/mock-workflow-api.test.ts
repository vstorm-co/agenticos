import { describe, expect, it } from "vitest";

import {
  MockWorkflowServer,
  RevisionConflictError,
  SaveFailedError,
  saveWorkflow,
} from "./mock-workflow-api";

const server = () => {
  const s = new MockWorkflowServer();
  s.latencyMs = 0;
  return s;
};

describe("mock workflow API", () => {
  it("seeds a different document for wf-b", async () => {
    const s = server();
    expect((await s.load("acme/wf-a")).graph.nodes.map((n) => n.id)).toContain("each-file");
    expect((await s.load("acme/wf-b")).graph.nodes.map((n) => n.id)).toContain("b-start");
  });

  it("accepts a save at the current revision and moves it on", async () => {
    const s = server();
    const doc = await s.load("k/wf-a");
    expect(await saveWorkflow(s, "k/wf-a", doc.graph, doc.revision)).toEqual({ revision: 2 });
    expect(s.snapshot("k/wf-a").revision).toBe(2);
    expect(s.revisionOf("k/wf-a")).toBe(2);
    expect(s.requests).toEqual([{ key: "k/wf-a", expected_revision: 1, status: 200 }]);
  });

  it("answers 409 with the server's revision when the client's is stale", async () => {
    const s = server();
    const doc = await s.load("k/wf-a");
    s.bumpRevision("k/wf-a");
    const error = await saveWorkflow(s, "k/wf-a", doc.graph, doc.revision).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(RevisionConflictError);
    expect(error).toMatchObject({ expectedRevision: 1, serverRevision: 2 });
    expect(s.requests.at(-1)?.status).toBe(409);
    // A refused save changes nothing.
    expect(s.snapshot("k/wf-a").revision).toBe(2);
  });

  it("can be told to refuse the next save, once", async () => {
    const s = server();
    const doc = await s.load("k/wf-a");
    s.forced = "conflict";
    await expect(saveWorkflow(s, "k/wf-a", doc.graph, doc.revision)).rejects.toBeInstanceOf(
      RevisionConflictError,
    );
    expect(s.forced).toBeNull();
    await expect(saveWorkflow(s, "k/wf-a", doc.graph, doc.revision)).resolves.toEqual({
      revision: 2,
    });
  });

  it("maps any other refusal to SaveFailedError", async () => {
    const s = server();
    const doc = await s.load("k/wf-a");
    s.forced = "error";
    const error = await saveWorkflow(s, "k/wf-a", doc.graph, doc.revision).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(SaveFailedError);
    expect(error).toMatchObject({ status: 500 });
  });

  it("waits out its latency when it has one", async () => {
    const s = new MockWorkflowServer();
    s.latencyMs = 5;
    const started = performance.now();
    await s.load("k/wf-a");
    expect(performance.now() - started).toBeGreaterThanOrEqual(4);
  });
});
