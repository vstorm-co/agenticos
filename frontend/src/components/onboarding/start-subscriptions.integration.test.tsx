import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartSubscriptions } from "./start-subscriptions";
import { apiClient } from "@/lib/api-client";
import type { SubscriptionAccount } from "@/lib/subscription-accounts-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => "org",
  useTenantGuard: () => () => true,
}));
vi.mock("@/stores", () => {
  const state = { user: { id: "person" } };
  return {
    useAuthStore: Object.assign(
      (selector: (state: { user: { id: string } }) => unknown) => selector(state),
      { getState: () => state },
    ),
  };
});
let enabled = true;
let items: SubscriptionAccount[] = [];
let failed = false;
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <StartSubscriptions />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  enabled = true;
  items = [];
  failed = false;
  vi.mocked(apiClient.get).mockImplementation(async () => {
    if (failed) throw new Error("offline");
    return { enabled, items };
  });
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://example.com/login",
    state: "test",
    flow: "device",
    user_code: "PLAN-CODE",
  });
});
it("lets a person select plans and sign in immediately without a shared API key", async () => {
  mount();
  const claude = screen.getByRole("checkbox", { name: "Claude Code (Pro, Max)" });
  await waitFor(() => expect(claude).not.toBeDisabled());
  await userEvent.click(claude);
  await userEvent.click(screen.getByRole("checkbox", { name: "ChatGPT (Codex)" }));
  await userEvent.click(screen.getByRole("checkbox", { name: "ChatGPT (Codex)" }));
  expect(screen.getAllByRole("button", { name: "Connect" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "Connect" }));
  expect(await screen.findByText("PLAN-CODE")).toBeInTheDocument();
  expect(apiClient.post).toHaveBeenCalledWith("/subscription-accounts/sign-ins", {
    provider: "claude",
  });
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
it("marks already connected plans and offers reconnection for unavailable accounts", async () => {
  items = [
    {
      name: "mine.json",
      provider: "codex",
      email: null,
      label: null,
      status: "active",
      disabled: false,
      unavailable: false,
    },
    {
      name: "old.json",
      provider: "claude",
      email: null,
      label: null,
      status: null,
      disabled: false,
      unavailable: true,
    },
  ];
  mount();
  expect(await screen.findByText("Connected")).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "ChatGPT (Codex)" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "ChatGPT (Codex)" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: "Claude Code (Pro, Max)" })).not.toBeChecked();
});
it("stays absent on deployments without subscription support", async () => {
  enabled = false;
  mount();
  await waitFor(() => expect(screen.queryByRole("heading")).not.toBeInTheDocument());
});
it("shows a read failure and retries instead of calling connected accounts empty", async () => {
  failed = true;
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(apiClient.get).toHaveBeenCalledTimes(2);
});
