import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { qk } from "@/lib/query-keys";
import { WorkflowConnectionsDialog } from "./workflow-connections-dialog";

vi.mock("@/components/mcp/mcp-server-list", () => ({
  McpServerList: ({
    initialServerKey,
    persistSelection,
  }: {
    initialServerKey?: string;
    persistSelection?: boolean;
  }) => (
    <p>
      {initialServerKey} · {persistSelection ? "bookmark" : "keep workflow URL"}
    </p>
  ),
}));

it("opens the requested service and refreshes workflow account choices on returning", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const close = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <WorkflowConnectionsDialog open catalogKey="google-workspace" onOpenChange={close} />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("google-workspace · keep workflow URL")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpConnections.all() });
  expect(close).toHaveBeenCalledWith(false);
});

it("refreshes the account choices when the dialog is dismissed with Escape", async () => {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const close = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <WorkflowConnectionsDialog open onOpenChange={close} />
    </QueryClientProvider>,
  );
  await screen.findByRole("dialog");

  await userEvent.keyboard("{Escape}");

  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpConnections.all() });
  expect(close).toHaveBeenCalledWith(false);
});
