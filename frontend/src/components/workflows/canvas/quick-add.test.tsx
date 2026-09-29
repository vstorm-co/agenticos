import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { NodeDefinition, Port } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { QuickAdd } from "./quick-add";

function def(id: string, name: string, ports: Port["kind"][], description = ""): NodeDefinition {
  return {
    id,
    version: 1,
    name,
    category: "data",
    description,
    kind: "action",
    config_schema: null,
    input_schema: null,
    output_schema: null,
    ports: ports.map((kind, index) => ({ id: `p${index}`, label: kind, kind, schema: null })),
    effect_kind: "pure",
    retry_guarantee: "none",
    scopes: [],
  };
}

const NOTIFY = def("notification.send", "Notify members", ["input", "output"], "Tell someone");
const DOWNLOAD = def("http.download", "Download a file", ["input", "output"], "Fetch over HTTP");
const START = def("core.input", "Input", ["output"]);
const ITEM = { ...def("loop.item", "Loop item", ["input", "output"]), loop_body_only: true };

beforeEach(() => useWorkflowEditorStore.setState({ scopePath: [] }));

describe("QuickAdd", () => {
  it("offers the steps that can follow, finds one by a plain match, and adds it", async () => {
    const onPick = vi.fn();
    render(
      <QuickAdd
        catalog={[NOTIFY, DOWNLOAD, START, ITEM]}
        nodeName="Search"
        portLabel="Out"
        onPick={onPick}
        prominent
      />,
    );
    const trigger = screen.getByRole("button", { name: "Add a step after Search (Out)" });
    expect(trigger.className).toContain("opacity-100");

    await userEvent.click(trigger);
    // A starting step cannot follow another, and a loop's own item only lives in a body.
    expect(screen.queryByText("Input")).toBeNull();
    expect(screen.queryByText("Loop item")).toBeNull();
    expect(screen.getByText("Download a file")).toBeTruthy();

    await userEvent.type(screen.getByPlaceholderText("Search steps"), "notif");
    expect(screen.queryByText("Download a file")).toBeNull();
    await userEvent.click(screen.getByText("Notify members"));

    expect(onPick).toHaveBeenCalledWith(NOTIFY);
    await waitFor(() => expect(screen.queryByPlaceholderText("Search steps")).toBeNull());
  });

  it("stays out of the way on a port already wired, and says when nothing matches", async () => {
    render(
      <QuickAdd
        catalog={[NOTIFY]}
        nodeName="Search"
        portLabel="Out"
        onPick={vi.fn()}
        prominent={false}
      />,
    );
    const trigger = screen.getByRole("button", { name: "Add a step after Search (Out)" });
    expect(trigger.className).toContain("opacity-0");

    await userEvent.click(trigger);
    await userEvent.type(screen.getByPlaceholderText("Search steps"), "zzz");
    expect(screen.getByText("No nodes match your search.")).toBeTruthy();
  });
});
