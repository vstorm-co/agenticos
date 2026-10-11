import type { DragEvent } from "react";
import { describe, expect, it } from "vitest";

import { carriesField, droppedField, observedFits, startFieldDrag } from "./field-drag";

function drag(): DragEvent {
  const data = new Map<string, string>();
  return {
    dataTransfer: {
      effectAllowed: "none",
      get types() {
        return [...data.keys()];
      },
      setData: (type: string, value: string) => data.set(type, value),
      getData: (type: string) => data.get(type) ?? "",
    },
  } as unknown as DragEvent;
}

describe("dragging a step's field", () => {
  it("carries the step, the path and the type it held", () => {
    const event = drag();
    expect(carriesField(event)).toBe(false);
    expect(droppedField(event)).toBeNull();

    startFieldDrag(event, { nodeId: "a", path: ["values", "name"], type: "string" });

    expect(carriesField(event)).toBe(true);
    expect(event.dataTransfer.effectAllowed).toBe("link");
    expect(droppedField(event)).toEqual({ nodeId: "a", path: ["values", "name"], type: "string" });
  });

  it("reads nothing out of a drop of another shape", () => {
    const event = drag();
    event.dataTransfer.setData("application/x-agenticos-step-field", '{"nodeId": 1}');
    expect(droppedField(event)).toBeNull();
    event.dataTransfer.setData("application/x-agenticos-step-field", "null");
    expect(droppedField(event)).toBeNull();
  });

  it("fits a value a run showed to the type a field declares", () => {
    expect(observedFits("string", "string")).toBe(true);
    expect(observedFits("integer", "number")).toBe(true);
    expect(observedFits("string", "number")).toBe(false);
    expect(observedFits(undefined, "number")).toBe(true);
    expect(observedFits("uuid-ish", "string")).toBe(true);
  });
});
