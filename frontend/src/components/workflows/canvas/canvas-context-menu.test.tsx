import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ContextMenu, ContextMenuTrigger } from "@/components/ui";
import { makeDefinition, port } from "@/components/workflows/validation/fixtures";
import type { NodeInstance } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { CanvasContextMenu } from "./canvas-context-menu";

const store = useWorkflowEditorStore;
const CATALOG = [
  makeDefinition({
    id: "http.request",
    name: "HTTP",
    ports: [port("in", "input", null), port("out", "output", null)],
  }),
];

function step(id: string, layout: NodeInstance["layout"]): NodeInstance {
  return { id, definition_id: "http.request", definition_version: 1, config: {}, layout };
}

async function openMenu(nodeId: string) {
  render(
    <ContextMenu>
      <ContextMenuTrigger>
        <span>card</span>
      </ContextMenuTrigger>
      <CanvasContextMenu nodeId={nodeId} catalog={CATALOG} />
    </ContextMenu>,
  );
  fireEvent.contextMenu(screen.getByText("card"));
  await screen.findByText("Open settings");
}

beforeEach(() => {
  store.getState().teardown();
  store.getState().seedGraph({
    entry_node_id: "a",
    nodes: [
      step("a", { x: 0, y: 0, width: 320, height: 180 }),
      step("b", { x: 0, y: 0 }),
      step("c", { x: 0, y: 0, height: 150 }),
    ],
    edges: [],
    bindings: [],
    scopes: [],
  });
});

afterEach(cleanup);

describe("a step's right-click menu", () => {
  it("puts a resized step back to its default size, leaving where it stands", async () => {
    await openMenu("a");

    await userEvent.click(screen.getByText("Reset size"));

    expect(store.getState().graph?.nodes[0]?.layout).toEqual({ x: 0, y: 0 });
  });

  it("offers it for a step resized in one direction only", async () => {
    await openMenu("c");
    expect(screen.getByText("Reset size")).toBeInTheDocument();
  });

  it("does not offer it for a step that was never resized", async () => {
    await openMenu("b");
    expect(screen.queryByText("Reset size")).not.toBeInTheDocument();
  });
});
