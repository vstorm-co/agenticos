import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FileDropZone } from "./file-drop-zone";

function zone(onFiles = vi.fn()) {
  render(
    <FileDropZone collectionName="Contracts" onFiles={onFiles}>
      <p>the documents</p>
    </FileDropZone>,
  );
  return { target: screen.getByText("the documents"), onFiles };
}

/** A drag event as Firefox sometimes delivers it: no `dataTransfer` at all. */
function bare(kind: "dragEnter" | "dragOver" | "drop", target: HTMLElement) {
  const event = createEvent[kind](target);
  Object.defineProperty(event, "dataTransfer", { value: null });
  return event;
}

describe("the file drop zone", () => {
  it("uploads what is dropped", () => {
    const { target, onFiles } = zone();
    const file = new File(["x"], "nda.pdf");
    const dataTransfer = { types: ["Files"], files: [file] };

    fireEvent.dragEnter(target, { dataTransfer });
    fireEvent.drop(target, { dataTransfer });

    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("accepts a drag that arrives without a dataTransfer, and does not throw", () => {
    const { target, onFiles } = zone();

    fireEvent(target, bare("dragEnter", target));
    const over = bare("dragOver", target);
    fireEvent(target, over);
    fireEvent(target, bare("drop", target));

    // `preventDefault` on dragover is what lets the browser deliver the drop.
    expect(over.defaultPrevented).toBe(true);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("ignores a drag of text, and a drop that brought no files", () => {
    const { target, onFiles } = zone();
    const text = { types: ["text/plain"], files: [] };

    const over = createEvent.dragOver(target, { dataTransfer: text });
    fireEvent(target, over);
    fireEvent.drop(target, { dataTransfer: text });

    expect(over.defaultPrevented).toBe(false);
    expect(onFiles).not.toHaveBeenCalled();
  });
});
