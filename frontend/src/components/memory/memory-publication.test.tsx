import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { toast } from "sonner";
import { apiClient } from "@/lib/api-client";
import type { MemoryClaim, MemoryNote } from "@/lib/memory-api";
import { ClaimDetail } from "./claim-detail";
import { NoteDetail } from "./note-detail";
import { MemoryPublication } from "./memory-publication";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: () => "26 Nov 2026" }),
}));
vi.mock("@/hooks/use-groups", () => ({
  useGroups: () => ({ groups: [{ id: "legal", name: "Legal" }] }),
}));

it("requires a reviewed audience and keeps a failed publication available to retry", async () => {
  const publish = vi
    .fn()
    .mockRejectedValueOnce(new Error("Unavailable"))
    .mockResolvedValue(undefined);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryPublication publish={publish} />
    </QueryClientProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "share" }));
  const confirm = screen.getByRole("button", { name: "confirmShare" });
  expect(confirm).toBeDisabled();
  await user.click(screen.getByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: "Legal" }));
  await user.click(confirm);
  expect(await screen.findByRole("alert")).toHaveTextContent("shareFailure");
  expect(publish).toHaveBeenLastCalledWith("legal");
  await user.click(screen.getByRole("combobox"));
  await user.click(await screen.findByRole("option", { name: "wholeOrganization" }));
  await user.click(confirm);
  expect(await screen.findByText("published")).toBeVisible();
  expect(publish).toHaveBeenLastCalledWith(null);
  await user.click(screen.getByText("close", { selector: "button" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  await user.click(screen.getByRole("button", { name: "share" }));
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
});

const claim: MemoryClaim = {
  id: "claim",
  statement: "Deadline for Atlas",
  subject: "deadline",
  kind: "fact",
  scope: "profile",
  agent_id: null,
  agent_name: null,
  origin: "person",
  status: "current",
  observed_at: "2026-11-26T00:00:00Z",
  effective_from: null,
  effective_to: null,
  supersedes_id: null,
  derived_from_count: 0,
};
const note: MemoryNote = {
  id: "note",
  name: "Plan",
  content: "Reviewed text",
  kind: "note",
  format: "md",
  agent_id: "agent",
  agent_name: null,
  description: null,
  created_at: null,
  updated_at: "2026-11-26T00:00:00Z",
  written_at: null,
  deactivated_at: null,
};

it.each(["note", "claim"] as const)(
  "publishes the selected %s to the chosen audience",
  async (kind) => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({});
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({
      ...claim,
      evidence: [],
      sources: [],
      superseded: null,
      withheld: 0,
      conflicts: [],
    });
    const noop = vi.fn();
    try {
      render(
        <QueryClientProvider client={new QueryClient()}>
          {kind === "claim" ? (
            <ClaimDetail canShare claim={claim} onClose={noop} correct={noop} retract={noop} />
          ) : (
            <NoteDetail
              canShare
              note={note}
              onClose={noop}
              update={noop}
              setActive={noop}
              remove={noop}
            />
          )}
        </QueryClientProvider>,
      );
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "share" }));
      await user.click(screen.getByRole("combobox"));
      await user.click(await screen.findByRole("option", { name: "Legal" }));
      await user.click(screen.getByRole("button", { name: "confirmShare" }));
      expect(await screen.findByText("published")).toBeVisible();
      expect(post).toHaveBeenCalledWith(
        kind === "claim" ? "/memory/claims/mine/claim/share" : "/memory/mine/note/share",
        {
          confirmed: true,
          group_id: "legal",
          ...(kind === "note" ? { expected_updated_at: note.updated_at } : {}),
        },
      );
    } finally {
      post.mockRestore();
      get.mockRestore();
    }
  },
);

