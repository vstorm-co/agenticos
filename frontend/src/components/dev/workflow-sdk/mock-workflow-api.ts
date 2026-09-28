import { sampleGraph, secondGraph } from "./fixtures";
import type { WorkflowGraph } from "./typed-graph";

/**
 * MOCK. There is no workflow API yet (#1782). This models the one contract the
 * evaluation depends on: a save carries `expected_revision`, and a stale one is
 * refused with HTTP 409 and the server's current revision.
 *
 * It answers in `Response` objects on purpose, so the client below reads a status
 * the way it will read a real one instead of catching a thrown mock error.
 */

export interface WorkflowDocument {
  revision: number;
  graph: WorkflowGraph;
}

export type ServerBehaviour = "ok" | "conflict" | "error";

/** A save the server refused because the caller's revision is stale (HTTP 409). */
export class RevisionConflictError extends Error {
  constructor(
    readonly expectedRevision: number,
    readonly serverRevision: number,
  ) {
    super(`revision ${expectedRevision} is stale, the server is at ${serverRevision}`);
    this.name = "RevisionConflictError";
  }
}

/** Any other non-2xx answer to a save. */
export class SaveFailedError extends Error {
  constructor(readonly status: number) {
    super(`the server answered ${status}`);
    this.name = "SaveFailedError";
  }
}

export class MockWorkflowServer {
  private readonly docs = new Map<string, WorkflowDocument>();
  /** Forces the next answer, whatever the revision says. Cleared after one use. */
  forced: ServerBehaviour | null = null;
  latencyMs = 150;
  readonly requests: { key: string; expected_revision: number; status: number }[] = [];

  private doc(key: string): WorkflowDocument {
    let doc = this.docs.get(key);
    if (!doc) {
      doc = { revision: 1, graph: key.endsWith("wf-b") ? secondGraph() : sampleGraph() };
      this.docs.set(key, doc);
    }
    return doc;
  }

  private async pause(): Promise<void> {
    if (this.latencyMs > 0) await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
  }

  async load(key: string): Promise<WorkflowDocument> {
    await this.pause();
    return structuredClone(this.doc(key));
  }

  /** Someone else saved: the revision moves on without this client knowing. */
  bumpRevision(key: string): number {
    const doc = this.doc(key);
    doc.revision += 1;
    return doc.revision;
  }

  /** What the server holds now. For assertions from outside the SDK's tree. */
  snapshot(key: string): WorkflowDocument {
    return structuredClone(this.doc(key));
  }

  revisionOf(key: string): number {
    return this.doc(key).revision;
  }

  /** `PUT /workflows/{key}` with `{ graph, expected_revision }`. */
  async put(
    key: string,
    body: { graph: WorkflowGraph; expected_revision: number },
  ): Promise<Response> {
    await this.pause();
    const doc = this.doc(key);
    const forced = this.forced;
    this.forced = null;
    const respond = (status: number, payload: unknown): Response => {
      this.requests.push({ key, expected_revision: body.expected_revision, status });
      return new Response(JSON.stringify(payload), { status });
    };
    if (forced === "error") return respond(500, { detail: "boom" });
    if (forced === "conflict" || body.expected_revision !== doc.revision) {
      return respond(409, { detail: "revision conflict", current_revision: doc.revision });
    }
    doc.revision += 1;
    doc.graph = structuredClone(body.graph);
    return respond(200, { revision: doc.revision });
  }
}

/** The client half: turns a `Response` into a revision, or a typed error. */
export async function saveWorkflow(
  server: MockWorkflowServer,
  key: string,
  graph: WorkflowGraph,
  expectedRevision: number,
): Promise<{ revision: number }> {
  const response = await server.put(key, { graph, expected_revision: expectedRevision });
  if (response.status === 409) {
    const { current_revision } = (await response.json()) as { current_revision: number };
    throw new RevisionConflictError(expectedRevision, current_revision);
  }
  if (!response.ok) throw new SaveFailedError(response.status);
  return (await response.json()) as { revision: number };
}
