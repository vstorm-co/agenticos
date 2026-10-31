import type { DragEvent } from "react";
import { describe, expect, it } from "vitest";

import {
  carriesField,
  droppedField,
  observedFits,
  scrollNearEdge,
  startFieldDrag,
} from "./field-drag";

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

describe("scrolling while a field is dragged", () => {
  /** A scrolling area 400px tall from y=100, holding `inner`, scrolled to 200. */
  function area(overflowY = "auto") {
    const outer = document.createElement("div");
    outer.style.overflowY = overflowY;
    Object.defineProperty(outer, "scrollHeight", { value: 2000 });
    Object.defineProperty(outer, "clientHeight", { value: 400 });
    outer.getBoundingClientRect = () => ({ top: 100, bottom: 500 }) as DOMRect;
    outer.scrollTop = 200;
    const inner = document.createElement("span");
    outer.appendChild(inner);
    document.body.appendChild(outer);
    return { outer, inner };
  }
  const at = (target: Element, clientY: number) => ({ target, clientY }) as unknown as DragEvent;

  it("scrolls the area up near its top and down near its bottom, faster at the edge", () => {
    const { outer, inner } = area();
    scrollNearEdge(at(inner, 101));
    expect(outer.scrollTop).toBe(200 - 24);
    scrollNearEdge(at(inner, 499));
    expect(outer.scrollTop).toBe(200);
    scrollNearEdge(at(inner, 470));
    expect(outer.scrollTop).toBe(200 + 12);
  });

  it("leaves the area alone away from its edges, and anything that does not scroll", () => {
    const { outer, inner } = area();
    scrollNearEdge(at(inner, 300));
    expect(outer.scrollTop).toBe(200);

    const fixed = area("hidden");
    scrollNearEdge(at(fixed.inner, 101));
    expect(fixed.outer.scrollTop).toBe(200);
  });
});
