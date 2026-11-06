import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { RememberedApprovals } from "./remembered-approvals";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), delete: vi.fn() } }));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (pick: (s: { user: { id: string } }) => unknown) =>
    pick({ user: { id: "person" } }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (pick: (s: { activeOrgId: string }) => unknown) => pick({ activeOrgId: "org" }),
}));

const choice = {
  id: "choice",
  agent_id: "agent",
  agent_name: "AgenticOS",
  tool_id: "agenticos_upsert_virtual_table_record",
  account: null,
  remember_scope: "conversation",
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <RememberedApprovals />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue([choice]);
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});
it("lists remembered choices and lets the person ask again without changing approval history", async () => {
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Ask again" }));
  await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/approvals/choice/consent"));
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
});
it("surfaces a withdrawal error rather than pretending the tool will ask again", async () => {
  vi.mocked(apiClient.delete).mockRejectedValue(new Error("Offline"));
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Ask again" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not forget");
});
it("shows a quiet empty state and can retry a failed read", async () => {
  vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Offline")).mockResolvedValue([]);
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No remembered approvals.")).toBeVisible();
});
it("labels an agent-wide choice with its account", async () => {
  vi.mocked(apiClient.get).mockResolvedValue([
    { ...choice, remember_scope: "agent", account: "Work" },
  ]);
  mount();
  expect(await screen.findByText("Always allow this tool for this agent · Work")).toBeVisible();
});
