import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useFileDrop } from "./use-file-drop";

/**
 * A drag event as the browser delivers it.
 *
 * jsdom has no `DataTransfer`, so the payload is attached by hand. Everything
 * under test reads exactly two things off it - `types` and `files` - which is
 * what makes the stand-in honest rather than a shape invented for the test.
 */
function drag(type: string, { files = [] as File[], carries = "Files" } = {}): Event {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", {
    value: { types: [carries], files },
  });
  return event;
}

const FILE = new File(["x"], "plan.xlsx", { type: "application/vnd.ms-excel" });

describe("dropping a file anywhere on the page", () => {
  it("takes the whole page as the target while a file is over it", () => {
    const { result } = renderHook(() => useFileDrop({ onFiles: vi.fn() }));

    act(() => void window.dispatchEvent(drag("dragenter")));

    expect(result.current.isDragging).toBe(true);
  });

  it("stays put over every element the pointer crosses", () => {
    // `dragenter` and `dragleave` fire per element, so a transcript full of cards
    // is a stream of both - counted rather than believed, or the overlay flickers
    // once per child and the drop lands on whatever is underneath.
    const { result } = renderHook(() => useFileDrop({ onFiles: vi.fn() }));

    act(() => {
      window.dispatchEvent(drag("dragenter"));
      window.dispatchEvent(drag("dragenter"));
      window.dispatchEvent(drag("dragleave"));
    });
    expect(result.current.isDragging).toBe(true);

    act(() => void window.dispatchEvent(drag("dragleave")));
    expect(result.current.isDragging).toBe(false);
  });

  it("hands over what was dropped, and puts the overlay away", () => {
    const onFiles = vi.fn();
    const { result } = renderHook(() => useFileDrop({ onFiles }));

    act(() => {
      window.dispatchEvent(drag("dragenter"));
      window.dispatchEvent(drag("drop", { files: [FILE] }));
    });

    expect(onFiles).toHaveBeenCalledWith([FILE]);
    expect(result.current.isDragging).toBe(false);
  });

  it("stops the browser opening the file instead", () => {
    // The default for a dropped file is to navigate to it, which is how missing
    // the composer used to cost somebody the conversation they were in.
    renderHook(() => useFileDrop({ onFiles: vi.fn() }));

    const over = drag("dragover");
    const dropped = drag("drop", { files: [FILE] });
    act(() => {
      window.dispatchEvent(over);
      window.dispatchEvent(dropped);
    });

    expect(over.defaultPrevented).toBe(true);
    expect(dropped.defaultPrevented).toBe(true);
  });

  it("leaves a drag that is not carrying files entirely alone", () => {
    // Selected text, a link, one of the app's own draggable rows. Not just
    // ignored - not prevented either, or dragging text inside the page breaks.
    const onFiles = vi.fn();
    const { result } = renderHook(() => useFileDrop({ onFiles }));

    const over = drag("dragover", { carries: "text/plain" });
    act(() => {
      window.dispatchEvent(drag("dragenter", { carries: "text/plain" }));
      window.dispatchEvent(over);
      // Including the leave: counting one that was never counted in would take
      // the depth negative and put the overlay away mid-drag.
      window.dispatchEvent(drag("dragleave", { carries: "text/plain" }));
      window.dispatchEvent(drag("drop", { carries: "text/plain" }));
    });

    expect(result.current.isDragging).toBe(false);
    expect(over.defaultPrevented).toBe(false);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("puts the overlay away when the drag is cancelled rather than dropped", () => {
    // Escape, or a drop outside the window. Nothing else ends that drag, so
    // without this the overlay sits over a page nobody is dragging onto.
    const { result } = renderHook(() => useFileDrop({ onFiles: vi.fn() }));

    act(() => void window.dispatchEvent(drag("dragenter")));
    act(() => void window.dispatchEvent(new Event("dragend")));

    expect(result.current.isDragging).toBe(false);
  });

  it("accepts nothing while the composer is disabled", () => {
    // An archived conversation, a run waiting on an approval. The overlay never
    // appearing is what says the page is not taking files.
    const onFiles = vi.fn();
    const { result } = renderHook(() => useFileDrop({ onFiles, disabled: true }));

    act(() => {
      window.dispatchEvent(drag("dragenter"));
      window.dispatchEvent(drag("drop", { files: [FILE] }));
    });

    expect(result.current.isDragging).toBe(false);
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("drops an empty drop rather than uploading nothing", () => {
    const onFiles = vi.fn();
    renderHook(() => useFileDrop({ onFiles }));

    act(() => void window.dispatchEvent(drag("drop")));

    expect(onFiles).not.toHaveBeenCalled();
  });

  it("stops listening when it goes away", () => {
    const onFiles = vi.fn();
    const { unmount } = renderHook(() => useFileDrop({ onFiles }));

    unmount();
    window.dispatchEvent(drag("drop", { files: [FILE] }));

    expect(onFiles).not.toHaveBeenCalled();
  });
});
