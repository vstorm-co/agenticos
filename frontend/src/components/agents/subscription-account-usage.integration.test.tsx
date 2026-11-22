import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SubscriptionAccountUsage } from "./subscription-account-usage";
import { apiClient } from "@/lib/api-client";
import type { SubscriptionAccount, SubscriptionUsage } from "@/lib/subscription-accounts-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
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
const account: SubscriptionAccount = {
  name: "a.json",
  provider: "antigravity",
  label: null,
  email: null,
  status: "active",
  disabled: false,
  unavailable: false,
};
let fail = false;
let usage: SubscriptionUsage;
function mount(own = account) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubscriptionAccountUsage account={own} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  fail = false;
  usage = {
    status: "available",
    observed_at: null,
    windows: [
      {
        kind: "provider",
        label: "Gemini · Weekly",
        duration_minutes: 10080,
        remaining_percent: 39,
        resets_at: null,
      },
      {
        kind: "provider",
        label: "Claude · 5-hour",
        duration_minutes: 300,
        remaining_percent: 50,
        resets_at: null,
      },
    ],
  };
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (!path.endsWith("/usage")) return { enabled: true, items: [account] };
    if (fail) throw new Error("offline");
    return usage;
  });
});
it("shows separate model-group windows with progress bars and refreshes this account only", async () => {
  mount();
  expect(await screen.findByText("Gemini · Weekly")).toBeInTheDocument();
  expect(screen.getByText("Claude · 5-hour")).toBeInTheDocument();
  expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  expect(screen.getByText("39% left")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Refresh limits" }));
  expect(apiClient.get).toHaveBeenLastCalledWith("/subscription-accounts/a.json/usage");
});
it("reports failed reads and lets the person retry without a fabricated allowance", async () => {
  fail = true;
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not update limits");
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Refresh limits" }));
  expect(await screen.findByText("39% left")).toBeInTheDocument();
});
it("distinguishes unavailable provider data and disabled accounts", async () => {
  usage = { status: "unavailable", observed_at: null, windows: [] };
  const view = mount();
  expect(await screen.findByText(/has not reported usage/)).toBeInTheDocument();
  view.unmount();
  vi.clearAllMocks();
  mount({ ...account, disabled: true });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Refresh limits" })).toBeDisabled(),
  );
  expect(apiClient.get).not.toHaveBeenCalledWith("/subscription-accounts/a.json/usage");
});

it.each(["claude", "anthropic"])(
  "renders the Claude usage read for %s credentials",
  async (provider) => {
    mount({ ...account, provider });
    expect(await screen.findByText("39% left")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/a.json/usage");
  },
);
