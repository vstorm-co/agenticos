import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { CodingTaskChanges } from "@/lib/coding-changes-api";
import { qk } from "@/lib/query-keys";
import { TaskChanges } from "./coding-changes";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

const changes: CodingTaskChanges = {
  id: "change-1",
  conversation_id: "chat-1",
  harness: "codex",
  files: [
    {
      path: "app.py",
      old_path: null,
      status: "modified",
      additions: 1,
      deletions: 1,
      binary: false,
      patch: "@@ -1 +1 @@\n-a\n+b\n",
      truncated: false,
    },
  ],
  omitted: 0,
  truncated: false,
  created_at: "2026-11-13T00:00:00Z",
  can_revert: true,
  reverted_at: null,
};

function show(
  value: CodingTaskChanges = changes,
  conversationId: string | null = changes.conversation_id,
) {
  vi.mocked(apiClient.get).mockResolvedValue(value);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: 3, retryDelay: 0 } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <TaskChanges changeId={value.id} conversationId={conversationId ?? undefined} />
    </QueryClientProvider>,
  );
  return { client, invalidate };
}

beforeEach(() => vi.clearAllMocks());

it("hides revert for a reader without workspace edit access", async () => {
  show({ ...changes, can_revert: false });
  expect(await screen.findByText("Changed 1 file")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Revert this task" })).toBeNull();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it.each(["a-fork", null])(
  "keeps a copied task report read-only when its conversation origin is %s",
  async (conversationId) => {
    show(changes, conversationId);
    expect(await screen.findByText("Changed 1 file")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Revert this task" })).toBeNull();
    expect(apiClient.post).not.toHaveBeenCalled();
  },
);

it("confirms the action, restores once, records the result and refreshes workspace files", async () => {
  const user = userEvent.setup();
  const restored = { ...changes, can_revert: false, reverted_at: "2026-11-13T01:00:00Z" };
  vi.mocked(apiClient.post).mockResolvedValue(restored);
  const { client, invalidate } = show();
  await user.click(await screen.findByRole("button", { name: "Revert this task" }));
  expect(apiClient.post).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(apiClient.post).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Revert this task" }));
  const buttons = screen.getAllByRole("button", { name: "Revert this task" });
  await user.click(buttons.at(-1)!);
  expect(await screen.findByText("This task was reverted.")).toBeVisible();
  expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
    "/conversations/coding-changes/change-1/revert",
  );
  expect(client.getQueryData(qk.codingChanges.detail(changes.id))).toEqual(restored);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.conversationWorkspace.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.sandboxWorkspaces.all() });
});

it("shows conflicting files and keeps the original diff when revert is refused", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post).mockRejectedValue(
    new ApiError(409, "conflict", {
      error: {
        code: "ALREADY_EXISTS",
        message: "conflict",
        details: { conflicting_files: ["src/later.py", 42] },
      },
    }),
  );
  show();
  await user.click(await screen.findByRole("button", { name: "Revert this task" }));
  await user.click(screen.getAllByRole("button", { name: "Revert this task" }).at(-1)!);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "These files changed after the task. Nothing was reverted.",
  );
  expect(screen.getByRole("alert")).toHaveTextContent("src/later.py");
  expect(screen.queryByText("This task was reverted.")).toBeNull();
  await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
});

it("reports a connection failure and permits a deliberate retry", async () => {
  const user = userEvent.setup();
  vi.mocked(apiClient.post)
    .mockRejectedValueOnce(new TypeError("connection lost"))
    .mockResolvedValueOnce({ ...changes, can_revert: false, reverted_at: "2026-11-13T01:00:00Z" });
  show();
  await user.click(await screen.findByRole("button", { name: "Revert this task" }));
  await user.click(screen.getAllByRole("button", { name: "Revert this task" }).at(-1)!);
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(apiClient.post).toHaveBeenCalledTimes(1);
  await user.click(screen.getAllByRole("button", { name: "Revert this task" }).at(-1)!);
  expect(await screen.findByText("This task was reverted.")).toBeVisible();
  expect(apiClient.post).toHaveBeenCalledTimes(2);
});
