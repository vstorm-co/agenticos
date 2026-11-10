import { describe, expect, it } from "vitest";

import { formatMs, formatUsd } from "./format";

describe("dashboard formatters", () => {
  it("write amounts and durations in the app's language, not the browser's", () => {
    expect(formatUsd("0.17", "en")).toBe("$0.17");
    expect(formatUsd(0.17, "pl")).toBe("$0,17");
    expect(formatMs(2400, "en")).toBe("2.4 s");
    expect(formatMs(2400, "pl")).toBe("2,4 s");
  });

  it("write a single run's cost to four places, which is often under a cent", () => {
    expect(formatUsd("0.0059", "en", 4)).toBe("$0.0059");
    expect(formatUsd("0.0059", "pl", 4)).toBe("$0,0059");
  });

  it("keep sub-second latency in milliseconds and a missing figure as a dash", () => {
    expect(formatMs(850, "en")).toBe("850 ms");
    expect(formatMs(null, "en")).toBe("—");
    expect(formatUsd(null, "en")).toBe("$0.00");
  });
});
