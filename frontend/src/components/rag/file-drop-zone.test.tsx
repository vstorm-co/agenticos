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
  it("keeps the hint across child boundaries and clears a cancelled drag", () => {
    const { target } = zone();
    const wrapper = target.parentElement;
    if (!wrapper) throw new Error("Missing zone");
    const sibling = document.createElement("span");
    wrapper.append(sibling);
    const dataTransfer = { types: ["Files"], files: [] };
    fireEvent.dragEnter(target, { dataTransfer });
    const leave = createEvent.dragLeave(target, { dataTransfer });
    Object.defineProperty(leave, "relatedTarget", { value: sibling });
    fireEvent(target, leave);
    expect(screen.getByTestId("project-file-drop-overlay")).toBeInTheDocument();
    vi.spyOn(wrapper, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 10, 200, 100));
    const webkitLeave = createEvent.dragLeave(target, { dataTransfer });
    Object.defineProperties(webkitLeave, {
      relatedTarget: { value: null },
      clientX: { value: 50 },
      clientY: { value: 60 },
    });
    fireEvent(target, webkitLeave);
    expect(screen.getByTestId("project-file-drop-overlay")).toBeInTheDocument();
    fireEvent(window, new Event("dragend"));
    expect(screen.queryByTestId("project-file-drop-overlay")).not.toBeInTheDocument();
    fireEvent.dragEnter(target, { dataTransfer });
    fireEvent.blur(window);
    expect(screen.queryByTestId("project-file-drop-overlay")).not.toBeInTheDocument();
  });

  it("uses copy feedback for external files and leaves internal moves alone", () => {
    const { target } = zone();
    const files = { types: ["Files"], dropEffect: "" };
    fireEvent.dragOver(target, { dataTransfer: files });
    expect(files.dropEffect).toBe("copy");
    const internal = { types: ["application/x-agenticos-project-path"], dropEffect: "move" };
    const over = createEvent.dragOver(target, { dataTransfer: internal });
    fireEvent(target, over);
    expect(over.defaultPrevented).toBe(false);
    expect(internal.dropEffect).toBe("move");
  });
});

it("does not navigate away when a file misses the project drop area", () => {
  const { onFiles } = zone();
  const drop = createEvent.drop(window, {
    dataTransfer: { types: ["Files"], files: [new File(["x"], "missed.pdf")] },
  });
  fireEvent(window, drop);
  expect(drop.defaultPrevented).toBe(true);
  expect(onFiles).not.toHaveBeenCalled();
  const text = createEvent.drop(window, { dataTransfer: { types: ["text/plain"], files: [] } });
  fireEvent(window, text);
  expect(text.defaultPrevented).toBe(false);
});
