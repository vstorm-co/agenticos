import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useProbeGate } from "./use-probe-gate";
import type { EmbeddingProbeResult } from "@/lib/embedding-probe-api";

function result(overrides: Partial<EmbeddingProbeResult> = {}): EmbeddingProbeResult {
  return {
    passed: true,
    outcome: "passed",
    dim: 768,
    calls: 3,
    knowledge_bases: [],
    probe_token: "tok",
    expires_at: null,
    ...overrides,
  };
}

describe("useProbeGate", () => {
  it("drops the token when any tested value changes", async () => {
    const { result: gate, rerender } = renderHook(({ values }) => useProbeGate(values), {
      initialProps: { values: { url: "a", model: "m" } },
    });
    expect(gate.current.status).toBe("idle");
    expect(gate.current.token).toBeNull();

    await act(() => gate.current.test(async () => result()));
    expect(gate.current.token).toBe("tok");
    expect(gate.current.status).toBe("passed");

    rerender({ values: { url: "a", model: "m" } });
    expect(gate.current.token).toBe("tok");

    rerender({ values: { url: "a", model: "other" } });
    expect(gate.current.token).toBeNull();
    expect(gate.current.status).toBe("idle");
    expect(gate.current.result).toBeNull();
  });

  it("keeps no token for a failed result", async () => {
    const { result: gate } = renderHook(() => useProbeGate({ url: "a" }));

    await act(() =>
      gate.current.test(async () =>
        result({ passed: false, outcome: "vectors_differ", probe_token: "tok" }),
      ),
    );

    expect(gate.current.status).toBe("failed");
    expect(gate.current.token).toBeNull();
    expect(gate.current.result?.outcome).toBe("vectors_differ");
  });
});
