/** @vitest-environment node */
import { describe, expect, it } from "vitest";

import * as route from "./route";

describe("/api/auth/pairing-codes", () => {
  it("forwards a POST only: a code is made, never read back or changed", () => {
    expect(Object.keys(route)).toEqual(["POST"]);
    expect(typeof route.POST).toBe("function");
  });
});
