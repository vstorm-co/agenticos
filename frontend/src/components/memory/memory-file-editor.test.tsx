import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MemoryFileEditor } from "./memory-file-editor";
import type { MemoryFile } from "@/types/memory";

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

const FILE: MemoryFile = {
  id: "f1",
  agent_id: "a1",
  name: "user-preferences",
  description: "tone",
  content: "Prefer bullet points.",
  format: "md",
  kind: "note",
  origin: "operator",
  owner_key: null,
  created_at: null,
  updated_at: null,
};

function mount(props: Partial<React.ComponentProps<typeof MemoryFileEditor>> = {}) {
  const onSave = vi.fn();
  const onPromote = vi.fn();
  const onCancel = vi.fn();
  render(
    <MemoryFileEditor
      file={FILE}
      canEdit
      isSaving={false}
      isPromoting={false}
      onSave={onSave}
      onPromote={onPromote}
      onCancel={onCancel}
      {...props}
    />,
  );
  return { onSave, onPromote, onCancel };
}

const save = () => screen.getByRole("button", { name: "Save" });

describe("MemoryFileEditor", () => {
  it("shows the origin and owner as read-only facts", () => {
    mount();
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Organisation")).toBeInTheDocument();
  });

  it("saves the whole editable set, so an untouched field is not lost", async () => {
    const { onSave } = mount();

    await userEvent.type(screen.getByLabelText("Description"), " and formats");
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith({
      description: "tone and formats",
      content: "Prefer bullet points.",
      format: "md",
      kind: "note",
    });
  });

  it("refuses a save that would write nothing", () => {
    mount();
    expect(save()).toBeDisabled();
  });

  it("sends an emptied description as null", async () => {
    const { onSave } = mount();

    await userEvent.clear(screen.getByLabelText("Description"));
    // Change kind too so the save is enabled without a description.
    await userEvent.type(screen.getByLabelText("Kind"), "s");
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ description: null }));
  });

  it("takes the format from a closed list", async () => {
    const { onSave } = mount();

    await userEvent.click(screen.getByLabelText("Format"));
    await userEvent.click(await screen.findByRole("option", { name: "txt" }));
    await userEvent.click(save());

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ format: "txt" }));
  });

  it("keeps a stored format the catalog does not list rather than showing none", () => {
    mount({ file: { ...FILE, format: "html" } });
    expect(screen.getByLabelText("Format")).toHaveTextContent("html");
    expect(save()).toBeDisabled();
  });

  it("does not offer to promote a file that is already trusted", () => {
    mount();
    expect(screen.queryByRole("button", { name: "Promote to trusted" })).not.toBeInTheDocument();
  });

  it("offers to promote an agent-authored file, and asks the caller to do it", async () => {
    const { onPromote } = mount({ file: { ...FILE, origin: "agent" } });

    await userEvent.click(screen.getByRole("button", { name: "Promote to trusted" }));

    expect(onPromote).toHaveBeenCalled();
  });

  it("gives a viewer a way out and nothing to write with", () => {
    mount({ canEdit: false, file: { ...FILE, origin: "agent" } });

    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    // The promote alert still explains the file, but a viewer cannot act on it.
    expect(screen.queryByRole("button", { name: "Promote to trusted" })).not.toBeInTheDocument();
  });

  it("cancels without saving", async () => {
    const { onCancel, onSave } = mount();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
