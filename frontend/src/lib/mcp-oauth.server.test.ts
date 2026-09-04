// @vitest-environment node
import { describe, expect, it } from "vitest";

import { hereForMcpOAuthReturn } from "./mcp-oauth";

describe("hereForMcpOAuthReturn on the server", () => {
  it("names no page where there is no window yet", () => {
    // A client component still renders once on the server, and the value is
    // read on a click rather than in the markup - so `undefined` here is the
    // right answer, not a hydration mismatch waiting to happen.
    expect(hereForMcpOAuthReturn()).toBeUndefined();
  });
});
