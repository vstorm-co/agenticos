import { renderHook } from "@testing-library/react";
import type { KeyboardEvent } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useCanvasShortcuts } from "./use-canvas-shortcuts";

/** An edit to the working graph: one more unwired step at `(x, y)`. */
function insertAt(x: number, y: number): string {
  const id = crypto.randomUUID();
  useWorkflowEditorStore.getState().insertNode({
    node: { id, definition_id: "act", definition_version: 1, config: {}, layout: { x, y } },
    edge: null,
    bindings: [],
    becomesEntry: false,
    replaces: null,
  });
  return id;
}

const store = useWorkflowEditorStore;

function nodeAt(id: string): NodeInstance {
  return { id, definition_id: "act", definition_version: 1, config: {}, layout: { x: 0, y: 0 } };
}

function seeded(): WorkflowGraph {
  return { entry_node_id: "a", nodes: [nodeAt("a")], edges: [], bindings: [], scopes: [] };
}

/** A synthetic keyboard event carrying only what the handler reads. */
function keyEvent(overrides: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return {
    key: "a",
    metaKey: false,
    ctrlKey: false,
    shiftKey: false,
    preventDefault: vi.fn(),
    ...overrides,
  } as unknown as KeyboardEvent;
}

function handlerFor(readOnly: boolean, cancel = vi.fn()) {
  const { result } = renderHook(() => useCanvasShortcuts(readOnly, cancel));
  return { handle: result.current, cancel };
}

