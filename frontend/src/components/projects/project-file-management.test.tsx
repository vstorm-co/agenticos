import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ProjectEntryActions } from "./project-entry-actions";
import { ProjectFileEditor } from "./project-file-editor";
import * as api from "@/lib/projects-api";

vi.mock("@/lib/projects-api", () => ({
  readEditableProjectFile: vi.fn(),
  saveProjectFile: vi.fn(),
}));
function wrap(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.readEditableProjectFile).mockResolvedValue({
    content: "# Notes\n",
    revision: "a".repeat(64),
  });
  vi.mocked(api.saveProjectFile).mockImplementation(async (_id, _path, file) => ({
    ...file,
    revision: "b".repeat(64),
  }));
});
describe("project entry actions", () => {
  async function open(mode: string, move = vi.fn().mockResolvedValue(undefined)) {
    render(
      <ProjectEntryActions
        path="notes"
        folders={["notes", "notes/child", "archive"]}
        onMove={move}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Actions for notes" }));
    await userEvent.click(screen.getByRole("menuitem", { name: mode }));
    return move;
  }
  it("renames a folder without allowing separators or an unchanged name", async () => {
    const move = await open("Rename");
    const input = screen.getByRole("textbox", { name: "Name" });
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "../bad");
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "Research");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(move).toHaveBeenCalledWith("notes", "Research"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("offers folders without itself or its descendants", async () => {
    const move = await open("Move to folder");
    await userEvent.click(screen.getByRole("combobox"));
    expect(screen.queryByRole("option", { name: "notes" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "notes/child" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "archive" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(move).toHaveBeenCalledWith("notes", "archive/notes"));
  });
  it("keeps a failed move open and can cancel it", async () => {
    await open("Rename", vi.fn().mockRejectedValue(new Error("collision")));
    await userEvent.type(screen.getByRole("textbox"), "2");
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be moved");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
describe("project text editor", () => {
  async function open() {
    wrap(<ProjectFileEditor projectId="p-1" path="notes.md" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit file" }));
    return screen.findByRole("textbox", { name: "File contents" });
  }
  it("saves the complete text and its opening revision, then refreshes the preview", async () => {
    const editor = await open();
    await userEvent.clear(editor);
    await userEvent.type(editor, "  Changed\n");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(api.saveProjectFile).toHaveBeenCalledWith("p-1", "notes.md", {
        content: "  Changed\n",
        revision: "a".repeat(64),
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled(),
    );
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("warns before closing a dirty file and preserves it when discard is cancelled", async () => {
    const editor = await open();
    await userEvent.type(editor, " changed");
    const event = new Event("beforeunload", { cancelable: true });
    fireEvent(window, event);
    expect(event.defaultPrevented).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Discard changes?" })).toHaveTextContent(
      "Discard changes?",
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(editor).toHaveValue("# Notes\n changed");
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.saveProjectFile).not.toHaveBeenCalled();
  });
  it("keeps the draft on a save failure", async () => {
    vi.mocked(api.saveProjectFile).mockRejectedValue(new Error("unavailable"));
    const editor = await open();
    await userEvent.type(editor, " changed");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(editor).toHaveValue("# Notes\n changed");
  });
  it("shows a failed read without offering to overwrite anything", async () => {
    vi.mocked(api.readEditableProjectFile).mockRejectedValue(new Error("binary"));
    wrap(<ProjectFileEditor projectId="p-1" path="notes.md" />);
    await userEvent.click(screen.getByRole("button", { name: "Edit file" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});

it("can dismiss a rename with Escape", async () => {
  render(<ProjectEntryActions path="notes" folders={[]} onMove={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Actions for notes" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("does not close a file while its save is in flight", async () => {
  let finish: (file: api.EditableProjectFile) => void = () => {
    throw new Error("Save not started");
  };
  vi.mocked(api.saveProjectFile).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  wrap(<ProjectFileEditor projectId="p-1" path="notes.md" />);
  await userEvent.click(screen.getByRole("button", { name: "Edit file" }));
  await userEvent.type(await screen.findByRole("textbox", { name: "File contents" }), " new");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await userEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!);
  expect(screen.getByRole("dialog", { name: "Edit file" })).toBeInTheDocument();
  await act(async () => finish({ content: "# Notes\n new", revision: "b".repeat(64) }));
  await userEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
