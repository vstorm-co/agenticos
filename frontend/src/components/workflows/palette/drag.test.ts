import { describe, expect, it, vi } from "vitest";

import type { NodeDefinition } from "@/lib/workflows/types";

import { NODE_DRAG_MIME, readNodeDragData, writeNodeDragData } from "./drag";

const DEFINITION: NodeDefinition = {
  id: "http.fetch",
  version: 2,
  name: "Fetch",
  category: "Network",
  description: "Call an HTTP endpoint",
  kind: "action",
  config_schema: null,
  input_schema: null,
  output_schema: null,
  ports: [],
  effect_kind: "read",
  retry_guarantee: "idempotent",
  scopes: [],
};

/** A minimal `DataTransfer` stand-in — jsdom does not implement the real one. */
function fakeDataTransfer(): DataTransfer {
  const store = new Map<string, string>();
  return {
    effectAllowed: "none",
    setData: vi.fn((type: string, value: string) => void store.set(type, value)),
    getData: vi.fn((type: string) => store.get(type) ?? ""),
  } as unknown as DataTransfer;
}

describe("writeNodeDragData / readNodeDragData", () => {
  it("round-trips a definition through the private MIME type", () => {
    const dt = fakeDataTransfer();

    writeNodeDragData(dt, DEFINITION);

    expect(dt.setData).toHaveBeenCalledWith(NODE_DRAG_MIME, JSON.stringify(DEFINITION));
    expect(dt.effectAllowed).toBe("copy");
    expect(readNodeDragData(dt)).toEqual(DEFINITION);
  });

  it("reads null when the drag carries nothing under the type", () => {
    expect(readNodeDragData(fakeDataTransfer())).toBeNull();
  });

  it("reads null when the payload is malformed", () => {
    const dt = fakeDataTransfer();
    dt.setData(NODE_DRAG_MIME, "{not json");

    expect(readNodeDragData(dt)).toBeNull();
  });
});
