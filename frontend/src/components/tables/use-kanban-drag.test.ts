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

describe("useKanbanDrag with a pointer", () => {
  function pointerDown(clientX = 100, clientY = 100) {
    return {
      button: 0,
      pointerId: 1,
      clientX,
      clientY,
      target: document.body,
    } as unknown as React.PointerEvent<HTMLDivElement>;
  }

  function pointerMove(board: HTMLElement, clientX: number, clientY = 100) {
    const card = document.createElement("div");
    board.append(card);
    return {
      pointerId: 1,
      clientX,
      clientY,
      currentTarget: card,
      preventDefault: vi.fn(),
    } as unknown as React.PointerEvent<HTMLDivElement>;
  }

  function boardAt(left: number, right: number) {
    const board = document.createElement("div");
    board.dataset.kanbanBoard = "";
    board.getBoundingClientRect = () => ({ left, right }) as DOMRect;
    document.body.append(board);
    return board;
  }

  it("lets Escape cancel a drag in progress without dropping", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    const board = boardAt(0, 1000);
    const item = { id: "r1" };

    act(() => result.current.cardProps(item).onPointerDown(pointerDown()));
    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 400)));
    expect(result.current.draggingItem).toBe(item);

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    });
    expect(result.current.draggingItem).toBe(item);

    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(result.current.draggingItem).toBeNull();
    expect(onDrop).not.toHaveBeenCalled();
    board.remove();
  });

  it("scrolls the board while a card is held near either edge", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const board = boardAt(0, 1000);
    board.scrollLeft = 100;
    const item = { id: "r1" };
    act(() => result.current.cardProps(item).onPointerDown(pointerDown()));

    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 980)));
    expect(board.scrollLeft).toBe(118);

    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 20)));
    expect(board.scrollLeft).toBe(100);

    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 500)));
    expect(board.scrollLeft).toBe(100);
    board.remove();
  });

  it("swallows the click that ends a drag, and only that one", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const board = boardAt(0, 1000);
    const item = { id: "r1" };
    act(() => result.current.cardProps(item).onPointerDown(pointerDown()));
    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 400)));

    const first = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
    result.current.cardProps(item).onClickCapture(first as unknown as React.MouseEvent);
    expect(first.preventDefault).toHaveBeenCalled();
    expect(first.stopPropagation).toHaveBeenCalled();

    const second = { preventDefault: vi.fn(), stopPropagation: vi.fn() };
    result.current.cardProps(item).onClickCapture(second as unknown as React.MouseEvent);
    expect(second.preventDefault).not.toHaveBeenCalled();
    board.remove();
  });

  it("ignores a press on a card's own actions or with another button", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const board = boardAt(0, 1000);
    const item = { id: "r1" };
    const actions = document.createElement("button");
    actions.dataset.kanbanActions = "";
    document.body.append(actions);

    act(() =>
      result.current.cardProps(item).onPointerDown({
        ...pointerDown(),
        target: actions,
      } as unknown as React.PointerEvent<HTMLDivElement>),
    );
    act(() =>
      result.current.cardProps(item).onPointerDown({
        ...pointerDown(),
        button: 2,
      } as unknown as React.PointerEvent<HTMLDivElement>),
    );
    act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 400)));

    expect(result.current.draggingItem).toBeNull();
    actions.remove();
    board.remove();
  });

  it("refuses a native drag while a pointer drag owns the card", () => {
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(vi.fn()));
    const item = { id: "r1" };
    act(() => result.current.cardProps(item).onPointerDown(pointerDown()));

    const event = { preventDefault: vi.fn() };
    result.current.cardProps(item).onDragStart(event as unknown as React.DragEvent);

    expect(event.preventDefault).toHaveBeenCalled();
  });

  it("drops on the lane under the pointer, and the unassigned lane drops as null", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    const board = boardAt(0, 1000);
    const lane = document.createElement("div");
    lane.dataset.kanbanLane = "lane-a";
    lane.dataset.kanbanAccepts = "true";
    const original = document.elementFromPoint;
    document.elementFromPoint = () => lane;
    const item = { id: "r1" };
    try {
      act(() => result.current.cardProps(item).onPointerDown(pointerDown()));
      act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 400)));
      act(() =>
        result.current.cardProps(item).onPointerUp({
          pointerId: 1,
          clientX: 400,
          clientY: 100,
        } as unknown as React.PointerEvent<HTMLDivElement>),
      );
      expect(onDrop).toHaveBeenLastCalledWith(item, "lane-a");

      lane.dataset.kanbanLane = "__none__";
      act(() => result.current.cardProps(item).onPointerDown(pointerDown()));
      act(() => result.current.cardProps(item).onPointerMove(pointerMove(board, 400)));
      act(() =>
        result.current.cardProps(item).onPointerUp({
          pointerId: 1,
          clientX: 400,
          clientY: 100,
        } as unknown as React.PointerEvent<HTMLDivElement>),
      );
      expect(onDrop).toHaveBeenLastCalledWith(item, null);
    } finally {
      document.elementFromPoint = original;
      board.remove();
    }
  });

  it("ignores a release from a pointer that is not the one dragging", () => {
    const onDrop = vi.fn();
    const { result } = renderHook(() => useKanbanDrag<{ id: string }>(onDrop));
    const item = { id: "r1" };
    act(() => result.current.cardProps(item).onPointerDown(pointerDown()));

    act(() =>
      result.current.cardProps(item).onPointerUp({
        pointerId: 2,
        clientX: 0,
        clientY: 0,
      } as unknown as React.PointerEvent<HTMLDivElement>),
    );

    expect(onDrop).not.toHaveBeenCalled();
  });
});
