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

describe("pointer dragging", () => {
  it("tracks the pointer after a threshold, drops in a live lane and suppresses the opening click", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    const card = document.createElement("div");
    const lane = document.createElement("div");
    lane.dataset.kanbanLane = "done";
    lane.dataset.kanbanAccepts = "true";
    const hit = vi.fn(() => lane);
    Object.defineProperty(document, "elementFromPoint", { configurable: true, value: hit });
    const item = { id: "r1" };
    const event = (x: number) =>
      ({
        button: 0,
        pointerId: 1,
        clientX: x,
        clientY: 20,
        currentTarget: card,
        target: card,
        preventDefault: vi.fn(),
      }) as unknown as React.PointerEvent<HTMLDivElement>;
    act(() => result.current.cardProps(item).onPointerDown(event(10)));
    act(() => result.current.cardProps(item).onPointerMove(event(12)));
    expect(result.current.draggingItem).toBeNull();
    act(() => result.current.cardProps(item).onPointerMove(event(25)));
    expect(result.current.position).toEqual({ x: 25, y: 20 });
    expect(result.current.laneProps("done", true)["data-drag-over"]).toBe(true);
    act(() => result.current.cardProps(item).onPointerUp(event(25)));
    expect(onDrop).toHaveBeenCalledExactlyOnceWith(item, "done");
    expect(result.current.draggingItem).toBeNull();
    const click = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
    result.current.cardProps(item).onClickCapture(click as unknown as React.MouseEvent);
    expect(click.stopPropagation).toHaveBeenCalledOnce();
    Reflect.deleteProperty(document, "elementFromPoint");
  });

  it("cancels a pointer move without writing", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag(onDrop));
    const card = document.createElement("div");
    const event = {
      button: 0,
      pointerId: 1,
      clientX: 0,
      clientY: 0,
      target: card,
      currentTarget: card,
    } as unknown as React.PointerEvent<HTMLDivElement>;
    act(() => result.current.cardProps("item").onPointerDown(event));
    act(() => result.current.cardProps("item").onPointerCancel());
    expect(onDrop).not.toHaveBeenCalled();
    expect(result.current.position).toBeNull();
  });
});
