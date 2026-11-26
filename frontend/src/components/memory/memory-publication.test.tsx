import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
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
