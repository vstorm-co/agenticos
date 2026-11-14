import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { NoteDetail } from "./note-detail";
import { saveBlob } from "@/lib/file-access";
import type { MemoryNote } from "@/lib/memory-api";
vi.mock("@/lib/file-access", async (original) => ({
  ...(await original<typeof import("@/lib/file-access")>()),
  saveBlob: vi.fn(),
}));
const note: MemoryNote = {
  id: "note",
  agent_id: "agent",
  agent_name: "Assistant",
  name: "checklist.md",
  content: "Zażółć — checklist",
  description: null,
  format: "md",
  kind: "note",
  created_at: "2026-11-06T00:00:00Z",
  updated_at: null,
  written_at: null,
  deactivated_at: null,
};
it("exports the current note as UTF-8 without a separate metadata tab", async () => {
  render(
    <NoteDetail
      note={note}
      onClose={vi.fn()}
      setActive={vi.fn()}
      remove={vi.fn()}
      update={vi.fn()}
    />,
  );
  expect(screen.queryByRole("tab", { name: "Memory details" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  const [blob, name] = vi.mocked(saveBlob).mock.calls[0]!;
  expect(name).toBe("checklist.md");
  expect(await blob.text()).toBe(note.content);
});
it("keeps a refused correction open and saves against the original revision", async () => {
  const close = vi.fn();
  const update = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
  const view = render(
    <NoteDetail note={note} onClose={close} setActive={vi.fn()} remove={vi.fn()} update={update} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Source" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Note content" }), {
    target: { value: "Corrected" },
  });
  view.rerender(
    <NoteDetail
      note={{ ...note, updated_at: "2026-11-14T00:00:00Z" }}
      onClose={close}
      setActive={vi.fn()}
      remove={vi.fn()}
      update={update}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(update).toHaveBeenCalledWith(note, "Corrected");
  expect(close).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
});
