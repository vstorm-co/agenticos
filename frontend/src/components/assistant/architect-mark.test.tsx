import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ArchitectMark, caretPoint, gazeToward } from "./architect-mark";

/**
 * The Architect's mark: which way its eyes look, and when.
 *
 * The geometry is pinned on its own, because jsdom lays nothing out; the
 * component is pinned on what it does with it - follow the box being typed in
 * while it watches, look ahead again when nothing is, and never move otherwise.
 */

function rect(left: number, top: number, width: number, height: number): DOMRect {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

const eyes = () => screen.getByTestId("architect-eyes");

afterEach(() => vi.restoreAllMocks());

describe("gazeToward", () => {
  it("looks down at text typed below the mark, within its reach", () => {
    const gaze = gazeToward(rect(0, 0, 56, 56), { x: 28, y: 500 });
    expect(gaze.x).toBeCloseTo(0);
    expect(gaze.y).toBeCloseTo(1.2);
  });

  it("looks left and right with the caret", () => {
    expect(gazeToward(rect(0, 0, 56, 56), { x: -400, y: 28 }).x).toBeCloseTo(-1.6);
    expect(gazeToward(rect(0, 0, 56, 56), { x: 400, y: 28 }).x).toBeCloseTo(1.6);
  });

  it("looks ahead at a caret on its own centre", () => {
    expect(gazeToward(rect(0, 0, 56, 56), { x: 28, y: 28 })).toEqual({ x: 0, y: 0 });
  });
});

describe("caretPoint", () => {
  function box(value: string, caret: number): HTMLTextAreaElement {
    const area = document.createElement("textarea");
    area.value = value;
    area.setSelectionRange(caret, caret);
    area.style.paddingLeft = "12px";
    area.style.paddingTop = "8px";
    area.style.lineHeight = "20px";
    vi.spyOn(area, "getBoundingClientRect").mockReturnValue(rect(100, 600, 400, 80));
    return area;
  }

  it("places the caret by the width of its line so far and the lines above it", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      font: "",
      measureText: (text: string) => ({ width: text.length * 7 }),
    } as unknown as CanvasRenderingContext2D);

    const point = caretPoint(box("first line\nhello", 17));

    expect(point.x).toBe(100 + 12 + 5 * 7);
    expect(point.y).toBe(600 + 8 + 1.5 * 20);
  });

  it("keeps a long line inside the box, and falls back to its left edge with no canvas", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      font: "",
      measureText: () => ({ width: 10_000 }),
    } as unknown as CanvasRenderingContext2D);
    expect(caretPoint(box("x".repeat(500), 500)).x).toBe(500);

    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    expect(caretPoint(box("abc", 3)).x).toBe(112);
  });

  it("reads a box with no styles of its own at a default line height", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const area = document.createElement("textarea");
    vi.spyOn(area, "getBoundingClientRect").mockReturnValue(rect(0, 0, 200, 400));

    expect(caretPoint(area)).toEqual({ x: 0, y: 10 });
  });
});

describe("ArchitectMark", () => {
  it("follows the text box being typed in while it watches, and looks ahead after", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    render(
      <>
        <ArchitectMark size="lg" watching />
        <textarea aria-label="message" />
      </>,
    );
    const area = screen.getByLabelText("message") as HTMLTextAreaElement;
    vi.spyOn(area, "getBoundingClientRect").mockReturnValue(rect(0, 800, 400, 60));

    act(() => area.focus());
    fireEvent.input(area, { target: { value: "hi" } });
    expect(eyes().style.transform).not.toBe("translate(0px, 0px)");

    act(() => area.blur());
    fireEvent.focusOut(area);
    expect(eyes().style.transform).toBe("translate(0px, 0px)");
  });

  it("keeps its eyes still when it is not watching", () => {
    render(
      <>
        <ArchitectMark size="sm" />
        <textarea aria-label="message" />
      </>,
    );
    const area = screen.getByLabelText("message");

    act(() => area.focus());
    fireEvent.input(area, { target: { value: "hi" } });

    expect(eyes().style.transform).toBe("translate(0px, 0px)");
  });

  it("stops listening once it is gone", () => {
    const removed = vi.spyOn(document, "removeEventListener");
    const { unmount } = render(<ArchitectMark watching />);

    unmount();

    expect(removed.mock.calls.map(([type]) => type)).toEqual(
      expect.arrayContaining(["input", "selectionchange", "focusin", "focusout"]),
    );
  });
});
