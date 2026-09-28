import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useKanbanDrag } from "./use-kanban-drag";

function dragEvent(): { preventDefault: () => void } {
  return { preventDefault: vi.fn() };
}

function dragStart() {
  const dataTransfer = { setData: vi.fn(), effectAllowed: "uninitialized" };
  return { dataTransfer } as unknown as React.DragEvent;
}

describe("useKanbanDrag", () => {
  it("starts with nothing being dragged", () => {
    const { result } = renderHook(() => useKanbanDrag(vi.fn()));
    expect(result.current.draggingItem).toBeNull();
  });

  it("tracks the item passed to a card's onDragStart, and clears it on drop", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));

    act(() => result.current.cardProps({ id: "r1" }).onDragStart(dragStart()));
    const lane = result.current.laneProps("lane-a", true);
    lane.onDrop(dragEvent() as unknown as React.DragEvent);

    expect(onDrop).toHaveBeenCalledWith({ id: "r1" }, "lane-a");
  });

  it("puts data on the drag, which Firefox needs before it starts one", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const event = dragStart();

    act(() => result.current.cardProps({ id: "r1" }).onDragStart(event));

    expect(event.dataTransfer.setData).toHaveBeenCalledWith("text/plain", "");
    expect(event.dataTransfer.effectAllowed).toBe("move");
  });

  it("clears the dragged item on drag end without firing a drop", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));

    act(() => result.current.cardProps({ id: "r1" }).onDragStart(dragStart()));
    act(() => result.current.cardProps({ id: "r1" }).onDragEnd());
    const lane = result.current.laneProps("lane-a", true);
    lane.onDrop(dragEvent() as unknown as React.DragEvent);

    expect(onDrop).not.toHaveBeenCalled();
  });

  it("a lane that does not accept drops calls preventDefault on neither dragOver nor drop, and never fires onDrop", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    act(() => result.current.cardProps({ id: "r1" }).onDragStart(dragStart()));

    const lane = result.current.laneProps(null, false);
    const over = dragEvent();
    lane.onDragOver(over as unknown as React.DragEvent);
    expect(over.preventDefault).not.toHaveBeenCalled();

    const drop = dragEvent();
    lane.onDrop(drop as unknown as React.DragEvent);
    expect(drop.preventDefault).toHaveBeenCalled();
    expect(onDrop).not.toHaveBeenCalled();
  });

  it("an accepting lane's dragOver calls preventDefault so the drop is allowed", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const lane = result.current.laneProps("lane-a", true);
    const over = dragEvent();

    lane.onDragOver(over as unknown as React.DragEvent);

    expect(over.preventDefault).toHaveBeenCalled();
  });

  it("a drop with nothing being dragged fires no callback", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    const lane = result.current.laneProps("lane-a", true);

    lane.onDrop(dragEvent() as unknown as React.DragEvent);

    expect(onDrop).not.toHaveBeenCalled();
  });
});