it("opts a note into updates and restores a previous body using the new revision", async () => {
  const updatedAt = "2026-11-27T00:00:00Z";
  const sharedContext = Array.from({ length: 16 }, (_, index) => `Plan item ${index + 1}`).join(
    "\n",
  );
  const currentNote = { ...note, content: `${sharedContext}\nThe current note body` };
  const patch = vi.spyOn(apiClient, "patch").mockResolvedValue({
    ...currentNote,
    updated_at: updatedAt,
    auto_update: true,
  });
  const get = vi.spyOn(apiClient, "get").mockResolvedValue({
    items: [
      {
        id: "revision",
        content: `${sharedContext}\nThe earlier note body`,
        source_conversation_id: "source-1",
        replaced_at: updatedAt,
        changed_by: "maintenance",
      },
    ],
    total: 1,
  });
  const post = vi.spyOn(apiClient, "post").mockResolvedValue(note);
  const close = vi.fn();
  const noop = vi.fn();
  try {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NoteDetail
          note={currentNote}
          onClose={close}
          update={noop}
          setActive={noop}
          remove={noop}
        />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    expect(get).not.toHaveBeenCalled();
    const automatic = screen.getByRole("button", { name: "noteAutoUpdate" });
    await user.click(automatic);
    expect(patch).toHaveBeenCalledWith("/memory/mine/note/auto-update", {
      enabled: true,
      expected_updated_at: note.updated_at,
    });
    expect(
      await screen.findByRole("button", { name: "noteAutoUpdate", pressed: true }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "noteHistory" }));
    await user.click(await screen.findByText("noteRevisionLabel"));
    expect(screen.getByText("The earlier note body")).toBeVisible();
    expect(screen.getByText("stepApprovalUnchangedLines")).toBeVisible();
    expect(screen.getByRole("link", { name: "noteRevisionSource" })).toHaveAttribute(
      "href",
      "/chat/source-1",
    );
    await user.click(screen.getByRole("button", { name: "noteRestoreVersion" }));
    expect(post).toHaveBeenCalledWith("/memory/mine/note/revisions/revision/restore", {
      expected_updated_at: updatedAt,
    });
  } finally {
    patch.mockRestore();
    get.mockRestore();
    post.mockRestore();
  }
});

it("pages through note history before restoring", async () => {
  const stamp = "2026-11-27T00:00:00Z";
  const get = vi.spyOn(apiClient, "get").mockImplementation(async (path) => ({
    items: [
      {
        id: path.endsWith("skip=5") ? "older" : "newer",
        content: path.endsWith("skip=5") ? "Older body" : "Newer body",
        replaced_at: stamp,
        changed_by: "agent",
      },
    ],
    total: 6,
  }));
  const noop = vi.fn();
  try {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NoteDetail note={note} onClose={noop} update={noop} setActive={noop} remove={noop} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "noteHistory" }));
    await user.click(await screen.findByRole("button", { name: "noteOlderVersions" }));
    expect(get).toHaveBeenCalledWith("/memory/mine/note/revisions?skip=5");
    await user.click(screen.getByRole("button", { name: "noteNewerVersions" }));
    expect(await screen.findByRole("button", { name: "noteOlderVersions" })).toBeVisible();
  } finally {
    get.mockRestore();
  }
});

it("reports refused note consent and restore without leaving the note", async () => {
  const patch = vi.spyOn(apiClient, "patch").mockRejectedValue(new Error("stale consent"));
  const post = vi.spyOn(apiClient, "post").mockRejectedValue(new Error("stale restore"));
  const get = vi.spyOn(apiClient, "get").mockResolvedValue({
    items: [
      {
        id: "older",
        content: "Older note",
        replaced_at: "2026-11-27T00:00:00Z",
        changed_by: "person",
      },
    ],
    total: 1,
  });
  const error = vi.spyOn(toast, "error").mockImplementation(() => "reported");
  const close = vi.fn();
  const noop = vi.fn();
  try {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <NoteDetail note={note} onClose={close} update={noop} setActive={noop} remove={noop} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    const automatic = screen.getByRole("button", { name: "noteAutoUpdate", pressed: false });
    await user.click(automatic);
    await waitFor(() => expect(error).toHaveBeenCalledTimes(1));
    expect(automatic).toHaveAttribute("aria-pressed", "false");
    await user.click(screen.getByRole("button", { name: "noteHistory" }));
    await user.click(await screen.findByText("noteRevisionLabel"));
    await user.click(screen.getByRole("button", { name: "noteRestoreVersion" }));
    await waitFor(() => expect(error).toHaveBeenCalledTimes(2));
    expect(close).not.toHaveBeenCalled();
  } finally {
    patch.mockRestore();
    post.mockRestore();
    get.mockRestore();
    error.mockRestore();
  }
});
