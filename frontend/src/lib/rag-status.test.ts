import { describe, expect, it } from "vitest";

import { ragStatus } from "./rag-status";

/**
 * The tokens are asserted against what the backend writes, not against what the
 * components used to compare with. Each row here has a source:
 * `app/services/rag_document.py` writes `processing`/`done`/`error`,
 * `app/worker/tasks/rag_tasks.py` writes `done`/`error` to a sync source, and
 * `app/repositories/sync_log.py` defaults a log to `running` with
 * `app/services/rag_sync.py` setting `cancelled`.
 */
describe("resolving a status the server sent", () => {
  it("separates a failure from a success rather than toning them alike", () => {
    expect(ragStatus("error").tone).toBe("failure");
    expect(ragStatus("done").tone).toBe("success");
  });

  it("reads both words for work still under way as progress", () => {
    expect(ragStatus("processing").tone).toBe("progress");
    expect(ragStatus("running").tone).toBe("progress");
  });

  it("keeps a cancelled sync out of both progress and failure", () => {
    // It used to be neither `done` nor `error`, so `/rag` drew it as a spinner
    // and a sync somebody stopped went on spinning for the life of the page.
    expect(ragStatus("cancelled").tone).toBe("cancelled");
  });

  it("gives every known status a word to be drawn with", () => {
    for (const status of ["processing", "running", "done", "error", "cancelled"]) {
      expect(ragStatus(status).words).not.toBeNull();
    }
  });

  it("invents nothing for a token this build does not know", () => {
    expect(ragStatus("failed")).toEqual({ words: null, tone: "unknown" });
    expect(ragStatus("")).toEqual({ words: null, tone: "unknown" });
  });
});