describe("useCanvasShortcuts", () => {
  beforeEach(() => {
    store.getState().teardown();
  });

  it("cancels connect mode on Escape, even read-only", () => {
    const { handle, cancel } = handlerFor(true);
    handle(keyEvent({ key: "Escape" }));
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("ignores a key with no modifier", () => {
    const event = keyEvent({ key: "z" });
    const { handle, cancel } = handlerFor(false);
    handle(event);
    expect(cancel).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("ignores every edit shortcut in read-only mode", () => {
    store.getState().seedGraph(seeded());
    insertAt(5, 5);
    const { handle } = handlerFor(true);
    handle(keyEvent({ key: "z", ctrlKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("undoes on Ctrl+Z and redoes on Ctrl+Shift+Z or Ctrl+Y", () => {
    store.getState().seedGraph(seeded());
    insertAt(5, 5);
    const { handle } = handlerFor(false);

    handle(keyEvent({ key: "z", ctrlKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(1);

    handle(keyEvent({ key: "Z", ctrlKey: true, shiftKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(2);

    handle(keyEvent({ key: "z", ctrlKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(1);
    handle(keyEvent({ key: "y", ctrlKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("copies the selection on Ctrl+C and pastes it on Ctrl+V", () => {
    store.getState().seedGraph(seeded());
    store.getState().setSelection({ nodeIds: ["a"], edgeIds: [] });
    const { handle } = handlerFor(false);

    handle(keyEvent({ key: "c", metaKey: true }));
    expect(store.getState().clipboard?.nodes).toHaveLength(1);

    handle(keyEvent({ key: "v", metaKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(2);
  });

  it("cuts the selection on Ctrl+X — copying then deleting it", () => {
    store.getState().seedGraph({
      entry_node_id: "a",
      nodes: [nodeAt("a"), nodeAt("b")],
      edges: [],
      bindings: [],
      scopes: [],
    });
    store.getState().setSelection({ nodeIds: ["b"], edgeIds: [] });
    const { handle } = handlerFor(false);

    handle(keyEvent({ key: "x", ctrlKey: true }));
    expect(store.getState().clipboard?.nodes).toHaveLength(1);
    expect(store.getState().graph?.nodes.map((node) => node.id)).toEqual(["a"]);
  });

  it("hands focus back to the canvas after a cut removes the focused step", () => {
    const region = document.createElement("section");
    region.tabIndex = -1;
    document.body.appendChild(region);
    store.getState().seedGraph({
      entry_node_id: "a",
      nodes: [nodeAt("a"), nodeAt("b")],
      edges: [],
      bindings: [],
      scopes: [],
    });
    store.getState().setSelection({ nodeIds: ["b"], edgeIds: [] });
    const { handle } = handlerFor(false);

    handle(keyEvent({ key: "x", metaKey: true, currentTarget: region } as Partial<KeyboardEvent>));
    expect(document.activeElement).toBe(region);
    region.remove();
  });

  it("copies nothing when the selection is empty", () => {
    store.getState().seedGraph(seeded());
    const { handle } = handlerFor(false);
    handle(keyEvent({ key: "c", ctrlKey: true }));
    expect(store.getState().clipboard).toBeNull();
  });

  it("copies nothing before a graph is seeded, and pastes nothing without a clip", () => {
    const { handle } = handlerFor(false);
    handle(keyEvent({ key: "c", ctrlKey: true }));
    expect(store.getState().clipboard).toBeNull();

    store.getState().seedGraph(seeded());
    handle(keyEvent({ key: "v", ctrlKey: true }));
    expect(store.getState().graph?.nodes).toHaveLength(1);
  });

  it("selects the visible connections along with the steps on Select all", () => {
    store.getState().seedGraph({
      ...seeded(),
      nodes: [nodeAt("a"), nodeAt("b")],
      edges: [
        {
          id: "link",
          source_node_id: "a",
          source_port: "out",
          target_node_id: "b",
          target_port: "in",
        },
      ],
    });
    const { handle } = handlerFor(false);

    handle(keyEvent({ key: "a", ctrlKey: true }));

    expect(store.getState().selection).toMatchObject({ nodeIds: ["a", "b"], edgeIds: ["link"] });
  });

  it("selects nothing on Select all before a graph is seeded", () => {
    const { handle } = handlerFor(false);
    const event = keyEvent({ key: "a", ctrlKey: true });

    handle(event);

    expect(store.getState().selection.nodeIds).toEqual([]);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("selects visible objects and copies, pastes and undoes notes with steps", () => {
    store
      .getState()
      .seedGraph({ ...seeded(), notes: [{ id: "note", text: "Plan", layout: { x: 10, y: 20 } }] });
    const { handle } = handlerFor(false);
    handle(keyEvent({ key: "a", ctrlKey: true }));
    expect(store.getState().selection.nodeIds).toEqual(["a", "note"]);
    handle(keyEvent({ key: "c", ctrlKey: true }));
    handle(keyEvent({ key: "v", ctrlKey: true }));
    expect(store.getState().graph?.notes).toHaveLength(2);
    expect(store.getState().graph?.notes?.[1]).toMatchObject({
      text: "Plan",
      layout: { x: 42, y: 52 },
    });
    expect(store.getState().graph?.notes?.[1]?.id).not.toBe("note");
    handle(keyEvent({ key: "z", ctrlKey: true }));
    expect(store.getState().graph?.notes).toHaveLength(1);
  });

  it("ignores an unmapped modifier chord", () => {
    store.getState().seedGraph(seeded());
    const event = keyEvent({ key: "q", ctrlKey: true });
    const { handle } = handlerFor(false);
    handle(event);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(store.getState().isDirty).toBe(false);
  });
});

describe("the picker and the sheet from the keyboard", () => {
  beforeEach(() => store.getState().teardown());

  it("opens the step picker on Tab and the shortcut sheet on ?", () => {
    const { handle } = handlerFor(false);
    handle(keyEvent({ key: "Tab" }));
    expect(store.getState().overlay).toBe("picker");
    handle(keyEvent({ key: "?" }));
    expect(store.getState().overlay).toBe("shortcuts");
  });

  it("offers no picker on a read-only canvas, but still the sheet", () => {
    const { handle } = handlerFor(true);
    handle(keyEvent({ key: "Tab" }));
    expect(store.getState().overlay).toBeNull();
    handle(keyEvent({ key: "?" }));
    expect(store.getState().overlay).toBe("shortcuts");
  });

  it("leaves every key to a field someone is typing in", () => {
    const { handle } = handlerFor(false);
    for (const target of [
      document.createElement("textarea"),
      document.createElement("input"),
      document.createElement("select"),
      (() => {
        const el = document.createElement("div");
        el.setAttribute("contenteditable", "true");
        return el;
      })(),
    ]) {
      handle(keyEvent({ key: "Tab", target } as Partial<KeyboardEvent>));
      handle(keyEvent({ key: "z", ctrlKey: true, target } as Partial<KeyboardEvent>));
    }
    expect(store.getState().overlay).toBeNull();
  });
});

it("leaves navigation and editing keys inside a canvas dialog to that dialog", () => {
  const dialog = document.createElement("div");
  dialog.setAttribute("role", "dialog");
  const button = document.createElement("button");
  dialog.append(button);
  const { handle } = handlerFor(false);
  const event = keyEvent({ key: "Tab", target: button });
  handle(event);
  expect(event.preventDefault).not.toHaveBeenCalled();
});
