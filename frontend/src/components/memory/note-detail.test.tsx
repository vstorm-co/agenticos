import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it, vi } from "vitest";
import { NoteDetail } from "./note-detail";
import { saveBlob, type FileAccess } from "@/lib/file-access";
vi.mock("@/lib/file-access", async (original) => ({
  ...(await original<typeof import("@/lib/file-access")>()),
  saveBlob: vi.fn(),
}));
vi.mock("@/components/files", () => ({
  FileViewer: ({ access }: { access: FileAccess }) => {
    const [bytes, setBytes] = useState("");
    return (
      <>
        <button
          onClick={async () => {
            setBytes(await (await access.readBytes()).text());
          }}
        >
          Read note bytes
        </button>
        <button onClick={() => access.download()}>Download note</button>
        <output>{bytes}</output>
      </>
    );
  },
}));
it("exports exactly the selected note as UTF-8 bytes with its original filename", async () => {
  render(
    <NoteDetail
      note={{
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
      }}
      onClose={vi.fn()}
      setActive={vi.fn()}
      remove={vi.fn()}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Read note bytes" }));
  expect(await screen.findByText("Zażółć — checklist")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Download note" }));
  await waitFor(() => expect(saveBlob).toHaveBeenCalled());
  const [blob, name] = vi.mocked(saveBlob).mock.calls[0]!;
  expect(name).toBe("checklist.md");
  expect(await blob.text()).toBe("Zażółć — checklist");
});
