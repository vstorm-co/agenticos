import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { McpToolPickerDialog } from "./mcp-tool-picker-dialog";
import type { ToolPickerState } from "./mcp-server-list-types";
import type { McpConnectionRecord } from "@/lib/mcp-connections-api";

const CONNECTION = { id: "c1", name: "notion" } as McpConnectionRecord;

const TOOLS = [
  { name: "notion-search", description: "Search the workspace and connected sources." },
  { name: "notion-fetch", description: "Retrieve a page by URL or ID." },
  { name: "notion-create-file-upload", description: "Create a short-lived upload URL." },
];

/**
 * The dialog drives its own state through the caller, so the harness holds it -
 * asserting on a controlled component with a frozen prop would test nothing
 * about what a click does.
 */
function Harness({ checked, onSave = vi.fn() }: { checked?: string[]; onSave?: () => void }) {
  const [state, setState] = useState<ToolPickerState | null>({
    scope: "organization",
    connection: CONNECTION,
    tools: TOOLS,
    checked: new Set(checked ?? TOOLS.map((tool) => tool.name)),
  });
  return (
    <McpToolPickerDialog
      toolPicker={state}
      setToolPicker={setState}
      submitting={false}
      onSave={onSave}
    />
  );
}

const list = () => within(screen.getByRole("dialog")).queryAllByRole("checkbox");

/**
 * Which of a server's tools it exposes.
 *
 * Notion offers twenty-five and the list was the whole dialog with no way to
 * find one, no count and no way to act on more than one at a time - so the only
 * thing a person is deciding here was the one thing the dialog would not say.
 */
describe("McpToolPickerDialog", () => {
  it("says how many of how many are on", () => {
    render(<Harness checked={["notion-search"]} />);

    expect(screen.getByRole("status")).toHaveTextContent("1 of 3 on");
  });

  it("narrows on a description, not only on a name", async () => {
    // Somebody looking for "upload" does not know the tool is called
    // `notion-create-file-upload`.
    render(<Harness />);

    await userEvent.type(screen.getByLabelText("Search tools…"), "short-lived");

    expect(list()).toHaveLength(1);
    expect(screen.getByText("notion-create-file-upload")).toBeVisible();
  });

  it("says so when a search matches nothing", async () => {
    render(<Harness />);

    await userEvent.type(screen.getByLabelText("Search tools…"), "zzz");

    expect(screen.getByText("No tool matches that.")).toBeVisible();
    expect(list()).toHaveLength(0);
  });

  it("turns every tool on at once", async () => {
    render(<Harness checked={[]} />);

    await userEvent.click(screen.getByRole("button", { name: "Select all" }));

    expect(screen.getByRole("status")).toHaveTextContent("3 of 3 on");
  });

  it("turns them all off again", async () => {
    render(<Harness />);

    await userEvent.click(screen.getByRole("button", { name: "Select none" }));

    expect(screen.getByRole("status")).toHaveTextContent("0 of 3 on");
  });

  it("acts on what the search narrowed to, not on the catalogue", async () => {
    // The reason to search first is to act on the result. Selecting none over
    // the whole list would throw away the twenty the reader was not looking at.
    render(<Harness />);
    await userEvent.type(screen.getByLabelText("Search tools…"), "fetch");

    await userEvent.click(screen.getByRole("button", { name: "Select none" }));

    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 on");
  });

  it("toggles one from anywhere on its row", async () => {
    // Twenty-five small targets at the right edge is a lot of travel to switch
    // six things off.
    render(<Harness />);

    await userEvent.click(screen.getByText("Search the workspace and connected sources."));

    expect(screen.getByRole("status")).toHaveTextContent("2 of 3 on");
  });

  it("refuses to save a selection of nothing", async () => {
    render(<Harness checked={[]} />);

    expect(screen.getByRole("button", { name: "Save selection" })).toBeDisabled();
  });

  it("saves what is checked", async () => {
    const onSave = vi.fn();
    render(<Harness onSave={onSave} />);

    await userEvent.click(screen.getByRole("button", { name: "Save selection" }));

    expect(onSave).toHaveBeenCalled();
  });
});
